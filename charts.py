"""
Plotly figures for the outcomes dashboard.

Every chart carries sample outcome statements in its hover box (the
"validation tooltip"), so readers can check a category against real text.

Color rules (so the charts read as one system):

* Magnitude uses one blue ramp, light to dark (treemap, heatmap).
* Identity uses the categorical palette in a fixed order, and each population
  group always gets the same color, whatever the filters.
* Single-series bars use the first categorical blue and need no legend.
"""

from __future__ import annotations

import textwrap
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from outcomes_data import (
    COL_DOMAIN,
    COL_DOMAIN_NUM,
    COL_DOMAIN_SHORT,
    COL_ORG_VIEW,
    COL_SUBCAT,
    COL_OUTCOME,
    MEASURE_ORGS,
    POPULATION_GROUP_ORDER,
    distinct_counts_by,
    domain_population_counts,
    domain_short,
    hierarchy_counts,
    sample_outcome_texts,
)

# =============================================================================
# THEME
# =============================================================================

# Categorical palette, validated for color-vision deficiency in this order.
# Assigned by position, never cycled.
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

# One-hue sequential ramp for magnitude (light = little, dark = a lot).
SEQUENTIAL_BLUE = ["#e6f0fc", "#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]

PRIMARY = CATEGORICAL[0]
TEXT_PRIMARY = "#1b1b1a"
TEXT_SECONDARY = "#5f5e5a"
GRID = "#e8e7e3"
SURFACE = "#ffffff"

# Each population group keeps its color no matter which groups are filtered in.
POPULATION_COLORS = dict(zip(POPULATION_GROUP_ORDER, CATEGORICAL))

FONT_FAMILY = '"Source Sans 3", "Source Sans Pro", -apple-system, "Segoe UI", sans-serif'

pio.templates["outcomes"] = go.layout.Template(
    layout=dict(
        font=dict(family=FONT_FAMILY, size=13, color=TEXT_PRIMARY),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=SURFACE,
        colorway=CATEGORICAL,
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=GRID, font=dict(family=FONT_FAMILY, size=13, color=TEXT_PRIMARY)),
        xaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=TEXT_SECONDARY)),
        yaxis=dict(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=TEXT_SECONDARY)),
        legend=dict(font=dict(color=TEXT_SECONDARY), title=dict(font=dict(color=TEXT_SECONDARY))),
        margin=dict(t=16, l=8, r=8, b=8),
    )
)
pio.templates.default = "plotly_white+outcomes"

SAMPLE_HOVER_BLOCK = "<br><br><b>Sample outcomes</b><br>%{customdata[0]}"

# Plotly's modebar clutters a dashboard; keep only "download as image".
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": [
        "zoom2d", "pan2d", "select2d", "lasso2d", "zoomIn2d", "zoomOut2d", "autoScale2d", "resetScale2d",
    ],
}


# =============================================================================
# SYSTEM MAP
# =============================================================================


# Readability rules for the treemap and sunburst. Plotly shrinks each label to
# fit its block, so on a full portfolio most labels end up a few pixels tall.
# Instead, every label is drawn at one size between these two limits, and a
# block too small for the minimum shows no text (hover still names it).
HIERARCHY_TEXT_SIZE = 15
HIERARCHY_MIN_TEXT_SIZE = 12
# Characters per line when wrapping long names (treemap blocks, sunburst wedges).
TREEMAP_WRAP = 22
SUNBURST_WRAP = 16
ROOT_LABEL = "All domains"


def wrap_label(text: str, width: int) -> str:
    """Break a long name onto several lines (Plotly uses <br> for line breaks)."""
    return "<br>".join(textwrap.wrap(str(text), width=width, break_long_words=False)) or str(text)


