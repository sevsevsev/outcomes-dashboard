"""
Schools and the partner programs that serve them.

Data layer for the "Partners at a school" page. Like outcomes_data.py it makes
no Streamlit calls.

Two district tables feed it, both kept out of git like every partner file:

* The program-to-school relationship table (the partnerships database's
  "Program Schools" export): one row per program per school per fiscal year,
  keyed by PARTNER ID, PROGRAM ID and EOS CODE (the school's ULCS code).
* The schools table (Schools.xlsx): ULCS code, school name, level, learning
  network, zip code and City Council district.

Coded outcomes join to the relationship table on the district partner and
program IDs, never on names. A coded file carries them in `partner_id` and
`program_id` columns (district program files, and logic-model files once the
IDs are added to the coder input), in `program_key` ("54_32"), or in the logic
model's file name ("... - 54_32 - Org - Program - Logic Model.pdf").

Not every program at a school has coded outcomes, so every function here keeps
the uncoded ones: a school's portfolio lists all its partners, and says which
of them the outcome picture covers.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import IO, Iterable, Optional, Union

import pandas as pd

from outcomes_data import (
    APP_DIR,
    COL_DOMAIN,
    COL_ORG,
    COL_OUTCOME,
    COL_PARTNER_ID,
    COL_PRIORITY,
    COL_SUBCAT,
    COL_TEXT,
    UNCODED_DOMAIN,
    UNCODED_PRIORITY,
    UNKNOWN_ORG,
    _plural,
    domain_order,
    sample_outcome_texts,
    subcategory_sort_key,
)

# --- Columns in the district exports (matched case-insensitively) ------------
REL_PARTNER = "PARTNER ID"
REL_PROGRAM = "PROGRAM ID"
REL_SCHOOL = "EOS CODE"          # the school's ULCS code
REL_YEAR = "FISCAL YEAR ID"      # 20252026
REL_DELETE = "DELETE"            # flagged for deletion in the database
REL_PARTNER_NAME = "PARTNER NAME"   # optional: used when a future export carries names
REL_PROGRAM_NAME = "PROGRAM NAME"
SCHOOL_CODE = "ULCS"
SCHOOL_NAME = "PUBLICATION NAME"
SCHOOL_LEVEL = "SCHOOL LEVEL"
SCHOOL_NETWORK = "LEARNING NETWORK SHORT"
SCHOOL_NETWORK_NAME = "LEARNING NETWORK"
SCHOOL_ZIP = "ZIP CODE"
SCHOOL_COUNCIL = "CITY COUNCIL DISTRICT"
SCHOOL_SHEET = "schools"         # Schools.xlsx has other sheets; this one lists every school

# --- Tidy column names ----------------------------------------------------------
COL_PROGRAM_ID = "program_id"
COL_ULCS = "ulcs"
COL_YEAR = "fiscal_year"
COL_SCHOOL = "school"
COL_LEVEL = "level"
COL_NETWORK = "network"
COL_NETWORK_NAME = "network_name"   # "Learning Network 5"
COL_ZIP = "zip"                     # "19104"
COL_COUNCIL = "council_district"    # "5"
COL_PARTNER = "partner"          # a readable partner name: the coded data's, else "Partner 170"
COL_PARTNER_NAME = "partner_name"
COL_PROGRAM_NAME = "program_name"

RELATIONSHIPS = "relationships"
SCHOOLS = "schools"

# What a partner's row says about its coded outcomes at one school.
CODED = "Coded"
PARTLY_CODED = "Partly coded"
NOT_CODED = "Not yet coded"
STATUS_ORDER = [CODED, PARTLY_CODED, NOT_CODED]

PROGRAM_KEY = "program_key"
KEY_PATTERN = re.compile(r"^\s*(\d+)_(\d+)\s*$")
FILE_KEY_PATTERN = re.compile(r"(?:^|\s-\s)\s*(\d+)_(\d+)\s+-\s")
FILE_ORG_PATTERN = re.compile(r"(?:^|\s-\s)\s*\d+_\d+\s+-\s+(.+?)\s+-\s")

LOCAL_DIR = APP_DIR / "data"


class NotASchoolTableError(ValueError):
    """Raised when an uploaded file is neither the relationship table nor the schools table."""


# =============================================================================
# READING
# =============================================================================


def _upper_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns=lambda c: re.sub(r"\s+", " ", str(c)).strip().upper())


def table_kind(df: pd.DataFrame) -> Optional[str]:
    """RELATIONSHIPS, SCHOOLS or None, from a table's column names."""
    cols = set(_upper_columns(df.head(0)).columns)
    if {REL_PARTNER, REL_PROGRAM, REL_SCHOOL} <= cols:
        return RELATIONSHIPS
    if {SCHOOL_CODE, SCHOOL_NAME} <= cols:
        return SCHOOLS
    return None


