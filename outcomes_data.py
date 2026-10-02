"""
Data layer for the outcomes dashboard.

Everything here is plain pandas with no Streamlit calls, so it can be imported
by the app, by tests, or by other tools (for example a script that exports a
filtered view to GeoJSON for a Leaflet map).

Sections:

* CONFIG       - file locations, column names, clean-up tables, labels
* LOADING      - reading and cleaning a coded-outcomes export and the codebook
* FILTERING    - DataFrame in, DataFrame out
* AGGREGATION  - tables that feed the charts and the peer matrix
"""

from __future__ import annotations

import html
import os
import re
import textwrap
from pathlib import Path
from typing import IO, Iterable, Optional, Sequence, Union

import numpy as np
import pandas as pd

# =============================================================================
# CONFIG
# =============================================================================

# Name of the export produced by the Qualitative Outcomes Coder.
DATA_FILENAME = "verified_coded_outcomes(5).csv"

# Set OUTCOMES_CSV to point the app at a file somewhere else, e.g.
#   OUTCOMES_CSV=/path/to/latest_export.csv streamlit run app.py
DATA_ENV_VAR = "OUTCOMES_CSV"

APP_DIR = Path(__file__).resolve().parent

# Places the app looks for the CSV, in order. The first one that exists wins.
DEFAULT_DATA_PATHS = [
    APP_DIR / "data" / DATA_FILENAME, # data/ folder (git-ignored, so partner data is never committed)
    APP_DIR / DATA_FILENAME,          # next to app.py
    Path.cwd() / DATA_FILENAME,       # wherever `streamlit run` was launched
]

# Every subcategory in the "original" codebook (v1.1.1), exported from the
# Qualitative Outcomes Coder's codebooks/original.ts. Lets the dashboard show
# goals that no program targets yet. Regenerate it when the codebook changes.
CODEBOOK_PATH = APP_DIR / "reference" / "codebook_subcategories.csv"
# The same list for codebook 3.x (codes like "Y4.2"), exported from the coder's
# codebooks/youthOutcomesV3.data.ts. load_codebook_for() picks the one that
# matches the loaded file's codes.
CODEBOOK_V3_PATH = APP_DIR / "reference" / "codebook_subcategories_v3.csv"

# Column names used throughout the app. Keeping them in one place means a
# renamed column in a future export only needs changing here.
COL_ORG = "organization"
COL_PROGRAM = "program"
COL_TEXT = "outcome_text_original"
COL_DOMAIN = "primary_domain"
COL_SUBCAT = "primary_subcategory"
COL_POP = "primary_target_population"
COL_CONF = "primary_confidence"

# Optional columns: used when present, ignored when absent.
COL_SOURCE_FILE = "source_filename"
COL_QA = "qa_status"
COL_ATOMIC = "outcome_text_atomic"
COL_NOTES = "notes"
COL_PARTNER_ID = "partner_id"       # district files carry a partner ID instead of an organization name
COL_SOURCE_TYPE = "source_type"     # where the outcome text came from (logic_model, program_description, ...)
COL_SPECIFICITY = "specificity"     # codebook 3.1+: code, domain (domain-only) or uncoded

# Organization and program are optional: district program-description files
# have neither an organization name nor (always) a program, so they fall back
# to the partner ID and placeholders instead of being refused.
REQUIRED_COLUMNS = [COL_TEXT, COL_DOMAIN, COL_SUBCAT, COL_POP, COL_CONF]

# Derived columns added by clean_outcomes().
COL_GRANTEE = "grantee_from_filename"   # organization parsed from the logic model's file name
COL_ORG_VIEW = "org_view"               # whichever organization column the user chose to group by
COL_DOMAIN_NUM = "domain_number"        # 3 for "Domain 3. ...", used for sorting
COL_OUTCOME = "outcome"                 # the coded (atomic) outcome, falling back to the original text
COL_FULL = "full_statement"             # the original statement, only when the coder split it
COL_DOMAIN_SHORT = "domain_short"       # "3. Social & Emotional Learning" for compact axis labels
COL_PROGRAM_LABEL = "program_label"     # "Org" or "Org: Program" when an organization has several
COL_PRIORITY = "priority"               # the plain-language priority a row's goal belongs to (PRIORITIES)

# Placeholder labels for missing values, so nothing silently drops out of a chart.
UNCODED_DOMAIN = "Uncoded"
UNASSIGNED_SUBCAT = "Unassigned subcategory"
UNKNOWN_POP = "unspecified"
UNKNOWN_ORG = "Unknown organization"
UNKNOWN_PROGRAM = "Unknown program"
# Codebook 3.1 codes a statement that names a domain but nothing specific to
# the domain alone. Those rows get a goal label of their own, e.g.
# "Y4 Social & Emotional Skills (CASEL), no specific goal".
DOMAIN_ONLY_SUFFIX = ", no specific goal"

# source_type values. A blank means the row predates the column, when every
# coded outcome came from a logic model. Early district files used
# "district_program_outcomes" for what is now "program_description".
SOURCE_LOGIC_MODEL = "logic_model"
SOURCE_ALIASES = {"district_program_outcomes": "program_description"}
SOURCE_LABELS = {
    "logic_model": "logic models",
    "program_description": "program descriptions",
    "other_outcome_text": "other outcome text",
}

# Confidence levels in review order. "none" means the coder could not code it.
CONFIDENCE_ORDER = ["high", "medium", "low", "none"]

# The same organization is sometimes written differently across logic models.
# Map each variant to one canonical spelling so counts and peer matches are not
# split. Only unambiguous duplicates belong here; distinct departments of the
# same institution (e.g. the Penn programs) are intentionally left separate.
ORG_ALIASES = {
    "ASAP (After School Activities Partnerships)": "After School Activities Partnerships (ASAP)",
    "Artwell": "ArtWell",
    "Great Philadelphia YMCA": "Greater Philadelphia YMCA",
    "LNESC": "LNESC (LULAC National Educational Service Centers, Inc.)",
    "Oxford Circle Christian Community Development Association":
        "Oxford Circle Community Development Association (OCCCDA)",
    # Abbreviation and a program name used as the organization in some parts
    # of the multi-part Historic Fair Hill logic model.
    "HFH": "Historic Fair Hill, Inc.",
    "The Commons": "Historic Fair Hill, Inc.",
    # Variants that appear in the 3.x recode export (2026-10-02).
    "ASAP After School Activities Partnerships": "After School Activities Partnerships (ASAP)",
    "After School Activities Partnerships": "After School Activities Partnerships (ASAP)",
    "ArtWell Collaborative Inc": "ArtWell",
    "Heights": "Heights Philadelphia",
    "Historic Fair Hill (HFH)": "Historic Fair Hill, Inc.",
    "Cobbs Creek Community Environmental Education Center, Inc. (CCCEEC, Inc.)":
        "Cobbs Creek Community Environmental Education Center, Inc.",
}

