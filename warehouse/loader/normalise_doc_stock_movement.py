"""
Flattens the ERP 'Document Wise Stock Movement' report (one row per product, one Qty / Value column pair per document
type, for a whole period and all locations together) into the ERP_DOC_STOCK_MOVEMENT contract layout: one row per
product x document type.

    python -m loader.normalise_doc_stock_movement <DocumentWiseStockMovement.xls> <out.csv> [--log NORMALISE_LOG.tsv]

The report has no dates and no locations inside the period: it says how many units of a product each kind of ERP
document moved between the two dates in its title. It is the only export that shows the document types the other
exports lack (Scrap Note, Increase / Decrease Stock, Inventory Transfer, sub-contractor DN / GIN, Return To Supplier).

Checks before anything is written (the file is refused otherwise):
  * the title states the period ('For The Period From dd/mm/yyyy To dd/mm/yyyy');
  * the first column pair is OPENING and the last is CLOSING;
  * on every row OPENING + all documents = CLOSING, in units.
Cells with no movement are left out. 'Product No.' is the text before the first ' - ' of the report's product label.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .readers import read_workbook

HEADERS = ["Product No.", "Product Description", "Document Type", "Quantity", "Value", "Period From", "Period To"]
_PERIOD = re.compile(r"For The Period From (\d{2})/(\d{2})/(\d{4}) To (\d{2})/(\d{2})/(\d{4})", re.I)


class LayoutError(Exception):
    pass


def _dec(v, where: str) -> Decimal:
    if v is None or str(v).strip() == "":
        return Decimal(0)
    try:
        return Decimal(str(v).strip())
    except InvalidOperation:
        raise LayoutError(f"{where}: '{v}' is not a number") from None


def normalise(path: Path) -> tuple[list[list[str]], dict]:
    book = read_workbook(path)
    if len(book) != 1:
        raise LayoutError(f"expected one sheet, found {list(book)}")
    rows = next(iter(book.values()))
    period = next((m for r in rows[:8] for v in r if v and (m := _PERIOD.search(str(v)))), None)
    if period is None:
        raise LayoutError("the title does not state the period ('For The Period From dd/mm/yyyy To dd/mm/yyyy')")
    p_from = f"{period[3]}-{period[2]}-{period[1]}"; p_to = f"{period[6]}-{period[5]}-{period[4]}"
    h = next((i for i, r in enumerate(rows[:12]) if len(r) > 1 and r[1] and str(r[1]).strip().upper() == "OPENING"), None)
    if h is None:
        raise LayoutError("no header row starting with OPENING")
    head, sub = rows[h], rows[h + 1]
    pairs = []                                     # (document type, qty column, value column)
    for i in range(1, len(head), 2):
        if head[i] is None:
            raise LayoutError(f"header: no document type above column {i + 1}")
        if (str(sub[i]).strip(), str(sub[i + 1]).strip()) != ("Qty", "Value"):
            raise LayoutError(f"header: columns {i + 1}-{i + 2} are not Qty / Value")
        pairs.append((str(head[i]).strip(), i, i + 1))
    if pairs[0][0].upper() != "OPENING" or pairs[-1][0].upper() != "CLOSING":
        raise LayoutError("the first column pair must be OPENING and the last CLOSING")
    out, products, seen = [], 0, set()
    for n, r in enumerate(rows[h + 2:], start=h + 3):
        if not any(v is not None and str(v).strip() for v in r):
            continue
        label = (r[0] or "").strip() if isinstance(r[0], str) else ""
        if " - " not in label:
            raise LayoutError(f"row {n}: product label '{label}' is not 'code - name'")
        code, name = (x.strip() for x in label.split(" - ", 1))
        if code in seen:
            raise LayoutError(f"row {n}: product {code} appears twice")
        seen.add(code); products += 1
        qty = [_dec(r[q], f"row {n}") for _, q, _ in pairs]
        if qty[0] + sum(qty[1:-1]) != qty[-1]:
            raise LayoutError(f"row {n} ({code}): OPENING + documents = {qty[0] + sum(qty[1:-1])}, but CLOSING = {qty[-1]}")
        for (doc, q, v) in pairs:
            dq, dv = _dec(r[q], f"row {n}"), _dec(r[v], f"row {n}")
            if dq != 0 or dv != 0:
                out.append([code, name, doc, str(dq), str(dv), p_from, p_to])
    stats = {"products": products, "lines": len(out), "types": len(pairs), "from": p_from, "to": p_to}
    return out, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path); ap.add_argument("out", type=Path); ap.add_argument("--log", type=Path)
    a = ap.parse_args(argv)
    try:
        data, st = normalise(a.report)
    except LayoutError as e:
        print(f"REFUSED  {e}", file=sys.stderr); return 1
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADERS); w.writerows(data)
    note = (f"{st['products']} products x {st['types']} column pairs -> {st['lines']} lines with a movement, period "
            f"{st['from']} to {st['to']}; every row checked: OPENING + documents = CLOSING")
    print(f"wrote {a.out}: {note}")
    if a.log:
        new = not a.log.exists()
        with open(a.log, "a", encoding="utf-8", newline="\n") as f:
            if new:
                f.write("workbook\tsheet\trows\tsource\tchanges\n")
            f.write(f"{a.report.name}\tDocWiseStockMovement\t{st['lines']}\tERP_DOC_STOCK_MOVEMENT\t{note}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
