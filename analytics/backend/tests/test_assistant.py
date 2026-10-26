"""The conversational assistant: deterministic parser units, ground-truth validation on the demo workspace,
honest failure behaviour, conversation persistence and the optional LLM path (mocked OpenAI-compatible API)."""
import csv
import json
import os

import httpx
import pytest

from conftest import SAMPLE_DIR, api

with open(os.path.join(SAMPLE_DIR, "ground_truth.json"), encoding="utf-8") as _f:
    GT = json.load(_f)

QUESTIONS = {
    "last_month": "What were total sales last month?",
    "shopify_amazon": "Compare Shopify and Amazon sales over the last six months.",
    "return_rate": "Which products have the highest return rate?",
    "inventory": "Show inventory movement by warehouse",
    "declining": "Which products have declining sales but increasing stock?",
    "marketing": "Compare marketing spend with sales revenue.",
    "dashboard": "Create a dashboard showing monthly sales, returns and inventory",
}


def ask(client, ws, question, conversation_id=None, engine="semantic", headers=None) -> dict:
    r = client.post(api(ws, "/assistant/ask"), json={"question": question, "conversation_id": conversation_id, "engine": engine},
                    headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def col(res, name):
    return [c["name"] for c in res["columns"]].index(name)


# ----------------------------------------------------------------------------------------------- parser units

@pytest.fixture(scope="module")
def nl(demo):
    from app import models as m
    from app.db import SessionLocal
    from app.services.catalog import load_catalog
    from app.services.nlq.parser import interpret
    from app.services.nlq.vocab import build_vocab, value_index

    db = SessionLocal()
    ws = db.get(m.Workspace, demo["workspace_id"])
    cat = load_catalog(db, ws)
    vocab = build_vocab(cat, value_index(cat))

    def parse(q, prev=None):
        return interpret(q, cat, vocab, prev)

    yield parse
    db.close()


@pytest.mark.parametrize("q,rng", [
    ("net sales last month", "last_month"),
    ("net sales in the last six months", {"last": 6, "unit": "months"}),
    ("net sales over the past 2 quarters", {"last": 2, "unit": "quarters"}),
    ("net sales this quarter", "this_quarter"),
    ("net sales year to date", "year_to_date"),
    ("net sales yesterday", "yesterday"),
    ("net sales in March 2026", {"from": "2026-03-01", "to": "2026-03-31"}),
    ("net sales in February 2024", {"from": "2024-02-01", "to": "2024-02-29"}),
    ("net sales from 2026-01-01 to 2026-01-15", {"from": "2026-01-01", "to": "2026-01-15"}),
    ("net sales in 2025", {"from": "2025-01-01", "to": "2025-12-31"}),
    ("net sales", None),
])
def test_time_phrases(nl, q, rng):
    it = nl(q)
    assert it.kind == "query"
    assert it.spec.time_range == rng
    assert [ms.metric for ms in it.spec.measures] == ["net_sales"]


def test_grains_and_trends(nl):
    it = nl("daily net sales last week")
    assert it.spec.dimensions[0].field == "@time" and it.spec.dimensions[0].grain == "day"
    assert it.spec.time_range == "last_week"
    it = nl("net sales trend")
    assert it.spec.dimensions[0].grain == "month"
    it = nl("quarterly units sold")
    assert it.spec.dimensions[0].grain == "quarter"


def test_comparisons(nl):
    it = nl("net sales this year vs last year")
    assert it.spec.compare == "previous_year" and it.spec.time_range == "this_year"
    it = nl("net sales last month compared to the previous month")
    assert it.spec.compare == "previous_period" and it.spec.time_range == "last_month"
    assert nl("net sales growth last quarter").spec.compare == "previous_period"


def test_top_n(nl):
    it = nl("top 5 products by net sales")
    assert it.spec.limit == 5 and it.spec.sort[0].dir == "desc"
    assert [d.field for d in it.spec.dimensions] == ["products.product_name"]
    it = nl("bottom 3 categories by units sold")
    assert it.spec.limit == 3 and it.spec.sort[0].dir == "asc"
    assert [d.field for d in it.spec.dimensions] == ["products.category"]
    it = nl("which channel has the highest net sales")
    assert it.spec.sort[0].dir == "desc" and it.spec.limit == 10


def test_exclusions(nl):
    it = nl("net sales by channel excluding amazon")
    assert any(f.op == "not_in" and f.value == ["Amazon"] for f in it.spec.filters)
    assert not any(f.op == "in" and "Amazon" in f.value for f in it.spec.filters)
    assert any(d.field.endswith(".channel") for d in it.spec.dimensions)  # the asked-for breakdown stays
    it = nl("net sales last month except flipkart")
    assert [(f.op, f.value) for f in it.spec.filters] == [("not_in", ["Flipkart"])]


def test_value_filters_and_glossary(nl):
    it = nl("net sales on amazon last month")
    assert [(f.op, f.value) for f in it.spec.filters] == [("in", ["Amazon"])]
    assert it.spec.dimensions == []
    it = nl("net sales on the website last month")  # glossary: website -> Shopify
    assert [(f.op, f.value) for f in it.spec.filters] == [("in", ["Shopify"])]
    it = nl("compare amazon and flipkart net sales")
    assert sorted(it.spec.filters[0].value) == ["Amazon", "Flipkart"]
    assert any(d.field == it.spec.filters[0].field for d in it.spec.dimensions)


def test_follow_ups(nl):
    prev = nl("net sales last month").spec
    it = nl("what about amazon only?", prev)
    assert it.kind == "query" and [ms.metric for ms in it.spec.measures] == ["net_sales"]
    assert it.spec.time_range == "last_month"
    assert [(f.op, f.value) for f in it.spec.filters] == [("in", ["Amazon"])]
    assert "Continuing from the previous question" in it.assumptions
    it2 = nl("and by category", it.spec)
    assert [d.field for d in it2.spec.dimensions] == ["products.category"]
    assert it2.spec.filters == it.spec.filters and it2.spec.time_range == "last_month"
    it3 = nl("now remove the filter", it2.spec)
    assert it3.spec.filters == []
    it4 = nl("tell me a joke", prev)
    assert it4.kind == "clarify"


@pytest.mark.parametrize("q", ["how is the weather on mars", "show me the flux capacitor readings", "asdf qwerty"])
def test_clarify_on_unknown(nl, q):
    it = nl(q)
    assert it.kind == "clarify" and it.clarification and it.suggestions


def test_clarify_when_no_measure(nl):
    it = nl("break it down by category")
    assert it.kind == "clarify" and "measure" in it.clarification.lower()


@pytest.mark.parametrize("q,kind", [("hello", "chitchat"), ("Thanks!", "chitchat"), ("hi", "chitchat"),
                                    ("what can you do?", "help"), ("help", "help"), ("What questions can I ask", "help")])
def test_chitchat_and_help(nl, q, kind):
    assert nl(q).kind == kind


def test_chart_words_and_dashboard_parse(nl):
    assert nl("net sales by channel as a pie chart").chart == "pie"
    assert nl("show net sales by month as a table").chart == "table"
    it = nl("build a dashboard with net sales and marketing spend for the last 6 months")
    assert it.kind == "dashboard"
    assert {w[2] for w in it.widgets} == {"kpi", "line"} and len(it.widgets) == 4
    assert all(w[1].time_range == {"last": 6, "unit": "months"} for w in it.widgets)
    assert nl("create a dashboard about nothing in particular").kind == "clarify"


# ----------------------------------------------------------------------------------------------- ground truth

@pytest.fixture(scope="module")
def answers(client, demo):
    ws = demo["workspace_id"]
    return {k: ask(client, ws, q) for k, q in QUESTIONS.items()}


def test_total_sales_last_month(answers):
    res = answers["last_month"]
    assert res["type"] == "answer" and res["engine"] == "semantic"
    assert res["rows"][0][0] == pytest.approx(GT["net_sales_last_month"], abs=0.01)
    # transfers / franchise dispatches are excluded by the metric's business rule
    assert GT["register_total_last_month_incl_transfers"] != pytest.approx(GT["net_sales_last_month"], abs=1)
    assert res["rows"][0][0] != pytest.approx(GT["register_total_last_month_incl_transfers"], abs=1)
    assert res["date_range"] == ["2026-09-01", "2026-09-30"]
    assert "SELECT" in res["sql"].upper() and "transaction_type" in res["sql"] and "'Sale'" in res["sql"]
    assert any("transaction_type" in a for a in res["assumptions"])
    assert "64.15 L" in res["text"]


def test_register_total_including_transfers(client, demo):
    ws = demo["workspace_id"]
    r = client.post(api(ws, "/query"), json={"measures": [{"field": "sales_register.net_amount", "agg": "sum"}], "time_range": "last_month"})
    assert r.json()["rows"][0][0] == pytest.approx(GT["register_total_last_month_incl_transfers"], abs=0.01)


def test_shopify_vs_amazon_last_six_months(answers):
    res = answers["shopify_amazon"]
    assert res["type"] == "answer"
    cols = res["columns"]
    t = next(i for i, c in enumerate(cols) if c["role"] == "dimension" and c["type"] == "date")
    ch = next(i for i, c in enumerate(cols) if c["role"] == "dimension" and i != t)
    v = next(i for i, c in enumerate(cols) if c["role"] == "measure")
    got = {f"{r[t][:7]}|{r[ch]}": r[v] for r in res["rows"]}
    expected = GT["shopify_amazon_monthly_last_6_months"]
    assert set(got) == set(expected)
    for k, val in expected.items():
        assert got[k] == pytest.approx(val, abs=0.01), k
    assert res["date_range"] == ["2026-04-01", "2026-09-30"]
    assert res["chart_type"] in ("line", "stacked_bar", "bar")


def test_highest_return_rate(answers):
    res = answers["return_rate"]
    assert res["type"] == "answer"
    name_i = next(i for i, c in enumerate(res["columns"]) if c["role"] == "dimension")
    rate_i = next(i for i, c in enumerate(res["columns"]) if c["role"] == "measure")
    got = [[r[name_i], r[rate_i]] for r in res["rows"]]
    assert [g[0] for g in got] == [e[0] for e in GT["return_rate_top10"]]
    for (gn, gr), (en, er) in zip(got, GT["return_rate_top10"]):
        assert gr == pytest.approx(er, abs=1e-6), gn
    assert res["columns"][rate_i]["format"] == "percent"
    assert res["chart_type"] != "pie"


def test_inventory_movement_by_warehouse(answers):
    with open(os.path.join(SAMPLE_DIR, "warehouses.csv"), encoding="utf-8") as f:
        names = {r["warehouse_id"]: r["warehouse_name"] for r in csv.DictReader(f)}
    expected = {names[k]: v for k, v in GT["inventory_movement_by_warehouse"].items()}
    res = answers["inventory"]
    assert res["type"] == "answer"
    got = {r[0]: r[1] for r in res["rows"]}
    assert got == pytest.approx(expected)


def test_declining_sales_increasing_stock(answers):
    res = answers["declining"]
    assert res["type"] == "answer"
    name_i = next(i for i, c in enumerate(res["columns"]) if c["role"] == "dimension")
    got = sorted(r[name_i] for r in res["rows"])
    assert got == sorted(GT["declining_sales_increasing_stock_names"])
    # every returned row really is declining in sales and increasing in stock
    ns, ns_p = col(res, "net_sales"), col(res, "net_sales__prev")
    st, st_p = col(res, "stock_on_hand"), col(res, "stock_on_hand__prev")
    assert all(r[ns] < r[ns_p] and r[st] > r[st_p] for r in res["rows"])
    assert any("3 complete months" in a for a in res["assumptions"])


def test_marketing_spend_vs_revenue(answers):
    res = answers["marketing"]
    assert res["type"] == "answer"
    t = next(i for i, c in enumerate(res["columns"]) if c["role"] == "dimension")
    sept = next(r for r in res["rows"] if r[t].startswith("2026-09"))
    assert sept[col(res, "marketing_spend")] == pytest.approx(GT["marketing_spend_last_month"], abs=0.01)
    assert sept[col(res, "net_sales")] == pytest.approx(GT["net_sales_last_month"], abs=0.01)
    assert any(i["type"] == "correlation" for i in res["insights"])


def test_create_dashboard(client, demo, answers):
    res = answers["dashboard"]
    assert res["type"] == "dashboard" and res["dashboard_id"]
    d = client.get(api(demo["workspace_id"], f"/dashboards/{res['dashboard_id']}"))
    assert d.status_code == 200
    widgets = d.json()["widgets"]
    metrics = {ms.get("metric") for w in widgets for ms in w["spec"]["measures"]}
    assert {"net_sales", "units_returned", "stock_on_hand"} <= metrics
    assert {w["chart_type"] for w in widgets} == {"kpi", "line"}
    assert any(w["spec"]["dimensions"] and w["spec"]["dimensions"][0]["grain"] == "month" for w in widgets)
    # every widget the assistant saved actually runs
    for w in widgets:
        r = client.post(api(demo["workspace_id"], f"/dashboards/{res['dashboard_id']}/widgets/{w['id']}/data"), json={})
        assert r.status_code == 200, w["title"]


# ----------------------------------------------------------------------------------------------- follow-ups / persistence

def test_follow_up_and_conversation_persistence(client, demo):
    ws = demo["workspace_id"]
    first = ask(client, ws, QUESTIONS["last_month"])
    cid = first["conversation_id"]
    second = ask(client, ws, "what about amazon only?", conversation_id=cid)
    assert second["conversation_id"] == cid and second["type"] == "answer"
    flt = second["spec"]["filters"]
    assert len(flt) == 1 and flt[0]["op"] == "in" and flt[0]["value"] == ["Amazon"] and flt[0]["field"].endswith(".channel")
    assert second["spec"]["time_range"] == "last_month"
    assert 0 < second["rows"][0][0] < first["rows"][0][0]
    assert second["rows"][0][0] == pytest.approx(GT["shopify_amazon_monthly_last_6_months"]["2026-09|Amazon"], abs=0.01)

    convs = client.get(api(ws, "/conversations")).json()
    c = next(x for x in convs if x["id"] == cid)
    assert c["message_count"] == 4 and c["title"] == QUESTIONS["last_month"]
    detail = client.get(api(ws, f"/conversations/{cid}")).json()
    assert [x["role"] for x in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][1]["payload"]["sql"] and detail["messages"][1]["payload"]["rows"][0][0] == first["rows"][0][0]
    assert detail["messages"][3]["payload"]["spec"]["filters"][0]["value"] == ["Amazon"]

    # another member does not see this conversation
    client.put(api(ws, "/members"), json={"user_email": "other@example.com", "role": "viewer"})
    other = {"X-User-Email": "other@example.com"}
    assert cid not in [x["id"] for x in client.get(api(ws, "/conversations"), headers=other).json()]
    assert client.get(api(ws, f"/conversations/{cid}"), headers=other).status_code == 404
    # a conversation id from another user starts a fresh conversation instead of leaking context
    res = ask(client, ws, "net sales by channel", conversation_id=cid, headers=other)
    assert res["conversation_id"] != cid

    assert client.delete(api(ws, f"/conversations/{cid}")).status_code == 204
    assert client.get(api(ws, f"/conversations/{cid}")).status_code == 404


def test_suggestions_and_history(client, demo):
    ws = demo["workspace_id"]
    sugg = client.get(api(ws, "/assistant/suggestions")).json()
    assert sugg and all(isinstance(s, str) for s in sugg)
    hist = client.get(api(ws, "/history"), params={"source": "ai"}).json()
    assert hist and all(h["source"] == "ai" for h in hist)


# ----------------------------------------------------------------------------------------------- honesty on failure

def test_empty_workspace_clarifies(client, workspace):
    res = ask(client, workspace["id"], "What were total sales last month?")
    assert res["type"] == "clarify" and "no data" in res["text"].lower()
    assert "rows" not in res


def test_unrelated_breakdown_is_not_an_answer(client, demo):
    res = ask(client, demo["workspace_id"], "marketing spend by product")
    assert res["type"] == "clarify"
    assert "could not run" in res["text"] and "relationship" in res["text"]
    assert not res.get("rows")


def test_execution_failure_is_not_an_answer(client, demo, monkeypatch):
    from app.services.executor import QueryExecutionError
    from app.services.nlq import assistant

    def boom(*a, **k):
        raise QueryExecutionError("The query took longer than 10s and was cancelled")

    monkeypatch.setattr(assistant, "run_spec", boom)
    res = ask(client, demo["workspace_id"], QUESTIONS["last_month"])
    assert res["type"] == "clarify" and "could not run" in res["text"] and not res.get("rows")

    def crash(*a, **k):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(assistant, "run_spec", crash)
    res = ask(client, demo["workspace_id"], QUESTIONS["last_month"])
    assert res["type"] == "error" and "could not answer" in res["text"] and not res.get("rows")
    # the failure is persisted truthfully in the conversation
    detail = client.get(api(demo["workspace_id"], f"/conversations/{res['conversation_id']}")).json()
    assert detail["messages"][-1]["payload"]["type"] == "error"


def test_dashboard_request_with_no_runnable_widgets(client, demo, monkeypatch):
    from app.services.nlq import assistant
    from app.services.query_engine import QueryError

    def bad(*a, **k):
        raise QueryError("nope")

    monkeypatch.setattr(assistant, "run_spec", bad)
    before = len(client.get(api(demo["workspace_id"], "/dashboards")).json())
    res = ask(client, demo["workspace_id"], QUESTIONS["dashboard"])
    assert res["type"] == "error" and "could not build" in res["text"]
    assert len(client.get(api(demo["workspace_id"], "/dashboards")).json()) == before


def test_help_and_chitchat_via_api(client, demo):
    res = ask(client, demo["workspace_id"], "hello")
    assert res["type"] == "help" and res["suggestions"]
    res = ask(client, demo["workspace_id"], "how is the weather on mars")
    assert res["type"] == "clarify" and "couldn't match" in res["text"]


# ----------------------------------------------------------------------------------------------- LLM path

class FakeLLM:
    """OpenAI-compatible chat/completions mock: JSON-mode calls get the queued SQL answers, others an explanation."""

    def __init__(self, sql_contents, status=200):
        self.sql_contents = list(sql_contents)
        self.status = status
        self.sql_calls: list[dict] = []
        self.explain_calls: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "boom"})
        if "response_format" in body:
            self.sql_calls.append(body)
            content = self.sql_contents[min(len(self.sql_calls), len(self.sql_contents)) - 1]
        else:
            self.explain_calls.append(body)
            content = "Mock explanation grounded in the rows."
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