# Values that were extracted into the organization column but are not names.
# They are treated as missing and back-filled from the file name.
JUNK_ORG_NAMES = {"Coded by:", "Coded by-"}

# Logic model files are named "<id>_<id> - <Organization> - <Program> - Logic Model.<ext>",
# sometimes followed by " — Part 2 of 6".
FILENAME_PATTERN = re.compile(r"^\s*\d+_\d+\s+-\s+(?P<org>.+?)\s+-\s+(?P<program>.+?)\s+-\s+Logic Model", re.I)

# Plotly hover boxes do not wrap text, so outcome samples are wrapped manually.
HOVER_WRAP_WIDTH = 70
HOVER_MAX_CHARS = 220
HOVER_SAMPLE_SIZE = 3

# Friendly labels for the target population codes.
POPULATION_LABELS = {
    "students_youth": "Students & youth",
    "educators_staff": "Educators & staff",
    "community_neighborhood": "Community & neighborhood",
    "school_district_system": "School / district system",
    "families_caregivers": "Families & caregivers",
    "partner_organizations": "Partner organizations",
    "mentors_volunteers": "Mentors & volunteers",
    "multiple_populations": "Multiple populations",
    UNKNOWN_POP: "Unspecified",
}

# Target populations grouped for charts. The small groups share an "Other"
# bucket so a stacked chart never needs more than seven colors. Order here is
# the stacking and legend order.
POPULATION_GROUPS = {
    "students_youth": "Students & youth",
    "educators_staff": "Educators & staff",
    "community_neighborhood": "Community",
    "school_district_system": "Schools & systems",
    "families_caregivers": "Families & caregivers",
    "partner_organizations": "Partner organizations",
}
OTHER_POPULATION = "Other or mixed"
POPULATION_GROUP_ORDER = list(POPULATION_GROUPS.values()) + [OTHER_POPULATION]

# What the size of a block (or length of a bar) represents in coverage views.
MEASURE_OUTCOMES = "Outcome statements"
MEASURE_ORGS = "Organizations"
MEASURE_PROGRAMS = "Programs"
MEASURES = [MEASURE_ORGS, MEASURE_OUTCOMES]
# The sunburst also counts programs, and leads with them.
SUNBURST_MEASURES = [MEASURE_PROGRAMS, MEASURE_OUTCOMES, MEASURE_ORGS]
MEASURE_COLUMNS = {MEASURE_PROGRAMS: "programs", MEASURE_OUTCOMES: "outcomes", MEASURE_ORGS: "organizations"}

ORG_GROUPING_OPTIONS = {
    "Name in the logic model": COL_ORG,
    "Grantee from the file name": COL_GRANTEE,
}

# Plain-language priorities, named the way school plans and public agendas name
# things, so a reader can find "Attendance" without knowing it is goal 11.5.
# Each rule lists codebook numbers: a domain like "3" or a goal like "11.5" from
# codebook 1.x, and a domain like "Y4" or a code like "Y1.13" from codebook 3.x.
# The two schemes never collide, so one table serves files coded with either.
# A row takes the priority with the most specific matching number, so the
# school measures win over their domain's catch-all. The list is editorial:
# edit it here and the landing chart follows.
PRIORITIES: list[tuple[str, tuple[str, ...]]] = [
    ("Attendance", ("11.5", "Y1.13")),
    ("Literacy", ("11.1", "Y1.1")),
    ("Math", ("11.2", "Y1.3")),
    ("Graduation & on-track", ("11.6", "Y1.15", "Y1.17")),
    ("Other academic learning", ("11", "Y1")),
    ("Mental health", ("7.2", "7.3", "7.4", "Y8.6", "Y8.7", "Y8.8", "Y8.9")),
    ("Physical health & safety", ("7", "Y8")),
    ("College & career", ("8", "Y7", "Y1.18")),
    ("Social-emotional skills", ("3", "Y4")),
    ("Belonging & relationships", ("2", "Y3")),
    ("Joy & interest in learning", ("1", "Y2")),
    ("Engagement & study habits", ("4", "Y1.9", "Y1.10", "Y1.11", "Y1.12")),
    ("Positive youth development", ("5", "Y5")),
    ("Civic voice & community", ("6", "Y6")),
    ("Access & equity", ("9", "A2")),
    ("Staff & system capacity", ("10", "A1", "A3")),
    ("Families & basic needs", ("12", "F1", "F2")),
]
UNCODED_PRIORITY = "Not coded"
# Priorities schools report on, which the findings compare with the most shared aim.
SCHOOL_MEASURES = ["Attendance", "Literacy", "Math"]

# One standing line under the filter bar. Every audience review found the same
# first misreading: taking what programs intend for what they achieved.
INTENT_NOTE = ("Outcomes that programs <b>intend</b>, taken from their logic models. "
               "They are not measured results.")


def intent_note(sources: Iterable[str] = (SOURCE_LOGIC_MODEL,)) -> str:
    """INTENT_NOTE, naming the documents the loaded outcomes actually came from."""
    labels = [SOURCE_LABELS.get(s, s.replace("_", " ")) for s in sorted(set(sources), key=str)]
    if not labels or labels == [SOURCE_LABELS[SOURCE_LOGIC_MODEL]]:
        return INTENT_NOTE
    named = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
    return f"Outcomes that programs <b>intend</b>, taken from their {named}. They are not measured results."


# =============================================================================
# LOADING
# =============================================================================


class MissingColumnsError(ValueError):
    """Raised when the CSV does not contain the columns the dashboard needs."""


def resolve_data_path() -> Optional[Path]:
    """Return the first CSV location that exists, or None if none do.

    The OUTCOMES_CSV environment variable takes priority over the defaults.
    """
    env_path = os.environ.get(DATA_ENV_VAR)
    candidates = ([Path(env_path)] if env_path else []) + DEFAULT_DATA_PATHS
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def parse_filename(filename: object) -> tuple[Optional[str], Optional[str]]:
    """Pull (organization, program) out of a logic model file name.

    >>> parse_filename("83_14 - BalletX - Dance eXchange - Logic Model.pdf")
    ('BalletX', 'Dance eXchange')
    """
    if not isinstance(filename, str):
        return None, None
    match = FILENAME_PATTERN.match(filename)
    if not match:
        return None, None
    return match.group("org").strip(), match.group("program").strip()


