"""
Outcomes Explorer
=================

A Streamlit dashboard for exploring coded outcomes extracted from
youth-serving program logic models. It is built for two audiences:

* The strategic partnerships team, who want to see where the system's
  resources are concentrated (and where they are thin).
* Program operators, who want to find peer organizations aiming at the same
  developmental goals.

Pages (top navigation):

1. What programs aim for - findings, linked priority (or domain) / goal / audience charts, coverage gaps
2. Find peers        - peers for an organization, organizations by goal, program comparison
3. Partners at a school - a school's partners, coded or not, and where their outcomes meet
4. Review coding     - paginated explorer for checking the coder's categorizations

Each page opens on a few plain-language findings and simple ranked charts.
Clicking a bar or dot narrows the charts and the table below it, so readers
can go from the overview down to individual outcome statements.

Run it with:

    streamlit run app.py

Code layout:

* outcomes_data.py - loading, cleaning, filtering, aggregation, findings (no Streamlit)
* charts.py        - Plotly figures and the shared chart theme
* app.py           - this file: page layout, widgets, navigation
"""

from __future__ import annotations

import html
import io
import re
from pathlib import Path
from typing import Callable, Optional, Sequence

import pandas as pd
import streamlit as st

import charts
import schools
from sunburst_component import codebook_sunburst
from outcomes_data import (
    CATEGORY_SEP,
    COL_ATOMIC,
    COL_CONF,
    COL_DOMAIN,
    COL_DOMAIN_NUM,
    COL_DOMAIN_SHORT,
    COL_FULL,
    COL_GRANTEE,
    COL_NOTES,
    COL_OUTCOME,
    COL_ORG,
    COL_ORG_VIEW,
    COL_POP,
    COL_PROGRAM,
    COL_PRIORITY,
    COL_PROGRAM_LABEL,
    COL_QA,
    COL_SOURCE_FILE,
    COL_SOURCE_TYPE,
    COL_SUBCAT,
    COL_TEXT,
    CONFIDENCE_ORDER,
    DATA_ENV_VAR,
    DATA_FILENAME,
    MEASURE_ORGS,
    MEASURE_PROGRAMS,
    MEASURES,
    SUNBURST_MEASURES,
    SUNBURST_SEP,
    ORG_GROUPING_OPTIONS,
    POPULATION_LABELS,
    UNASSIGNED_SUBCAT,
    MissingColumnsError,
    chart_search_index,
    compute_peer_overlap,
    count_organizations,
    domain_order,
    domain_short,
    domain_summary,
    filter_outcomes,
    goal_summary,
    intent_note,
    load_codebook_categories,
    load_codebook_for,
    load_codebook_short_names,
    load_codebook_terms,
    load_codebook_definitions,
    organizations_for_subcategory,
    peer_heatmap_data,
    population_group,
    population_summary,
    portfolio_findings,
    priority_summary,
    program_flows,
    program_labels,
    program_options,
    read_outcomes_csv,
    resolve_data_path,
    sorted_subcategories,
    subcategory_coverage,
    sunburst_nodes,
    to_export_frame,
)

APP_TITLE = "Outcomes Explorer"

# Session-state keys for the filters, so "Clear filters" can reset them.
PLACE_KEYS = {"f_zip": schools.COL_ZIP, "f_council": schools.COL_COUNCIL, "f_network": schools.COL_NETWORK_NAME}
FILTER_KEYS = ["f_domains", "f_pops", "f_orgs", "f_conf", *PLACE_KEYS, "f_schools"]
ALL_DOMAINS = "All domains"
MAX_PROGRAMS = 6
DEFAULT_PROGRAMS = 4
UPLOAD_KEY = "uploaded_csv"          # (file name, bytes) of a CSV uploaded this session
READ_ERRORS = (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError)
VIEWS = ["Wheel", "Ranked", "Sunburst", "Treemap"]
# What the first ranked chart groups by: plain priorities, or the codebook's own domains.
GROUP_PRIORITIES = "Priorities"
GROUP_DOMAINS = "Codebook domains"
GROUPINGS = [GROUP_PRIORITIES, GROUP_DOMAINS]


# =============================================================================
# CACHED LOADERS
# =============================================================================


@st.cache_data(show_spinner="Loading coded outcomes...")
def load_from_path(path: str) -> pd.DataFrame:
    return read_outcomes_csv(path)


@st.cache_data(show_spinner="Loading your file...")
def load_from_bytes(data: bytes) -> pd.DataFrame:
    return read_outcomes_csv(io.BytesIO(data))


def cached_codebook(df: pd.DataFrame) -> pd.DataFrame:
    return _codebook_for_domains(tuple(sorted(df[COL_DOMAIN].dropna().unique())))


@st.cache_data
def _codebook_for_domains(domains: tuple[str, ...]) -> pd.DataFrame:
    return load_codebook_for(pd.DataFrame({COL_DOMAIN: list(domains)}))


# Every click reruns the whole page, so the counts behind the findings, the
# sunburst and the coverage table are kept per filtered frame instead of being
# worked out again. Streamlit keys these caches on the frame's contents.
@st.cache_data(show_spinner=False, max_entries=24)
def cached_sunburst_nodes(df: pd.DataFrame) -> pd.DataFrame:
    return sunburst_nodes(df, cached_codebook(df))


@st.cache_data(show_spinner=False, max_entries=24)
def cached_wheel_nodes(df: pd.DataFrame) -> pd.DataFrame:
    return sunburst_nodes(df, cached_codebook(df), include_empty_goals=True, categories=load_codebook_categories())


@st.cache_data(show_spinner=False)
def cached_definitions() -> dict:
    return load_codebook_definitions()


@st.cache_data(show_spinner=False)
def cached_short_names() -> dict:
    return load_codebook_short_names()


@st.cache_data(show_spinner=False, max_entries=24)
def cached_search_index(df: pd.DataFrame, layout: str) -> dict:
    nodes = cached_wheel_nodes(df) if layout == "equal" else cached_sunburst_nodes(df)
    return chart_search_index(df, nodes, load_codebook_terms())


@st.cache_data(show_spinner=False, max_entries=24)
def cached_coverage(df: pd.DataFrame) -> pd.DataFrame:
    return subcategory_coverage(df, cached_codebook(df))


@st.cache_data(show_spinner=False, max_entries=24)
def cached_findings(df: pd.DataFrame, coverage: pd.DataFrame) -> list[str]:
    return portfolio_findings(df, coverage)


# =============================================================================
# STYLE
# =============================================================================

