"""
Generates loader/contracts/<SOURCE>.json from the verified sample files.

A contract states exactly what a file must look like. The loader refuses any
file that differs (missing column, new column, wrong sheet...). When the ERP
genuinely changes an export, the fix is deliberate: regenerate / edit the
contract, regenerate the raw DDL, review both in git.

Run:  python -m loader.build_contracts <folder with the sample files>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .readers import read_workbook

HERE = Path(__file__).parent
CONTRACTS = HERE / "contracts"

RESERVED = {"batch_id", "source_row_number", "source_col_number"}


def to_column_name(header: str) -> str:
    """'Payment mode/Account' -> 'payment_mode_account'. Deterministic; collisions are an error."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", header.strip()).strip("_").lower()
    if not s:
        raise ValueError(f"header {header!r} has no usable characters")
    if s[0].isdigit():
        s = "c_" + s
    if s in RESERVED:
        s = "src_" + s
    return s[:63]


def table_columns(headers: list[str]) -> list[dict]:
    cols, seen = [], {}
    for h in headers:
        c = to_column_name(h)
        if c in seen:
            raise ValueError(f"headers {seen[c]!r} and {h!r} both become column '{c}'")
        seen[c] = h
        cols.append({"header": h, "column": c})
    return cols


# source -> (sample file, sheet selector, other-sheets policy, business date, as-of required, extra)
SPEC = {
    "ERP_RETAIL_SALES":       ("Retail_Sales_01-04-2026_to_15-09-2026.xlsx", {"name": "Sheet1"}, "must_be_empty",
                               {"header": "BILLDATE", "format": "excel_datetime"}, False, {}),
    "ERP_DOMESTIC_SALES":     ("Domestic_Sales_01-04-2026_to_15-09-2026.xlsx", {"name": "Sheet1"}, "must_be_empty",
                               {"header": "BILLDATETIME", "format": "excel_datetime"}, False, {}),
    "ERP_RETAIL_RETURN":      ("Retail_Sales_Return_Current_FY.xlsx", {"name": "Sheet1"}, "must_be_empty",
                               {"header": "RETURNDATE", "format": "excel_datetime"}, False, {}),
    "ERP_DOMESTIC_RETURN":    ("Domestic_Sale_Return_Current_FY.xlsx", {"name": "Sheet1"}, "must_be_empty",
                               {"header": "BILLDATE", "format": "excel_datetime"}, False, {}),
    "ERP_STOCK_TRANSFER_OUT": ("Stock_Transfer_01-04-2026_to_15-09-2026.xlsx", {"name": "Sheet1"}, "must_be_empty",
                               {"header": "DOCOPENDATE", "format": "excel_datetime"}, False, {}),
    "ERP_STOCK_TRANSFER_IN":  ("Stock_Transfer_Inward_01-04-2026_to_15-09-2026.xlsx", {"name": "Sheet1"}, "must_be_empty",
                               {"header": "DOCOPENDATE", "format": "excel_datetime"}, False, {}),
    "ERP_PURCHASE_ORDER":     ("Pending_Purchase_Order_26-27_12_09_v2.xlsx", {"name": "Sheet1"}, "must_be_empty",
                               {"header": "PO Open Date", "format": "excel_datetime"}, True, {}),
    "BLINKIT_SALES":          ("BLINKIT_SALES_DATA_SEP_26.xlsx", {"name": "Sheet1"}, "must_be_empty",
                               {"header": "Order Date", "format": "text_ymd"}, False, {}),
    "BLINKIT_INVENTORY":      ("Blinkit_inventory_sep_26.xlsx", {"name": "Stock On Hand"}, "must_be_empty", None, True,
                               {"unnamed_columns": [{"position": 23, "rule": "values_in", "values": ["--"]}]}),
    "INSTAMART_SALES":        ("Instamart_sep_sales_data.xlsx", {"name": "Sales Report"}, "ignore",
                               {"header": "ORDERED_DATE", "format": "excel_datetime"}, False,
                               {"unnamed_columns": [{"position": 0, "rule": "row_counter"}],
                                "ignored_sheets_note": "Brand Metrics = city-level marketing data, not loaded in this phase"}),
    "ERP_ITEM_MASTER":        ("Product_Master_List_13-10-2026_11_51.xlsx", {"name": "Sheet1"}, "must_be_empty", None, True, {}),
    "INSTAMART_INVENTORY":    ("Instamart_inventory_26_sep_26.xlsx", {"pattern": r"^ItemInventory_\d+$"}, "must_be_empty", None, True, {}),
}


