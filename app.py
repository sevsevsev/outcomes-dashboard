"""
Outcomes Dashboard
==================

A Streamlit prototype for exploring coded outcomes extracted from youth-serving
program logic models. It is built for two audiences:

* The strategic partnerships team, who want to see where the system's
  resources are concentrated (and where they are thin).
* Program operators, who want to find peer organizations aiming at the same
  developmental goals.

The app has three views, switched from the sidebar:

1. System-Level Policy Mapping      - treemap/sunburst + stacked bar chart
2. Program Alignment & Partnerships - peer matrix + "who works on this goal"
3. Data Governance & Validation     - paginated raw-data explorer

Run it with:

    streamlit run app.py

Code layout
-----------
The file is split into clearly separated layers so pieces can be reused
(for example by a future Leaflet map export):

* CONFIG            - constants, column names, name clean-up tables
* DATA LOADING      - reading and cleaning the CSV (no UI code except caching)
* FILTERING         - pure pandas functions: DataFrame in, DataFrame out
* AGGREGATION       - pure pandas functions that build chart/table inputs
* CHART BUILDERS    - functions that return Plotly figures
* UI COMPONENTS     - small reusable Streamlit widgets
* VIEWS             - one function per dashboard view
* MAIN              - page setup, sidebar navigation, error handling

Everything in FILTERING and AGGREGATION is free of Streamlit calls, so it can
be imported and unit-tested, or reused by a script that writes GeoJSON for a
map, without starting the app.
"""

from __future__ import annotations

import html
import io
import os
import re
import textwrap
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd
import plotly.express as px
import streamlit as st

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

ORG_GROUPING_OPTIONS = {
    "Name in the logic model": COL_ORG,
    "Grantee from the file name": COL_GRANTEE,
}


# =============================================================================
# DATA LOADING
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

    # --- Helper columns -------------------------------------------------------
    df[COL_DOMAIN_NUM] = df[COL_DOMAIN].map(_domain_number)
    df[COL_DOMAIN_SHORT] = df[COL_DOMAIN].map(_domain_short)

    # Default grouping; main() may switch this to the grantee column.
    df[COL_ORG_VIEW] = df[COL_ORG]
    return df.reset_index(drop=True)


@st.cache_data(show_spinner="Loading coded outcomes...")
def load_outcomes_from_path(path: str) -> pd.DataFrame:
    """Read and clean the CSV at `path`. Cached so reruns are instant.

    Raises FileNotFoundError, pandas parser errors, or MissingColumnsError;
    main() turns those into friendly messages.
    """
    raw = pd.read_csv(path, dtype=str, keep_default_na=True)
    return clean_outcomes(raw)


@st.cache_data(show_spinner="Loading uploaded file...")
def load_outcomes_from_bytes(data: bytes) -> pd.DataFrame:
    """Same as load_outcomes_from_path, for a file uploaded through the UI."""
    raw = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=True)
    return clean_outcomes(raw)


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
    internal = {COL_ORG_VIEW, COL_DOMAIN_NUM, COL_DOMAIN_SHORT}
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


def hierarchy_counts(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (domain, subcategory) with its outcome count and hover samples."""
    grouped = (
        df.groupby([COL_DOMAIN, COL_SUBCAT], observed=True)
        .agg(count=(COL_TEXT, "size"), samples=(COL_TEXT, sample_outcome_texts))
        .reset_index()
    )
    return grouped


def domain_population_counts(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (domain, target population) with count and hover samples."""
    grouped = (
        df.groupby([COL_DOMAIN, COL_DOMAIN_SHORT, COL_DOMAIN_NUM, COL_POP], observed=True)
        .agg(count=(COL_TEXT, "size"), samples=(COL_TEXT, sample_outcome_texts))
        .reset_index()
        .sort_values([COL_DOMAIN_NUM, COL_POP])
    )
    grouped["population_label"] = grouped[COL_POP].map(lambda p: POPULATION_LABELS.get(p, p))
    return grouped


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
        subset.groupby([org_col, COL_SUBCAT])[COL_TEXT].agg(sample_outcome_texts)
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
            samples=(COL_TEXT, sample_outcome_texts),
        )
        .reset_index()
        .rename(columns={org_col: "organization"})
        .sort_values(["count", "organization"], ascending=[False, True])
        .reset_index(drop=True)
    )