def read_table(source: Union[str, Path, IO[bytes]], name: str = "") -> tuple[str, pd.DataFrame]:
    """Read an .xlsx or .csv file and return (kind, tidy table).

    Workbooks may hold several sheets; the first that looks like one of the
    two tables wins (Schools.xlsx keeps its list on the "schools" sheet).
    """
    name = name or str(source)
    if name.lower().endswith((".xlsx", ".xlsm", ".xls")):
        sheets = pd.read_excel(source, sheet_name=None)
        ordered = sorted(sheets.items(), key=lambda item: item[0].strip().lower() != SCHOOL_SHEET)
        candidates = [frame for _, frame in ordered]
    else:
        candidates = [pd.read_csv(source, dtype=str)]
    for frame in candidates:
        kind = table_kind(frame)
        if kind == RELATIONSHIPS:
            return kind, tidy_relationships(frame)
        if kind == SCHOOLS:
            return kind, tidy_schools(frame)
    raise NotASchoolTableError(
        f"{Path(name).name} has neither the program-to-school columns ({REL_PARTNER}, {REL_PROGRAM}, "
        f"{REL_SCHOOL}) nor the schools columns ({SCHOOL_CODE}, {SCHOOL_NAME.title()})."
    )


def read_table_bytes(data: bytes, name: str) -> tuple[str, pd.DataFrame]:
    return read_table(io.BytesIO(data), name)


def _id_text(series: pd.Series) -> pd.Series:
    """IDs as plain digit strings ("54", not "54.0"), so district and coded IDs compare equal."""
    numbers = pd.to_numeric(series, errors="coerce")
    return numbers.map(lambda v: str(int(v)) if pd.notna(v) else pd.NA).astype("string")


