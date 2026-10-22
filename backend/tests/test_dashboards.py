"""Reports, dashboards, widgets and dashboard-level filtering / drill-down (mini model, today = 2026-10-17)."""
import pytest

from conftest import api, build_mini

AMOUNT = {"field": "sales.amount", "agg": "sum"}
BY_CHANNEL = {"dimensions": [{"field": "sales.channel"}], "measures": [AMOUNT]}


@pytest.fixture(scope="module")
def mini(client):
    m = build_mini(client, "dash")
    yield m
    client.delete(f"/api/workspaces/{m['ws']}")


def _table(res):
    return {r[0]: r[1] for r in res["rows"]}


# ----------------------------------------------------------------------------------------------- reports

def test_reports_crud(client, mini):
    ws = mini["ws"]
    r = client.post(api(ws, "/reports"), json={"name": "Sales by channel", "chart_type": "bar", "spec": BY_CHANNEL,
                                               "options": {"color": "blue"}})
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["spec"]["dimensions"][0]["field"] == "sales.channel" and rep["options"] == {"color": "blue"}
    assert client.get(api(ws, f"/reports/{rep['id']}")).json()["name"] == "Sales by channel"
    assert rep["id"] in [x["id"] for x in client.get(api(ws, "/reports")).json()]

    r = client.put(api(ws, f"/reports/{rep['id']}"), json={"name": "Renamed", "chart_type": "pie", "spec": {**BY_CHANNEL, "time_range": "last_month"}})
    assert r.status_code == 200 and r.json()["chart_type"] == "pie" and r.json()["spec"]["time_range"] == "last_month"

    # invalid specs and chart types are rejected up front
    assert client.post(api(ws, "/reports"), json={"name": "x", "chart_type": "bar", "spec": {"measures": [{"field": "sales.nope"}]}}).status_code == 400
    assert client.post(api(ws, "/reports"), json={"name": "x", "chart_type": "sparkle", "spec": BY_CHANNEL}).status_code == 400
    assert client.put(api(ws, f"/reports/{rep['id']}"), json={"name": "x", "chart_type": "bar",
                                                             "spec": {"dimensions": [{"field": "products.category"}], "measures": [{"field": "spend.spend"}]}}).status_code == 400
    assert client.get(api(ws, f"/reports/{rep['id']}")).json()["name"] == "Renamed"

    assert client.delete(api(ws, f"/reports/{rep['id']}")).status_code == 204
    assert client.get(api(ws, f"/reports/{rep['id']}")).status_code == 404
    assert client.put(api(ws, f"/reports/{rep['id']}"), json={"name": "x", "spec": BY_CHANNEL}).status_code == 404


def test_reports_are_workspace_scoped(client, mini, workspace):
    rep = client.post(api(mini["ws"], "/reports"), json={"name": "r", "spec": BY_CHANNEL}).json()
    assert client.get(api(workspace["id"], f"/reports/{rep['id']}")).status_code == 404
    assert client.delete(api(workspace["id"], f"/reports/{rep['id']}")).status_code == 404


# ----------------------------------------------------------------------------------------------- dashboards

