"""Phase 1 of the AI assistants plan: a chat on each dashboard that knows the dashboard and what is on screen.

The mini workspace's sales (net_sales = SUM(amount) of Sale rows): Aug-Sep 2026 = 1,160 (Amazon 650, Shopify 510);
all dates = 1,390."""
import json

import pytest

from app import models as m
from app.config import get_settings
from app.db import SessionLocal, get_engine
from app.services.agent import context as actx
from app.services.catalog import load_catalog

from conftest import api, build_mini

AUG_SEP = {"from": "2026-08-01", "to": "2026-09-30"}


def _plan(spec=None, kind="spec", assumptions=None, clarification=""):
    return {"kind": kind, "title": "t", "chart": "auto", "assumptions": assumptions or [], "clarification": clarification,
            "spec": json.dumps(spec) if spec is not None else "", "sql": ""}


@pytest.fixture(scope="module")
def board(client):
    mini = build_mini(client, "dashchat")
    ws = mini["ws"]
    d = client.post(api(ws, "/dashboards"), json={
        "name": "Sales board", "key": "sales-board", "domain": "sales",
        "description": "Net sales excluding GST. Transfers are not sales. CAVEAT-MARKER: Amazon reports late.",
        "filters": [{"id": "period", "type": "date_range", "label": "Sale date", "field": "@time", "value": AUG_SEP},
                    {"id": "channel", "type": "values", "label": "Channel", "field": "channels.channel", "value": []}]}).json()
    widgets = {}
    for title, ct, spec, opts in (
            ("Net sales", "kpi", {"measures": [{"metric": "net_sales"}]}, {}),
            ("Net sales by channel", "bar", {"dimensions": [{"field": "channels.channel"}], "measures": [{"metric": "net_sales"}]},
             {"drill_path": ["products.product_name"]}),
            ("Units returned", "kpi", {"measures": [{"metric": "units_returned"}]}, {})):
        r = client.post(api(ws, f"/dashboards/{d['id']}/widgets"), json={"title": title, "chart_type": ct, "spec": spec, "options": opts})
        assert r.status_code == 201, r.text
        widgets[title] = r.json()["id"]
    return {"ws": ws, "dash": d["id"], "w": widgets}


@pytest.fixture()
def chat_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "assistant_dashboard_chat", True)


def ask(client, board, question, screen=None, conv=None, engine="auto", status=200, headers=None):
    r = client.post(api(board["ws"], "/dashboards/key/sales-board/assistant/ask"),
                    json={"question": question, "conversation_id": conv, "engine": engine, "screen_state": screen or {}},
                    headers=headers or {})
    assert r.status_code == status, r.text
    return r.json()


def _session():
    get_engine()
    return SessionLocal()


def _dash(board):
    with _session() as db:
        d = db.get(m.Dashboard, board["dash"])
        cat = load_catalog(db, db.get(m.Workspace, board["ws"]))
        return db, d, cat


# ----------------------------------------------------------------------------------------------- access

def test_switched_off_by_default(client, board):
    ask(client, board, "net sales", status=403)
    r = client.get(api(board["ws"], "/dashboards/key/sales-board/assistant/conversations"))
    assert r.status_code == 403


def test_admins_only_until_real_sign_in(client, board, chat_on):
    client.put(api(board["ws"], "/members"), json={"user_email": "viewer-chat@example.com", "role": "viewer"})
    client.put(api(board["ws"], "/members"), json={"user_email": "editor-chat@example.com", "role": "editor"})
    for who in ("viewer-chat@example.com", "editor-chat@example.com", "stranger@example.com"):
        ask(client, board, "net sales", headers={"X-User-Email": who}, status=403)


def test_unknown_dashboard_key(client, board, chat_on):
    r = client.post(api(board["ws"], "/dashboards/key/nope/assistant/ask"), json={"question": "x"})
    assert r.status_code == 404


# ----------------------------------------------------------------------------------------------- the pack

