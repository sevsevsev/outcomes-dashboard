"""Copy the SPOTlight indicator links and the outcome crosswalk from the coder repo into reference/.

The coder repo (Qualitative-Outcomes-Coder) builds two files the District pages read:

* codebook-refinement/spotlight/youth_outcomes_v3.spotlight-links.json, from the
  checked evidence table of the SPOTlight relevance review: the District's 13
  SPOTlight indicators, the recommended links from codebook 3.x goals to those
  indicators (each with its evidence level and the program model a partner must
  run), the links that were checked and turned down, and the guardrail note.
  Copied to reference/spotlight_links_v3.json. The dashboard reads this copy
  rather than the `possible_spotlight_links` column, which older exports don't have.
* codebook-refinement/crosswalk/youth_outcomes_v3.crosswalk.json, the outcome
  crosswalk: each code and domain in exactly one lane, the District priority it
  serves, with a plain "serves" line, the lane names and the Board Bylaw 003.1
  quotes. It holds no counts and no evidence. Copied to
  reference/outcome_crosswalk_v3.json. The two files are joined by code in the
  dashboard, never edited.

Each file is copied as it is, so the coder repo stays its one source. Copy only
from the coder's main branch. Run this again whenever the coder rebuilds either
file; it tells them apart by their contents:

    python scripts/build_spotlight_links.py ../Qualitative-Outcomes-Coder/codebook-refinement/spotlight/youth_outcomes_v3.spotlight-links.json ../Qualitative-Outcomes-Coder/codebook-refinement/crosswalk/youth_outcomes_v3.crosswalk.json

A link is "possible" only: it counts for a program that runs the studied model,
which a person has to confirm. A lane is not a score. Public display needs
district sign-off.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "reference"
OUT = REFERENCE / "spotlight_links_v3.json"
CROSSWALK_OUT = REFERENCE / "outcome_crosswalk_v3.json"
NEEDED = ("indicators", "links", "notRecommended", "guardrails")
CROSSWALK_NEEDED = ("lanes", "codes", "source")


def check(data: dict) -> None:
    """Stop on a file that isn't the links file, or whose links name an indicator it doesn't list."""
    missing = [k for k in NEEDED if k not in data]
    if missing:
        sys.exit(f"not a SPOTlight links file: missing {', '.join(missing)}")
    indicators = {i["id"] for i in data["indicators"]}
    for link in data["links"] + data.get("associated", []):
        unknown = set(link["indicators"]) - indicators
        if unknown:
            sys.exit(f"link {link['id']} names unknown indicators {sorted(unknown)}")


def check_crosswalk(data: dict) -> None:
    """Stop on a crosswalk with a code in no lane or in two, a lane it doesn't list, or any counts."""
    missing = [k for k in CROSSWALK_NEEDED if k not in data]
    if missing:
        sys.exit(f"not an outcome crosswalk: missing {', '.join(missing)}")
    lanes = {lane["id"] for lane in data["lanes"]}
    seen = set()
    for entry in data["codes"]:
        if entry["code"] in seen:
            sys.exit(f"code {entry['code']} appears twice")
        seen.add(entry["code"])
        if entry.get("lane") not in lanes:
            sys.exit(f"code {entry['code']} names unknown lane {entry.get('lane')!r}")
        if not entry.get("serves"):
            sys.exit(f"code {entry['code']} has no serves line")
    if any(isinstance(v, (int, float)) for entry in data["codes"] for v in entry.values()):
        sys.exit("the crosswalk carries numbers; it should hold no counts")


def copy(path: str) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "lanes" in data:
        check_crosswalk(data)
        CROSSWALK_OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {CROSSWALK_OUT}: {len(data['codes'])} codes and domains in {len(data['lanes'])} lanes "
              f"(crosswalk {data.get('crosswalkVersion', '?')}, codebook {data.get('codebookVersion', '?')})")
        return
    check(data)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(data['indicators'])} indicators, {len(data['links'])} recommended links "
          f"(codebook {data.get('codebookVersion', '?')}, reviewed {data.get('reviewedOn', '?')})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        copy(arg)
