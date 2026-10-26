"""The semantic query engine (/query) on a tiny hand-computed model. Today is pinned to 2026-10-17.

Sales (amount, qty, txn_type):              Returns:            Stock snapshots (semi-additive):
 1 2026-07-10 P1 Shopify 2 200 Sale          2026-08-10 P1 1      2026-08-31 P1 7, P2 8
 2 2026-08-05 P1 Amazon  1 100 Sale          2026-09-10 P2 2      2026-09-01 P1 10, P2 20
 3 2026-08-20 P2 Shopify 3 450 Sale          2026-09-12 P1 1      2026-09-30 P1 15, P2 5
 4 2026-09-02 P1 Amazon  4 400 Sale
 5 2026-09-15 P2 Amazon  1 150 Sale         Spend: 2026-08-10 Amazon 30, 2026-09-01 Shopify 100,
 6 2026-09-28 P3 Shopify 2  60 Sale                2026-09-15 Amazon 50
 7 2026-09-30 P1 Shopify 5 500 Transfer
 8 2026-10-05 P3 Amazon  1  30 Sale         Products: P1 Widget/Tools, P2 Gadget/Tools, P3 Gizmo/Toys
"""
import pytest

from conftest import api, build_mini


@pytest.fixture(scope="module")
def mini(client):
    m = build_mini(client, "qe")
    yield m
    client.delete(f"/api/workspaces/{m['ws']}")


def run(client, mini, spec: dict, status: int = 200) -> dict:
    r = client.post(api(mini["ws"], "/query"), json=spec)
    assert r.status_code == status, r.text
    return r.json()


def table(res: dict) -> dict:
    """{dims tuple (or single value): measures tuple (or single value)}"""
    cols = res["columns"]
    di = [i for i, c in enumerate(cols) if c["role"] == "dimension"]
    mi = [i for i, c in enumerate(cols) if c["role"] == "measure"]
    out = {}
    for r in res["rows"]:
        k = tuple(r[i] for i in di)
        v = tuple(r[i] for i in mi)
        out[k[0] if len(k) == 1 else k] = v[0] if len(v) == 1 else v
    return out


def scalar(res: dict):
    assert res["row_count"] == 1
    return res["rows"][0][0]


AMOUNT = {"field": "sales.amount", "agg": "sum"}


# ----------------------------------------------------------------------------------------------- aggregations

def test_basic_aggregations(client, mini):
    res = run(client, mini, {"measures": [
        {"field": "sales.amount", "agg": "sum"}, {"field": "sales.amount", "agg": "avg"}, {"field": "sales.*", "agg": "count"},
        {"field": "sales.sku", "agg": "count_distinct"}, {"field": "sales.amount", "agg": "min"}, {"field": "sales.amount", "agg": "max"},
        {"field": "sales.qty", "agg": "median"}]})
    assert res["rows"][0] == pytest.approx([1890.0, 236.25, 8, 3, 30.0, 500.0, 2.0])
    assert res["suggested_chart"] == "kpi"
    assert res["sql"].upper().startswith("WITH")
    labels = [c["label"] for c in res["columns"]]
    assert labels[0] == "Total Amount" and labels[2] == "Number of Sales rows"


def test_metric_direction_reaches_the_result(client, mini):
    # a rising return rate must not be shown as good: the metric's direction travels with its column
    mid = next(m["id"] for m in client.get(api(mini["ws"], "/metrics")).json() if m["name"] == "return_rate")
    m = next(x for x in client.get(api(mini["ws"], "/metrics")).json() if x["name"] == "return_rate")
    m = {k: v for k, v in m.items() if k != "id"} | {"higher_is_better": False}
    assert client.put(api(mini["ws"], f"/metrics/{mid}"), json=m).status_code == 200
    try:
        cols = run(client, mini, {"measures": [{"metric": "return_rate"}, {"metric": "net_sales"}]})["columns"]
        assert [c["higher_is_better"] for c in cols] == [False, True]
    finally:
        assert client.put(api(mini["ws"], f"/metrics/{mid}"), json=m | {"higher_is_better": True}).status_code == 200


def test_sum_on_text_column_rejected(client, mini):
    r = run(client, mini, {"measures": [{"field": "sales.channel", "agg": "sum"}]}, status=400)
    assert "count" in r["detail"]


def test_dimension_and_default_sort(client, mini):
    res = run(client, mini, {"dimensions": [{"field": "sales.channel"}], "measures": [AMOUNT]})
    assert table(res) == {"Shopify": 1210.0, "Amazon": 680.0}
    assert [r[0] for r in res["rows"]] == ["Shopify", "Amazon"]  # measure desc by default


