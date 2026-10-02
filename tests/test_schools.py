"""Tests for the school page's data layer (schools.py), with small synthetic district tables."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import charts  # noqa: E402
import outcomes_data as od  # noqa: E402
import schools as sc  # noqa: E402

SEL = "Domain Y4. Social & Emotional Skills"
ACAD = "Domain Y1. Academic Learning & Achievement"


def outcomes():
    def row(org, program, key, domain, subcat, text="An outcome", **extra):
        return {"organization": org, "program": program, "program_key": key, "outcome_text_original": text,
                "primary_domain": domain, "primary_subcategory": subcat,
                "primary_target_population": "students_youth", "primary_confidence": "high",
                "source_filename": f"2025-07-08 - {key} - {org or 'Org From File'} - {program} - Logic Model.pdf",
                **extra}
    raw = pd.DataFrame([
        row("BalletX", "Dance", "10_1", SEL, "Y4.2 Emotion regulation", "Kids calm down"),
        row("BalletX", "Dance", "10_1", ACAD, "Y1.1 Literacy", "Kids read"),
        row(None, "Mentors", "20_5", SEL, "Y4.2 Emotion regulation", "Youth cope"),
        row("No IDs Inc", "Thing", "no-ids_thing", ACAD, "Y1.1 Literacy"),
    ])
    return sc.with_program_ids(od.clean_outcomes(raw))


def relationships():
    raw = pd.DataFrame({
        "PARTNER ID": [10, 10, 20, 30, 10, 99],
        "PROGRAM ID": [1, 2, 5, 7, 1, 8],
        "EOS CODE": [1010, 1010, 1010, 1010, 2020, 2020],
        "FISCAL YEAR ID": [20252026] * 5 + [20242025],
        "DELETE": [None, None, None, None, None, None],
    })
    return sc.tidy_relationships(raw)


def test_ids_come_from_program_key_or_columns():
    df = outcomes()
    assert df["partner_id"].tolist()[:3] == ["10", "10", "20"]
    assert pd.isna(df["program_id"].iloc[3])
    district = sc.with_program_ids(pd.DataFrame({"partner_id": ["4"], "program_id": ["1.0"]}))
    assert (district["partner_id"].iloc[0], district["program_id"].iloc[0]) == ("4", "1")


def test_relationships_keep_latest_year_only():
    rel = relationships()
    assert set(rel["fiscal_year"]) == {"20252026"}
    assert "8" not in set(rel["program_id"])


def test_table_kind_tells_the_two_tables_apart():
    assert sc.table_kind(pd.DataFrame(columns=["Partner ID", "Program ID", "EOS Code"])) == sc.RELATIONSHIPS
    assert sc.table_kind(pd.DataFrame(columns=["ULCS", "Publication Name"])) == sc.SCHOOLS
    assert sc.table_kind(pd.DataFrame(columns=["foo"])) is None


def test_portfolio_marks_coded_partly_coded_and_not_coded():
    portfolio = sc.school_portfolio(relationships(), "1010", outcomes()).set_index("partner_id")
    assert portfolio.loc["10", "status"] == sc.PARTLY_CODED      # program 1 coded, program 2 not
    assert portfolio.loc["20", "status"] == sc.CODED
    assert portfolio.loc["30", "status"] == sc.NOT_CODED
    assert portfolio.loc["30", "partner"] == "Partner 30"
    assert portfolio.loc["20", "partner"] == "Org From File"     # name recovered from the file name
    assert list(portfolio["status"]) == [sc.CODED, sc.PARTLY_CODED, sc.NOT_CODED]


def test_school_outcomes_and_flows_cover_only_programs_at_the_school():
    df, rel = outcomes(), relationships()
    portfolio = sc.school_portfolio(rel, "2020", df)
    labels = dict(zip(portfolio["partner_id"], portfolio["partner"]))
    rows = sc.school_outcomes(df, rel, "2020", labels)
    assert set(rows["partner"]) == {"BalletX"} and len(rows) == 2
    flows = sc.partner_flows(rows)
    assert set(flows["target"]) == {SEL, ACAD}


def test_findings_say_how_much_of_the_school_is_covered():
    df, rel = outcomes(), relationships()
    portfolio = sc.school_portfolio(rel, "1010", df)
    labels = dict(zip(portfolio["partner_id"], portfolio["partner"]))
    rows = sc.school_outcomes(df, rel, "1010", labels)
    text = " ".join(sc.school_findings("Bartram", portfolio, rows, "2025-26"))
    assert "**3 partners** run **4 programs**" in text
    assert "**2 of 3** have coded outcomes" in text and "**1** is listed as not yet coded" in text
    empty = sc.school_findings("Nowhere", portfolio.iloc[0:0], rows.iloc[0:0])
    assert "No partner programs" in empty[0]


def test_join_summary_counts_programs_without_ids():
    summary = sc.join_summary(outcomes(), relationships())
    assert summary == {"programs": 3, "with_ids": 2, "matched": 2, "schools": 2}


def test_school_options_name_unknown_codes():
    schools = sc.tidy_schools(pd.DataFrame({"ULCS": [1010], "Publication Name": ["Bartram"],
                                            "School Level": ["High"]}))
    options = sc.school_options(relationships(), schools).set_index("ulcs")
    assert options.loc["1010", "school"] == "Bartram"
    assert options.loc["2020", "school"] == "School 2020"


def test_school_dots_add_grey_rows_for_uncoded_partners():
    df, rel = outcomes(), relationships()
    portfolio = sc.school_portfolio(rel, "1010", df)
    labels = dict(zip(portfolio["partner_id"], portfolio["partner"]))
    rows = sc.school_outcomes(df, rel, "1010", labels)
    fig = charts.build_school_dots(sc.partner_flows(rows), ["BalletX", "Org From File"],
                                   [("Partner 30", "Not yet coded")])
    assert list(fig.layout.yaxis.categoryarray)[-1] == "Partner 30"
    assert fig.data[-1].text == ("Not yet coded",)
    assert "Y4 ›" in fig.data[1].text[-1] or "Y4 ›" in fig.data[1].text[0]
