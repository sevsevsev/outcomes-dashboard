"""Write reference/codebook_terms_v3.csv: each 3.x code's category, and the words the chart search looks at.

The codebook's own descriptions live in the coder repo
(Qualitative-Outcomes-Coder, codebooks/youthOutcomesV3.data.ts). This copies
the parts that say what a domain or goal covers (its name, short name,
category, definition and "include" line) so a search for "mentoring" finds
Y3.2 Supportive adults even when no program uses that word. The "exclude"
and "use instead" lines are left out: they name what a code is NOT.

The `category` column ("B. Close relationships") puts each goal in its
category, for the wheel's category ring, and `short` is the goal's short
name ("Supportive adults"), for wheel labels too tight for the full name;
domain rows leave both blank.

It also writes reference/codebook_definitions_v3.json: what the wheel's side
panel shows for an open domain or a picked goal. A domain gets its description;
a goal its definition, what it includes and excludes, and the goals its "use
instead" line points to (as codes; the chart shows their names). Codes inside
those lines are swapped for plain names, since the dashboard shows names, not
codes. Categories have no description in the codebook, so they get none here.
The file records the codebook version it came from.

Run it again when the codebook changes:

    python scripts/build_codebook_terms.py ../Qualitative-Outcomes-Coder/codebooks/youthOutcomesV3.data.ts
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "reference" / "codebook_terms_v3.csv"
DEFINITIONS_OUT = OUT.with_name("codebook_definitions_v3.json")
CODE = re.compile(r"\b([YFA]\d+(?:\.\d+)?)(?:\s*[-\u2013]\s*([YFA]\d+\.\d+))?\b")


def read_domains(ts_path: Path) -> list[dict]:
    text = ts_path.read_text(encoding="utf-8")
    start = text.index("= [", text.index("export const V3_DOMAINS")) + 2
    depth = 0
    for end in range(start, len(text)):
        depth += {"[": 1, "]": -1}.get(text[end], 0)
        if depth == 0:
            break
    return json.loads(text[start:end + 1])


def rows(domains: list[dict]) -> list[dict]:
    out = []
    for d in domains:
        out.append({"code": d["id"], "category": "", "short": "",
                    "terms": " ".join([d["name"], d.get("description", "")]).strip()})
        for cat in d["categories"]:
            for c in cat["codes"]:
                parts = [c["name"], c.get("short", ""), cat["name"], c.get("definition", ""), c.get("include", "")]
                out.append({"code": c["id"], "category": f"{cat['letter']}. {cat['name']}", "short": c.get("short", ""),
                            "terms": " ".join(p for p in parts if p).strip()})
    return out


def read_version(ts_path: Path) -> str:
    """V3_VERSION from youthOutcomesV3.ts, next to the data file."""
    found = re.search(r"V3_VERSION\s*=\s*'([^']+)'", (ts_path.parent / "youthOutcomesV3.ts").read_text(encoding="utf-8"))
    return found.group(1) if found else ""


def definitions(domains: list[dict], version: str) -> dict:
    names = {d["id"]: d["name"] for d in domains}
    for d in domains:
        for cat in d["categories"]:
            for c in cat["codes"]:
                names[c["id"]] = c.get("short") or c["name"]
    order = list(names)

    def span(first: str, last: str | None) -> list[str]:
        """A code, or every code from `first` to `last` ("Y1.1-Y1.4")."""
        if not last or first not in order or last not in order:
            return [first]
        return order[order.index(first):order.index(last) + 1]

    def plain(text: str) -> str:
        def name(m: re.Match) -> str:
            first, last = m.group(1), m.group(2)
            if first not in names:
                return m.group(0)
            return names[first] if not last or last not in names else f"{names[first]} to {names[last]}"
        return CODE.sub(name, text or "").strip()

    out = {"version": version, "domains": {}, "goals": {}}
    for d in domains:
        out["domains"][d["id"]] = {"description": plain(d.get("description", ""))}
        for cat in d["categories"]:
            for c in cat["codes"]:
                see = []
                for m in CODE.finditer(c.get("useInstead", "")):
                    for code in span(m.group(1), m.group(2)):
                        if code in names and code != c["id"] and code not in see:
                            see.append(code)
                out["goals"][c["id"]] = {"definition": plain(c.get("definition", "")), "include": plain(c.get("include", "")),
                                         "exclude": plain(c.get("exclude", "")), "see_also": see}
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["code", "category", "short", "terms"])
        writer.writeheader()
        domains = read_domains(Path(sys.argv[1]))
        writer.writerows(rows(domains))
    DEFINITIONS_OUT.write_text(json.dumps(definitions(domains, read_version(Path(sys.argv[1]))), indent=1, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    print(f"wrote {OUT} and {DEFINITIONS_OUT}")
