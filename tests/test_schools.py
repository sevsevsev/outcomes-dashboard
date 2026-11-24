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
    assert "on file for **2 of 3**" in text and "the other **1** is listed at the bottom" in text
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
    # Headers name the domain (here the first words of its codebook name) and leave the code off.
    assert any("<b>Social &amp;</b>" in text and "<b>Skills</b>" in text for text in fig.data[1].text)
    assert not any("<b>Y4</b>" in text for text in fig.data[1].text)


def school_table():
    return sc.tidy_schools(pd.DataFrame({
        "ULCS": [1010, 2020, 3030],
        "Publication Name": ["Adams", "Baker", "Carver"],
        "Learning Network": ["Learning Network 10", "Learning Network 2", "Learning Network 2"],
        "Learning Network Short": ["LN 10", "LN 2", "LN 2"],
        "Zip Code": [19104, 19143, 19143],
        "City Council District": [3, 2, 2],
    }))


def test_schools_table_reads_place_columns():
    table = school_table().set_index("ulcs")
    assert table.loc["1010", "zip"] == "19104"
    assert table.loc["2020", "council_district"] == "2"
    assert table.loc["2020", "network_name"] == "Learning Network 2"
    # A table without the place columns still loads, with them left empty.
    bare = sc.tidy_schools(pd.DataFrame({"ULCS": [1], "Publication Name": ["X"]}))
    assert bare["zip"].isna().all() and bare["council_district"].isna().all()


def test_place_values_list_only_schools_with_programs_in_natural_order():
    rel = relationships()   # programs run at 1010 and 2020, none at 3030
    assert sc.place_values(school_table(), rel, "network_name") == ["Learning Network 2", "Learning Network 10"]
    assert sc.place_values(school_table(), rel, "zip") == ["19104", "19143"]
    assert sc.place_values(None, rel, "zip") == []


def test_place_filters_keep_programs_at_matching_schools():
    df, rel, table = outcomes(), relationships(), school_table()
    assert sc.matching_schools(table, rel, {"zip": ["19143"]}) == {"2020"}
    assert sc.matching_schools(table, rel, {"zip": ["19143"], "council_district": ["3"]}) == set()
    assert sc.matching_schools(table, rel, {"zip": []}, ["1010"]) == {"1010"}
    # School 2020 hosts only BalletX program 1; the program without IDs is never placed.
    mask = sc.at_schools(df, rel, {"2020"})
    assert df.loc[mask, "program"].unique().tolist() == ["Dance"]
    assert not mask.iloc[3]
    assert sc.at_schools(df, rel, {"1010"}).sum() == 3


def test_school_dots_show_every_codebook_domain_with_gaps_marked():
    df, rel = outcomes(), relationships()
    portfolio = sc.school_portfolio(rel, "1010", df)
    labels = dict(zip(portfolio["partner_id"], portfolio["partner"]))
    rows = sc.school_outcomes(df, rel, "1010", labels)
    codebook = od.load_codebook(od.CODEBOOK_V3_PATH)
    columns = od.domain_order_with_codebook(rows, codebook)
    assert len(columns) == 13 and set(rows["primary_domain"]) <= set(columns)
    fig = charts.build_school_dots(sc.partner_flows(rows), ["BalletX", "Org From File"],
                                   [("Partner 30", "Not yet coded")], columns=columns)
    assert list(fig.layout.xaxis.categoryarray) == columns
    headers = fig.data[1]
    named = set(rows["primary_domain"])
    for domain, text, custom in zip(headers.x, headers.text, headers.customdata):
        if domain in named:
            assert custom[0] == charts.DOMAIN_KEY + domain and "none" not in text
        else:
            assert custom[0] == "" and "<i>none</i>" in text   # a gap: shown, not clickable


# --- 3.3.0 export and the database's Schools_Partners_Relate.xlsx (2026-11-24) -----------------

def _export_330():
    """Rows shaped like coded_outcomes_youth_outcomes_v3-3.3.0: "Partner ID"/"Program ID" columns and
    "PP-GG-slug - Org - Program - Logic Model" file names, one failed spreadsheet lookup ("#N")."""
    def row(pid, gid, filename, org):
        return {"Partner ID": pid, "Program ID": gid, "organization": org, "program": None,
                "source_filename": filename, "outcome_text_original": "Kids read",
                "primary_domain": ACAD, "primary_subcategory": "Y1.1 Literacy",
                "primary_target_population": "students_youth", "primary_confidence": "high"}
    return pd.DataFrame([
        row("10", "1", "10-1-dance-2026 - BalletX - Dance - Logic Model.pdf", "BalletX"),
        row("113", "13", "113-13-historic-fair-hill-2026 - Historic Fair Hill, Inc. - Historic Fair Hill"
                         " - Logic Model.pdf — Part 1 of 6", None),
        row("43", "#N", "43-#N-A-asap-2026 - ASAP - ASAP Chess - Logic Model.pdf", "ASAP"),
    ])


