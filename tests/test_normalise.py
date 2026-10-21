"""Platform sell-out normaliser (loader/normalise_platform_sales.py): pure tests, no database."""
import datetime as dt

import pytest
from openpyxl import Workbook

from loader.normalise_platform_sales import LayoutError, contract_headers, normalise_workbook, to_iso_date, write_month
from loader.readers import read_workbook
from loader.validate import load_contract, parse

BLINKIT = contract_headers("BLINKIT_SALES")[0]
INSTAMART = contract_headers("INSTAMART_SALES")[0]


def book(path, sheets):
    wb = Workbook(); wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


def blinkit_row(headers, **values):
    base = {"Order Id": 111, "Order Date": "2025-09-01", "Item Id": 555, "ELLE SKU": "GSTEA2724", "Order Status": "DELIVERED",
            "Quantity": 1, "Supply City": "Pune"}
    base.update(values)
    return [base.get(h) for h in headers]


@pytest.mark.parametrize("value,iso", [("2 July 2025", "2025-07-02"), (dt.datetime(2025, 9, 1), "2025-09-01"),
                                       (46024, "2026-01-02"), ("2026-05-19", "2026-05-19"), ("2026-05-19 00:00:00", "2026-05-19")])
def test_every_platform_date_encoding(value, iso):
    assert to_iso_date(value) == iso


def test_unknown_date_is_refused():
    with pytest.raises(LayoutError):
        to_iso_date("next tuesday")


def test_sku_alias_and_settlement_layout_without_personal_data(tmp_path):
    std = [h if h != "ELLE SKU" else "Elle sku" for h in BLINKIT]                 # a renamed SKU column
    settle = ["Order ID", "Order Date", "Customer Name", "Item ID", "Order Status", "Quantity", "Item Level Payout"]
    f = book(tmp_path / "b.xlsx", {
        "Sep 25": [std, blinkit_row(BLINKIT, **{"Order Date": "2025-09-03"})],
        " July 25": [settle, [222, "2 July 2025", "A Customer", 555, "DELIVERED", 2, 99.5]],
    })
    sheets = {n: (recs, notes) for n, recs, notes in normalise_workbook(f, "BLINKIT_SALES")}
    jul, notes = sheets[" July 25"]
    assert jul[0]["Order Id"] == 222 and jul[0]["Order Date"] == "2025-07-02" and jul[0]["Quantity"] == 2
    assert jul[0]["ELLE SKU"] == "GSTEA2724"                                       # from Item Id 555, unambiguous
    assert any("dropped 'Customer Name'" in n for n in notes)
    paths = write_month("BLINKIT_SALES", [r for recs, _ in sheets.values() for r in recs], tmp_path)
    text = "".join(str(v) for p in paths for row in read_workbook(p)["Sheet1"] for v in row)
    assert "A Customer" not in text and "99.5" not in text                          # personal data and payout never written
    for p in paths:                                                                 # every output passes the real contract
        parse(read_workbook(p), load_contract("BLINKIT_SALES"))


def test_ambiguous_item_id_never_gets_a_sku(tmp_path):
    std = list(BLINKIT)
    settle = ["Order ID", "Order Date", "Item ID", "Order Status", "Quantity"]
    f = book(tmp_path / "b.xlsx", {
        "A": [std, blinkit_row(BLINKIT, **{"ELLE SKU": "GSTEA2724"}), blinkit_row(BLINKIT, **{"ELLE SKU": "GSTEA9999"})],
        "B": [settle, [333, "2025-07-05", 555, "DELIVERED", 1]],
    })
    b = {n: recs for n, recs, _ in normalise_workbook(f, "BLINKIT_SALES")}["B"]
    assert b[0]["ELLE SKU"] is None                                                 # item 555 maps to two SKUs: left empty


def test_unexpected_column_is_refused(tmp_path):
    f = book(tmp_path / "b.xlsx", {"X": [BLINKIT + ["Something New"], blinkit_row(BLINKIT) + ["?"]]})
    with pytest.raises(LayoutError, match="unexpected column"):
        normalise_workbook(f, "BLINKIT_SALES")


def instamart_row(n, date, sku="SWETA2453"):
    v = {"BRAND": "ellementry", "ORDERED_DATE": date, "CITY": "Delhi", "AREA_NAME": "x", "STORE_ID": 1400547,
         "L1_CATEGORY": "a", "L2_CATEGORY": "b", "L3_CATEGORY": "c", "PRODUCT_NAME": "mug", "VARIANT": "2 pieces",
         "ITEM_CODE": 357618, "Elle SKU": sku, "COMBO": "No", "BASE_MRP": 1090, "UNITS_SOLD": 1, "GMV": 1090}
    return [n] + [v.get(h) for h in INSTAMART]


def test_headerless_instamart_sheet_gets_the_header_only_when_columns_match(tmp_path):
    f = book(tmp_path / "i.xlsx", {
        "April": [[None] + INSTAMART, instamart_row(0, dt.datetime(2025, 4, 2))],
        "August": [instamart_row(0, dt.datetime(2025, 8, 8)), instamart_row(1, dt.datetime(2025, 8, 9))],
    })
    sheets = {n: (recs, notes) for n, recs, notes in normalise_workbook(f, "INSTAMART_SALES")}
    aug, notes = sheets["August"]
    assert len(aug) == 2 and aug[0]["ORDERED_DATE"] == "2025-08-08" and aug[0]["Elle SKU"] == "SWETA2453"
    assert any("header row missing" in n for n in notes)
    for p in write_month("INSTAMART_SALES", aug, tmp_path):
        parse(read_workbook(p), load_contract("INSTAMART_SALES"))


def test_headerless_sheet_with_other_columns_is_refused(tmp_path):
    f = book(tmp_path / "i.xlsx", {
        "April": [[None] + INSTAMART, instamart_row(0, dt.datetime(2025, 4, 2))],
        "Odd": [["ellementry", "not a date", "Delhi"]],
    })
    with pytest.raises(LayoutError, match="no header row"):
        normalise_workbook(f, "INSTAMART_SALES")


def test_stray_cells_are_skipped_and_reported(tmp_path):
    stray = [None] * (len(INSTAMART) + 1); stray[11] = "m"
    f = book(tmp_path / "i.xlsx", {"April": [[None] + INSTAMART, instamart_row(0, dt.datetime(2025, 4, 2)), stray]})
    recs, notes = {n: (r, no) for n, r, no in normalise_workbook(f, "INSTAMART_SALES")}["April"]
    assert len(recs) == 1 and any("skipped 1 row" in n for n in notes)
