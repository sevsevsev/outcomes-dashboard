"""Copy the Portrait of a Graduate skills list from the coder repo into reference/.

The coder repo (Qualitative-Outcomes-Coder) keeps the School District of
Philadelphia Portrait of a Graduate, version 11.2, as
codebook-refinement/portrait-of-a-graduate/portrait_skills_11.2.csv: one row
for each of the 14 competencies and each of the 69 skills, with the columns
id, type (competency or skill), group (the wheel slice), competency, name,
statement (the "I can" statement) and has_progression. The names and
statements are the District's own words.

The Portrait of a Graduate page reads the copy at
reference/portrait_skills_11.2.csv and takes every name and statement from
it word for word. The file is copied byte for byte, so the coder repo stays
its one source. Copy only from the coder's main branch, and run this again
whenever the coder updates the file:

    python scripts/build_portrait_reference.py ../Qualitative-Outcomes-Coder/codebook-refinement/portrait-of-a-graduate/portrait_skills_11.2.csv

The framework is the Portrait of a Graduate Competency Framework, written by
Building 21 for the School District of Philadelphia, licensed CC BY-NC-SA 4.0.
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "reference"
OUT = REFERENCE / "portrait_skills_11.2.csv"
COLUMNS = ["id", "type", "group", "competency", "name", "statement", "has_progression"]
GROUPS = {"Ethical and Creative Problem Solver", "Culturally Responsive Communicator",
          "Strong Community Builder and Collaborator", "Global Citizen", "Lifelong Learner", "Scholar"}


def check(text: str) -> tuple[int, int]:
    """Stop on a file that isn't the skills list; return (competencies, skills)."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or list(rows[0]) != COLUMNS:
        sys.exit(f"not the Portrait skills list: expected columns {', '.join(COLUMNS)}")
    competencies = {r["id"]: r for r in rows if r["type"] == "competency"}
    skills = [r for r in rows if r["type"] == "skill"]
    for row in rows:
        if row["type"] not in ("competency", "skill"):
            sys.exit(f"{row['id']} has an unknown type {row['type']!r}")
        if row["group"] not in GROUPS:
            sys.exit(f"{row['id']} names an unknown group {row['group']!r}")
        if not row["name"] or not row["statement"]:
            sys.exit(f"{row['id']} has no name or no statement")
    for skill in skills:
        parent = competencies.get(skill["competency"])
        if parent is None or not skill["id"].startswith(skill["competency"] + "."):
            sys.exit(f"skill {skill['id']} names an unknown competency {skill['competency']!r}")
        if parent["group"] != skill["group"]:
            sys.exit(f"skill {skill['id']} sits in a different group from its competency")
    if {c["group"] for c in competencies.values()} != GROUPS:
        sys.exit("the competencies do not cover all six groups")
    return len(competencies), len(skills)


def copy(path: str) -> None:
    text = Path(path).read_text(encoding="utf-8")
    competencies, skills = check(text)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}: {competencies} competencies and {skills} skills")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    copy(sys.argv[1])
