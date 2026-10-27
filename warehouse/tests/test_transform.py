"""
Transform tests. Need DW_TRANSFORM_DB: a disposable database built with build_db.sh, seeded, with
the sample files loaded (see README). Each test leaves the database as a successful build.
"""
import os, shutil, subprocess, sys
from pathlib import Path
import psycopg
import pytest

DB = os.environ.get("DW_TRANSFORM_DB")
pytestmark = pytest.mark.skipif(not DB, reason="set DW_TRANSFORM_DB to a loaded, disposable database")
ROOT = Path(__file__).resolve().parent.parent


def run(env_extra=None):
    env = dict(os.environ, **(env_extra or {}))
    return subprocess.run([sys.executable, "-m", "transform", "run", DB, "--started-by", "pytest"],
                          cwd=ROOT, capture_output=True, text=True, env=env)


def q(sql, *a):
    with psycopg.connect(dbname=DB) as c:
        return c.execute(sql, a).fetchall()


def setting(key, value):
    with psycopg.connect(dbname=DB) as c:
        c.execute("UPDATE meta.pipeline_setting SET setting_value = %s WHERE setting_key = %s", (value, key))


@pytest.fixture(scope="module", autouse=True)
def first_build():
    r = run(); assert r.returncode == 0, r.stdout + r.stderr
    yield
    setting("partner_list_complete", "false"); run()


def counts():
    return dict(q("SELECT 'sales', count(*) FROM core.fact_sales_line UNION ALL SELECT 'returns', count(*) FROM core.fact_return_line "
                  "UNION ALL SELECT 'ledger', count(*) FROM core.fact_stock_movement UNION ALL SELECT 'net', sum(net_sales_amount)::BIGINT FROM core.fact_sales_line"))


def test_rerun_is_identical_and_keys_are_stable():
    before = counts(); keys = dict(q("SELECT sku_code, product_key FROM core.dim_product"))
    assert run().returncode == 0
    assert counts() == before
    assert dict(q("SELECT sku_code, product_key FROM core.dim_product")) == keys


def test_failed_quality_gate_rolls_back_everything(tmp_path):
    before = counts(); runs_before = q("SELECT count(*) FROM meta.transform_run WHERE status = 'SUCCEEDED'")[0][0]
    sqldir = tmp_path / "sql"; shutil.copytree(ROOT / "transform" / "sql", sqldir)
    (sqldir / "55_force_fail.sql").write_text(
        "DELETE FROM core.fact_sales_line WHERE sales_line_id IN (SELECT min(sales_line_id) FROM core.fact_sales_line);"
        "INSERT INTO meta.dq_check_result (transform_run_id, check_name, target_table, severity, outcome, failed_row_count, details) "
        "SELECT run_id, 'forced_failure', 'test', 'ERROR', 'FAIL', 1, 'test' FROM ctx;")
    r = run({"DW_TRANSFORM_SQL_DIR": str(sqldir)})
    assert r.returncode == 1 and "rolled back" in r.stderr
    assert counts() == before                                                   # the deleted row is back: nothing committed
    assert q("SELECT count(*) FROM meta.transform_run WHERE status = 'SUCCEEDED'")[0][0] == runs_before
    assert q("SELECT status FROM meta.transform_run ORDER BY transform_run_id DESC LIMIT 1")[0][0] == "FAILED"


def test_reconciliation_gate_catches_duplication(tmp_path):
    sqldir = tmp_path / "sql"; shutil.copytree(ROOT / "transform" / "sql", sqldir)
    (sqldir / "45_duplicate_a_line.sql").write_text(       # simulate a lookup that duplicates a row
        "INSERT INTO core.fact_sales_line (source_name, bill_number, source_sku_code, line_occurrence, bill_date_key, order_key, product_key,"
        " location_key, channel_key, partner_key, quantity, net_sales_amount, net_amount_method, batch_id, source_row_number)"
        " SELECT source_name, bill_number, source_sku_code, 99, bill_date_key, order_key, product_key, location_key, channel_key, partner_key,"
        " quantity, net_sales_amount, net_amount_method, batch_id, source_row_number FROM core.fact_sales_line LIMIT 1;")
    r = run({"DW_TRANSFORM_SQL_DIR": str(sqldir)})
    assert r.returncode == 1 and "sales_rows_reconcile" in r.stderr


