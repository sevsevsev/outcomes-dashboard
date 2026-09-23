"""Tests for the pure data functions in app.py.

Run from the repository root with:  python -m pytest
Uses a small synthetic export, so the real CSV is not needed.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402

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


def test_hierarchy_chart_gives_every_node_sample_text(df):
    for chart_type in ("Treemap", "Sunburst"):
        fig = app.build_hierarchy_chart(df, chart_type)
        assert all("(?)" not in str(c[0]) for c in fig.data[0].customdata)


def test_hover_samples_escape_html():
    text = app.sample_outcome_texts(pd.Series(["<b>bold</b> claim"]))
    assert "&lt;b&gt;" in text and "<b>bold" not in text


def test_subcategory_sort_is_numeric():
    labels = ["10.1 A", "3.1.4 B", "3.1.2 C", "1.4 D"]
    assert app.sorted_subcategories(labels) == ["1.4 D", "3.1.2 C", "3.1.4 B", "10.1 A"]
