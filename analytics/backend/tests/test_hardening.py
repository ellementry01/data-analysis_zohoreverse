"""Regression tests for post-audit hardening: DoS functions, recursive CTEs, headers, error opacity, zip bombs."""
import zipfile

import pytest

from app.services.ingest import IngestError, read_grids
from app.services.sql_safety import UnsafeSQLError, validate_select


@pytest.mark.parametrize("sql", [
    "SELECT repeat('x', 1000000000)",
    "SELECT current_database()",
    "SELECT current_query()",
    "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT * FROM r",
    "SELECT * FROM t, (WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT n FROM r) x",
])
def test_amplification_and_fingerprinting_rejected(sql):
    with pytest.raises(UnsafeSQLError):
        validate_select(sql, "ws_x", {"t"})


def test_normal_cte_still_allowed():
    out = validate_select("WITH a AS (SELECT c, SUM(v) AS s FROM t GROUP BY c) SELECT * FROM a", "ws_x", {"t"})
    assert "SUM" in out.upper()


def test_security_headers_on_api_and_spa(client):
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"


def test_unhandled_errors_are_opaque(client, monkeypatch):
    from app.routers import workspaces

    def boom(*a, **k):
        raise RuntimeError("secret internal detail: password=hunter2")

    monkeypatch.setattr(workspaces.llm, "enabled", boom)
    c = type(client)(client.app, raise_server_exceptions=False)
    r = c.get("/api/me")
    assert r.status_code == 500
    assert "hunter2" not in r.text and "reference" in r.json()["detail"]


def test_xlsx_zip_bomb_rejected(tmp_path):
    p = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(p, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"\0" * (120 * 1024 ** 2))
    with pytest.raises(IngestError, match="unreasonable size"):
        read_grids(str(p), "bomb.xlsx")


def test_not_a_zip_rejected_cleanly(tmp_path):
    p = tmp_path / "fake.xlsx"
    p.write_bytes(b"this is not a workbook")
    with pytest.raises(IngestError):
        read_grids(str(p), "fake.xlsx")


@pytest.mark.parametrize("name", ["LLM_API_KEY", "ELLEMENTRY_SECRET_KEY", "DATABASE_URL", "ellementry_conn_x", "ELLEMENTRY_CONN_"])
def test_connector_password_env_restricted_to_dedicated_prefix(client, workspace, name):
    r = client.post(f"/api/workspaces/{workspace['id']}/connectors",
                    json={"name": "x", "kind": "postgresql", "config": {"host": "evil.example", "database": "d", "user": "u", "password_env": name}})
    assert r.status_code == 400 and "ELLEMENTRY_CONN_" in r.json()["detail"]


def test_connector_password_env_read_from_dotenv(monkeypatch, tmp_path):
    from app.services import connectors

    (tmp_path / ".env").write_text("ELLEMENTRY_CONN_TEST_PASSWORD=from-dotenv\n")
    monkeypatch.setattr("app.config.BACKEND_DIR", str(tmp_path))
    monkeypatch.delenv("ELLEMENTRY_CONN_TEST_PASSWORD", raising=False)
    assert connectors._password({"password_env": "ELLEMENTRY_CONN_TEST_PASSWORD"}) == "from-dotenv"


def test_connector_import_of_empty_table_keeps_source_types(client, workspace):
    """Empty source tables must not be imported as all-text (types come from the source schema)."""
    from sqlalchemy import text as sa_text

    from app.db import get_engine

    with get_engine().begin() as c:
        c.execute(sa_text("CREATE SCHEMA IF NOT EXISTS conn_empty_src"))
        c.execute(sa_text("DROP TABLE IF EXISTS conn_empty_src.sales_empty"))
        c.execute(sa_text("CREATE TABLE conn_empty_src.sales_empty (sale_date date, created_at timestamp, qty integer, "
                          "amount numeric(12,2), is_return boolean, channel text)"))
    url = get_engine().url
    base = f"/api/workspaces/{workspace['id']}"
    r = client.post(f"{base}/connectors", json={"name": "src", "kind": "postgresql", "config": {
        "host": url.host or "localhost", "port": str(url.port or 5432), "database": url.database, "user": url.username, "schema": "conn_empty_src"}})
    assert r.status_code == 201, r.text
    r = client.post(f"{base}/connectors/{r.json()['id']}/import", json={"tables": [{"schema": "conn_empty_src", "table": "sales_empty"}]})
    assert r.status_code == 201, r.text
    ds = client.get(f"{base}/datasets/{r.json()[0]['id']}").json()
    assert ds["row_count"] == 0
    assert {c["name"]: c["data_type"] for c in ds["columns"]} == {
        "sale_date": "date", "created_at": "datetime", "qty": "integer", "amount": "decimal", "is_return": "boolean", "channel": "text"}


def test_how_many_dataset_counts_rows_even_when_word_is_also_a_data_value():
    from app.services.catalog import DS, Catalog, Col
    from app.services.nlq.parser import interpret
    from app.services.nlq.vocab import build_vocab

    loc = DS(1, "locations", "Locations", "file", {"location_code": Col("location_code", "Location code", "text"),
                                                   "location_type": Col("location_type", "Location type", "text")}, None, 3)
    notes = DS(2, "notes", "Notes", "file", {"topic": Col("topic", "Topic", "text")}, None, 2)
    cat = Catalog(1, "ws_t", {1: loc, 2: notes}, [], {}, {})
    vocab = build_vocab(cat, {(2, "topic"): ["Locations", "Pricing"]})  # "locations" is also a data value
    it = interpret("How many locations by location type?", cat, vocab)
    assert it.kind == "query"
    assert [m.field for m in it.spec.measures] == ["locations.*"]
    assert [d.field for d in it.spec.dimensions] == ["locations.location_type"]
    assert not it.spec.filters


def test_empty_result_explained_as_no_data():
    from app.services.nlq.assistant import template_explanation

    res = {"columns": [{"name": "net_sales", "label": "Net sales", "role": "measure", "type": "decimal"}],
           "rows": [[None]], "date_range": ["2026-09-01", "2026-09-30"]}
    assert template_explanation("t", res, []).startswith("There is no data for this (2026-09-01 to 2026-09-30)")
