"""
The Portrait of a Graduate view's data: which parts of the School District of
Philadelphia Portrait of a Graduate partner programs work toward.

The Portrait rows come from the coder's Portrait codebook (codebook_version
"portrait_of_a_graduate@0.1.0"), in the same export layout as the 3.3.0 file:
`primary_domain` is a competency ("POG.2 Persist with purpose and adapt with
confidence"), `primary_subcategory` a skill ("POG.2.1 Know my values and
aspirations"), empty when the statement names a competency but no single skill
(`specificity` "domain"). Competency "OUT" holds results the Portrait does not
name; it is codebook-defined, never a part of the Portrait, so it is never drawn
as a slice of the wheel.

Rules this module keeps:

* Portrait rows never mix with 3.x rows in one count: `split_by_codebook` takes
  them apart by `codebook_version`.
* Counts are programs, not statements. A program counts once per skill,
  competency and slice, however many of its statements land there, and programs
  that share one logic model count once (outcomes_data.logic_model_programs).
* Uncoded rows count nowhere. "Families, staff, programs or systems" (OUT.5)
  stays out of every youth figure.
* Nothing is totalled, ranked or scored, and progression stages are never shown.
* Every competency and skill name and "I can" statement is read word for word
  from reference/portrait_skills_11.2.csv (scripts/build_portrait_reference.py).

No Streamlit calls, so tests and other tools can import it.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional, Union

import pandas as pd

import outcomes_data as od

REFERENCE_PATH = Path(__file__).resolve().parent / "reference" / "portrait_skills_11.2.csv"
COL_VERSION = "codebook_version"
COL_UNCODED = "uncoded"
VERSION_PREFIX = "portrait_of_a_graduate"
DEFAULT_VERSION = "0.1.0"
EXAMPLES = 3   # example statements under each skill

# Helper columns added by classify().
COL_COMPETENCY = "pog_competency"   # "POG.2", "OUT", or "" when uncoded
COL_SKILL = "pog_skill"             # "POG.2.1", "OUT.3", or "" for a competency-only or uncoded row
COL_KIND = "pog_kind"               # skill, competency (named no single skill), outside, or uncoded

KIND_SKILL, KIND_COMPETENCY, KIND_OUTSIDE, KIND_UNCODED = "skill", "competency", "outside", "uncoded"
OUTSIDE = "OUT"
ADULTS = "OUT.5"   # results for families, staff, programs or systems: never in a youth figure

# The six slices, clockwise from the top left as on the District's graphic. `group` is the
# reference file's value; `title` splits the graphic's wording into plain and bold parts.
# Colours are taken from the graphic (approximate; no official District palette was found). Two are
# a shade darker than the graphic so white labels keep at least 4.5:1 contrast; `ink` is the label colour.
NAVY = "#0b1640"
SLICES = [
    {"group": "Ethical and Creative Problem Solver", "title": ["An ethical and creative ", "problem solver"],
     "icon": "bulb", "color": "#1f4e8c", "ink": "#ffffff", "half": "individual"},
    {"group": "Culturally Responsive Communicator", "title": ["A culturally responsive ", "communicator"],
     "icon": "speech", "color": "#b95310", "ink": "#ffffff", "half": "collective"},
    {"group": "Strong Community Builder and Collaborator", "title": ["A strong community builder and ", "collaborator"],
     "icon": "handshake", "color": "#ffb000", "ink": NAVY, "half": "collective"},
    {"group": "Global Citizen", "title": ["A ", "global citizen"],
     "icon": "globe", "color": "#ff7722", "ink": NAVY, "half": "collective"},
    {"group": "Lifelong Learner", "title": ["A self-aware, persistent, ", "lifelong learner"],
     "icon": "brain", "color": "#12b3de", "ink": NAVY, "half": "individual"},
    {"group": "Scholar", "title": ["A ", "scholar", ", prepared for post-secondary life"],
     "icon": "cap", "color": "#2e77b8", "ink": "#ffffff", "half": "individual"},
]
HALVES = {"individual": "Prepared for individual success", "collective": "Prepared to build collective success"}

# The codebook-defined "outside the Portrait" codes, in the order the panel lists them. The names are the
# shorter wording Severin set for this panel (the codebook's OUT.6 adds "the Portrait does not name").
OUTSIDE_CODES = [
    ("OUT.1", "Feeling, belief or identity"),
    ("OUT.2", "Relationship a young person has"),
    ("OUT.3", "Status or attainment"),
    ("OUT.4", "Health, safety or services"),
    ("OUT.6", "Other skill or knowledge"),
    (ADULTS, "Families, staff, programs or systems"),
]

TESTING_BANNER = ("Testing version (Portrait of a Graduate codebook {version}). Codes are not yet checked by a "
                  "person. For internal use.")
CREDIT = ("Portrait of a Graduate Competency Framework, written by Building 21 for the School District of "
          "Philadelphia, licensed CC BY-NC-SA 4.0.")

_COMPETENCY = re.compile(r"^\s*(POG\.\d+|OUT)\b")
_SKILL = re.compile(r"^\s*(POG\.\d+\.\d+|OUT\.\d+)\b")


# =============================================================================
# REFERENCE AND LOADING
# =============================================================================


def load_reference(path: Union[str, Path] = REFERENCE_PATH) -> pd.DataFrame:
    """The 14 competencies and 69 skills, in the file's order, as text (an empty frame if the file is missing)."""
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except FileNotFoundError:
        return pd.DataFrame(columns=["id", "type", "group", "competency", "name", "statement", "has_progression"])