# The codebook explorer's look (the coder repo's public explorer site): Inter on
# a plain white page, slate greys, one blue, rounded-lg controls, small
# uppercase labels, and quiet hover transitions. Sections are separated by
# space and a hairline rather than boxed, and color is saved for the data.
# Colors match .streamlit/config.toml and charts.py.
INK = charts.TEXT_PRIMARY
MUTED = charts.TEXT_SECONDARY
HAIRLINE = charts.GRID
INK_2 = "#334155"     # slate-700, body text
FAINT = "#94a3b8"     # slate-400
WASH = "#f1f5f9"      # slate-100, the explorer's active-tab and hover fill
ACCENT = charts.PRIMARY
CSS = f"""
<style>
/* The browser's scroll anchoring shifts the page when a table below a chart changes; keep it still. */
[data-testid="stMain"], html, body {{ overflow-anchor: none; }}
.block-container {{ padding-top: 5.25rem; padding-bottom: 4rem; max-width: 1240px; }}
body, .stApp {{ -webkit-font-smoothing: antialiased; }}

/* Top bar, as on the explorer site: the site name, then the pages as quiet pills. */
[data-testid="stHeader"] {{ background: #fff; border-bottom: 1px solid {HAIRLINE}; height: 4rem; }}
[data-testid="stHeader"]::before {{
  content: "{APP_TITLE}"; position: absolute; left: 1.5rem; top: 50%; transform: translateY(-50%);
  font-weight: 700; font-size: 1.15rem; letter-spacing: -0.02em; color: #1e293b; pointer-events: none;
}}
[data-testid="stToolbar"] {{ padding-left: 12.5rem; height: 4rem; align-items: center; }}
@media (max-width: 640px) {{
  [data-testid="stHeader"]::before {{ display: none; }}
  [data-testid="stToolbar"] {{ padding-left: 0.5rem; }}
}}
[data-testid="stTopNavLink"] {{ border-radius: 0.5rem; padding: 0.45rem 0.8rem; transition: background-color .15s, color .15s; }}
[data-testid="stTopNavLink"] p {{ font-size: 0.875rem; font-weight: 500; color: {MUTED}; transition: color .15s; }}
[data-testid="stTopNavLink"]:hover {{ background: #f8fafc; }}
[data-testid="stTopNavLink"]:hover p {{ color: {INK}; }}
[data-testid="stTopNavLink"][aria-current="page"] {{ background: {WASH}; }}
[data-testid="stTopNavLink"][aria-current="page"] p {{ color: {INK}; }}

h1 {{ font-size: 1.75rem !important; font-weight: 600 !important; letter-spacing: -0.025em; line-height: 1.2 !important;
      padding: 0.35rem 0 0 0 !important; color: {INK}; }}
.page-lede {{ color: {MUTED}; font-size: 1rem !important; line-height: 1.6; margin: -0.3rem 0 0.4rem 0;
              max-width: 46rem; }}

.findings {{ margin: 0.35rem 0 0.8rem 0; padding-left: 1.1rem; max-width: 52rem; font-size: 1.0625rem;
             line-height: 1.6; color: {INK_2}; }}
.findings li {{ margin: 0 0 0.3rem 0; padding-left: 0.15rem; }}
.findings li::marker {{ color: #cbd5e1; }}
.findings b {{ color: {INK}; font-weight: 600; }}

/* Sections: a hairline above, no box (see section()). */
[class*="st-key-sec-"] {{ border-top: 1px solid {HAIRLINE}; padding-top: 1.5rem; margin-top: 1.25rem; }}
.sec-title {{ font-size: 1.125rem !important; font-weight: 600; letter-spacing: -0.01em; margin: 0; color: {INK}; }}
.sec-note {{ color: {MUTED}; font-size: 0.875rem !important; margin: 0.15rem 0 0.6rem 0; }}
/* Chart labels are the explorer's small uppercase eyebrows. */
.subhead {{ font-size: 0.6875rem !important; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
            color: {MUTED}; margin: 0.4rem 0 0.25rem 0; }}
.subhead-note {{ font-weight: 500; color: {FAINT}; }}

.status {{ color: {MUTED}; font-size: 0.875rem !important; margin: 0; }}
.status b {{ color: {INK}; font-weight: 600; font-variant-numeric: tabular-nums; }}
.intent {{ color: {MUTED}; font-size: 0.875rem !important; margin: 0.1rem 0 0 0; }}
.intent b {{ color: {INK}; font-weight: 600; }}
.crumb {{ font-size: 0.9375rem !important; margin: 0; color: {MUTED}; }}
.crumb b {{ color: {INK}; font-weight: 600; font-variant-numeric: tabular-nums; }}

.goal-name {{ font-weight: 600; font-size: 0.9375rem !important; margin: 0.8rem 0 0.2rem 0; color: {INK}; }}
.statements {{ margin: 0 0 0.2rem 0; padding: 0; margin-left: 0 !important; list-style: none; font-size: 0.875rem; line-height: 1.55; }}
.statements li {{ margin-bottom: 0.35rem; background: #f8fafc; border-radius: 0.5rem; padding: 0.45rem 0.75rem;
                  color: {INK_2}; }}
.none {{ color: {FAINT}; font-size: 0.875rem; margin: 0; }}

/* Widget labels: small and medium weight, as in the explorer's forms. */
[data-testid="stWidgetLabel"] p {{ font-size: 0.8125rem !important; font-weight: 500; color: {INK_2}; }}

/* Segmented controls look like the explorer's tab switcher: a light track, the chosen option a raised white tab. */
[data-testid="stButtonGroup"] [role="radiogroup"] {{ background: rgba(226, 232, 240, .6); border-radius: 0.5rem;
  padding: 0.25rem; gap: 0.125rem; width: fit-content; max-width: 100%; flex-wrap: wrap; }}
button[data-variant="segmented_control"] {{ border: 0 !important; background: transparent !important;
  border-radius: 0.375rem !important; min-height: 2rem; padding: 0.3rem 0.75rem; box-shadow: none;
  transition: background-color .15s, color .15s, box-shadow .15s; }}
button[data-variant="segmented_control"] p {{ font-size: 0.875rem; color: #475569; }}
button[data-variant="segmented_control"]:hover p {{ color: {INK}; }}
button[data-variant="segmented_control"][aria-checked="true"] {{ background: #fff !important;
  box-shadow: 0 1px 2px rgba(15, 23, 42, .08), 0 0 0 1px rgba(15, 23, 42, .04); }}
button[data-variant="segmented_control"][aria-checked="true"] p {{ color: {INK}; font-weight: 500; }}
button[data-variant="segmented_control"]:disabled {{ opacity: .45; }}

/* Pills (review page) follow the same idea: quiet until chosen. */
button[data-variant*="pills"] {{ transition: background-color .15s, border-color .15s, color .15s; }}

/* Filters and Data: the explorer's secondary button (white, slate border that darkens on hover). */
[data-testid="stPopoverButton"] {{ border-color: #cbd5e1; border-radius: 0.5rem; min-height: 2.5rem;
  transition: border-color .15s, background-color .15s; }}
[data-testid="stPopoverButton"]:hover {{ border-color: {FAINT}; background: #f8fafc; color: {INK}; }}
[data-testid="stPopoverButton"] p {{ font-weight: 500; font-size: 0.875rem; white-space: nowrap; }}
[data-testid="stPopoverButton"] {{ min-width: max-content; }}

/* Search boxes: the explorer's rounded field with a soft blue focus ring. */
[data-testid="stTextInputRootElement"] {{ border-radius: 0.75rem; transition: border-color .15s, box-shadow .15s; }}
[data-testid="stTextInputRootElement"]:focus-within {{ border-color: #60a5fa; box-shadow: 0 0 0 3px rgba(59, 130, 246, .2); }}
[data-testid="stTextInputRootElement"] input::placeholder {{ color: {FAINT}; }}

/* Text buttons (Clear selection, downloads): slate until hovered. */
button[kind="tertiary"] p {{ color: {MUTED}; font-size: 0.875rem; transition: color .15s; }}
button[kind="tertiary"]:hover p {{ color: {INK}; }}

/* Chosen items in multiselects read as quiet chips, not blue buttons. */
[data-testid="stMultiSelect"] [data-tag] {{ background: {WASH} !important; color: {INK} !important; }}
[data-testid="stMultiSelect"] [data-tag] * {{ color: inherit !important; }}
[data-testid="stMultiSelect"] [data-tag] svg {{ color: {MUTED} !important; }}
/* Long names: chosen items wrap onto more lines instead of hiding behind a sideways scroll or "…". */
[data-testid="stMultiSelectTagsContainer"] {{ flex-wrap: wrap !important; overflow: visible !important;
  height: auto !important; }}
[data-testid="stMultiSelect"] div:has([data-testid="stMultiSelectTagsContainer"]) {{ height: auto !important;
  max-height: none !important; }}
[data-testid="stMultiSelect"] [data-tag] {{ max-width: 100% !important; height: auto !important; }}
[data-testid="stMultiSelect"] [data-tag] span {{ white-space: normal !important; overflow: visible !important;
  text-overflow: clip !important; }}

/* Tables and charts sit on the page with a hairline, rounded like the explorer's panels. */
[data-testid="stDataFrame"] {{ border-radius: 0.75rem; overflow: hidden; }}
/* Tabs use the same track as the segmented controls, instead of an underline. */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ background: rgba(226, 232, 240, .6); border-radius: 0.5rem;
  padding: 0.25rem; gap: 0.125rem; width: fit-content; }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"], [data-testid="stTabs"] [data-baseweb="tab-border"] {{ display: none; }}
[data-testid="stTabs"] [data-baseweb="tab"] {{ border-radius: 0.375rem; padding: 0.35rem 0.85rem; height: auto;
  transition: background-color .15s, box-shadow .15s; }}
[data-testid="stTabs"] [data-baseweb="tab"] p {{ font-size: 0.875rem; font-weight: 500; color: #475569; }}
[data-testid="stTabs"] [data-baseweb="tab"]:hover p {{ color: {INK}; }}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {{ background: #fff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, .08), 0 0 0 1px rgba(15, 23, 42, .04); }}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] p {{ color: {INK}; }}

/* New content fades in instead of popping, as the explorer's pages do. */
@keyframes od-fade {{ from {{ opacity: 0; transform: translateY(2px); }} to {{ opacity: 1; transform: none; }} }}
.findings, .sec-title, .crumb {{ animation: od-fade .25s ease-out both; }}
@media (prefers-reduced-motion: reduce) {{ .findings, .sec-title, .crumb {{ animation: none; }} }}
</style>
"""


def page_header(title: str, lede: Optional[str] = None) -> None:
    st.title(title, anchor=False)
    if lede:
        st.markdown(f"<p class='page-lede'>{lede}</p>", unsafe_allow_html=True)


def section(title: Optional[str] = None, note: Optional[str] = None, key: Optional[str] = None):
    """One section of a page, set off by a hairline. Use as `with section("Title", "note"):`."""
    box = st.container(key=f"sec-{key or slug(title or 'section')}")
    if title:
        box.markdown(f"<p class='sec-title'>{html.escape(title)}</p>", unsafe_allow_html=True)
    if note:
        box.markdown(f"<p class='sec-note'>{note}</p>", unsafe_allow_html=True)
    return box


def subhead(text: str, note: str = "") -> None:
    extra = f" <span class='subhead-note'>{html.escape(note)}</span>" if note else ""
    st.markdown(f"<p class='subhead'>{html.escape(text)}{extra}</p>", unsafe_allow_html=True)


def findings(sentences: Sequence[str]) -> None:
    """The page's lead: a few plain-language findings. **bold** marks the numbers."""
    if not sentences:
        return
    items = "".join(f"<li>{bold_markup(s)}</li>" for s in sentences)
    st.markdown(f"<ul class='findings'>{items}</ul>", unsafe_allow_html=True)


