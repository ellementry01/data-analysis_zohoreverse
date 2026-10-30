"""
Turns the Blinkit and Instamart "all months" workbooks into one file per month in the exact layout of their
loader contracts, so the normal loader can check and load them.

    python -m loader.normalise_platform_sales <workbook.xlsx> BLINKIT_SALES|INSTAMART_SALES <out_dir> [--log LOG.tsv]

What it changes, and nothing else:
  * header names, through the explicit alias table below (e.g. 'Elle sku' / 'SKU ID' -> 'ELLE SKU');
  * dates, written as ISO text YYYY-MM-DD (the sheets mix '2 July 2025', real dates, Excel serials and ISO text);
  * columns the contract does not have are dropped: payout / commission columns and personal data
    (customer name, buyer GST name and number) are never written;
  * Instamart sheets exported without a header row get the contract header ONLY after checking that the sheet has
    the standard column count and that every column holds what that position holds in the labelled months;
  * a missing SKU is filled from the platform item id ONLY where the labelled months map that id to exactly one SKU.
Every other cell is copied as it is. A sheet whose layout is not recognised is refused, never guessed.
Each output file and every change applied is written to the log, next to the original workbook it came from.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook

HERE = Path(__file__).parent


class LayoutError(ValueError):
    pass


def contract_headers(source: str) -> tuple[list[str], str, bool]:
    c = json.loads((HERE / "contracts" / f"{source}.json").read_text(encoding="utf-8"))
    counter = any(u.get("rule") == "row_counter" for u in c.get("unnamed_columns", []))
    return [x["header"] for x in c["columns"]], c["sheet"]["name"], counter


# header as found in a monthly sheet -> contract header (exact strings, after trimming)
ALIASES = {
    "BLINKIT_SALES": {
        "Order ID": "Order Id", "Item ID": "Item Id",
        "Elle SKU": "ELLE SKU", "Elle sku": "ELLE SKU", "elle sku": "ELLE SKU", "SKU": "ELLE SKU", "SKU ID": "ELLE SKU",
        "IGST %": "IGST(%)", "CGST %": "CGST(%)", "SGST %": "SGST(%)", "CESS %": "CESS(%)",
        "State GST": "Supply State GST",
    },
    "INSTAMART_SALES": {"elle sku": "Elle SKU", "SKU ID": "Elle SKU"},
}
# columns that may be present and are deliberately not loaded (never personal data in the output)
DROPPED = {
    "BLINKIT_SALES": {"S.No.", "Order Type", "Customer Name", "GST Name (where buyer has given gst)",
                      "GST Number (where buyer has given gst)", "IRN", "L0 Category", "L1 Category", "L2 Category",
                      "Commission %", "Commission Charge (Rs)", "Commission GST (Rs)", "Shipping Charge (Rs)",
                      "Shipping GST (Rs)", "TCS Amount", "TDS 1940 Amount", "TDS 194O Amount", "TDS 194Q Amount",
                      "Net Deductions", "Net Additions", "Item Level Payout", "Bank UTR", "Settlement Date",
                      "Settlement Status", "Unsettled Amount", "Expansion Level"},
    "INSTAMART_SALES": set(),
}
DATE_HEADER = {"BLINKIT_SALES": "Order Date", "INSTAMART_SALES": "ORDERED_DATE"}
SKU_HEADER = {"BLINKIT_SALES": "ELLE SKU", "INSTAMART_SALES": "Elle SKU"}
ITEM_HEADER = {"BLINKIT_SALES": "Item Id", "INSTAMART_SALES": "ITEM_CODE"}
QTY_HEADER = {"BLINKIT_SALES": "Quantity", "INSTAMART_SALES": "UNITS_SOLD"}
SKU_PATTERN = re.compile(r"^[A-Z]{4,6}\d{3,5}[A-Z0-9-]*$")
_TEXT_DATE = re.compile(r"^(\d{1,2}) ([A-Za-z]+) (\d{4})$")


def to_iso_date(v) -> str | None:
    """Every date encoding found in the platform sheets -> 'YYYY-MM-DD'. Anything else: LayoutError."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 30000 < v < 60000:      # Excel serial day
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$", s)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    m = _TEXT_DATE.match(s)
    if m:
        return dt.datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%d %B %Y").date().isoformat()
    raise LayoutError(f"unrecognised date value {s!r}")


def _rows(ws) -> list[list]:
    return [list(r) for r in ws.iter_rows(values_only=True) if r and any(v is not None and str(v).strip() != "" for v in r)]


def _clean(h) -> str | None:
    return None if h is None or str(h).strip() == "" else str(h).strip()