# Codebook 3.x prefixes its numbers with the part (Y young people, F families,
# A staff, organizations and systems). Parts sort in that order, after 1.x's
# plain numbers would, so a file mixing both schemes still sorts sensibly.
PART_OFFSETS = {"": 0, "Y": 0, "F": 100, "A": 200}
DOMAIN_CODE_PATTERN = re.compile(r"\s*Domain\s+([YFA]?)(\d+)\b")
CODE_PATTERN = re.compile(r"\s*([YFA]?)(\d+(?:\.\d+)*)\b")


def domain_code(domain: object) -> Optional[str]:
    """'3' for 'Domain 3. Social & ...', 'Y4' for 'Domain Y4. Social & ...'; None when there is no number."""
    match = DOMAIN_CODE_PATTERN.match(str(domain))
    return match.group(1) + match.group(2) if match else None


def _domain_number(domain: object) -> float:
    """A sort key: 3.0 for 'Domain 3. ...', 4.0 for 'Domain Y4. ...', 201.0 for 'Domain A1. ...'.

    Infinity for anything unparseable, so it sorts last.
    """
    match = DOMAIN_CODE_PATTERN.match(str(domain))
    return float(PART_OFFSETS[match.group(1)] + int(match.group(2))) if match else float("inf")


def domain_short(domain: str) -> str:
    """'Domain 3. Social & Emotional Learning (CASEL-aligned)' -> '3. Social & Emotional Learning'."""
    short = re.sub(r"^\s*Domain\s+", "", domain)
    return re.sub(r"\s*\(.*?\)\s*$", "", short)


def subcategory_sort_key(label: str) -> tuple:
    """Sort '3.1.4 Confidence...' after '3.1.2 ...' and before '10.1 ...' (numeric, not alphabetical).

    3.x codes sort the same way within their part: Y1.2 before Y1.10, all Y before F, all F before A.
    """
    match = CODE_PATTERN.match(str(label))
    if not match:
        return ((float("inf"),), str(label))
    parts = [int(p) for p in match.group(2).strip(".").split(".") if p.isdigit()]
    parts[0] += PART_OFFSETS[match.group(1)]
    # Numbers in their own tuple, so "Y4 ..." (a domain-only label) sorts just
    # before "Y4.1 ..." instead of comparing its text with a number.
    return (tuple(parts), str(label))


def _code_number(domain: object, subcategory: str) -> Optional[str]:
    """The most specific codebook number for a row: '3.1.4' or 'Y4.2' from its goal, else '3' or 'Y4'.

    `domain` is the domain label, or (as before) its number from _domain_number().
    """
    match = re.match(r"\s*([YFA]?\d+(?:\.\d+)+)\b", str(subcategory))
    if match:
        return match.group(1)
    if isinstance(domain, str):
        return domain_code(domain)
    if pd.isna(domain) or domain == float("inf"):
        return None
    return str(int(domain))


def priority_of(domain: object, subcategory: str) -> str:
    """The plain-language priority (PRIORITIES) for a row's domain and goal.

    The most specific matching number wins ("11.5" over "11", "Y1.13" over "Y1").
    """
    code = _code_number(domain, subcategory)
    if code is None:
        return UNCODED_PRIORITY
    best, best_len = UNCODED_PRIORITY, -1
    for label, numbers in PRIORITIES:
        for n in numbers:
            if (code == n or code.startswith(n + ".")) and len(n) > best_len:
                best, best_len = label, len(n)
    return best


def codebook_scheme(domains: Iterable[str]) -> set[str]:
    """Which codebook numbering the domain labels use: {'1.x'}, {'3.x'}, both, or neither."""
    schemes = set()
    for domain in domains:
        code = domain_code(domain)
        if code:
            schemes.add("3.x" if code[0].isalpha() else "1.x")
    return schemes


def _merge_case_variants(names: pd.Series) -> pd.Series:
    """Spell names that differ only in capitals ('PRIDE YOUTH SERVICES') one way.

    Prefers a spelling that is not all capitals, then the one most rows use.
    """
    present = names.dropna()
    if present.empty:
        return names

    def pick(spellings: pd.Series) -> str:
        counts = spellings.value_counts()
        return min(counts.index, key=lambda n: (n.isupper(), -counts[n], n))

    canonical = present.groupby(present.str.casefold()).agg(pick)
    return names.map(lambda n: canonical.get(n.casefold(), n) if isinstance(n, str) else n).astype("string")