def bold_markup(text: str) -> str:
    """Escape text for HTML and turn **x** into <b>x</b>."""
    return re.sub(r"[*][*](.+?)[*][*]", r"<b>\1</b>", html.escape(text))


def plot(fig, key: str, **kwargs):
    """Render a Plotly figure with the dashboard's shared settings."""
    # Set on the figure itself: Streamlit's renderer can override template backgrounds.
    # A chart that picks its own plot color (the heatmap's empty cells) keeps it.
    fig.update_layout(plot_bgcolor=fig.layout.plot_bgcolor or charts.SURFACE, paper_bgcolor="rgba(0,0,0,0)")
    return st.plotly_chart(fig, key=key, config=charts.PLOTLY_CONFIG, theme=None, **kwargs)


def clickable(fig, key: str):
    """Render a chart whose marks can be clicked; return the key (customdata[0]) of the clicked mark, or None.

    The figure must not depend on the selection: Streamlit identifies the
    chart by its figure, so a changed figure would drop the click. Plotly
    styles the clicked mark itself (see charts.SELECTED).
    """
    points = selected_points(plot(fig, key=key, on_select="rerun", selection_mode="points"))
    custom = point_customdata(points[0]) if points else []
    return custom[0] if custom else None


def add_hover_value(fig, values: Sequence, template: str) -> None:
    """Add one more value per bar (customdata[3]) to a ranked bar chart's hover, above the samples."""
    trace = fig.data[0]
    trace.customdata = [list(c) + [v] for c, v in zip(trace.customdata, values)]
    trace.hovertemplate = trace.hovertemplate.replace("<br><br><b>Sample", f"<br>{template}<br><br><b>Sample", 1)


# =============================================================================
# SHARED WIDGETS
# =============================================================================

DISPLAY_LABELS = {
    COL_ORG_VIEW: "Organization",
    COL_ORG: "Organization",
    COL_GRANTEE: "Grantee (file name)",
    COL_PROGRAM: "Program",
    COL_OUTCOME: "Outcome",
    COL_FULL: "From the full statement",
    COL_TEXT: "Original statement",
    COL_ATOMIC: "Atomic outcome",
    COL_DOMAIN: "Domain",
    COL_SUBCAT: "Goal",
    COL_POP: "For",
    COL_CONF: "Confidence",
    COL_QA: "QA status",
    COL_NOTES: "Coder notes",
    COL_SOURCE_FILE: "Source file",
}
# Reading order: who, what they aim for, which goal it counts toward; context last.
DISPLAY_COLUMNS = [COL_ORG_VIEW, COL_OUTCOME, COL_SUBCAT, COL_POP, COL_CONF, COL_PROGRAM, COL_FULL]
# Table cells can't wrap, so columns get pixel widths sized to what they hold:
# names and outcomes get room, short columns stay narrow.
COLUMN_WIDTHS = {COL_ORG_VIEW: 280, COL_PROGRAM: 200, COL_OUTCOME: 380, COL_FULL: 320, COL_SUBCAT: 260,
                 COL_POP: 140, COL_CONF: 100, COL_NOTES: 260, COL_QA: 110, COL_SOURCE_FILE: 260}
# Columns dropped from a table when every row has the same value, since the selection already says it.
REPEATABLE = [COL_ORG_VIEW, COL_PROGRAM, COL_SUBCAT, COL_POP, COL_CONF]


def pretty_population(code: str) -> str:
    return POPULATION_LABELS.get(code, code)


def outcome_table(df: pd.DataFrame, columns: Sequence[str] = DISPLAY_COLUMNS, height="auto") -> None:
    """Outcome rows as a scrollable table with readable headers."""
    cols = [c for c in columns if c in df.columns]
    if len(df) > 1:
        cols = [c for c in cols if not (c in REPEATABLE and df[c].nunique() == 1)]
    if COL_FULL in cols and not df[COL_FULL].fillna("").astype(bool).any():
        cols.remove(COL_FULL)
    config = {c: st.column_config.TextColumn(DISPLAY_LABELS.get(c, c), width=COLUMN_WIDTHS.get(c)) for c in cols}
    config[COL_OUTCOME] = st.column_config.TextColumn(
        DISPLAY_LABELS[COL_OUTCOME], width=COLUMN_WIDTHS[COL_OUTCOME], help="The outcome as the coder categorized it.")
    config[COL_FULL] = st.column_config.TextColumn(
        DISPLAY_LABELS[COL_FULL], width=COLUMN_WIDTHS[COL_FULL],
        help="Filled in only when the coder split a longer statement into separate outcomes.")
    shown = df[cols].copy()
    if COL_POP in shown:
        shown[COL_POP] = shown[COL_POP].map(pretty_population)
    if COL_CONF in shown:
        shown[COL_CONF] = shown[COL_CONF].astype(str).str.title()
    st.dataframe(shown, column_config=config, hide_index=True, height=height)


def download_button(df: pd.DataFrame, label: str, filename: str, key: str) -> None:
    """CSV download of a filtered view (also the hook for other tools, e.g. a map)."""
    csv = to_export_frame(df).to_csv(index=False).encode("utf-8")
    st.download_button(label, csv, file_name=filename, mime="text/csv", key=key, type="tertiary")


def outcomes_panel(rows: pd.DataFrame, where: str, key: str, nonce_key: Optional[str] = None,
                   height: int = 420) -> None:
    """The table a chart above filters: a count of what is selected, a search box, the rows and a download.

    `where` is HTML appended to the count (e.g. " in <b>3. Social…</b>").
    With `nonce_key`, a Clear selection button resets the charts keyed on it.
    """
    head, clear = st.columns([6, 1], vertical_alignment="center")
    head.markdown(f"<p class='crumb'><b>{len(rows):,}</b> outcome statements{where}</p>", unsafe_allow_html=True)
    if nonce_key:
        clear.button("Clear selection", key=f"{key}_clear", type="tertiary", on_click=clear_selection,
                     args=(nonce_key,))
    query = st.text_input("Search these outcomes", key=f"{key}_query", placeholder="Search these outcomes",
                          label_visibility="collapsed")
    if query:
        rows = filter_outcomes(rows, text_query=query)
    # A short list sizes to its rows instead of leaving an empty grid, but its box keeps the
    # full height: a chart click re-filters this table, and a page that grew or shrank would
    # move the chart under the pointer so the next click missed its mark.
    with st.container(key=f"rows-{key}"):
        st.html(f"<style>.st-key-rows-{key} {{ min-height: {height + 60}px; }}</style>")
        outcome_table(rows, height=height if len(rows) > 10 else "auto")
        download_button(rows, f"Download these {len(rows):,} (CSV)", f"outcomes_{key}.csv", key=f"{key}_dl")


def describe(*parts: Optional[str], audience: Optional[str] = None) -> str:
    """ " in <b>A</b> › <b>B</b> for <b>audience</b>", skipping missing parts (escaped)."""
    path = " › ".join(f"<b>{html.escape(p)}</b>" for p in parts if p)
    text = f" in {path}" if path else ""
    if audience:
        text += f" for <b>{html.escape(audience)}</b>"
    return text


def statement_list(texts: Sequence[str]) -> str:
    """Outcome statements as an HTML list (escaped), for side-by-side reading."""
    if len(texts) == 0:
        return "<p class='none'>None in this goal</p>"
    return "<ul class='statements'>" + "".join(f"<li>{html.escape(str(t))}</li>" for t in texts) + "</ul>"


def selected_points(event) -> list[dict]:
    """Points the user clicked on a chart rendered with on_select, or [] if none."""
    if not event:
        return []
    selection = event.get("selection") if isinstance(event, dict) else getattr(event, "selection", None)
    if not selection:
        return []
    points = selection.get("points") if isinstance(selection, dict) else getattr(selection, "points", None)
    return list(points or [])


def point_customdata(point: dict) -> list:
    data = point.get("customdata")
    if data is None:
        return []
    return list(data) if isinstance(data, (list, tuple)) else [data]


def slug(text: str) -> str:
    return re.sub(r"\W+", "_", text).strip("_").lower()


def keep_valid(key: str, options: Sequence) -> None:
    """Drop stale selections from a multiselect's state when its options change."""
    if key in st.session_state:
        valid = set(options)
        st.session_state[key] = [v for v in st.session_state[key] if v in valid]


def clear_selection(nonce_key: str) -> None:
    """Reset every chart selection whose key includes this counter (a new key starts unselected)."""
    st.session_state[nonce_key] = st.session_state.get(nonce_key, 0) + 1


def plain_domain(domain: str) -> str:
    """ "Domain 3. Social & Emotional Learning (CASEL-aligned)" -> "Social & Emotional Learning" """
    return domain_short(domain).split(". ", 1)[-1]


# =============================================================================
# PAGE 1: SYSTEM MAP
# =============================================================================