def test_time_grain_month(client, mini):
    res = run(client, mini, {"dimensions": [{"field": "sales.sale_date", "grain": "month"}], "measures": [AMOUNT]})
    assert table(res) == {"2026-07-01": 200.0, "2026-08-01": 550.0, "2026-09-01": 1110.0, "2026-10-01": 30.0}
    assert [r[0] for r in res["rows"]] == sorted(r[0] for r in res["rows"])  # time ascending
    assert res["suggested_chart"] == "line"
    assert any(i["type"] == "partial" for i in res["insights"])  # October is still in progress
    res = run(client, mini, {"dimensions": [{"field": "@time", "grain": "quarter"}], "measures": [AMOUNT]})
    assert table(res) == {"2026-07-01": 1860.0, "2026-10-01": 30.0}


@pytest.mark.parametrize("rng,expected,dates", [
    ("last_month", 1110.0, ["2026-09-01", "2026-09-30"]),
    ("this_month", 30.0, ["2026-10-01", "2026-10-17"]),
    ({"preset": "last_3_months"}, 1860.0, ["2026-07-01", "2026-09-30"]),
    ({"last": 2, "unit": "months"}, 1660.0, ["2026-08-01", "2026-09-30"]),
    ({"from": "2026-08-01", "to": "2026-08-31"}, 550.0, ["2026-08-01", "2026-08-31"]),
    ({"from": "2026-09-30", "to": "2026-09-30"}, 500.0, ["2026-09-30", "2026-09-30"]),
    ("last_quarter", 1860.0, ["2026-07-01", "2026-09-30"]),
    ("this_year", 1890.0, ["2026-01-01", "2026-10-17"]),
    ("last_year", None, ["2025-01-01", "2025-12-31"]),
    ("last_30_days", 590.0, ["2026-09-18", "2026-10-17"]),
])
def test_date_range_presets(client, mini, rng, expected, dates):
    res = run(client, mini, {"measures": [AMOUNT], "time_range": rng})
    assert scalar(res) == expected
    assert res["date_range"] == dates


def test_bad_date_range(client, mini):
    run(client, mini, {"measures": [AMOUNT], "time_range": "fortnight"}, status=400)
    run(client, mini, {"measures": [AMOUNT], "time_range": {"from": "not-a-date"}}, status=400)


def test_time_field_selects_date_column(client, mini):
    # the returns date range applies to returns' own date column
    res = run(client, mini, {"measures": [{"field": "returns.qty_returned", "agg": "sum"}], "time_range": "last_month"})
    assert scalar(res) == 3


# ----------------------------------------------------------------------------------------------- filters

@pytest.mark.parametrize("flt,expected", [
    ({"field": "sales.channel", "op": "in", "value": ["Amazon"]}, 680.0),
    ({"field": "sales.channel", "op": "in", "value": ["amazon"]}, 680.0),
    ({"field": "sales.channel", "op": "not_in", "value": ["Amazon"]}, 1210.0),
    ({"field": "sales.amount", "op": "between", "value": [100, 400]}, 850.0),
    ({"field": "sales.amount", "op": "between", "value": [None, 100]}, 190.0),
    ({"field": "sales.channel", "op": "contains", "value": "shop"}, 1210.0),
    ({"field": "sales.channel", "op": "not_contains", "value": "shop"}, 680.0),
    ({"field": "sales.channel", "op": "starts_with", "value": "Am"}, 680.0),
    ({"field": "sales.qty", "op": "gte", "value": 4}, 900.0),
    ({"field": "sales.sale_date", "op": "lt", "value": "2026-08-06"}, 300.0),
    ({"field": "sales.txn_type", "op": "neq", "value": "Transfer"}, 1390.0),
    ({"field": "sales.sale_date", "op": "date_range", "value": "last_month"}, 1110.0),
    ({"field": "products.category", "op": "eq", "value": "Toys"}, 90.0),
    ({"field": "sales.channel", "op": "is_null"}, None),
])
def test_filters(client, mini, flt, expected):
    assert scalar(run(client, mini, {"measures": [AMOUNT], "filters": [flt]})) == expected


def test_filter_values_are_bound_not_inlined(client, mini):
    evil = "x'); DROP TABLE sales; --"
    res = run(client, mini, {"measures": [AMOUNT], "filters": [{"field": "sales.channel", "op": "eq", "value": evil}]})
    assert scalar(res) is None
    assert run(client, mini, {"measures": [AMOUNT]})["rows"][0][0] == 1890.0


