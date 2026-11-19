"""Which pages and views this release shows.

The first stable release keeps three pages (the wheel, Find peers and Partners at a school) so people meet
a small, settled tool first. The other pages and the ranked view stay in the code and come back when
`SHOW_ALL_PAGES` is set to a true value, as an environment variable or a Streamlit secret (for testing
them locally or on a private deploy).
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

FLAG = "SHOW_ALL_PAGES"
ALL_PAGES = ("map", "peers", "schools", "indicators", "portrait", "review")
RELEASED_PAGES = ("map", "peers", "schools")
ALL_VIEWS = ("Wheel", "Ranked")
RELEASED_VIEWS = ("Wheel",)
TRUE = {"1", "true", "yes", "on"}


def flag_on(environ: Mapping[str, str] = os.environ, secrets: Optional[Mapping] = None) -> bool:
    """True when SHOW_ALL_PAGES is set to 1, true, yes or on, in the environment or the app's secrets."""
    for source in (environ, {} if secrets is None else secrets):
        try:
            value = source.get(FLAG)
        except Exception:   # Streamlit raises when no secrets file exists
            value = None
        if value is not None and str(value).strip().lower() in TRUE:
            return True
    return False


def shown_pages(all_on: bool) -> tuple[str, ...]:
    return ALL_PAGES if all_on else RELEASED_PAGES


def shown_views(all_on: bool) -> tuple[str, ...]:
    return ALL_VIEWS if all_on else RELEASED_VIEWS
