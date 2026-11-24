#!/usr/bin/env python3
"""List the coded programs that do not link to a school, and suggest district IDs for them.

    python scripts/check_program_ids.py --coded coded_outcomes_...csv \
        --relationships Schools_Partners_Relate.xlsx --out program_id_check.csv

The dashboard joins coded outcomes to schools on district partner and program
IDs only. This script is the review step for the programs that fail that join:
for each coded program it reports whether the IDs link, and why not if they
don't (the partner is not in the program-to-school table, the program runs at
no school this year, the program ID belongs to another partner, or the row
has no IDs). For those rows it lists the closest district partner and program
names as candidates.

Candidates are leads for a person to check, never answers: names that share
only common words ("Philadelphia", "Center", "Youth") are often different
organizations. Once a candidate is confirmed, record it as a row in
reference/program_id_fixes.csv and the dashboard uses it.

The relationship table must carry the PARTNER NAME and PROGRAM NAME columns
(Schools_Partners_Relate.xlsx does) for candidates to be listed.
"""

from __future__ import annotations

import argparse
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import outcomes_data as od  # noqa: E402
import schools  # noqa: E402

STOP = set("the of inc and for a an llc co corp corporation incorporated program programs "
           "philadelphia philly".split())
FLOOR = 0.45

LINKED = "Linked"
FIXED = "Linked by a reviewed fix"
CONFLICT = "Program ID belongs to another partner"
NOT_AT_SCHOOLS = "Program runs at no school in this table"
PARTNER_MISSING = "Partner not in this table"
NO_IDS = "No IDs in the export"


def norm(text: object) -> str:
    text = re.sub(r"\(.*?\)", " ", str(text).lower()).replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return " ".join(w for w in text.split() if w not in STOP)


def similarity(a: object, b: object) -> float:
    """String similarity from 0 to 1: the better of a character ratio and a word overlap."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    overlap = len(ta & tb)
    words = 0.5 * overlap / min(len(ta), len(tb)) + 0.5 * overlap / len(ta | tb)
    return round(max(SequenceMatcher(None, a, b).ratio(), words), 2)


def check(coded: pd.DataFrame, relationships: pd.DataFrame) -> pd.DataFrame:
    raw = schools.outcome_program_ids(coded)
    fixed = schools.apply_id_fixes(raw, coded)
    rows = coded.assign(file_partner_id=raw[od.COL_PARTNER_ID], file_program_id=raw[schools.COL_PROGRAM_ID],
                        partner_id=fixed[od.COL_PARTNER_ID], program_id=fixed[schools.COL_PROGRAM_ID])
    programs = (rows.groupby(["file_partner_id", "file_program_id", "partner_id", "program_id", od.COL_ORG,
                              od.COL_PROGRAM], dropna=False)
                .size().rename("outcome_rows").reset_index())

    rel = relationships.drop_duplicates(schools.COL_PROGRAM_ID)
    pairs = set(zip(rel[od.COL_PARTNER_ID], rel[schools.COL_PROGRAM_ID]))
    owner = dict(zip(rel[schools.COL_PROGRAM_ID], rel[od.COL_PARTNER_ID]))
    has_names = schools.COL_PARTNER_NAME in rel.columns and schools.COL_PROGRAM_NAME in rel.columns
    partner_name = (dict(zip(rel[od.COL_PARTNER_ID], rel[schools.COL_PARTNER_NAME])) if has_names else {})
    program_name = (dict(zip(rel[schools.COL_PROGRAM_ID], rel[schools.COL_PROGRAM_NAME])) if has_names else {})
    by_partner = rel.groupby(od.COL_PARTNER_ID)[schools.COL_PROGRAM_ID].apply(list).to_dict()

    out = []
    for row in programs.itertuples(index=False):
        pid, gid = row.partner_id, row.program_id
        if pd.notna(gid) and (pid, gid) in pairs:
            status = FIXED if (row.file_partner_id, row.file_program_id) != (pid, gid) else LINKED
        elif pd.isna(gid):
            status = NO_IDS
        elif gid in owner:
            status = CONFLICT
        elif pid in by_partner:
            status = NOT_AT_SCHOOLS
        else:
            status = PARTNER_MISSING
        candidates = []
        if status not in (LINKED, FIXED) and has_names:
            if gid in owner:
                candidates.append(f"program {gid} is {program_name[gid]} of partner {owner[gid]} "
                                  f"{partner_name[owner[gid]]}")
            partners = sorted(((similarity(row.organization, n), i, n) for i, n in partner_name.items()),
                              reverse=True)[:3]
            partners = [p for p in partners if p[0] >= FLOOR]
            if pd.notna(pid) and pid in partner_name and pid not in [p[1] for p in partners]:
                partners.insert(0, (similarity(row.organization, partner_name[pid]), pid, partner_name[pid]))
            for score, i, name in partners:
                candidates.append(f"partner {i} {name} ({score})")
                ranked = sorted(((similarity(row.program, program_name[g]), g) for g in by_partner.get(i, [])),
                                reverse=True)[:4]
                candidates += [f"  program {g} {program_name[g]} ({s})" for s, g in ranked]
        out.append({**row._asdict(), "status": status,
                    "district_partner_name": partner_name.get(pid, ""),
                    "district_program_name": program_name.get(gid, "") if (pid, gid) in pairs else "",
                    "candidates": "\n".join(candidates)})
    order = {s: n for n, s in enumerate([NO_IDS, CONFLICT, PARTNER_MISSING, NOT_AT_SCHOOLS, FIXED, LINKED])}
    return pd.DataFrame(out).sort_values(["status", od.COL_ORG], key=lambda c: c.map(order) if c.name == "status"
                                         else c.str.casefold()).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--coded", required=True, help="coded-outcomes export (.csv)")
    parser.add_argument("--relationships", required=True, help="program-to-school table (.xlsx or .csv)")
    parser.add_argument("--out", required=True, help="where to write the review list (.csv)")
    args = parser.parse_args()
    coded = od.clean_outcomes(pd.read_csv(args.coded, dtype=str))
    kind, relationships = schools.read_table(args.relationships)
    if kind != schools.RELATIONSHIPS:
        sys.exit(f"{args.relationships} is not the program-to-school table")
    result = check(coded, relationships)
    result.to_csv(args.out, index=False)
    linked = result["status"].isin([LINKED, FIXED])
    print(f"{int(linked.sum())} of {len(result)} coded programs link to a school "
          f"({int(result.loc[linked, 'outcome_rows'].sum())} of {int(result['outcome_rows'].sum())} outcome rows).")
    print(result["status"].value_counts().to_string())


if __name__ == "__main__":
    main()
