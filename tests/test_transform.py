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
