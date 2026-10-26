"""
Checks a workbook against its contract and turns it into raw records.

Everything here is a pure function of (file contents, contract): no database.
Any mismatch raises ContractError with a message that says exactly what differs.
Non-fatal observations come back as warnings and are recorded as DQ WARN rows.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .readers import is_empty_row

CONTRACT_DIR = Path(__file__).parent / "contracts"


class ContractError(Exception):
    """The file does not match its contract. Nothing is loaded."""


@dataclass
class Parsed:
    columns: list[str]                       # raw column names, in record order
    records: list[tuple]                     # (source_row_number, [source_col_number,] *values)
    rows_read: int
    period_start: dt.date | None = None
    period_end: dt.date | None = None
    as_of_in_file: dt.date | None = None
    warnings: list[tuple[str, str, int]] = field(default_factory=list)   # (check_name, details, failed_rows)


def load_contract(source: str) -> dict:
    p = CONTRACT_DIR / f"{source}.json"
    if not p.exists():
        known = sorted(x.stem for x in CONTRACT_DIR.glob("*.json"))
        raise ContractError(f"no contract for source '{source}'. Known sources: {', '.join(known)}")
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- sheets
def select_sheet(book: dict, contract: dict) -> str:
    sel, names = contract["sheet"], list(book)
    if "name" in sel:
        if sel["name"] not in book:
            raise ContractError(f"sheet '{sel['name']}' not found. Sheets in file: {names}")
        chosen = sel["name"]
    elif "pattern" in sel:
        hits = [n for n in names if re.match(sel["pattern"], n)]
        if len(hits) != 1:
            raise ContractError(f"expected exactly one sheet matching {sel['pattern']!r}, found {hits}. Sheets: {names}")
        chosen = hits[0]
    else:
        chosen = names[sel["index"]]
    if contract["other_sheets"] == "must_be_empty":
        for n in names:
            if n != chosen and any(not is_empty_row(r) for r in book[n]):
                raise ContractError(f"sheet '{n}' contains data but only '{chosen}' is loaded for this source. "
                                    "Data outside the loaded sheet would be silently lost.")
    return chosen


# --------------------------------------------------------------------------- dates
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?: \d{2}:\d{2}:\d{2})?$")
_DMY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_MDY_T = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?: \d{1,2}:\d{2}(?::\d{2})?)?$")


def parse_business_date(text: str | None, fmt: str) -> dt.date | None:
    """Used ONLY to record the period a file covers. Staging does the real, per-row parsing."""
    if text is None:
        return None
    t = text.strip()
    try:
        if fmt in ("excel_datetime", "text_ymd"):
            m = _ISO.match(t)
            return dt.date(int(m[1]), int(m[2]), int(m[3])) if m else None
        if fmt == "excel_datetime_or_text_dmy_repeated":
            m = _ISO.match(t)
            if m:                                   # a real Excel date cell
                return dt.date(int(m[1]), int(m[2]), int(m[3]))
            return parse_business_date(t, "text_dmy_repeated")
        if fmt == "text_dmy_repeated":
            parts = [p.strip() for p in t.split(";") if p.strip()]
            ms = [_DMY.match(p) for p in parts]
            if not ms or not all(ms):
                return None
            dates = {dt.date(int(m[3]), int(m[2]), int(m[1])) for m in ms}
            return dates.pop() if len(dates) == 1 else None
        if fmt == "text_mdy_time":
            m = _MDY_T.match(t)
            return dt.date(int(m[3]), int(m[1]), int(m[2])) if m else None
    except ValueError:            # e.g. 31/02/2026
        return None
    raise ContractError(f"unknown business date format '{fmt}' in contract")


def _period(values: list, fmt: str, header: str) -> tuple:
    dates, bad = [], 0
    for v in values:
        if v is None:
            continue
        d = parse_business_date(v, fmt)
        if d is None:
            bad += 1
        else:
            dates.append(d)
    if not dates:
        raise ContractError(f"no parseable business dates in column '{header}' (format {fmt})")
    warn = [("business_date_unparseable", f"{bad} non-empty value(s) in '{header}' did not parse as {fmt}; "
             "they are loaded unchanged and handled in staging", bad)] if bad else []
    return min(dates), max(dates), warn


# --------------------------------------------------------------------------- TABLE layout
def parse_table(rows: list[list], contract: dict) -> Parsed:
    hr = contract["header_row"] - 1
    if len(rows) <= hr:
        raise ContractError("file has no header row")
    header = rows[hr]
    unnamed = {u["position"]: u for u in contract.get("unnamed_columns", [])}
    expected = [c["header"] for c in contract["columns"]]

    for pos in unnamed:
        if pos >= len(header) or header[pos] is not None:
            raise ContractError(f"expected an unnamed column at position {pos + 1}, found {header[pos] if pos < len(header) else 'nothing'!r}")
    named = [(i, h) for i, h in enumerate(header) if i not in unnamed]

    if contract["column_match"] == "exact_set":
        width = len(header)
        while width > 0 and header[width - 1] is None and (width - 1) not in unnamed:
            width -= 1                                     # trailing empty header cells from Excel formatting
        stray = [i + 1 for i, h in named if h is None and i < width]
        if stray:
            raise ContractError(f"blank header at column position(s) {stray} not declared in the contract")
        present = [h for i, h in named if h is not None]
        dup = sorted({h for h in present if present.count(h) > 1})
        missing = [h for h in expected if h not in present]
        extra = [h for h in present if h not in expected]
        if dup or missing or extra:
            raise ContractError("columns differ from contract:"
                                + (f"\n  missing: {missing}" if missing else "")
                                + (f"\n  new / unexpected: {extra}" if extra else "")
                                + (f"\n  duplicated: {dup}" if dup else "")
                                + "\n  If the ERP export genuinely changed, update the contract deliberately (see README).")
        pos_of = {h: i for i, h in named if h is not None}
    else:  # leading: first N headers fixed, remainder ignored by design
        got = [h for _, h in named[:len(expected)]]
        if got != expected:
            raise ContractError(f"first columns must be {expected}, found {got}")
        width = None
        pos_of = {h: i for i, h in named[:len(expected)]}

    positions = [pos_of[h] for h in expected]
    records, rows_read, counter = [], 0, 0
    for r_idx in range(hr + 1, len(rows)):
        row = rows[r_idx]
        if is_empty_row(row):
            continue
        rows_read += 1
        if width is not None:
            beyond = [i + 1 for i in range(width, len(row)) if row[i] is not None and i not in unnamed]
            if beyond:
                raise ContractError(f"row {r_idx + 1} has values beyond the last header (column(s) {beyond[:5]})")
        for pos, rule in unnamed.items():
            v = row[pos] if pos < len(row) else None
            if rule["rule"] == "row_counter":
                if v != str(counter):
                    raise ContractError(f"unnamed column {pos + 1} expected row counter {counter} at row {r_idx + 1}, found {v!r}")
            elif rule["rule"] == "values_in":
                if v is not None and v not in rule["values"]:
                    raise ContractError(f"unnamed column {pos + 1} holds unexpected value {v!r} at row {r_idx + 1}; "
                                        f"only {rule['values']} are allowed to be dropped")
        counter += 1
        records.append((r_idx + 1, *[row[p] if p < len(row) else None for p in positions]))

    parsed = Parsed(columns=[c["column"] for c in contract["columns"]], records=records, rows_read=rows_read)
    bd = contract.get("business_date")
    if bd and records:
        i = expected.index(bd["header"]) + 1
        parsed.period_start, parsed.period_end, w = _period([r[i] for r in records], bd["format"], bd["header"])
        parsed.warnings += w
    if not records:
        raise ContractError("file has a header but no data rows")
    return parsed


# --------------------------------------------------------------------------- STOCK_PIVOT layout
def _num(v: str | None) -> float:
    if v is None or v.strip() == "":
        return 0.0
    try:
        return float(v.replace(",", ""))
    except ValueError:
        raise ContractError(f"non-numeric quantity {v!r} in stock report")


def parse_stock_pivot(rows: list[list], contract: dict) -> Parsed:
    def cell(r, c):
        return rows[r - 1][c - 1] if len(rows) >= r and len(rows[r - 1]) >= c else None

    t = contract["title_cell"]
    if cell(t["row"], t["col"]) != t["equals"]:
        raise ContractError(f"report title is {cell(t['row'], t['col'])!r}, expected {t['equals']!r}")
    a = contract["as_of_cell"]
    m = re.match(a["pattern"], (cell(a["row"], a["col"]) or "").strip())
    if not m:
        raise ContractError(f"report date {cell(a['row'], a['col'])!r} not in expected 'M/D/YYYY To M/D/YYYY' form")
    d_from = dt.date(int(m[3]), int(m[1]), int(m[2]))
    d_to = dt.date(int(m[6]), int(m[4]), int(m[5]))
    if d_from != d_to:
        raise ContractError(f"stock report covers {d_from}..{d_to}; a snapshot must be for a single day")

    hr = contract["header_row"] - 1
    header = rows[hr]
    prod = contract["product_columns"]
    pos = {}
    for pc in prod:
        hits = [i for i, h in enumerate(header) if h == pc["header"]]
        if len(hits) != 1:
            raise ContractError(f"expected header {pc['header']!r} exactly once in row {hr + 1}, found {len(hits)}")
        pos[pc["column"]] = hits[0]
    start = max(pos.values()) + 1
    mrp_h, total_h = contract["block_value_header"], contract["total_header"]

    blocks, total_col, current = [], None, None     # blocks: (location, qty_col, mrp_col)
    for j in range(start, len(header)):
        h = header[j]
        if h is None:
            continue
        if h == mrp_h:
            if current is None or current[2] is not None:
                raise ContractError(f"'{mrp_h}' at column {j + 1} does not follow a location header")
            current[2] = j
        elif h == total_h:
            total_col, current = j, None
        else:
            if current is not None and current[2] is None:
                raise ContractError(f"location '{current[0]}' has no '{mrp_h}' column")
            current = [h, j, None]
            blocks.append(current)
    if current is not None and current[2] is None:
        raise ContractError(f"location '{current[0]}' has no '{mrp_h}' column")
    if total_col is None:
        raise ContractError(f"no '{total_h}' column found")
    names = [b[0] for b in blocks]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ContractError(f"duplicate location columns: {dup}")

    warnings = []
    f = contract["channel_filter_cell"]
    filt = [x.strip() for x in (cell(f["row"], f["col"]) or "").split(",") if x.strip()]
    not_in_filter = [n for n in names if n not in filt]
    if not_in_filter:
        raise ContractError(f"location columns not in the report's channel filter: {not_in_filter}")
    absent = [x for x in filt if x not in names]
    if absent:
        warnings.append(("stock_report_locations_without_column",
                         f"{len(absent)} location(s) selected in the report filter have no column: {absent}", len(absent)))

    records, rows_read, mismatch = [], 0, []
    col_sums = {qc: 0.0 for _, qc, _ in blocks}
    col_sums[total_col] = 0.0
    footer_seen = False
    for r_idx in range(hr + 1, len(rows)):
        row = rows[r_idx]
        if is_empty_row(row):
            continue
        get = lambda c: row[c] if c < len(row) else None
        if footer_seen:
            raise ContractError(f"row {r_idx + 1} has content after the grand-total row (layout change)")
        if get(pos["prod_num"]) is None:
            if get(pos["unit"]) == total_h:          # grand-total footer: verify every location column, then skip
                footer_seen = True
                bad = [(loc, col_sums[qc], _num(get(qc))) for loc, qc, _ in blocks if abs(col_sums[qc] - _num(get(qc))) > 1e-6]
                if abs(col_sums[total_col] - _num(get(total_col))) > 1e-6:
                    bad.append((total_h, col_sums[total_col], _num(get(total_col))))
                if bad:
                    raise ContractError(f"column totals do not match the report's grand-total row: {bad[:5]} "
                                        "(rows missing or shifted); nothing loaded")
                continue
            raise ContractError(f"row {r_idx + 1} has content but no Prod Num (unexpected footer or layout change)")
        rows_read += 1
        pvals = [get(pos[pc["column"]]) for pc in prod]
        total = _num(get(total_col))
        s = 0.0
        for loc, qc, mc in blocks:
            q = get(qc)
            s += _num(q)
            col_sums[qc] += _num(q)
            records.append((r_idx + 1, qc + 1, *pvals, loc, q, get(mc)))
        col_sums[total_col] += total
        if abs(s - total) > 1e-6:
            mismatch.append(r_idx + 1)
    if mismatch:
        raise ContractError(f"{len(mismatch)} row(s) where the sum of location quantities != Total (first rows: {mismatch[:5]}). "
                            "The report layout may have changed; nothing loaded.")
    if not footer_seen:
        raise ContractError("stock report has no grand-total row; the export may be truncated")
    if not records:
        raise ContractError("stock report has no product rows")
    return Parsed(columns=[c["column"] for c in contract["columns"]], records=records, rows_read=rows_read,
                  as_of_in_file=d_to, warnings=warnings)


def parse(book: dict, contract: dict) -> tuple[str, Parsed]:
    sheet = select_sheet(book, contract)
    rows = book[sheet]
    parsed = parse_stock_pivot(rows, contract) if contract["layout"] == "STOCK_PIVOT" else parse_table(rows, contract)
    return sheet, parsed