# =============================================================================
# CHART BUILDERS
# -----------------------------------------------------------------------------
# Every chart carries sample outcome statements in its hover box (the
# "validation tooltip"), so users can check a category against real text.
# =============================================================================

SAMPLE_HOVER_BLOCK = "<br><br><b>Sample outcomes</b><br>%{customdata[0]}"


def build_hierarchy_chart(df: pd.DataFrame, chart_type: str = "Treemap"):
    """Treemap or sunburst: domain (parent) -> subcategory (child), sized by row count."""
    counts = hierarchy_counts(df)
    chart_fn = px.treemap if chart_type == "Treemap" else px.sunburst
    root = "All outcomes"
    fig = chart_fn(
        counts,
        path=[px.Constant(root), COL_DOMAIN, COL_SUBCAT],
        values="count",
        custom_data=["samples"],
        color=COL_DOMAIN,
        color_discrete_sequence=px.colors.qualitative.Safe + px.colors.qualitative.Pastel,
    )

    # Plotly fills custom_data for parent nodes with "(?)" because the children
    # disagree. Replace those with samples drawn from the whole domain (or the
    # whole dataset for the root) so every block has a meaningful tooltip.
    # Nodes are identified by parent rather than by splitting ids on "/",
    # because some labels (e.g. "School/Program Connectedness") contain "/".
    trace = fig.data[0]
    domain_samples = df.groupby(COL_DOMAIN)[COL_TEXT].agg(sample_outcome_texts)
    root_id = next(i for i, p in zip(trace.ids, trace.parents) if not p)
    fixed = []
    for label, parent, custom in zip(trace.labels, trace.parents, trace.customdata):
        if not parent:                      # the "All outcomes" root
            fixed.append([sample_outcome_texts(df[COL_TEXT])])
        elif parent == root_id:             # a domain
            fixed.append([domain_samples.get(label, "")])
        else:                               # a subcategory (leaf): already correct
            fixed.append(list(custom))
    trace.customdata = fixed

    fig.update_traces(
        hovertemplate=(
            "<b>%{label}</b><br>%{value} outcomes · %{percentRoot:.1%} of all shown"
            + SAMPLE_HOVER_BLOCK
            + "<extra></extra>"
        ),
        # Show the count on each block too, so the chart is readable without hovering.
        texttemplate="%{label}<br>%{value}" if chart_type == "Treemap" else "%{label}",
    )
    if chart_type == "Sunburst":
        fig.update_traces(insidetextorientation="radial")
    fig.update_layout(margin=dict(t=30, l=10, r=10, b=10), height=640, showlegend=False)
    return fig


def build_domain_population_bar(df: pd.DataFrame):
    """Stacked bars: outcomes per domain, split by target population."""
    counts = domain_population_counts(df)
    order = [d for d in counts.sort_values(COL_DOMAIN_NUM)[COL_DOMAIN_SHORT].drop_duplicates()]
    fig = px.bar(
        counts,
        x=COL_DOMAIN_SHORT,
        y="count",
        color="population_label",
        custom_data=["samples", COL_DOMAIN, COL_POP],
        category_orders={COL_DOMAIN_SHORT: order},
        labels={COL_DOMAIN_SHORT: "Domain", "count": "Outcomes", "population_label": "Target population"},
        color_discrete_sequence=px.colors.qualitative.Safe,
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[1]}</b><br>%{fullData.name}: %{y} outcomes"
            + SAMPLE_HOVER_BLOCK
            + "<extra></extra>"
        )
    )
    fig.update_layout(
        barmode="stack",
        height=560,
        xaxis_tickangle=-35,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(t=60, l=10, r=10, b=10),
    )
    return fig