def test_invalid_filters(client, mini):
    run(client, mini, {"measures": [AMOUNT], "filters": [{"field": "sales.qty", "op": "eq", "value": "abc"}]}, status=400)
    run(client, mini, {"measures": [AMOUNT], "filters": [{"field": "sales.qty", "op": "regex", "value": "1"}]}, status=400)
    run(client, mini, {"measures": [AMOUNT], "filters": [{"field": "sales.nope", "op": "eq", "value": "1"}]}, status=400)


# ----------------------------------------------------------------------------------------------- joins

def test_dimension_from_lookup_table(client, mini):
    res = run(client, mini, {"dimensions": [{"field": "products.category"}], "measures": [AMOUNT]})
    assert table(res) == {"Tools": 1800.0, "Toys": 90.0}
    assert "LEFT JOIN" in res["sql"]
    res = run(client, mini, {"dimensions": [{"field": "products.product_name"}, {"field": "channels.channel_type"}], "measures": [AMOUNT]})
    assert table(res)[("Widget", "D2C")] == 700.0


def test_multi_fact_no_fan_out(client, mini):
    res = run(client, mini, {"dimensions": [{"field": "products.category"}],
                             "measures": [{"field": "sales.qty", "agg": "sum"}, {"field": "returns.qty_returned", "agg": "sum"}]})
    assert table(res) == {"Tools": (16, 4), "Toys": (3, None)}
    # totals too: a naive join of sales x returns on sku would give 3 x 2 rows for P1
    res = run(client, mini, {"measures": [{"field": "sales.qty", "agg": "sum"}, {"field": "returns.qty_returned", "agg": "sum"}]})
    assert res["rows"][0] == [19, 4]


def test_multi_fact_shared_lookup_and_time(client, mini):
    res = run(client, mini, {"dimensions": [{"field": "channels.channel"}],
                             "measures": [AMOUNT, {"field": "spend.spend", "agg": "sum"}]})
    assert table(res) == {"Shopify": (1210.0, 100.0), "Amazon": (680.0, 80.0)}
    res = run(client, mini, {"dimensions": [{"field": "@time", "grain": "month"}],
                             "measures": [AMOUNT, {"field": "spend.spend", "agg": "sum"}]})
    assert table(res) == {"2026-07-01": (200.0, None), "2026-08-01": (550.0, 30.0), "2026-09-01": (1110.0, 150.0), "2026-10-01": (30.0, None)}


def test_unrelated_dimension_error(client, mini):
    r = run(client, mini, {"dimensions": [{"field": "products.category"}], "measures": [{"field": "spend.spend", "agg": "sum"}]}, status=400)
    assert "relationship" in r["detail"] and "Spend" in r["detail"] and "Category" in r["detail"]


def test_filter_on_unrelated_dataset_warns(client, mini):
    res = run(client, mini, {"measures": [{"field": "spend.spend", "agg": "sum"}],
                             "filters": [{"field": "products.category", "op": "eq", "value": "Toys"}]})
    assert res["rows"][0][0] == 180.0
    assert any("does not apply" in w for w in res["warnings"])


def test_unknown_fields(client, mini):
    assert "Unknown dataset" in run(client, mini, {"measures": [{"field": "nope.x"}]}, status=400)["detail"]
    assert "Unknown column" in run(client, mini, {"measures": [{"field": "sales.nope"}]}, status=400)["detail"]
    run(client, mini, {"measures": [{"metric": "nope"}]}, status=400)
    run(client, mini, {}, status=400)
    run(client, mini, {"measures": [AMOUNT], "sort": [{"field": "nope"}]}, status=400)


# ----------------------------------------------------------------------------------------------- metrics

def test_metric_filter_rule(client, mini):
    res = run(client, mini, {"measures": [{"metric": "net_sales"}, AMOUNT]})
    assert res["rows"][0] == [1390.0, 1890.0]
    assert "FILTER" in res["sql"].upper()
    res = run(client, mini, {"dimensions": [{"field": "sales.sale_date", "grain": "month"}], "measures": [{"metric": "net_sales"}],
                             "time_range": "last_month"})
    assert table(res) == {"2026-09-01": 610.0}


def test_metric_only_groups_hidden(client, mini):
    # P1/Shopify in September only has a Transfer -> excluded by the metric rule, so the group disappears
    res = run(client, mini, {"dimensions": [{"field": "sales.channel"}], "measures": [{"metric": "net_sales"}],
                             "filters": [{"field": "sales.sku", "op": "eq", "value": "P1"}], "time_range": "last_month"})
    assert table(res) == {"Amazon": 400.0}