@pytest.fixture()
def fake_llm(monkeypatch):
    from app.config import get_settings
    from app.services.nlq import llm

    def install(sql_contents, status=200):
        fake = FakeLLM(sql_contents, status)
        monkeypatch.setattr(get_settings(), "llm_base_url", "http://fake/v1")
        monkeypatch.setattr(get_settings(), "llm_api_key", "test-key")
        monkeypatch.setattr(llm, "_transport", httpx.MockTransport(fake))
        return fake

    yield install


def q_json(sql, **kw):
    return json.dumps({"type": "query", "sql": sql, "chart": "bar", "title": "LLM answer", "assumptions": ["assumed"], **kw})


GOOD_SQL = ("SELECT channel, SUM(net_amount) AS net_sales FROM sales_register WHERE transaction_type = 'Sale' "
            "AND invoice_date >= DATE '2026-09-01' AND invoice_date < DATE '2026-10-01' GROUP BY channel ORDER BY 2 DESC")


def test_llm_valid_sql(client, demo, fake_llm):
    fake = fake_llm([q_json(GOOD_SQL)])
    assert client.get("/api/me").json()["llm"] == {"enabled": True, "provider": "openai-compatible", "model": "gpt-4o-mini", "base_url_host": "fake"}
    res = ask(client, demo["workspace_id"], "net sales per channel last month", engine="llm")
    assert res["type"] == "answer" and res["engine"] == "llm"
    assert res["text"] == "Mock explanation grounded in the rows."
    assert res["chart_type"] == "bar" and res["assumptions"] == ["assumed"]
    total = sum(r[1] for r in res["rows"])
    assert total == pytest.approx(GT["net_sales_last_month"], abs=0.05)
    assert "sales_register" in res["sql"]
    # the prompt carried the schema and the semantic layer, and the API key
    sys_msgs = " ".join(m["content"] for m in fake.sql_calls[0]["messages"] if m["role"] == "system")
    assert "TABLE sales_register" in sys_msgs and "net_sales" in sys_msgs and "2026-10-17" in sys_msgs
    assert fake.sql_calls[0]["messages"][-1]["content"] == "net sales per channel last month"


