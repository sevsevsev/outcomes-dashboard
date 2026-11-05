"""
The District indicators map as a Streamlit component (st.components.v2).

Drawn in the browser by components/spotlight_map.js, like the codebook wheel
(sunburst_component.py): the District's SPOTlight indicators in a list, and for
the one picked there, its goals, the program models and research associations
that join them to it, and the indicator, with a side panel for whatever is
pointed at or picked. Pointing costs no rerun; only
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
    """Draw the map; return the pick as {"kind": "goal" | "link" | "indicator", "id", "focus"}, or None.

    `focus` is the indicator shown when the pick was made. `data` comes from charts.spotlight_map_data. A new
    `key` starts the map afresh, on `data["focus"]` with nothing picked.
    """
    result = _map(key=key, data=data, default={"selection": data.get("selected")},
                  on_selection_change=on_change or (lambda: None))
    selection = result.get("selection") if result else None
    return selection if isinstance(selection, dict) and selection.get("kind") else None