def test_safety_switch_keeps_unlisted_domestic_names_unclassified():
    rows = dict(q("SELECT partner_name, partner_type FROM core.dim_partner WHERE partner_role = 'CUSTOMER' "
                  "AND partner_name IN ('Shoppers Stop Limited', 'Ayush Baid', 'Dileep Crafts Private Limited', 'Shopify_Customer')"))
    assert rows["Shoppers Stop Limited"] == "UNCLASSIFIED" and rows["Ayush Baid"] == "UNCLASSIFIED"
    assert rows["Dileep Crafts Private Limited"] == "GROUP_EXPORT"          # listed (BR-007)
    assert rows["Shopify_Customer"] == "D2C_CHANNEL_ACCOUNT"                # retail default, always applies (BR-005)
    assert q("SELECT count(*) FROM core.fact_stock_movement m JOIN core.dim_movement_type t USING (movement_type_key) "
             "WHERE t.movement_code = 'ISSUE_UNCLASSIFIED'")[0][0] > 0      # stock still leaves, recorded honestly


def test_when_list_is_complete_elimination_applies_and_employee_stock_moves_to_holding():
    setting("partner_list_complete", "true")
    try:
        assert run().returncode == 0
        assert q("SELECT partner_type FROM core.dim_partner WHERE partner_name = 'Ayush Baid' AND partner_role = 'CUSTOMER'")[0][0] == "EMPLOYEE"
        n = q("SELECT count(*) FROM core.fact_stock_movement m JOIN core.dim_location l USING (location_key) "
              "WHERE l.location_code = 'EMPLOYEE_EXHIBITION'")[0][0]
        assert n > 0                                                       # BR-029
        assert q("SELECT count(*) FROM mart.v_net_sales_daily WHERE partner_type = 'EMPLOYEE'")[0][0] == 0   # never revenue
    finally:
        setting("partner_list_complete", "false")
    assert run().returncode == 0


def test_ledger_rules():
    assert q("SELECT count(*) FROM core.fact_stock_movement m JOIN core.dim_product p USING (product_key) WHERE p.item_type IN ('CHARGE','SERVICE')")[0][0] == 0
    # Kiranakart (Blinkit) credit notes: unsold stock leaves the consignment location and arrives back (BR-022)
    out_, in_ = q("SELECT sum(-m.quantity) FILTER (WHERE t.movement_code = 'CONSIGNMENT_RETURN_OUT'), "
                  "sum(m.quantity) FILTER (WHERE t.movement_code = 'CONSIGNMENT_RETURN_IN') "
                  "FROM core.fact_stock_movement m JOIN core.dim_movement_type t USING (movement_type_key)")[0]
    assert out_ and out_ == in_
    assert q("SELECT count(*) FROM core.fact_stock_movement m JOIN core.dim_movement_type t USING (movement_type_key) "
             "WHERE sign(m.quantity) <> t.stock_effect")[0][0] == 0


def test_nothing_after_cut_off():
    end = q("SELECT setting_value FROM meta.pipeline_setting WHERE setting_key = 'prototype_period_end'")[0][0].replace("-", "")
    for t, col in [("fact_sales_line", "bill_date_key"), ("fact_return_line", "return_date_key"), ("fact_stock_transfer_line", "document_date_key"),
                   ("fact_partner_sellout", "order_date_key"), ("fact_inventory_snapshot", "snapshot_date_key"), ("fact_purchase_order_line", "po_date_key")]:
        assert q(f"SELECT count(*) FROM core.{t} WHERE {col} > %s", int(end))[0][0] == 0, t


def test_every_dq_error_check_passed_and_coverage_written():
    assert q("SELECT count(*) FROM mart.v_data_quality_latest WHERE severity = 'ERROR' AND outcome = 'FAIL'")[0][0] == 0
    assert q("SELECT count(*) FROM mart.v_data_quality_latest WHERE severity = 'ERROR'")[0][0] >= 6
    assert q("SELECT count(DISTINCT period_month) FROM meta.process_coverage")[0][0] == 18      # Apr 2025 .. Sep 2026


# ------------------------------------------------------------------ purchase orders (schema 2.3)
def _po_xlsx(path, rows):
    """rows: (po_number, open_date, sku, order_qty, pending_qty, status, document_remark)"""
    import datetime as dt
    from openpyxl import Workbook
    from loader.validate import load_contract
    headers = [c["header"] for c in load_contract("ERP_PURCHASE_ORDER")["columns"]]
    wb = Workbook(); ws = wb.active; ws.title = "Sheet1"; ws.append(headers)
    for po, d, sku, qty, pending, status, remark in rows:
        r = [None] * len(headers)
        for h, v in [("PO No.", po), ("PO Open Date", dt.datetime.fromisoformat(d)), ("SKU No.", sku), ("Order Qty", qty),
                     ("PO Pending Qty", pending), ("STATUS", status), ("CONTACTNAME", "Pytest Factory"), ("Document Remark", remark)]:
            r[headers.index(h)] = v
        ws.append(r)
    wb.save(path)
    return path


