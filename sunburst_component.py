"""
The codebook sunburst as a Streamlit component (st.components.v2).

Plotly's sunburst sent every hover to a tooltip and every click through a
full Python rerun that rebuilt the figure. This one is plain SVG drawn by
components/codebook_sunburst.js: hover feedback, zooming into a domain and
the readouts all happen in the browser, and only a click's result (the
picked domain and goal) comes back to Python, to filter the table below.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import streamlit as st

_HERE = Path(__file__).resolve().parent / "components"

_sunburst = st.components.v2.component(
    "codebook_sunburst",
    css=(_HERE / "codebook_sunburst.css").read_text(encoding="utf-8"),
    js=(_HERE / "codebook_sunburst.js").read_text(encoding="utf-8"),
)


def codebook_sunburst(data: dict, key: str) -> Optional[dict]:
    """Draw the sunburst; return the picked {"domain", "goal"} (goal may be None), or None.

    `data` comes from charts.codebook_sunburst_data. A new `key` starts the
    chart afresh, unzoomed and with nothing picked.
    """
    result = _sunburst(key=key, data=data, default={"selection": data.get("selected")},
                       on_selection_change=lambda: None)
    selection = result.get("selection") if result else None
    return selection if isinstance(selection, dict) and selection.get("domain") else None
