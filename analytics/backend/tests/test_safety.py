"""Static SQL / expression validation and the runtime guards of the executor."""
import pytest
from sqlalchemy import text

from app.db import get_engine
from app.services.executor import QueryExecutionError, run_readonly
from app.services.expressions import ExpressionError, validate_expression
from app.services.sql_safety import UnsafeSQLError, referenced_tables, validate_select

SCHEMA = "ws_safetytest"
ALLOWED = {"sales", "products"}


def ok(sql: str, **kw) -> str:
    return validate_select(sql, SCHEMA, ALLOWED, **kw)


def bad(sql: str) -> str:
    with pytest.raises(UnsafeSQLError) as ei:
        validate_select(sql, SCHEMA, ALLOWED)
    return str(ei.value)


# ----------------------------------------------------------------------------------------------- accepted

@pytest.mark.parametrize("sql", [
    "SELECT * FROM sales",
    "select region, sum(amount) as total from sales group by region order by 2 desc",
    "WITH t AS (SELECT sku, SUM(qty) AS q FROM sales GROUP BY sku) SELECT p.name, t.q FROM t JOIN products p ON p.sku = t.sku",
    "SELECT sku FROM sales UNION SELECT sku FROM products",
    "SELECT sku FROM sales UNION ALL SELECT sku FROM products EXCEPT SELECT 'x'",
    "SELECT sku, amount, SUM(amount) OVER (PARTITION BY sku ORDER BY sale_date) AS running, "
    "RANK() OVER (ORDER BY amount DESC) AS rnk FROM sales",
    f"SELECT * FROM {SCHEMA}.sales",
    "SELECT date_trunc('month', sale_date)::date AS m, COUNT(*) FROM sales WHERE amount > 10 GROUP BY 1",
    "SELECT * FROM sales s LEFT JOIN products p ON p.sku = s.sku WHERE s.sku IN (SELECT sku FROM products)",
    "SELECT * FROM sales;",
])
def test_accepts_read_only_selects(sql):
    out = ok(sql)
    assert out.upper().startswith(("SELECT", "WITH"))


def test_limit_wrapper_added():
    out = ok("SELECT * FROM sales", row_limit=100)
    assert out.startswith("SELECT * FROM (") and out.endswith("LIMIT 101")
    assert "_ellementry_q" in out


def test_referenced_tables_ignores_ctes():
    assert referenced_tables("WITH x AS (SELECT * FROM sales) SELECT * FROM x JOIN products ON true") == {"sales", "products"}


# ----------------------------------------------------------------------------------------------- rejected

@pytest.mark.parametrize("sql", [
    "INSERT INTO sales VALUES (1)",
    "UPDATE sales SET amount = 0",
    "DELETE FROM sales",
    "DROP TABLE sales",
    "ALTER TABLE sales ADD COLUMN x int",
    "CREATE TABLE x AS SELECT * FROM sales",
    "COPY sales TO '/tmp/out.csv'",
    "COPY (SELECT * FROM sales) TO PROGRAM 'rm -rf /'",
    "GRANT ALL ON sales TO public",
    "SET search_path = public",
    "SET ROLE postgres",
    "TRUNCATE sales",
    "VACUUM sales",
    "BEGIN",
    "CALL some_proc()",
    "DO $$ BEGIN PERFORM 1; END $$",
])
def test_rejects_non_select_statements(sql):
    bad(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE sales",
    "SELECT * FROM sales; SELECT * FROM products",
    "SELECT * INTO new_table FROM sales",
    "SELECT * FROM sales FOR UPDATE",
    "SELECT * FROM sales FOR SHARE",
    "WITH d AS (DELETE FROM sales RETURNING *) SELECT * FROM d",
    "WITH u AS (UPDATE sales SET amount = 0 RETURNING *) SELECT * FROM u",
])
def test_rejects_multi_statements_into_locks_and_writable_ctes(sql):
    bad(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM pg_catalog.pg_class",
    "SELECT * FROM pg_class",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM ellementry_meta.workspaces",
    "SELECT * FROM public.anything",
    "SELECT * FROM ws_other.sales",
    "SELECT * FROM otherdb.ws_safetytest.sales",
    "SELECT * FROM _raw_sales",
    "SELECT * FROM customers",
    "SELECT * FROM sales JOIN pg_user ON true",
    "SELECT (SELECT usename FROM pg_user LIMIT 1) FROM sales",
    "SELECT * FROM generate_series(1, 10)",
])
def test_rejects_other_schemas_raw_and_unknown_tables(sql):
    bad(sql)


