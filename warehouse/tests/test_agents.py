"""
Agent runner tests (PRD-001 section 10.2 / 10.5 for the rules switched on). Need DW_TRANSFORM_DB: a disposable,
loaded and built database with migration 240 applied, e.g. a restore of a warehouse backup:

    DW_DATABASE=<copy> python dw.py pytest -q tests/test_agents.py

Every test leaves the settings and rules as it found them.
"""
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

DB = os.environ.get("DW_TRANSFORM_DB")
pytestmark = pytest.mark.skipif(not DB, reason="set DW_TRANSFORM_DB to a loaded, disposable database")
ROOT = Path(__file__).resolve().parent.parent


def run(which="all"):
    return subprocess.run([sys.executable, "-m", "agents", "run", which, DB, "--started-by", "pytest"],
                          cwd=ROOT, capture_output=True, text=True)


def q(sql, *a):
    with psycopg.connect(dbname=DB) as c:
        return c.execute(sql, a).fetchall()


def x(sql, *a):
    with psycopg.connect(dbname=DB) as c:
        c.execute(sql, a)


@contextmanager
def setting(key, value):
    old = q("SELECT setting_value FROM meta.pipeline_setting WHERE setting_key = %s", key)
    if value is None:
        x("DELETE FROM meta.pipeline_setting WHERE setting_key = %s", key)
    else:
        x("UPDATE meta.pipeline_setting SET setting_value = %s WHERE setting_key = %s", value, key)
    try:
        yield
    finally:
        if old and value is None:
            x("INSERT INTO meta.pipeline_setting (setting_key, setting_value, description) VALUES (%s, %s, 'restored by test')",
              key, old[0][0])
        elif old:
            x("UPDATE meta.pipeline_setting SET setting_value = %s WHERE setting_key = %s", old[0][0], key)


@contextmanager
def rule(code, **cols):
    old = q("SELECT is_active, process_name FROM insight.alert_rule WHERE alert_code = %s", code)[0]
    for k, v in cols.items():
        x(f"UPDATE insight.alert_rule SET {k} = %s WHERE alert_code = %s", v, code)
    try:
        yield
    finally:
        x("UPDATE insight.alert_rule SET is_active = %s, process_name = %s WHERE alert_code = %s", old[0], old[1], code)


def open_events(code=None):
    return q("SELECT identity_key, alert_id, severity, message FROM insight.alert_event WHERE status = 'OPEN'"
             + (" AND alert_code = %s" if code else "") + " ORDER BY identity_key", *([code] if code else []))


@pytest.fixture(scope="module", autouse=True)
def first_run():
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    yield
    run()


def test_rules_raise_alerts_with_complete_messages():
    for code in ("STK-A01", "STK-A02", "OPS-A02"):
        ev = open_events(code)
        assert ev, f"{code} raised nothing on the loaded data"
        assert all(m.endswith(".") and len(m) > 40 for *_, m in ev)
    sev = {s for _, _, s, _ in open_events("STK-A01")}
    assert sev == {"CRITICAL"}
    assert {s for _, _, s, _ in open_events("STK-A02")} == {"WARNING"}


def test_rerun_keeps_one_open_event_per_condition_and_is_identical():
    before = open_events()
    r = run()
    assert r.returncode == 0, r.stderr
    assert "0 raised" in r.stdout
    assert open_events() == before                      # same ids, same severities, same messages
    dup = q("SELECT identity_key FROM insight.alert_event WHERE status IN ('OPEN','ACKNOWLEDGED') "
            "GROUP BY identity_key HAVING count(*) > 1")
    assert dup == []


def test_no_alert_when_threshold_not_crossed_and_condition_gone_auto_resolves():
    before = {k for k, *_ in open_events("STK-A02")}
    with setting("stock.low_cover_days", "0"):
        assert run("stock").returncode == 0
        assert open_events("STK-A02") == []
        resolved = q("SELECT identity_key, handled_by FROM insight.alert_event WHERE alert_code = 'STK-A02' "
                     "AND status = 'RESOLVED' AND identity_key = ANY(%s)", list(before))
        assert {k for k, _ in resolved} == before and {h for _, h in resolved} == {"stock_ai"}
    assert run("stock").returncode == 0                 # crossed again: raised as new events
    assert {k for k, *_ in open_events("STK-A02")} == before


def test_threshold_lowered_raises_more_and_messages_name_it():
    base = len(open_events("STK-A02"))
    with setting("stock.low_cover_days", "30"):
        assert run("stock").returncode == 0
        ev = open_events("STK-A02")
        assert len(ev) > base
        assert all("below the 30-day threshold" in m for *_, m in ev)
    run("stock")


def test_po_critical_threshold_sets_severity():
    with setting("ops.po_overdue_critical_days", "100000"):
        assert run("operations").returncode == 0
        assert {s for _, _, s, _ in open_events("OPS-A02")} == {"WARNING"}
    assert run("operations").returncode == 0
    days = q("SELECT metric_value, severity FROM insight.alert_event WHERE alert_code = 'OPS-A02' AND status = 'OPEN'")
    assert all((s == "CRITICAL") == (d > 14) for d, s in days)


