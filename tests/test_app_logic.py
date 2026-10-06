"""Tests for the data layer (outcomes_data.py) and chart builders (charts.py).

Run from the repository root with:  python -m pytest
Uses a small synthetic export, so the real CSV is not needed.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import charts  # noqa: E402
import outcomes_data as app  # noqa: E402

SEL = "Domain 3. Social & Emotional Learning (CASEL-aligned)"
JOY = "Domain 1. Joy, Interest & Motivation in Learning"
CONF = "3.1.4 Confidence, self-efficacy & growth mindset"
TEAM = "3.4.2 Cooperation, teamwork & collaboration"
CREATE = "1.4 Creative Expression & Making"
BELONG = "2.1 School/Program Connectedness (Belonging)"


def raw_rows():
    def row(org, program, text, domain, subcat, pop="students_youth", conf="high", filename=None):
        return {
            "organization": org, "program": program, "outcome_text_original": text,
            "primary_domain": domain, "primary_subcategory": subcat,
            "primary_target_population": pop, "primary_confidence": conf,
            "source_filename": filename or f"1_1 - {org} - {program} - Logic Model.pdf",
        }

    return pd.DataFrame([
        row("BalletX", "Dance eXchange", "Increased student confidence", SEL, CONF),
        row("BalletX", "Dance eXchange", "Students work in teams", SEL, TEAM),
        row("BalletX", "Dance eXchange", "Students create dances", JOY, CREATE),
        row("Artwell", "Poets", "Youth feel confident", SEL, CONF, conf="low"),
        row("ArtWell", "Poets", "Youth collaborate", SEL, TEAM, pop="educators_staff"),
        row("Musicopia", "Drum Line", "Students make music", JOY, CREATE),
        row(None, "Reading Buddies", "Kids feel they belong",
            "Domain 2. Belonging, Relationships & School Connectedness", BELONG,
            filename="113_13 - Historic Fair Hill, Inc. - Historic Fair Hill - Logic Model.pdf — Part 3 of 6"),
        row("HFH", "Gardens", "Uncodeable statement", None, None, pop=None, conf="none"),
    ])


@pytest.fixture
def df():
    return app.clean_outcomes(raw_rows())


def test_parse_filename_handles_multi_part_files():
    name = "113_13 - Historic Fair Hill, Inc. - Historic Fair Hill - Logic Model.pdf — Part 3 of 6"
    assert app.parse_filename(name) == ("Historic Fair Hill, Inc.", "Historic Fair Hill")
    assert app.parse_filename("not a logic model") == (None, None)
    assert app.parse_filename(None) == (None, None)


def test_clean_fills_missing_orgs_and_merges_aliases(df):
    orgs = set(df["organization"])
    assert "Historic Fair Hill, Inc." in orgs  # back-filled from the file name, and the HFH alias
    assert "HFH" not in orgs and "Artwell" not in orgs
    assert (df["organization"] == "ArtWell").sum() == 2


def test_clean_labels_missing_categories(df):
    uncoded = df[df["outcome_text_original"] == "Uncodeable statement"].iloc[0]
    assert uncoded["primary_domain"] == app.UNCODED_DOMAIN
    assert uncoded["primary_subcategory"] == app.UNASSIGNED_SUBCAT
    assert uncoded["primary_target_population"] == app.UNKNOWN_POP


def test_clean_rejects_missing_columns():
    with pytest.raises(app.MissingColumnsError):
        app.clean_outcomes(pd.DataFrame({"organization": ["x"]}))


def test_filter_outcomes_combines_filters(df):
    assert len(app.filter_outcomes(df)) == len(df)
    assert len(app.filter_outcomes(df, domains=[SEL], confidences=["high"])) == 3
    assert len(app.filter_outcomes(df, populations=[])) == len(df)  # empty list means no filter
    assert len(app.filter_outcomes(df, text_query="CONFIDEN")) == 2


def test_peer_overlap_ranks_by_shared_subcategories(df):
    peers = app.compute_peer_overlap(df, "BalletX")
    assert peers["organization"].tolist() == ["ArtWell", "Musicopia"]
    top = peers.iloc[0]
    assert top["shared_subcategories"] == 2
    assert top["coverage"] == pytest.approx(2 / 3)
    assert top["jaccard"] == pytest.approx(2 / 3)
    assert top["shared_list"] == f"{CONF}; {TEAM}"


def test_peer_overlap_ignores_unassigned_subcategory(df):
    # Historic Fair Hill shares nothing coded with anyone; its uncoded row must not count as overlap.
    assert app.compute_peer_overlap(df, "Historic Fair Hill, Inc.").empty
    assert app.compute_peer_overlap(df, "No such org").empty


def test_heatmap_matrices_align(df):
    counts, samples = app.peer_heatmap_data(df, "BalletX", ["ArtWell", "Musicopia"])
    assert counts.shape == samples.shape == (3, 3)
    assert counts.loc["Musicopia", CREATE] == 1
    assert counts.loc["Musicopia", CONF] == 0


def test_hierarchy_chart_gives_every_node_sample_text_and_exact_counts(df):
    for measure in app.MEASURES:
        for chart_type in ("Treemap", "Sunburst"):
            fig = charts.build_hierarchy_chart(df, measure, chart_type)
            trace = fig.data[0]
            assert all("(?)" not in str(c[0]) for c in trace.customdata)
            # Hover carries the full name, so key nodes by it rather than the display label.
            nodes = {c[3]: c for c in trace.customdata}
            # SEL has 4 outcomes from 2 organizations (BalletX and ArtWell each have two).
            assert list(nodes[SEL][1:3]) == [4, 2]


def test_hierarchy_chart_labels_stay_readable(df):
    for chart_type, width in (("Treemap", charts.TREEMAP_WRAP), ("Sunburst", charts.SUNBURST_WRAP)):
        fig = charts.build_hierarchy_chart(df, chart_type=chart_type)
        trace = fig.data[0]
        # One "All domains" root to click back to, with the domains under it.
        roots = [i for i, p in zip(trace.ids, trace.parents) if not p]
        top = [lab for lab, p in zip(trace.labels, trace.parents) if p in roots]
        assert len(roots) == 1
        assert top and all(not label.replace("<br>", " ").startswith("Domain ") for label in top)
        # Subcategory names wrap onto short lines (single long words can't wrap).
        subcats = [lab for lab, p in zip(trace.labels, trace.parents) if p and p not in roots]
        assert all(len(line) <= width for label in subcats for line in label.split("<br>") if " " in line)
        # Blocks too small for readable text hide it instead of shrinking it.
        assert fig.layout.uniformtext.mode == "hide"
        assert fig.layout.uniformtext.minsize >= 12


def test_hierarchy_chart_opens_on_domains_with_exact_counts(df):
    for chart_type in ("Treemap", "Sunburst"):
        fig = charts.build_hierarchy_chart(df, chart_type=chart_type)
        trace = fig.data[0]
        # Only the root and the domains are drawn until the reader clicks a domain.
        assert trace.maxdepth == 2
        # Domain shading and label counts are distinct organizations, not a sum over subcategories.
        by_name = {c[3]: (c, color) for c, color in zip(trace.customdata, trace.marker.colors)}
        custom, color = by_name[SEL]
        assert custom[2] == color == 2


def test_hierarchy_chart_handles_a_single_domain(df):
    one = app.filter_outcomes(df, domains=[SEL])
    for chart_type in ("Treemap", "Sunburst"):
        trace = charts.build_hierarchy_chart(one, chart_type=chart_type).data[0]
        # The domain itself is the only top-level block (no "All domains" header).
        assert [c[3] for c, p in zip(trace.customdata, trace.parents) if not p] == [SEL]
        assert {c[3] for c, p in zip(trace.customdata, trace.parents) if p} == set(one[app.COL_SUBCAT])


def test_hover_samples_escape_html():
    text = app.sample_outcome_texts(pd.Series(["<b>bold</b> claim"]))
    assert "&lt;b&gt;" in text and "<b>bold" not in text


def test_subcategory_sort_is_numeric():
    labels = ["10.1 A", "3.1.4 B", "3.1.2 C", "1.4 D"]
    assert app.sorted_subcategories(labels) == ["1.4 D", "3.1.2 C", "3.1.4 B", "10.1 A"]


def test_population_groups_fold_small_groups():
    assert app.population_group("students_youth") == "Students & youth"
    assert app.population_group("mentors_volunteers") == app.OTHER_POPULATION
    assert app.population_group(app.UNKNOWN_POP) == app.OTHER_POPULATION


def test_domain_population_shares_sum_to_one(df):
    counts = app.domain_population_counts(df)
    shares = counts.groupby(app.COL_DOMAIN)["share"].sum()
    assert shares.round(9).eq(1).all()


def test_coverage_counts_organizations_and_includes_codebook_gaps(df):
    codebook = pd.DataFrame({
        app.COL_DOMAIN: [SEL, SEL, JOY],
        app.COL_SUBCAT: [CONF, "3.9 Nobody does this", CREATE],
    })
    coverage = app.subcategory_coverage(df, codebook).set_index(app.COL_SUBCAT)
    assert coverage.loc["3.9 Nobody does this", "organizations"] == 0
    assert coverage.loc[CONF, "organizations"] == 2     # BalletX and ArtWell
    assert coverage.loc[CREATE, "organizations"] == 2   # BalletX and Musicopia
    assert app.UNASSIGNED_SUBCAT not in coverage.index
    assert coverage["organizations"].is_monotonic_increasing


def test_bundled_codebook_matches_coded_labels():
    codebook = app.load_codebook()
    assert len(codebook) > 50
    assert CONF in set(codebook[app.COL_SUBCAT])


def test_outcome_text_prefers_atomic_and_keeps_split_context():
    raw = raw_rows().head(2).assign(
        outcome_text_original=["Increased confidence, well-being and self-worth", "Students work in teams"],
        outcome_text_atomic=["Increased well-being", "Students work in teams"],
    )
    df = app.clean_outcomes(raw)
    assert df.loc[0, app.COL_OUTCOME] == "Increased well-being"
    assert df.loc[0, app.COL_FULL] == "Increased confidence, well-being and self-worth"
    assert df.loc[1, app.COL_FULL] == ""  # not split, so no extra context
    assert app.COL_OUTCOME not in app.to_export_frame(df).columns


def test_program_labels_name_the_program_only_when_an_org_has_several(df):
    labels = set(app.program_options(df)[app.COL_PROGRAM_LABEL])
    assert "BalletX" in labels
    assert {"Historic Fair Hill, Inc.: Gardens", "Historic Fair Hill, Inc.: Reading Buddies"} <= labels


def test_program_flows_go_to_domains_then_to_one_domains_subcategories(df):
    flows = app.program_flows(df, ["BalletX", "ArtWell"])
    assert flows.groupby("source")["outcomes"].sum().to_dict() == {"ArtWell": 2, "BalletX": 3}
    assert flows["target"].tolist()[0] == JOY  # codebook order: Domain 1 before Domain 3
    zoomed = app.program_flows(df, ["BalletX", "ArtWell"], domain=SEL)
    assert set(zoomed["target"]) == {CONF, TEAM}
    assert zoomed["outcomes"].sum() == 4


def test_program_dots_put_programs_in_rows_and_domains_in_codebook_order(df):
    programs = ["BalletX", "ArtWell"]
    fig = charts.build_program_dots(app.program_flows(df, programs), programs)
    trace = fig.data[0]
    columns = list(fig.layout.xaxis.categoryarray)
    assert app.domain_code(columns[0]) == "1" and app.domain_code(columns[-1]) == "3"
    # Rows are keyed on full names; only the tick text wraps.
    assert list(fig.layout.yaxis.categoryarray) == programs == list(fig.layout.yaxis.tickvals)
    # customdata[0] names the cell a click picks.
    assert f"BalletX||{JOY}" in [c[0] for c in trace.customdata]
    # Dots take their domain's codebook color and fade (not recolor) when another is picked.
    assert set(trace.marker.color) <= {charts.domain_color(c) for c in columns}
    assert trace.unselected.marker.opacity < 1 and trace.unselected.marker.color is None


def test_program_dots_domain_headers_are_clickable_marks_until_zoomed(df):
    programs = ["BalletX", "ArtWell"]
    fig = charts.build_program_dots(app.program_flows(df, programs), programs)
    header = fig.data[1]
    # Each domain name is a mark whose click key names the domain; axis labels give way to it.
    assert [c[0] for c in header.customdata] == [charts.DOMAIN_KEY + JOY, charts.DOMAIN_KEY + SEL]
    assert list(header.x) == list(fig.layout.xaxis.categoryarray)
    assert fig.layout.xaxis.showticklabels is False
    assert header.marker.opacity == 0 and header.unselected.marker.opacity == 0
    zoomed = charts.build_program_dots(app.program_flows(df, programs, domain=SEL), programs, zoomed=True)
    # Zoomed into a domain, goal headers are labels only: their clicks name nothing.
    assert {c[0] for c in zoomed.data[1].customdata} == {""}


def test_ranked_bars_fade_everything_but_the_clicked_bar(df):
    domains = app.domain_summary(df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]}))
    fig = charts.build_ranked_bars(domains, app.COL_DOMAIN_SHORT, "organizations", app.COL_DOMAIN)
    trace = fig.data[0]
    assert [c[0] for c in trace.customdata][0] == SEL          # most organizations first; key in customdata[0]
    assert "Uncoded" not in [c[0] for c in trace.customdata]
    # Plotly styles the selection, so the figure is the same before and after a click.
    assert trace.marker.color == charts.PRIMARY
    assert trace.selected.marker.color == charts.PRIMARY
    assert trace.unselected.marker.color == charts.FADED


def test_summaries_count_organizations_once(df):
    frame = df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]})
    domains = app.domain_summary(frame).set_index(app.COL_DOMAIN)
    assert domains.loc[SEL, "organizations"] == 2      # BalletX and ArtWell
    assert domains.loc[SEL, "outcomes"] == 4
    assert domains.index[0] == SEL                     # most organizations first
    goals = app.goal_summary(frame)
    assert app.UNASSIGNED_SUBCAT not in set(goals[app.COL_SUBCAT])
    pops = app.population_summary(frame).set_index("population_group")
    assert pops.loc["Students & youth", "outcomes"] == 6
    assert pops.loc["Educators & staff", "outcomes"] == 1


def test_findings_state_the_top_domain_and_codebook_gaps(df):
    frame = df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]})
    coverage = app.subcategory_coverage(frame, app.load_codebook())
    text = " ".join(app.portfolio_findings(frame, coverage))
    assert "**Social-emotional skills** is the most widely shared aim: **2 of 4** organizations" in text
    assert "Far fewer name what schools report on: **0** name attendance, **0** literacy and **0** math." in text
    gaps = int((coverage["organizations"] == 0).sum())
    assert f"**{gaps} goals** in the codebook have no program" in text
    assert "of outcomes are about students and youth" in text
    assert app.portfolio_findings(frame.iloc[0:0], coverage) == []


def test_priorities_put_school_measures_before_their_domain():
    assert app.priority_of(11.0, "11.5 Attendance, Chronic Absence & School Stability") == "Attendance"
    assert app.priority_of(11.0, "11.3 General Content Knowledge & Conceptual Understanding") == \
        "Other academic learning"
    assert app.priority_of(7.0, "7.2 Mental Health Status (Symptom Reduction)") == "Mental health"
    assert app.priority_of(7.0, "7.1 Physical Activity & Nutrition") == "Physical health & safety"
    assert app.priority_of(3.0, CONF) == "Social-emotional skills"
    assert app.priority_of(1.0, app.UNASSIGNED_SUBCAT) == "Joy & interest in learning"  # falls back to the domain
    assert app.priority_of(float("inf"), app.UNASSIGNED_SUBCAT) == app.UNCODED_PRIORITY
    # 11.5 must not match 11.50-style numbers or 1.1 match 11.
    assert app.priority_of(1.0, "1.1 Joy & Emotional Wellness") == "Joy & interest in learning"


def test_priority_summary_counts_organizations_and_skips_uncoded(df):
    frame = df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]})
    summary = app.priority_summary(frame).set_index(app.COL_PRIORITY)
    assert summary.loc["Social-emotional skills", "organizations"] == 2   # BalletX and ArtWell
    assert summary.loc["Social-emotional skills", "outcomes"] == 4
    assert summary.index[0] == "Social-emotional skills"
    assert app.UNCODED_PRIORITY not in summary.index


def test_rows_with_no_organization_are_not_counted_as_one():
    raw = raw_rows()
    raw.loc[len(raw)] = {**raw.iloc[0].to_dict(), "organization": None, "source_filename": None}
    frame = app.clean_outcomes(raw)
    assert (frame[app.COL_ORG] == app.UNKNOWN_ORG).sum() == 1
    assert frame[app.COL_ORG].nunique() == 5
    assert app.count_organizations(frame[app.COL_ORG]) == 4
    summary = app.priority_summary(frame).set_index(app.COL_PRIORITY)
    assert summary.loc["Social-emotional skills", "organizations"] == 2


def test_sunburst_nodes_count_programs_and_organizations_at_each_level(df):
    frame = df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]})
    nodes = app.sunburst_nodes(frame).set_index("id")
    root = nodes.loc[app.SUNBURST_ROOT]
    assert root["outcomes"] == len(frame)
    assert root["programs"] == app.count_programs(frame) == 5
    sel = nodes.loc[SEL]
    assert (sel["level"], sel["outcomes"], sel["programs"], sel["organizations"]) == ("domain", 4, 2, 2)
    conf = nodes.loc[SEL + app.SUNBURST_SEP + CONF]
    assert (conf["level"], conf["parent"], conf["goal"], conf["programs"]) == ("goal", SEL, CONF, 2)
    # Domains in codebook order, then their goals; Uncoded last.
    domains = nodes[nodes["level"] == "domain"].index.tolist()
    assert domains[0] == JOY and domains[-1] == app.UNCODED_DOMAIN


def test_chart_search_index_lists_each_goals_statements_with_program_and_org(df):
    frame = df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]})
    nodes = app.sunburst_nodes(frame)
    index = app.chart_search_index(frame, nodes, {"3.1.4": "self-efficacy belief", "3": "social emotional"})
    conf = index["rows"][SEL + app.SUNBURST_SEP + CONF]
    assert sorted(index["texts"][t] for t, _, _ in conf) == ["Increased student confidence", "Youth feel confident"]
    # Two programs at two organizations, as the chart counts them.
    assert len({p for _, p, _ in conf}) == 2 and len({o for _, _, o in conf}) == 2
    assert set(index["rows"]) <= set(nodes["id"])
    assert index["terms"] == {SEL + app.SUNBURST_SEP + CONF: "self-efficacy belief", SEL: "social emotional"}
    json.dumps(index)  # it goes to the browser as JSON


def test_wheel_nodes_group_goals_into_codebook_categories(df):
    frame = df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]})
    categories = {"3.1.4": "A. Self", "3.4.2": "B. Others"}
    nodes = app.sunburst_nodes(frame, categories=categories).set_index("id")
    cat_a = nodes.loc[SEL + app.CATEGORY_SEP + "A. Self"]
    assert (cat_a["level"], cat_a["parent"], cat_a["code"], cat_a["title"]) == ("category", SEL, "A", "Self")
    # Exact counts at the category: CONF has two outcomes from two programs.
    assert (cat_a["outcomes"], cat_a["programs"]) == (2, 2)
    assert nodes.loc[SEL + app.SUNBURST_SEP + CONF, "category"] == SEL + app.CATEGORY_SEP + "A. Self"
    assert nodes.loc[JOY + app.SUNBURST_SEP + CREATE, "category"] == ""
    data = charts.codebook_sunburst_data(nodes.reset_index(), app.MEASURE_PROGRAMS, layout="equal")
    cat = next(n for n in data["nodes"] if n["level"] == "category" and n["title"] == "Others")
    assert cat["value"] == 2 and cat["label"] == "B" and cat["eyebrow"].endswith("Category B")
    assert all(n["category"] is None for n in data["nodes"] if n["level"] == "goal" and n["parent"] == JOY)
    # Without categories, nothing changes.
    assert "category" not in set(app.sunburst_nodes(frame)["level"])


def test_chart_nodes_carry_plain_names_longest_first_and_code_last(df):
    frame = df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]})
    nodes = app.sunburst_nodes(frame, categories={"3.1.4": "A. Self"})
    data = charts.codebook_sunburst_data(nodes, app.MEASURE_PROGRAMS, layout="equal",
                                         short_names={"3.1.4": "Confidence"})
    by_title = {n["title"]: n for n in data["nodes"]}
    goal = next(n for n in data["nodes"] if n["level"] == "goal" and n["goal"] == CONF)
    assert goal["names"] == [goal["title"], "Confidence", "3.1.4"]
    assert by_title["Self"]["names"] == ["Self", "A"]
    domain = next(n for n in data["nodes"] if n["level"] == "domain" and n["id"] == SEL)
    assert domain["names"][0] == domain["title"] and domain["names"][-1] == domain["label"]
    assert next(n for n in data["nodes"] if n["level"] == "root")["names"] == []


def test_codebook_short_names_come_from_the_3x_codebook():
    short = app.load_codebook_short_names()
    assert short["Y3.2"] == "Supportive adults"
    assert short["Y1.1"] == "Literacy"
    assert "Y1" not in short


def test_codebook_categories_cover_every_3x_goal():
    cats = app.load_codebook_categories()
    codes = {app.split_code(g)[0] for g in app.load_codebook(app.CODEBOOK_V3_PATH)[app.COL_SUBCAT]}
    assert codes == set(cats)
    assert cats["Y3.2"] == "B. Close relationships"
    assert len(set(cats.values())) <= 39


def test_codebook_terms_cover_every_3x_goal():
    terms = app.load_codebook_terms()
    codes = {app.split_code(g)[0] for g in app.load_codebook(app.CODEBOOK_V3_PATH)[app.COL_SUBCAT]}
    assert codes <= set(terms)
    assert "mentor" in terms["Y3.2"] and "Academic" in terms["Y1"]


def test_codebook_sunburst_data_sizes_domains_by_their_goals_and_reads_exact_counts(df):
    frame = df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]})
    data = charts.codebook_sunburst_data(app.sunburst_nodes(frame), app.MEASURE_PROGRAMS)
    nodes = {n["id"]: n for n in data["nodes"]}
    goals = [n for n in data["nodes"] if n["parent"] == SEL]
    # Each SEL goal has 2 programs, so the arc is 4 while the readout gives the 2 distinct programs.
    assert nodes[SEL]["value"] == sum(g["value"] for g in goals) == 4
    assert nodes[SEL]["count"] == nodes[SEL]["programs"] == 2
    assert (nodes[SEL]["eyebrow"], nodes[SEL]["label"], nodes[SEL]["title"]) == (
        "Domain 3", "3", "Social & Emotional Learning")
    conf = nodes[SEL + app.SUNBURST_SEP + CONF]
    assert (conf["eyebrow"], conf["label"], conf["goal"]) == ("Goal 3.1.4", "3.1.4", CONF)
    # Same domain, same hue on both rings; the Uncoded domain has none (the chart draws it grey).
    assert nodes[SEL]["hue"] == conf["hue"] is not None
    assert nodes[app.UNCODED_DOMAIN]["hue"] is None
    # Plain-text samples, and JSON-safe values throughout (the browser parses this).
    assert all(isinstance(t, str) and "<br>" not in t for t in conf["samples"])
    json.dumps(data, allow_nan=False)
    # The signature follows the counts, not the selection.
    again = charts.codebook_sunburst_data(app.sunburst_nodes(frame), app.MEASURE_PROGRAMS,
                                          selected={"domain": SEL, "goal": None})
    assert again["sig"] == data["sig"]
    assert charts.codebook_sunburst_data(app.sunburst_nodes(frame), app.MEASURE_ORGS)["sig"] != data["sig"]


def test_sunburst_colors_follow_the_codebook_not_the_filters(df):
    frame = df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]})
    codebook = app.load_codebook_for(frame)
    full = app.sunburst_nodes(frame, codebook).set_index("id")
    only_sel = app.sunburst_nodes(frame[frame[app.COL_DOMAIN] == SEL], codebook).set_index("id")
    assert full.at[SEL, "domain_index"] == only_sel.at[SEL, "domain_index"]


def test_wheel_nodes_keep_every_codebook_goal_with_zero_counts(df):
    frame = df.assign(**{app.COL_ORG_VIEW: df[app.COL_ORG]})
    codebook = app.load_codebook_for(frame)
    nodes = app.sunburst_nodes(frame, codebook, include_empty_goals=True).set_index("id")
    goals = nodes[nodes["level"] == "goal"]
    # Every codebook goal has a node; the ones no outcome names count zero.
    codebook_ids = {d + app.SUNBURST_SEP + g for d, g in zip(codebook[app.COL_DOMAIN], codebook[app.COL_SUBCAT])}
    assert codebook_ids <= set(goals.index)
    conf = goals.loc[SEL + app.SUNBURST_SEP + CONF]
    assert conf["programs"] == 2
    assert (goals.loc[list(codebook_ids - set(app.sunburst_nodes(frame)["id"])), "programs"] == 0).all()
    # Same counts and colors as the sunburst where both have the node.
    plain = app.sunburst_nodes(frame, codebook).set_index("id")
    shared = plain.index
    assert (nodes.loc[shared, "programs"] == plain["programs"]).all()
    assert (nodes.loc[shared, "domain_index"] == plain["domain_index"]).all()
    data = charts.codebook_sunburst_data(nodes.reset_index(), app.MEASURE_PROGRAMS, layout="equal")
    assert data["layout"] == "equal"
    json.dumps(data, allow_nan=False)
    assert data["sig"] != charts.codebook_sunburst_data(nodes.reset_index(), app.MEASURE_PROGRAMS)["sig"]


def test_split_code():
    assert app.split_code("Y1.3 Mathematics") == ("Y1.3", "Mathematics")
    assert app.split_code("Domain Y4. Social & Emotional Skills (CASEL)") == ("Y4", "Social & Emotional Skills")
    assert app.split_code(CONF) == ("3.1.4", "Confidence, self-efficacy & growth mindset")
    assert app.split_code(app.UNCODED_DOMAIN) == ("", app.UNCODED_DOMAIN)


def test_sample_outcomes_are_distinct_stable_and_skip_blanks():
    texts = pd.Series(["a", "b", "a", "", None, "c", "d"])
    picked = app.sample_outcomes(texts, n=3)
    assert len(picked) == len(set(picked)) == 3 and set(picked) <= {"a", "b", "c", "d"}
    assert app.sample_outcomes(texts, n=3) == picked
    assert app.sample_outcomes(pd.Series(["x", "x"])) == ["x"]


# --- Codebook 3.x and district program files ----------------------------------

Y1 = "Domain Y1. Academic Learning & Achievement"
Y4 = "Domain Y4. Social & Emotional Skills (CASEL)"
A2 = "Domain A2. Program Quality, Access & Reach"
ATTEND = "Y1.13 Attendance & School Stability"
STUDY = "Y1.11 Learning Strategies & Study Skills"
REGULATE = "Y4.2 Emotion Regulation & Coping"


def district_rows():
    """The shape of a district program-description export: codebook 3.x, partner IDs, no organization column."""
    def row(partner, program, text, domain, subcat, specificity="code", source="program_description"):
        return {
            "partner_id": partner, "program": program, "outcome_text_original": text,
            "primary_domain": domain, "primary_subcategory": subcat,
            "primary_target_population": "students_youth", "primary_confidence": "high",
            "source_type": source, "specificity": specificity,
        }

    return pd.DataFrame([
        row("4", "Social Skills Playgroup", "Students stay on task", Y1, STUDY),
        row("4", "Social Skills Playgroup", "Students manage frustration", Y4, REGULATE),
        row("116", "North10", "Increase school attendance", Y1, ATTEND, source="district_program_outcomes"),
        row("116", "North10", "Grow social-emotionally", Y4, None, specificity="domain"),
        row("74", "Tennis", "Provide a safe after-school space", A2, "A2.1 Program Quality"),
        row("74", "Tennis", "Overall youth development", None, None, specificity="uncoded"),
    ])


def test_district_file_without_organization_loads_and_groups_by_partner():
    frame = app.clean_outcomes(district_rows())
    assert set(frame[app.COL_ORG]) == {"Partner 4", "Partner 116", "Partner 74"}
    assert app.count_organizations(frame[app.COL_ORG]) == 3


def test_partner_id_fills_rows_with_no_organization_name():
    raw = pd.concat([raw_rows(), district_rows()], ignore_index=True)
    frame = app.clean_outcomes(raw)
    assert "Partner 116" in set(frame[app.COL_ORG])
    assert "BalletX" in set(frame[app.COL_ORG])


def test_source_type_defaults_to_logic_model_and_renames_old_district_value():
    assert set(app.clean_outcomes(raw_rows())[app.COL_SOURCE_TYPE]) == {"logic_model"}
    sources = set(app.clean_outcomes(district_rows())[app.COL_SOURCE_TYPE])
    assert sources == {"program_description"}
    assert "logic models" in app.intent_note(["logic_model"])
    assert "program descriptions" in app.intent_note(sources)
    assert "logic models and program descriptions" in app.intent_note(["logic_model", "program_description"])


def test_priorities_recognize_codebook_3_codes():
    assert app.priority_of(Y1, ATTEND) == "Attendance"
    assert app.priority_of(Y1, "Y1.1 Literacy: Reading & Writing") == "Literacy"
    assert app.priority_of(Y1, "Y1.10 Academic Perseverance") == "Engagement & study habits"  # not Literacy
    assert app.priority_of(Y1, "Y1.18 Postsecondary Enrollment, Persistence & Completion") == "College & career"
    assert app.priority_of(Y1, "Y1.5 Other Academic Subjects") == "Other academic learning"
    assert app.priority_of("Domain Y8. Health, Safety & Well-Being", "Y8.6 Mental Health Symptoms & Distress") \
        == "Mental health"
    assert app.priority_of(Y4, app.UNASSIGNED_SUBCAT) == "Social-emotional skills"
    assert app.priority_of("Domain F2. Basic Needs & Economic Stability", "F2.2 Food Security") == \
        "Families & basic needs"
    frame = app.clean_outcomes(district_rows())
    assert app.UNCODED_PRIORITY not in set(frame.loc[frame[app.COL_DOMAIN] != app.UNCODED_DOMAIN, app.COL_PRIORITY])


def test_codebook_3_domains_sort_by_part_then_number():
    frame = app.clean_outcomes(district_rows())
    assert app.domain_order(frame) == [Y1, Y4, A2, app.UNCODED_DOMAIN]
    labels = ["A2.1 X", "Y1.13 X", "Y1.2 X", "F1.1 X", "Y4 X, no specific goal", "Y4.1 X"]
    assert app.sorted_subcategories(labels) == ["Y1.2 X", "Y1.13 X", "Y4 X, no specific goal", "Y4.1 X",
                                                "F1.1 X", "A2.1 X"]


def test_domain_only_rows_get_their_own_goal_and_stay_out_of_coverage_gaps():
    frame = app.clean_outcomes(district_rows())
    frame = frame.assign(**{app.COL_ORG_VIEW: frame[app.COL_ORG]})
    row = frame[frame[app.COL_TEXT] == "Grow social-emotionally"].iloc[0]
    assert row[app.COL_SUBCAT] == "Y4 Social & Emotional Skills (CASEL), no specific goal"
    assert row[app.COL_PRIORITY] == "Social-emotional skills"
    uncoded = frame[frame[app.COL_TEXT] == "Overall youth development"].iloc[0]
    assert uncoded[app.COL_SUBCAT] == app.UNASSIGNED_SUBCAT
    coverage = app.subcategory_coverage(frame, app.load_codebook_for(frame))
    assert not coverage[app.COL_SUBCAT].str.endswith(app.DOMAIN_ONLY_SUFFIX).any()


def test_codebook_matches_the_files_numbering():
    v3 = app.load_codebook_for(app.clean_outcomes(district_rows()))
    assert len(v3) == 98 and ATTEND in set(v3[app.COL_SUBCAT]) and CONF not in set(v3[app.COL_SUBCAT])
    v1 = app.load_codebook_for(app.clean_outcomes(raw_rows()))
    assert CONF in set(v1[app.COL_SUBCAT]) and ATTEND not in set(v1[app.COL_SUBCAT])
    frame = app.clean_outcomes(district_rows())
    frame = frame.assign(**{app.COL_ORG_VIEW: frame[app.COL_ORG]})
    coverage = app.subcategory_coverage(frame, v3)
    assert (coverage["organizations"] == 0).sum() == 98 - 4   # every 3.x code but the four the file uses


def test_peer_and_findings_views_work_on_a_codebook_3_file():
    frame = app.clean_outcomes(district_rows())
    frame = frame.assign(**{app.COL_ORG_VIEW: frame[app.COL_ORG]})
    peers = app.compute_peer_overlap(frame, "Partner 4")
    assert peers.empty   # nobody else shares Y1.11 or Y4.2
    counts, samples = app.peer_heatmap_data(frame, "Partner 116", ["Partner 4"])
    assert counts.shape == samples.shape
    coverage = app.subcategory_coverage(frame, app.load_codebook_for(frame))
    assert app.portfolio_findings(frame, coverage)


def test_names_differing_only_in_capitals_merge_to_the_mixed_case_spelling():
    raw = raw_rows()
    raw.loc[len(raw)] = {**raw.iloc[5].to_dict(), "organization": "MUSICOPIA"}
    raw.loc[len(raw)] = {**raw.iloc[5].to_dict(), "organization": "MUSICOPIA"}
    frame = app.clean_outcomes(raw)
    assert "MUSICOPIA" not in set(frame[app.COL_ORG])
    assert (frame[app.COL_ORG] == "Musicopia").sum() == 3


# --- The app itself -------------------------------------------------------------


def test_app_runs_every_view(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "export.csv"
    raw_rows().to_csv(path, index=False)
    monkeypatch.setenv(app.DATA_ENV_VAR, str(path))
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    assert not at.exception
    for view in ("Sunburst", "Treemap", "Ranked"):
        at.session_state["v1_view"] = view
        at.run()
        assert not at.exception, view


def test_axis_labels_wrap_instead_of_cutting():
    name = "Netter Center for Community Partnerships, University of Pennsylvania"
    label = charts.axis_label(name)
    assert "…" not in label and label.replace("<br>", " ") == name
    # Hyphenated words stay whole.
    assert "Self-<br>" not in charts.axis_label("Goal-Setting, Organization & Self-Discipline", 20)


def test_rows_sharing_a_long_prefix_stay_separate(df):
    long = "After School Activities Partnerships (ASAP)"
    programs = [f"{long}: Drama", f"{long}: Chess and Scrabble Clubs"]
    flows = pd.DataFrame({"source": programs, "target": [JOY, JOY], "outcomes": [4, 5], "samples": ["", ""]})
    fig = charts.build_program_dots(flows, programs)
    assert list(fig.data[0].y) == programs
    assert list(fig.layout.yaxis.categoryarray) == programs


def test_ranked_bars_key_rows_on_full_names():
    names = ["Y4.7 Teamwork, Collaboration & Group Leadership", "Y1.18 Postsecondary Enrollment, Persistence"]
    data = pd.DataFrame({"label": names, "n": [3, 2], "key": names, "samples": ["", ""]})
    fig = charts.build_ranked_bars(data, "label", "n", "key")
    assert list(fig.data[0].y) == names
    assert all("…" not in t for t in fig.layout.yaxis.ticktext)


def test_coded_by_is_an_organization_not_junk():
    raw = pd.DataFrame({
        "organization": ["Coded by:", None], "program": ["Coded by: Classroom"] * 2,
        "outcome_text_original": ["a", "b"], "primary_domain": [SEL] * 2,
        "primary_subcategory": ["x", "y"], "primary_target_population": ["students_youth"] * 2,
        "primary_confidence": ["high"] * 2,
        "source_filename": ["101_127 - Coded by- - Coded by- Classroom - Logic Model.pdf"] * 2,
    })
    clean = app.clean_outcomes(raw)
    assert set(clean["organization"]) == {"Coded by: (formerly Coded by Kids)"}


def test_codebook_definitions_cover_every_v3_code():
    """The wheel's panel has the codebook's words for every 3.x domain and goal, with names for its 'see also' codes."""
    from outcomes_data import load_codebook_definitions, load_codebook_terms
    defs = load_codebook_definitions()
    codes = load_codebook_terms()
    assert defs["version"]
    for code in codes:
        if "." in code:
            assert defs["goals"][code]["definition"], code
            assert all(other in codes for other in defs["goals"][code]["see_also"]), code
        else:
            assert defs["domains"][code]["description"], code
    # Codes are swapped for plain names in the text people read.
    import re
    for g in defs["goals"].values():
        for field in ("definition", "include", "exclude"):
            assert not re.search(r"\b[YFA]\d+\.\d+\b", g[field]), g[field]
