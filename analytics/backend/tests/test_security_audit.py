"""Regression tests for the security audit.

Each test pins a confirmed vulnerability so it cannot silently return:
  SEC-1  CTE-name shadowing bypassed the schema allow-list (cross-tenant pg_catalog / pg_stats read).
  SEC-2  Spreadsheet formula injection in CSV/XLSX exports.
  SEC-3  Upload size limit was enforced only after the whole file was buffered in memory.
"""
import pytest

from app.routers.data import _csv_safe
from app.services.sql_safety import UnsafeSQLError, validate_select

from conftest import api, upload_csv

SCHEMA = "ws_audit"
ALLOWED = {"sales", "products"}


# ----------------------------------------------------------------------------------- SEC-1 CTE shadowing

@pytest.mark.parametrize("sql", [
    # a dummy CTE in a sibling sub-query must not whitelist a same-named real table in an outer scope
    "SELECT nspname FROM pg_namespace, (WITH pg_namespace AS (SELECT 1 a) SELECT a FROM pg_namespace) z",
    "SELECT * FROM pg_stats, (WITH pg_stats AS (SELECT 1 a) SELECT a FROM pg_stats) s",
    "SELECT schemaname FROM pg_tables, (WITH pg_tables AS (SELECT 1 a) SELECT a FROM pg_tables) z",
    # a non-recursive CTE referring to its own name reads the physical table, not the CTE
    "WITH pg_stats AS (SELECT * FROM pg_stats) SELECT * FROM pg_stats",
    "WITH pg_class AS (SELECT * FROM pg_class) SELECT * FROM pg_class",
    "SELECT * FROM (WITH pg_roles AS (SELECT 1) SELECT 1) a, pg_roles",
])
def test_cte_shadowing_cannot_reach_system_catalogs(sql):
    with pytest.raises(UnsafeSQLError):
        validate_select(sql, SCHEMA, ALLOWED)


@pytest.mark.parametrize("sql", [
    "WITH t AS (SELECT sku FROM sales) SELECT t.sku FROM t JOIN products p ON p.sku = t.sku",
    "WITH a AS (SELECT * FROM sales), b AS (SELECT * FROM a) SELECT * FROM b",
    # (recursive CTEs are rejected by policy since the hardening pass; see test_hardening.py)
    # shadowing a catalog name with a dummy CTE and only reading the dummy is harmless
    "WITH pg_stats AS (SELECT 1 AS a) SELECT a FROM pg_stats",
])
def test_legitimate_ctes_still_accepted(sql):
    assert validate_select(sql, SCHEMA, ALLOWED)


def test_cte_shadow_blocked_live(client):
    """End to end through /sql: a workspace member cannot read another tenant's catalog metadata."""
    r = client.post("/api/workspaces", json={"name": "sec-live"})
    ws = r.json()["id"]
    try:
        attack = ("SELECT schemaname, tablename FROM pg_tables, "
                  "(WITH pg_tables AS (SELECT 1 a) SELECT a FROM pg_tables) z WHERE schemaname LIKE 'ws_%'")
        resp = client.post(f"/api/workspaces/{ws}/sql", json={"sql": attack})
        assert resp.status_code == 400, resp.text
        assert "inaccessible" in resp.text or "not allowed" in resp.text
    finally:
        client.delete(f"/api/workspaces/{ws}")


# ----------------------------------------------------------------------------------- SEC-2 CSV injection

@pytest.mark.parametrize("payload", ["=1+1", "+1", "-1+1", "@SUM(A1)", "=cmd|'/c calc'!A1", "\t=1", "\r=1"])
def test_csv_safe_neutralises_formulas(payload):
    assert _csv_safe(payload) == "'" + payload


@pytest.mark.parametrize("value", ["plain", "Amazon", "", "123", "a=b"])
def test_csv_safe_leaves_normal_text(value):
    assert _csv_safe(value) == value


def test_export_endpoint_sanitizes(client):
    r = client.post("/api/workspaces", json={"name": "sec-export"})
    ws = r.json()["id"]
    try:
        ds = upload_csv(client, ws, "x.csv", "label,amount\n=2+5,10\nnormal,20\n", name="X")["dataset"]
        resp = client.get(api(ws, f"/datasets/{ds['id']}/export"), params={"format": "csv"})
        assert resp.status_code == 200
        assert "'=2+5" in resp.text  # leading-equals cell was quoted
    finally:
        client.delete(f"/api/workspaces/{ws}")


# ----------------------------------------------------------------------------------- SEC-3 upload size cap

def test_upload_size_enforced(client):
    from app.config import get_settings

    r = client.post("/api/workspaces", json={"name": "sec-upload"})
    ws = r.json()["id"]
    s = get_settings()
    original = s.max_upload_mb
    s.max_upload_mb = 0  # anything non-empty must now be rejected, before buffering
    try:
        resp = client.post(f"/api/workspaces/{ws}/uploads", files={"file": ("big.csv", b"a,b\n1,2\n")})
        assert resp.status_code == 400
        assert "larger than" in resp.text
    finally:
        s.max_upload_mb = original
        client.delete(f"/api/workspaces/{ws}")


# ----------------------------------------------------------------------------------- SEC-4 robustness

def test_non_list_filters_is_400_not_500(client):
    r = client.post("/api/workspaces", json={"name": "sec-filters"})
    ws = r.json()["id"]
    try:
        ds = upload_csv(client, ws, "f.csv", "sku,amt\nP1,1\n", name="F")["dataset"]
        resp = client.get(api(ws, f"/datasets/{ds['id']}/rows"), params={"filters": "123"})
        assert resp.status_code == 400, resp.text
    finally:
        client.delete(f"/api/workspaces/{ws}")