@pytest.fixture()
def po_exports(tmp_path):
    """Loads synthetic PO exports; afterwards retires them, rebuilds, and removes every trace."""
    import datetime as dt
    from loader.load import load_file
    with psycopg.connect(dbname=DB) as c:
        start = c.execute("SELECT coalesce(max(batch_id), 0) FROM meta.load_batch").fetchone()[0]

    def load(name, rows, as_of):
        with psycopg.connect(dbname=DB) as c:
            return load_file("ERP_PURCHASE_ORDER", _po_xlsx(tmp_path / name, rows), as_of=dt.date.fromisoformat(as_of),
                             loaded_by="pytest", conn=c)
    yield load
    setting("po_document_remark_confirmed", "false")
    with psycopg.connect(dbname=DB) as c:
        c.execute("UPDATE meta.load_batch SET status = 'SUPERSEDED' WHERE batch_id > %s", (start,))
    assert run().returncode == 0                       # facts no longer point at the test batches
    with psycopg.connect(dbname=DB) as c:
        c.execute("DELETE FROM raw.erp_purchase_order WHERE batch_id > %s", (start,))
        c.execute("DELETE FROM meta.dq_check_result WHERE batch_id > %s", (start,))
        c.execute("DELETE FROM meta.load_batch WHERE batch_id > %s", (start,))


def po_lines(prefix="PYTEST/"):
    return {(po, sku): (qty, doc) for po, sku, qty, doc in q(
        "SELECT po_number, source_sku_code, order_qty::INT, document_type FROM core.fact_purchase_order_line "
        "WHERE po_number LIKE %s", prefix + "%")}


def test_po_exports_of_different_years_coexist_and_a_reexport_replaces(po_exports):
    real_before = q("SELECT count(*) FROM core.fact_purchase_order_line WHERE po_number NOT LIKE %s", "PYTEST/%")[0][0]
    po_exports("fy2526.xlsx", [("PYTEST/2526/1", "2025-05-10", "GSTEA2724", 10, 10, "In Progress", "Purchase"),
                               ("PYTEST/2526/2", "2025-06-01", "GSTEA2724", 4, 4, "In Progress", "Return")], "2026-03-31")
    po_exports("fy2627.xlsx", [("PYTEST/2627/1", "2026-05-02", "GSTEA2724", 7, 7, "In Progress", "Purchase")], "2026-05-31")
    assert run().returncode == 0
    lines = po_lines()
    # before 2.3 only the newest export was read and the FY 25-26 lines vanished
    assert lines == {("PYTEST/2526/1", "GSTEA2724"): (10, "PURCHASE"), ("PYTEST/2526/2", "GSTEA2724"): (4, "RETURN"),
                     ("PYTEST/2627/1", "GSTEA2724"): (7, "PURCHASE")}
    # an earlier year's re-export replaces only its own POs, and wins over the older state of them
    po_exports("fy2526_again.xlsx", [("PYTEST/2526/1", "2025-05-10", "GSTEA2724", 12, 0, "Received", "Purchase")], "2026-04-15")
    assert run().returncode == 0
    lines = po_lines()
    assert lines[("PYTEST/2526/1", "GSTEA2724")] == (12, "PURCHASE")
    assert ("PYTEST/2526/2", "GSTEA2724") in lines and ("PYTEST/2627/1", "GSTEA2724") in lines
    assert q("SELECT count(*) FROM core.fact_purchase_order_line WHERE po_number NOT LIKE %s", "PYTEST/%")[0][0] == real_before


def test_po_document_remark_decides_nothing_until_confirmed(po_exports):
    po_exports("remark.xlsx", [("PYTEST/R/1", "2026-04-03", "GSTEA2724", 5, 5, "In Progress", "Purchase"),
                               ("PYTEST/R/2", "2026-04-03", "GSTEA2724", 3, 3, "In Progress", "Return")], "2026-04-30")
    assert run().returncode == 0
    open_pos = lambda: dict(q("SELECT po_number, document_type FROM mart.v_open_purchase_orders WHERE po_number LIKE %s", "PYTEST/R/%"))
    assert open_pos() == {"PYTEST/R/1": "PURCHASE", "PYTEST/R/2": "RETURN"}       # BR-031 proposed: shown, not applied
    assert q("SELECT outcome FROM mart.v_data_quality_latest WHERE check_name = 'po_document_type_unknown'")[0][0] in ("PASS", "FAIL")
    setting("po_document_remark_confirmed", "true")
    assert run().returncode == 0
    assert open_pos() == {"PYTEST/R/1": "PURCHASE"}                                # confirmed: a return-inward is not a purchase
    assert q("SELECT count(*) FROM core.fact_purchase_order_line WHERE po_number = 'PYTEST/R/2'")[0][0] == 1   # still recorded in core