def test_pack_describes_the_dashboard(board):
    with _session() as db:
        d = db.get(m.Dashboard, board["dash"])
        cat = load_catalog(db, db.get(m.Workspace, board["ws"]))
        pack = actx.build_dashboard_pack(db, d, cat)
    assert "DASHBOARD: Sales board" in pack and "key sales-board" in pack
    assert "CAVEAT-MARKER" in pack                                  # the description with its caveats
    for t in ("Net sales", "Net sales by channel", "Units returned"):
        assert f"\"{t}\"" in pack
    assert "Sale date [id period]" in pack and "2026-08-01 to 2026-09-30" in pack
    assert "Channel [id channel]" in pack and "default All" in pack
    assert "net_sales \"Net sales\" = SUM(amount)" in pack and "only where txn_type = Sale" in pack   # metric rule
    assert "units_returned" in pack
    assert "drill-down:" in pack
    assert "DATA BEHIND THE WIDGETS" in pack and "sales (Sales): 8 rows; dates 2026-07-10 to 2026-10-05" in pack
    assert len(pack) <= actx.PACK_CHAR_BUDGET


def test_pack_is_rebuilt_when_a_widget_changes(client, board):
    with _session() as db:
        d = db.get(m.Dashboard, board["dash"])
        cat = load_catalog(db, db.get(m.Workspace, board["ws"]))
        before = actx.build_dashboard_pack(db, d, cat)
    wid = board["w"]["Units returned"]
    client.put(api(board["ws"], f"/dashboards/{board['dash']}/widgets/{wid}"),
               json={"title": "Units returned (all)", "chart_type": "kpi", "spec": {"measures": [{"metric": "units_returned"}]}})
    try:
        with _session() as db:
            d = db.get(m.Dashboard, board["dash"])
            cat = load_catalog(db, db.get(m.Workspace, board["ws"]))
            after = actx.build_dashboard_pack(db, d, cat)
        assert "Units returned (all)" in after and after != before
    finally:
        client.put(api(board["ws"], f"/dashboards/{board['dash']}/widgets/{wid}"),
                   json={"title": "Units returned", "chart_type": "kpi", "spec": {"measures": [{"metric": "units_returned"}]}})


def test_long_dashboards_stay_within_budget(monkeypatch, board):
    monkeypatch.setattr(actx, "PACK_CHAR_BUDGET", 900)
    with _session() as db:
        d = db.get(m.Dashboard, board["dash"])
        cat = load_catalog(db, db.get(m.Workspace, board["ws"]))
        actx._pack_cache.clear()
        pack = actx.build_dashboard_pack(db, d, cat)
    actx._pack_cache.clear()
    assert len(pack) <= 900


# ----------------------------------------------------------------------------------------------- screen state

@pytest.mark.parametrize("screen, msg", [
    ({"filters": [{"id": "nope", "value": []}]}, "Unknown dashboard filter"),
    ({"filters": [{"id": "period", "value": {"from": "yesterday-ish"}}]}, "Invalid date range"),
    ({"filters": [{"id": "period", "value": "next_century"}]}, "Invalid date range"),
    ({"filters": [{"id": "channel", "value": [{"x": 1}]}]}, "Invalid values"),
    ({"drill": {"999999": [{"field": "channels.channel", "value": "Amazon"}]}}, "not on this dashboard"),
    ({"focus_widget_id": 999999}, "not on this dashboard"),
])
def test_screen_state_is_validated(client, board, chat_on, screen, msg):
    out = ask(client, board, "net sales", screen=screen, status=400)
    assert msg in out["detail"]


def test_drill_only_on_the_widgets_own_fields(client, board, chat_on):
    wid = str(board["w"]["Net sales by channel"])
    out = ask(client, board, "net sales", screen={"drill": {wid: [{"field": "sales.amount", "value": 1}]}}, status=400)
    assert "Invalid drill-down" in out["detail"]


def test_screen_numbers_are_recomputed_on_the_server(board):
    db, d, cat = _dash(board)
    with _session() as db:
        d = db.get(m.Dashboard, board["dash"])
        screen = actx.validate_screen(d, {"filters": [{"id": "channel", "value": ["Amazon"]}],
                                          "focus_widget_id": board["w"]["Net sales by channel"]})
        text = actx.screen_summary(db, d, cat, screen, "owner@local")
    lines = text.splitlines()
    assert lines[0] == "FILTERS IN FORCE: Sale date = 2026-08-01 to 2026-09-30; Channel = Amazon"
    assert lines[1].startswith("THE USER IS ASKING ABOUT THIS WIDGET -> \"Net sales by channel\"")  # focus first
    assert "\"Net sales\": Net sales ₹650" in text                    # Aug-Sep Amazon only, recomputed
    # channel can't reach returns: the number covers all channels, and the summary says so instead of hiding it
    assert "\"Units returned\": Units returned 4  [NOTE: Filter on 'channels.channel' does not apply" in text
    assert "NOT filtered by it" in text
    assert len(text) <= actx.SCREEN_CHAR_BUDGET