def test_composite_metric(client, mini):
    res = run(client, mini, {"measures": [{"metric": "return_rate"}, {"metric": "units_sold"}, {"metric": "units_returned"}]})
    assert res["rows"][0] == pytest.approx([4 / 14, 14, 4])
    res = run(client, mini, {"dimensions": [{"field": "products.category"}], "measures": [{"metric": "return_rate"}]})
    t = table(res)
    assert t["Tools"] == pytest.approx(4 / 11) and t.get("Toys") is None
    assert res["columns"][-1]["format"] == "percent" and res["columns"][-1]["additive"] is False


def test_semi_additive_latest_snapshot(client, mini):
    assert scalar(run(client, mini, {"measures": [{"metric": "stock_on_hand"}]})) == 20
    res = run(client, mini, {"dimensions": [{"field": "@time", "grain": "month"}], "measures": [{"metric": "stock_on_hand"}]})
    assert table(res) == {"2026-08-01": 15, "2026-09-01": 20}
    res = run(client, mini, {"dimensions": [{"field": "products.product_name"}], "measures": [{"metric": "stock_on_hand"}]})
    assert table(res) == {"Widget": 15, "Gadget": 5}
    assert scalar(run(client, mini, {"measures": [{"metric": "stock_on_hand"}], "time_range": {"from": "2026-09-01", "to": "2026-09-15"}})) == 30
    # semi-additive and additive measures side by side
    res = run(client, mini, {"dimensions": [{"field": "products.category"}], "measures": [{"metric": "stock_on_hand"}, {"metric": "units_sold"}]})
    assert table(res)["Tools"] == (20, 11)
    assert next(c for c in res["columns"] if c["name"] == "stock_on_hand")["additive"] is False


def test_metric_crud_validation(client, mini):
    ws, ds = mini["ws"], mini["ds"]
    bad = [
        dict(kind="simple", name="Bad Name", label="x", dataset_id=ds["sales"], expression="SUM(qty)"),
        dict(kind="simple", name="m1", label="x", dataset_id=ds["sales"], expression="qty * 2"),
        dict(kind="simple", name="m1", label="x", dataset_id=ds["sales"], expression="SUM(nope)"),
        dict(kind="simple", name="m1", label="x", dataset_id=ds["sales"], expression="SUM(qty)", filters=[{"column": "nope", "value": 1}]),
        dict(kind="simple", name="m1", label="x", dataset_id=ds["sales"], expression="SUM(qty)", time_column="channel"),
        dict(kind="simple", name="m1", label="x", dataset_id=None, expression="SUM(qty)"),
        dict(kind="composite", name="m1", label="x", expression="1 + 1"),
        dict(kind="composite", name="m1", label="x", expression="{nope} / 2"),
        dict(kind="composite", name="m1", label="x", expression="{m1} / 2"),
        dict(kind="simple", name="net_sales", label="x", dataset_id=ds["sales"], expression="SUM(qty)"),
    ]
    for b in bad:
        assert client.post(api(ws, "/metrics"), json=b).status_code == 400, b
    r = client.post(api(ws, "/metrics"), json=dict(kind="simple", name="tmp_units", label="Tmp", dataset_id=ds["sales"], expression="SUM(qty)"))
    assert r.status_code == 201
    mid = r.json()["id"]
    r = client.put(api(ws, f"/metrics/{mid}"), json=dict(kind="simple", name="tmp_units", label="Tmp 2", dataset_id=ds["sales"], expression="MAX(qty)"))
    assert r.status_code == 200 and r.json()["label"] == "Tmp 2"
    assert scalar(run(client, mini, {"measures": [{"metric": "tmp_units"}]})) == 5
    # metrics used by a composite cannot be deleted
    comp = next(x for x in client.get(api(ws, "/metrics")).json() if x["name"] == "units_sold")
    assert client.delete(api(ws, f"/metrics/{comp['id']}")).status_code == 400
    assert client.delete(api(ws, f"/metrics/{mid}")).status_code == 204


# ----------------------------------------------------------------------------------------------- business rules

