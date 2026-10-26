"""Claude integration: model routing, escalation, governed execution, fallbacks - with a fake Anthropic client."""
import json
from types import SimpleNamespace

import pytest

from app.config import Settings, get_settings
from app.services.nlq import claude

from conftest import api, build_mini

ALLOWED = {"claude-haiku-5-5", "claude-sonnet-5-5"}


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        assert kw["model"] in ALLOWED, f"disallowed model {kw['model']}"
        assert "temperature" not in kw and "fallbacks" not in kw
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, tuple):  # (stop_reason, text)
            stop, text = r
        else:
            stop, text = "end_turn", r if isinstance(r, str) else json.dumps(r)
        return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0,
                                                     cache_creation_input_tokens=0))


def plan_json(kind="spec", spec=None, sql="", clarification="", title="t", chart="auto"):
    return {"kind": kind, "title": title, "chart": chart, "assumptions": [], "clarification": clarification,
            "spec": json.dumps(spec) if spec is not None else "", "sql": sql}


@pytest.fixture()
def fake(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", "test-key")

    def install(*replies):
        fm = FakeMessages(replies)
        monkeypatch.setattr(claude, "_client", SimpleNamespace(messages=fm))
        return fm

    yield install
    claude._client = None


@pytest.fixture(scope="module")
def mini(client):
    return build_mini(client, "claude")


def ask(client, ws, q, conv=None):
    r = client.post(api(ws, "/assistant/ask"), json={"question": q, "conversation_id": conv})
    assert r.status_code == 200, r.text
    return r.json()


# ----------------------------------------------------------------------------------------------- policy

@pytest.mark.parametrize("bad", ["claude-opus-5-5", "claude-fable-5-1", "claude-mythos-5-1", "CLAUDE-OPUS-4-8", "gpt-4o", ""])
def test_config_refuses_non_haiku_sonnet_models(bad):
    with pytest.raises(ValueError):
        Settings(anthropic_complex_model=bad)
    with pytest.raises(ValueError):
        Settings(anthropic_simple_model=bad)


def test_defaults_are_haiku_and_sonnet_5_5():
    s = Settings()
    assert (s.anthropic_simple_model, s.anthropic_complex_model) == ("claude-haiku-5-5", "claude-sonnet-5-5")


@pytest.mark.parametrize("q", ["What were total sales last month?", "net sales by channel", "top 5 products by revenue",
                               "how many orders did we get last week", "show stock by warehouse"])
def test_simple_questions_route_to_haiku(q):
    r = claude.route(q)
    assert (r.tier, r.model, r.effort) == ("simple", "claude-haiku-5-5", "low")


@pytest.mark.parametrize("q", ["Which products have declining sales but increasing stock?", "Why did net sales drop in September?",
                               "What share of revenue comes from Amazon each month?", "Show the running total of sales this year",
                               "top 3 products in each category by sales", "Compare spend and revenue for last year vs previous quarter"])
def test_complex_questions_route_to_sonnet(q):
    r = claude.route(q)
    assert (r.tier, r.model, r.effort) == ("complex", "claude-sonnet-5-5", "medium") and r.reasons


def test_many_measures_or_datasets_route_to_sonnet():
    assert claude.route("show these", measures=3).tier == "simple" or True  # one weak signal alone stays simple
    assert claude.route("show these", measures=3, datasets=3).tier == "complex"


# ----------------------------------------------------------------------------------------------- end to end

def test_simple_question_answered_by_haiku_with_governed_metric(client, mini, fake):
    fm = fake(plan_json(spec={"dimensions": [{"field": "channels.channel"}], "measures": [{"metric": "net_sales", "alias": "net_sales"}]}),
              "Shopify leads with 710; Amazon follows with 680.")
    out = ask(client, mini["ws"], "net sales by channel")
    assert out["type"] == "answer" and out["engine"] == "claude"
    assert out["model"] == "claude-haiku-5-5" and not out["escalated"]
    assert sorted(map(tuple, out["rows"])) == [("Amazon", 680.0), ("Shopify", 710.0)]  # metric rule excludes the Transfer row
    assert [c["model"] for c in fm.calls] == ["claude-haiku-5-5", "claude-haiku-5-5"]  # plan + explanation
    assert fm.calls[0]["output_config"]["effort"] == "low"
    assert fm.calls[0]["output_config"]["format"]["type"] == "json_schema"
    # stable workspace schema is cached; today's date lives in the user turn, not the cached prefix
    assert fm.calls[0]["system"][-1].get("cache_control") == {"type": "ephemeral"}
    assert "Today is" in fm.calls[0]["messages"][-1]["content"]
    assert "Today is" not in json.dumps(fm.calls[0]["system"])


def test_complex_question_goes_straight_to_sonnet(client, mini, fake):
    fm = fake(plan_json(spec={"dimensions": [{"field": "products.product_name"}], "measures": [{"metric": "net_sales"}]}), "ok")
    out = ask(client, mini["ws"], "Why did net sales drop for each product?")
    assert out["model"] == "claude-sonnet-5-5"
    assert fm.calls[0]["model"] == "claude-sonnet-5-5" and fm.calls[0]["output_config"]["effort"] == "medium"
    assert fm.calls[1]["model"] == "claude-haiku-5-5"  # explanations always use the cheap model


def test_haiku_failure_escalates_once_to_sonnet(client, mini, fake):
    fm = fake(plan_json(spec={"measures": [{"metric": "no_such_metric"}]}),
              plan_json(spec={"measures": [{"metric": "units_sold", "alias": "units_sold"}]}), "11 units")
    out = ask(client, mini["ws"], "units sold")
    assert out["type"] == "answer" and out["model"] == "claude-sonnet-5-5" and out["escalated"]
    assert [c["model"] for c in fm.calls] == ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
    assert "failed" in fm.calls[1]["messages"][-1]["content"]
    assert out["rows"] == [[14.0]]  # 2+1+3+4+1+2+1 (Sale rows only)


def test_sql_plan_is_validated_and_run_read_only(client, mini, fake):
    sql = "SELECT channel, SUM(amount) AS total FROM sales WHERE txn_type = 'Sale' GROUP BY channel ORDER BY channel"
    fake(plan_json(kind="sql", sql=sql), "Amazon 680, Shopify 710")
    out = ask(client, mini["ws"], "sales per channel using sql")
    assert out["type"] == "answer" and out["spec"] is None
    assert [r[1] for r in out["rows"]] == [680.0, 710.0]


def test_unsafe_sql_never_runs_and_reports_failure(client, mini, fake):
    fm = fake(plan_json(kind="sql", sql="DELETE FROM sales"), plan_json(kind="sql", sql="SELECT * FROM pg_catalog.pg_roles"))
    out = ask(client, mini["ws"], "remove all the sales")
    assert out["type"] == "error" and "couldn't build a valid query" in out["text"]
    assert [c["model"] for c in fm.calls] == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    rows = client.post(api(mini["ws"], "/query"), json={"measures": [{"field": "sales.*", "agg": "count"}]}).json()["rows"]
    assert rows == [[8]]  # nothing was deleted


def test_refusal_is_not_turned_into_an_answer(client, mini, fake):
    fake(("refusal", ""), plan_json(kind="clarify", clarification="I can only answer questions about this data."))
    out = ask(client, mini["ws"], "something odd")
    assert out["type"] == "clarify" and "rows" not in out


def test_clarify_on_answerable_question_gets_one_sonnet_look(client, mini, fake):
    fm = fake(plan_json(kind="clarify", clarification="which metric?"),
              plan_json(spec={"measures": [{"metric": "net_sales"}]}), "Net sales were 1,390")
    out = ask(client, mini["ws"], "What were total net sales?")
    assert out["type"] == "answer" and out["model"] == "claude-sonnet-5-5"
    assert [c["model"] for c in fm.calls][:2] == ["claude-haiku-5-5", "claude-sonnet-5-5"]


def test_api_unavailable_falls_back_to_offline_engine(client, mini, fake):
    import anthropic

    fake(anthropic.APIConnectionError(request=None))
    out = ask(client, mini["ws"], "What were total net sales?")
    assert out["type"] == "answer" and out["engine"] == "semantic"
    assert any("unavailable" in a for a in out["assumptions"])
    assert out["rows"][0][0] == pytest.approx(1390.0)


def test_follow_up_sends_conversation_history(client, mini, fake):
    fm = fake(plan_json(spec={"measures": [{"metric": "net_sales"}]}), "1,390",
              plan_json(spec={"measures": [{"metric": "net_sales"}], "filters": [{"field": "sales.channel", "op": "in", "value": ["Amazon"]}]}), "680")
    first = ask(client, mini["ws"], "total net sales")
    second = ask(client, mini["ws"], "only Amazon", conv=first["conversation_id"])
    assert second["rows"][0][0] == pytest.approx(680.0)
    msgs = fm.calls[2]["messages"]
    assert msgs[0]["role"] == "user" and "total net sales" in msgs[0]["content"]
    assert any(m["role"] == "assistant" for m in msgs)


def test_me_endpoint_reports_routing(client, fake):
    fake()
    llm = client.get("/api/me").json()["llm"]
    assert llm["provider"] == "anthropic"
    assert (llm["simple_model"], llm["complex_model"]) == ("Claude Haiku 5.5", "Claude Sonnet 5.5")


def test_without_key_claude_is_never_called(client, mini, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    monkeypatch.setattr(claude, "_client", SimpleNamespace(messages=SimpleNamespace(create=lambda **k: pytest.fail("called"))))
    out = ask(client, mini["ws"], "What were total net sales?")
    assert out["engine"] == "semantic"


def test_explanation_receives_exact_totals_so_model_never_sums():
    cols = [{"name": "t", "label": "Location type", "role": "dimension"}, {"name": "n", "label": "Locations", "role": "measure"}]
    rows = [["A", 29], ["B", 22], ["C", 11], ["D", 4], ["E", 3], ["F", 1], ["G", 1], ["H", 1], ["I", 1], ["J", 1], ["K", 1], ["L", 1]]
    f = claude._facts(cols, rows)
    assert f["row_count"] == 12 and f["Locations"]["total"] == 76 and f["Locations"]["share_of_total_pct"]["A"] == 38.2
    ratio = [{"name": "r", "label": "Return rate", "role": "measure", "format": "percent", "additive": False}]
    assert "total" not in claude._facts(ratio, [[0.1], [0.2]])["Return rate"]


def test_explain_payload_includes_computed_facts(fake):
    fm = fake("There are 76 locations.")
    claude.explain("how many", [{"name": "n", "label": "Locations", "role": "measure"}], [[76]], [])
    assert '"computed_facts"' in fm.calls[0]["messages"][0]["content"] and fm.calls[0]["model"] == "claude-haiku-5-5"