def test_llm_unsafe_sql_rejected_and_retried(client, demo, fake_llm):
    ws = demo["workspace_id"]
    before = client.get(api(ws, f"/datasets/{demo['datasets']['sales_register']}")).json()["row_count"]
    fake = fake_llm([q_json("DELETE FROM sales_register"), q_json("SELECT * FROM ellementry_meta.workspaces")])
    res = ask(client, ws, "delete everything", engine="llm")
    assert res["type"] == "error" and res["engine"] == "llm"
    assert "could not produce a valid query" in res["text"]
    assert not res.get("rows")
    assert len(fake.sql_calls) == 2
    feedback = fake.sql_calls[1]["messages"][-1]["content"]
    assert "Rejected by the safety validator" in feedback
    assert client.get(api(ws, f"/datasets/{demo['datasets']['sales_register']}")).json()["row_count"] == before
    hist = client.get(api(ws, "/history"), params={"source": "ai"}).json()
    assert {h["status"] for h in hist[:2]} == {"rejected"}


def test_llm_retry_succeeds_after_feedback(client, demo, fake_llm):
    fake = fake_llm([q_json("SELECT nope FROM sales_register"), q_json(GOOD_SQL)])
    res = ask(client, demo["workspace_id"], "net sales per channel last month", engine="llm")
    assert res["type"] == "answer" and res["engine"] == "llm" and len(fake.sql_calls) == 2
    assert "nope" in fake.sql_calls[1]["messages"][-1]["content"]