def build(sample_dir: Path) -> None:
    CONTRACTS.mkdir(exist_ok=True)
    for source, (fname, sheet, other, bdate, as_of_req, extra) in SPEC.items():
        book = read_workbook(sample_dir / fname)
        sname = sheet.get("name") or next(n for n in book if re.match(sheet["pattern"], n))
        header = book[sname][0]
        unnamed = {u["position"] for u in extra.get("unnamed_columns", [])}
        headers = [h for i, h in enumerate(header) if i not in unnamed]
        if any(h is None for h in headers):
            raise ValueError(f"{source}: blank header not declared as unnamed column")
        contract = {
            "source_name": source, "status": "verified", "verified_against": fname,
            "layout": "TABLE", "sheet": sheet, "other_sheets": other, "header_row": 1,
            "column_match": "exact_set", "expected_width": len(header),
            "unnamed_columns": extra.get("unnamed_columns", []),
            "columns": table_columns(headers), "business_date": bdate, "as_of_required": as_of_req,
        }
        if "ignored_sheets_note" in extra:
            contract["ignored_sheets_note"] = extra["ignored_sheets_note"]
        write(contract)

    # Product master: Sheet1 carries product columns FOLLOWED by a stale copy of
    # the stock report. Only the product columns are loaded; the rest is ignored
    # on purpose and must never be read as inventory.
    master_cols = ["Prod Num", "Status", "Prod Name", "Prod Type", "Unit"]
    book = read_workbook(sample_dir / "Ellementry_Final_Mastor_-_2026_september_updated.xlsx")
    assert book["Sheet1"][0][:5] == master_cols, book["Sheet1"][0][:5]
    write({"source_name": "PRODUCT_MASTER", "status": "verified",
           "verified_against": "Ellementry_Final_Mastor_-_2026_september_updated.xlsx",
           "layout": "TABLE", "sheet": {"name": "Sheet1"}, "other_sheets": "ignore", "header_row": 1,
           "column_match": "leading", "columns": table_columns(master_cols), "unnamed_columns": [],
           "business_date": None, "as_of_required": True,
           "ignored_columns_note": "Columns after 'Unit' are a stale copy of the stock report: deliberately NOT loaded",
           "ignored_sheets_note": "Mastor - Jan 2026, MRP to change Lot 1/2 are working sheets"})

    # Channelwise stock report (.xls): pivoted, one column block per location.
    write({"source_name": "ERP_INVENTORY_SNAPSHOT", "status": "verified", "verified_against": "Inventory_report_15_Sept.xls",
           "layout": "STOCK_PIVOT", "sheet": {"name": "ChannelwiseStock"}, "other_sheets": "must_be_empty",
           "header_row": 19,
           "product_columns": [{"header": "Prod Num", "column": "prod_num"}, {"header": "Prod Name", "column": "prod_name"},
                               {"header": "Prod Type", "column": "prod_type"}, {"header": "Prod Group", "column": "prod_group"},
                               {"header": "Prod Category", "column": "prod_category"},
                               {"header": "Prod Sub Category", "column": "prod_sub_category"}, {"header": "Unit", "column": "unit"}],
           "block_value_header": "Active MRP", "total_header": "Total",
           "title_cell": {"row": 1, "col": 1, "equals": "Inventory Position At all Channels -  Product Wise"},
           "as_of_cell": {"row": 3, "col": 1, "pattern": r"^(\d{1,2})/(\d{1,2})/(\d{4}) To (\d{1,2})/(\d{1,2})/(\d{4})$",
                          "order": "MDY"},
           "channel_filter_cell": {"row": 11, "col": 3},
           "business_date": None, "as_of_required": True,
           "columns": [{"header": h, "column": c} for h, c in
                       [("Prod Num", "prod_num"), ("Prod Name", "prod_name"), ("Prod Type", "prod_type"), ("Prod Group", "prod_group"),
                        ("Prod Category", "prod_category"), ("Prod Sub Category", "prod_sub_category"), ("Unit", "unit"),
                        ("(location block header)", "location_header"), ("(location quantity)", "qty"),
                        ("(location Active MRP)", "active_mrp")]]})

    # WMS dispatch: first drafted from the column list the business pasted, then verified (Oct 2026)
    # against the full export 'Dispatch order report 1 Apr.2025 to 15 Sep.2026.xlsm': every one of the
    # 46 columns matched, and its dates are real Excel date-times, not the M/D/YYYY text of the pasted rows.
    wms_headers = ("Order No|Extern Order No|Outbound Delivery No|Order Type|Tracking No|Status|Order Date|Ship Date|Delivery Qty|"
                   "Picked QTY|Weight|L|B|H|Pigeon Hole|No of Boxes|LrNo|Transporter|Pod|Vehicle No|Site Location|"
                   "Order Serving Location|Customer Name|Customer Address|Customer PinCode|Customer Phone|Customer Email|"
                   "Transporter Status|Transporter Remarks|Manifest No|Delivery Date|Ext Manifest No|Pick Date|Pack Date|"
                   "Sortation Date|Picklist No|SKU|Customer|UOMQty|Transporter URL|ONHOLD|LPN|Ext Transporter Name|"
                   "Transporter Error Description|Ship By Date|Invoice No").split("|")
    write({"source_name": "WMS_DISPATCH", "status": "verified",
           "verified_against": "Dispatch order report 1 Apr.2025 to 15 Sep.2026.xlsm",
           "layout": "TABLE", "sheet": {"index": 0}, "other_sheets": "must_be_empty", "header_row": 1,
           "column_match": "exact_set", "expected_width": len(wms_headers), "unnamed_columns": [],
           "columns": table_columns(wms_headers),
           "business_date": {"header": "Order Date", "format": "excel_datetime"}, "as_of_required": False})


def write(contract: dict) -> None:
    path = CONTRACTS / f"{contract['source_name']}.json"
    path.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    n = len(contract.get("columns", []))
    print(f"  {contract['source_name']:24s} {contract['status']:8s} {n:3d} columns -> {path.name}")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