def test_dashboards_crud_and_widgets(client, mini):
    ws = mini["ws"]
    filters = [{"id": "date", "type": "date_range", "label": "Date", "field": "@time", "value": "last_12_months"},
               {"type": "values", "label": "Channel", "field": "sales.channel", "value": []}]
    r = client.post(api(ws, "/dashboards"), json={"name": "Overview", "description": "d", "filters": filters})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["widgets"] == [] and [f["id"] for f in d["filters"]] == ["date", "f1"]
    did = d["id"]
    assert client.post(api(ws, "/dashboards"), json={"name": "x", "filters": [{"type": "slider"}]}).status_code == 400

    # widgets: from a spec, from a report, auto layout stacks below the previous widget
    w1 = client.post(api(ws, f"/dashboards/{did}/widgets"), json={"title": "Net sales", "chart_type": "kpi",
                                                                   "spec": {"measures": [{"metric": "net_sales"}]}})
    assert w1.status_code == 201, w1.text
    w1 = w1.json()
    assert w1["layout"] == {"x": 0, "y": 0, "w": 3, "h": 2}
    rep = client.post(api(ws, "/reports"), json={"name": "By channel", "spec": BY_CHANNEL}).json()
    w2 = client.post(api(ws, f"/dashboards/{did}/widgets"), json={"title": "By channel", "chart_type": "bar", "report_id": rep["id"]}).json()
    assert w2["report_id"] == rep["id"] and w2["spec"]["dimensions"][0]["field"] == "sales.channel"
    assert w2["layout"] == {"x": 0, "y": 2, "w": 6, "h": 4}
    assert client.post(api(ws, f"/dashboards/{did}/widgets"), json={"title": "x", "chart_type": "bar"}).status_code == 400
    assert client.post(api(ws, f"/dashboards/{did}/widgets"), json={"title": "x", "chart_type": "bar",
                                                                     "spec": {"measures": [{"field": "nope.x"}]}}).status_code == 400
    assert client.post(api(ws, f"/dashboards/{did}/widgets"), json={"title": "x", "chart_type": "wobble", "spec": BY_CHANNEL}).status_code == 400

    # update a widget
    r = client.put(api(ws, f"/dashboards/{did}/widgets/{w2['id']}"), json={"title": "Channel mix", "chart_type": "donut",
                                                                            "spec": {**BY_CHANNEL, "limit": 1}})
    assert r.status_code == 200 and r.json()["title"] == "Channel mix" and r.json()["spec"]["limit"] == 1
    assert r.json()["layout"] == {"x": 0, "y": 2, "w": 6, "h": 4}  # unchanged when not sent
    assert client.put(api(ws, f"/dashboards/{did}/widgets/999999"), json={"title": "x"}).status_code == 404

    # layout save ignores unknown widget ids
    r = client.put(api(ws, f"/dashboards/{did}/layout"), json=[{"id": w1["id"], "x": 6, "y": 0, "w": 6, "h": 3},
                                                               {"id": 999999, "x": 0, "y": 0, "w": 1, "h": 1}])
    assert r.status_code == 200
    assert {w["id"]: w["layout"] for w in r.json()["widgets"]}[w1["id"]] == {"x": 6, "y": 0, "w": 6, "h": 3}

    # update dashboard
    r = client.put(api(ws, f"/dashboards/{did}"), json={"name": "Overview 2", "filters": filters[:1]})
    assert r.status_code == 200 and r.json()["name"] == "Overview 2" and len(r.json()["filters"]) == 1
    listing = client.get(api(ws, "/dashboards")).json()
    assert next(x for x in listing if x["id"] == did)["widget_count"] == 2

    # delete a widget, then the dashboard
    assert client.delete(api(ws, f"/dashboards/{did}/widgets/{w1['id']}")).status_code == 204
    assert client.delete(api(ws, f"/dashboards/{did}/widgets/{w1['id']}")).status_code == 404
    assert len(client.get(api(ws, f"/dashboards/{did}")).json()["widgets"]) == 1
    assert client.delete(api(ws, f"/dashboards/{did}")).status_code == 204
    assert client.get(api(ws, f"/dashboards/{did}")).status_code == 404


@pytest.fixture()
def dash(client, mini):
    ws = mini["ws"]
    d = client.post(api(ws, "/dashboards"), json={"name": "Filters", "filters": [
        {"id": "date", "type": "date_range", "field": "@time", "value": None},
        {"id": "ch", "type": "values", "field": "sales.channel", "value": []}]}).json()
    widgets = {}
    for title, ct, spec in [
        ("Sales", "kpi", {"measures": [AMOUNT]}),
        ("By channel", "bar", BY_CHANNEL),
        ("Trend", "line", {"dimensions": [{"field": "@time", "grain": "month"}], "measures": [AMOUNT]}),
        ("Category", "bar", {"dimensions": [{"field": "products.category"}], "measures": [AMOUNT, {"metric": "units_returned"}]}),
        ("Net sales", "kpi", {"measures": [{"metric": "net_sales"}]}),
    ]:
        widgets[title] = client.post(api(ws, f"/dashboards/{d['id']}/widgets"), json={"title": title, "chart_type": ct, "spec": spec}).json()["id"]
    yield d["id"], widgets
    client.delete(api(ws, f"/dashboards/{d['id']}"))


