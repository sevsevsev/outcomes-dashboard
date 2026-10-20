"""
The District priorities grid as a Streamlit component (st.components.v2).

Drawn in the browser by components/priority_grid.js, like the indicators map
(spotlight_component.py): the crosswalk's lanes as rows under the Board's three
headings, the codebook's domains as columns, a dot where a lane has goals from
a domain, and a side panel for whatever is pointed at or picked. Pointing costs
no rerun; only a pick comes back to Python, to filter the table below.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import streamlit as st

_HERE = Path(__file__).resolve().parent / "components"

_grid = st.components.v2.component(
    "priority_grid",
    css=(_HERE / "priority_grid.css").read_text(encoding="utf-8"),
    js=(_HERE / "priority_grid.js").read_text(encoding="utf-8"),
)


def priority_grid(data: dict, key: str, on_change: Optional[Callable[[], None]] = None) -> Optional[dict]:
    """Draw the grid; return the pick as {"kind": "lane" | "cell", "id": "lane" or "lane|domain"}, or None.

    `data` comes from outcomes_data.priority_grid_data plus a `sig`. A new `key` starts the grid afresh.
    """
    result = _grid(key=key, data=data, default={"selection": data.get("selected")},
                   on_selection_change=on_change or (lambda: None))
    selection = result.get("selection") if result else None
    return selection if isinstance(selection, dict) and selection.get("kind") else None