def test_screen_defaults_and_drill(board):
    with _session() as db:
        d = db.get(m.Dashboard, board["dash"])
        cat = load_catalog(db, db.get(m.Workspace, board["ws"]))
        screen = actx.validate_screen(d, {"drill": {str(board["w"]["Net sales by channel"]): [{"field": "channels.channel", "value": "Shopify"}]}})
        assert screen.filters[0]["value"] == AUG_SEP                    # omitted filters keep the dashboard default
        text = actx.screen_summary(db, d, cat, screen, "owner@local")
    assert "\"Net sales by channel\" (drilled into Shopify)" in text and "₹510" in text


# ----------------------------------------------------------------------------------------------- filter inheritance

def test_question_inherits_the_dashboard_period_and_filters(client, board, chat_on, fake_claude):
    fm = fake_claude(_plan({"measures": [{"metric": "net_sales", "alias": "net_sales"}]}), "Net sales were 650.")
    out = ask(client, board, "What were net sales?", screen={"filters": [{"id": "channel", "value": ["Amazon"]}]})
    assert out["type"] == "answer" and out["rows"] == [[650.0]]
    assert out["spec"]["time_range"] == AUG_SEP
    assert any("Sale date: 2026-08-01 to 2026-09-30" in a for a in out["assumptions"])
    assert any("Channel filter (channels.channel): Amazon" in a for a in out["assumptions"])
    # the pack is a cached system block after the schema; the screen and today's date are in the user turn
    system = fm.calls[0]["system"]
    assert "DASHBOARD: Sales board" in system[-1]["text"] and system[-1]["cache_control"] == {"type": "ephemeral"}
    assert "SCREEN STATE" in fm.calls[0]["messages"][-1]["content"]
    assert "Channel = Amazon" in fm.calls[0]["messages"][-1]["content"]
    assert "Today is" not in json.dumps(system) and "FILTERS IN FORCE" not in json.dumps(system)  # volatile parts uncached


def test_question_with_its_own_period_and_channel_keeps_them(client, board, chat_on, fake_claude):
    fake_claude(_plan({"measures": [{"metric": "net_sales", "alias": "net_sales"}], "time_range": {"from": "2026-07-01", "to": "2026-10-31"},
                       "filters": [{"field": "channels.channel", "op": "eq", "value": "Shopify"}]}), "ok")
    out = ask(client, board, "Shopify net sales Jul-Oct?", screen={"filters": [{"id": "channel", "value": ["Amazon"]}]})
    assert out["rows"] == [[710.0]]                                   # 200 + 450 + 60, not Amazon, not Aug-Sep only
    assert not any("dashboard's" in a for a in out["assumptions"])


def test_filter_that_cannot_reach_the_data_is_left_out_and_said(client, board, chat_on, fake_claude):
    fake_claude(_plan({"measures": [{"metric": "units_returned", "alias": "u"}]}), "ok")
    out = ask(client, board, "How many units were returned?", screen={"filters": [{"id": "channel", "value": ["Amazon"]}]})
    assert out["type"] == "answer" and out["rows"] == [[4.0]]         # Aug-Sep returns of every channel
    assert any("does not apply to this data" in a and "covers all values" in a for a in out["assumptions"])
    assert not any("Channel filter (channels.channel)" in a for a in out["assumptions"])   # not claimed as applied
    assert any("Sale date" in a for a in out["assumptions"])                              # the period still applied


def test_offline_engine_also_uses_the_dashboard_filters(client, board, chat_on):
    out = ask(client, board, "net sales", engine="semantic", screen={"filters": [{"id": "channel", "value": ["Shopify"]}]})
    assert out["engine"] == "semantic" and out["rows"][0][-1] == 510.0


# ----------------------------------------------------------------------------------------------- threads