def _data(client, mini, did, wid, **body):
    r = client.post(api(mini["ws"], f"/dashboards/{did}/widgets/{wid}/data"), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_widget_data_and_dashboard_filters(client, mini, dash):
    did, w = dash
    assert _data(client, mini, did, w["Sales"])["rows"] == [[1890.0]]
    # empty filter values are ignored
    assert _data(client, mini, did, w["Sales"], filters=[{"type": "date_range", "field": "@time", "value": None},
                                                       {"type": "values", "field": "sales.channel", "value": []}])["rows"] == [[1890.0]]
    date = {"type": "date_range", "field": "@time", "value": "last_month"}
    res = _data(client, mini, did, w["Sales"], filters=[date])
    assert res["rows"] == [[1110.0]] and res["applied_spec"]["time_range"] == "last_month"
    res = _data(client, mini, did, w["Trend"], filters=[date])
    assert _table(res) == {"2026-09-01": 1110.0}
    # one dashboard date filter applies to every fact's own date column
    res = _data(client, mini, did, w["Category"], filters=[date])
    assert {r[0]: (r[1], r[2]) for r in res["rows"]} == {"Tools": (1050.0, 3), "Toys": (60.0, None)}

    chan = {"type": "values", "field": "sales.channel", "value": ["Amazon"]}
    assert _data(client, mini, did, w["Sales"], filters=[chan])["rows"] == [[680.0]]
    assert _data(client, mini, did, w["Sales"], filters=[chan, date])["rows"] == [[550.0]]
    assert _table(_data(client, mini, did, w["By channel"], filters=[chan])) == {"Amazon": 680.0}
    # a values filter on a lookup column reaches the fact through the relationship
    cat = {"type": "values", "field": "products.category", "value": "Toys"}
    assert _data(client, mini, did, w["Sales"], filters=[cat])["rows"] == [[90.0]]
    # explicit date column for the date filter
    res = _data(client, mini, did, w["Sales"], filters=[{"type": "date_range", "field": "sales.sale_date",
                                                         "value": {"from": "2026-08-01", "to": "2026-08-31"}}])
    assert res["rows"] == [[550.0]] and res["applied_spec"]["time_field"] == "sales.sale_date"


def test_widget_drill_and_compare(client, mini, dash):
    did, w = dash
    drill = [{"field": "sales.channel", "op": "eq", "value": "Shopify"}]
    res = _data(client, mini, did, w["By channel"], drill=drill)
    assert _table(res) == {"Shopify": 1210.0}
    res = _data(client, mini, did, w["By channel"], drill=drill, drill_dimension={"field": "products.product_name"})
    assert _table(res) == {"Widget": 700.0, "Gadget": 450.0, "Gizmo": 60.0}
    assert res["applied_spec"]["dimensions"] == [{"field": "products.product_name", "grain": None, "alias": None, "label": None}]
    res = _data(client, mini, did, w["Trend"], drill=[{"field": "products.category", "op": "eq", "value": "Toys"}],
                drill_dimension={"field": "sales.sale_date", "grain": "day"})
    assert _table(res) == {"2026-09-28": 60.0, "2026-10-05": 30.0}
    res = _data(client, mini, did, w["Net sales"], filters=[{"type": "date_range", "field": "@time", "value": "last_month"}],
                compare="previous_period")
    assert res["rows"][0][:2] == [610.0, 550.0]
    assert _data(client, mini, did, w["Sales"], compare="bogus")["rows"] == [[1890.0]]
    r = client.post(api(mini["ws"], f"/dashboards/{did}/widgets/999999/data"), json={})
    assert r.status_code == 404


def test_filter_values_endpoint(client, mini, dash):
    did, _ = dash
    r = client.get(api(mini["ws"], f"/dashboards/{did}/values"), params={"field": "sales.channel"})
    assert r.status_code == 200, r.text
    assert sorted(r.json()) == ["Amazon", "Shopify"]
    r = client.get(api(mini["ws"], f"/dashboards/{did}/values"), params={"field": "products.category"})
    assert sorted(r.json()) == ["Tools", "Toys"]


def test_duplicate_and_template(client, mini, dash):
    ws = mini["ws"]
    did, w = dash
    r = client.post(api(ws, f"/dashboards/{did}/duplicate"))
    assert r.status_code == 201
    copy = r.json()
    assert copy["name"] == "Filters (copy)" and copy["id"] != did
    src = client.get(api(ws, f"/dashboards/{did}")).json()
    assert [x["title"] for x in copy["widgets"]] == [x["title"] for x in src["widgets"]]
    assert {x["id"] for x in copy["widgets"]}.isdisjoint({x["id"] for x in src["widgets"]})
    assert copy["filters"] == src["filters"]
    # editing the copy leaves the original alone
    client.delete(api(ws, f"/dashboards/{copy['id']}/widgets/{copy['widgets'][0]['id']}"))
    assert len(client.get(api(ws, f"/dashboards/{did}")).json()["widgets"]) == 5

    tpl = client.post(api(ws, "/dashboards"), json={"name": "Template: KPIs", "is_template": True}).json()
    client.post(api(ws, f"/dashboards/{tpl['id']}/widgets"), json={"title": "Sales", "chart_type": "kpi", "spec": {"measures": [AMOUNT]}})
    r = client.post(api(ws, f"/dashboards/{tpl['id']}/duplicate"), params={"name": "My KPIs"})
    made = r.json()
    assert made["name"] == "My KPIs" and made["is_template"] is False and len(made["widgets"]) == 1
    assert _data(client, mini, made["id"], made["widgets"][0]["id"])["rows"] == [[1890.0]]


def test_dashboards_persist_and_lineage(client, mini, dash):
    from fastapi.testclient import TestClient

    from app.db import reset_engines
    from app.main import app

    did, w = dash
    reset_engines()
    with TestClient(app) as c2:
        d = c2.get(api(mini["ws"], f"/dashboards/{did}")).json()
        assert [x["title"] for x in d["widgets"]] == ["Sales", "By channel", "Trend", "Category", "Net sales"]
        assert d["filters"][1]["field"] == "sales.channel"
        res = c2.post(api(mini["ws"], f"/dashboards/{did}/widgets/{w['Sales']}/data"), json={}).json()
        assert res["rows"] == [[1890.0]]
    lin = client.get(api(mini["ws"], "/lineage")).json()
    edges = {(e["from"], e["to"]) for e in lin["edges"]}
    sales_id = mini["ds"]["sales"]
    assert (f"ds{sales_id}", f"dash{did}") in edges


def test_viewer_can_read_but_not_edit_dashboards(client, mini, dash):
    ws = mini["ws"]
    did, w = dash
    client.put(api(ws, "/members"), json={"user_email": "dash-viewer@example.com", "role": "viewer"})
    h = {"X-User-Email": "dash-viewer@example.com"}
    assert client.get(api(ws, f"/dashboards/{did}"), headers=h).status_code == 200
    assert client.post(api(ws, f"/dashboards/{did}/widgets/{w['Sales']}/data"), json={}, headers=h).status_code == 200
    assert client.post(api(ws, "/dashboards"), json={"name": "x"}, headers=h).status_code == 403
    assert client.delete(api(ws, f"/dashboards/{did}"), headers=h).status_code == 403
    assert client.put(api(ws, f"/dashboards/{did}/layout"), json=[], headers=h).status_code == 403