def page_system_map(df: pd.DataFrame) -> None:
    page_header("What these programs aim for")
    if df.empty:
        st.warning("No outcomes match the current filters. Clear some of them to see results.")
        return

    coverage = cached_coverage(df)
    findings(cached_findings(df, coverage))

    with section("Explore the portfolio", "Click a bar or slice to narrow the charts beside and below it, and the "
                 "outcomes table.", key="explore"):
        t0, t1, t2 = st.columns([3, 3, 3])
        view = t2.segmented_control("View", VIEWS, default="Wheel", key="v1_view") or "Wheel"
        grouping = t0.segmented_control(
            "Group by", GROUPINGS, default=GROUP_PRIORITIES, key="v1_grouping", disabled=view != "Ranked",
            help="Priorities use plain names such as Attendance or Math. Codebook domains are the coder's "
                 "own twelve domains, which the treemap and sunburst always use.",
        ) or GROUP_PRIORITIES
        if view in ("Wheel", "Sunburst"):
            measure = t1.segmented_control(
                "Count", SUNBURST_MEASURES, default=MEASURE_PROGRAMS, key="v1_measure_sb",
                help="Programs and organizations count each one once per goal and once per domain. Outcome "
                     "statements gives more weight to programs that list many outcomes.",
            ) or MEASURE_PROGRAMS
        else:
            measure = t1.segmented_control(
                "Count", MEASURES, default=MEASURE_ORGS, key="v1_measure",
                help="Organizations counts each organization once per goal. Outcome statements gives more weight "
                     "to organizations that list many outcomes.",
            ) or MEASURE_ORGS
        if view in ("Wheel", "Sunburst"):
            chosen_domain = sunburst_view(df, measure, layout="equal" if view == "Wheel" else "value")
        elif view == "Ranked":
            chosen_domain = linked_explorer(df, measure, grouping)
        else:
            chosen_domain = None
            hierarchy_view(df, measure, view)

    thin_goals(coverage, chosen_domain)
    download_button(df, "Download all outcomes on this page (CSV)", "system_map_outcomes.csv", key="v1_dl_all")


def linked_explorer(df: pd.DataFrame, measure: str, grouping: str = GROUP_PRIORITIES) -> Optional[str]:
    """Priorities (or domains), goals and audiences as ranked bars; each click narrows the charts after it
    and the table.

    Returns the selected domain, if any, so the coverage table can follow it.
    Each chart's key includes the selections before it, so picking a new
    priority or domain starts its goals chart unselected.
    """
    value = "organizations" if measure == MEASURE_ORGS else "outcomes"
    other = "outcomes" if value == "organizations" else "organizations"
    noun = "organizations" if value == "organizations" else "outcome statements"
    other_template = ("%{customdata[3]} outcome statements" if value == "organizations"
                      else "%{customdata[3]} organizations")
    by_priority = grouping == GROUP_PRIORITIES
    base = f"v1_{st.session_state.get('v1_nonce', 0)}_{value}_{'pri' if by_priority else 'dom'}"

    left, right = st.columns(2, gap="large")
    with left:
        if by_priority:
            groups = priority_summary(df).sort_values(value, ascending=False, kind="stable")
            subhead("Priorities", f"by {noun}")
            fig = charts.build_ranked_bars(groups, COL_PRIORITY, value, COL_PRIORITY, value_noun=noun)
        else:
            groups = domain_summary(df).sort_values([value, COL_DOMAIN_NUM], ascending=[False, True])
            subhead("Domains", f"by {noun}")
            fig = charts.build_ranked_bars(groups, COL_DOMAIN_SHORT, value, COL_DOMAIN, value_noun=noun)
        add_hover_value(fig, groups[other].tolist(), other_template)
        chosen = clickable(fig, f"{base}_top")

    group_col = COL_PRIORITY if by_priority else COL_DOMAIN
    scope = df if chosen is None else df[df[group_col] == chosen]
    # The coverage table below follows a domain. Each priority sits inside one domain, so it follows that.
    domains_in_scope = scope[COL_DOMAIN].unique() if chosen is not None else []
    domain = domains_in_scope[0] if len(domains_in_scope) == 1 else None
    chosen_name = (chosen if by_priority else plain_domain(chosen)) if chosen else None
    goals = goal_summary(scope).sort_values([value, other], ascending=False)
    if chosen is None:
        goals = goals.head(12)
    goal_key = f"{base}_goal_{slug(chosen or 'all')}"
    goal = None
    with right:
        if chosen is None:
            subhead("Most shared goals", f"top {len(goals)}")
        else:
            subhead(f"Goals in {chosen_name}", f"by {noun}")
        if goals.empty:
            st.caption("No coded goals here.")
        else:
            fig = charts.build_ranked_bars(goals, COL_SUBCAT, value, COL_SUBCAT,
                                           value_noun=noun)
            add_hover_value(fig, goals[other].tolist(), other_template)
            goal = clickable(fig, goal_key)

    if goal is not None:
        scope = scope[scope[COL_SUBCAT] == goal]
    pops = population_summary(scope)
    pop_key = f"{base}_pop_{slug(chosen or 'all')}_{slug(goal or 'all')}"
    subhead("Who these outcomes are for", "outcome statements by target population")
    narrow, _ = st.columns(2, gap="large")
    with narrow:
        fig = charts.build_ranked_bars(pops, "population_group", "outcomes", "population_group", value_noun="outcome statements")
        add_hover_value(fig, pops["organizations"].tolist(), "%{customdata[3]} organizations")
        audience = clickable(fig, pop_key)

    rows = scope if audience is None else scope[scope[COL_POP].map(population_group) == audience]
    selected_any = chosen is not None or goal is not None or audience is not None
    outcomes_panel(rows, describe(chosen_name, goal, audience=audience), key="v1",
                   nonce_key="v1_nonce" if selected_any else None)
    return domain


def sunburst_view(df: pd.DataFrame, measure: str, layout: str = "value") -> Optional[str]:
    """Domains and their goals as one sunburst, styled after the codebook explorer's. A click narrows the table.

    `layout="equal"` draws the wheel: every codebook goal gets the same slice,
    including goals no outcome names, and its count is the length of its bar.

    The chart is drawn in the browser (sunburst_component.py): hovering,
    zooming into a domain and back out cost no rerun. A click sends back the
    picked domain and goal, and only then does this page rerun, to filter
    the table. Changing the count or the filters redraws the chart with its
    open domain kept.

    Returns the selected domain, if any, so the coverage table can follow it.
    """
    nodes = cached_wheel_nodes(df) if layout == "equal" else cached_sunburst_nodes(df)
    key = f"v1sb_{layout}_{st.session_state.get('v1_nonce', 0)}"
    last_key = f"{key}_last"
    data = charts.codebook_sunburst_data(nodes, measure, selected=st.session_state.get(last_key), layout=layout,
                                         short_names=cached_short_names())
    data["search"] = cached_search_index(df, layout)
    data["definitions"] = cached_definitions()
    pick = codebook_sunburst(data, key=key)
    ids = set(nodes["id"])
    if pick and pick["domain"] not in ids:
        pick = None
    if pick and pick.get("goal") and pick["domain"] + SUNBURST_SEP + pick["goal"] not in ids:
        pick = {"domain": pick["domain"], "goal": None}
    if pick and pick.get("category") and pick["domain"] + CATEGORY_SEP + pick["category"] not in ids:
        pick = {"domain": pick["domain"], "goal": None}
    st.session_state[last_key] = pick

    domain = pick["domain"] if pick else None
    goal = pick.get("goal") if pick else None
    category = pick.get("category") if pick and not goal else None
    if category:
        # A category on the wheel's middle ring narrows the table to its goals.
        cat_id = domain + CATEGORY_SEP + category
        goals = nodes.loc[nodes["category"] == cat_id, "goal"].tolist()
        rows = filter_outcomes(df, domains=[domain], subcategories=goals)
    else:
        rows = df if domain is None else filter_outcomes(df, domains=[domain], subcategories=[goal] if goal else None)
    outcomes_panel(rows, describe(domain_short(domain) if domain else None, goal or category), key="v1_sb",
                   nonce_key="v1_nonce" if pick else None)
    return domain


def hierarchy_view(df: pd.DataFrame, measure: str, chart_type: str) -> None:
    """The treemap, with pickers for reading the outcomes behind a block."""
    plot(charts.build_hierarchy_chart(df, measure, chart_type), key="v1_hierarchy")
    back = "the domain's name at the top" if chart_type == "Treemap" else "the center"
    st.caption(f"Click a domain to open its goals, and {back} to go back.")
    d1, d2 = st.columns(2)
    domain_choice = d1.selectbox("Domain", domain_order(df), key="v1_domain", format_func=domain_short)
    subcats = sorted_subcategories(df.loc[df[COL_DOMAIN] == domain_choice, COL_SUBCAT])
    subcat_choice = d2.selectbox("Goal", ["All goals"] + subcats, key=f"v1_subcat_{slug(domain_choice)}")
    goal = None if subcat_choice == "All goals" else subcat_choice
    chosen = filter_outcomes(df, domains=[domain_choice], subcategories=[goal] if goal else None)
    outcomes_panel(chosen, describe(domain_short(domain_choice), goal), key="v1_block")