def build_peer_heatmap(counts: pd.DataFrame, samples: pd.DataFrame):
    """Heatmap of outcome counts: organizations (rows) x shared subcategories (columns)."""
    fig = px.imshow(
        counts,
        color_continuous_scale="Blues",
        aspect="auto",
        text_auto=True,
        labels=dict(x="Subcategory", y="Organization", color="Outcomes"),
    )
    fig.update_traces(
        customdata=samples.to_numpy()[..., None],
        hovertemplate=(
            "<b>%{y}</b><br>%{x}<br>%{z} outcomes"
            + SAMPLE_HOVER_BLOCK
            + "<extra></extra>"
        ),
    )
    fig.update_layout(
        height=max(320, 42 * len(counts) + 220),
        xaxis_tickangle=-35,
        margin=dict(t=20, l=10, r=10, b=10),
    )
    return fig


def build_subcategory_org_bar(orgs: pd.DataFrame, subcategory: str):
    """Horizontal bars: which organizations target a subcategory, and how often."""
    fig = px.bar(
        orgs,
        x="count",
        y="organization",
        orientation="h",
        custom_data=["samples", "programs"],
        labels={"count": "Outcomes", "organization": ""},
        color_discrete_sequence=[px.colors.qualitative.Safe[0]],
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{y}</b><br>%{x} outcomes in this subcategory<br>Programs: %{customdata[1]}"
            + SAMPLE_HOVER_BLOCK
            + "<extra></extra>"
        )
    )
    fig.update_layout(
        yaxis=dict(autorange="reversed"),
        height=max(260, 28 * len(orgs) + 80),
        margin=dict(t=10, l=10, r=10, b=10),
    )
    return fig


# =============================================================================
# UI COMPONENTS
# =============================================================================

# Columns shown whenever outcome rows are listed in a table.
DISPLAY_COLUMNS = [COL_ORG_VIEW, COL_PROGRAM, COL_TEXT, COL_DOMAIN, COL_SUBCAT, COL_POP, COL_CONF]
DISPLAY_LABELS = {
    COL_ORG_VIEW: "Organization",
    COL_ORG: "Organization",
    COL_GRANTEE: "Grantee (file name)",
    COL_PROGRAM: "Program",
    COL_TEXT: "Outcome (original text)",
    COL_ATOMIC: "Atomic outcome",
    COL_DOMAIN: "Domain",
    COL_SUBCAT: "Subcategory",
    COL_POP: "Target population",
    COL_CONF: "Confidence",
    COL_QA: "QA status",
    COL_NOTES: "Coder notes",
    COL_SOURCE_FILE: "Source file",
}


def outcome_table(df: pd.DataFrame, columns: Sequence[str] = DISPLAY_COLUMNS, height: Optional[int] = None) -> None:
    """Render outcome rows as a scrollable table with readable headers."""
    cols = [c for c in columns if c in df.columns]
    config = {c: st.column_config.TextColumn(DISPLAY_LABELS.get(c, c)) for c in cols}
    config[COL_TEXT] = st.column_config.TextColumn(DISPLAY_LABELS[COL_TEXT], width="large")
    kwargs = {"height": height} if height else {}
    st.dataframe(df[cols], column_config=config, hide_index=True, **kwargs)


def outcome_inspector(df: pd.DataFrame, title: str, key: str, max_rows: int = 25) -> None:
    """Expandable list of outcome statements behind a chart element.

    This is the "click to reveal" half of the validation tooltips: hover shows
    a few samples, this shows the full set (up to max_rows, with a download).
    """
    with st.expander(f"{title} · {len(df):,} outcomes", expanded=True):
        if df.empty:
            st.info("No outcomes match this selection.")
            return
        shown = df if len(df) <= max_rows else df.sample(max_rows, random_state=0)
        if len(df) > max_rows:
            st.caption(f"Showing a random sample of {max_rows} of {len(df):,}. Download for the full list.")
        outcome_table(shown)
        download_button(df, f"Download these {len(df):,} outcomes", f"outcomes_{key}.csv", key=f"dl_{key}")


def download_button(df: pd.DataFrame, label: str, filename: str, key: str) -> None:
    """CSV download of a filtered view (the export hook for other tools, e.g. a map)."""
    csv = to_export_frame(df).to_csv(index=False).encode("utf-8")
    st.download_button(label, csv, file_name=filename, mime="text/csv", key=key)


