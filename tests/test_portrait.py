"""Tests for the Portrait of a Graduate view's data (portrait.py) and its reference file.

Run from the repository root with:  python -m pytest
Uses a small synthetic export, so no partner file is needed.
"""

import csv
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import outcomes_data as od  # noqa: E402
import portrait  # noqa: E402

VERSION = "portrait_of_a_graduate@0.1.0"
VALUES = ("POG.2 Persist with purpose and adapt with confidence", "POG.2.1 Know my values and aspirations")
WELLBEING = ("POG.2 Persist with purpose and adapt with confidence", "POG.2.2 Care for my well-being")
CRITICAL = ("POG.7 Think Critically", None)          # names the competency, no single skill
FEELING = ("OUT Outside the Portrait of a Graduate", "OUT.1 Feeling, belief or identity")
ADULTS = ("OUT Outside the Portrait of a Graduate", "OUT.5 Families, staff, programs or systems")


def row(org, program, text, code, uncoded=False, filename=None, version=VERSION, pop="students_youth"):
    domain, subcat = code if code else (None, None)
    specificity = "uncoded" if uncoded else ("domain" if domain and not subcat else "code")
    return {
        "organization": org, "program": program, "outcome_text_original": text,
        "primary_domain": domain, "primary_subcategory": subcat, "primary_target_population": pop,
        "primary_confidence": "none" if uncoded else "high", "uncoded": str(uncoded).lower(),
        "specificity": specificity, "codebook_version": version,
        "source_filename": filename or f"1_1 - {org} - {program} - Logic Model.pdf",
    }


def frame(rows):
    df = od.clean_outcomes(pd.DataFrame(rows))
    return df.assign(**{od.COL_ORG_VIEW: df[od.COL_ORG]})


@pytest.fixture
def sample():
    return frame([
        # Two statements from one program in one skill: the program counts once.
        row("Artwell", "Poets", "Youth name what matters to them", VALUES),
        row("Artwell", "Poets", "Youth set goals that reflect their values", VALUES),
        row("Artwell", "Poets", "Youth feel confident", FEELING),
        # Two programs coded from one shared logic model: they count once.
        row("BalletX", "Dance A", "Dancers care for their bodies", WELLBEING, filename="shared.pdf"),
        row("BalletX", "Dance B", "Dancers care for their health", WELLBEING, filename="shared.pdf"),
        row("Mural Arts", "Murals", "Students think critically about public art", CRITICAL),
        row("Mural Arts", "Murals", "Parents attend workshops", ADULTS, pop="families_caregivers"),
        row("Mural Arts", "Murals", "Participants will show growth in the following areas:", None, uncoded=True),
    ])


# ---------------------------------------------------------------- reference file

def test_reference_has_every_competency_and_skill_once():
    ref = portrait.load_reference()
    assert list(ref.columns) == ["id", "type", "group", "competency", "name", "statement", "has_progression"]
    assert (ref["type"] == "competency").sum() == 14
    assert (ref["type"] == "skill").sum() == 69
    assert ref["id"].is_unique
    assert (ref["name"].str.len() > 0).all() and (ref["statement"].str.len() > 0).all()


def test_slices_match_the_reference_groups_and_the_graphic():
    ref = portrait.load_reference()
    comps = ref[ref["type"] == "competency"]
    assert {s["group"] for s in portrait.SLICES} == set(comps["group"])
    expected = {"Ethical and Creative Problem Solver": ["POG.7", "POG.8", "POG.9"],
                "Culturally Responsive Communicator": ["POG.3", "POG.4"],
                "Strong Community Builder and Collaborator": ["POG.5", "POG.6"],
                "Global Citizen": ["POG.10", "POG.11"],
                "Lifelong Learner": ["POG.1", "POG.2"],
                "Scholar": ["POG.12", "POG.13", "POG.14"]}
    for group, ids in expected.items():
        assert comps.loc[comps["group"] == group, "id"].tolist() == ids
    # Clockwise from the top left, as on the District's graphic; left half individual, right half collective.
    assert [s["group"] for s in portrait.SLICES] == list(expected)
    assert [s["half"] for s in portrait.SLICES] == ["individual", "collective", "collective", "collective",
                                                    "individual", "individual"]


def _luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