def build_hierarchy_chart(df: pd.DataFrame, measure: str = MEASURE_ORGS, chart_type: str = "Treemap"):
    """Treemap or sunburst: domain (parent) -> subcategory (child).

    Block size follows `measure` (organizations or outcome statements).
    Color always shows how many organizations target the subcategory, so dark
    blocks are the most saturated goals and pale ones the thinnest.

    The chart opens on domains only; clicking a domain expands it into its
    subcategories, and clicking its name (treemap) or the center (sunburst)
    goes back. Showing one level at a time gives every label room to be
    read. Labels use the short domain name and wrapped subcategory names;
    hover shows the full names.
    """
    counts = hierarchy_counts(df)
    size_col = "organizations" if measure == MEASURE_ORGS else "outcomes"
    is_treemap = chart_type == "Treemap"
    # An "All domains" root is what you click to go back up from a domain.
    has_root = counts[COL_DOMAIN].nunique() > 1
    count_index, count_noun = (2, "organizations") if measure == MEASURE_ORGS else (1, "outcome statements")
    wrap = TREEMAP_WRAP if is_treemap else SUNBURST_WRAP

    # Display labels: short domain names and subcategory names wrapped onto
    # short lines, so they fit narrow blocks without shrinking.
    counts["domain_label"] = counts[COL_DOMAIN].map(lambda s: wrap_label(domain_short(s), wrap))
    counts["subcat_label"] = counts[COL_SUBCAT].map(lambda s: wrap_label(s, wrap))

    chart_fn = px.treemap if is_treemap else px.sunburst
    fig = chart_fn(
        counts,
        path=([px.Constant(ROOT_LABEL)] if has_root else []) + ["domain_label", "subcat_label"],
        values=size_col,
        color="organizations",
        color_continuous_scale=SEQUENTIAL_BLUE,
        custom_data=["samples", "outcomes", "organizations", COL_SUBCAT],
    )

    # Plotly fills custom_data and color for parent nodes by aggregating
    # children, which gives "(?)" for text and double-counts organizations
    # working in several subcategories. Recompute domains from the rows so
    # labels, hover and shading are exact.
    # Nodes are identified by parent (not by splitting ids on "/"), because
    # some labels, e.g. "School/Program Connectedness", contain "/".
    trace = fig.data[0]
    root_id = next(i for i, p in zip(trace.ids, trace.parents) if not p) if has_root else ""
    full_domain = dict(zip(counts["domain_label"], counts[COL_DOMAIN]))
    per_domain = distinct_counts_by(df, COL_DOMAIN)
    domain_samples = df.groupby(COL_DOMAIN)[COL_OUTCOME].agg(sample_outcome_texts)
    fixed, colors = [], []
    for label, parent, custom, color in zip(trace.labels, trace.parents, trace.customdata, trace.marker.colors):
        if has_root and not parent:
            fixed.append([sample_outcome_texts(df[COL_OUTCOME]), len(df), df[COL_ORG_VIEW].nunique(), ROOT_LABEL])
            # A colorscale overrides root_color, so the root takes the palest
            # blue and reads as background rather than as a count.
            colors.append(0)
        elif parent == root_id:
            domain = full_domain[label]
            row = per_domain.loc[domain]
            fixed.append([domain_samples.get(domain, ""), int(row["outcomes"]), int(row["organizations"]), domain])
            colors.append(int(row["organizations"]))
        else:
            fixed.append(list(custom))
            colors.append(color)
    trace.customdata = fixed
    trace.marker.colors = colors

    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[3]}</b><br>%{customdata[2]} organizations · %{customdata[1]} outcome statements"
            + SAMPLE_HOVER_BLOCK
            + "<extra></extra>"
        ),
        marker=dict(line=dict(color=SURFACE, width=2)),
        textfont=dict(size=HIERARCHY_TEXT_SIZE),
        # Show the exact count rather than Plotly's summed value, which
        # double-counts organizations at the domain level.
        texttemplate=f"<b>%{{label}}</b><br>%{{customdata[{count_index}]}} {count_noun}",
        # One level below the current center at a time: domains first,
        # a domain's subcategories after a click.
        maxdepth=2,
    )
    if is_treemap:
        fig.update_traces(
            textposition="top left",
            tiling=dict(pad=4),
            # Header strips fit a two-line domain name once it's expanded.
            marker_pad=dict(t=48, l=4, r=4, b=4),
            pathbar=dict(visible=False),  # the header above does the same job
        )
    else:
        # "auto" turns each label whichever way lets it be largest.
        fig.update_traces(insidetextorientation="auto")
    fig.update_layout(
        height=720,
        margin=dict(t=8, l=0, r=0, b=0),
        uniformtext=dict(minsize=HIERARCHY_MIN_TEXT_SIZE, mode="hide"),
        coloraxis_colorbar=dict(title=dict(text="Organizations", side="top"), thickness=12, len=0.6),
    )
    return fig


# Wrap width for program and goal names beside the Sankey's bars.
SANKEY_WRAP = 30
SANKEY_TARGET_COLOR = "#b4b2ab"   # neutral, so color stays on the programs being compared


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {alpha})"