def test_raw_table_rejected_even_if_listed_as_allowed():
    with pytest.raises(UnsafeSQLError):
        validate_select("SELECT * FROM _raw_sales", SCHEMA, ALLOWED | {"_raw_sales"})


@pytest.mark.parametrize("sql", [
    "SELECT pg_sleep(10)",
    "SELECT * FROM sales WHERE pg_sleep(1) IS NOT NULL",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_ls_dir('.')",
    "SELECT * FROM dblink('host=evil', 'select 1') AS t(x int)",
    "SELECT dblink_exec('host=evil', 'drop table x')",
    "SELECT set_config('statement_timeout', '0', false)",
    "SELECT current_setting('data_directory')",
    "SELECT lo_import('/etc/passwd')",
    "SELECT version()",
    "SELECT current_user",
    "SELECT nextval('seq')",
    "SELECT txid_current()",
    "SELECT query_to_xml('select 1', true, true, '')",
])
def test_rejects_dangerous_functions(sql):
    bad(sql)


@pytest.mark.parametrize("sql", [
    "SELECT $$abc$$ FROM sales",
    "SELECT $tag$abc$tag$ FROM sales",
    "SELECT $q$x$q$; DROP TABLE sales; SELECT $q$y$q$",
])
def test_rejects_dollar_quoting(sql):
    bad(sql)


def test_rejects_empty_and_too_long():
    bad("")
    bad("   ")
    bad("SELECT 1 FROM sales WHERE " + " OR ".join(["amount = 1"] * 3000))


def test_rejects_garbage():
    bad("SELEC * FRM sales")


# ----------------------------------------------------------------------------------------------- expressions

COLS = {"qty", "price", "name", "order_date", "region"}


@pytest.mark.parametrize("expr", [
    "qty * price",
    "(qty + 1) / NULLIF(price, 0)",
    "CASE WHEN qty > 10 THEN 'big' WHEN qty > 0 THEN 'small' ELSE 'none' END",
    "ROUND(price * 1.18, 2)",
    "COALESCE(price, 0) - ABS(qty)",
    "UPPER(TRIM(name)) || '-' || LOWER(region)",
    "date_trunc('month', order_date)",
    "EXTRACT(YEAR FROM order_date)",
    "CAST(qty AS NUMERIC) / 2",
    "qty BETWEEN 1 AND 5",
    "region IN ('North', 'South')",
    "name ILIKE '%kadai%'",
    "GREATEST(qty, 0)",
])
def test_expression_allowed(expr):
    out = validate_expression(expr, COLS)
    assert out


@pytest.mark.parametrize("expr,msg", [
    ("(SELECT 1)", "ubquer"),
    ("qty + (SELECT max(qty) FROM sales)", "ubquer"),
    ("qty IN (SELECT qty FROM other)", "ubquer"),
    ("unknown_col * 2", "Unknown column"),
    ("s.qty * 2", "Qualified"),
    ("SUM(qty)", "only allowed in metrics"),
    ("COUNT(*)", "only allowed in metrics"),
    ("pg_sleep(1)", "not allowed"),
    ("version()", "not allowed"),
    ("random()", "not allowed"),
    ("qty; DROP TABLE x", "Semicolons"),
    ("", "empty"),
])
def test_expression_rejected(expr, msg):
    with pytest.raises(ExpressionError) as ei:
        validate_expression(expr, COLS)
    assert msg.lower() in str(ei.value).lower()