def thin_goals(coverage: pd.DataFrame, domain: Optional[str]) -> None:
    """Every goal in the codebook, fewest organizations first. Follows the domain picked above."""
    shown = coverage if domain is None else coverage[coverage[COL_DOMAIN] == domain]
    zero = int((shown["organizations"] == 0).sum())
    note = "Every goal in the codebook, fewest organizations first." + (
        f" {zero} {'has' if zero == 1 else 'have'} no program yet." if zero else "")
    title = "Where coverage is thin" + (f" in {plain_domain(domain)}" if domain else "")
    with section(title, note, key="coverage"):
        st.dataframe(
            shown[[COL_SUBCAT, COL_DOMAIN_SHORT, "organizations", "programs", "outcomes"]],
            hide_index=True,
            height=min(400, 35 * len(shown) + 38),
            column_config={
                COL_SUBCAT: st.column_config.TextColumn("Goal", width=320),
                COL_DOMAIN_SHORT: st.column_config.TextColumn("Domain", width=300),
                "organizations": st.column_config.ProgressColumn(
                    "Organizations", format="%d", min_value=0,
                    max_value=int(coverage["organizations"].max() or 1)),
                "programs": st.column_config.NumberColumn("Programs", width="small"),
                "outcomes": st.column_config.NumberColumn("Statements", width="small",
                                                          help="Outcome statements"),
            },
        )
        download_button(shown.drop(columns=["samples"]), "Download this table (CSV)", "goal_coverage.csv",
                        key="v1_dl_cov")


# =============================================================================
# PAGE 2: FIND PEERS
# =============================================================================


def page_find_peers(df: pd.DataFrame) -> None:
    page_header(
        "Find peers",
        "Start from an organization to see who shares its goals, from a goal to see who works on it, "
        "or compare a few programs side by side.",
    )
    if df.empty:
        st.warning("No outcomes match the current filters. Clear some of them to see results.")
        return

    tab_org, tab_goal, tab_compare = st.tabs(["Peers for an organization", "Who works on a goal",
                                              "Compare programs"])
    with tab_org:
        peers_for_organization(df)
    with tab_goal:
        organizations_for_goal(df)
    with tab_compare:
        compare_programs(df)


def peers_for_organization(df: pd.DataFrame) -> None:
    orgs = sorted(df[COL_ORG_VIEW].unique(), key=str.casefold)
    org = st.selectbox("Organization", orgs, key="v2_org", placeholder="Type to search organizations")
    if org is None:
        return
    org_rows = df[df[COL_ORG_VIEW] == org]
    org_subcats = sorted_subcategories(org_rows.loc[org_rows[COL_SUBCAT] != UNASSIGNED_SUBCAT, COL_SUBCAT])
    peers = compute_peer_overlap(df, org)
    n_programs = org_rows[COL_PROGRAM].nunique()
    findings([
        f"{org} runs **{n_programs} program{'s' if n_programs != 1 else ''}** with "
        f"**{len(org_rows):,} outcome statements** across **{len(org_subcats)} goals**.",
        (f"**{len(peers)} organizations** share at least one of those goals. The closest, "
         f"{peers.iloc[0]['organization']}, shares **{int(peers.iloc[0]['shared_subcategories'])}**."
         if not peers.empty else "No other organization shares any of its goals under the current filters."),
    ])
    if peers.empty:
        return

    with section("Closest peers", "Ranked by shared goals. Select a row to read the two organizations' "
                 "outcomes side by side.", key="peer_matrix"):
        table = peers.assign(coverage=(peers["coverage"] * 100).round().astype(int))
        event = st.dataframe(
            table,
            hide_index=True,
            key=f"v2_peer_table_{slug(org)}",
            on_select="rerun",
            selection_mode="single-row",
            height=min(400, 35 * len(peers) + 38),
            column_order=["organization", "shared_subcategories", "coverage", "jaccard", "shared_list"],
            column_config={
                "organization": st.column_config.TextColumn("Peer organization", width=260),
                "shared_subcategories": st.column_config.NumberColumn(
                    "Shared goals", help="Goals both organizations target."),
                "coverage": st.column_config.ProgressColumn(
                    "Covers", help=f"Share of {org}'s goals this peer also targets.",
                    min_value=0, max_value=100, format="%d%%"),
                "jaccard": st.column_config.ProgressColumn(
                    "Overall overlap", help="Shared goals divided by all goals either organization targets. "
                                            "High means the two portfolios look alike overall.",
                    min_value=0.0, max_value=1.0, format="%.2f"),
                "shared_list": st.column_config.TextColumn("Shared goals, listed", width=420,
                                                           help="The full list is in the CSV download."),
            },
        )
        download_button(peers, "Download the peer list (CSV)", f"peers_{slug(org)}.csv", key="v2_dl_peers")

    rows = event.selection.rows if event and hasattr(event, "selection") else []
    peer = peers.iloc[rows[0]]["organization"] if rows else peers.iloc[0]["organization"]
    shared = sorted_subcategories(peers.loc[peers["organization"] == peer, "shared_list"].iloc[0].split("; "))
    side_by_side(df, org, peer, shared, picked=bool(rows))

    with section("Overlap across peers", "Outcome statements each peer has in each of this organization's "
                 "goals. Empty cells mean none. Hover a cell to read them.", key="peer_heatmap"):
        max_peers = min(30, len(peers))
        top_n = st.slider("Peers to show", 1, max_peers, min(10, max_peers), key=f"v2_topn_{slug(org)}") \
            if max_peers > 1 else 1
        counts, samples = peer_heatmap_data(df, org, peers["organization"].head(top_n).tolist())
        plot(charts.build_peer_heatmap(counts, samples), key="v2_heatmap")


def side_by_side(df: pd.DataFrame, org: str, peer: str, shared: list[str], picked: bool) -> None:
    """Both organizations' outcome statements, goal by goal, in full."""
    note = f"Their outcomes in the {len(shared)} goals they share." + (
        "" if picked else " This is the closest peer; select another row above to switch.")
    with section(f"{org} and {peer}", note, key="peer_pair"):
        pair = df[df[COL_ORG_VIEW].isin([org, peer]) & df[COL_SUBCAT].isin(shared)]
        h1, h2 = st.columns(2, gap="large")
        h1.markdown(f"<p class='subhead'>{html.escape(org)}</p>", unsafe_allow_html=True)
        h2.markdown(f"<p class='subhead'>{html.escape(peer)}</p>", unsafe_allow_html=True)
        with st.container(height=520, border=False):
            for goal in shared:
                st.markdown(f"<p class='goal-name'>{html.escape(goal)}</p>", unsafe_allow_html=True)
                c1, c2 = st.columns(2, gap="large")
                for col, who in ((c1, org), (c2, peer)):
                    texts = pair.loc[(pair[COL_ORG_VIEW] == who) & (pair[COL_SUBCAT] == goal), COL_OUTCOME]
                    col.markdown(statement_list(texts.tolist()), unsafe_allow_html=True)
        download_button(pair, "Download both lists (CSV)", f"peers_{slug(org)}_{slug(peer)}.csv",
                        key="v2_dl_pair")


def organizations_for_goal(df: pd.DataFrame) -> None:
    all_subcats = sorted_subcategories(df.loc[df[COL_SUBCAT] != UNASSIGNED_SUBCAT, COL_SUBCAT])
    if not all_subcats:
        st.info("No coded goals under the current filters.")
        return
    subcat = st.selectbox("Goal", all_subcats, key="v2_subcat", placeholder="Type to search goals")
    if subcat is None:
        return
    orgs_for = organizations_for_subcategory(df, subcat)
    goal_rows = df[df[COL_SUBCAT] == subcat]
    n_programs = goal_rows[[COL_ORG_VIEW, COL_PROGRAM]].drop_duplicates().shape[0]
    findings([f"**{len(orgs_for)} organizations** work on this goal, through **{n_programs} programs** and "
              f"**{len(goal_rows):,} outcome statements**."])
    with section("Organizations working on this goal", "Click a bar to show only that organization's "
                 "outcomes in the table.", key="goal_orgs"):
        key = f"v2_goal_bar_{st.session_state.get('v2_goal_nonce', 0)}_{slug(subcat)}"
        fig = charts.build_ranked_bars(orgs_for, "organization", "count", "organization", value_noun="outcome statements in this goal")
        add_hover_value(fig, orgs_for["programs"].tolist(), "Programs: %{customdata[3]}")
        chosen = clickable(fig, key)
        rows = goal_rows if chosen is None else goal_rows[goal_rows[COL_ORG_VIEW] == chosen]
        where = f" from <b>{html.escape(chosen)}</b>" if chosen else " in this goal"
        outcomes_panel(rows, where, key="v2_goal", nonce_key="v2_goal_nonce" if chosen else None, height=360)