def selected_points(event) -> list[dict]:
    """Points the user clicked on a chart rendered with on_select, or [] if none.

    Streamlit's selection event shape has changed between versions, so read it
    defensively.
    """
    if not event:
        return []
    selection = event.get("selection") if isinstance(event, dict) else getattr(event, "selection", None)
    if not selection:
        return []
    points = selection.get("points") if isinstance(selection, dict) else getattr(selection, "points", None)
    return list(points or [])


def point_customdata(point: dict) -> list:
    """The custom_data values attached to a clicked point."""
    data = point.get("customdata")
    if data is None:
        return []
    return list(data) if isinstance(data, (list, tuple)) else [data]


def pretty_population(code: str) -> str:
    return POPULATION_LABELS.get(code, code)


# =============================================================================
# VIEWS
# =============================================================================


def view_system_mapping(df: pd.DataFrame) -> None:
    """View 1: where outcomes (and so resources) are concentrated across the system."""
    st.header("System-Level Policy Mapping")
    st.caption(
        "How the partner portfolio's outcomes spread across the codebook. Large blocks show "
        "where many programs invest; small or missing blocks show thin coverage. "
        "Hover any block or bar to read sample outcome statements."
    )

    if df.empty:
        st.warning("No outcomes match the current filters.")
        return

    # --- Headline numbers -----------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Outcomes", f"{len(df):,}")
    c2.metric("Organizations", f"{df[COL_ORG_VIEW].nunique():,}")
    c3.metric("Programs", f"{df[[COL_ORG_VIEW, COL_PROGRAM]].drop_duplicates().shape[0]:,}")
    c4.metric("Subcategories in use", f"{df.loc[df[COL_SUBCAT] != UNASSIGNED_SUBCAT, COL_SUBCAT].nunique():,}")

    # --- Treemap / sunburst ---------------------------------------------------
    st.subheader("Domains and subcategories")
    chart_type = st.radio("Chart type", ["Treemap", "Sunburst"], horizontal=True, key="v1_chart_type")
    st.plotly_chart(build_hierarchy_chart(df, chart_type), key="v1_hierarchy")
    st.caption("Click a domain to zoom in; click the top bar (treemap) or centre (sunburst) to zoom out.")

    # Drill-down: the full list behind any block of the chart.
    domains = domain_order(df)
    d1, d2 = st.columns(2)
    domain_choice = d1.selectbox("Inspect a domain", domains, key="v1_domain")
    subcats = sorted_subcategories(df.loc[df[COL_DOMAIN] == domain_choice, COL_SUBCAT])
    # Keyed by domain so the choice resets when the domain changes.
    subcat_choice = d2.selectbox(
        "…and optionally one subcategory", ["All subcategories"] + subcats, key=f"v1_subcat_{domain_choice}"
    )
    inspect = filter_outcomes(
        df,
        domains=[domain_choice],
        subcategories=None if subcat_choice == "All subcategories" else [subcat_choice],
    )
    label = domain_choice if subcat_choice == "All subcategories" else subcat_choice
    outcome_inspector(inspect, label, key="v1_hierarchy")

    # --- Stacked bar ----------------------------------------------------------
    st.subheader("Who the outcomes are for")
    st.caption("Outcomes per domain, stacked by target population. Click a bar segment to list its outcomes.")
    event = st.plotly_chart(
        build_domain_population_bar(df),
                key="v1_bar",
        on_select="rerun",
        selection_mode="points",
    )
    points = selected_points(event)
    if points:
        custom = point_customdata(points[0])
        if len(custom) >= 3:
            domain, population = custom[1], custom[2]
            outcome_inspector(
                filter_outcomes(df, domains=[domain], populations=[population]),
                f"{domain} · {pretty_population(population)}",
                key="v1_bar_selection",
            )

    download_button(df, "Download the outcomes behind these charts", "system_mapping_outcomes.csv", key="v1_dl_all")


