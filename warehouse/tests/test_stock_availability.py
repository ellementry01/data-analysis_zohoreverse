"""
Stock availability (schema 2.18): the reorder-sheet normaliser, and the rules of mart.v_stock_availability.

The view tests need DW_TRANSFORM_DB: a disposable, loaded and built database with migration 260 applied and a
reorder sheet loaded, e.g.

    DW_DATABASE=<copy> python dw.py pytest -q tests/test_stock_availability.py
"""
import csv
import os

import psycopg
import pytest

from loader import normalise_planning_master as npm

# ----------------------------------------------------------------------------- normaliser

HEAD = ["SKU", "PRODNAME", "Discontinued product list", "top 40 sku", "GRADE ", "Amazon NOW  SKU", "OTHER PLATEFORM SKU",
        "Launch Date", "New sku Replacement", "New Mrp", "FACTORY NAME ", "MOQ", "MLT", "instamrart ", "Po Delivery Date ",
        "PO PENDING ", "W.H INVENTORY", "factory cost with freight", "MRP"]


def _row(sku="PWDEA3709", launch="03-05-2025", mlt="45", moq="200", po_date="", cost="76.2"):
    return [sku, "Puro 3\" Pillar Candle", "121 SKU", "", "C", "", "", launch, "MWTEA5263", "450", "ASTERBLUME ", moq, mlt,
            "yes", po_date, "0", "5160", cost, "450"]


def _sheet(path, rows, title="SKU MASTER 485", head=None):
    lines = [[title] + [""] * (len(HEAD) - 1), head or HEAD] + rows
    text = "\r\n".join("\t".join(r) for r in lines) + "\r\n"
    path.write_bytes(text.encode("utf-8"))      # bytes, as Excel saves it (write_text would double the line ends on Windows)
    return path


def test_sheet_keeps_only_planning_columns_and_fixes_dates(tmp_path):
    rows, st = npm.normalise(_sheet(tmp_path / "s.xls", [_row(), _row(sku="X2", launch="00-01-1900", mlt="NOT", po_date="30-09-2026"), [""] * 5]))
    assert st == {"rows": 2, "skipped_without_sku": 0}
    i = npm.HEADERS.index
    assert rows[0][i("Launch Date")] == "2025-05-03" and rows[0][i("Factory")] == "ASTERBLUME" and rows[0][i("MOQ")] == "200"
    assert rows[1][i("Launch Date")] == "" and rows[1][i("MLT Days")] == "NOT" and rows[1][i("PO Delivery Date")] == "2026-09-30"
    assert "MRP" not in npm.HEADERS and not any("76.2" in v for r in rows for v in r)        # prices and costs are dropped


def test_sheet_is_refused_when_it_is_not_the_reorder_sheet_or_a_product_repeats(tmp_path):
    with pytest.raises(npm.LayoutError, match="not the reorder sheet"):
        npm.normalise(_sheet(tmp_path / "a.xls", [_row()], title="Something else"))
    with pytest.raises(npm.LayoutError, match="'MLT' not found"):
        npm.normalise(_sheet(tmp_path / "b.xls", [_row()], head=[h if h != "MLT" else "Lead" for h in HEAD]))
    with pytest.raises(npm.LayoutError, match="appears twice"):
        npm.normalise(_sheet(tmp_path / "c.xls", [_row(), _row(sku="pwdea3709")]))
    with pytest.raises(npm.LayoutError, match="is not like 03-05-2025"):
        npm.normalise(_sheet(tmp_path / "d.xls", [_row(launch="May 2025")]))
    (tmp_path / "e.xls").write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 20)
    with pytest.raises(npm.LayoutError, match="Tab delimited"):
        npm.normalise(tmp_path / "e.xls")


def test_sheet_command_writes_the_csv_and_the_log(tmp_path):
    _sheet(tmp_path / "s.xls", [_row()])
    out, log = tmp_path / "o" / "x.csv", tmp_path / "LOG.tsv"
    assert npm.main([str(tmp_path / "s.xls"), str(out), "--log", str(log)]) == 0
    got = list(csv.reader(open(out, encoding="utf-8")))
    assert got[0] == npm.HEADERS and len(got) == 2 and "SKU_PLANNING_MASTER" in log.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- the view

DB = os.environ.get("DW_TRANSFORM_DB")
needs_db = pytest.mark.skipif(not DB, reason="set DW_TRANSFORM_DB to a loaded, disposable database")


def q(sql, *a):
    with psycopg.connect(dbname=DB) as c:
        return c.execute(sql, a).fetchall()


@needs_db
def test_availability_covers_continued_trading_products_once():
    (n, distinct), = q("SELECT count(*), count(DISTINCT sku_code) FROM mart.v_stock_availability")
    (cont,), = q("SELECT count(*) FROM core.dim_product WHERE lifecycle_status = 'CONTINUED' AND item_type = 'TRADING' AND NOT is_unknown_member")
    assert n == distinct == cont
    assert not q("SELECT 1 FROM mart.v_stock_availability v JOIN core.dim_product p USING (sku_code) WHERE p.lifecycle_status <> 'CONTINUED'")


@needs_db
def test_ideal_reorder_and_status_follow_the_rule():
    bad = q("""SELECT sku_code FROM mart.v_stock_availability WHERE
        target_days <> mlt_days + transit_buffer_days
        OR ideal_qty <> ceil(units_sold_in_window / sales_days * target_days)
        OR available_qty <> stock_qty + on_order_qty
        OR shortfall_qty <> greatest(ideal_qty - available_qty, 0)
        OR reorder_qty < shortfall_qty
        OR (moq > 0 AND reorder_qty %% moq <> 0)
        OR (moq > 0 AND reorder_qty - shortfall_qty >= moq)
        OR (coalesce(moq, 0) = 0 AND reorder_qty <> shortfall_qty)
        OR (availability_status = '1. Reorder now') <> (daily_sales > 0 AND available_qty < ideal_qty)
        OR (reorder_qty > 0 AND availability_status <> '1. Reorder now')
        OR (availability_status = '5. No recent sales') <> (daily_sales = 0)""")
    assert not bad, bad[:5]


@needs_db
def test_missing_mlt_uses_the_default_and_bulk_channels_do_not_count():
    (default,), = q("SELECT setting_value::INT FROM meta.pipeline_setting WHERE setting_key = 'availability.default_mlt_days'")
    assert not q("SELECT 1 FROM mart.v_stock_availability WHERE mlt_is_default AND mlt_days <> %s", default)
    assert not q("SELECT 1 FROM mart.v_stock_availability WHERE NOT mlt_is_default AND mlt_days <> mlt_days_in_sheet")
    (bulk_in,), = q("""SELECT count(*) FROM mart.v_stock_availability v WHERE v.units_sold_in_window <> (
        SELECT coalesce(sum(s.quantity), 0) FROM core.fact_sales_line s JOIN core.dim_product p ON p.product_key = s.product_key
        JOIN core.dim_date d ON d.date_key = s.bill_date_key JOIN core.dim_channel c ON c.channel_key = s.channel_key
        JOIN core.dim_partner pt ON pt.partner_key = s.partner_key
        WHERE p.sku_code = v.sku_code AND NOT pt.is_internal AND c.channel_code NOT IN ('B2B', 'EXPORT_DIRECT', 'EXPORT_VIA_DILEEP', '#UNKNOWN')
          AND d.calendar_date > v.sales_to - 365 AND d.calendar_date <= v.sales_to)""")
    assert bulk_in == 0