def clean_outcomes(raw: pd.DataFrame) -> pd.DataFrame:
    """Validate and tidy a raw coded-outcomes export.

    * Checks the required columns exist.
    * Trims whitespace in text columns.
    * Back-fills missing organization/program names from the file name and
      merges known spelling variants (ORG_ALIASES).
    * Replaces missing category values with explicit placeholder labels so
      they stay visible in charts instead of silently disappearing.
    * Adds helper columns for sorting and compact labels.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise MissingColumnsError(
            "The CSV is missing required column(s): " + ", ".join(missing)
        )

    df = raw.copy()

    # --- Trim stray whitespace in every text column ---------------------------
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].astype("string").str.strip().replace("", pd.NA)

    # District program files name a partner by ID only. Label it so rows from
    # one partner still group together, rather than all collapsing into
    # "Unknown organization".
    if COL_ORG not in df.columns:
        df[COL_ORG] = pd.Series(pd.NA, index=df.index, dtype="string")
    if COL_PARTNER_ID in df.columns:
        df[COL_ORG] = df[COL_ORG].fillna("Partner " + df[COL_PARTNER_ID])
    if COL_PROGRAM not in df.columns:
        df[COL_PROGRAM] = pd.Series(pd.NA, index=df.index, dtype="string")

    # --- Where each outcome came from ------------------------------------------
    if COL_SOURCE_TYPE in df.columns:
        df[COL_SOURCE_TYPE] = df[COL_SOURCE_TYPE].replace(SOURCE_ALIASES).fillna(SOURCE_LOGIC_MODEL)
    else:
        df[COL_SOURCE_TYPE] = SOURCE_LOGIC_MODEL

    # --- Organization and program names ---------------------------------------
    if COL_SOURCE_FILE in df.columns:
        parsed = df[COL_SOURCE_FILE].map(parse_filename)
        file_org = parsed.str[0]
        file_program = parsed.str[1]
    else:
        file_org = pd.Series(pd.NA, index=df.index)
        file_program = pd.Series(pd.NA, index=df.index)

    org = df[COL_ORG].mask(df[COL_ORG].isin(JUNK_ORG_NAMES))
    org = org.fillna(file_org).mask(lambda s: s.isin(JUNK_ORG_NAMES))
    org = org.replace(ORG_ALIASES)
    df[COL_ORG] = _merge_case_variants(org).fillna(UNKNOWN_ORG)

    df[COL_GRANTEE] = file_org.mask(file_org.isin(JUNK_ORG_NAMES)).fillna(df[COL_ORG])
    df[COL_PROGRAM] = df[COL_PROGRAM].fillna(file_program).fillna(UNKNOWN_PROGRAM)

    # --- Categories -----------------------------------------------------------
    if COL_SPECIFICITY in df.columns:
        # Codebook 3.1 domain-only rows: a domain and deliberately no code.
        domain_only = (df[COL_SPECIFICITY].str.lower() == "domain") & df[COL_SUBCAT].isna() & df[COL_DOMAIN].notna()
        df.loc[domain_only, COL_SUBCAT] = (
            df.loc[domain_only, COL_DOMAIN].str.replace(r"^\s*Domain\s+", "", regex=True)
            .str.replace(".", "", n=1, regex=False) + DOMAIN_ONLY_SUFFIX
        )
    df[COL_DOMAIN] = df[COL_DOMAIN].fillna(UNCODED_DOMAIN)
    df[COL_SUBCAT] = df[COL_SUBCAT].fillna(UNASSIGNED_SUBCAT)
    df[COL_POP] = df[COL_POP].fillna(UNKNOWN_POP)
    df[COL_CONF] = df[COL_CONF].fillna("none").str.lower()
    df[COL_TEXT] = df[COL_TEXT].fillna("")

    # --- Outcome text ---------------------------------------------------------
    # The coder splits compound statements ("Increased confidence, well-being
    # and self-worth") into atomic outcomes ("Increased well-being"), and each
    # row is coded on its atomic outcome. Show that as the outcome, and keep the
    # original only as context on rows that came from a split. About half of
    # the atomic outcomes are rewrites rather than exact excerpts, so they
    # cannot simply be highlighted inside the original.
    atomic = df[COL_ATOMIC].fillna("") if COL_ATOMIC in df.columns else pd.Series("", index=df.index)
    df[COL_OUTCOME] = atomic.where(atomic.str.len() > 0, df[COL_TEXT])
    was_split = df[COL_OUTCOME].str.strip().str.casefold() != df[COL_TEXT].str.strip().str.casefold()
    df[COL_FULL] = df[COL_TEXT].where(was_split, "")

    # --- Helper columns -------------------------------------------------------
    df[COL_DOMAIN_NUM] = df[COL_DOMAIN].map(_domain_number)
    df[COL_DOMAIN_SHORT] = df[COL_DOMAIN].map(domain_short)
    df[COL_PRIORITY] = [priority_of(d, g) for d, g in zip(df[COL_DOMAIN], df[COL_SUBCAT])]

    # Default grouping; main() may switch this to the grantee column.
    df[COL_ORG_VIEW] = df[COL_ORG]
    return df.reset_index(drop=True)


def read_outcomes_csv(source: Union[str, Path, IO[bytes]]) -> pd.DataFrame:
    """Read and clean a coded-outcomes CSV from a path or an open binary file.

    Raises FileNotFoundError, pandas parser errors, or MissingColumnsError;
    the app turns those into friendly messages.
    """
    raw = pd.read_csv(source, dtype=str, keep_default_na=True)
    return clean_outcomes(raw)


def load_codebook_for(df: pd.DataFrame) -> pd.DataFrame:
    """The codebook (or codebooks) whose numbering the loaded file uses.

    A file coded with 3.x must not be compared against the 1.x goal list, or
    every 3.x goal looks like a gap and every 1.x goal looks untouched.
    """
    schemes = codebook_scheme(df[COL_DOMAIN].dropna().unique())
    paths = [CODEBOOK_PATH] if not schemes or "1.x" in schemes else []
    if "3.x" in schemes:
        paths.append(CODEBOOK_V3_PATH)
    return pd.concat([load_codebook(p) for p in paths], ignore_index=True)


def load_codebook(path: Union[str, Path] = CODEBOOK_PATH) -> pd.DataFrame:
    """Every (domain, subcategory) pair in the codebook, or an empty frame if the file is missing.

    The dashboard uses this to show subcategories that no program targets
    yet, which never appear in the coded data itself.
    """
    try:
        codebook = pd.read_csv(path, dtype=str)
    except FileNotFoundError:
        return pd.DataFrame(columns=[COL_DOMAIN, COL_SUBCAT])
    return codebook[[COL_DOMAIN, COL_SUBCAT]].dropna().drop_duplicates()


# =============================================================================
# FILTERING
# -----------------------------------------------------------------------------
# Pure functions: DataFrame in, DataFrame out. No Streamlit calls, so they can
# be reused by other front ends (e.g. a Leaflet map export) and tested alone.
# =============================================================================


def _isin_or_all(series: pd.Series, values: Optional[Iterable]) -> pd.Series:
    """Boolean mask: True where `series` is in `values`; all True when no values given."""
    if values is None:
        return pd.Series(True, index=series.index)
    values = list(values)
    if not values:
        return pd.Series(True, index=series.index)
    return series.isin(values)


def filter_outcomes(
    df: pd.DataFrame,
    *,
    organizations: Optional[Iterable[str]] = None,
    org_col: str = COL_ORG_VIEW,
    programs: Optional[Iterable[str]] = None,
    domains: Optional[Iterable[str]] = None,
    subcategories: Optional[Iterable[str]] = None,
    populations: Optional[Iterable[str]] = None,
    confidences: Optional[Iterable[str]] = None,
    qa_statuses: Optional[Iterable[str]] = None,
    text_query: Optional[str] = None,
) -> pd.DataFrame:
    """Return the rows of `df` matching every filter that was supplied.

    Each argument is optional; None or an empty list means "no filter on this
    column". `text_query` is a case-insensitive substring search over the
    outcome text (and the atomic outcome text when present).

    Example (e.g. for a map layer of low-confidence SEL outcomes):

        filter_outcomes(df, domains=["Domain 3. Social & Emotional Learning (CASEL-aligned)"],
                        confidences=["low"])
    """
    mask = (
        _isin_or_all(df[org_col], organizations)
        & _isin_or_all(df[COL_PROGRAM], programs)
        & _isin_or_all(df[COL_DOMAIN], domains)
        & _isin_or_all(df[COL_SUBCAT], subcategories)
        & _isin_or_all(df[COL_POP], populations)
        & _isin_or_all(df[COL_CONF], confidences)
    )
    if qa_statuses and COL_QA in df.columns:
        mask &= df[COL_QA].isin(list(qa_statuses))
    if text_query:
        query = text_query.strip()
        text_mask = df[COL_TEXT].str.contains(query, case=False, regex=False, na=False)
        if COL_ATOMIC in df.columns:
            text_mask |= df[COL_ATOMIC].str.contains(query, case=False, regex=False, na=False)
        mask &= text_mask
    return df[mask]


def to_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Columns to include when a filtered view is downloaded.

    Keeps the original export columns plus the cleaned organization/grantee
    names, and drops internal helper columns. A future map export would join
    this frame to organization coordinates on `organization` or
    `grantee_from_filename`.
    """
    internal = {COL_ORG_VIEW, COL_DOMAIN_NUM, COL_DOMAIN_SHORT, COL_OUTCOME, COL_FULL}
    return df[[c for c in df.columns if c not in internal]]


