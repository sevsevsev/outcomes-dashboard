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

REQUIRED_COLUMNS = [COL_ORG, COL_PROGRAM, COL_TEXT, COL_DOMAIN, COL_SUBCAT, COL_POP, COL_CONF]

# Derived columns added by clean_outcomes().
COL_GRANTEE = "grantee_from_filename"   # organization parsed from the logic model's file name
COL_ORG_VIEW = "org_view"               # whichever organization column the user chose to group by
COL_DOMAIN_NUM = "domain_number"        # 3 for "Domain 3. ...", used for sorting
COL_OUTCOME = "outcome"                 # the coded (atomic) outcome, falling back to the original text
COL_FULL = "full_statement"             # the original statement, only when the coder split it
COL_DOMAIN_SHORT = "domain_short"       # "3. Social & Emotional Learning" for compact axis labels

# Placeholder labels for missing values, so nothing silently drops out of a chart.
UNCODED_DOMAIN = "Uncoded"
UNASSIGNED_SUBCAT = "Unassigned subcategory"
UNKNOWN_POP = "unspecified"
UNKNOWN_ORG = "Unknown organization"
UNKNOWN_PROGRAM = "Unknown program"

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
MEASURES = [MEASURE_ORGS, MEASURE_OUTCOMES]

ORG_GROUPING_OPTIONS = {
    "Name in the logic model": COL_ORG,
    "Grantee from the file name": COL_GRANTEE,
}


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


def _domain_number(domain: object) -> float:
    """3.0 for 'Domain 3. Social & ...'; infinity for anything unparseable (sorts last)."""
    match = re.match(r"\s*Domain\s+(\d+)", str(domain))
    return float(match.group(1)) if match else float("inf")


def _domain_short(domain: str) -> str:
    """'Domain 3. Social & Emotional Learning (CASEL-aligned)' -> '3. Social & Emotional Learning'."""
    short = re.sub(r"^\s*Domain\s+", "", domain)
    return re.sub(r"\s*\(.*?\)\s*$", "", short)


def subcategory_sort_key(label: str) -> tuple:
    """Sort '3.1.4 Confidence...' after '3.1.2 ...' and before '10.1 ...' (numeric, not alphabetical)."""
    match = re.match(r"\s*([\d.]+)", str(label))
    if not match:
        return (float("inf"), str(label))
    parts = tuple(int(p) for p in match.group(1).strip(".").split(".") if p.isdigit())
    return parts + (str(label),)


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
    df[COL_ORG] = org.replace(ORG_ALIASES).fillna(UNKNOWN_ORG)

    df[COL_GRANTEE] = file_org.mask(file_org.isin(JUNK_ORG_NAMES)).fillna(df[COL_ORG])
    df[COL_PROGRAM] = df[COL_PROGRAM].fillna(file_program).fillna(UNKNOWN_PROGRAM)

    # --- Categories -----------------------------------------------------------
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
    df[COL_DOMAIN_SHORT] = df[COL_DOMAIN].map(_domain_short)

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


def sample_outcome_texts(texts: pd.Series, n: int = HOVER_SAMPLE_SIZE, seed: int = 0) -> str:
    """A few distinct outcome statements, formatted as a bulleted hover snippet.

    Uses a fixed seed so the same chart always shows the same samples (users
    are less likely to distrust a chart whose tooltip changes on every rerun).
    """
    unique = texts.dropna().loc[lambda s: s.str.len() > 0].drop_duplicates()
    if unique.empty:
        return "<i>(no outcome text)</i>"
    picked = unique.sample(n=min(n, len(unique)), random_state=seed)
    return "<br>".join("• " + _wrap_for_hover(t) for t in picked)


def domain_order(df: pd.DataFrame) -> list[str]:
    """Domains in numeric order (Domain 1, 2, ... 12, then Uncoded)."""
    pairs = df[[COL_DOMAIN, COL_DOMAIN_NUM]].drop_duplicates().sort_values([COL_DOMAIN_NUM, COL_DOMAIN])
    return pairs[COL_DOMAIN].tolist()


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
            organizations=(COL_ORG_VIEW, "nunique"),
            samples=(COL_OUTCOME, sample_outcome_texts),
        )
        .reset_index()
    )


def distinct_counts_by(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Outcomes and distinct organizations for each value of `column` (e.g. per domain)."""
    return df.groupby(column).agg(outcomes=(COL_TEXT, "size"), organizations=(COL_ORG_VIEW, "nunique"))


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
    coded = df[(df[COL_SUBCAT] != UNASSIGNED_SUBCAT) & (df[COL_DOMAIN] != UNCODED_DOMAIN)]
    counts = (
        coded.groupby([COL_DOMAIN, COL_SUBCAT], observed=True)
        .agg(
            organizations=(COL_ORG_VIEW, "nunique"),
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
    counts[COL_DOMAIN_SHORT] = counts[COL_DOMAIN].map(_domain_short)
    counts["_order"] = counts[COL_SUBCAT].map(subcategory_sort_key)
    return (
        counts.sort_values(["organizations", "outcomes", "_order"])
        .drop(columns="_order")
        .reset_index(drop=True)
    )


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
