"""
Plotly figures for the outcomes dashboard.

Every chart carries sample outcome statements in its hover box (the
"validation tooltip"), so readers can check a category against real text.

Color rules (so the charts read as one system):

* Ranked bars and dots are one series in the accent blue. When the reader
  clicks a mark, it keeps the blue and the rest fade to grey, so the
  selection is what stands out.
* Magnitude uses one blue ramp, light to dark (treemap, heatmap).
* Categorical hues are assigned in a fixed order, never cycled.
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
    COL_ORG_VIEW,
    COL_SUBCAT,
    COL_OUTCOME,
    MEASURE_ORGS,
    distinct_counts_by,
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
FADED = "#cfd3da"          # marks that are not selected
TEXT_PRIMARY = "#16181d"
TEXT_SECONDARY = "#5b616d"
GRID = "#e6e8ec"
SURFACE = "#ffffff"

FONT_FAMILY = '"Source Sans", "Source Sans 3", "Source Sans Pro", -apple-system, "Segoe UI", sans-serif'

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
        margin=dict(t=44, l=0, r=0, b=0),
        uniformtext=dict(minsize=HIERARCHY_MIN_TEXT_SIZE, mode="hide"),
        # A slim key above the top-right corner, so the chart itself gets the full width.
        coloraxis_colorbar=dict(
            orientation="h", x=1, xanchor="right", y=1.01, yanchor="bottom", len=0.28, thickness=8,
            title=dict(text="Organizations working on it", side="top", font=dict(size=12, color=TEXT_SECONDARY)),
            tickfont=dict(size=11, color=TEXT_SECONDARY), outlinewidth=0,
        ),
    )
    return fig


# =============================================================================
# RANKED BARS AND DOTS (the linked, clickable views)
# =============================================================================

LABEL_CHARS = 44   # longer category names are shortened on the axis; hover shows them in full
ROW_HEIGHT = 30    # pixels per bar, which keeps each bar under 24px thick


def short_label(text: str, limit: int = LABEL_CHARS) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# How a clicked mark and the others look. Plotly applies this in the browser, so
# the figure itself never changes with the selection; Streamlit identifies a
# chart by its figure, and a changed figure would drop the reader's click.
SELECTED = dict(marker=dict(color=PRIMARY, opacity=1))
UNSELECTED = dict(marker=dict(color=FADED, opacity=1))
# Bars carry their value as text; it stays in text ink whether or not the bar is picked.
BAR_SELECTED = dict(marker=SELECTED["marker"], textfont=dict(color=TEXT_PRIMARY))
BAR_UNSELECTED = dict(marker=UNSELECTED["marker"], textfont=dict(color=TEXT_SECONDARY))
# Dot counts print inside the dot, so a faded dot needs darker ink than white.
DOT_UNSELECTED = dict(marker=UNSELECTED["marker"], textfont=dict(color=TEXT_SECONDARY))


def build_ranked_bars(
    data: pd.DataFrame,
    label_col: str,
    value_col: str,
    key_col: str,
    value_noun: str = "organizations",
    detail: Optional[str] = None,
):
    """Horizontal bars in the order given (first row at the top), one series, no legend.

    `key_col` goes into customdata[0] so a click tells the app which row was
    picked. Values sit at the bar tips; hover adds `detail` (a
    customdata-based template line) and sample outcomes from the `samples`
    column.
    """
    keys = data[key_col].tolist()
    custom = list(zip(keys, data["samples"], data[label_col]))
    fig = go.Figure(go.Bar(
        x=data[value_col],
        y=[short_label(v) for v in data[label_col]],
        orientation="h",
        marker=dict(color=PRIMARY),
        customdata=custom,
        text=data[value_col],
        textposition="outside",
        cliponaxis=False,
        textfont=dict(color=TEXT_SECONDARY, size=12),
        hovertemplate=(
            "<b>%{customdata[2]}</b><br>%{x} " + value_noun
            + (f"<br>{detail}" if detail else "")
            + "<br><br><b>Sample outcomes</b><br>%{customdata[1]}<extra></extra>"
        ),
        selected=BAR_SELECTED,
        unselected=BAR_UNSELECTED,
    ))
    fig.update_layout(
        height=ROW_HEIGHT * max(len(data), 2) + 24,
        xaxis=dict(visible=False, range=[0, (data[value_col].max() or 1) * 1.12]),
        yaxis=dict(autorange="reversed", automargin=True, tickfont=dict(color=TEXT_PRIMARY, size=13),
                   showgrid=False),
        margin=dict(t=4, l=0, r=8, b=4),
        bargap=0.34,
        barcornerradius=4,
        showlegend=False,
        dragmode=False,
    )
    return fig


DOT_GRID_WRAP = 14   # characters per line in the column labels
DOT_ROW = 58         # pixels per program row
DOT_HEADER = 72      # pixels for the column headers
DOMAIN_KEY = "domain::"   # customdata[0] prefix for a clicked domain header
# Header marks are invisible hit areas under the domain names; only the text shows.
HEADER_SELECTED = dict(marker=dict(opacity=0), textfont=dict(color=PRIMARY))
HEADER_UNSELECTED = dict(marker=dict(opacity=0), textfont=dict(color=TEXT_PRIMARY))


def build_program_dots(flows: pd.DataFrame, programs: list[str], zoomed: bool = False):
    """Programs (rows) by domain or subcategory (columns); dot area is the number of outcome statements.

    It answers "where do these programs overlap?" without crossing lines.
    customdata[0] is "program||target", so a click tells the app which cell
    was picked. With domains as columns, each domain name is itself a
    clickable mark (customdata[0] is DOMAIN_KEY + domain) so the app can
    drill into that domain's goals; axis labels can't be clicked.
    """
    targets = list(dict.fromkeys(flows["target"]))
    rows = [p for p in programs if p in set(flows["source"])]
    names = {t: (t if zoomed else domain_short(t)) for t in targets}
    x_labels = {t: wrap_label(names[t], DOT_GRID_WRAP) for t in targets}
    peak = flows["outcomes"].max() or 1
    sizes = [12 + 34 * (n / peak) ** 0.5 for n in flows["outcomes"]]
    keys = [f"{src}||{tgt}" for src, tgt in zip(flows["source"], flows["target"])]
    target_names = [names[t] for t in flows["target"]]
    fig = go.Figure(go.Scatter(
        x=[x_labels[t] for t in flows["target"]],
        y=[short_label(p, 40) for p in flows["source"]],
        mode="markers+text",
        # Plotly fades sized dots to 0.7 by default; keep them the same blue as the bars.
        marker=dict(size=sizes, color=PRIMARY, opacity=1, line=dict(color=SURFACE, width=2)),
        # Counts print inside dots big enough to hold them; hover gives every count.
        text=[str(n) if size >= 24 else "" for n, size in zip(flows["outcomes"], sizes)],
        textfont=dict(color=SURFACE, size=12),
        customdata=list(zip(keys, flows["samples"], flows["source"], target_names, flows["outcomes"])),
        hovertemplate=(
            "<b>%{customdata[2]}</b> in <b>%{customdata[3]}</b><br>%{customdata[4]} outcome statements"
            "<br><br><b>Sample outcomes</b><br>%{customdata[1]}<extra></extra>"
        ),
        selected=SELECTED,
        unselected=DOT_UNSELECTED,
    ))
    height = 16 + DOT_HEADER + DOT_ROW * len(rows)
    header_share = DOT_HEADER / (height - 16)
    grid_axis = dict(showgrid=True, gridcolor=GRID, fixedrange=True)
    layout = dict(
        height=height,
        xaxis=dict(type="category", categoryorder="array", categoryarray=[x_labels[t] for t in targets],
                   **grid_axis),
        yaxis=dict(type="category", categoryorder="array", categoryarray=[short_label(p, 40) for p in rows],
                   autorange="reversed", automargin=True, tickfont=dict(size=13, color=TEXT_PRIMARY),
                   domain=[0, 1 - header_share], **grid_axis),
        margin=dict(t=8, l=0, r=16, b=8),
        showlegend=False,
        dragmode=False,
    )
    if zoomed:
        # Goal names stay plain axis labels above the grid.
        layout["xaxis"].update(side="top", automargin=True, tickfont=dict(size=12, color=TEXT_SECONDARY))
        layout["yaxis"]["domain"] = [0, 1]
    else:
        # Domain names sit on their own strip (y2) as clickable text marks.
        totals = flows.groupby("target", sort=False)["outcomes"].sum()
        fig.add_trace(go.Scatter(
            x=[x_labels[t] for t in targets],
            y=[0] * len(targets),
            yaxis="y2",
            mode="markers+text",
            marker=dict(symbol="square", size=DOT_HEADER - 8, color=SURFACE, opacity=0),
            text=[f"{x_labels[t]} ›" for t in targets],
            textposition="middle center",
            textfont=dict(color=TEXT_PRIMARY, size=12),
            customdata=[(DOMAIN_KEY + t, "", t, names[t], int(totals[t])) for t in targets],
            hovertemplate=("<b>%{customdata[3]}</b><br>%{customdata[4]} outcome statements from these programs"
                           "<br>Click to see its goals<extra></extra>"),
            selected=HEADER_SELECTED,
            unselected=HEADER_UNSELECTED,
        ))
        layout["xaxis"]["showticklabels"] = False
        layout["yaxis2"] = dict(domain=[1 - header_share, 1], range=[-0.5, 0.5], visible=False, fixedrange=True)
    fig.update_layout(**layout)
    return fig


# =============================================================================
# PEERS
# =============================================================================

EMPTY_CELL = "#f5f5f2"   # the page canvas: an empty heatmap cell reads as "nothing here"


def build_peer_heatmap(counts: pd.DataFrame, samples: pd.DataFrame):
    """Heatmap of outcome counts: organizations (rows) x the selected organization's subcategories.

    Cells with no outcomes are left empty (the pale canvas shows through), so
    the eye goes to the overlaps that exist rather than to a grid of zeros.
    """
    shown = counts.where(counts > 0)
    fig = px.imshow(
        shown,
        color_continuous_scale=SEQUENTIAL_BLUE,
        zmin=0,
        aspect="auto",
        labels=dict(x="", y="", color="Outcomes"),
    )
    fig.update_traces(
        customdata=samples.to_numpy()[..., None],
        text=shown.map(lambda v: "" if pd.isna(v) else f"{int(v)}").to_numpy(),
        texttemplate="%{text}",
        hovertemplate="<b>%{y}</b><br>%{x}<br>%{z} outcomes" + SAMPLE_HOVER_BLOCK + "<extra></extra>",
        hoverongaps=False,
        xgap=2,
        ygap=2,
    )
    fig.update_layout(
        height=max(320, 40 * len(counts) + 200),
        plot_bgcolor=EMPTY_CELL,
        xaxis=dict(side="top", tickangle=-30, showgrid=False),
        yaxis=dict(showgrid=False),
        margin=dict(t=8, l=0, r=0, b=0),
        coloraxis_colorbar=dict(thickness=8, len=0.5, outlinewidth=0, tickfont=dict(size=11)),
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
        share = f"{n / total:.0%}" if n / total >= 0.01 else "<1%"
        fig.add_bar(
            # The legend gives each level's share; the filter pills below it give the counts.
            x=[n], y=[""], orientation="h", name=f"{level.title()} · {share}",
            marker=dict(color=colors.get(level, "#8a8984"), line=dict(color=SURFACE, width=2)),
            hovertemplate=f"<b>{level.title()}</b>: {n:,} outcomes ({n / total:.0%})<extra></extra>",
        )
    fig.update_layout(
        barmode="stack",
        height=74,
        bargap=0,
        showlegend=True,
        legend=dict(orientation="h", y=-0.12, yanchor="top", x=0, traceorder="normal", itemwidth=30,
                    font=dict(size=12, color=TEXT_SECONDARY)),
        xaxis=dict(visible=False, range=[0, total]),
        yaxis=dict(visible=False),
        margin=dict(t=0, l=0, r=0, b=34),
    )
    return fig