def test_330_export_id_columns_and_file_names_are_read():
    df = sc.with_program_ids(od.clean_outcomes(_export_330()))
    assert df[od.COL_PARTNER_ID].tolist()[:2] == ["10", "113"]
    assert df[sc.COL_PROGRAM_ID].tolist()[:2] == ["1", "13"]
    assert pd.isna(df[sc.COL_PROGRAM_ID].iloc[2])          # "#N" is a failed lookup, not an ID
    # The organization comes from the dash-style file name, not "Unknown organization" or "Partner 113".
    assert df[od.COL_ORG].iloc[1] == "Historic Fair Hill, Inc."
    assert df[od.COL_PROGRAM].iloc[1] == "Historic Fair Hill"


def test_dash_file_names_give_ids_when_the_columns_are_missing():
    raw = _export_330().drop(columns=["Partner ID", "Program ID"])
    ids = sc.outcome_program_ids(raw)
    assert ids[sc.COL_PROGRAM_ID].tolist()[:2] == ["1", "13"]
    assert ids[od.COL_PARTNER_ID].isna().iloc[2]
    # A dated file name is not read as an ID pair.
    dated = pd.DataFrame({"source_filename": ["2025-07-08 - Org - Program - Logic Model.pdf"]})
    assert sc.outcome_program_ids(dated)[sc.COL_PROGRAM_ID].isna().all()


def _relate_workbook(path, family="16"):
    """An .xlsx like the partnerships database writes: font family 16, which openpyxl refuses."""
    import re
    import zipfile
    pd.DataFrame({"EOS Code": [1010], "School Name": ["A School"], "Partner ID": [10],
                  "Partner Name": ["BalletX Inc"], "Fiscal Year": ["2025-2026"], "Program ID": [1],
                  "Program Name": ["Dance"]}).to_excel(path, index=False)
    with zipfile.ZipFile(path) as src:
        items = {i.filename: src.read(i.filename) for i in src.infolist()}
    # openpyxl versions write the tag as <family val="2"/> or <family val="2" />; drop it, then add ours.
    styles = re.sub(rb'<family\s+val="\d+"\s*/>', b"", items["xl/styles.xml"])
    items["xl/styles.xml"] = re.sub(rb"<font>", f'<font><family val="{family}"/>'.encode(), styles)
    assert f'<family val="{family}"/>'.encode() in items["xl/styles.xml"]
    with zipfile.ZipFile(path, "w") as dst:
        for name, data in items.items():
            dst.writestr(name, data)


def test_relate_export_with_bad_font_family_is_read(tmp_path):
    path = tmp_path / "Schools_Partners_Relate.xlsx"
    _relate_workbook(path)
    kind, rel = sc.read_table(path)
    assert kind == sc.RELATIONSHIPS
    row = rel.iloc[0]
    assert (row[od.COL_PARTNER_ID], row[sc.COL_PROGRAM_ID], row[sc.COL_ULCS]) == ("10", "1", "1010")
    assert row[sc.COL_YEAR] == "20252026"
    assert sc.fiscal_year_label(row[sc.COL_YEAR]) == "2025-26"
    assert row[sc.COL_PARTNER_NAME] == "BalletX Inc"
    assert sc.find_local_tables(tmp_path) == {sc.RELATIONSHIPS: path}


def test_reviewed_id_fixes_correct_a_pair_or_fill_missing_ids(tmp_path):
    fixes_file = tmp_path / "fixes.csv"
    fixes_file.write_text("# comment\nfile_partner_id,file_program_id,file_organization,partner_id,program_id,note\n"
                          "113,13,,88,82,wrong partner\n,,asap,43,73,confirmed\n")
    fixes = sc.load_id_fixes(fixes_file)
    df = od.clean_outcomes(_export_330())
    ids = sc.apply_id_fixes(sc.outcome_program_ids(df), df, fixes)
    assert list(zip(ids[od.COL_PARTNER_ID], ids[sc.COL_PROGRAM_ID])) == [("10", "1"), ("88", "82"), ("43", "73")]
    # Without a fix nothing is guessed from names.
    empty = sc.load_id_fixes(tmp_path / "none.csv")
    assert sc.apply_id_fixes(sc.outcome_program_ids(df), df, empty)[sc.COL_PROGRAM_ID].isna().iloc[2]


def test_shipped_id_fixes_file_is_valid():
    fixes = sc.load_id_fixes()
    assert not fixes.empty
    assert fixes[[od.COL_PARTNER_ID, sc.COL_PROGRAM_ID]].notna().all().all()
    keyed = fixes["file_program_id"].notna() | fixes["file_organization"].notna()
    assert keyed.all()