def test_metric_expressions():
    assert "SUM" in validate_expression("SUM(qty * price)", COLS, allow_aggregates=True).upper()
    assert validate_expression("COUNT(DISTINCT name)", COLS, allow_aggregates=True)
    assert validate_expression("SUM(qty) / NULLIF(COUNT(*), 0)", COLS, allow_aggregates=True)
    with pytest.raises(ExpressionError, match="aggregate"):
        validate_expression("qty * price", COLS, allow_aggregates=True)
    with pytest.raises(ExpressionError):
        validate_expression("SUM(nope)", COLS, allow_aggregates=True)


# ----------------------------------------------------------------------------------------------- runtime guards

@pytest.fixture(scope="module")
def scratch(client):
    eng = get_engine()
    with eng.begin() as c:
        c.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
        c.execute(text(f'DROP TABLE IF EXISTS "{SCHEMA}".sales'))
        c.execute(text(f'CREATE TABLE "{SCHEMA}".sales (sku text, amount numeric)'))
        c.execute(text(f"INSERT INTO \"{SCHEMA}\".sales VALUES ('a', 1), ('b', 2)"))
    yield SCHEMA
    with eng.begin() as c:
        c.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))


def _count(schema):
    with get_engine().connect() as c:
        return c.execute(text(f'SELECT count(*) FROM "{schema}".sales')).scalar()


def test_run_readonly_returns_rows_and_uses_search_path(scratch):
    res = run_readonly("SELECT sku, amount FROM sales ORDER BY sku", {}, scratch)
    assert res.columns == ["sku", "amount"]
    assert res.rows == [["a", 1.0], ["b", 2.0]]
    assert not res.truncated


def test_run_readonly_row_limit(scratch):
    res = run_readonly("SELECT sku FROM sales", {}, scratch, row_limit=1)
    assert res.row_count == 1 and res.truncated


@pytest.mark.parametrize("sql", [
    "WITH d AS (DELETE FROM sales RETURNING *) SELECT count(*) FROM d",
    "WITH u AS (UPDATE sales SET amount = 0 RETURNING *) SELECT * FROM u",
    "INSERT INTO sales VALUES ('c', 3)",
    "CREATE TABLE sneaky (x int)",
])
def test_writes_blocked_at_runtime_when_validator_bypassed(scratch, sql):
    before = _count(scratch)
    with pytest.raises(QueryExecutionError) as ei:
        run_readonly(sql, {}, scratch)
    assert "not allowed" in str(ei.value) or "read-only" in str(ei.value)
    assert _count(scratch) == before


def test_set_config_cannot_escape_read_only(scratch):
    with pytest.raises(QueryExecutionError):
        run_readonly("SELECT set_config('transaction_read_only', 'off', true); DELETE FROM sales", {}, scratch)
    assert _count(scratch) == 2


def test_statement_timeout(scratch):
    with pytest.raises(QueryExecutionError) as ei:
        run_readonly("SELECT pg_sleep(3)", {}, scratch, timeout_ms=200)
    msg = str(ei.value)
    assert "took longer than" in msg and "cancelled" in msg
    assert "0.2s" in msg  # sub-second timeouts are reported precisely


def test_search_path_hides_other_schemas(scratch):
    with pytest.raises(QueryExecutionError):
        run_readonly("SELECT * FROM workspaces", {}, scratch)  # ellementry_meta table, not on the search path


def test_sql_console_endpoint(client, workspace):
    from conftest import api, upload_csv

    ws = workspace["id"]
    upload_csv(client, ws, "s.csv", "sku,amount\na,1\nb,2\n", name="Sales")
    r = client.post(api(ws, "/sql"), json={"sql": "SELECT sku, amount FROM sales ORDER BY sku"})
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [["a", 1], ["b", 2]]
    for sql in ("DELETE FROM sales", "SELECT * FROM ellementry_meta.workspaces", "SELECT * FROM _raw_sales", "SELECT pg_sleep(1)"):
        r = client.post(api(ws, "/sql"), json={"sql": sql})
        assert r.status_code == 400, sql
    hist = client.get(api(ws, "/history"), params={"source": "sql"}).json()
    assert {h["status"] for h in hist} >= {"ok", "rejected"}