def _stack_positions(sizes: list[float], gap: float = 0.03) -> list[float]:
    """Vertical centers (0 = top, 1 = bottom) that stack nodes in the given order.

    Plotly's automatic layout reorders nodes to reduce crossings, which
    scrambles the codebook order; fixed positions keep it.
    """
    total = sum(sizes) or 1
    usable = 1 - gap * max(len(sizes) - 1, 0)
    centers, top = [], 0.0
    for size in sizes:
        height = size / total * usable
        centers.append(min(max(top + height / 2, 0.001), 0.999))
        top += height + gap
    return centers


def build_program_sankey(flows: pd.DataFrame, programs: list[str], zoomed: bool = False):
    """Sankey from programs (left) to domains, or to one domain's subcategories (right).

    Band width is the number of outcome statements. Each program keeps one
    color from the categorical palette, and its bands carry that color, so
    you can follow a program across the chart. Hover a band for samples.
    """
    targets = list(dict.fromkeys(flows["target"]))
    sources = [p for p in programs if p in set(flows["source"])]
    index = {name: i for i, name in enumerate(sources + targets)}
    color_of = {p: CATEGORICAL[i % len(CATEGORICAL)] for i, p in enumerate(programs)}

    target_names = targets if zoomed else [domain_short(t) for t in targets]
    source_sizes = [flows.loc[flows["source"] == p, "outcomes"].sum() for p in sources]
    target_sizes = [flows.loc[flows["target"] == t, "outcomes"].sum() for t in targets]
    fig = go.Figure(
        go.Sankey(
            arrangement="fixed",
            node=dict(
                x=[0.001] * len(sources) + [0.999] * len(targets),
                y=_stack_positions(source_sizes) + _stack_positions(target_sizes),
                label=[wrap_label(n, SANKEY_WRAP) for n in sources + target_names],
                customdata=sources + target_names,
                color=[color_of[p] for p in sources] + [SANKEY_TARGET_COLOR] * len(targets),
                pad=14,
                thickness=18,
                line=dict(width=0),
                hovertemplate="<b>%{customdata}</b><br>%{value} outcome statements<extra></extra>",
            ),
            link=dict(
                source=[index[s] for s in flows["source"]],
                target=[index[t] for t in flows["target"]],
                value=flows["outcomes"].tolist(),
                color=[_rgba(color_of[s], 0.4) for s in flows["source"]],
                customdata=flows["samples"].tolist(),
                hovertemplate=(
                    "<b>%{source.customdata}</b> to <b>%{target.customdata}</b>"
                    "<br>%{value} outcome statements"
                    "<br><br><b>Sample outcomes</b><br>%{customdata}<extra></extra>"
                ),
            ),
            textfont=dict(family=FONT_FAMILY, size=14, color=TEXT_PRIMARY),
        )
    )
    # Room for a two-line label beside every bar, even the thinnest.
    fig.update_layout(height=max(480, 64 * max(len(targets), len(sources))), margin=dict(t=8, l=8, r=8, b=8))
    return fig


def build_domain_population_bar(df: pd.DataFrame, as_share: bool = False):
    """Horizontal stacked bars: outcome statements per domain, split by population group."""
    counts = domain_population_counts(df)
    value = "share" if as_share else "count"
    order = counts.sort_values(COL_DOMAIN_NUM)[COL_DOMAIN_SHORT].drop_duplicates().tolist()
    fig = px.bar(
        counts,
        y=COL_DOMAIN_SHORT,
        x=value,
        color="population_group",
        orientation="h",
        custom_data=["samples", COL_DOMAIN, "population_group", "count", "share"],
        category_orders={COL_DOMAIN_SHORT: order, "population_group": POPULATION_GROUP_ORDER},
        color_discrete_map=POPULATION_COLORS,
        labels={COL_DOMAIN_SHORT: "", "count": "Outcome statements", "share": "Share of the domain's outcomes",
                "population_group": "Who the outcome is for"},
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{customdata[1]}</b><br>%{customdata[2]}: %{customdata[3]} outcomes "
            "(%{customdata[4]:.0%} of this domain)"
            + SAMPLE_HOVER_BLOCK
            + "<extra></extra>"
        ),
        marker_line=dict(color=SURFACE, width=1.5),
    )
    fig.update_layout(
        barmode="stack",
        height=max(380, 36 * len(order) + 120),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, title=None),
        xaxis=dict(tickformat=".0%" if as_share else ",d", title=None),
        yaxis=dict(automargin=True),
        margin=dict(t=48, l=0, r=8, b=8),
        bargap=0.28,
    )
    return fig


