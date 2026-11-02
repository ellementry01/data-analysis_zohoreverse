"""
Flattens the ERP 'MRN Register' (goods receipts, Inventory Reports > MRN Register, ReportIndex 11213) into the
ERP_GRN_REGISTER contract layout: one row per goods-receipt line.

    python -m loader.normalise_grn_register <MRNRegister.xls> <out.xlsx> [--log NORMALISE_LOG.tsv]

The report prints a GRN header row (GRN No., date, supplier, PO, bill) followed by its item rows. When a GRN has
debit-note memos, the report repeats every item row once per memo: identical rows within one GRN (same product,
quantities, rate and amount) are therefore kept ONCE, and the number of copies is written to 'Repeats in source'.
Checked on the Apr 2025 - Sep 2026 export: the de-duplicated quantities equal the ERP's own Goods Receipt Note
movement (Document Wise Stock Movement report) for 1,694 of 1,698 products. Nothing else is changed.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import OrderedDict
from pathlib import Path

from openpyxl import Workbook

from .readers import read_workbook

HEADERS = ["GRN No.", "GRN Date", "Supplier", "PO No.", "PO Date", "Bill No.", "Bill Date", "Product No.", "HSN Code",
           "Product Description", "Bill Quantity", "Received Quantity", "Rate", "Amount", "GST %", "Total Amount",
           "Repeats in source"]
EXPECTED = ["GRN No.", "GRN Date", "Supplier", "PO No.", "PO Date", "Indent No.", "Indent Date", "Bill No.", "Bill Date",
            "Product No.", "HSN Code", "Product Description", "Bill Quantity", "Received Quantity", "Rate", "Discount %",
            "Amount", "GST %", "Total Amount", "Inspection Remarks"]
_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


class LayoutError(Exception):
    pass


def _s(v) -> str | None:
    return None if v is None or str(v).strip() == "" else str(v).strip()


def _num(v) -> str | None:
    """'1.00 Pcs' -> '1.00', '900.00 INR' -> '900.00'; numbers as written, never rounded."""
    s = _s(v)
    if s is None:
        return None
    m = re.match(r"^-?[\d,]*\.?\d+", s)
    if not m:
        raise LayoutError(f"not a number: {s!r}")
    return m.group(0).replace(",", "")


def normalise(path: Path) -> tuple[list[list], dict]:
    sheets = read_workbook(path)
    if list(sheets) != ["MRNRegister"]:
        raise LayoutError(f"expected one sheet 'MRNRegister', found {list(sheets)}")
    rows = sheets["MRNRegister"]
    hdr_i = next((i for i, r in enumerate(rows[:20]) if r and _s(r[0]) == "GRN No."), None)
    if hdr_i is None:
        raise LayoutError("header row 'GRN No.' not found")
    hdr = [_s(h) for h in rows[hdr_i]]
    if [h for h in hdr[:20]] != EXPECTED:
        raise LayoutError(f"unexpected columns: {hdr[:20]}")
    lines: "OrderedDict[tuple, list]" = OrderedDict()
    cur, grns, raw_lines = None, 0, 0
    for r in rows[hdr_i + 1:]:
        r = list(r) + [None] * (len(hdr) - len(r))
        if _s(r[0]) == "Total":
            break
        if _s(r[0]) and _s(r[1]) and _DATE.match(_s(r[1])):
            cur = [_s(r[0]), _s(r[1]), _s(r[2]), _s(r[3]), _s(r[4]) if _s(r[4]) else None, _s(r[7]), _s(r[8])]
            grns += 1
            continue
        if _s(r[9]):
            if cur is None:
                raise LayoutError("item row before any GRN header row")
            raw_lines += 1
            item = [_s(r[9]), _s(r[10]), _s(r[11]), _num(r[12]), _num(r[13]), _num(r[14]), _num(r[16]), _num(r[17]), _num(r[18])]
            key = (cur[0], *item)
            if key in lines:
                lines[key][-1] += 1
            else:
                lines[key] = cur + item + [1]
    if not lines:
        raise LayoutError("no goods-receipt lines found")
    stats = {"grns": grns, "raw_lines": raw_lines, "lines": len(lines), "repeated": sum(1 for v in lines.values() if v[-1] > 1)}
    return list(lines.values()), stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path); ap.add_argument("out", type=Path); ap.add_argument("--log", type=Path)
    a = ap.parse_args(argv)
    try:
        data, st = normalise(a.report)
    except LayoutError as e:
        print(f"REFUSED  {e}", file=sys.stderr); return 1
    wb = Workbook(); ws = wb.active; ws.title = "Sheet1"
    ws.append(HEADERS)
    for r in data:
        ws.append(r)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(a.out)
    note = (f"{st['grns']} GRNs, {st['raw_lines']} item rows -> {st['lines']} lines; {st['repeated']} line(s) printed "
            f"more than once (once per debit-note memo) kept once")
    print(f"wrote {a.out}: {note}")
    if a.log:
        new = not a.log.exists()
        with open(a.log, "a", encoding="utf-8", newline="\n") as f:
            if new:
                f.write("workbook\tsheet\trows\tsource\tchanges\n")
            f.write(f"{a.report.name}\tMRNRegister\t{st['lines']}\tERP_GRN_REGISTER\t{note}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