def view_partnership_discovery(df: pd.DataFrame) -> None:
    """View 2: find organizations pursuing the same developmental goals."""
    st.header("Program Alignment & Partnership Discovery")
    st.caption(
        "Pick an organization to see which peers share the most subcategories with it, or pick a "
        "subcategory to see everyone working toward that goal."
    )

    if df.empty:
        st.warning("No outcomes match the current filters.")
        return

    tab_org, tab_goal = st.tabs(["Peers for an organization", "Organizations by goal"])

    # --- Peers for an organization -------------------------------------------
    with tab_org:
        orgs = sorted(df[COL_ORG_VIEW].unique(), key=str.casefold)
        # Selectboxes are searchable: start typing to narrow the list.
        org = st.selectbox("Organization (type to search)", orgs, key="v2_org")
        org_rows = df[df[COL_ORG_VIEW] == org]
        org_subcats = sorted_subcategories(org_rows.loc[org_rows[COL_SUBCAT] != UNASSIGNED_SUBCAT, COL_SUBCAT])

        c1, c2, c3 = st.columns(3)
        c1.metric("Outcomes", f"{len(org_rows):,}")
        c2.metric("Programs", f"{org_rows[COL_PROGRAM].nunique():,}")
        c3.metric("Subcategories targeted", f"{len(org_subcats):,}")

        peers = compute_peer_overlap(df, org)
        if peers.empty:
            st.info("No other organization shares a subcategory with this one under the current filters.")
        else:
            st.markdown("**Peer matrix** · organizations ranked by shared subcategories")
            st.dataframe(
                peers,
                hide_index=True,
                                height=min(420, 36 * len(peers) + 40),
                column_config={
                    "organization": st.column_config.TextColumn("Peer organization"),
                    "shared_subcategories": st.column_config.NumberColumn(
                        "Shared subcategories", help="Subcategories both organizations target."
                    ),
                    "coverage": st.column_config.ProgressColumn(
                        "Coverage of selected",
                        help="Share of the selected organization's subcategories that this peer also targets.",
                        min_value=0.0, max_value=1.0, format="percent",
                    ),
                    "jaccard": st.column_config.ProgressColumn(
                        "Similarity (Jaccard)",
                        help="Shared ÷ all subcategories either organization targets. "
                             "High means their portfolios look alike overall, not just overlap.",
                        min_value=0.0, max_value=1.0, format="%.2f",
                    ),
                    "peer_outcomes_in_shared": st.column_config.NumberColumn(
                        "Peer outcomes in shared areas",
                        help="How many of the peer's outcomes fall in the shared subcategories.",
                    ),
                    "programs": st.column_config.TextColumn("Peer programs"),
                    "shared_list": st.column_config.TextColumn("Shared subcategories (list)", width="large"),
                },
            )
            slug = re.sub(r"\W+", "_", org).strip("_").lower()
            download_button(peers, "Download peer matrix", f"peers_{slug}.csv", key="v2_dl_peers")

            st.markdown("**Overlap heatmap** · hover a cell to read that organization's outcomes")
            top_n = st.slider("Peers to show", 3, max(3, min(30, len(peers))), min(10, len(peers)), key=f"v2_topn_{org}") \
                if len(peers) > 3 else len(peers)
            counts, samples = peer_heatmap_data(df, org, peers["organization"].head(top_n).tolist())
            st.plotly_chart(build_peer_heatmap(counts, samples), key="v2_heatmap")

            # Click-to-reveal: compare the selected org's outcomes with one peer's, side by side.
            peer = st.selectbox("Compare outcome statements with", peers["organization"].tolist(), key=f"v2_peer_{org}")
            shared = peers.loc[peers["organization"] == peer, "shared_list"].iloc[0].split("; ")
            left, right = st.columns(2)
            with left:
                outcome_inspector(filter_outcomes(df, organizations=[org], subcategories=shared),
                                  f"{org} · shared areas", key="v2_left")
            with right:
                outcome_inspector(filter_outcomes(df, organizations=[peer], subcategories=shared),
                                  f"{peer} · shared areas", key="v2_right")

    # --- Organizations by goal -----------------------------------------------
    with tab_goal:
        all_subcats = sorted_subcategories(df.loc[df[COL_SUBCAT] != UNASSIGNED_SUBCAT, COL_SUBCAT])
        if not all_subcats:
            st.info("No coded subcategories under the current filters.")
            return
        subcat = st.selectbox("Subcategory (type to search)", all_subcats, key="v2_subcat")
        orgs_for = organizations_for_subcategory(df, subcat)
        st.metric("Organizations working toward this goal", f"{len(orgs_for):,}")
        st.caption("Click a bar to list that organization's outcomes in this subcategory.")
        event = st.plotly_chart(
            build_subcategory_org_bar(orgs_for, subcat),
                        key="v2_goal_bar",
            on_select="rerun",
            selection_mode="points",
        )
        points = selected_points(event)
        chosen_org = points[0].get("y") if points else None
        if chosen_org:
            outcome_inspector(filter_outcomes(df, organizations=[chosen_org], subcategories=[subcat]),
                              f"{chosen_org} · {subcat}", key="v2_goal_selection")
        else:
            outcome_inspector(filter_outcomes(df, subcategories=[subcat]), subcat, key="v2_goal_all")


