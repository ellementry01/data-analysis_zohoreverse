"""ERP MRN Register normaliser: GRN header rows + item rows -> one row per receipt line; memo repeats kept once."""
from openpyxl import Workbook

from loader.normalise_grn_register import EXPECTED, normalise


def report(path, rows):
    wb = Workbook(); ws = wb.active; ws.title = "MRNRegister"
    ws.append(["Dileep Essentials Pvt Ltd"]); ws.append([]); ws.append(["MRN Register"])
    ws.append(EXPECTED + [None] * 8)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def head(grn, date, po):
    return [grn, date, "Factory A", po, "01/05/2025", None, None, "BILL/1", date] + [None] * 19


def item(sku, qty, rate="10.00 INR"):
    return [None] * 9 + [sku, "6912", "Mug", f"{qty} Pcs", f"{qty}Pcs", rate, None, "100", "5", "105"] + [None] * 9


def test_memo_repeats_are_kept_once_and_real_lines_stay(tmp_path):
    f = report(tmp_path / "m.xlsx", [head("JPR/GRN/1/25-26", "05/05/2025", "PO/1/25-26"), item("SWETA1", 10), item("SWETA1", 10),
                                     item("SWETA2", 3), head("JPR/GRN/2/25-26", "06/05/2025", None), item("SWETA1", 10),
                                     ["Total"] + [None] * 27])
    lines, st = normalise(f)
    assert [(l[0], l[7], l[11], l[-1]) for l in lines] == [("JPR/GRN/1/25-26", "SWETA1", "10", 2), ("JPR/GRN/1/25-26", "SWETA2", "3", 1),
                                                         ("JPR/GRN/2/25-26", "SWETA1", "10", 1)]
    assert lines[2][3] is None and st == {"grns": 2, "raw_lines": 4, "lines": 3, "repeated": 1}