def build_coverage_bar(coverage: pd.DataFrame, x_max: Optional[float] = None):
    """Horizontal bars of organizations per subcategory (one series, no legend).

    Pass the same `x_max` to charts shown side by side so bar lengths compare.
    """
    data = coverage.iloc[::-1]  # plotly draws the first row at the bottom
    fig = px.bar(
        data,
        x="organizations",
        y=COL_SUBCAT,
        orientation="h",
        custom_data=["samples", "outcomes", "programs", COL_DOMAIN],
        color_discrete_sequence=[PRIMARY],
        labels={"organizations": "Organizations", COL_SUBCAT: ""},
        text="organizations",
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{y}</b><br>%{customdata[3]}<br>%{x} organizations · %{customdata[2]} programs · "
            "%{customdata[1]} outcome statements"
            + SAMPLE_HOVER_BLOCK
            + "<extra></extra>"
        ),
        textposition="outside",
        cliponaxis=False,
        textfont=dict(color=TEXT_SECONDARY),
    )
    fig.update_layout(
        height=max(240, 30 * len(data) + 40),
        xaxis=dict(visible=False, range=[0, (x_max or data["organizations"].max() or 1) * 1.08]),
        yaxis=dict(automargin=True),
        margin=dict(t=4, l=0, r=24, b=4),
        bargap=0.3,
    )
    return fig


# =============================================================================
# PEERS
# =============================================================================


def build_peer_heatmap(counts: pd.DataFrame, samples: pd.DataFrame):
    """Heatmap of outcome counts: organizations (rows) x the selected organization's subcategories."""
    fig = px.imshow(
        counts,
        color_continuous_scale=SEQUENTIAL_BLUE,
        aspect="auto",
        text_auto=True,
        labels=dict(x="", y="", color="Outcomes"),
    )
    fig.update_traces(
        customdata=samples.to_numpy()[..., None],
        hovertemplate="<b>%{y}</b><br>%{x}<br>%{z} outcomes" + SAMPLE_HOVER_BLOCK + "<extra></extra>",
        xgap=2,
        ygap=2,
    )
    fig.update_layout(
        height=max(320, 40 * len(counts) + 200),
        xaxis=dict(side="top", tickangle=-30, showgrid=False),
        yaxis=dict(showgrid=False),
        margin=dict(t=8, l=0, r=0, b=0),
        coloraxis_colorbar=dict(thickness=12, len=0.6),
    )
    return fig


def build_subcategory_org_bar(orgs: pd.DataFrame):
    """Horizontal bars: which organizations target a subcategory, and with how many outcomes."""
    fig = px.bar(
        orgs,
        x="count",
        y="organization",
        orientation="h",
        custom_data=["samples", "programs"],
        labels={"count": "Outcome statements", "organization": ""},
        color_discrete_sequence=[PRIMARY],
        text="count",
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{y}</b><br>%{x} outcomes in this subcategory<br>Programs: %{customdata[1]}"
            + SAMPLE_HOVER_BLOCK
            + "<extra></extra>"
        ),
        textposition="outside",
        cliponaxis=False,
        textfont=dict(color=TEXT_SECONDARY),
    )
    fig.update_layout(
        yaxis=dict(autorange="reversed", automargin=True),
        xaxis=dict(visible=False),
        height=max(220, 30 * len(orgs) + 40),
        margin=dict(t=4, l=0, r=24, b=4),
        bargap=0.3,
    )
    return fig


# =============================================================================
# REVIEW
# =============================================================================


def build_confidence_bar(counts: pd.Series):
    """One stacked bar showing how the coder's confidence is distributed (a compact overview)."""
    colors = {"high": "#1c5cab", "medium": "#5598e7", "low": "#eb6834", "none": "#8a8984"}
    fig = go.Figure()
    total = int(counts.sum()) or 1
    for level, n in counts.items():
        fig.add_bar(
            x=[n], y=[""], orientation="h", name=f"{level.title()} ({n:,})",
            marker=dict(color=colors.get(level, "#8a8984"), line=dict(color=SURFACE, width=2)),
            hovertemplate=f"<b>{level.title()}</b>: {n:,} outcomes ({n / total:.0%})<extra></extra>",
        )
    fig.update_layout(
        barmode="stack",
        height=110,
        showlegend=True,
        legend=dict(orientation="h", y=-0.35, x=0, traceorder="normal"),
        xaxis=dict(visible=False, range=[0, total]),
        yaxis=dict(visible=False),
        margin=dict(t=0, l=0, r=0, b=0),
    )
    return fig