def map_header(source: str, header: list, expected: list[str]) -> tuple[dict[int, str], list[str]]:
    """Positions -> contract header. Returns the mapping and the notes on what was renamed / dropped."""
    aliases, dropped, mapping, notes = ALIASES[source], DROPPED[source], {}, []
    for i, raw in enumerate(header):
        h = _clean(raw)
        if h is None:
            continue
        target = h if h in expected else aliases.get(h)
        if target is None:
            if h in dropped:
                notes.append(f"dropped '{h}'")
                continue
            raise LayoutError(f"unexpected column {h!r}")
        if target in mapping.values():
            if target == ITEM_HEADER[source]:              # Instamart July 2025 repeats ITEM_CODE: keep the first
                notes.append(f"dropped repeated '{h}' at column {i + 1}")
                continue
            raise LayoutError(f"two columns map to {target!r}")
        if target != h:
            notes.append(f"renamed '{h}' -> '{target}'")
        mapping[i] = target
    return mapping, notes


def normalise_sheet(source: str, name: str, rows: list[list], reference: list[str] | None, item_to_sku: dict) -> tuple[list[dict], list[str]]:
    """One monthly sheet -> list of records keyed by contract header, plus the notes of what was changed."""
    expected, _, counter = contract_headers(source)
    header, data, notes = rows[0], rows[1:], []
    if all(_clean(h) is None or str(h).strip() not in expected + list(ALIASES[source]) + list(DROPPED[source])
           for h in header):
        # no header row: accepted only when the column positions match the labelled months exactly
        if reference is None or len(header) != len(reference) or not _positions_match(source, rows, reference):
            raise LayoutError(f"sheet {name!r} has no header row and its columns do not match the labelled months")
        header, data = reference, rows
        notes.append("header row missing: standard header assigned after a column-by-column check")
    if source == "INSTAMART_SALES" and _clean(header[0]) is None:
        header = [None] + list(header[1:])                       # leading unnamed row counter: regenerated below
    if source == "INSTAMART_SALES":                              # July 2025: SKU column exported without a name
        header = list(header)
        for i, h in enumerate(header):
            if i > 0 and _clean(h) is None and SKU_HEADER[source] not in [_clean(x) for x in header]:
                vals = [r[i] for r in data if i < len(r) and r[i] not in (None, "")]
                if vals and all(SKU_PATTERN.match(str(v).strip()) for v in vals):
                    header[i] = SKU_HEADER[source]
                    notes.append(f"unnamed column {i + 1} holds SKU codes only: named '{SKU_HEADER[source]}'")
    mapping, more = map_header(source, header, expected)
    notes += more
    out, stray = [], 0
    for r in data:
        rec = {h: None for h in expected}
        for i, h in mapping.items():
            rec[h] = r[i] if i < len(r) else None
        if all(rec[h] in (None, "") for h in (DATE_HEADER[source], QTY_HEADER[source], "Order Id", "STORE_ID") if h in rec):
            stray += 1                                           # a stray cell, no sale in it
            continue
        rec[DATE_HEADER[source]] = to_iso_date(rec[DATE_HEADER[source]])
        out.append(rec)
    if stray:
        notes.append(f"skipped {stray} row(s) with no date, order / store or quantity (stray cells)")
    if any(rec[DATE_HEADER[source]] is None for rec in out):
        raise LayoutError(f"sheet {name!r}: rows without a date")
    filled = 0
    for rec in out:                                              # SKU from the item id, only when unambiguous
        if rec[SKU_HEADER[source]] in (None, "") and rec[ITEM_HEADER[source]] not in (None, ""):
            skus = item_to_sku.get(str(rec[ITEM_HEADER[source]]).strip(), set())
            if len(skus) == 1:
                rec[SKU_HEADER[source]] = next(iter(skus)); filled += 1
    if filled:
        notes.append(f"{filled} SKU(s) filled from {ITEM_HEADER[source]} (one SKU for that id in the labelled months)")
    return out, notes


def _positions_match(source: str, rows: list[list], reference: list) -> bool:
    """Headerless sheet check: date column parses as a date, numeric columns are numbers, text columns are text."""
    idx = {(_clean(h) or ""): i for i, h in enumerate(reference)}
    for r in rows:
        try:
            to_iso_date(r[idx[DATE_HEADER[source]]])
        except (LayoutError, ValueError):
            return False
        for h in ("STORE_ID", "ITEM_CODE", "UNITS_SOLD", "GMV"):
            if h in idx and r[idx[h]] is not None and not isinstance(r[idx[h]], (int, float)):
                return False
        if "BRAND" in idx and not isinstance(r[idx["BRAND"]], str):
            return False
    return True


