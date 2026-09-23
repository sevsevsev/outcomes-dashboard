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

1. System map        - where outcomes and organizations concentrate, coverage gaps
2. Find peers        - peer matrix for an organization, organizations by goal
3. Review coding     - paginated explorer for checking the coder's categorizations

Run it with:

    streamlit run app.py

Code layout:

* outcomes_data.py - loading, cleaning, filtering, aggregation (no Streamlit)
* charts.py        - Plotly figures and the shared chart theme
* app.py           - this file: page layout, widgets, navigation
"""

from __future__ import annotations

import io
import re
from typing import Callable, Optional, Sequence

import pandas as pd
import streamlit as st

import charts
from outcomes_data import (
    COL_ATOMIC,
    COL_CONF,
    COL_DOMAIN,
    COL_DOMAIN_NUM,
    COL_FULL,
    COL_GRANTEE,
    COL_NOTES,
    COL_OUTCOME,
    COL_ORG,
    COL_ORG_VIEW,
    COL_POP,
    COL_PROGRAM,
    COL_QA,
    COL_SOURCE_FILE,
    COL_SUBCAT,
    COL_TEXT,
    CONFIDENCE_ORDER,
    DATA_ENV_VAR,
    DATA_FILENAME,
    MEASURE_ORGS,
    MEASURES,
    ORG_GROUPING_OPTIONS,
    POPULATION_LABELS,
    UNASSIGNED_SUBCAT,
    MissingColumnsError,
    compute_peer_overlap,
    domain_order,
    filter_outcomes,
    load_codebook,
    organizations_for_subcategory,
    peer_heatmap_data,
    population_group,
    read_outcomes_csv,
    resolve_data_path,
    sorted_subcategories,
    subcategory_coverage,
    to_export_frame,
)

APP_TITLE = "Outcomes Explorer"

# Session-state keys for the sidebar filters, so "Reset filters" can clear them.
FILTER_KEYS = ["f_domains", "f_pops", "f_orgs", "f_conf"]
UPLOAD_KEY = "uploaded_csv"          # (file name, bytes) of a CSV uploaded this session
READ_ERRORS = (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError)


# =============================================================================
# CACHED LOADERS
# =============================================================================


@st.cache_data(show_spinner="Loading coded outcomes...")
def load_from_path(path: str) -> pd.DataFrame:
    return read_outcomes_csv(path)


@st.cache_data(show_spinner="Loading your file...")
def load_from_bytes(data: bytes) -> pd.DataFrame:
    return read_outcomes_csv(io.BytesIO(data))


@st.cache_data
def cached_codebook() -> pd.DataFrame:
    return load_codebook()


# =============================================================================
# STYLE
# =============================================================================

# Small CSS touches on top of the theme in .streamlit/config.toml: tighter
# page top, bordered metric cards, and muted captions.
CSS = """
<style>
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px; }
h1 { font-weight: 700; letter-spacing: -0.01em; }
h2, h3 { font-weight: 650; letter-spacing: -0.005em; }
[data-testid="stMetric"] {
    background: var(--secondary-background-color, #f6f6f3);
    border: 1px solid rgba(49, 51, 63, 0.08);
    border-radius: 10px;
    padding: 0.8rem 1rem;
}
[data-testid="stMetricLabel"] p { font-size: 0.85rem; color: #5f5e5a; }
[data-testid="stMetricValue"] { font-size: 1.7rem; font-weight: 650; }
.page-lede { color: #5f5e5a; font-size: 1.02rem; margin: -0.4rem 0 1.2rem 0; max-width: 60rem; }
.section-note { color: #5f5e5a; font-size: 0.92rem; margin: -0.5rem 0 0.6rem 0; }
.filter-chip {
    display: inline-block; background: #e6f0fc; color: #104281; border-radius: 999px;
    padding: 0.1rem 0.6rem; margin: 0 0.3rem 0.3rem 0; font-size: 0.8rem;
}
</style>
"""


def page_header(title: str, lede: str) -> None:
    st.title(title)
    st.markdown(f"<p class='page-lede'>{lede}</p>", unsafe_allow_html=True)


def section(title: str, note: Optional[str] = None) -> None:
    st.subheader(title)
    if note:
        st.markdown(f"<p class='section-note'>{note}</p>", unsafe_allow_html=True)


def kpi_row(items: Sequence[tuple[str, str, Optional[str]]]) -> None:
    """A row of headline numbers: (label, value, help text)."""
    for col, (label, value, help_text) in zip(st.columns(len(items)), items):
        col.metric(label, value, help=help_text)


def plot(fig, key: str, **kwargs):
    """Render a Plotly figure with the dashboard's shared settings."""
    # Set on the figure itself: Streamlit's renderer can override template backgrounds.
    fig.update_layout(plot_bgcolor=charts.SURFACE, paper_bgcolor="rgba(0,0,0,0)")
    return st.plotly_chart(fig, key=key, config=charts.PLOTLY_CONFIG, theme=None, **kwargs)


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
    COL_SUBCAT: "Subcategory",
    COL_POP: "Target population",
    COL_CONF: "Confidence",
    COL_QA: "QA status",
    COL_NOTES: "Coder notes",
    COL_SOURCE_FILE: "Source file",
}
DISPLAY_COLUMNS = [COL_ORG_VIEW, COL_PROGRAM, COL_OUTCOME, COL_FULL, COL_SUBCAT, COL_POP, COL_CONF]


def pretty_population(code: str) -> str:
    return POPULATION_LABELS.get(code, code)


def outcome_table(df: pd.DataFrame, columns: Sequence[str] = DISPLAY_COLUMNS, height="auto") -> None:
    """Outcome rows as a scrollable table with readable headers."""
    cols = [c for c in columns if c in df.columns]
    config = {c: st.column_config.TextColumn(DISPLAY_LABELS.get(c, c)) for c in cols}
    config[COL_OUTCOME] = st.column_config.TextColumn(
        DISPLAY_LABELS[COL_OUTCOME], width="large", help="The outcome as the coder categorized it.")
    config[COL_FULL] = st.column_config.TextColumn(
        DISPLAY_LABELS[COL_FULL], width="medium",
        help="Filled in only when the coder split a longer statement into separate outcomes.")
    shown = df[cols].copy()
    if COL_POP in shown:
        shown[COL_POP] = shown[COL_POP].map(pretty_population)
    st.dataframe(shown, column_config=config, hide_index=True, height=height)


def download_button(df: pd.DataFrame, label: str, filename: str, key: str) -> None:
    """CSV download of a filtered view (also the hook for other tools, e.g. a map)."""
    csv = to_export_frame(df).to_csv(index=False).encode("utf-8")
    st.download_button(label, csv, file_name=filename, mime="text/csv", key=key, icon=":material/download:")


def outcome_list(df: pd.DataFrame, title: str, key: str, max_rows: int = 25, expanded: bool = True) -> None:
    """The outcome statements behind a chart element, with a download.

    This is the "click to reveal" half of the validation tooltips: hover shows
    a few samples, this shows the full set.
    """
    with st.expander(f"{title} · {len(df):,} outcomes", expanded=expanded, icon=":material/format_list_bulleted:"):
        if df.empty:
            st.info("No outcomes match this selection.")
            return
        shown = df if len(df) <= max_rows else df.sample(max_rows, random_state=0)
        if len(df) > max_rows:
            st.caption(f"A random sample of {max_rows} of {len(df):,}. Download for the full list.")
        outcome_table(shown)
        download_button(df, f"Download all {len(df):,}", f"outcomes_{key}.csv", key=f"dl_{key}")


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


# =============================================================================
# PAGE 1: SYSTEM MAP
# =============================================================================


def page_system_map(df: pd.DataFrame) -> None:
    page_header(
        "System map",
        "Where the partner portfolio concentrates its effort, and where coverage is thin. "
        "Hover any block or bar to read real outcome statements behind it.",
    )
    if df.empty:
        st.warning("No outcomes match the current filters. Loosen them in the sidebar.")
        return

    coded = df[df[COL_SUBCAT] != UNASSIGNED_SUBCAT]
    kpi_row([
        ("Organizations", f"{df[COL_ORG_VIEW].nunique():,}", None),
        ("Programs", f"{df[[COL_ORG_VIEW, COL_PROGRAM]].drop_duplicates().shape[0]:,}", None),
        ("Outcome statements", f"{len(df):,}", "One row per atomic outcome after the coder split compound statements."),
        ("Subcategories targeted", f"{coded[COL_SUBCAT].nunique():,}", None),
    ])

    # --- Treemap / sunburst ---------------------------------------------------
    section(
        "Where the portfolio invests",
        "Blocks are subcategories grouped by domain. Darker blocks have more organizations working on them.",
    )
    c1, c2, _ = st.columns([2, 2, 3])
    measure = c1.segmented_control(
        "Size blocks by", MEASURES, default=MEASURE_ORGS, key="v1_measure",
        help="Organizations shows how many partners pursue a goal. Outcome statements weights "
             "organizations that list many outcomes more heavily.",
    ) or MEASURE_ORGS
    chart_type = c2.segmented_control("Chart", ["Treemap", "Sunburst"], default="Treemap", key="v1_chart") or "Treemap"
    plot(charts.build_hierarchy_chart(df, measure, chart_type), key="v1_hierarchy")
    st.caption("Click a domain to zoom in, then click its header to zoom back out.")

    with st.expander("Read the outcomes behind a block", icon=":material/search:"):
        d1, d2 = st.columns(2)
        domain_choice = d1.selectbox("Domain", domain_order(df), key="v1_domain")
        subcats = sorted_subcategories(df.loc[df[COL_DOMAIN] == domain_choice, COL_SUBCAT])
        subcat_choice = d2.selectbox(
            "Subcategory", ["All subcategories"] + subcats, key=f"v1_subcat_{slug(domain_choice)}"
        )
        chosen = filter_outcomes(
            df, domains=[domain_choice],
            subcategories=None if subcat_choice == "All subcategories" else [subcat_choice],
        )
        outcome_list(chosen, domain_choice if subcat_choice == "All subcategories" else subcat_choice,
                     key="v1_block", expanded=True)

    # --- Coverage -------------------------------------------------------------
    section(
        "Most and least covered goals",
        "Subcategories ranked by how many organizations target them. Goals at the bottom are "
        "candidates for new partnerships or investment.",
    )
    coverage = subcategory_coverage(df, cached_codebook())
    gaps = coverage[coverage["organizations"] == 0]
    covered = coverage[coverage["organizations"] > 0]
    top_n = 12
    x_max = covered["organizations"].max() if not covered.empty else 1  # shared scale so bars compare
    left, right = st.columns(2)
    with left:
        st.markdown("**Most organizations**")
        plot(charts.build_coverage_bar(covered.tail(top_n).iloc[::-1], x_max), key="v1_cov_top")
    with right:
        st.markdown("**Fewest organizations** (at least one)")
        plot(charts.build_coverage_bar(covered.head(top_n), x_max), key="v1_cov_bottom")
    if not gaps.empty:
        st.markdown(
            f"**No organization targets these {len(gaps)} codebook subcategories** under the current filters:"
        )
        st.markdown(" ".join(f"<span class='filter-chip'>{g}</span>" for g in gaps[COL_SUBCAT]),
                    unsafe_allow_html=True)
    with st.expander("All subcategories with counts", icon=":material/table_rows:"):
        st.dataframe(
            coverage[[COL_SUBCAT, COL_DOMAIN, "organizations", "programs", "outcomes"]],
            hide_index=True,
            column_config={
                COL_SUBCAT: st.column_config.TextColumn("Subcategory", width="large"),
                COL_DOMAIN: st.column_config.TextColumn("Domain"),
                "organizations": st.column_config.ProgressColumn(
                    "Organizations", format="%d", min_value=0, max_value=int(coverage["organizations"].max() or 1)),
                "programs": st.column_config.NumberColumn("Programs"),
                "outcomes": st.column_config.NumberColumn("Outcome statements"),
            },
        )
        download_button(coverage.drop(columns=["samples"]), "Download coverage table", "subcategory_coverage.csv",
                        key="v1_dl_cov")

    # --- Population ------------------------------------------------------------
    section(
        "Who the outcomes are for",
        "Outcome statements per domain, split by target population. Click a segment to list its outcomes.",
    )
    view_as = st.segmented_control("Show", ["Count", "Share of domain"], default="Count", key="v1_pop_view") or "Count"
    event = plot(
        charts.build_domain_population_bar(df, as_share=view_as == "Share of domain"),
        key="v1_pop_bar", on_select="rerun", selection_mode="points",
    )
    points = selected_points(event)
    if points:
        custom = point_customdata(points[0])
        if len(custom) >= 3:
            domain, group = custom[1], custom[2]
            rows = df[(df[COL_DOMAIN] == domain) & (df[COL_POP].map(population_group) == group)]
            outcome_list(rows, f"{domain} · {group}", key="v1_pop_selection")

    st.divider()
    download_button(df, "Download the outcomes on this page", "system_map_outcomes.csv", key="v1_dl_all")


# =============================================================================
# PAGE 2: FIND PEERS
# =============================================================================


def page_find_peers(df: pd.DataFrame) -> None:
    page_header(
        "Find peers",
        "Find organizations pursuing the same developmental goals: start from an organization to see "
        "its closest peers, or from a goal to see everyone working on it.",
    )
    if df.empty:
        st.warning("No outcomes match the current filters. Loosen them in the sidebar.")
        return

    tab_org, tab_goal = st.tabs([":material/groups: Peers for an organization", ":material/flag: Who works on a goal"])
    with tab_org:
        peers_for_organization(df)
    with tab_goal:
        organizations_for_goal(df)


def peers_for_organization(df: pd.DataFrame) -> None:
    orgs = sorted(df[COL_ORG_VIEW].unique(), key=str.casefold)
    org = st.selectbox("Organization", orgs, key="v2_org", placeholder="Type to search organizations")
    if org is None:
        return
    org_rows = df[df[COL_ORG_VIEW] == org]
    org_subcats = sorted_subcategories(org_rows.loc[org_rows[COL_SUBCAT] != UNASSIGNED_SUBCAT, COL_SUBCAT])
    peers = compute_peer_overlap(df, org)

    kpi_row([
        ("Programs", f"{org_rows[COL_PROGRAM].nunique():,}", ", ".join(sorted(org_rows[COL_PROGRAM].unique()))),
        ("Outcome statements", f"{len(org_rows):,}", None),
        ("Subcategories targeted", f"{len(org_subcats):,}", None),
        ("Peers sharing a goal", f"{len(peers):,}", None),
    ])

    if peers.empty:
        st.info("No other organization shares a subcategory with this one under the current filters.")
        return

    section(
        "Peer matrix",
        "Ranked by shared subcategories. Select a row to compare the two organizations' outcomes.",
    )
    table = peers.assign(coverage=(peers["coverage"] * 100).round().astype(int))
    event = st.dataframe(
        table,
        hide_index=True,
        key=f"v2_peer_table_{slug(org)}",
        on_select="rerun",
        selection_mode="single-row",
        height=min(420, 36 * len(peers) + 40),
        column_order=["organization", "shared_subcategories", "coverage", "jaccard",
                      "peer_outcomes_in_shared", "shared_list", "programs"],
        column_config={
            "organization": st.column_config.TextColumn("Peer organization", pinned=True),
            "shared_subcategories": st.column_config.NumberColumn(
                "Shared goals", help="Subcategories both organizations target."),
            "coverage": st.column_config.ProgressColumn(
                "Covers", help=f"Share of {org}'s subcategories this peer also targets.",
                min_value=0, max_value=100, format="%d%%"),
            "jaccard": st.column_config.ProgressColumn(
                "Similarity", help="Shared goals divided by all goals either organization targets. "
                                   "High means the two portfolios look alike overall.",
                min_value=0.0, max_value=1.0, format="%.2f"),
            "peer_outcomes_in_shared": st.column_config.NumberColumn(
                "Peer outcomes in shared goals", help="How deep the peer's work in the shared goals goes."),
            "shared_list": st.column_config.TextColumn("Shared subcategories", width="large"),
            "programs": st.column_config.TextColumn("Peer programs"),
        },
    )
    download_button(peers, "Download peer matrix", f"peers_{slug(org)}.csv", key="v2_dl_peers")

    rows = event.selection.rows if event and hasattr(event, "selection") else []
    peer = peers.iloc[rows[0]]["organization"] if rows else peers.iloc[0]["organization"]
    shared = peers.loc[peers["organization"] == peer, "shared_list"].iloc[0].split("; ")

    section(f"{org} and {peer}", f"Their outcomes in the {len(shared)} goals they share."
            + ("" if rows else " Showing the top peer; select another row above to switch."))
    left, right = st.columns(2)
    with left:
        outcome_list(filter_outcomes(df, organizations=[org], subcategories=shared), org, key="v2_left")
    with right:
        outcome_list(filter_outcomes(df, organizations=[peer], subcategories=shared), peer, key="v2_right")

    section("Overlap heatmap", "How many outcomes each peer has in each of this organization's goals. "
            "Hover a cell to read them.")
    max_peers = min(30, len(peers))
    top_n = st.slider("Peers to show", 1, max_peers, min(10, max_peers), key=f"v2_topn_{slug(org)}") \
        if max_peers > 1 else 1
    counts, samples = peer_heatmap_data(df, org, peers["organization"].head(top_n).tolist())
    plot(charts.build_peer_heatmap(counts, samples), key="v2_heatmap")


def organizations_for_goal(df: pd.DataFrame) -> None:
    all_subcats = sorted_subcategories(df.loc[df[COL_SUBCAT] != UNASSIGNED_SUBCAT, COL_SUBCAT])
    if not all_subcats:
        st.info("No coded subcategories under the current filters.")
        return
    subcat = st.selectbox("Goal (subcategory)", all_subcats, key="v2_subcat", placeholder="Type to search goals")
    if subcat is None:
        return
    orgs_for = organizations_for_subcategory(df, subcat)
    goal_rows = df[df[COL_SUBCAT] == subcat]
    kpi_row([
        ("Organizations", f"{len(orgs_for):,}", None),
        ("Programs", f"{goal_rows[[COL_ORG_VIEW, COL_PROGRAM]].drop_duplicates().shape[0]:,}", None),
        ("Outcome statements", f"{len(goal_rows):,}", None),
    ])
    section("Organizations working on this goal", "Click a bar to list that organization's outcomes.")
    event = plot(charts.build_subcategory_org_bar(orgs_for), key="v2_goal_bar",
                 on_select="rerun", selection_mode="points")
    points = selected_points(event)
    chosen_org = points[0].get("y") if points else None
    if chosen_org:
        outcome_list(filter_outcomes(df, organizations=[chosen_org], subcategories=[subcat]),
                     f"{chosen_org} · {subcat}", key="v2_goal_selection")
    else:
        outcome_list(goal_rows, subcat, key="v2_goal_all", expanded=False)


# =============================================================================
# PAGE 3: REVIEW CODING
# =============================================================================


def page_review(df: pd.DataFrame) -> None:
    page_header(
        "Review coding",
        "Check individual categorizations, starting with the ones the coder was least sure about.",
    )
    if df.empty:
        st.warning("No outcomes match the current filters. Loosen them in the sidebar.")
        return

    conf_counts = df[COL_CONF].value_counts().reindex(CONFIDENCE_ORDER).dropna().astype(int)
    plot(charts.build_confidence_bar(conf_counts), key="v3_conf_bar")

    present = list(conf_counts.index) + sorted(set(df[COL_CONF]) - set(CONFIDENCE_ORDER))
    f1, f2 = st.columns([3, 2])
    confidences = f1.pills(
        "Confidence", present, selection_mode="multi",
        default=[c for c in ("low", "none") if c in present] or present, key="v3_conf",
        format_func=lambda c: f"{c.title()} ({int(conf_counts.get(c, 0)):,})",
    )
    qa_statuses = []
    if COL_QA in df.columns:
        qa_statuses = f2.pills("QA status", sorted(df[COL_QA].dropna().unique()), selection_mode="multi", key="v3_qa")
    query = st.text_input("Search outcome text", key="v3_query", placeholder="e.g. confidence, reading, mentor",
                          icon=":material/search:")

    filtered = filter_outcomes(df, confidences=confidences, qa_statuses=qa_statuses, text_query=query) \
        .sort_values([COL_DOMAIN_NUM, COL_SUBCAT, COL_ORG_VIEW])

    # --- Pagination -----------------------------------------------------------
    page_size = 50
    n_pages = max(1, -(-len(filtered) // page_size))  # ceiling division
    # Page number lives in session state so it can reset when filters shrink the result.
    if st.session_state.get("v3_page", 1) > n_pages:
        st.session_state["v3_page"] = 1
    st.session_state.setdefault("v3_page", 1)
    page = st.session_state["v3_page"]
    start = (page - 1) * page_size

    st.markdown(f"**{len(filtered):,} outcomes** · showing {min(start + 1, len(filtered)):,}–"
                f"{min(start + page_size, len(filtered)):,}")
    columns = [COL_ORG_VIEW, COL_PROGRAM, COL_OUTCOME, COL_FULL, COL_SUBCAT, COL_CONF, COL_NOTES, COL_QA,
               COL_SOURCE_FILE]
    outcome_table(filtered.iloc[start:start + page_size], columns=columns, height=560)

    p1, p2, p3 = st.columns([1, 2, 4], vertical_alignment="bottom")
    p1.number_input("Page", min_value=1, max_value=n_pages, step=1, key="v3_page")
    p2.markdown(f"of {n_pages}")
    with p3:
        download_button(filtered, f"Download all {len(filtered):,} rows", "outcomes_for_review.csv", key="v3_dl")


# =============================================================================
# DATA, SIDEBAR, NAVIGATION
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
    st.title(APP_TITLE)
    st.markdown(
        "<p class='page-lede'>Explore outcomes coded from partner programs' logic models: where the "
        "portfolio concentrates, which organizations share goals, and which categorizations need a "
        "human check.</p>",
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown("#### Upload a coded outcomes export")
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


def sidebar(df: pd.DataFrame, source: str, page_key: str) -> pd.DataFrame:
    """Sidebar filters that apply to every page. Returns the filtered frame."""
    with st.sidebar:
        st.markdown(f"### {APP_TITLE}")
        st.caption(f"Data: {source} · {len(df):,} outcome statements")

        grouping = st.radio(
            "Group organizations by", list(ORG_GROUPING_OPTIONS), key="org_grouping",
            help="The logic model's own name is more specific (for example separate Penn departments). "
                 "The file name groups sub-units under the organization that applied.",
        )
        df = df.assign(**{COL_ORG_VIEW: df[ORG_GROUPING_OPTIONS[grouping]]})

        st.markdown("#### Filters")
        domains = domain_order(df)
        keep_valid("f_domains", domains)
        chosen_domains = st.multiselect("Domains", domains, key="f_domains", placeholder="All domains")

        pops = sorted(df[COL_POP].unique(), key=pretty_population)
        keep_valid("f_pops", pops)
        chosen_pops = st.multiselect("Target populations", pops, format_func=pretty_population,
                                     key="f_pops", placeholder="All populations")

        # The peers page compares organizations with each other, so an
        # organization filter there would hide the peers being searched for.
        chosen_orgs = None
        if page_key != "peers":
            orgs = sorted(df[COL_ORG_VIEW].unique(), key=str.casefold)
            keep_valid("f_orgs", orgs)
            chosen_orgs = st.multiselect("Organizations", orgs, key="f_orgs", placeholder="All organizations")

        # The review page has its own confidence control.
        chosen_conf = None
        if page_key != "review":
            levels = [c for c in CONFIDENCE_ORDER if c in set(df[COL_CONF])]
            keep_valid("f_conf", levels)
            chosen_conf = st.multiselect(
                "Coder confidence", levels, key="f_conf", placeholder="All confidence levels",
                format_func=str.title,
                help="Choose High and Medium to leave out categorizations that still need review.",
            )

        filtered = filter_outcomes(df, domains=chosen_domains, populations=chosen_pops,
                                   organizations=chosen_orgs, confidences=chosen_conf)
        active = sum(bool(st.session_state.get(k)) for k in FILTER_KEYS)
        if active:
            st.markdown(f"Showing **{len(filtered):,}** of {len(df):,} outcomes")
            st.button("Reset filters", on_click=reset_filters, icon=":material/filter_alt_off:")

        with st.expander("Data file", icon=":material/upload_file:"):
            replacement = st.file_uploader("Load a different CSV", type="csv", key="replace_upload")
            if replacement is not None and st.session_state.get(UPLOAD_KEY, ("",))[0] != replacement.name:
                remember_upload(replacement)
                st.rerun()

        with st.expander("About the measures", icon=":material/help:"):
            st.markdown(
                "- **Outcome statement**: one outcome after the coder split compound statements.\n"
                "- **Organizations** counts each organization once per goal, however many outcomes it lists.\n"
                "- **Similarity** in the peer matrix is shared goals divided by all goals either "
                "organization targets.\n"
                "- **Confidence** is the coder's own rating; *none* means it could not code the statement."
            )
    return filtered


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon=":material/hub:", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    df, source = load_data()
    if df is None:
        welcome_screen()
        st.stop()

    # Pages read the filtered frame from here once the sidebar has run.
    holder: dict[str, pd.DataFrame] = {}
    pages = {
        "map": st.Page(lambda: page_system_map(holder["df"]), title="System map",
                       icon=":material/dashboard:", url_path="system-map", default=True),
        "peers": st.Page(lambda: page_find_peers(holder["df"]), title="Find peers",
                         icon=":material/diversity_3:", url_path="find-peers"),
        "review": st.Page(lambda: page_review(holder["df"]), title="Review coding",
                          icon=":material/fact_check:", url_path="review-coding"),
    }
    current = st.navigation(list(pages.values()), position="top")
    page_key = next(k for k, p in pages.items() if p.url_path == current.url_path)
    holder["df"] = sidebar(df, source, page_key)
    current.run()


if __name__ == "__main__":
    main()
