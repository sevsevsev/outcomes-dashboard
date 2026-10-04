"""Write reference/codebook_terms_v3.csv: the words the chart search looks at for each 3.x code.

The codebook's own descriptions live in the coder repo
(Qualitative-Outcomes-Coder, codebooks/youthOutcomesV3.data.ts). This copies
the parts that say what a domain or goal covers (its name, short name,
category, definition and "include" line) so a search for "mentoring" finds
Y3.2 Supportive adults even when no program uses that word. The "exclude"
and "use instead" lines are left out: they name what a code is NOT.

Run it again when the codebook changes:

    python scripts/build_codebook_terms.py ../Qualitative-Outcomes-Coder/codebooks/youthOutcomesV3.data.ts
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "reference" / "codebook_terms_v3.csv"


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
        out.append({"code": d["id"], "terms": " ".join([d["name"], d.get("description", "")]).strip()})
        for cat in d["categories"]:
            for c in cat["codes"]:
                parts = [c["name"], c.get("short", ""), cat["name"], c.get("definition", ""), c.get("include", "")]
                out.append({"code": c["id"], "terms": " ".join(p for p in parts if p).strip()})
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["code", "terms"])
        writer.writeheader()
        writer.writerows(rows(read_domains(Path(sys.argv[1]))))
    print(f"wrote {OUT}")