@pytest.mark.parametrize("spec", portrait.SLICES, ids=lambda s: s["group"])
def test_slice_labels_keep_enough_contrast(spec):
    a, b = sorted([_luminance(spec["color"]), _luminance(spec["ink"])])
    assert (b + 0.05) / (a + 0.05) >= 4.5


def test_copy_script_takes_the_coder_file_and_refuses_another(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_portrait_reference as script
    text = portrait.REFERENCE_PATH.read_text(encoding="utf-8")
    assert script.check(text) == (14, 69)
    rows = list(csv.reader(text.splitlines()))
    rows[5][2] = "Somewhere Else"
    with pytest.raises(SystemExit):
        script.check("\n".join(",".join(f'"{c}"' for c in r) for r in rows))


# ---------------------------------------------------------------- reading the export

def test_portrait_rows_are_told_apart_from_3x_rows_by_codebook_version(sample):
    v3 = frame([row("Artwell", "Poets", "Youth read more",
                    ("Domain Y1. Academic Learning & Achievement", "Y1.1 Literacy: Reading & Writing"),
                    version="youth_outcomes_v3@3.3.0")])
    mixed = pd.concat([sample, v3], ignore_index=True)
    others, pog = portrait.split_by_codebook(mixed)
    assert len(pog) == len(sample) and len(others) == 1
    assert others[od.COL_SUBCAT].iloc[0].startswith("Y1.1")
    assert not pog[od.COL_DOMAIN].str.startswith("Domain").any()


def test_classify_sorts_skills_competencies_outside_and_uncoded(sample):
    rows = portrait.classify(sample)
    kinds = dict(zip(rows[od.COL_TEXT], rows[portrait.COL_KIND]))
    assert kinds["Youth name what matters to them"] == "skill"
    assert kinds["Students think critically about public art"] == "competency"
    assert kinds["Youth feel confident"] == "outside"
    assert kinds["Participants will show growth in the following areas:"] == "uncoded"
    critical = rows[rows[od.COL_TEXT] == "Students think critically about public art"].iloc[0]
    assert critical[portrait.COL_COMPETENCY] == "POG.7" and critical[portrait.COL_SKILL] == ""


# ---------------------------------------------------------------- counting

def test_counts_are_programs_once_per_place_with_shared_logic_models_once(sample):
    data = portrait.wheel_data(sample)
    comp = data["competencies"]["POG.2"]
    skills = {s["id"]: s for s in comp["skills"]}
    assert skills["POG.2.1"]["programs"] == 1        # two statements, one program
    assert skills["POG.2.2"]["programs"] == 1        # two programs, one shared logic model
    assert comp["programs"] == 2
    lifelong = next(s for s in data["slices"] if s["group"] == "Lifelong Learner")
    assert lifelong["programs"] == 2
    assert data["competencies"]["POG.7"]["programs"] == 1
    assert data["competencies"]["POG.7"]["onlyPrograms"] == 1   # named the competency, no single skill
    assert all(s["programs"] == 0 for s in data["competencies"]["POG.7"]["skills"])


def test_outside_codes_stay_off_the_wheel_and_families_stay_apart(sample):
    data = portrait.wheel_data(sample)
    assert [o["id"] for o in data["outside"]] == ["OUT.1", "OUT.2", "OUT.3", "OUT.4", "OUT.6", "OUT.5"]
    assert [o["name"] for o in data["outside"]][:2] == ["Feeling, belief or identity",
                                                        "Relationship a young person has"]
    adults = [o for o in data["outside"] if not o["youth"]]
    assert [o["id"] for o in adults] == ["OUT.5"] and adults[0]["programs"] == 1
    assert "OUT" not in data["competencies"]
    assert all(not c.startswith("OUT") for s in data["slices"] for c in s["competencies"])


def test_youth_share_leaves_out_uncoded_rows_and_families_staff_programs(sample):
    share = portrait.youth_share(sample)
    # Youth results: 2 values, 2 well-being, 1 critical thinking, 1 feeling. OUT.5 and the uncoded row are out.
    assert share["results"] == 6 and share["portrait"] == 5 and share["outside"] == 1
    assert share["portrait_pct"] + share["outside_pct"] == 100
    assert portrait.share_sentence(share) == ("Of the results partners name for young people, 83% match a "
                                              "Portrait skill or competency and 17% fall outside the Portrait.")


def test_uncoded_rows_count_nowhere(sample):
    rows = portrait.pick_rows(sample, None)
    assert "Participants will show growth in the following areas:" not in set(rows[od.COL_TEXT])


def test_picks_narrow_the_table(sample):
    texts = lambda pick: set(portrait.pick_rows(sample, pick)[od.COL_TEXT])
    assert texts({"kind": "skill", "id": "POG.2.1"}) == {"Youth name what matters to them",
                                                          "Youth set goals that reflect their values"}
    assert len(texts({"kind": "slice", "id": "Lifelong Learner"})) == 4
    assert texts({"kind": "only", "id": "POG.7"}) == {"Students think critically about public art"}
    assert texts({"kind": "outside", "id": "OUT.5"}) == {"Parents attend workshops"}


# ---------------------------------------------------------------- what people read

def test_names_on_screen_carry_numbers_never_bare_codes(sample):
    assert od.goal_name("POG.2.1 Know my values and aspirations") == "Know my values and aspirations (2.1)"
    assert od.goal_name("OUT.3 Status or attainment") == "Status or attainment"
    critical = sample.loc[sample[od.COL_TEXT] == "Students think critically about public art", od.COL_SUBCAT].iloc[0]
    assert od.goal_name(critical) == "Think Critically (7), no single skill"
    assert portrait.pick_name({"kind": "skill", "id": "POG.2.1"}) == "Know my values and aspirations (2.1)"
    assert portrait.pick_name({"kind": "competency", "id": "POG.12"}) == "Apply Academic Knowledge and Skills (12)"
    assert portrait.pick_name({"kind": "slice", "id": "Scholar"}) == "A scholar, prepared for post-secondary life"


def test_names_and_statements_come_from_the_reference_word_for_word(sample):
    ref = portrait.load_reference().set_index("id")
    data = portrait.wheel_data(sample)
    for cid, comp in data["competencies"].items():
        assert comp["name"] == ref.loc[cid, "name"] and comp["statement"] == ref.loc[cid, "statement"]
        for skill in comp["skills"]:
            assert skill["name"] == ref.loc[skill["id"], "name"]
            assert skill["statement"] == ref.loc[skill["id"], "statement"]


def test_examples_keep_the_split_rule(sample):
    split = frame([{**row("Artwell", "Poets", "Youth name their values and make friends", VALUES),
                    "outcome_text_atomic": "Youth name their values", "row_id": "R1"}])
    example = portrait.wheel_data(split)["competencies"]["POG.2"]["skills"][0]["examples"][0]
    assert example["t"] == "Youth name their values and make friends"   # the full sentence, never the part alone
    assert example["m"] == [[0, len("Youth name their values")]]


def test_banner_and_credit_wording():
    assert portrait.TESTING_BANNER.format(version="0.1.0") == (
        "Testing version (Portrait of a Graduate codebook 0.1.0). Codes are not yet checked by a person. "
        "For internal use.")
    assert portrait.CREDIT == ("Portrait of a Graduate Competency Framework, written by Building 21 for the School "
                               "District of Philadelphia, licensed CC BY-NC-SA 4.0.")
    assert portrait.codebook_version(pd.DataFrame({"codebook_version": [VERSION]})) == "0.1.0"


def test_a_mixed_file_never_lets_portrait_rows_into_the_3x_pages(sample):
    """Severin's case (2026-11-10): one file with 3.x and Portrait rows made the 3.x wheel show 27 domains."""
    v3 = frame([row("Artwell", "Poets", "Youth read more",
                    ("Domain Y1. Academic Learning & Achievement", "Y1.1 Literacy: Reading & Writing"),
                    version="youth_outcomes_v3@3.3.0")])
    blank = sample.assign(codebook_version="")      # an export that left the version blank
    for portrait_rows in (sample, blank):
        others, pog = portrait.split_by_codebook(pd.concat([v3, portrait_rows], ignore_index=True))
        coded = others[od.COL_DOMAIN] != "Uncoded"   # a blank-version uncoded row cannot be told apart; it counts nowhere
        assert others.loc[coded, od.COL_DOMAIN].str.startswith("Domain").all() and coded.sum() == 1
        assert len(pog) == len(sample) - (portrait_rows is blank)