def number(code: str) -> str:
    """ "POG.2.1" -> "2.1"; "POG.12" -> "12". How codes appear on screen, in brackets after a name."""
    return code.removeprefix("POG.")


def is_portrait(df: pd.DataFrame) -> pd.Series:
    """Rows coded with the Portrait codebook, told apart from 3.x rows by `codebook_version`.

    A file without that column counts as Portrait only when its competencies are Portrait ones.
    """
    if COL_VERSION in df.columns:
        return df[COL_VERSION].fillna("").astype(str).str.strip().str.startswith(VERSION_PREFIX)
    return df[od.COL_DOMAIN].fillna("").astype(str).str.match(_COMPETENCY)


def split_by_codebook(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(everything else, Portrait rows), each with a fresh index, so the two never meet in one count."""
    mask = is_portrait(df)
    return df[~mask].reset_index(drop=True), df[mask].reset_index(drop=True)


def codebook_version(df: pd.DataFrame) -> str:
    """ "0.1.0" from "portrait_of_a_graduate@0.1.0" (the newest if a file holds several)."""
    if COL_VERSION not in df.columns:
        return DEFAULT_VERSION
    versions = sorted({str(v).split("@", 1)[1] for v in df[COL_VERSION].dropna().unique() if "@" in str(v)})
    return versions[-1] if versions else DEFAULT_VERSION


def _truthy(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """`df` with the competency, skill and kind of each row (COL_COMPETENCY, COL_SKILL, COL_KIND).

    A row is uncoded when the coder says so (`uncoded`, or `specificity` "uncoded") or names no competency.
    A Portrait competency with no skill is "competency"; an OUT code is "outside"; the rest are "skill".
    """
    competency = df[od.COL_DOMAIN].fillna("").astype(str).str.extract(_COMPETENCY, expand=False).fillna("")
    skill = df[od.COL_SUBCAT].fillna("").astype(str).str.extract(_SKILL, expand=False).fillna("")
    # A skill always belongs to its competency (POG.5.1 is in POG.5); one that doesn't is not trusted.
    skill = skill.where([s.startswith(c + ".") for s, c in zip(skill, competency)], "")
    uncoded = competency.eq("")
    if COL_UNCODED in df.columns:
        uncoded |= _truthy(df[COL_UNCODED])
    if od.COL_SPECIFICITY in df.columns:
        uncoded |= df[od.COL_SPECIFICITY].fillna("").astype(str).str.lower().eq("uncoded")
    kind = pd.Series(KIND_SKILL, index=df.index)
    kind[skill.eq("")] = KIND_COMPETENCY
    kind[competency.eq(OUTSIDE)] = KIND_OUTSIDE
    kind[uncoded] = KIND_UNCODED
    return df.assign(**{COL_COMPETENCY: competency.where(~uncoded, ""), COL_SKILL: skill.where(~uncoded, ""),
                        COL_KIND: kind})


def plain_label(label: object) -> Optional[str]:
    """A Portrait goal label as people read it, or None when it isn't one.

    "POG.2.1 Know my values and aspirations" -> "Know my values and aspirations (2.1)";
    "POG2 Persist with purpose..., no specific goal" (a competency-only row after cleaning) ->
    "Persist with purpose... (2), no specific skill"; "OUT.3 Status or attainment" -> "Status or attainment".
    """
    text = str(label)
    match = re.match(r"^\s*POG\.?(\d+(?:\.\d+)?)\.?\s+(.*)$", text)
    if match:
        name = match.group(2)
        if name.endswith(od.DOMAIN_ONLY_SUFFIX):
            return f"{name.removesuffix(od.DOMAIN_ONLY_SUFFIX)} ({match.group(1)}), no single skill"
        return f"{name} ({match.group(1)})"
    match = re.match(r"^\s*OUT(?:\.\d+)?\s+(.*)$", text)
    return match.group(1) if match else None


# =============================================================================
# COUNTS
# =============================================================================


def youth_share(df: pd.DataFrame) -> dict:
    """How the results partners name for young people split between the Portrait and outside it.

    Counts coded results (one per coded statement part), leaving out uncoded rows and OUT.5, which covers
    adults and organizations. Returns {"results", "portrait", "outside", "portrait_pct", "outside_pct"}; the two
    percentages are whole numbers that add up to 100 (both 0 when there are no youth results).
    """
    rows = df if COL_KIND in df.columns else classify(df)
    youth = rows[(rows[COL_KIND] != KIND_UNCODED) & (rows[COL_SKILL] != ADULTS)]
    inside = int(youth[COL_KIND].isin([KIND_SKILL, KIND_COMPETENCY]).sum())
    total = len(youth)
    pct = round(100 * inside / total) if total else 0
    return {"results": total, "portrait": inside, "outside": total - inside,
            "portrait_pct": pct, "outside_pct": (100 - pct) if total else 0}


def share_sentence(share: dict) -> str:
    """The plain line above the wheel."""
    if not share["results"]:
        return "No results for young people are coded in this view yet."
    return (f"Of the results partners name for young people, {share['portrait_pct']}% match a Portrait skill or "
            f"competency and {share['outside_pct']}% fall outside the Portrait.")


def _examples(rows: pd.DataFrame, seed_text: str) -> list[dict]:
    """A few distinct statements for the side panel, picked the same way on every run (split-part rule kept)."""
    seed = int(hashlib.md5(seed_text.encode("utf-8")).hexdigest()[:8], 16)
    return [od.outcome_payload(k) for k in od.sample_outcomes(rows[od.COL_OUTCOME], EXAMPLES, seed=seed)]


def _programs(labels: pd.Series) -> int:
    return int(labels.nunique())


def wheel_data(df: pd.DataFrame, reference: Optional[pd.DataFrame] = None) -> dict:
    """Everything the Portrait wheel and its panels draw, from the (filtered) Portrait rows.

    {"slices": [...six, clockwise from the top left...], "competencies": {id: ...}, "outside": [...],
     "share": youth_share, "halves": HALVES, "sig": ...}. Each count is the number of programs naming a goal
    there, with programs that share a logic model counted once.
    """
    reference = load_reference() if reference is None else reference
    rows = classify(df) if COL_KIND not in df.columns else df
    coded = rows[rows[COL_KIND] != KIND_UNCODED]
    programs = od.logic_model_programs(coded) if not coded.empty else pd.Series(dtype=str)
    coded = coded.assign(_program=programs)

    comps = reference[reference["type"] == "competency"]
    skills = reference[reference["type"] == "skill"]
    competencies: dict[str, dict] = {}
    for _, comp in comps.iterrows():
        cid = comp["id"]
        in_comp = coded[coded[COL_COMPETENCY] == cid]
        only = in_comp[in_comp[COL_KIND] == KIND_COMPETENCY]
        skill_list = []
        for _, skill in skills[skills["competency"] == cid].iterrows():
            in_skill = in_comp[in_comp[COL_SKILL] == skill["id"]]
            skill_list.append({"id": skill["id"], "num": number(skill["id"]), "name": skill["name"],
                               "statement": skill["statement"], "programs": _programs(in_skill["_program"]),
                               "examples": _examples(in_skill, skill["id"]) if len(in_skill) else []})
        competencies[cid] = {
            "id": cid, "num": number(cid), "name": comp["name"], "statement": comp["statement"],
            "group": comp["group"], "programs": _programs(in_comp["_program"]),
            "onlyPrograms": _programs(only["_program"]),
            "onlyExamples": _examples(only, cid) if len(only) else [],
            "skills": skill_list,
        }

    slices = []
    for spec in SLICES:
        ids = comps.loc[comps["group"] == spec["group"], "id"].tolist()
        in_slice = coded[coded[COL_COMPETENCY].isin(ids)]
        slices.append({**spec, "id": spec["group"], "name": "".join(spec["title"]), "competencies": ids,
                       "programs": _programs(in_slice["_program"])})

    outside = []
    for code, name in OUTSIDE_CODES:
        in_code = coded[coded[COL_SKILL] == code]
        outside.append({"id": code, "name": name, "youth": code != ADULTS,
                        "programs": _programs(in_code["_program"]),
                        "examples": _examples(in_code, code) if len(in_code) else []})

    data = {"slices": slices, "competencies": competencies, "outside": outside, "share": youth_share(rows),
            "halves": HALVES, "navy": NAVY}
    data["sig"] = hashlib.md5(repr(sorted(
        (k, v["programs"], v["onlyPrograms"], tuple(s["programs"] for s in v["skills"]))
        for k, v in competencies.items()) + [(o["id"], o["programs"]) for o in outside]
        + [len(rows)]).encode("utf-8")).hexdigest()
    return data


def pick_rows(df: pd.DataFrame, pick: Optional[dict]) -> pd.DataFrame:
    """The coded rows a wheel pick stands for: a slice, a competency, a skill or an outside-the-Portrait code.

    With nothing picked, every coded row (uncoded rows are left out here as everywhere in this view).
    """
    rows = classify(df) if COL_KIND not in df.columns else df
    rows = rows[rows[COL_KIND] != KIND_UNCODED]
    if not pick:
        return rows
    kind, pid = pick.get("kind"), pick.get("id")
    if kind == "slice":
        reference = load_reference()
        ids = reference.loc[(reference["type"] == "competency") & (reference["group"] == pid), "id"].tolist()
        return rows[rows[COL_COMPETENCY].isin(ids)]
    if kind == "competency":
        return rows[rows[COL_COMPETENCY] == pid]
    if kind == "only":
        return rows[(rows[COL_COMPETENCY] == pid) & (rows[COL_KIND] == KIND_COMPETENCY)]
    if kind in ("skill", "outside"):
        return rows[rows[COL_SKILL] == pid]
    return rows


def pick_name(pick: Optional[dict], reference: Optional[pd.DataFrame] = None) -> Optional[str]:
    """What a pick is called on screen ("Know my values and aspirations (2.1)"), for the table's heading."""
    if not pick:
        return None
    reference = load_reference() if reference is None else reference
    kind, pid = pick.get("kind"), pick.get("id")
    if kind == "slice":
        spec = next((s for s in SLICES if s["group"] == pid), None)
        return "".join(spec["title"]) if spec else None
    if kind in ("skill", "outside") and pid in dict(OUTSIDE_CODES):
        return dict(OUTSIDE_CODES)[pid]
    match = reference[reference["id"] == pid]
    if match.empty:
        return None
    name = f"{match.iloc[0]['name']} ({number(pid)})"
    return f"{name}, no single skill" if kind == "only" else name


ENV_VAR = "PORTRAIT_CSV"
LOCAL_PATTERN = "*portrait*.csv"


def find_local_file(data_dir: Union[str, Path] = Path(__file__).resolve().parent / "data") -> Optional[Path]:
    """A Portrait export to open on start: PORTRAIT_CSV if set, else the newest data/*portrait*.csv, else None."""
    import os
    env = os.environ.get(ENV_VAR)
    if env and Path(env).is_file():
        return Path(env)
    found = sorted(Path(data_dir).glob(LOCAL_PATTERN), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None