def view_data_governance(df: pd.DataFrame) -> None:
    """View 3: review the coder's output, starting with the least confident rows."""
    st.header("Data Governance & Validation")
    st.caption(
        "Review individual coded outcomes. Filter to low or no-confidence rows to find categorizations "
        "that need a human check."
    )

    if df.empty:
        st.warning("No outcomes match the current filters.")
        return

    # --- Confidence overview --------------------------------------------------
    conf_counts = df[COL_CONF].value_counts()
    cols = st.columns(len(CONFIDENCE_ORDER))
    for col, level in zip(cols, CONFIDENCE_ORDER):
        label = "Not coded (none)" if level == "none" else f"{level.title()} confidence"
        col.metric(label, f"{int(conf_counts.get(level, 0)):,}")

    # --- Filters specific to this view ---------------------------------------
    f1, f2, f3 = st.columns([2, 2, 3])
    present_levels = [c for c in CONFIDENCE_ORDER if c in conf_counts.index] + \
        sorted(set(conf_counts.index) - set(CONFIDENCE_ORDER))
    default_levels = [c for c in ("low", "none") if c in present_levels] or present_levels
    confidences = f1.multiselect("Confidence", present_levels, default=default_levels, key="v3_conf")
    qa_statuses = []
    if COL_QA in df.columns:
        qa_options = sorted(df[COL_QA].dropna().unique())
        qa_statuses = f2.multiselect("QA status", qa_options, key="v3_qa")
    query = f3.text_input("Search outcome text", key="v3_query", placeholder="e.g. confidence, reading, mentor")

    orgs = st.multiselect("Organizations", sorted(df[COL_ORG_VIEW].unique(), key=str.casefold), key="v3_orgs")

    filtered = filter_outcomes(
        df,
        confidences=confidences,
        qa_statuses=qa_statuses,
        organizations=orgs,
        text_query=query,
    ).sort_values([COL_DOMAIN_NUM, COL_SUBCAT, COL_ORG_VIEW])

    # --- Pagination -----------------------------------------------------------
    p1, p2, p3 = st.columns([1, 1, 3])
    page_size = p1.selectbox("Rows per page", [25, 50, 100, 250], index=1, key="v3_page_size")
    n_pages = max(1, -(-len(filtered) // page_size))  # ceiling division
    # The page number lives in session state so it can be reset to 1 when a
    # filter shrinks the result below the current page.
    if st.session_state.get("v3_page", 1) > n_pages:
        st.session_state["v3_page"] = 1
    st.session_state.setdefault("v3_page", 1)
    page = p2.number_input("Page", min_value=1, max_value=n_pages, step=1, key="v3_page")
    start = (page - 1) * page_size
    p3.markdown(
        f"<div style='padding-top:2rem'>Rows {min(start + 1, len(filtered)):,}–"
        f"{min(start + page_size, len(filtered)):,} of {len(filtered):,} · page {page} of {n_pages}</div>",
        unsafe_allow_html=True,
    )

    columns = [COL_ORG_VIEW, COL_PROGRAM, COL_TEXT, COL_ATOMIC, COL_DOMAIN, COL_SUBCAT,
               COL_POP, COL_CONF, COL_QA, COL_NOTES, COL_SOURCE_FILE]
    outcome_table(filtered.iloc[start:start + page_size], columns=columns, height=560)
    download_button(filtered, f"Download all {len(filtered):,} filtered rows", "outcomes_for_review.csv", key="v3_dl")


VIEWS = {
    "1 · System-Level Policy Mapping": view_system_mapping,
    "2 · Program Alignment & Partnerships": view_partnership_discovery,
    "3 · Data Governance & Validation": view_data_governance,
}


# =============================================================================
# MAIN
# =============================================================================


def load_data_or_stop() -> pd.DataFrame:
    """Load the CSV, falling back to an upload box. Stops the app on failure.

    Error handling covers: file not found, unreadable/empty CSV, and CSVs that
    lack the required columns.
    """
    path = resolve_data_path()
    try:
        if path is None:
            raise FileNotFoundError(DATA_FILENAME)
        return load_outcomes_from_path(str(path))
    except FileNotFoundError:
        st.warning(
            f"Could not find **{DATA_FILENAME}**. Put it in the `data/` folder or next to `app.py`, "
            f"set the `{DATA_ENV_VAR}` environment variable to its path, or upload it below."
        )
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        st.error(f"**{path}** could not be read as a CSV: {exc}")
    except MissingColumnsError as exc:
        st.error(f"**{path}** is not a coded-outcomes export. {exc}")

    uploaded = st.file_uploader("Upload a coded outcomes CSV", type="csv")
    if uploaded is None:
        st.stop()
    try:
        return load_outcomes_from_bytes(uploaded.getvalue())
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        st.error(f"The uploaded file could not be read as a CSV: {exc}")
    except MissingColumnsError as exc:
        st.error(f"The uploaded file is not a coded-outcomes export. {exc}")
    st.stop()


def sidebar_filters(df: pd.DataFrame, show_confidence: bool) -> pd.DataFrame:
    """Global filters that apply to every view. Returns the filtered frame."""
    st.sidebar.header("Filters")

    grouping = st.sidebar.radio(
        "Group organizations by",
        list(ORG_GROUPING_OPTIONS),
        key="org_grouping",
        help="The logic model's own name is more specific (e.g. separate Penn departments); "
             "the grantee from the file name groups sub-units under the organization that applied.",
    )
    df = df.assign(**{COL_ORG_VIEW: df[ORG_GROUPING_OPTIONS[grouping]]})

    domains = st.sidebar.multiselect(
        "Domains", domain_order(df), key="f_domains", placeholder="All domains"
    )
    pops = sorted(df[COL_POP].unique())
    populations = st.sidebar.multiselect(
        "Target populations", pops, format_func=pretty_population, key="f_pops", placeholder="All populations"
    )
    confidences = None
    if show_confidence:
        levels = [c for c in CONFIDENCE_ORDER if c in set(df[COL_CONF])]
        confidences = st.sidebar.multiselect(
            "Coder confidence", levels, key="f_conf", placeholder="All confidence levels",
            help="Tip: pick high and medium to leave out categorizations that still need review.",
        )
    else:
        st.sidebar.caption("Confidence is filtered on the page in this view.")

    filtered = filter_outcomes(df, domains=domains, populations=populations, confidences=confidences)
    st.sidebar.caption(f"Showing **{len(filtered):,}** of {len(df):,} outcomes.")
    return filtered


def main() -> None:
    st.set_page_config(page_title="Outcomes Dashboard", page_icon="📊", layout="wide")

    st.sidebar.title("Outcomes Dashboard")
    view_name = st.sidebar.radio("View", list(VIEWS), key="view")

    df = load_data_or_stop()
    filtered = sidebar_filters(df, show_confidence=VIEWS[view_name] is not view_data_governance)
    VIEWS[view_name](filtered)


if __name__ == "__main__":
    main()
