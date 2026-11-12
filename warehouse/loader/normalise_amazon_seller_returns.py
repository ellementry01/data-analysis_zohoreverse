"""
Joins Amazon Seller Central "Manage Seller Fulfilled Returns" reports (tab-separated, one file per download window) into
one CSV in the AMAZON_SELLER_RETURNS contract layout: one row per return request line.

    python -m loader.normalise_amazon_seller_returns <folder or .tsv files...> <out.csv> [--log NORMALISE_LOG.tsv]

What changes, and nothing else:
  * header names are trimmed (the report writes " Merchant SKU" with a leading space);
  * the three date columns ("Order date", "Return request date", "Return delivery date") are rewritten from
    01-Apr-2025 to 2025-04-01;
  * values that are only spaces become empty;
  * identical rows (the same return request, e.g. where download windows overlap) are kept once;
  * the output is UTF-8 (the reports are UTF-8 or Windows-1252).
A file whose columns differ from the expected list, or a date that cannot be read, stops the run.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

HEADERS = ["Order ID", "Order date", "Return request date", "Return request status", "Amazon RMA ID", "Seller RMA ID",
           "Label type", "Label cost", "Currency code", "Return carrier", "Tracking ID", "Label to be paid by",
           "A-to-z claim", "Is prime", "ASIN", "Merchant SKU", "Item Name", "Return quantity", "Return reason", "In policy",
           "Return type", "Resolution", "Invoice number", "Return delivery date", "Order Amount", "Order quantity",
           "SafeT Action reason", "SafeT claim ID", "SafeT claim state", "SafeT claim creation time",
           "SafeT claim reimbursement amount", "Refunded Amount", "Category", "Order Item ID"]
DATE_COLUMNS = ("Order date", "Return request date", "Return delivery date")


class LayoutError(Exception):
    pass


def _iso(value: str, where: str) -> str:
    try:
        return dt.datetime.strptime(value, "%d-%b-%Y").date().isoformat()
    except ValueError:
        raise LayoutError(f"{where}: date '{value}' is not like 01-Apr-2025") from None


def read_report(path: Path) -> list[list[str]]:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:              # Seller Central writes these reports in Windows-1252 (e.g. a dash in an item name)
        text = data.decode("cp1252")
    rows = list(csv.reader(text.splitlines(), delimiter="\t"))
    if not rows:
        raise LayoutError(f"{path.name}: empty file")
    header = [h.strip() for h in rows[0]]
    if header != HEADERS:
        missing = [h for h in HEADERS if h not in header]
        extra = [h for h in header if h not in HEADERS]
        raise LayoutError(f"{path.name}: columns differ from the expected report (missing {missing}, unexpected {extra})")
    out = []
    for n, row in enumerate(rows[1:], start=2):
        if not any(v.strip() for v in row):
            continue
        if len(row) != len(HEADERS):
            raise LayoutError(f"{path.name} row {n}: {len(row)} values, expected {len(HEADERS)}")
        vals = [v.strip() for v in row]
        for c in DATE_COLUMNS:
            i = HEADERS.index(c)
            if vals[i]:
                vals[i] = _iso(vals[i], f"{path.name} row {n}, {c}")
        out.append(vals)
    return out


def normalise(paths: list[Path]) -> tuple[list[list[str]], dict]:
    seen: dict[tuple, None] = {}
    read = 0
    for p in sorted(paths):
        for row in read_report(p):
            read += 1
            seen.setdefault(tuple(row), None)
    rows = [list(r) for r in seen]
    return rows, {"files": len(paths), "read": read, "rows": len(rows), "repeated": read - len(rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", type=Path, nargs="+", help="a folder of .tsv reports, or the .tsv files; the last value is the output .csv")
    ap.add_argument("--log", type=Path)
    a = ap.parse_args(argv)
    *inputs, out = a.inputs
    paths: list[Path] = []
    for p in inputs:
        paths += sorted(p.glob("*.tsv")) if p.is_dir() else [p]
    if not paths or out.suffix.lower() != ".csv":
        print("usage: <folder or .tsv files...> <out.csv>", file=sys.stderr); return 2
    try:
        rows, st = normalise(paths)
    except LayoutError as e:
        print(f"REFUSED  {e}", file=sys.stderr); return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADERS); w.writerows(rows)
    note = (f"{st['files']} report file(s), {st['read']} rows -> {st['rows']} lines; {st['repeated']} identical row(s) "
            f"(same return request) kept once; dates rewritten as yyyy-mm-dd")
    print(f"wrote {out}: {note}")
    if a.log:
        new = not a.log.exists()
        with open(a.log, "a", encoding="utf-8", newline="\n") as f:
            if new:
                f.write("workbook\tsheet\trows\tsource\tchanges\n")
            f.write(f"{paths[0].parent.name}/ ({st['files']} files)\tTSV\t{st['rows']}\tAMAZON_SELLER_RETURNS\t{note}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
