"""Phase 0 of the AI assistants plan: dashboard keys, conversation scopes, the AI usage ledger and spend caps,
feature flags, the scripted-Claude harness and the eval runner."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app import models as m
from app.config import get_settings
from app.db import SessionLocal, get_engine
from app.services import ai_usage
from app.services.naming import dashboard_key, unique_dashboard_key

from conftest import api, build_mini
from fakes import FakeMessages, say, tool_call, turn


@pytest.fixture(scope="module")
def mini(client):
    return build_mini(client, "groundwork")


def _plan(spec):
    return {"kind": "spec", "title": "t", "chart": "auto", "assumptions": [], "clarification": "",
            "spec": json.dumps(spec), "sql": ""}


def _session():
    get_engine()
    return SessionLocal()


# ----------------------------------------------------------------------------------------------- dashboard keys

def test_dashboard_key_rule():
    assert dashboard_key("Sales & channels") == "sales-channels"
    assert dashboard_key("Discontinued & slow stock") == "discontinued-slow-stock"
    assert dashboard_key("  Ünïcode — Report 2026 ") == "unicode-report-2026"
    assert dashboard_key("&&&") == "dashboard"
    assert unique_dashboard_key("stock", {"stock", "stock-2"}) == "stock-3"


def test_dashboard_keys_are_derived_unique_and_stable(client, workspace):
    ws = workspace["id"]
    a = client.post(api(ws, "/dashboards"), json={"name": "Sales & channels"}).json()
    b = client.post(api(ws, "/dashboards"), json={"name": "Sales & channels"}).json()
    assert (a["key"], b["key"]) == ("sales-channels", "sales-channels-2")
    assert a["domain"] == ""
    # a rename keeps the key
    r = client.put(api(ws, f"/dashboards/{a['id']}"), json={"name": "Sales and channels (renamed)"})
    assert r.status_code == 200 and r.json()["key"] == "sales-channels"
    # lookup by key
    r = client.get(api(ws, "/dashboards/key/sales-channels"))
    assert r.status_code == 200 and r.json()["id"] == a["id"]
    assert client.get(api(ws, "/dashboards/key/nope")).status_code == 404
    # list carries the key
    assert {d["key"] for d in client.get(api(ws, "/dashboards")).json()} == {"sales-channels", "sales-channels-2"}


def test_explicit_key_and_domain_are_validated(client, workspace):
    ws = workspace["id"]
    r = client.post(api(ws, "/dashboards"), json={"name": "Stock", "key": "stock", "domain": "stock"})
    assert r.status_code == 201 and (r.json()["key"], r.json()["domain"]) == ("stock", "stock")
    assert client.post(api(ws, "/dashboards"), json={"name": "Other", "key": "stock"}).status_code == 400  # taken
    assert client.post(api(ws, "/dashboards"), json={"name": "Bad", "key": "Bad Key!"}).status_code == 400
    assert client.post(api(ws, "/dashboards"), json={"name": "Bad", "domain": "astrology"}).status_code == 400
    other = client.post(api(ws, "/dashboards"), json={"name": "Other"}).json()
    did = r.json()["id"]
    assert client.put(api(ws, f"/dashboards/{other['id']}"), json={"name": "Other", "key": "stock"}).status_code == 400
    r = client.put(api(ws, f"/dashboards/{did}"), json={"name": "Stock", "key": "stock-position", "domain": "operations"})
    assert r.status_code == 200 and (r.json()["key"], r.json()["domain"]) == ("stock-position", "operations")
    # omitting key / domain on update keeps them
    r = client.put(api(ws, f"/dashboards/{did}"), json={"name": "Stock"})
    assert (r.json()["key"], r.json()["domain"]) == ("stock-position", "operations")


def test_same_key_allowed_in_different_workspaces(client):
    a = client.post("/api/workspaces", json={"name": "keys-a"}).json()["id"]
    b = client.post("/api/workspaces", json={"name": "keys-b"}).json()["id"]
    try:
        assert client.post(api(a, "/dashboards"), json={"name": "Stock", "key": "stock"}).status_code == 201
        assert client.post(api(b, "/dashboards"), json={"name": "Stock", "key": "stock"}).status_code == 201
    finally:
        client.delete(f"/api/workspaces/{a}")
        client.delete(f"/api/workspaces/{b}")


def test_duplicate_gets_its_own_key_and_keeps_domain(client, workspace):
    ws = workspace["id"]
    src = client.post(api(ws, "/dashboards"), json={"name": "Fulfilment", "domain": "operations"}).json()
    copy = client.post(api(ws, f"/dashboards/{src['id']}/duplicate")).json()
    assert copy["key"] == "fulfilment-copy" and copy["domain"] == "operations"


def test_migration_backfills_keys_and_round_trips(client):
    """0002 down and up again: existing dashboards get keys from their names, unique per workspace."""
    from alembic import command
    from alembic.config import Config

    ws = client.post("/api/workspaces", json={"name": "migration-roundtrip"}).json()["id"]
    try:
        ids = [client.post(api(ws, "/dashboards"), json={"name": n}).json()["id"] for n in ("Days of cover", "Days of cover", "Returns")]
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = Config(os.path.join(here, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(here, "alembic"))
        cfg.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
        get_engine().dispose()
        command.downgrade(cfg, "0001_initial")
        command.upgrade(cfg, "head")
        get_engine().dispose()
        keys = [client.get(api(ws, f"/dashboards/{i}")).json()["key"] for i in ids]
        assert keys == ["days-of-cover", "days-of-cover-2", "returns"]
    finally:
        client.delete(f"/api/workspaces/{ws}")


# ----------------------------------------------------------------------------------------------- conversation scopes

def test_ask_page_lists_and_continues_only_its_own_threads(client, mini, fake_claude):
    ws = mini["ws"]
    with _session() as db:
        dash_thread = m.Conversation(workspace_id=ws, title="on a dashboard", user_email="owner@local",
                                     scope_type="dashboard", dashboard_key="stock")
        db.add(dash_thread)
        db.commit()
        dash_id = dash_thread.id
    listed = {c["id"] for c in client.get(api(ws, "/conversations")).json()}
    assert dash_id not in listed
    # asking with a dashboard thread's id starts a new Ask thread instead of writing into the dashboard's thread
    fake_claude(_plan({"measures": [{"metric": "units_sold", "alias": "units_sold"}]}), "11 units")
    out = client.post(api(ws, "/assistant/ask"), json={"question": "units sold", "conversation_id": dash_id}).json()
    assert out["conversation_id"] != dash_id
    with _session() as db:
        assert len(db.get(m.Conversation, dash_id).messages) == 0
        assert db.get(m.Conversation, out["conversation_id"]).scope_type == "workspace"


# ----------------------------------------------------------------------------------------------- usage ledger and caps

def test_cost_estimates():
    rate = get_settings().usd_inr_rate
    assert ai_usage.cost_inr("claude-haiku-5-5", {"input_tokens": 50_000, "output_tokens": 2000}) == pytest.approx(
        (50_000 * 0.10 + 2000 * 0.50) / 1e6 * rate, abs=1e-4)
    assert ai_usage.cost_inr("claude-sonnet-5-5", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}) == pytest.approx(12 * rate)
    assert ai_usage.cost_inr("claude-sonnet-5-5", {"cache_read_input_tokens": 1_000_000,
                                                   "cache_creation_input_tokens": 1_000_000}) == pytest.approx(2.70 * rate)
    # Haiku is dearer above a 100K-token prompt
    long = ai_usage.cost_inr("claude-haiku-5-5", {"input_tokens": 150_000, "output_tokens": 1000})
    assert long == pytest.approx((150_000 * 0.50 + 1000 * 2.50) / 1e6 * rate)
    # an unknown model is costed at the dearer allowed model, never free
    assert ai_usage.cost_inr("claude-unknown", {"input_tokens": 1_000_000}) == pytest.approx(2.00 * rate)


def test_price_override_from_settings(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_prices_json", json.dumps({"claude-haiku-5-5": {
        "input": 1.0, "output": 1.0, "cache_read": 1.0, "cache_write": 1.0}}))
    assert ai_usage.cost_inr("claude-haiku-5-5", {"input_tokens": 1_000_000}) == pytest.approx(get_settings().usd_inr_rate)
    monkeypatch.setattr(get_settings(), "ai_prices_json", "not json")
    assert ai_usage.cost_inr("claude-haiku-5-5", {"input_tokens": 50_000}) == pytest.approx(
        50_000 * 0.10 / 1e6 * get_settings().usd_inr_rate, abs=1e-4)


def test_every_claude_call_is_recorded_with_who_and_why(client, mini, fake_claude):
    ws = mini["ws"]
    started = datetime.now(timezone.utc)
    fm = fake_claude(_plan({"measures": [{"metric": "units_sold", "alias": "units_sold"}]}), "11 units sold.",
                     usage={"input_tokens": 2000, "output_tokens": 300, "cache_read_input_tokens": 5000,
                            "cache_creation_input_tokens": 0})
    out = client.post(api(ws, "/assistant/ask"), json={"question": "units sold"}).json()
    assert len(fm.calls) == 2  # plan + explanation
    with _session() as db:
        rows = (db.query(m.AIUsage).filter(m.AIUsage.workspace_id == ws, m.AIUsage.created_at >= started)
                .order_by(m.AIUsage.id).all())
    assert [(r.purpose, r.model, r.user_email, r.conversation_id) for r in rows] == [
        ("chat", "claude-haiku-5-5", "owner@local", out["conversation_id"]),
        ("explain", "claude-haiku-5-5", "owner@local", out["conversation_id"])]
    assert rows[0].input_tokens == 2000 and rows[0].cache_read_tokens == 5000
    assert rows[0].cost_inr == pytest.approx(ai_usage.cost_inr("claude-haiku-5-5", {
        "input_tokens": 2000, "output_tokens": 300, "cache_read_input_tokens": 5000}))
    assert out["usage"]["cost_inr"] == pytest.approx(rows[0].cost_inr)


def test_daily_cap_stops_claude_and_answers_offline(client, mini, fake_claude, monkeypatch):
    ws = mini["ws"]
    with _session() as db:
        row = m.AIUsage(workspace_id=ws, user_email="owner@local", purpose="chat", model="claude-haiku-5-5", cost_inr=0.5)
        db.add(row)
        db.commit()
        row_id = row.id
    try:
        monkeypatch.setattr(get_settings(), "ai_daily_limit_user_inr", 0.4)
        fm = fake_claude()  # any call would fail the test: the script is empty
        out = client.post(api(ws, "/assistant/ask"), json={"question": "units sold"}).json()
        assert fm.calls == []
        assert out["engine"] == "semantic"
        assert "spend limit" in json.dumps(out).lower()
    finally:
        with _session() as db:
            db.delete(db.get(m.AIUsage, row_id))
            db.commit()


def test_caps_by_user_by_month_and_switched_off(monkeypatch):
    s = get_settings()
    now = datetime.now(timezone.utc)
    with _session() as db:
        db.add_all([m.AIUsage(user_email="cap-a@example.com", purpose="chat", model="claude-sonnet-5-5", cost_inr=60),
                    m.AIUsage(user_email="cap-a@example.com", purpose="chat", model="claude-sonnet-5-5", cost_inr=50,
                              created_at=now - timedelta(days=40))])  # outside today and this month
        db.commit()
    try:
        monkeypatch.setattr(s, "ai_monthly_limit_inr", 0)
        monkeypatch.setattr(s, "ai_daily_limit_user_inr", 100)
        ai_usage.check_budget("cap-a@example.com")  # 60 today < 100
        monkeypatch.setattr(s, "ai_daily_limit_user_inr", 60)
        with pytest.raises(ai_usage.BudgetExceeded, match="today"):
            ai_usage.check_budget("cap-a@example.com")
        ai_usage.check_budget("cap-b@example.com")  # another user is not affected
        monkeypatch.setattr(s, "ai_daily_limit_user_inr", 0)  # 0 switches the daily cap off
        ai_usage.check_budget("cap-a@example.com")
        monkeypatch.setattr(s, "ai_monthly_limit_inr", ai_usage.spent_inr(None, ai_usage._month_start(now)))
        with pytest.raises(ai_usage.BudgetExceeded, match="month"):
            ai_usage.check_budget("cap-b@example.com")  # the monthly cap covers everyone
    finally:
        with _session() as db:
            db.query(m.AIUsage).filter(m.AIUsage.user_email == "cap-a@example.com").delete()
            db.commit()


def test_day_boundary_is_indian_time():
    # 20:00 UTC on 7 Nov is already 8 Nov in India
    start = ai_usage._day_start(datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc))
    assert start.isoformat() == "2026-11-08T00:00:00+05:30"
    assert ai_usage._month_start(datetime(2026, 11, 30, 19, 0, tzinfo=timezone.utc)).isoformat() == "2026-12-01T00:00:00+05:30"


def test_ledger_failure_never_loses_the_answer(monkeypatch):
    def broken():
        raise RuntimeError("database down")
    monkeypatch.setattr(ai_usage, "_session", broken)
    assert ai_usage.record("claude-haiku-5-5", {"input_tokens": 10}) >= 0


# ----------------------------------------------------------------------------------------------- feature flags

def test_feature_flags_default_off_and_reported(client, monkeypatch):
    feats = client.get("/api/me").json()["features"]
    assert feats == {"dashboard_chat": False, "agent_loop": False, "memory": False, "global_assistant": False,
                     "scheduled_agents": False}
    monkeypatch.setattr(get_settings(), "assistant_dashboard_chat", True)
    assert client.get("/api/me").json()["features"]["dashboard_chat"] is True


# ----------------------------------------------------------------------------------------------- the harness itself

def _tools(*names):
    return [{"name": n, "description": f"{n} tool", "input_schema": {"type": "object", "properties": {}}} for n in names]


def test_harness_enforces_the_tool_loop_contract():
    call = tool_call("run_query", {"spec": {}})
    fm = FakeMessages([turn(say("Checking."), call), "Done."])
    first = fm.create(model="claude-haiku-5-5", max_tokens=100, messages=[{"role": "user", "content": "q"}],
                      tools=_tools("run_query"))
    assert first.stop_reason == "tool_use"
    good = [{"role": "user", "content": "q"}, {"role": "assistant", "content": first.content},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call.id, "content": "[]"}]}]
    assert fm.create(model="claude-haiku-5-5", max_tokens=100, messages=good, tools=_tools("run_query")).stop_reason == "end_turn"
    assert fm.tool_results()[0]["tool_use_id"] == call.id


def test_harness_catches_a_missing_tool_result():
    call = tool_call("run_query", {})
    fm = FakeMessages([turn(call), "x"])
    fm.create(model="claude-haiku-5-5", max_tokens=10, messages=[{"role": "user", "content": "q"}], tools=_tools("run_query"))
    with pytest.raises(AssertionError, match="tool_result"):
        fm.create(model="claude-haiku-5-5", max_tokens=10, tools=_tools("run_query"),
                  messages=[{"role": "user", "content": "q"}, {"role": "assistant", "content": []},
                            {"role": "user", "content": [{"type": "text", "text": "forgot"}]}])


@pytest.mark.parametrize("kw, msg", [
    ({"model": "claude-opus-5-5"}, "disallowed model"),
    ({"model": "claude-fable-5-1"}, "disallowed model"),
    ({"model": "claude-haiku-5-5", "temperature": 0}, "forbidden"),
    ({"model": "claude-sonnet-5-5", "fallbacks": "default"}, "forbidden"),
    ({"model": "claude-sonnet-5-5", "tool_choice": {"type": "any"}, "tools": _tools("a")}, "forced tool_choice"),
    ({"model": "claude-haiku-5-5", "tools": _tools("a", "a")}, "duplicate tool"),
    ({"model": "claude-haiku-5-5", "tools": [{"name": "a"}]}, "malformed tool"),
])
def test_harness_rejects_requests_that_break_the_rules(kw, msg):
    with pytest.raises(AssertionError, match=msg):
        FakeMessages(["x"]).create(max_tokens=10, messages=[{"role": "user", "content": "q"}], **kw)


def test_harness_rejects_calls_to_undeclared_tools():
    with pytest.raises(AssertionError, match="undeclared"):
        FakeMessages([turn(tool_call("drop_tables", {}))]).create(model="claude-haiku-5-5", max_tokens=10,
                                                                  messages=[{"role": "user", "content": "q"}], tools=_tools("run_query"))


def test_harness_reports_running_out_of_replies():
    with pytest.raises(AssertionError, match="ran out"):
        FakeMessages([]).create(model="claude-haiku-5-5", max_tokens=10, messages=[{"role": "user", "content": "q"}])


# ----------------------------------------------------------------------------------------------- eval runner

def test_number_parsing_handles_indian_formats():
    from evals.runner import parse_numbers

    nums = parse_numbers("Stock is ₹3.86 Cr across 1,23,456 units; slow stock ₹53.2 L; RTO 7.8%; 45,246 orders; 12 locations.")
    for v in (3.86e7, 123456, 5.32e6, 0.078, 7.8, 45246, 12):
        assert any(abs(n - v) <= abs(v) * 1e-9 for n in nums), v


def test_scoring_rules():
    from evals.runner import score

    case = {"id": "c", "expect": {"tolerance": 0.005}, "must_mention": [["location", "store"]], "must_not_mention": ["zero"]}
    ok = score(case, {"type": "answer", "text": "There are 3.86 Cr in 12 locations", "rows": [[38_612_345]],
                      "columns": [{"name": "v", "role": "measure"}]}, 38_612_345)
    assert ok.passed, ok.problems
    bad = score(case, {"type": "answer", "text": "There are zero stores", "rows": [[5]]}, 7)
    assert not bad.passed and len(bad.problems) == 2  # wrong number, forbidden word
    err = score({"id": "e"}, {"type": "error", "text": "boom"}, None)
    assert not err.passed


class _InProcess:
    def __init__(self, client):
        self.client = client

    def _check(self, path, r):
        from evals.runner import EvalError

        if r.status_code >= 400:
            raise EvalError(f"{path}: HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def post(self, path, body):
        return self._check(path, self.client.post(path, json=body))

    def get(self, path):
        return self._check(path, self.client.get(path))

    def delete(self, path):
        r = self.client.delete(path)
        assert r.status_code == 204, r.text


def test_eval_runner_end_to_end_with_the_offline_engine(client, mini):
    from evals.runner import report, run_set

    cases = [{"id": "channels", "question": "How many channels are there?",
              "expect": {"sql": "SELECT COUNT(*) AS n FROM channels"}, "must_mention": [["channel", "channels"]]},
             {"id": "broken-sql", "question": "How many channels are there?", "expect": {"sql": "DELETE FROM channels"}}]
    results = run_set(_InProcess(client), mini["ws"], cases, engine="semantic")
    assert results[0].passed, results[0].problems
    assert results[0].engine == "semantic" and results[0].cost_inr == 0
    assert not results[1].passed and "HTTP 400" in results[1].problems[0]  # the validator refuses a non-SELECT
    assert "1/2 passed" in report(results)


def test_live_runs_need_explicit_ok(monkeypatch, capsys):
    from evals.__main__ import main

    monkeypatch.delenv("EVAL_LIVE_OK", raising=False)
    assert main(["run", "sample", "--live"]) == 2
    assert "EVAL_LIVE_OK" in capsys.readouterr().err


def test_sample_set_loads():
    from evals.runner import load_set

    cases = load_set("sample")
    assert {c["id"] for c in cases} == {"locations-count", "channels-count"}
