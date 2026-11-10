"""
The Portrait of a Graduate wheel as a Streamlit component (st.components.v2).

Drawn in the browser by components/portrait_wheel.js, like the codebook wheel
(sunburst_component.py): the District graphic's six slices, a ring of the 14
competencies, the outer ring's two halves, the "Results the Portrait does not
name" list on the left and a side panel on the right. Pointing costs no rerun;
only a pick (a slice, competency, skill or outside code) comes back to Python,
to narrow the table below.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import streamlit as st

_HERE = Path(__file__).resolve().parent / "components"

_wheel = st.components.v2.component(
    "portrait_wheel",
    css=(_HERE / "portrait_wheel.css").read_text(encoding="utf-8"),
    js=(_HERE / "portrait_wheel.js").read_text(encoding="utf-8"),
)


def portrait_wheel(data: dict, key: str) -> Optional[dict]:
    """Draw the wheel; return the pick as {"kind": "slice" | "competency" | "only" | "skill" | "outside", "id"},
    or None. `data` comes from portrait.wheel_data. A new `key` starts the wheel afresh."""
    result = _wheel(key=key, data=data, default={"selection": data.get("selected")},
                    on_selection_change=lambda: None)
    selection = result.get("selection") if result else None
    return selection if isinstance(selection, dict) and selection.get("kind") else None