def test_po_alerts_are_one_per_purchase_order_and_only_purchases():
    ev = q("SELECT document_ref FROM insight.alert_event WHERE alert_code = 'OPS-A02' AND status = 'OPEN'")
    refs = [r for r, in ev]
    assert len(refs) == len(set(refs)) and all(refs)
    expected = q("SELECT count(DISTINCT po_number) FROM mart.v_open_purchase_orders WHERE document_type = 'PURCHASE' "
                 "AND has_due_date AND days_overdue > 0 AND pending_qty > 0")[0][0]
    assert len(refs) == expected


def test_stockout_only_continued_trading_products_at_known_sellable_locations():
    bad = q("SELECT count(*) FROM insight.alert_event e JOIN core.dim_product p USING (product_key) "
            "JOIN core.dim_location l USING (location_key) WHERE e.alert_code IN ('STK-A01','STK-A02') AND e.status = 'OPEN' "
            "AND (p.lifecycle_status <> 'CONTINUED' OR p.item_type <> 'TRADING' OR NOT l.is_sellable_stock "
            "OR l.location_type = 'PARTNER_CONSIGNMENT' OR p.product_key <= 0 OR l.location_key <= 0)")[0][0]
    assert bad == 0


def test_rule_switched_off_raises_nothing_and_closes_its_alerts():
    with rule("STK-A01", is_active=False):
        r = run("stock")
        assert r.returncode == 0 and "STK-A01 off" in r.stdout
        assert open_events("STK-A01") == []
    assert run("stock").returncode == 0
    assert open_events("STK-A01")


def test_rule_without_data_for_its_process_is_skipped():
    before = open_events("STK-A02")
    with rule("STK-A02", process_name="Courier cost"):      # coverage NONE
        r = run("stock")
        assert r.returncode == 0 and "STK-A02 skipped: no Courier cost data" in r.stdout
        assert open_events("STK-A02") == before            # skipped means untouched, not resolved
    run("stock")


def test_agent_switch_off_writes_no_run():
    n = q("SELECT count(*) FROM insight.model_run WHERE agent = 'STOCK'")[0][0]
    with setting("agent.stock.enabled", "false"):
        r = run("stock")
        assert r.returncode == 0 and "switched off" in r.stdout
    assert q("SELECT count(*) FROM insight.model_run WHERE agent = 'STOCK'")[0][0] == n


def test_missing_or_invalid_setting_refuses_to_start():
    n = q("SELECT count(*) FROM insight.model_run")[0][0]
    with setting("stock.low_cover_days", None):
        r = run("stock")
        assert r.returncode == 3 and "stock.low_cover_days" in r.stderr
    with setting("stock.low_cover_days", "seven"):
        assert run("stock").returncode == 3
    assert q("SELECT count(*) FROM insight.model_run")[0][0] == n


def test_failed_latest_build_refuses_to_start():
    n = q("SELECT count(*) FROM insight.model_run")[0][0]
    rid = q("INSERT INTO meta.transform_run (status, period_start, period_end, partner_list_complete, started_by, finished_at, notes) "
            "SELECT 'FAILED', period_start, period_end, partner_list_complete, 'pytest', CURRENT_TIMESTAMP, 'test' "
            "FROM meta.transform_run ORDER BY transform_run_id DESC LIMIT 1 RETURNING transform_run_id")[0][0]
    try:
        r = run()
        assert r.returncode == 3 and "not SUCCEEDED" in r.stderr
        assert q("SELECT count(*) FROM insight.model_run")[0][0] == n
    finally:
        x("DELETE FROM meta.transform_run WHERE transform_run_id = %s", rid)


def test_a_failing_rule_marks_the_run_failed_and_writes_nothing(monkeypatch):
    sys.path.insert(0, str(ROOT))
    import agents.__main__ as runner
    before = q("SELECT count(*), max(alert_id) FROM insight.alert_event")
    monkeypatch.setitem(runner.RULES, "STK-A02", "SELECT 1/0")
    with psycopg.connect(dbname=DB, autocommit=False) as conn:
        with pytest.raises(psycopg.errors.DivisionByZero):
            runner.run_agent(conn, "STOCK", "pytest")
    assert q("SELECT count(*), max(alert_id) FROM insight.alert_event") == before
    st = q("SELECT status, notes FROM insight.model_run ORDER BY run_id DESC LIMIT 1")[0]
    assert st[0] == "FAILED" and "DivisionByZero" in st[1]


def test_app_login_can_read_the_agent_views_and_nothing_else_new():
    for v in ("v_agent_alerts", "v_agent_rules", "v_agent_runs"):
        assert q("SELECT has_table_privilege('ellementry_metrics', %s, 'SELECT')", f"mart.{v}")[0][0], v
    assert not q("SELECT has_schema_privilege('ellementry_metrics', 'insight', 'USAGE')")[0][0]
    cols = {c for c, in q("SELECT column_name FROM information_schema.columns WHERE table_schema = 'mart' "
                         "AND table_name = 'v_agent_rules'")}
    assert {"alert_code", "rule_name", "current_settings", "is_active"} <= cols
    s = q("SELECT current_settings FROM mart.v_agent_rules WHERE alert_code = 'STK-A02'")[0][0]
    assert s.startswith("stock.low_cover_days = ")