# =============================================================================
# AGGREGATION
# -----------------------------------------------------------------------------
# Pure functions that turn the filtered rows into chart and table inputs.
# =============================================================================


def _wrap_for_hover(text: str) -> str:
    """Escape, shorten and line-wrap one outcome statement for a Plotly hover box."""
    text = " ".join(str(text).split())
    if len(text) > HOVER_MAX_CHARS:
        text = text[: HOVER_MAX_CHARS - 1].rstrip() + "…"
    lines = textwrap.wrap(html.escape(text), HOVER_WRAP_WIDTH) or [""]
    return "<br>   ".join(lines)


def sample_outcomes(texts: pd.Series, n: int = HOVER_SAMPLE_SIZE, seed: int = 0) -> list[str]:
    """A few distinct, non-empty outcome statements, picked the same way on every run.

    A fixed seed keeps the same chart showing the same samples (users are less
    likely to distrust a chart whose examples change on every rerun). This is
    called once per bar, slice or cell, so it avoids pandas' slower
    `Series.sample`.
    """
    unique = list(dict.fromkeys(t for t in texts if isinstance(t, str) and t))
    if len(unique) <= n:
        return unique
    picks = np.random.RandomState(seed).choice(len(unique), size=n, replace=False)
    return [unique[i] for i in picks]


def sample_outcome_texts(texts: pd.Series, n: int = HOVER_SAMPLE_SIZE, seed: int = 0) -> str:
    """A few distinct outcome statements (see sample_outcomes), formatted as a bulleted hover snippet."""
    picked = sample_outcomes(texts, n, seed)
    if not picked:
        return "<i>(no outcome text)</i>"
    return "<br>".join("• " + _wrap_for_hover(t) for t in picked)


def domain_order(df: pd.DataFrame) -> list[str]:
    """Domains in numeric order (Domain 1, 2, ... 12, then Uncoded)."""
    pairs = df[[COL_DOMAIN, COL_DOMAIN_NUM]].drop_duplicates().sort_values([COL_DOMAIN_NUM, COL_DOMAIN])
    return pairs[COL_DOMAIN].tolist()


def count_organizations(orgs: pd.Series) -> int:
    """Distinct organizations, leaving out the placeholder for rows with no name.

    A handful of rows name no organization and have no file name to recover
    one from. They are not an organization, so they never count as one.
    """
    return int(orgs[orgs != UNKNOWN_ORG].nunique())


def sorted_subcategories(values: Iterable[str]) -> list[str]:
    """Unique subcategory labels in codebook order."""
    return sorted(set(values), key=subcategory_sort_key)


def population_group(code: str) -> str:
    """Chart grouping for a target population code (small groups fold into 'Other or mixed')."""
    return POPULATION_GROUPS.get(code, OTHER_POPULATION)