def tidy_relationships(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per program and school: partner_id, program_id, ulcs, fiscal_year (+ names if given).

    Rows flagged in DELETE are dropped. When the export spans several fiscal
    years, only the latest is kept, so a school shows its current partners.
    """
    df = _upper_columns(raw)
    if REL_DELETE in df.columns:
        flag = df[REL_DELETE].astype("string").str.strip().str.lower()
        df = df[flag.isna() | flag.isin(["", "0", "0.0", "n", "no", "false"])]
    out = pd.DataFrame({
        COL_PARTNER_ID: _id_text(df[REL_PARTNER]),
        COL_PROGRAM_ID: _id_text(df[REL_PROGRAM]),
        COL_ULCS: _id_text(df[REL_SCHOOL]),
        COL_YEAR: _id_text(df[REL_YEAR]) if REL_YEAR in df.columns else pd.Series(pd.NA, index=df.index,
                                                                                  dtype="string"),
    })
    for source, target in ((REL_PARTNER_NAME, COL_PARTNER_NAME), (REL_PROGRAM_NAME, COL_PROGRAM_NAME)):
        if source in df.columns:
            out[target] = df[source].astype("string").str.strip()
    out = out.dropna(subset=[COL_PARTNER_ID, COL_PROGRAM_ID, COL_ULCS])
    if out[COL_YEAR].notna().any():
        out = out[out[COL_YEAR] == out[COL_YEAR].max()]
    return out.drop_duplicates([COL_PROGRAM_ID, COL_ULCS]).reset_index(drop=True)


def tidy_schools(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per school: ulcs, school, level, network, network_name, zip, council_district.

    Columns the file lacks are left empty; zip codes keep their first five digits.
    """
    df = _upper_columns(raw)
    out = pd.DataFrame({
        COL_ULCS: _id_text(df[SCHOOL_CODE]),
        COL_SCHOOL: df[SCHOOL_NAME].astype("string").str.strip(),
    })
    for source, target in ((SCHOOL_LEVEL, COL_LEVEL), (SCHOOL_NETWORK, COL_NETWORK),
                           (SCHOOL_NETWORK_NAME, COL_NETWORK_NAME)):
        out[target] = df[source].astype("string").str.strip() if source in df.columns else pd.NA
    out[COL_NETWORK_NAME] = out[COL_NETWORK_NAME].fillna(out[COL_NETWORK])
    out[COL_ZIP] = (_id_text(df[SCHOOL_ZIP]).str.zfill(5).str[:5] if SCHOOL_ZIP in df.columns
                    else pd.Series(pd.NA, index=df.index, dtype="string"))
    out[COL_COUNCIL] = (_id_text(df[SCHOOL_COUNCIL]) if SCHOOL_COUNCIL in df.columns
                        else pd.Series(pd.NA, index=df.index, dtype="string"))
    return out.dropna(subset=[COL_ULCS]).drop_duplicates(COL_ULCS).reset_index(drop=True)


def find_local_tables(folder: Path = LOCAL_DIR) -> dict[str, Path]:
    """The relationship and schools tables in data/, found by their columns, newest file first."""
    found: dict[str, Path] = {}
    if not folder.is_dir():
        return found
    files = [p for p in folder.iterdir() if p.suffix.lower() in (".xlsx", ".csv") and not p.name.startswith("~$")]
    for path in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            if path.suffix.lower() == ".csv":
                kind = table_kind(pd.read_csv(path, nrows=0))
            else:
                sheets = pd.read_excel(path, sheet_name=None, nrows=0)
                kinds = {table_kind(frame) for frame in sheets.values()} - {None}
                kind = next(iter(sorted(kinds)), None)
        except (ValueError, OSError, pd.errors.ParserError, UnicodeDecodeError):
            continue
        if kind and kind not in found:
            found[kind] = path
    return found


def fiscal_year_label(year: object) -> str:
    """ "20252026" -> "2025-26" """
    text = str(year) if year is not None and not pd.isna(year) else ""
    return f"{text[:4]}-{text[6:]}" if len(text) == 8 and text.isdigit() else text


# =============================================================================
# JOINING CODED OUTCOMES TO DISTRICT IDS
# =============================================================================


def outcome_program_ids(df: pd.DataFrame) -> pd.DataFrame:
    """The district (partner_id, program_id) of each coded outcome row, aligned with df's index.

    Uses, in order: partner_id and program_id columns, a "54_32" program_key,
    then the "54_32" in the logic model's file name. Rows with neither stay
    empty: they are coded but cannot be placed at a school.
    """
    ids = pd.DataFrame({COL_PARTNER_ID: pd.Series(pd.NA, index=df.index, dtype="string"),
                        COL_PROGRAM_ID: pd.Series(pd.NA, index=df.index, dtype="string")})
    if COL_PARTNER_ID in df.columns and COL_PROGRAM_ID in df.columns:
        ids[COL_PARTNER_ID] = _id_text(df[COL_PARTNER_ID])
        ids[COL_PROGRAM_ID] = _id_text(df[COL_PROGRAM_ID])
    for column, pattern in ((PROGRAM_KEY, KEY_PATTERN), ("source_filename", FILE_KEY_PATTERN)):
        missing = ids[COL_PROGRAM_ID].isna()
        if not missing.any() or column not in df.columns:
            continue
        parts = df.loc[missing, column].astype("string").str.extract(pattern)
        ids.loc[missing, COL_PARTNER_ID] = parts[0].astype("string")
        ids.loc[missing, COL_PROGRAM_ID] = parts[1].astype("string")
    return ids


def with_program_ids(df: pd.DataFrame) -> pd.DataFrame:
    """df with its district partner_id and program_id filled in where they can be found."""
    ids = outcome_program_ids(df)
    return df.assign(**{COL_PARTNER_ID: ids[COL_PARTNER_ID], COL_PROGRAM_ID: ids[COL_PROGRAM_ID]})


def partner_names(outcomes: pd.DataFrame, relationships: Optional[pd.DataFrame] = None) -> dict[str, str]:
    """A readable name for each partner ID: the relationship table's own name if it has one, else the
    most common organization name in the coded data. Partners with neither are left out."""
    names: dict[str, str] = {}
    coded = outcomes.dropna(subset=[COL_PARTNER_ID])
    org = coded[COL_ORG].mask(coded[COL_ORG].isin([UNKNOWN_ORG]) | coded[COL_ORG].str.match(r"^Partner \d+$", na=False))
    if "source_filename" in coded.columns:
        # Some exports leave the organization blank; the logic model's file name still has it.
        org = org.fillna(coded["source_filename"].astype("string").str.extract(FILE_ORG_PATTERN)[0])
    for partner, orgs in org.dropna().groupby(coded[COL_PARTNER_ID]):
        names[str(partner)] = orgs.value_counts().index[0]
    if relationships is not None and COL_PARTNER_NAME in relationships.columns:
        given = relationships.dropna(subset=[COL_PARTNER_NAME]).drop_duplicates(COL_PARTNER_ID)
        names.update(dict(zip(given[COL_PARTNER_ID], given[COL_PARTNER_NAME])))
    return names


def join_summary(outcomes: pd.DataFrame, relationships: pd.DataFrame) -> dict[str, int]:
    """How the coded programs line up with the relationship table.

    programs: distinct coded programs; with_ids: those carrying district IDs;
    matched: those found in the relationship table; schools: schools where at
    least one matched program runs.
    """
    ids = outcomes[[COL_PARTNER_ID, COL_PROGRAM_ID]]
    if PROGRAM_KEY in outcomes.columns:
        program = outcomes[PROGRAM_KEY].astype(str)
    else:
        program = outcomes[COL_ORG].astype(str) + "|" + outcomes.get("program", outcomes[COL_TEXT]).astype(str)
    per_program = outcomes.assign(_name=program)
    with_ids = ids.dropna().drop_duplicates()
    without = per_program[ids[COL_PROGRAM_ID].isna()]["_name"].nunique()
    pairs = set(zip(relationships[COL_PARTNER_ID], relationships[COL_PROGRAM_ID]))
    matched = [pair for pair in zip(with_ids[COL_PARTNER_ID], with_ids[COL_PROGRAM_ID]) if pair in pairs]
    rel = relationships[[(a, b) in set(matched) for a, b in zip(relationships[COL_PARTNER_ID],
                                                                relationships[COL_PROGRAM_ID])]]
    return {"programs": len(with_ids) + without, "with_ids": len(with_ids), "matched": len(matched),
            "schools": rel[COL_ULCS].nunique()}


# =============================================================================
# ONE SCHOOL
# =============================================================================


def school_options(relationships: pd.DataFrame, schools: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Every school in either table: ulcs, school, level, programs, sorted by name.

    A ULCS code the schools table doesn't know is named "School 3040".
    """
    counts = relationships.groupby(COL_ULCS)[COL_PROGRAM_ID].nunique().rename("programs")
    base = schools if schools is not None else pd.DataFrame(columns=[COL_ULCS, COL_SCHOOL, COL_LEVEL])
    codes = pd.Index(base[COL_ULCS]).union(counts.index)
    out = pd.DataFrame({COL_ULCS: codes.astype(str)}).merge(base, on=COL_ULCS, how="left")
    out[COL_SCHOOL] = out[COL_SCHOOL].fillna("School " + out[COL_ULCS])
    out["programs"] = out[COL_ULCS].map(counts).fillna(0).astype(int)
    return out.sort_values(COL_SCHOOL, key=lambda s: s.str.casefold()).reset_index(drop=True)


def partner_label_map(programs: pd.DataFrame, names: dict[str, str]) -> dict[str, str]:
    """partner_id -> label: the partner's name, or "Partner 170"; two partners with one name get their IDs."""
    labels = {p: names.get(p, f"Partner {p}") for p in programs[COL_PARTNER_ID].unique()}
    counts = pd.Series(list(labels.values())).value_counts()
    return {p: (f"{label} ({p})" if counts[label] > 1 else label) for p, label in labels.items()}


def school_portfolio(relationships: pd.DataFrame, ulcs: str, outcomes: pd.DataFrame) -> pd.DataFrame:
    """One row per partner at the school, coded ones first.

    `outcomes` is the full coded data (with program IDs), not a filtered view:
    whether a program is coded must not change with the filters.
    Columns: partner_id, partner, programs_here, coded_programs, outcomes,
    status, program_ids, program_names.
    """
    here = relationships[relationships[COL_ULCS] == str(ulcs)]
    columns = [COL_PARTNER_ID, COL_PARTNER, "programs_here", "coded_programs", "outcomes", "status",
               "program_ids", "program_names"]
    if here.empty:
        return pd.DataFrame(columns=columns)
    coded = outcomes.dropna(subset=[COL_PROGRAM_ID])
    per_program = coded.groupby([COL_PARTNER_ID, COL_PROGRAM_ID]).size()
    program_names = (coded.dropna(subset=["program"]).groupby([COL_PARTNER_ID, COL_PROGRAM_ID])["program"].first()
                     if "program" in coded.columns else pd.Series(dtype="string"))
    labels = partner_label_map(here, partner_names(outcomes, relationships))

    rows = []
    for partner, programs in here.groupby(COL_PARTNER_ID):
        keys = list(zip(programs[COL_PARTNER_ID], programs[COL_PROGRAM_ID]))
        counts = [int(per_program.get(k, 0)) for k in keys]
        n_coded = sum(c > 0 for c in counts)
        names = []
        for (key, row) in zip(keys, programs.itertuples(index=False)):
            name = program_names.get(key) if len(program_names) else None
            given = getattr(row, COL_PROGRAM_NAME, None) if COL_PROGRAM_NAME in programs.columns else None
            names.append(str(name or given or f"program {key[1]}"))
        rows.append({
            COL_PARTNER_ID: partner,
            COL_PARTNER: labels[partner],
            "programs_here": len(keys),
            "coded_programs": n_coded,
            "outcomes": sum(counts),
            "status": CODED if n_coded == len(keys) else (PARTLY_CODED if n_coded else NOT_CODED),
            "program_ids": "; ".join(k[1] for k in keys),
            "program_names": "; ".join(names),
        })
    out = pd.DataFrame(rows, columns=columns)
    out["_status"] = out["status"].map(STATUS_ORDER.index)
    out["_name"] = out[COL_PARTNER].str.casefold()
    return out.sort_values(["_status", "_name"]).drop(columns=["_status", "_name"]).reset_index(drop=True)


def school_outcomes(outcomes: pd.DataFrame, relationships: pd.DataFrame, ulcs: str,
                    labels: dict[str, str]) -> pd.DataFrame:
    """The coded outcome rows of the programs at this school, with a `partner` label column."""
    here = relationships.loc[relationships[COL_ULCS] == str(ulcs), [COL_PARTNER_ID, COL_PROGRAM_ID]]
    pairs = set(zip(here[COL_PARTNER_ID], here[COL_PROGRAM_ID]))
    keep = [(a, b) in pairs for a, b in zip(outcomes[COL_PARTNER_ID], outcomes[COL_PROGRAM_ID])]
    rows = outcomes[keep]
    return rows.assign(**{COL_PARTNER: rows[COL_PARTNER_ID].map(labels)})


def partner_flows(rows: pd.DataFrame, domain: Optional[str] = None) -> pd.DataFrame:
    """Outcome statements from each partner to each domain (or, with `domain`, to its goals).

    Same columns as outcomes_data.program_flows, so charts.build_program_dots
    can draw it: source (partner), target, outcomes, samples.
    """
    if domain is not None:
        rows = rows[rows[COL_DOMAIN] == domain]
    target = COL_SUBCAT if domain is not None else COL_DOMAIN
    if rows.empty:
        return pd.DataFrame(columns=["source", "target", "outcomes", "samples"])
    flows = (
        rows.groupby([COL_PARTNER, target], observed=True)
        .agg(outcomes=(COL_TEXT, "size"), samples=(COL_OUTCOME, sample_outcome_texts))
        .reset_index()
        .rename(columns={COL_PARTNER: "source", target: "target"})
    )
    if domain is None:
        order = {d: i for i, d in enumerate(domain_order(rows))}
        flows["_order"] = flows["target"].map(order)
    else:
        flows["_order"] = flows["target"].map(subcategory_sort_key)
    return flows.sort_values(["_order", "source"]).drop(columns="_order").reset_index(drop=True)


def _listed(names: Iterable[str]) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def school_findings(school: str, portfolio: pd.DataFrame, rows: pd.DataFrame, year: str = "") -> list[str]:
    """Two or three sentences: who is at the school, how many the outcome picture covers, and the common aim."""
    n = len(portfolio)
    if n == 0:
        return [f"No partner programs are recorded at **{school}**{' for ' + year if year else ''}."]
    n_programs = int(portfolio["programs_here"].sum())
    coded = portfolio[portfolio["status"] != NOT_CODED]
    k = len(coded)
    found = [f"**{_plural(n, 'partner')}** run **{_plural(n_programs, 'program')}** at {school}"
             f"{' in ' + year if year else ''}."]
    if k == 0:
        found.append("None of them has coded outcomes yet, so there is nothing to chart. "
                     "They are listed below as not yet coded.")
        return found
    partly = int((coded["status"] == PARTLY_CODED).sum())
    sentence = (f"**{k} of {n}** have coded outcomes, so the picture below covers "
                f"{'them' if k > 1 else 'that partner'}"
                + (f"; the other **{n - k}** {'is' if n - k == 1 else 'are'} listed as not yet coded."
                   if k < n else "."))
    if partly:
        sentence = sentence[:-1] + (f" ({partly} of the coded {'partner runs' if partly == 1 else 'partners run'} "
                                    "other programs here that are not coded yet).")
    found.append(sentence)

    aims = rows[(rows[COL_DOMAIN] != UNCODED_DOMAIN) & (rows[COL_PRIORITY] != UNCODED_PRIORITY)]
    if not aims.empty:
        per_aim = aims.groupby(COL_PRIORITY)[COL_PARTNER].nunique().sort_values(ascending=False, kind="stable")
        top = per_aim[per_aim == per_aim.iloc[0]].index.tolist()[:3]
        count = int(per_aim.iloc[0])
        found.append(f"The most common aim among them is **{_listed(top)}**: **{count} of {k}** coded "
                     f"{'partner names' if count == 1 else 'partners name'} at least one outcome in "
                     f"{'it' if len(top) == 1 else 'each'}.")
    return found


# =============================================================================
# PLACE FILTERS (zip code, council district, learning network, school)
# =============================================================================

PLACE_COLUMNS = (COL_ZIP, COL_COUNCIL, COL_NETWORK_NAME)


def number_order(value: object) -> tuple:
    """Sorts "Learning Network 10" after "Learning Network 9", and "District 2" before "District 10"."""
    text = str(value)
    digits = re.findall(r"\d+", text)
    return (re.sub(r"\d+", "", text), int(digits[0]) if digits else -1, text)


def place_values(schools_table: Optional[pd.DataFrame], relationships: pd.DataFrame, column: str) -> list[str]:
    """The values of one place column among schools that host at least one program, in natural order."""
    if schools_table is None or column not in schools_table.columns:
        return []
    hosting = schools_table[schools_table[COL_ULCS].isin(set(relationships[COL_ULCS]))]
    return sorted(hosting[column].dropna().unique().tolist(), key=number_order)


def matching_schools(schools_table: Optional[pd.DataFrame], relationships: pd.DataFrame,
                     places: Optional[dict[str, Iterable[str]]] = None,
                     school_codes: Optional[Iterable[str]] = None) -> set[str]:
    """ULCS codes of the schools that match every place choice (any value within one choice).

    `places` maps a place column (zip, council_district, network_name) to the
    chosen values; empty choices are ignored. Picked schools narrow the result further.
    """
    codes = set(relationships[COL_ULCS])
    if schools_table is not None:
        table = schools_table
        for column, values in (places or {}).items():
            values = set(values or [])
            if values and column in table.columns:
                table = table[table[column].isin(values)]
        if any(values for values in (places or {}).values()):
            codes &= set(table[COL_ULCS])
    if school_codes:
        codes &= {str(c) for c in school_codes}
    return codes


def at_schools(outcomes: pd.DataFrame, relationships: pd.DataFrame, codes: Iterable[str]) -> pd.Series:
    """True for the outcome rows whose program runs at one of these schools.

    `outcomes` needs partner_id and program_id (see with_program_ids); rows
    without them can't be placed at any school, so they are always False.
    """
    here = relationships[relationships[COL_ULCS].isin(set(codes))]
    pairs = set(zip(here[COL_PARTNER_ID], here[COL_PROGRAM_ID]))
    return pd.Series([(a, b) in pairs for a, b in zip(outcomes[COL_PARTNER_ID], outcomes[COL_PROGRAM_ID])],
                     index=outcomes.index)