def normalise_workbook(path: Path, source: str) -> list[tuple[str, list[dict], list[str]]]:
    if source not in ALIASES:
        raise LayoutError(f"no normaliser for {source}")
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = [(ws.title, _rows(ws)) for ws in wb.worksheets]
    finally:
        wb.close()
    sheets = [(n, r) for n, r in sheets if r]
    expected = contract_headers(source)[0]
    # the labelled layout the headerless sheets must match, and the item id -> SKU map, from labelled sheets only
    reference, item_to_sku = None, defaultdict(set)
    for n, rows in sheets:
        hdr = [_clean(h) for h in rows[0]]
        if SKU_HEADER[source] in hdr and ITEM_HEADER[source] in hdr:
            if reference is None and source == "INSTAMART_SALES" and len(hdr) == len(expected) + 1:
                reference = rows[0]
            si, ii = hdr.index(SKU_HEADER[source]), hdr.index(ITEM_HEADER[source])
            for r in rows[1:]:
                if r[si] not in (None, "") and r[ii] not in (None, "") and SKU_PATTERN.match(str(r[si]).strip()):
                    item_to_sku[str(r[ii]).strip()].add(str(r[si]).strip())
        for alias, target in ALIASES[source].items():
            if target == SKU_HEADER[source] and alias in hdr and ITEM_HEADER[source] in hdr:
                si, ii = hdr.index(alias), hdr.index(ITEM_HEADER[source])
                for r in rows[1:]:
                    if r[si] not in (None, "") and r[ii] not in (None, "") and SKU_PATTERN.match(str(r[si]).strip()):
                        item_to_sku[str(r[ii]).strip()].add(str(r[si]).strip())
            elif target == SKU_HEADER[source] and alias in hdr and "Item ID" in hdr:
                si, ii = hdr.index(alias), hdr.index("Item ID")
                for r in rows[1:]:
                    if r[si] not in (None, "") and r[ii] not in (None, "") and SKU_PATTERN.match(str(r[si]).strip()):
                        item_to_sku[str(r[ii]).strip()].add(str(r[si]).strip())
    result = [(n, *normalise_sheet(source, n, rows, reference, item_to_sku)) for n, rows in sheets]
    return _drop_shifted_copies(source, result) if source == "INSTAMART_SALES" else result


def _drop_shifted_copies(source: str, result: list) -> list:
    """Instamart 'june' sheet (Oct 2026 workbook): 37 July orders pasted at its foot one column to the left (no SKU
    column), so 'No' sits in the SKU column, the MRP in COMBO_UNITS_SOLD and the selling value in UNITS_SOLD. Such a row
    is dropped only when the same order (date, store, item id, MRP) is in the workbook correctly laid out; otherwise the
    run stops: a shifted row is never repaired by guessing."""
    def shifted(r):
        return (str(r.get(SKU_HEADER[source]) or "").strip().lower() in ("no", "yes") and r.get("GMV") is None
                and isinstance(r.get("COMBO_UNITS_SOLD"), (int, float)))
    good = {(r[DATE_HEADER[source]], r["STORE_ID"], r[ITEM_HEADER[source]], r["BASE_MRP"])
            for _, recs, _ in result for r in recs if not shifted(r)}
    out = []
    for name, recs, notes in result:
        bad = [r for r in recs if shifted(r)]
        if bad:
            orphans = [r for r in bad if (r[DATE_HEADER[source]], r["STORE_ID"], r[ITEM_HEADER[source]], r["COMBO_UNITS_SOLD"]) not in good]
            if orphans:
                raise LayoutError(f"sheet {name!r}: {len(orphans)} row(s) shifted one column left with no correct copy elsewhere")
            recs = [r for r in recs if not shifted(r)]
            notes = notes + [f"dropped {len(bad)} row(s) pasted one column to the left; each is a copy of an order "
                             f"present correctly in another sheet"]
        out.append((name, recs, notes))
    return out


def write_month(source: str, records: list[dict], out_dir: Path) -> list[Path]:
    """One file per calendar month present in the records, in the contract layout."""
    expected, sheet, counter = contract_headers(source)
    by_month = defaultdict(list)
    for rec in records:
        by_month[rec[DATE_HEADER[source]][:7]].append(rec)
    paths = []
    for month, recs in sorted(by_month.items()):
        wb = Workbook(); ws = wb.active; ws.title = sheet
        ws.append(([None] if counter else []) + expected)
        for n, rec in enumerate(recs):          # row counter starts at 0, as Instamart exports it
            ws.append(([n] if counter else []) + [rec[h] for h in expected])
        p = out_dir / f"{source}__{month}.xlsx"
        wb.save(p); paths.append(p)
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m loader.normalise_platform_sales")
    ap.add_argument("workbook", type=Path); ap.add_argument("source"); ap.add_argument("out_dir", type=Path)
    ap.add_argument("--log", type=Path, help="append one line per sheet: workbook, sheet, rows, output, changes")
    a = ap.parse_args(argv)
    try:
        sheets = normalise_workbook(a.workbook, a.source)
    except LayoutError as e:
        print(f"REFUSED  {a.workbook.name}: {e}", file=sys.stderr); return 1
    a.out_dir.mkdir(parents=True, exist_ok=True)
    allrecs = [rec for _, recs, _ in sheets for rec in recs]
    paths = write_month(a.source, allrecs, a.out_dir)
    lines = [f"{a.workbook.name}\t{n}\t{len(recs)}\t{a.source}\t{'; '.join(notes) or 'copied as is'}" for n, recs, notes in sheets]
    if a.log:
        new = not a.log.exists()
        with open(a.log, "a", encoding="utf-8", newline="\n") as f:
            if new:
                f.write("workbook\tsheet\trows\tsource\tchanges\n")
            f.write("\n".join(lines) + "\n")
    for l in lines:
        print(l)
    print(f"wrote {len(paths)} monthly file(s), {len(allrecs)} rows -> {a.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