def test_llm_code_fenced_json(client, demo, fake_llm):
    fake_llm(["Sure! Here you go:\n```json\n" + q_json(GOOD_SQL) + "\n```\nHope that helps."])
    res = ask(client, demo["workspace_id"], "net sales per channel last month", engine="llm")
    assert res["type"] == "answer" and res["engine"] == "llm"


def test_llm_malformed_json_is_not_an_answer(client, demo, fake_llm):
    fake_llm(["I think the answer is 42"])
    res = ask(client, demo["workspace_id"], "net sales per channel last month", engine="llm")
    assert res["type"] == "error" and "did not return JSON" in res["text"] and not res.get("rows")


def test_llm_clarify(client, demo, fake_llm):
    fake_llm([json.dumps({"type": "clarify", "clarification": "Which store do you mean?"})])
    res = ask(client, demo["workspace_id"], "sales at the store", engine="llm")
    assert res["type"] == "clarify" and res["engine"] == "llm" and res["text"] == "Which store do you mean?"


def test_llm_http_error(client, demo, fake_llm):
    fake_llm([], status=500)
    res = ask(client, demo["workspace_id"], "sales at the store", engine="llm")
    assert res["type"] == "error" and "HTTP 500" in res["text"]
    # in auto mode the semantic engine still answers, and a failing explainer falls back to the template text
    res = ask(client, demo["workspace_id"], QUESTIONS["last_month"], engine="auto")
    assert res["type"] == "answer" and res["engine"] == "semantic" and "64.15 L" in res["text"]
    # ...and an un-parseable question returns the semantic clarification, not a fake answer
    res = ask(client, demo["workspace_id"], "how is the weather on mars", engine="auto")
    assert res["type"] == "clarify"