def default_programs(df: pd.DataFrame, options: pd.DataFrame) -> list[str]:
    """Start the comparison with the organization picked on the peers tab and its closest peers."""
    org = st.session_state.get("v2_org")
    if org not in set(options[COL_ORG_VIEW]):
        return options[COL_PROGRAM_LABEL].head(3).tolist()
    peers = compute_peer_overlap(df, org)
    orgs = [org] + (peers["organization"].head(3).tolist() if not peers.empty else [])
    chosen = options[options[COL_ORG_VIEW].isin(orgs)]
    chosen = chosen.assign(_rank=chosen[COL_ORG_VIEW].map({o: i for i, o in enumerate(orgs)}))
    return chosen.sort_values(["_rank", "outcomes"], ascending=[True, False])[COL_PROGRAM_LABEL].head(
        DEFAULT_PROGRAMS).tolist()


def compare_programs(df: pd.DataFrame) -> None:
    options = program_options(df)
    labels = options[COL_PROGRAM_LABEL].tolist()
    keep_valid("v2_programs", labels)
    if not st.session_state.get("v2_programs"):
        st.session_state["v2_programs"] = default_programs(df, options)
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    programs = c1.multiselect(
        "Programs to compare", labels, key="v2_programs", max_selections=MAX_PROGRAMS,
        placeholder="Type to search programs",
        help=f"Up to {MAX_PROGRAMS}. It starts with the organization picked on the first tab and its "
             "closest peers.",
    )
    if not programs:
        st.info("Pick at least one program to compare.")
        return

    overview = program_flows(df, programs)
    domains = list(dict.fromkeys(overview["target"]))
    # A clicked domain header asks for its goals on the next run, before the Columns box is drawn.
    if "v2_zoom_next" in st.session_state:
        st.session_state["v2_zoom"] = st.session_state.pop("v2_zoom_next")
    if st.session_state.get("v2_zoom") not in [ALL_DOMAINS] + domains:
        st.session_state.pop("v2_zoom", None)
    zoom = c2.selectbox("Columns", [ALL_DOMAINS] + domains, key="v2_zoom",
                        format_func=lambda d: "Domains" if d == ALL_DOMAINS else f"Goals in {plain_domain(d)}")
    zoomed = zoom != ALL_DOMAINS
    flows = program_flows(df, programs, domain=zoom) if zoomed else overview

    title = f"Where these programs meet in {plain_domain(zoom)}" if zoomed else "Where these programs meet"
    note = ("Bigger dots mean more outcome statements. Click a dot to list its outcomes below."
            if zoomed else
            "Bigger dots mean more outcome statements. Click a domain name to see its goals, "
            "or a dot to list its outcomes below.")
    with section(title, note, key="dots"):
        if zoomed:
            st.button("‹ All domains", key="v2_unzoom", type="tertiary",
                      on_click=lambda: st.session_state.update(v2_zoom=ALL_DOMAINS))
        # The key changes with the programs and columns, so a new comparison starts unselected.
        key = (f"v2_dots_{st.session_state.get('v2_dot_nonce', 0)}_{slug(zoom)}_"
               f"{slug('_'.join(programs))[:80]}")
        cell = clickable(charts.build_program_dots(flows, programs, zoomed=zoomed), key)
        if cell and cell.startswith(charts.DOMAIN_KEY):
            st.session_state["v2_zoom_next"] = cell.removeprefix(charts.DOMAIN_KEY)
            clear_selection("v2_dot_nonce")
            st.rerun()
        rows = df.assign(**{COL_PROGRAM_LABEL: program_labels(df)})
        rows = rows[rows[COL_PROGRAM_LABEL].isin(programs)]
        if zoomed:
            rows = rows[rows[COL_DOMAIN] == zoom]
        where = " from these programs"
        if cell:
            program, target = cell.split("||", 1)
            rows = rows[(rows[COL_PROGRAM_LABEL] == program)
                        & (rows[COL_SUBCAT if zoomed else COL_DOMAIN] == target)]
            where = f" from <b>{html.escape(program)}</b>" + describe(target if zoomed else domain_short(target))
        outcomes_panel(rows, where, key="v2_compare", nonce_key="v2_dot_nonce" if cell else None, height=360)


# =============================================================================
# PAGE 3: REVIEW CODING
# =============================================================================