def test_threads_are_per_dashboard_and_per_user(client, board, chat_on, fake_claude):
    ws = board["ws"]
    fake_claude(_plan({"measures": [{"metric": "net_sales", "alias": "n"}]}), "1,160.")
    first = ask(client, board, "net sales?")
    with _session() as db:
        c = db.get(m.Conversation, first["conversation_id"])
        assert (c.scope_type, c.dashboard_key) == ("dashboard", "sales-board")
        user_msg, answer_msg = c.messages
        assert user_msg.screen_state["filters"][0] == {"id": "period", "value": AUG_SEP}
        assert answer_msg.model == "claude-haiku-5-5" and answer_msg.usage["input_tokens"] == 100
    listed = client.get(api(ws, "/dashboards/key/sales-board/assistant/conversations")).json()
    assert first["conversation_id"] in {t["id"] for t in listed}
    assert first["conversation_id"] not in {t["id"] for t in client.get(api(ws, "/conversations")).json()}  # not on Ask
    # another dashboard (or the Ask page) can't continue this thread
    other = client.post(api(ws, "/dashboards"), json={"name": "Other board", "key": "other-board"}).json()
    fake_claude(_plan({"measures": [{"metric": "net_sales", "alias": "n"}]}), "ok")
    r = client.post(api(ws, "/dashboards/key/other-board/assistant/ask"),
                    json={"question": "and units?", "conversation_id": first["conversation_id"]}).json()
    assert r["conversation_id"] != first["conversation_id"]
    fake_claude(_plan({"measures": [{"metric": "net_sales", "alias": "n"}]}), "ok")
    r = client.post(api(ws, "/assistant/ask"), json={"question": "x", "conversation_id": first["conversation_id"]}).json()
    assert r["conversation_id"] != first["conversation_id"]
    # another admin sees none of my threads and can't continue them
    client.put(api(ws, "/members"), json={"user_email": "admin2-chat@example.com", "role": "admin"})
    h = {"X-User-Email": "admin2-chat@example.com"}
    assert client.get(api(ws, "/dashboards/key/sales-board/assistant/conversations"), headers=h).json() == []
    assert client.get(api(ws, f"/conversations/{first['conversation_id']}"), headers=h).status_code == 404
    fake_claude(_plan({"measures": [{"metric": "net_sales", "alias": "n"}]}), "ok")
    r = ask(client, board, "follow up", conv=first["conversation_id"], headers=h)
    assert r["conversation_id"] != first["conversation_id"]
    client.delete(api(ws, f"/dashboards/{other['id']}"))


def test_follow_up_continues_the_thread_with_history(client, board, chat_on, fake_claude):
    fake_claude(_plan({"measures": [{"metric": "net_sales", "alias": "n"}]}), "Net sales were 1,160.")
    first = ask(client, board, "net sales?")
    fm = fake_claude(_plan({"dimensions": [{"field": "channels.channel"}], "measures": [{"metric": "net_sales", "alias": "n"}]}), "ok")
    second = ask(client, board, "by channel", conv=first["conversation_id"])
    assert second["conversation_id"] == first["conversation_id"]
    sent = json.dumps(fm.calls[0]["messages"])
    assert "net sales?" in sent and "Net sales were 1,160." in sent


def test_dashboard_chat_never_creates_dashboards(client, board, chat_on, fake_claude):
    fm = fake_claude()
    before = len(client.get(api(board["ws"], "/dashboards")).json())
    out = ask(client, board, "Create a dashboard showing monthly net sales and units returned")
    assert out["type"] == "help" and "can't create or change dashboards" in out["text"]
    assert len(client.get(api(board["ws"], "/dashboards")).json()) == before and fm.calls == []


# ----------------------------------------------------------------------------------------------- feedback

