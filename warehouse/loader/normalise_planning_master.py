"""
Turns the team's reorder sheet ("SKU MASTER", saved from Excel as tab-separated text with an .xls name, e.g.
"12-11-26.xls") into one CSV in the SKU_PLANNING_MASTER contract layout: one row per product with the planning
fields the stock availability check needs (schema 2.18).

    python -m loader.normalise_planning_master <sheet.xls> <out.csv> [--log NORMALISE_LOG.tsv]

What changes, and nothing else:
  * only the planning columns are kept (product, list group, top 40, grade, platform flags, launch date, replacement
    product, factory, MOQ, MLT, PO pending, PO delivery date, warehouse stock); sales workings, prices, costs and
    margins are dropped;
  * columns are found by their header (row 2), so moved columns do not matter; a missing header stops the run;
  * the two date columns are rewritten from 03-05-2025 to 2025-05-03 (Excel's empty date 00-01-1900 becomes empty);
  * values are trimmed; values that are only spaces become empty.
A product code that appears twice, a date that cannot be read, or a file that is not the reorder sheet stops the run.
The sheet's date is not inside the file: load it with --as-of <date of the sheet>.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

# output header -> the sheet's header (compared trimmed, case and spacing ignored)
COLUMNS = [("SKU", "SKU"), ("Product Name", "PRODNAME"), ("List Group", "Discontinued product list"),
           ("Top 40", "top 40 sku"), ("Grade", "GRADE"), ("Amazon Now", "Amazon NOW SKU"), ("Instamart", "instamrart"),
           ("Launch Date", "Launch Date"), ("Replacement SKU", "New sku Replacement"), ("Factory", "FACTORY NAME"),
           ("MOQ", "MOQ"), ("MLT Days", "MLT"), ("PO Pending", "PO PENDING"), ("PO Delivery Date", "Po Delivery Date"),
           ("Warehouse Stock", "W.H INVENTORY")]
HEADERS = [c for c, _ in COLUMNS]
DATE_COLUMNS = ("Launch Date", "PO Delivery Date")
TITLE = "SKU MASTER"


class LayoutError(Exception):
    pass


def _key(h: str) -> str:
    return re.sub(r"\s+", " ", h).strip().lower()


def _iso(value: str, where: str) -> str:
    if value in ("", "00-01-1900", "0"):
        return ""
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise LayoutError(f"{where}: date '{value}' is not like 03-05-2025")


def read_sheet(path: Path) -> list[list[str]]:
    data = path.read_bytes()
    if data[:4] == b"\xd0\xcf\x11\xe0" or data[:2] == b"PK":
        raise LayoutError(f"{path.name}: a real Excel workbook; save the sheet as 'Text (Tab delimited)' first")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    rows = list(csv.reader(text.splitlines(), delimiter="\t"))
    if len(rows) < 3 or not rows[0] or not rows[0][0].strip().upper().startswith(TITLE):
        raise LayoutError(f"{path.name}: not the reorder sheet (row 1 should start with '{TITLE}')")
    header = [_key(h) for h in rows[1]]
    pos = {}
    for out, src in COLUMNS:
        if _key(src) not in header:
            raise LayoutError(f"{path.name}: column '{src}' not found in row 2")
        pos[out] = header.index(_key(src))                # first occurrence: the planning block is at the left
    return rows[2:], pos


def normalise(path: Path) -> tuple[list[list[str]], dict]:
    body, pos = read_sheet(path)
    out, seen, skipped = [], {}, 0
    for n, row in enumerate(body, start=3):
        vals = {c: (row[i].strip() if i < len(row) else "") for c, i in pos.items()}
        if not vals["SKU"]:
            skipped += any(v.strip() for v in row)
            continue
        sku = vals["SKU"].upper()
        if sku in seen:
            raise LayoutError(f"{path.name} row {n}: product {vals['SKU']} appears twice (also row {seen[sku]})")
        seen[sku] = n
        for c in DATE_COLUMNS:
            vals[c] = _iso(vals[c], f"{path.name} row {n}, {c}")
        out.append([vals[c] for c in HEADERS])
    return out, {"rows": len(out), "skipped_without_sku": skipped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--log", type=Path)
    a = ap.parse_args(argv)
    if a.out.suffix.lower() != ".csv":
        print("usage: <sheet.xls> <out.csv>", file=sys.stderr); return 2
    try:
        rows, st = normalise(a.sheet)
    except LayoutError as e:
        print(f"REFUSED  {e}", file=sys.stderr); return 1
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADERS); w.writerows(rows)
    note = (f"{st['rows']} products; kept the {len(HEADERS)} planning columns (sales workings, prices, costs and margins "
            f"dropped); dates rewritten as yyyy-mm-dd; {st['skipped_without_sku']} row(s) without a product code skipped")
    print(f"wrote {a.out}: {note}")
    if a.log:
        new = not a.log.exists()
        with open(a.log, "a", encoding="utf-8", newline="\n") as f:
            if new:
                f.write("workbook\tsheet\trows\tsource\tchanges\n")
            f.write(f"{a.sheet.name}\tTSV\t{st['rows']}\tSKU_PLANNING_MASTER\t{note}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