def page_review(df: pd.DataFrame) -> None:
    page_header("Review coding",
                "Check individual categorizations, starting with the ones the coder was least sure about.")
    if df.empty:
        st.warning("No outcomes match the current filters. Clear some of them to see results.")
        return

    conf_counts = df[COL_CONF].value_counts().reindex(CONFIDENCE_ORDER).dropna().astype(int)
    present = list(conf_counts.index) + sorted(set(df[COL_CONF]) - set(CONFIDENCE_ORDER))
    unsure = int(conf_counts.reindex(["low", "none"]).fillna(0).sum())
    findings([f"The coder was highly confident about **{int(conf_counts.get('high', 0)) / len(df):.0%}** of "
              f"these outcomes. **{unsure:,}** were rated low or none; the list starts with those."])

    with section("How sure the coder was", key="review_filters"):
        plot(charts.build_confidence_bar(conf_counts), key="v3_conf_bar")
        f1, f2 = st.columns([3, 2])
        confidences = f1.pills(
            "Confidence", present, selection_mode="multi",
            default=[c for c in ("low", "none") if c in present] or present, key="v3_conf",
            format_func=lambda c: f"{c.title()} ({int(conf_counts.get(c, 0)):,})",
        )
        qa_statuses = []
        if COL_QA in df.columns:
            qa_statuses = f2.pills("QA status", sorted(df[COL_QA].dropna().unique()), selection_mode="multi",
                                   key="v3_qa")
        query = st.text_input("Search outcome text", key="v3_query",
                              placeholder="For example: confidence, reading, mentor")

    filtered = filter_outcomes(df, confidences=confidences, qa_statuses=qa_statuses, text_query=query) \
        .sort_values([COL_DOMAIN_NUM, COL_SUBCAT, COL_ORG_VIEW])

    page_size = 50
    n_pages = max(1, -(-len(filtered) // page_size))  # ceiling division
    # Page number lives in session state so it can reset when filters shrink the result.
    if st.session_state.get("v3_page", 1) > n_pages:
        st.session_state["v3_page"] = 1
    st.session_state.setdefault("v3_page", 1)
    page = st.session_state["v3_page"]
    start = (page - 1) * page_size

    shown = (f"Showing {start + 1:,}–{min(start + page_size, len(filtered)):,}, sorted by domain and goal."
             if len(filtered) > page_size else "Sorted by domain and goal.")
    with section(f"{len(filtered):,} outcomes to check", shown, key="review_table"):
        # What a reviewer checks first (outcome, goal, confidence, notes) comes before the context.
        columns = [COL_ORG_VIEW, COL_OUTCOME, COL_SUBCAT, COL_CONF, COL_NOTES, COL_QA, COL_PROGRAM, COL_FULL,
                   COL_SOURCE_FILE]
        outcome_table(filtered.iloc[start:start + page_size], columns=columns, height=560)
        if n_pages > 1:
            p1, _, p3 = st.columns([1, 2, 4], vertical_alignment="bottom")
            p1.number_input(f"Page (of {n_pages})", min_value=1, max_value=n_pages, step=1, key="v3_page")
        else:
            p3 = st.container()
        with p3:
            download_button(filtered, f"Download all {len(filtered):,} rows (CSV)", "outcomes_for_review.csv",
                            key="v3_dl")


# =============================================================================
# PAGE 4: PARTNERS AT A SCHOOL
# =============================================================================

SCHOOL_UPLOAD_KEY = "school_tables"   # {kind: (file name, bytes)} uploaded this session


@st.cache_data(show_spinner="Loading the school tables...")
def load_school_table_bytes(data: bytes, name: str) -> tuple[str, pd.DataFrame]:
    return schools.read_table_bytes(data, name)


@st.cache_data(show_spinner="Loading the school tables...")
def load_school_table_path(path: str, modified: float) -> tuple[str, pd.DataFrame]:
    return schools.read_table(path)


@st.cache_data(ttl=60)
def local_school_tables() -> dict[str, str]:
    return {kind: str(path) for kind, path in schools.find_local_tables().items()}


def school_tables() -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """The relationship and schools tables: uploaded this session, else found in data/. Returns (tables, file names)."""
    uploaded = st.session_state.get(SCHOOL_UPLOAD_KEY, {})
    local = local_school_tables()
    tables, names = {}, {}
    for kind in (schools.RELATIONSHIPS, schools.SCHOOLS):
        if kind in uploaded:
            name, data = uploaded[kind]
            tables[kind] = load_school_table_bytes(data, name)[1]
            names[kind] = name
        elif kind in local:
            path = local[kind]
            tables[kind] = load_school_table_path(path, Path(path).stat().st_mtime)[1]
            names[kind] = Path(path).name
    return tables, names


def school_uploader(key: str) -> None:
    """Takes either table, or both at once, and tells them apart by their columns."""
    files = st.file_uploader("Program-to-school table and schools table", type=["xlsx", "csv"],
                             accept_multiple_files=True, key=key, label_visibility="collapsed")
    stored = st.session_state.setdefault(SCHOOL_UPLOAD_KEY, {})
    changed = False
    for file in files or []:
        try:
            kind, _ = load_school_table_bytes(file.getvalue(), file.name)
        except schools.NotASchoolTableError as exc:
            st.error(str(exc))
            continue
        except (ValueError, *READ_ERRORS) as exc:
            st.error(f"{file.name} could not be read: {exc}")
            continue
        if stored.get(kind) != (file.name, file.getvalue()):
            stored[kind] = (file.name, file.getvalue())
            changed = True
    if changed:
        st.rerun()


def page_schools(df: pd.DataFrame, everything: pd.DataFrame) -> None:
    """Pick a school and see its partners: which have coded outcomes, and where those outcomes meet.

    `df` is the filtered data the charts show; `everything` is the whole file,
    so whether a partner counts as coded never depends on the filters.
    """
    page_header("Partners at a school")
    tables, names = school_tables()
    relationships = tables.get(schools.RELATIONSHIPS)
    if relationships is None:
        with section("Add the school tables", key="school_upload"):
            st.markdown(
                "This page needs the district's program-to-school table (partner, program and school IDs), and "
                "the schools table that names each ULCS code. Drop both files here; they stay in this browser "
                "session.")
            school_uploader("school_upload_first")
        st.caption("Running locally? Put both files in `data/` and they load automatically.")
        return

    school_list = tables.get(schools.SCHOOLS)
    coded_all = schools.with_program_ids(everything)
    joined = schools.join_summary(coded_all, relationships)
    year = schools.fiscal_year_label(relationships[schools.COL_YEAR].dropna().max()
                                     if relationships[schools.COL_YEAR].notna().any() else "")
    options = schools.school_options(relationships, school_list)
    by_code = options.set_index(schools.COL_ULCS)

    def school_label(code: str) -> str:
        level = by_code.at[code, schools.COL_LEVEL] if schools.COL_LEVEL in by_code else None
        return by_code.at[code, schools.COL_SCHOOL] + (f" · {level}" if isinstance(level, str) else "")

    pick, data_col = st.columns([4, 1], vertical_alignment="bottom")
    ulcs = pick.selectbox("School", options[schools.COL_ULCS].tolist(), index=None, key="v4_school",
                          format_func=school_label, placeholder="Type to search schools")
    with data_col.popover("School tables", width="stretch"):
        st.markdown(f"Programs and schools from **{names.get(schools.RELATIONSHIPS)}**"
                    + (f" and **{names[schools.SCHOOLS]}**" if schools.SCHOOLS in names else "")
                    + (f", fiscal year {year}." if year else "."))
        st.markdown(
            f"Coded outcomes join on district partner and program IDs, never on names. "
            f"**{joined['with_ids']} of {joined['programs']}** coded programs in the loaded file carry those IDs, "
            f"and **{joined['matched']}** of them appear in the program-to-school table.")
        school_uploader("school_upload_replace")

    if ulcs is None:
        with_partners = int((options["programs"] > 0).sum())
        findings([
            f"**{with_partners} schools** host partner programs" + (f" in {year}." if year else "."),
            f"At **{joined['schools']}** of them, at least one partner has coded outcomes. "
            "Pick a school to see who works there and what they aim for.",
        ])
        return

    school_name = by_code.at[ulcs, schools.COL_SCHOOL]
    portfolio = schools.school_portfolio(relationships, ulcs, coded_all)
    labels = dict(zip(portfolio[schools.COL_PARTNER_ID], portfolio[schools.COL_PARTNER]))
    rows = schools.school_outcomes(schools.with_program_ids(df), relationships, ulcs, labels)
    rows = rows.assign(**{COL_ORG_VIEW: rows[schools.COL_PARTNER]})
    findings(schools.school_findings(school_name, portfolio, rows, year))
    if portfolio.empty:
        return

    coded = portfolio[portfolio["status"] != schools.NOT_CODED]
    if not coded.empty:
        school_dots(rows, portfolio, ulcs)
    school_partner_list(portfolio, school_name, ulcs)


def school_dots(rows: pd.DataFrame, portfolio: pd.DataFrame, ulcs: str) -> None:
    """Partners (rows) by domain, with partners lacking coded outcomes as grey rows; clicks narrow the table."""
    plotted = [p for p in portfolio.loc[portfolio["status"] != schools.NOT_CODED, schools.COL_PARTNER]
               if p in set(rows[schools.COL_PARTNER])]
    overview = schools.partner_flows(rows)
    domains = list(dict.fromkeys(overview["target"]))
    if "v4_zoom_next" in st.session_state:
        st.session_state["v4_zoom"] = st.session_state.pop("v4_zoom_next")
    zoom = st.session_state.get("v4_zoom")
    if zoom not in domains:
        zoom = st.session_state["v4_zoom"] = None
    flows = schools.partner_flows(rows, domain=zoom) if zoom else overview

    filtered_out = [(p, "None under the current filters")
                    for p in portfolio.loc[portfolio["status"] != schools.NOT_CODED, schools.COL_PARTNER]
                    if p not in plotted]
    not_coded = [(p, "Not yet coded")
                 for p in portfolio.loc[portfolio["status"] == schools.NOT_CODED, schools.COL_PARTNER]]
    title = f"Where these partners meet in {plain_domain(zoom)}" if zoom else "Where these partners meet"
    note = ("Bigger dots mean more outcome statements. Click a dot to list its outcomes below." if zoom else
            "Bigger dots mean more outcome statements. Click a domain name to see its goals, or a dot to list "
            "its outcomes below. Grey rows are partners here without coded outcomes.")
    with section(title, note, key="school_dots"):
        if zoom:
            st.button("‹ All domains", key="v4_unzoom", type="tertiary",
                      on_click=lambda: st.session_state.update(v4_zoom=None))
        if flows.empty:
            st.caption("None of these partners' outcomes match the current filters.")
            cell = None
        else:
            key = f"v4_dots_{st.session_state.get('v4_dot_nonce', 0)}_{ulcs}_{slug(zoom or 'all')}_{len(rows)}"
            fig = charts.build_school_dots(flows, plotted, filtered_out + not_coded, zoomed=bool(zoom))
            cell = clickable(fig, key) or None
        if cell and cell.startswith(charts.DOMAIN_KEY):
            st.session_state["v4_zoom_next"] = cell.removeprefix(charts.DOMAIN_KEY)
            clear_selection("v4_dot_nonce")
            st.rerun()
        shown = rows if not zoom else rows[rows[COL_DOMAIN] == zoom]
        where = " from the partners at this school"
        if cell:
            partner, target = cell.split("||", 1)
            shown = shown[(shown[schools.COL_PARTNER] == partner)
                          & (shown[COL_SUBCAT if zoom else COL_DOMAIN] == target)]
            where = f" from <b>{html.escape(partner)}</b>" + describe(target if zoom else domain_short(target))
        elif zoom:
            where += describe(domain_short(zoom))
        outcomes_panel(shown, where, key="v4_school", nonce_key="v4_dot_nonce" if cell else None, height=360)


def school_partner_list(portfolio: pd.DataFrame, school_name: str, ulcs: str) -> None:
    """Every partner at the school, coded or not, with its programs here."""
    n_coded = int((portfolio["status"] != schools.NOT_CODED).sum())
    with section("Every partner here", f"{n_coded} of {len(portfolio)} have coded outcomes. Partners without a "
                 "name in the loaded file show their district partner ID.", key="school_partners"):
        st.dataframe(
            portfolio[[schools.COL_PARTNER, "status", "programs_here", "coded_programs", "outcomes",
                       "program_names", schools.COL_PARTNER_ID]],
            hide_index=True,
            height=min(420, 35 * len(portfolio) + 38),
            column_config={
                schools.COL_PARTNER: st.column_config.TextColumn("Partner", width=240),
                "status": st.column_config.TextColumn("Outcomes", width="small"),
                "programs_here": st.column_config.NumberColumn("Programs here"),
                "coded_programs": st.column_config.NumberColumn("Coded"),
                "outcomes": st.column_config.NumberColumn("Statements", help="Outcome statements"),
                "program_names": st.column_config.TextColumn("Programs", width=320),
                schools.COL_PARTNER_ID: st.column_config.TextColumn("Partner ID", width="small"),
            },
        )
        csv = portfolio.to_csv(index=False).encode("utf-8")
        st.download_button("Download this list (CSV)", csv, file_name=f"partners_{ulcs}_{slug(school_name)}.csv",
                           mime="text/csv", key="v4_dl_partners", type="tertiary")


# =============================================================================
# DATA, FILTER BAR, NAVIGATION
# =============================================================================


def _read_or_report(loader: Callable[[], pd.DataFrame], source: str) -> Optional[pd.DataFrame]:
    try:
        return loader()
    except READ_ERRORS as exc:
        st.error(f"{source} could not be read as a CSV: {exc}")
    except MissingColumnsError as exc:
        st.error(f"{source} is not a coded-outcomes export. {exc}")
    return None


def remember_upload(uploaded) -> None:
    """Keep an uploaded file for the rest of the session, so switching pages doesn't lose it."""
    if uploaded is not None:
        st.session_state[UPLOAD_KEY] = (uploaded.name, uploaded.getvalue())


def load_data() -> tuple[Optional[pd.DataFrame], str]:
    """Return (data, source description). Data is None when nothing is loaded yet."""
    if UPLOAD_KEY in st.session_state:
        name, data = st.session_state[UPLOAD_KEY]
        return _read_or_report(lambda: load_from_bytes(data), f"**{name}**"), name
    path = resolve_data_path()
    if path is None:
        return None, ""
    try:
        return _read_or_report(lambda: load_from_path(str(path)), f"**{path.name}**"), path.name
    except FileNotFoundError:
        return None, ""


def welcome_screen() -> None:
    """Shown until a CSV is available: explains what to upload."""
    page_header(APP_TITLE, "Explore outcomes coded from partner programs' logic models: where the portfolio "
                           "concentrates, which organizations share goals, and which categorizations need a "
                           "human check.")
    with section("Upload a coded outcomes export", key="welcome"):
        st.markdown(
            f"Use the CSV exported by the Qualitative Outcomes Coder, such as `{DATA_FILENAME}`. "
            "The file stays in this browser session and is not saved once you close the tab."
        )
        uploaded = st.file_uploader("Coded outcomes CSV", type="csv", label_visibility="collapsed")
        if uploaded is not None:
            remember_upload(uploaded)
            st.rerun()
    st.caption(
        f"Running locally? Put the file in `data/{DATA_FILENAME}` or set `{DATA_ENV_VAR}` to its path "
        "and it loads automatically."
    )


def reset_filters() -> None:
    for key in FILTER_KEYS:
        st.session_state.pop(key, None)


FILTER_NOUNS = {"f_domains": ("domain", "domains"), "f_pops": ("audience", "audiences"),
                "f_orgs": ("organization", "organizations"), "f_conf": ("confidence level", "confidence levels"),
                "f_zip": ("zip code", "zip codes"), "f_council": ("council district", "council districts"),
                "f_network": ("learning network", "learning networks"), "f_schools": ("school", "schools")}


def place_filters(df: pd.DataFrame) -> Optional[pd.Series]:
    """Zip code, council district, learning network and school pickers, inside the Filters menu.

    A place keeps the outcomes of programs that run at its schools, joined on
    district partner and program IDs (the school tables must be loaded).
    Returns a row mask for `df`, or None when no place is picked.
    """
    st.markdown("**Where programs run**")
    tables, _ = school_tables()
    relationships = tables.get(schools.RELATIONSHIPS)
    if relationships is None:
        st.caption("Add the program-to-school table and the schools table to filter by zip code, council "
                   "district, learning network or school.")
        school_uploader("school_upload_filters")
        return None
    school_list = tables.get(schools.SCHOOLS)
    labels = {"f_zip": "Zip codes", "f_council": "City Council districts", "f_network": "Learning networks"}
    places = {}
    for key, column in PLACE_KEYS.items():
        values = schools.place_values(school_list, relationships, column)
        if not values:
            continue
        keep_valid(key, values)
        places[column] = st.multiselect(
            labels[key], values, key=key, placeholder="Anywhere",
            format_func=(lambda v: f"District {v}") if key == "f_council" else str)
    # The school list follows the other place choices.
    options = schools.school_options(relationships, school_list)
    nearby = schools.matching_schools(school_list, relationships, places)
    options = options[options[schools.COL_ULCS].isin(nearby | set(st.session_state.get("f_schools", [])))]
    names = dict(zip(options[schools.COL_ULCS], options[schools.COL_SCHOOL]))
    keep_valid("f_schools", list(names))
    picked = st.multiselect("Schools", list(names), key="f_schools", placeholder="All schools",
                            format_func=lambda code: names.get(code, f"School {code}"))
    if not any(places.values()) and not picked:
        return None
    codes = schools.matching_schools(school_list, relationships, places, picked)
    with_ids = schools.with_program_ids(df)
    unplaced = with_ids[schools.COL_PROGRAM_ID].isna()
    if unplaced.any():
        st.caption(f"{int(unplaced.sum()):,} outcome statements have no district program ID, so they can't be "
                   "placed at a school and drop out while a place is picked.")
    return schools.at_schools(with_ids, relationships, codes)


def filter_bar(df: pd.DataFrame, source: str, page_key: str) -> pd.DataFrame:
    """One row above every page: what is showing, a Filters menu and a Data menu. Returns the filtered frame."""
    status, filters_col, data_col = st.columns([6, 1.5, 1.2], vertical_alignment="center")
    active = [k for k in FILTER_KEYS if st.session_state.get(k)]

    # The Data menu runs first because the organization grouping changes the filter options.
    with data_col.popover("Data", width="stretch"):
        st.markdown(f"Loaded **{source}**, {len(df):,} outcome statements.")
        grouping = st.radio(
            "Group organizations by", list(ORG_GROUPING_OPTIONS), key="org_grouping",
            help="The logic model's own name is more specific (for example separate Penn departments). "
                 "The file name groups sub-units under the organization that applied.",
        )
        replacement = st.file_uploader("Load a different CSV", type="csv", key="replace_upload")
        # Compare contents as well as names: a fresh export often keeps the old file's name.
        if replacement is not None and st.session_state.get(UPLOAD_KEY) != (replacement.name,
                                                                             replacement.getvalue()):
            remember_upload(replacement)
            st.rerun()
        st.markdown(
            "**About the measures**\n\n"
            "- **Outcome statement**: one outcome after the coder split compound statements.\n"
            "- **Organizations** counts each organization once per goal, however many outcomes it lists. "
            "Rows with no organization name are not counted as one.\n"
            "- **Overall overlap** between peers is shared goals divided by all goals either organization "
            "targets.\n"
            "- **Confidence** is the coder's own rating; *none* means it could not code the statement."
        )
    df = df.assign(**{COL_ORG_VIEW: df[ORG_GROUPING_OPTIONS[grouping]]})

    with filters_col.popover(f"Filters · {len(active)}" if active else "Filters", width="stretch"):
        domains = domain_order(df)
        keep_valid("f_domains", domains)
        chosen_domains = st.multiselect("Domains", domains, key="f_domains", placeholder="All domains",
                                        format_func=domain_short)
        pops = sorted(df[COL_POP].unique(), key=pretty_population)
        keep_valid("f_pops", pops)
        chosen_pops = st.multiselect("Who the outcome is for", pops, format_func=pretty_population,
                                     key="f_pops", placeholder="Everyone")
        # The peers page compares organizations with each other, so an
        # organization filter there would hide the peers being searched for.
        # The schools page lists every partner at a school, so it has none either.
        chosen_orgs = None
        if page_key not in ("peers", "schools"):
            orgs = sorted(df[COL_ORG_VIEW].unique(), key=str.casefold)
            keep_valid("f_orgs", orgs)
            chosen_orgs = st.multiselect("Organizations", orgs, key="f_orgs", placeholder="All organizations")
        # The review page has its own confidence control.
        chosen_conf = None
        if page_key != "review":
            levels = [c for c in CONFIDENCE_ORDER if c in set(df[COL_CONF])]
            keep_valid("f_conf", levels)
            chosen_conf = st.multiselect("Coder confidence", levels, key="f_conf", placeholder="Any confidence",
                                         format_func=str.title)
        # The school page picks one school itself, so the place filters live on the other pages.
        at_places = place_filters(df) if page_key != "schools" else None
        if active:
            st.button("Clear filters", on_click=reset_filters, type="tertiary")

    filtered = filter_outcomes(df, domains=chosen_domains, populations=chosen_pops,
                               organizations=chosen_orgs, confidences=chosen_conf)
    if at_places is not None:
        filtered = filtered[at_places.reindex(filtered.index, fill_value=False)]
    n_orgs = count_organizations(filtered[COL_ORG_VIEW])
    active = [k for k in FILTER_KEYS if st.session_state.get(k)]
    if active:
        what = " and ".join(
            f"{len(st.session_state[k])} {FILTER_NOUNS[k][len(st.session_state[k]) != 1]}" for k in active)
        text = (f"Filtered to {what}: <b>{len(filtered):,}</b> of {len(df):,} outcome statements from "
                f"<b>{n_orgs}</b> organizations")
    else:
        text = f"All <b>{len(df):,}</b> outcome statements from <b>{n_orgs}</b> organizations"
    status.markdown(f"<p class='status'>{text}</p><p class='intent'>{intent_note(df[COL_SOURCE_TYPE].unique())}</p>", unsafe_allow_html=True)
    return filtered


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    df, source = load_data()
    if df is None:
        welcome_screen()
        st.stop()

    # Pages read the filtered frame from here once the filter bar has run.
    holder: dict[str, pd.DataFrame] = {}
    pages = {
        "map": st.Page(lambda: page_system_map(holder["df"]), title="What programs aim for", url_path="system-map",
                       default=True),
        "peers": st.Page(lambda: page_find_peers(holder["df"]), title="Find peers", url_path="find-peers"),
        "schools": st.Page(lambda: page_schools(holder["df"], df), title="Partners at a school",
                           url_path="schools"),
        "review": st.Page(lambda: page_review(holder["df"]), title="Review coding", url_path="review-coding"),
    }
    current = st.navigation(list(pages.values()), position="top")
    page_key = next(k for k, p in pages.items() if p.url_path == current.url_path)
    holder["df"] = filter_bar(df, source, page_key)
    current.run()


if __name__ == "__main__":
    main()