def test_feedback_on_answers(client, board, chat_on, fake_claude):
    ws = board["ws"]
    fake_claude(_plan({"measures": [{"metric": "net_sales", "alias": "n"}]}), "ok")
    out = ask(client, board, "net sales?")
    cid, mid = out["conversation_id"], out["message_id"]
    url = api(ws, f"/conversations/{cid}/messages/{mid}/feedback")
    assert client.post(url, json={"feedback": "down", "note": "wrong period"}).json() == {"id": mid, "feedback": "down", "note": "wrong period"}
    msgs = client.get(api(ws, f"/conversations/{cid}")).json()["messages"]
    assert msgs[-1]["feedback"] == "down"
    assert client.post(url, json={"feedback": None}).json()["feedback"] is None
    assert client.post(url, json={"feedback": "meh"}).status_code == 422
    user_mid = msgs[0]["id"]
    assert client.post(api(ws, f"/conversations/{cid}/messages/{user_mid}/feedback"), json={"feedback": "up"}).status_code == 404
    client.put(api(ws, "/members"), json={"user_email": "admin3-chat@example.com", "role": "admin"})
    assert client.post(url, json={"feedback": "up"}, headers={"X-User-Email": "admin3-chat@example.com"}).status_code == 404


# ----------------------------------------------------------------------------------------------- eval runner on dashboards

def test_rounding_aware_number_matching():
    from evals.runner import _matches, number_tokens

    def m(text, target):
        return any(_matches(n, target) for n in number_tokens(text))
    assert m("₹3.86 Cr", 38_612_345) and m("₹53 L", 5_320_000) and m("25 hours", 25.4) and m("7.8%", 0.0784)
    assert m("1,23,456 units", 123_456) and m("45,246 orders", 45_246)
    assert not m("₹3.9 Cr", 38_000_000) and not m("26 hours", 25.4) and not m("8.1%", 0.0784)


def test_invented_numbers_are_caught():
    from evals.runner import invented_numbers

    ans = {"type": "answer", "text": "Net sales were 1,160 in Aug-Sep 2026 (15 Sep 2026); Amazon had 650, 56% of the total, "
                                     "and Shopify 999.",
           "columns": [{"name": "channel", "role": "dimension"}, {"name": "n", "role": "measure"}],
           "rows": [["Amazon", 650.0], ["Shopify", 510.0]], "assumptions": []}
    assert invented_numbers(ans) == ["999"]       # 1,160 is the total, 56% a share; dates are not data


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


def test_eval_runner_asks_the_dashboard_with_widget_expectations(client, board, chat_on):
    from evals.runner import run_set, summary

    cases = [{"id": "kpi", "dashboard": "sales-board", "question": "net sales", "expect": {"widget": "Net sales"}},
             {"id": "filtered", "dashboard": "sales-board", "question": "net sales",
              "screen_state": {"filters": [{"id": "channel", "value": ["Amazon"]}]}, "expect": {"widget": "Net sales"}},
             {"id": "top", "dashboard": "sales-board", "question": "net sales by channel",
              "expect": {"widget": "Net sales by channel", "top": True}},
             {"id": "row", "dashboard": "sales-board", "question": "net sales by channel",
              "expect": {"widget": "Net sales by channel", "row": "shop"}},
             {"id": "missing-widget", "dashboard": "sales-board", "question": "x", "expect": {"widget": "Nope"}}]
    url = api(board["ws"], "/dashboards/key/sales-board/assistant/conversations")
    before = {t["id"] for t in client.get(url).json()}
    res = {r.id: r for r in run_set(_InProcess(client), board["ws"], cases, engine="semantic")}
    assert res["kpi"].passed and res["kpi"].expected == 1160.0, res["kpi"].problems
    assert res["filtered"].passed and res["filtered"].expected == 650.0, res["filtered"].problems
    assert res["top"].passed and res["top"].expected_label == "Amazon", res["top"].problems
    assert res["row"].passed and res["row"].expected == 510.0, res["row"].problems
    assert not res["missing-widget"].passed and "not on dashboard" in res["missing-widget"].problems[0]
    s = summary(list(res.values()))
    assert (s["cases"], s["passed"], s["invented"]) == (5, 4, 0)
    # the runner removes the threads it created
    assert {t["id"] for t in client.get(url).json()} == before


def test_dashboard_basic_set_is_well_formed():
    from evals.runner import load_set

    cases = load_set("dashboard_basic")
    assert len(cases) == 80
    keys = {"executive-overview", "sales-channels", "returns", "stock", "fulfilment", "purchasing-transfers",
            "discontinued-slow-stock", "days-of-cover", "instamart", "data-health"}
    for k in keys:
        assert sum(c["dashboard"] == k for c in cases) == 8, k
    assert all(c.get("expect") or c.get("must_mention") for c in cases)