def test_business_rule_applied(client, mini):
    ws, ds = mini["ws"], mini["ds"]
    r = client.post(api(ws, "/rules"), json={"dataset_id": ds["sales"], "name": "No transfers",
                                             "filters": [{"column": "txn_type", "op": "neq", "value": "Transfer"}]})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    try:
        assert scalar(run(client, mini, {"measures": [AMOUNT]})) == 1390.0
        assert scalar(run(client, mini, {"measures": [AMOUNT], "apply_rules": False})) == 1890.0
        res = run(client, mini, {"dimensions": [{"field": "products.category"}], "measures": [AMOUNT, {"field": "returns.qty_returned", "agg": "sum"}]})
        assert table(res)["Tools"] == (1300.0, 4)  # the rule only touches its own dataset
        r = client.put(api(ws, f"/rules/{rid}"), json={"dataset_id": ds["sales"], "name": "No transfers", "enabled": False,
                                                       "filters": [{"column": "txn_type", "op": "neq", "value": "Transfer"}]})
        assert r.status_code == 200
        assert scalar(run(client, mini, {"measures": [AMOUNT]})) == 1890.0
        assert client.post(api(ws, "/rules"), json={"dataset_id": ds["sales"], "name": "x", "filters": [{"column": "nope"}]}).status_code == 400
        assert client.post(api(ws, "/rules"), json={"dataset_id": ds["sales"], "name": "x", "filters": []}).status_code == 422
    finally:
        assert client.delete(api(ws, f"/rules/{rid}")).status_code == 204


# ----------------------------------------------------------------------------------------------- comparison / sort

def test_compare_previous_period_total(client, mini):
    res = run(client, mini, {"measures": [AMOUNT], "time_range": "last_month", "compare": "previous_period"})
    names = [c["name"] for c in res["columns"]]
    assert names == ["total_amount", "total_amount__prev", "total_amount__change_pct"]
    assert res["rows"][0] == pytest.approx([1110.0, 550.0, round(560 / 550, 4)])
    assert res["comparison"]["previous_range"] == "2026-08-01 to 2026-08-31"
    assert any(i["type"] == "comparison" for i in res["insights"])


def test_compare_previous_period_by_month_and_dimension(client, mini):
    res = run(client, mini, {"dimensions": [{"field": "@time", "grain": "month"}], "measures": [AMOUNT],
                             "time_range": {"last": 2, "unit": "months"}, "compare": "previous_period"})
    # Aug-Sep vs Jun-Jul: months line up by offset
    assert table(res) == {"2026-08-01": (550.0, None, None), "2026-09-01": (1110.0, 200.0, 4.55)}
    res = run(client, mini, {"dimensions": [{"field": "sales.channel"}], "measures": [AMOUNT],
                             "time_range": "last_month", "compare": "previous_period"})
    t = table(res)
    assert t["Amazon"] == pytest.approx((550.0, 100.0, 4.5))
    assert t["Shopify"] == pytest.approx((560.0, 450.0, round(110 / 450, 4)))
    assert "Overall" in res["comparison"]["summary"]


def test_compare_needs_range(client, mini):
    res = run(client, mini, {"measures": [AMOUNT], "compare": "previous_period"})
    assert any("needs a date range" in w for w in res["warnings"])


def test_sort_and_limit(client, mini):
    res = run(client, mini, {"dimensions": [{"field": "sales.sku"}], "measures": [AMOUNT], "sort": [{"field": "total_amount", "dir": "desc"}], "limit": 2})
    assert res["rows"] == [["P1", 1200.0], ["P2", 600.0]]
    res = run(client, mini, {"dimensions": [{"field": "sales.sku"}], "measures": [AMOUNT], "sort": [{"field": "total_amount", "dir": "asc"}], "limit": 1})
    assert res["rows"] == [["P3", 90.0]]
    res = run(client, mini, {"dimensions": [{"field": "sales.sku"}], "measures": [AMOUNT], "sort": [{"field": "sku", "dir": "asc"}]})
    assert [r[0] for r in res["rows"]] == ["P1", "P2", "P3"]


def test_dimension_only_listing_and_export(client, mini):
    res = run(client, mini, {"dimensions": [{"field": "products.category"}]})
    assert sorted(r[0] for r in res["rows"]) == ["Tools", "Toys"]
    r = client.post(api(mini["ws"], "/query/export"), params={"format": "csv"},
                    json={"dimensions": [{"field": "sales.channel"}], "measures": [AMOUNT]})
    assert r.status_code == 200
    assert r.content.decode("utf-8-sig").splitlines() == ["Channel,Total Amount", "Shopify,1210.0", "Amazon,680.0"]


def test_model_endpoint(client, mini):
    model = client.get(api(mini["ws"], "/model")).json()
    sales = next(d for d in model["datasets"] if d["slug"] == "sales")
    assert set(sales["lookups"]) == {"products", "channels"}
    roles = {f["name"]: f["role"] for f in sales["fields"]}
    assert roles["amount"] == "measure" and roles["sale_id"] == "dimension"
    assert {m["name"] for m in model["metrics"]} >= {"net_sales", "return_rate", "stock_on_hand"}
    assert "last_month" in model["date_presets"]