def test_auto_mode_semantic_first_llm_explains(client, demo, fake_llm):
    fake = fake_llm([q_json(GOOD_SQL)])
    res = ask(client, demo["workspace_id"], QUESTIONS["last_month"], engine="auto")
    assert res["engine"] == "semantic" and res["text"] == "Mock explanation grounded in the rows."
    assert res["rows"][0][0] == pytest.approx(GT["net_sales_last_month"], abs=0.01)
    assert fake.sql_calls == [] and len(fake.explain_calls) == 1
    explained = json.loads(fake.explain_calls[0]["messages"][-1]["content"])
    assert explained["rows"][0][0] == pytest.approx(GT["net_sales_last_month"], abs=0.01)
    # a question the semantic engine cannot map goes to the LLM
    res = ask(client, demo["workspace_id"], "how is the weather on mars", engine="auto")
    assert res["engine"] == "llm" and res["type"] == "answer" and len(fake.sql_calls) == 1


def test_parse_json_unit():
    from app.services.nlq.llm import LLMError, parse_json

    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json('```json\n{"a": {"b": 2}}\n```') == {"a": {"b": 2}}
    assert parse_json('```\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here: {"sql": "SELECT 1"} done') == {"sql": "SELECT 1"}
    for bad in ("no json here", '{"a": 1', "[1, 2]", '{"a": }', ""):
        with pytest.raises(LLMError):
            parse_json(bad)


def test_llm_disabled_by_default():
    from app.services.nlq import llm

    assert llm.enabled() is False
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])
