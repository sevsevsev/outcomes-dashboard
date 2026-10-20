"""
The District indicators map as a Streamlit component (st.components.v2).

Drawn in the browser by components/spotlight_map.js, like the codebook wheel
(sunburst_component.py): goals on the left, the program models the studies
tested in the middle, the District's SPOTlight indicators on the right, with a
side panel for whatever is pointed at or picked. Pointing costs no rerun; only
a pick comes back to Python, to filter the table below.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import streamlit as st

_HERE = Path(__file__).resolve().parent / "components"

_map = st.components.v2.component(
    "spotlight_map",
    css=(_HERE / "spotlight_map.css").read_text(encoding="utf-8"),
    js=(_HERE / "spotlight_map.js").read_text(encoding="utf-8"),
)


def spotlight_map(data: dict, key: str, on_change: Optional[Callable[[], None]] = None) -> Optional[dict]:
    """Draw the map; return the pick as {"kind": "goal" | "link" | "indicator" | "other", "id"}, or None.

    `data` comes from charts.spotlight_map_data. A new `key` starts the map afresh, with nothing picked.
    """
    result = _map(key=key, data=data, default={"selection": data.get("selected")},
                  on_selection_change=on_change or (lambda: None))
    selection = result.get("selection") if result else None
    return selection if isinstance(selection, dict) and selection.get("kind") else None
