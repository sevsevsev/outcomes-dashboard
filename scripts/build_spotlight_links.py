"""Copy the SPOTlight indicator links from the coder repo into reference/spotlight_links_v3.json.

The coder repo (Qualitative-Outcomes-Coder) builds
codebook-refinement/spotlight/youth_outcomes_v3.spotlight-links.json from the
checked evidence table of the SPOTlight relevance review: the District's 13
SPOTlight indicators, the 12 recommended links from codebook 3.x goals to those
indicators (each with its evidence level and the program model a partner must
run), the links that were checked and turned down, and the guardrail note for
goals with no link. The dashboard reads this copy rather than the
`possible_spotlight_links` column, which older exports don't have.

The file is copied as it is, so the coder repo stays its one source. Run this
again whenever the coder rebuilds it:

    python scripts/build_spotlight_links.py ../Qualitative-Outcomes-Coder/codebook-refinement/spotlight/youth_outcomes_v3.spotlight-links.json

A link is "possible" only: it counts for a program that runs the studied model,
which a person has to confirm. Public display needs district sign-off.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "reference" / "spotlight_links_v3.json"
NEEDED = ("indicators", "links", "notRecommended", "guardrails")


def check(data: dict) -> None:
    """Stop on a file that isn't the links file, or whose links name an indicator it doesn't list."""
    missing = [k for k in NEEDED if k not in data]
    if missing:
        sys.exit(f"not a SPOTlight links file: missing {', '.join(missing)}")
    indicators = {i["id"] for i in data["indicators"]}
    for link in data["links"]:
        unknown = set(link["indicators"]) - indicators
        if unknown:
            sys.exit(f"link {link['id']} names unknown indicators {sorted(unknown)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    check(data)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(data['indicators'])} indicators, {len(data['links'])} recommended links "
          f"(codebook {data.get('codebookVersion', '?')}, reviewed {data.get('reviewedOn', '?')})")
