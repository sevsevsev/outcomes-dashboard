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

import hashlib
import html
import json
import re
import textwrap
from typing import Optional, Sequence

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from outcomes_data import (
    COL_DOMAIN,
    COL_ORG_VIEW,
    COL_SUBCAT,
    COL_OUTCOME,
    DOMAIN_ONLY_SUFFIX,
    MEASURE_COLUMNS,
    MEASURE_ORGS,
    MEASURE_PROGRAMS,
    UNCODED_DOMAIN,
    count_organizations,
    distinct_counts_by,
    domain_code,
    domain_short,
    hierarchy_counts,
    sample_outcome_texts,
    SUNBURST_SEP,
)

# =============================================================================
# THEME
# =============================================================================

# Categorical palette, validated for color-vision deficiency in this order.
# Assigned by position, never cycled.
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

# One-hue sequential ramp for magnitude (light = little, dark = a lot).
SEQUENTIAL_BLUE = ["#e6f0fc", "#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]

# The codebook explorer's colors (Tailwind blue-600 and slate), so the two sites read as one family.
PRIMARY = "#3b82f6"       # blue-500: the explorer's blue, a step lighter so long bars don't shout
FADED = "#cbd5e1"          # marks that are not selected (slate-300)
TEXT_PRIMARY = "#0f172a"   # slate-900
TEXT_SECONDARY = "#64748b" # slate-500
GRID = "#e2e8f0"           # slate-200
SURFACE = "#ffffff"

FONT_FAMILY = '"Inter", -apple-system, "Segoe UI", sans-serif'

pio.templates["outcomes"] = go.layout.Template(
    layout=dict(
        font=dict(family=FONT_FAMILY, size=13, color=TEXT_PRIMARY),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=SURFACE,
        colorway=CATEGORICAL,
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=GRID, align="left",
                        font=dict(family=FONT_FAMILY, size=13, color=TEXT_PRIMARY)),
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
    return "<br>".join(textwrap.wrap(str(text), width=width, break_long_words=False, break_on_hyphens=False)) or str(text)


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
            fixed.append([sample_outcome_texts(df[COL_OUTCOME]), len(df), count_organizations(df[COL_ORG_VIEW]), ROOT_LABEL])
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
# CODEBOOK SUNBURST
# =============================================================================

# The sunburst is drawn in the browser (components/codebook_sunburst.js, after
# the codebook explorer's components/CodebookSunburst.tsx in the coder repo);
# this section builds its data. One quiet hue per domain, taken by the
# domain's position in the codebook, so a domain has the same color here as
# in the explorer whatever the filters.
DOMAIN_HUES = [28, 350, 262, 214, 158, 190, 4, 232, 44, 292, 128, 16]
NOUNS = {MEASURE_PROGRAMS: "programs", MEASURE_ORGS: "organizations"}
HOVER_SAMPLE_CHARS = 240   # longer sample statements are cut; the readout clamps them to three lines anyway


def _clip(text: str, limit: int) -> str:
    """A sample statement cut at a word break, with "…" so the reader sees it goes on."""
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def is_coded_domain(domain: str) -> bool:
    """False for the placeholder domain of rows the coder could not place."""
    return domain != UNCODED_DOMAIN


def codebook_sunburst_data(nodes: pd.DataFrame, measure: str = MEASURE_PROGRAMS,
                           selected: Optional[dict] = None, layout: str = "value",
                           short_names: Optional[dict] = None) -> dict:
    """What the browser-side sunburst (sunburst_component.py) draws, from `sunburst_nodes`.

    `layout` "value" sizes each slice by its count (the sunburst). "equal"
    gives every goal the same angle and shows its count as the length of its
    bar (the wheel), so goals with few or no programs keep a visible place;
    build its nodes with `sunburst_nodes(..., include_empty_goals=True)`.

    Programs and organizations work in several goals, so a domain's arc is
    the sum of its goals' counts, while its readout gives the exact number
    of distinct programs (or organizations) in the domain. `sig` changes only
    when what is drawn changes, so reruns caused by a click leave the chart
    (and its zoom) alone.

    Each node's `names` lists its plain names, longest first, then its code
    (domain: full name, nickname, code; goal: full name, `short_names` entry,
    code), so the chart writes the longest one that fits.
    """
    short_names = short_names or {}
    size_col = MEASURE_COLUMNS[measure]
    noun = NOUNS.get(measure, "outcome statements")
    goal_sizes = nodes[size_col].astype(float).where(nodes["level"] == "goal", 0.0)
    domain_sizes = goal_sizes.groupby(nodes["parent"]).sum()
    category_sizes = goal_sizes.groupby(nodes["category"]).sum()
    out = []
    for row, size in zip(nodes.itertuples(index=False), goal_sizes):
        coded = row.level == "root" or is_coded_domain(row.domain)
        if row.level == "domain":
            eyebrow = f"Domain {row.code}" if row.code else "Not coded"
            label = row.code if coded else "–"
            size = float(domain_sizes.get(row.id, 0.0))
        elif row.level == "category":
            eyebrow, label = f"{domain_code(row.domain)} · Category {row.code}", row.code
            size = float(category_sizes.get(row.id, 0.0))
        elif row.level == "goal":
            # A domain-only row's "goal" carries the domain's number and no code of its own.
            has_code = "." in row.code
            eyebrow = (f"Goal {row.code}" if has_code else "Not coded" if not coded
                       else "Domain only" if row.goal.endswith(DOMAIN_ONLY_SUFFIX) else "No goal assigned")
            label = row.code if has_code else ""
        else:
            eyebrow, label = "", ""
        if row.level == "domain":
            names = [row.title, DOMAIN_NICKNAMES.get(row.code, ""), row.code] if coded else [row.title]
        elif row.level == "category":
            names = [row.title, row.code]
        elif row.level == "goal":
            names = [row.title, short_names.get(row.code, ""), row.code if "." in row.code else ""]
        else:
            names = []
        out.append({
            "id": row.id, "parent": row.parent, "level": row.level,
            "names": list(dict.fromkeys(n for n in names if n)),
            "goal": row.goal if isinstance(row.goal, str) else None,
            "category": row.category or None,
            "eyebrow": eyebrow, "title": row.title, "label": label,
            "hue": DOMAIN_HUES[int(row.domain_index) % len(DOMAIN_HUES)] if coded and row.domain_index >= 0 else None,
            "value": size, "count": int(getattr(row, size_col)),
            "programs": int(row.programs), "organizations": int(row.organizations), "outcomes": int(row.outcomes),
            "samples": [_clip(" ".join(str(t).split()), HOVER_SAMPLE_CHARS) for t in row.sample_list],
        })
    n_domains = int(nodes.loc[nodes["level"] == "domain", "domain"].map(is_coded_domain).sum())
    sig = hashlib.sha1(json.dumps([measure, layout, [(n["id"], n["value"], n["count"]) for n in out]]).encode()).hexdigest()
    return {
        "sig": sig[:16], "layout": layout, "sep": SUNBURST_SEP, "noun": noun, "noun_one": noun.removesuffix("s"),
        "n_domains": n_domains, "nodes": out, "selected": selected,
    }


# =============================================================================
# RANKED BARS AND DOTS (the linked, clickable views)
# =============================================================================

# How labels fit (the same rules on every page):
# * A chart never cuts a name. Long names wrap at word breaks onto a second
#   (rarely a third) line, and rows grow to fit; hover still has the full name.
# * A row's identity is always its full name. Only the tick text is wrapped, so
#   two names that share a long prefix can't merge into one row.
# * Plotly sizes the label gutter from the tick text (automargin), so the
#   layout follows from the data alone and stays the same on every rerun.
AXIS_WRAP = 26     # characters per line in row labels
AXIS_MAX_LINES = 3
ROW_HEIGHT = 30    # pixels per one-line bar row; two-line rows get more
LINE_HEIGHT = 16   # pixels per line of 13px label text
BAR_THICKNESS = 18
LABEL_GAP = 8      # pixels between a row label and its bar or grid


def axis_label(text: str, width: int = AXIS_WRAP, max_lines: int = AXIS_MAX_LINES) -> str:
    """A row label wrapped at word breaks ("<br>"), never mid-word or at a hyphen.

    Only a name longer than `max_lines` lines loses its tail, with "…".
    """
    text = str(text)
    lines = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [text]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,;:&-") + "…"
    return "<br>".join(html.escape(line, quote=False) for line in lines)


def line_count(label: str) -> int:
    return label.count("<br>") + 1


def category_ticks(names: Sequence[str], width: int = AXIS_WRAP, color: Optional[dict] = None) -> dict:
    """Axis settings that keep each row keyed on its full name but print it wrapped.

    `color` maps a name to a text color for rows that should read differently.
    """
    color = color or {}

    def tick(name: str) -> str:
        label = axis_label(name, width)
        if name not in color:
            return label
        return "<br>".join(f"<span style='color:{color[name]}'>{line}</span>" for line in label.split("<br>"))

    # An invisible tick makes the gap between label and plot; unlike a label standoff,
    # automargin counts tick length when it sizes the gutter, so no label is clipped.
    return dict(tickmode="array", tickvals=list(names), ticktext=[tick(n) for n in names],
                ticks="outside", ticklen=LABEL_GAP, tickcolor="rgba(0,0,0,0)")


# How a clicked mark and the others look. Plotly applies this in the browser, so
# the figure itself never changes with the selection; Streamlit identifies a
# chart by its figure, and a changed figure would drop the reader's click.
SELECTED = dict(marker=dict(color=PRIMARY, opacity=1))
UNSELECTED = dict(marker=dict(color=FADED, opacity=1))
# Bars carry their value as text; it stays in text ink whether or not the bar is picked.
BAR_SELECTED = dict(marker=SELECTED["marker"], textfont=dict(color=TEXT_PRIMARY))
BAR_UNSELECTED = dict(marker=UNSELECTED["marker"], textfont=dict(color=TEXT_SECONDARY))


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
    column. Long labels wrap, and every row grows to the tallest label.
    """
    keys = data[key_col].tolist()
    names = [str(v) for v in data[label_col]]
    custom = list(zip(keys, data["samples"], names))
    lines = max((line_count(axis_label(n)) for n in names), default=1)
    row = max(ROW_HEIGHT, LINE_HEIGHT * lines + 12)
    fig = go.Figure(go.Bar(
        x=data[value_col],
        y=names,
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
        # The top margin keeps Plotly's hover toolbar off the first (longest) bar's value.
        height=row * max(len(data), 2) + 32,
        xaxis=dict(visible=False, range=[0, (data[value_col].max() or 1) * 1.12]),
        yaxis=dict(type="category", autorange="reversed", automargin=True,
                   tickfont=dict(color=TEXT_PRIMARY, size=13), showgrid=False, **category_ticks(names)),
        margin=dict(t=28, l=0, r=8, b=4),
        bargap=1 - BAR_THICKNESS / row,
        barcornerradius=4,
        showlegend=False,
        dragmode=False,
    )
    return fig


# --- Dot grids (Find peers, Partners at a school) ----------------------------

DOT_ROW = 58         # pixels per row: room for a three-line name
DOMAIN_KEY = "domain::"   # customdata[0] prefix for a clicked domain header
# Codebook colors: each domain's dots and header take the hue it has in the
# codebook explorer and the sunburst (DOMAIN_HUES, by codebook position).
DOMAIN_ORDER_V3 = ["Y1", "Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "F1", "F2", "A1", "A2", "A3"]
UNCODED_DOT = "#9aa1ad"
# Column headers: the code large and bold in the domain's color, a short name
# under it. When columns get narrow, every other header steps up one tier (a
# thin line drops to its column), so each header has two columns of width.
HEADER_CODE_SIZE = 15
HEADER_NAME_SIZE = 12
HEADER_LINE = 16     # pixels per header line
STAGGER_AT = 7       # more columns than this and the headers stagger
DOMAIN_NAME_WRAP = 11
GOAL_NAME_WRAP = 13
GOAL_NAME_LINES = 3
# Header marks are invisible hit areas under the header text; only the text shows.
HEADER_SELECTED = dict(marker=dict(opacity=0))
HEADER_UNSELECTED = dict(marker=dict(opacity=0))
# Dots keep their domain's color when picked; the others fade.
DOT_SELECTED = dict(marker=dict(opacity=1))
DOT_UNSELECTED = dict(marker=dict(opacity=0.22), textfont=dict(color=TEXT_SECONDARY))
# A school can touch every 3.x domain, too many columns for full names, so each
# domain header carries a word or two; hovering a header gives the full name.
DOMAIN_NICKNAMES = {
    "Y1": "Academics", "Y2": "Interest", "Y3": "Belonging", "Y4": "Social-emotional", "Y5": "Identity",
    "Y6": "Character, civic", "Y7": "Career", "Y8": "Health, safety", "F1": "Families", "F2": "Basic needs",
    "A1": "Staff", "A2": "Program quality", "A3": "Systems",
}


def label_code(label: str) -> Optional[str]:
    """The domain code a domain or goal label starts with: "Y4" for "Domain Y4. ..." or "Y4.2 ...",
    "3" for "3.1.4 ..."; None for placeholders such as "Uncoded"."""
    match = re.match(r"^\s*(?:Domain\s+)?([YFA]?)(\d+)", str(label))
    return match.group(1) + match.group(2) if match else None


def domain_hue(label: str) -> Optional[int]:
    """The codebook explorer's hue for the domain a domain or goal label belongs to."""
    code = label_code(label)
    if code is None or not is_coded_domain(label):
        return None
    index = DOMAIN_ORDER_V3.index(code) if code in DOMAIN_ORDER_V3 else int(code) - 1 if code.isdigit() else None
    return None if index is None else DOMAIN_HUES[index % len(DOMAIN_HUES)]


def domain_color(label: str, lightness: int = 46) -> str:
    hue = domain_hue(label)
    return UNCODED_DOT if hue is None else f"hsl({hue}, 55%, {lightness}%)"


def _wrap_lines(text: str, width: int, max_lines: int, hyphens: bool = True) -> list[str]:
    lines = textwrap.wrap(str(text), width=width, break_long_words=False, break_on_hyphens=hyphens) or [str(text)]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,;:&-") + "…"
    return lines


def _header_parts(target: str, zoomed: bool) -> tuple[str, list[str]]:
    """(code, name lines) for a column header."""
    if zoomed:
        code = str(target).split(" ", 1)[0] if label_code(target) else ""
        title = str(target).split(" ", 1)[1] if code and " " in str(target) else str(target)
        return code, _wrap_lines(title, GOAL_NAME_WRAP, GOAL_NAME_LINES, hyphens=False)
    code = domain_code(target)
    if code is None or not is_coded_domain(target):
        return "", ["Uncoded" if not is_coded_domain(target) else domain_short(target)]
    name = DOMAIN_NICKNAMES.get(code) or domain_short(target).split(" ", 1)[-1]
    return code, _wrap_lines(name, DOMAIN_NAME_WRAP, 2)


def _header_text(code: str, lines: list[str], color: str, arrow: bool) -> str:
    tail = " ›" if arrow else ""
    name = "<br>".join(html.escape(line, quote=False) for line in lines)
    if not code:
        return f"<b>{name}</b>{tail}"
    return (f"<span style='font-size:{HEADER_CODE_SIZE}px;color:{color}'><b>{code}</b></span>{tail}"
            f"<br>{name}")


def build_program_dots(flows: pd.DataFrame, programs: list[str], zoomed: bool = False):
    """Programs (rows) by domain or subcategory (columns); dot area is the number of outcome statements.

    It answers "where do these programs overlap?" without crossing lines.
    customdata[0] is "program||target", so a click tells the app which cell
    was picked. With domains as columns, each domain header is itself a
    clickable mark (customdata[0] is DOMAIN_KEY + domain) so the app can
    drill into that domain's goals; axis labels can't be clicked. Rows are
    keyed on full names and printed wrapped; dots and headers take their
    domain's codebook color.
    """
    targets = list(dict.fromkeys(flows["target"]))
    rows = [p for p in programs if p in set(flows["source"])]
    peak = flows["outcomes"].max() or 1
    # The biggest dot shrinks when columns get narrow, so neighbors don't touch.
    biggest = max(30, min(46, 640 / max(len(targets), 1)))
    sizes = [12 + (biggest - 12) * (n / peak) ** 0.5 for n in flows["outcomes"]]
    keys = [f"{src}||{tgt}" for src, tgt in zip(flows["source"], flows["target"])]
    names = {t: (t if zoomed else domain_short(t)) for t in targets}
    target_names = [names[t] for t in flows["target"]]
    fig = go.Figure(go.Scatter(
        x=list(flows["target"]),
        y=list(flows["source"]),
        mode="markers+text",
        marker=dict(size=sizes, color=[domain_color(t) for t in flows["target"]], opacity=1,
                    line=dict(color=SURFACE, width=2)),
        # Counts print inside dots big enough to hold them; hover gives every count.
        text=[str(n) if size >= 24 else "" for n, size in zip(flows["outcomes"], sizes)],
        textfont=dict(color=SURFACE, size=12),
        customdata=list(zip(keys, flows["samples"], flows["source"], target_names, flows["outcomes"])),
        hovertemplate=(
            "<b>%{customdata[2]}</b> in <b>%{customdata[3]}</b><br>%{customdata[4]} outcome statements"
            "<br><br><b>Sample outcomes</b><br>%{customdata[1]}<extra></extra>"
        ),
        selected=DOT_SELECTED,
        unselected=DOT_UNSELECTED,
    ))

    # The header strip (y2), in pixels: one or two tiers of header text.
    parts = {t: _header_parts(t, zoomed) for t in targets}
    tier = HEADER_LINE * (1 + max((len(lines) for _, lines in parts.values()), default=1)) + 6
    stagger = len(targets) > STAGGER_AT
    strip = tier * (2 if stagger else 1) + 6
    lifted = [stagger and i % 2 == 1 for i in range(len(targets))]
    centers = [tier * (1.5 if up else 0.5) + 4 for up in lifted]
    totals = flows.groupby("target", sort=False)["outcomes"].sum()
    fig.add_trace(go.Scatter(
        x=targets,
        y=centers,
        yaxis="y2",
        mode="markers+text",
        marker=dict(symbol="square", size=tier - 4, color=SURFACE, opacity=0),
        text=[_header_text(*parts[t], domain_color(t, 40), arrow=not zoomed) for t in targets],
        textposition="middle center",
        textfont=dict(color=TEXT_PRIMARY, size=HEADER_NAME_SIZE),
        customdata=[((DOMAIN_KEY + t) if not zoomed else "", "", t, names[t], int(totals[t])) for t in targets],
        hovertemplate=("<b>%{customdata[3]}</b><br>%{customdata[4]} outcome statements from these rows"
                       + ("" if zoomed else "<br>Click to see its goals") + "<extra></extra>"),
        selected=HEADER_SELECTED,
        unselected=HEADER_UNSELECTED,
    ))

    if any(lifted):
        # Drawn after the headers, so the header stays fig.data[1]. A thin line from each lifted header down to its column.
        line_x, line_y = [], []
        for t, up, c in zip(targets, lifted, centers):
            if up:
                line_x += [t, t, None]
                line_y += [0, c - tier / 2 + 2, None]
        fig.add_trace(go.Scatter(x=line_x, y=line_y, yaxis="y2", mode="lines", hoverinfo="skip",
                                 line=dict(color=GRID, width=1), showlegend=False))
    height = 12 + strip + DOT_ROW * len(rows)
    header_share = strip / (height - 12)
    grid_axis = dict(showgrid=True, gridcolor=GRID, fixedrange=True)
    fig.update_layout(
        height=height,
        xaxis=dict(type="category", categoryorder="array", categoryarray=targets, showticklabels=False,
                   **grid_axis),
        yaxis=dict(type="category", categoryorder="array", categoryarray=rows,
                   range=[len(rows) - 0.5, -0.5], automargin=True,
                   tickfont=dict(size=13, color=TEXT_PRIMARY), domain=[0, 1 - header_share],
                   **category_ticks(rows), **grid_axis),
        yaxis2=dict(domain=[1 - header_share, 1], range=[0, strip], visible=False, fixedrange=True),
        margin=dict(t=6, l=0, r=16, b=6),
        showlegend=False,
        dragmode=False,
    )
    return fig


NOT_CODED_TEXT = "#8a909b"   # rows for partners whose outcomes are not coded


def build_school_dots(flows: pd.DataFrame, partners: list[str], extra_rows: Sequence[tuple[str, str]] = (),
                      zoomed: bool = False):
    """build_program_dots for one school's partners, plus grey rows for partners with nothing to plot.

    `extra_rows` is (partner, note) pairs, such as ("Partner 170", "Not yet coded"):
    they keep the whole portfolio on one chart, so the reader sees how much of
    it the dots cover. They are left out when zoomed into one domain.
    """
    fig = build_program_dots(flows, partners, zoomed=zoomed)
    if zoomed or not extra_rows:
        return fig
    plotted = list(fig.layout.yaxis.categoryarray)
    labels = [p for p, _ in extra_rows if p not in plotted]
    notes = [note for p, note in extra_rows if p not in plotted]
    first_column = fig.layout.xaxis.categoryarray[0]
    fig.add_trace(go.Scatter(
        x=[first_column] * len(labels), y=labels, mode="text",
        text=notes, textposition="middle right",
        textfont=dict(color=NOT_CODED_TEXT, size=12),
        customdata=[("",)] * len(labels), hoverinfo="skip",
        selected=dict(textfont=dict(color=NOT_CODED_TEXT)), unselected=dict(textfont=dict(color=NOT_CODED_TEXT)),
    ))
    strip = fig.layout.yaxis2.range[1]
    rows = plotted + labels
    height = 12 + strip + DOT_ROW * len(rows)
    header_share = strip / (height - 12)
    fig.update_layout(
        height=height,
        yaxis=dict(categoryarray=rows, range=[len(rows) - 0.5, -0.5], domain=[0, 1 - header_share],
                   **category_ticks(rows, color={p: NOT_CODED_TEXT for p in labels})),
        yaxis2=dict(domain=[1 - header_share, 1]),
    )
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
        yaxis=dict(showgrid=False, automargin=True, **category_ticks([str(i) for i in counts.index])),
        margin=dict(t=8, l=0, r=0, b=0),
        coloraxis_colorbar=dict(thickness=8, len=0.5, outlinewidth=0, tickfont=dict(size=11)),
    )
    return fig


# =============================================================================
# REVIEW
# =============================================================================


def build_confidence_bar(counts: pd.Series):
    """One stacked bar showing how the coder's confidence is distributed (a compact overview)."""
    colors = {"high": "#2563eb", "medium": "#93c5fd", "low": "#f59e0b", "none": "#94a3b8"}
    fig = go.Figure()
    total = int(counts.sum()) or 1
    for level, n in counts.items():
        share = f"{n / total:.0%}" if n / total >= 0.01 else "<1%"
        fig.add_bar(
            # The legend gives each level's share; the filter pills below it give the counts.
            x=[n], y=[""], orientation="h", name=f"{level.title()} · {share}",
            marker=dict(color=colors.get(level, "#94a3b8"), line=dict(color=SURFACE, width=2)),
            hovertemplate=f"<b>{level.title()}</b>: {n:,} outcomes ({n / total:.0%})<extra></extra>",
        )
    fig.update_layout(
        barmode="stack",
        height=58,
        bargap=0,
        showlegend=True,
        legend=dict(orientation="h", y=-0.12, yanchor="top", x=0, traceorder="normal", itemwidth=30,
                    font=dict(size=12, color=TEXT_SECONDARY)),
        xaxis=dict(visible=False, range=[0, total]),
        yaxis=dict(visible=False),
        margin=dict(t=0, l=0, r=0, b=36),
        barcornerradius=4,
    )
    return fig
