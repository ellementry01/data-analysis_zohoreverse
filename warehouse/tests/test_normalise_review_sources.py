"""Normalisers added with schema 2.17: Amazon seller-fulfilled returns and the ERP Document Wise Stock Movement report."""
import csv

import pytest
from openpyxl import Workbook

from loader import normalise_amazon_seller_returns as asr
from loader import normalise_doc_stock_movement as dsm


# ----------------------------------------------------------------------------- Amazon seller-fulfilled returns

def _row(order="404-1", rma="RMA1", sku="SWETA1", reason="CR-DEFECTIVE", rtype="C-Returns", date="01-Apr-2025", delivered="04-Apr-2025"):
    r = {h: "" for h in asr.HEADERS}
    r.update({"Order ID": order, "Order date": "28-Mar-2025", "Return request date": date, "Amazon RMA ID": rma,
              "Merchant SKU": sku, "Return quantity": "1", "Return reason": reason, "Return type": rtype,
              "Return delivery date": delivered, "Currency code": " ", "Order Item ID": "1"})
    return [r[h] for h in asr.HEADERS]


def _tsv(path, rows, header=None, encoding="utf-8"):
    header = header or [("" if h != "Merchant SKU" else " ") + h for h in asr.HEADERS]   # the report writes ' Merchant SKU'
    path.write_text("\n".join("\t".join(r) for r in [header] + rows) + "\n", encoding=encoding)
    return path


def test_seller_returns_join_files_fix_dates_and_keep_a_repeated_row_once(tmp_path):
    a = _tsv(tmp_path / "a.tsv", [_row(), _row(order="404-2", rma="RMA2", reason="UND-UNKNOWN", rtype="Rejected", delivered="")])
    b = _tsv(tmp_path / "b.tsv", [_row(), _row(order="404-3", rma="RMA3", sku="Mug – blue")], encoding="cp1252")
    rows, st = asr.normalise([a, b])
    assert st == {"files": 2, "read": 4, "rows": 3, "repeated": 1}
    i = asr.HEADERS.index
    assert [r[i("Return request date")] for r in rows] == ["2025-04-01"] * 3
    assert rows[1][i("Return delivery date")] == "" and rows[1][i("Return type")] == "Rejected"
    assert rows[0][i("Currency code")] == "" and rows[2][i("Merchant SKU")] == "Mug – blue"


def test_seller_returns_refuse_a_changed_layout_or_an_unreadable_date(tmp_path):
    with pytest.raises(asr.LayoutError, match="columns differ"):
        asr.normalise([_tsv(tmp_path / "c.tsv", [_row()[:-1]], header=asr.HEADERS[:-1])])
    with pytest.raises(asr.LayoutError, match="is not like 01-Apr-2025"):
        asr.normalise([_tsv(tmp_path / "d.tsv", [_row(date="2025/04/01")])])


def test_seller_returns_command_writes_the_csv_and_the_log(tmp_path):
    _tsv(tmp_path / "a.tsv", [_row()])
    out, log = tmp_path / "out" / "x.csv", tmp_path / "LOG.tsv"
    assert asr.main([str(tmp_path), str(out), "--log", str(log)]) == 0
    got = list(csv.reader(open(out, encoding="utf-8")))
    assert got[0] == asr.HEADERS and len(got) == 2
    assert "AMAZON_SELLER_RETURNS" in log.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- ERP Document Wise Stock Movement

def _report(path, items, title="For The Period From 01/04/2025 To 15/09/2026", types=("OPENING", "Scrap Note", "Goods Receipt Note", "CLOSING")):
    wb = Workbook(); ws = wb.active; ws.title = "DocWiseStockMovement"
    ws.append(["Dileep Essentials Pvt Ltd"]); ws.append([]); ws.append([title]); ws.append([])
    ws.append([None] + [x for t in types for x in (t, None)])
    ws.append([None] + ["Qty", "Value"] * len(types))
    for r in items:
        ws.append(r)
    wb.save(path)
    return path


def test_movement_report_becomes_one_row_per_product_and_document(tmp_path):
    f = _report(tmp_path / "m.xlsx", [["SWETA1 - Mug - blue", 5, 500, -2, -200, 10, 1000, 13, 1300],
                                      ["SWETA2 - Bowl", 0, 0, None, None, None, None, 0, 0]])
    rows, st = dsm.normalise(f)
    assert rows == [["SWETA1", "Mug - blue", "OPENING", "5", "500", "2025-04-01", "2026-09-15"],
                    ["SWETA1", "Mug - blue", "Scrap Note", "-2", "-200", "2025-04-01", "2026-09-15"],
                    ["SWETA1", "Mug - blue", "Goods Receipt Note", "10", "1000", "2025-04-01", "2026-09-15"],
                    ["SWETA1", "Mug - blue", "CLOSING", "13", "1300", "2025-04-01", "2026-09-15"]]
    assert st["products"] == 2 and st["lines"] == 4


def test_movement_report_is_refused_when_a_row_does_not_add_up_or_has_no_period(tmp_path):
    with pytest.raises(dsm.LayoutError, match="CLOSING = 99"):
        dsm.normalise(_report(tmp_path / "a.xlsx", [["SWETA1 - Mug", 5, 500, -2, -200, 10, 1000, 99, 0]]))
    with pytest.raises(dsm.LayoutError, match="does not state the period"):
        dsm.normalise(_report(tmp_path / "b.xlsx", [["SWETA1 - Mug", 0, 0, None, None, None, None, 0, 0]], title="Stock movement"))
    with pytest.raises(dsm.LayoutError, match="appears twice"):
        dsm.normalise(_report(tmp_path / "c.xlsx", [["SWETA1 - Mug", 0, 0, None, None, None, None, 0, 0]] * 2))