def hierarchy_counts(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (domain, subcategory) with outcome and organization counts and hover samples.

    Columns: outcomes (rows), organizations (distinct organizations), and
    samples (a hover snippet of outcome statements).
    """
    return (
        df.groupby([COL_DOMAIN, COL_SUBCAT], observed=True)
        .agg(
            outcomes=(COL_TEXT, "size"),
            organizations=(COL_ORG_VIEW, count_organizations),
            samples=(COL_OUTCOME, sample_outcome_texts),
        )
        .reset_index()
    )


def count_programs(df: pd.DataFrame) -> int:
    """Distinct programs, where a program is a program name within one organization."""
    return int(df[[COL_ORG_VIEW, COL_PROGRAM]].drop_duplicates().shape[0])


SUNBURST_ROOT = "all"
SUNBURST_SEP = "\x1f"   # joins domain and goal in a node id; never appears in a label


def split_code(label: str) -> tuple[str, str]:
    """ "Y1.3 Mathematics" -> ("Y1.3", "Mathematics"); "Domain Y1. Academic..." -> ("Y1", "Academic...").

    Labels with no code (Uncoded, Unassigned subcategory) come back as ("", label).
    """
    text = re.sub(r"^\s*Domain\s+", "", str(label))
    match = re.match(r"([YFA]?\d+(?:\.\d+)*)\.?\s+(.*)$", text)
    if not match:
        return "", str(label)
    return match.group(1), re.sub(r"\s*\(.*?\)\s*$", "", match.group(2))


def sunburst_nodes(df: pd.DataFrame, codebook: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """The nodes of the domain -> goal sunburst: one root, one row per domain, one per goal.

    Columns: id, parent, level ("root", "domain" or "goal"), domain, goal,
    code and title (the label split into "Y1.3" and "Mathematics"),
    domain_index (picks the domain's color: its position in `codebook` when
    given, so a domain keeps its color under any filter, else its position
    in the data), outcomes, programs, organizations (exact distinct counts at
    that node), samples (hover snippet) and sample_list (the same statements
    as plain text). Domains come in numeric order and goals in codebook
    order, so the ring reads clockwise like the codebook.

    Everything is counted with one groupby per level, because this runs on
    every rerun of the sunburst view.
    """
    programs = df[[COL_DOMAIN, COL_SUBCAT, COL_ORG_VIEW, COL_PROGRAM]].drop_duplicates()
    named = df[df[COL_ORG_VIEW] != UNKNOWN_ORG]

    def level_counts(keys: list[str]) -> pd.DataFrame:
        if not keys:
            return pd.DataFrame({
                "outcomes": [len(df)], "programs": [count_programs(df)],
                "organizations": [count_organizations(df[COL_ORG_VIEW])],
                "sample_list": [sample_outcomes(df[COL_OUTCOME])],
            })
        return pd.DataFrame({
            "outcomes": df.groupby(keys, sort=False).size(),
            "programs": programs.drop_duplicates(keys + [COL_ORG_VIEW, COL_PROGRAM]).groupby(keys, sort=False).size(),
            "organizations": named.groupby(keys, sort=False)[COL_ORG_VIEW].nunique(),
            "sample_list": df.groupby(keys, sort=False)[COL_OUTCOME].agg(sample_outcomes),
        }).fillna({"organizations": 0})

    by_goal, by_domain, root = level_counts([COL_DOMAIN, COL_SUBCAT]), level_counts([COL_DOMAIN]), level_counts([])
    order = domain_order(df)
    if codebook is not None and not codebook.empty:
        known = list(dict.fromkeys(codebook[COL_DOMAIN]))
        hue_index = {d: known.index(d) if d in known else len(known) + i for i, d in enumerate(order)}
    else:
        hue_index = {d: i for i, d in enumerate(order)}

    def node(node_id, parent, level, domain, goal, label, stats) -> dict:
        code, title = split_code(label) if label else ("", "All domains")
        return {"id": node_id, "parent": parent, "level": level, "domain": domain, "goal": goal,
                "code": code, "title": title, "domain_index": hue_index.get(domain, -1),
                "outcomes": int(stats["outcomes"]), "programs": int(stats["programs"]),
                "organizations": int(stats["organizations"]), "sample_list": stats["sample_list"]}

    nodes = [node(SUNBURST_ROOT, "", "root", None, None, None, root.iloc[0])]
    goals_by_domain = by_goal.reset_index().groupby(COL_DOMAIN, sort=False)[COL_SUBCAT].agg(list)
    for domain in order:
        nodes.append(node(domain, SUNBURST_ROOT, "domain", domain, None, domain, by_domain.loc[domain]))
        for goal in sorted_subcategories(goals_by_domain.get(domain, [])):
            nodes.append(node(domain + SUNBURST_SEP + goal, domain, "goal", domain, goal, goal,
                              by_goal.loc[(domain, goal)]))
    frame = pd.DataFrame(nodes)
    frame["samples"] = frame["sample_list"].map(
        lambda texts: "<br>".join("• " + _wrap_for_hover(t) for t in texts) or "<i>(no outcome text)</i>")
    return frame


def distinct_counts_by(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Outcomes and distinct organizations for each value of `column` (e.g. per domain)."""
    return df.groupby(column).agg(outcomes=(COL_TEXT, "size"), organizations=(COL_ORG_VIEW, count_organizations))


def domain_population_counts(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (domain, population group) with outcome count, share of the domain, and samples."""
    grouped = (
        df.assign(population_group=df[COL_POP].map(population_group))
        .groupby([COL_DOMAIN, COL_DOMAIN_SHORT, COL_DOMAIN_NUM, "population_group"], observed=True)
        .agg(count=(COL_TEXT, "size"), samples=(COL_OUTCOME, sample_outcome_texts))
        .reset_index()
    )
    grouped["share"] = grouped["count"] / grouped.groupby(COL_DOMAIN)["count"].transform("sum")
    grouped["population_group"] = pd.Categorical(
        grouped["population_group"], categories=POPULATION_GROUP_ORDER, ordered=True
    )
    return grouped.sort_values([COL_DOMAIN_NUM, "population_group"]).reset_index(drop=True)


def subcategory_coverage(df: pd.DataFrame, codebook: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """How many organizations, programs and outcomes target each subcategory.

    When a codebook is given, subcategories nobody targets are included with
    zero counts, so real gaps show up. Placeholder labels (Uncoded /
    Unassigned) are left out. Sorted from least to most covered.
    """
    coded = df[(df[COL_SUBCAT] != UNASSIGNED_SUBCAT) & (df[COL_DOMAIN] != UNCODED_DOMAIN)
               & ~df[COL_SUBCAT].str.endswith(DOMAIN_ONLY_SUFFIX)]
    counts = (
        coded.groupby([COL_DOMAIN, COL_SUBCAT], observed=True)
        .agg(
            organizations=(COL_ORG_VIEW, count_organizations),
            programs=(COL_PROGRAM, "nunique"),
            outcomes=(COL_TEXT, "size"),
            samples=(COL_OUTCOME, sample_outcome_texts),
        )
        .reset_index()
    )
    if codebook is not None and not codebook.empty:
        counts = codebook.merge(counts, on=[COL_DOMAIN, COL_SUBCAT], how="outer")
        for col in ("organizations", "programs", "outcomes"):
            counts[col] = counts[col].fillna(0).astype(int)
        counts["samples"] = counts["samples"].fillna("<i>(no program targets this yet)</i>")
    counts[COL_DOMAIN_SHORT] = counts[COL_DOMAIN].map(domain_short)
    counts["_order"] = counts[COL_SUBCAT].map(subcategory_sort_key)
    return (
        counts.sort_values(["organizations", "outcomes", "_order"])
        .drop(columns="_order")
        .reset_index(drop=True)
    )


def program_labels(df: pd.DataFrame) -> pd.Series:
    """A readable, unique name for each row's program.

    Program names alone are often generic ("Youth Programs"), so the label
    leads with the organization and adds the program only when that
    organization has more than one.
    """
    programs_per_org = df.groupby(COL_ORG_VIEW)[COL_PROGRAM].transform("nunique")
    return df[COL_ORG_VIEW].where(programs_per_org <= 1, df[COL_ORG_VIEW] + ": " + df[COL_PROGRAM])


def program_options(df: pd.DataFrame) -> pd.DataFrame:
    """One row per program: label, organization, and outcome count, largest first."""
    return (
        df.assign(**{COL_PROGRAM_LABEL: program_labels(df)})
        .groupby([COL_PROGRAM_LABEL, COL_ORG_VIEW], observed=True)
        .size()
        .rename("outcomes")
        .reset_index()
        .sort_values(["outcomes", COL_PROGRAM_LABEL], ascending=[False, True])
        .reset_index(drop=True)
    )


def program_flows(df: pd.DataFrame, programs: Iterable[str], domain: Optional[str] = None) -> pd.DataFrame:
    """Outcome statements flowing from each chosen program to a domain.

    With `domain` set, flows go to that domain's subcategories instead, for
    zooming in. Columns: source (program label), target (domain or
    subcategory), outcomes, samples. Targets are in codebook order.
    """
    rows = df.assign(**{COL_PROGRAM_LABEL: program_labels(df)})
    rows = rows[rows[COL_PROGRAM_LABEL].isin(list(programs))]
    if domain is not None:
        rows = rows[rows[COL_DOMAIN] == domain]
    target_col = COL_SUBCAT if domain is not None else COL_DOMAIN
    flows = (
        rows.groupby([COL_PROGRAM_LABEL, target_col], observed=True)
        .agg(outcomes=(COL_TEXT, "size"), samples=(COL_OUTCOME, sample_outcome_texts))
        .reset_index()
        .rename(columns={COL_PROGRAM_LABEL: "source", target_col: "target"})
    )
    if domain is None:
        order = {d: i for i, d in enumerate(domain_order(rows))}
        flows["_order"] = flows["target"].map(order)
    else:
        flows["_order"] = flows["target"].map(subcategory_sort_key)
    return flows.sort_values(["_order", "source"]).drop(columns="_order").reset_index(drop=True)


def org_subcategory_sets(df: pd.DataFrame, org_col: str = COL_ORG_VIEW) -> dict[str, set[str]]:
    """Map each organization to the set of subcategories it targets.

    The 'Unassigned subcategory' placeholder is excluded: two organizations
    both having an uncoded outcome is not a meaningful overlap.
    """
    coded = df[df[COL_SUBCAT] != UNASSIGNED_SUBCAT]
    # Built with a comprehension: some pandas versions turn sets returned from
    # .agg() into lists, which breaks the set arithmetic below.
    return {org: set(subcats) for org, subcats in coded.groupby(org_col)[COL_SUBCAT]}


def compute_peer_overlap(df: pd.DataFrame, organization: str, org_col: str = COL_ORG_VIEW) -> pd.DataFrame:
    """Rank other organizations by how many subcategories they share with `organization`.

    Returns one row per peer that shares at least one subcategory, with:

    * shared_subcategories - number of subcategories both organizations target
    * coverage             - share of the selected organization's subcategories
                             the peer also targets (0-1)
    * jaccard              - shared / (union of both sets), a symmetric
                             similarity score that does not favour large
                             organizations with many outcomes (0-1)
    * peer_outcomes_in_shared - how many of the peer's outcomes fall in the
                             shared subcategories (depth of the overlap)
    * programs             - the peer's programs, for context
    * shared_list          - the shared subcategory labels, in codebook order

    Sorted by shared count, then Jaccard, then name.
    """
    sets = org_subcategory_sets(df, org_col)
    columns = [
        "organization", "shared_subcategories", "coverage", "jaccard",
        "peer_outcomes_in_shared", "programs", "shared_list",
    ]
    if organization not in sets:
        return pd.DataFrame(columns=columns)

    target = sets[organization]
    coded = df[df[COL_SUBCAT] != UNASSIGNED_SUBCAT]
    programs_by_org = df.groupby(org_col)[COL_PROGRAM].agg(lambda s: ", ".join(sorted(set(s))))

    rows = []
    for other, subcats in sets.items():
        if other == organization:
            continue
        shared = target & subcats
        if not shared:
            continue
        peer_rows = coded[(coded[org_col] == other) & coded[COL_SUBCAT].isin(shared)]
        rows.append(
            {
                "organization": other,
                "shared_subcategories": len(shared),
                "coverage": len(shared) / len(target),
                "jaccard": len(shared) / len(target | subcats),
                "peer_outcomes_in_shared": len(peer_rows),
                "programs": programs_by_org.get(other, ""),
                "shared_list": "; ".join(sorted_subcategories(shared)),
            }
        )

    if not rows:
        return pd.DataFrame(columns=columns)
    return (
        pd.DataFrame(rows, columns=columns)
        .sort_values(["shared_subcategories", "jaccard", "organization"], ascending=[False, False, True])
        .reset_index(drop=True)
    )


def peer_heatmap_data(
    df: pd.DataFrame, organization: str, peers: Sequence[str], org_col: str = COL_ORG_VIEW
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Matrices for the peer heatmap.

    Rows are the selected organization followed by `peers`; columns are the
    selected organization's subcategories. Returns (counts, hover_samples),
    two DataFrames of identical shape.
    """
    orgs = [organization] + [p for p in peers if p != organization]
    target_subcats = sorted_subcategories(
        df.loc[(df[org_col] == organization) & (df[COL_SUBCAT] != UNASSIGNED_SUBCAT), COL_SUBCAT]
    )
    subset = df[df[org_col].isin(orgs) & df[COL_SUBCAT].isin(target_subcats)]

    counts = (
        subset.groupby([org_col, COL_SUBCAT]).size()
        .unstack(fill_value=0)
        .reindex(index=orgs, columns=target_subcats, fill_value=0)
    )
    samples = (
        subset.groupby([org_col, COL_SUBCAT])[COL_OUTCOME].agg(sample_outcome_texts)
        .unstack()
        .reindex(index=orgs, columns=target_subcats)
        .fillna("<i>(no outcomes in this subcategory)</i>")
    )
    return counts, samples


def organizations_for_subcategory(df: pd.DataFrame, subcategory: str, org_col: str = COL_ORG_VIEW) -> pd.DataFrame:
    """Organizations with at least one outcome in `subcategory`, with counts and samples."""
    subset = df[df[COL_SUBCAT] == subcategory]
    if subset.empty:
        return pd.DataFrame(columns=["organization", "count", "programs", "samples"])
    return (
        subset.groupby(org_col)
        .agg(
            count=(COL_TEXT, "size"),
            programs=(COL_PROGRAM, lambda s: ", ".join(sorted(set(s)))),
            samples=(COL_OUTCOME, sample_outcome_texts),
        )
        .reset_index()
        .rename(columns={org_col: "organization"})
        .sort_values(["count", "organization"], ascending=[False, True])
        .reset_index(drop=True)
    )


# =============================================================================
# FINDINGS AND LINKED VIEWS
# =============================================================================


def domain_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per domain: organizations, outcomes, short name and number, with hover samples.

    Placeholder rows (Uncoded) are left out. Sorted by organizations, most first.
    """
    coded = df[df[COL_DOMAIN] != UNCODED_DOMAIN]
    if coded.empty:
        return pd.DataFrame(columns=[COL_DOMAIN, COL_DOMAIN_SHORT, COL_DOMAIN_NUM, "organizations", "outcomes",
                                     "samples"])
    return (
        coded.groupby([COL_DOMAIN, COL_DOMAIN_SHORT, COL_DOMAIN_NUM], observed=True)
        .agg(organizations=(COL_ORG_VIEW, count_organizations), outcomes=(COL_TEXT, "size"),
             samples=(COL_OUTCOME, sample_outcome_texts))
        .reset_index()
        .sort_values(["organizations", "outcomes", COL_DOMAIN_NUM], ascending=[False, False, True])
        .reset_index(drop=True)
    )


def priority_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per plain-language priority: organizations, outcomes and hover samples.

    Rows that were never coded are left out. Sorted by organizations, most
    first, then in PRIORITIES order.
    """
    coded = df[df[COL_PRIORITY] != UNCODED_PRIORITY]
    if coded.empty:
        return pd.DataFrame(columns=[COL_PRIORITY, "organizations", "outcomes", "samples"])
    order = {label: i for i, (label, _) in enumerate(PRIORITIES)}
    summary = (
        coded.groupby(COL_PRIORITY)
        .agg(organizations=(COL_ORG_VIEW, count_organizations), outcomes=(COL_TEXT, "size"),
             samples=(COL_OUTCOME, sample_outcome_texts))
        .reset_index()
    )
    summary["_order"] = summary[COL_PRIORITY].map(order)
    return (
        summary.sort_values(["organizations", "_order"], ascending=[False, True])
        .drop(columns="_order")
        .reset_index(drop=True)
    )


def goal_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per coded subcategory: domain, organizations, outcomes and samples, most organizations first."""
    coded = df[(df[COL_SUBCAT] != UNASSIGNED_SUBCAT) & (df[COL_DOMAIN] != UNCODED_DOMAIN)]
    if coded.empty:
        return pd.DataFrame(columns=[COL_DOMAIN, COL_SUBCAT, "organizations", "outcomes", "samples"])
    counts = hierarchy_counts(coded)
    counts["_order"] = counts[COL_SUBCAT].map(subcategory_sort_key)
    return (
        counts.sort_values(["organizations", "outcomes", "_order"], ascending=[False, False, True])
        .drop(columns="_order")
        .reset_index(drop=True)
    )


def population_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Outcomes and organizations per population group, in the fixed group order (empty groups dropped)."""
    groups = df[COL_POP].map(population_group)
    summary = (
        df.assign(population_group=groups)
        .groupby("population_group")
        .agg(outcomes=(COL_TEXT, "size"), organizations=(COL_ORG_VIEW, count_organizations),
             samples=(COL_OUTCOME, sample_outcome_texts))
        .reindex(POPULATION_GROUP_ORDER)
        .dropna(subset=["outcomes"])
        .reset_index()
    )
    summary["outcomes"] = summary["outcomes"].astype(int)
    summary["organizations"] = summary["organizations"].astype(int)
    return summary


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def portfolio_findings(df: pd.DataFrame, coverage: Optional[pd.DataFrame] = None) -> list[str]:
    """Two to four plain-language findings about the filtered outcomes, as Markdown sentences.

    Each one states a fact the charts below show, with the numbers inline, so
    the page leads with what the data says rather than with raw counts.
    """
    findings: list[str] = []
    domains = domain_summary(df)
    n_orgs = count_organizations(df[COL_ORG_VIEW])
    if domains.empty or n_orgs == 0:
        return findings

    priorities = priority_summary(df)
    if len(priorities) > 1:
        top = priorities.iloc[0]
        findings.append(
            f"**{top[COL_PRIORITY]}** is the most widely shared aim: "
            f"**{int(top['organizations'])} of {n_orgs}** organizations name at least one outcome in it."
        )
        counts = priorities.set_index(COL_PRIORITY)["organizations"]
        school = {label: int(counts.get(label, 0)) for label in SCHOOL_MEASURES}
        if top[COL_PRIORITY] not in school:
            named = [f"**{n}** {label.lower()}" for label, n in school.items()]
            named[0] = named[0].replace("** ", "** name ", 1)
            findings.append("Far fewer name what schools report on: "
                            + ", ".join(named[:-1]) + " and " + named[-1] + ".")

    if coverage is not None and not coverage.empty:
        gaps = int((coverage["organizations"] == 0).sum())
        single = int((coverage["organizations"] == 1).sum())
        if gaps or single:
            parts = []
            if gaps:
                parts.append(f"**{_plural(gaps, 'goal')}** in the codebook "
                             f"{'has' if gaps == 1 else 'have'} no program")
            if single:
                parts.append(f"{'another ' if gaps else ''}**{single}** "
                             f"{'has' if single == 1 else 'have'} only one organization")
            sentence = ", and ".join(parts) + "."
            findings.append(sentence[0].upper() + sentence[1:])

    groups = df[COL_POP].map(population_group)
    student_share = (groups == "Students & youth").mean()
    if 0 < student_share < 1:
        share_by_domain = (
            df.assign(_students=groups == "Students & youth")
            .loc[df[COL_DOMAIN] != UNCODED_DOMAIN]
            .groupby(COL_DOMAIN)["_students"].mean()
        )
        adult_domains = share_by_domain[share_by_domain < 0.5]
        sentence = f"**{student_share:.0%}** of outcomes are about students and youth"
        if len(adult_domains) == 1:
            sentence += (f". **{domain_short(adult_domains.index[0]).split('. ', 1)[-1]}** is the one domain "
                         "where most outcomes are about adults, families or systems instead")
        elif len(adult_domains) > 1:
            names = [domain_short(d).split(". ", 1)[-1] for d in adult_domains.index]
            listed = (", ".join(names[:-1]) + " and " + names[-1]) if len(names) <= 3 else f"{len(names)} domains"
            sentence += f". In {listed}, most outcomes are about adults, families or systems instead"
        findings.append(sentence + ".")
    return findings