# ------------------------------------------------------------------ shipments (WMS dispatch, schema 2.3)
def _has_dispatch():
    return q("SELECT count(*) FROM raw.wms_dispatch")[0][0] > 0


def test_shipments_reconcile_to_the_dispatch_export():
    if not _has_dispatch():
        pytest.skip("no WMS dispatch file loaded")
    staged = q("SELECT count(*) FROM stg.wms_dispatch WHERE order_date BETWEEN %s::DATE AND %s::DATE",
               *[q("SELECT setting_value FROM meta.pipeline_setting WHERE setting_key = %s", k)[0][0]
                 for k in ("prototype_period_start", "prototype_period_end")])[0][0]
    assert q("SELECT count(*) FROM core.fact_shipment")[0][0] == staged > 0
    assert q("SELECT count(*) FROM mart.v_fulfilment")[0][0] == staged                       # no row lost in the joins
    rto = q("SELECT count(*) FROM stg.wms_dispatch WHERE status_raw IN ('RTO Delivered', 'isRTOInitiated')")[0][0]
    assert q("SELECT count(*) FROM core.fact_shipment WHERE is_rto")[0][0] == rto
    assert q("SELECT count(*) FROM core.fact_shipment f JOIN core.dim_location l ON l.location_key = f.fulfilment_location_key "
             "WHERE l.location_code <> 'BAGRU_WH'")[0][0] == 0                                  # BR-017


def test_shipment_sku_quantities_are_never_guessed():
    if not _has_dispatch():
        pytest.skip("no WMS dispatch file loaded")
    # single-SKU deliveries carry the row quantity; several SKUs in one cell are never split evenly
    assert q("SELECT count(*) FROM core.bridge_shipment_sku b JOIN core.fact_shipment f USING (shipment_id) "
             "WHERE b.quantity_source = 'SINGLE_SKU_ROW' AND b.quantity <> f.delivery_qty")[0][0] == 0
    assert q("SELECT count(*) FROM (SELECT shipment_id FROM core.bridge_shipment_sku WHERE quantity_source = 'SINGLE_SKU_ROW' "
             "GROUP BY 1 HAVING count(*) > 1) x")[0][0] == 0
    assert q("SELECT count(*) FROM core.bridge_shipment_sku b JOIN core.fact_shipment f USING (shipment_id) "
             "WHERE b.quantity_source = 'INVOICE_LINE' AND NOT EXISTS (SELECT 1 FROM core.fact_sales_line s "
             "WHERE s.bill_number = f.invoice_number)")[0][0] == 0


def test_dispatch_personal_data_stays_in_raw():
    for schema, table in [("stg", "wms_dispatch"), ("core", "fact_shipment"), ("mart", "v_fulfilment")]:
        cols = {c for (c,) in q("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
                                schema, table)}
        assert cols and not cols & {"customer_name", "customer_address", "customer_phone", "customer_email"}, table


def test_executive_views_exist_and_follow_the_revenue_rules():
    for v in ("v_sales_orders_daily", "v_partner_sellout_daily", "v_fulfilment", "v_stock_position_daily", "v_return_to_sale"):
        q(f"SELECT * FROM mart.{v} LIMIT 1")
    # invoices per day reconcile with the invoice side of v_net_sales_daily (same scope, BR-001)
    a = q("SELECT round(sum(invoiced_sales), 2) FROM mart.v_sales_orders_daily")[0][0]
    b = q("SELECT round(sum(gross_sales), 2) FROM mart.v_net_sales_daily")[0][0]
    assert a == b


def test_cost_highest_mrp_and_item_master_category():
    """2.8 business rules: unit cost and category come from the ERP item master only; the higher MRP is current."""
    if not q("SELECT count(*) FROM stg.item_master")[0][0]:
        pytest.skip("no ERP item master loaded")
    bad = q("""SELECT count(*) FROM core.dim_product p LEFT JOIN stg.item_master im USING (sku_code)
               WHERE NOT p.is_unknown_member AND (p.category IS DISTINCT FROM im.category
                     OR p.current_cost IS DISTINCT FROM round(nullif(im.cost, 0), 2))""")[0][0]   # stored to the paisa
    assert bad == 0
    lower = q("""SELECT count(*) FROM core.dim_product p JOIN stg.item_master im USING (sku_code)
                 WHERE im.mrp > 0 AND p.current_mrp < im.mrp""")[0][0]
    assert lower == 0                                    # never below the item master's MRP
    assert q("""SELECT count(*) FROM mart.v_stock_position_latest
                WHERE stock_value_cost IS DISTINCT FROM CASE WHEN unit_cost > 0 THEN on_hand_qty * unit_cost END""")[0][0] == 0
    assert q("SELECT channel_group FROM core.dim_channel WHERE channel_code = 'EXPORT_B2C'") == [("D2C_WEBSITE",)]
