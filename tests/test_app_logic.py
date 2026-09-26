"""Tests for the data layer (outcomes_data.py) and chart builders (charts.py).

Run from the repository root with:  python -m pytest
Uses a small synthetic export, so the real CSV is not needed.
"""

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
    assert columns[0].startswith("1.") and columns[-1].startswith("3.")
    assert list(fig.layout.yaxis.categoryarray) == programs
    # customdata[0] names the cell a click picks.
    assert f"BalletX||{JOY}" in [c[0] for c in trace.customdata]
    assert trace.marker.color == charts.PRIMARY
    assert trace.unselected.marker.color == charts.FADED


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
    assert len(zoomed.data) == 1


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
