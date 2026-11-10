"""Phase 6 of the AI assistants plan: the global assistant on the Ask page. The dashboard index, cross-dashboard tools,
memories from every scope, permissions (no data, memories or mention of a dashboard the person can't see), the index's
size with 10 and 30 dashboards, streaming, older threads, the switch. Claude is scripted (tests/fakes.py)."""
import json

import pytest

from app import models as m
from app.config import get_settings
from app.db import SessionLocal, get_engine
from app.services import memory
from app.services.agent import global_scope, tools as T
from app.services.catalog import load_catalog
from app.services.permissions import set_acting

from conftest import api, build_mini
from fakes import tool_call, turn

NS = {"measures": [{"metric": "net_sales", "alias": "net_sales"}]}
UR = {"measures": [{"metric": "units_returned", "alias": "units_returned"}]}
AUG_SEP = {"from": "2026-08-01", "to": "2026-09-30"}
V = "viewer-global@example.com"


def _db():
    get_engine()
    return SessionLocal()


@pytest.fixture(scope="module")
def ws(client):
    mini = build_mini(client, "global")
    w = mini["ws"]
    for key, name, desc, spec, domain in (
            ("sales-board", "Sales board", "Net sales excluding GST. Second sentence is left out.", NS, "sales"),
            ("returns-board", "Returns board", "Units customers sent back.", UR, "operations"),
            ("secret-board", "Secret board", "Board only admins see.", NS, "executive")):
        d = client.post(api(w, "/dashboards"), json={"name": name, "key": key, "description": desc, "domain": domain, "filters": [
            {"id": "period", "type": "date_range", "label": "Sale date", "field": "@time", "value": AUG_SEP}]}).json()
        client.post(api(w, f"/dashboards/{d['id']}/widgets"), json={"title": f"{name} headline", "chart_type": "kpi", "spec": spec})
    client.put(api(w, "/members"), json={"user_email": V, "role": "viewer"})
    r = client.post(api(w, "/access-rules"), json={"target_type": "dashboard", "target": "secret-board",
                                                   "principal_type": "role", "principal": "admin"})
    assert r.status_code == 201, r.text
    return w


@pytest.fixture()
def on(monkeypatch):
    s = get_settings()
    for flag in ("assistant_dashboard_chat", "assistant_agent_loop", "assistant_global", "assistant_memory", "assistant_data_issues"):
        monkeypatch.setattr(s, flag, True)


@pytest.fixture(autouse=True)
def clean(ws):
    yield
    with _db() as db:
        for t in (m.Memory, m.DataIssue, m.DashboardInsight):
            db.query(t).filter_by(workspace_id=ws).delete()
        db.query(m.Job).delete()
        db.commit()


def ask(client, ws, q, conv=None, user=None, engine="auto", status=200):
    r = client.post(api(ws, "/assistant/ask"), json={"question": q, "conversation_id": conv, "engine": engine},
                    headers={"X-User-Email": user} if user else {})
    assert r.status_code == status, r.text
    return r.json()


def as_person(db, ws_id, user, role):
    return set_acting(db.get(m.Workspace, ws_id), user, role)


# ----------------------------------------------------------------------------------------------- the global assistant

def test_the_ask_page_answers_with_the_global_assistant(client, ws, on, fake_claude):
    fm = fake_claude(turn(tool_call("get_widget_data", {"dashboard_key": "sales-board", "widget": "Sales board headline"}),
                          tool_call("get_widget_data", {"dashboard_key": "returns-board", "widget": "Returns board headline"})),
                     "Sales board: net sales ₹1,160. Returns board: 4 units returned.")
    out = ask(client, ws, "compare the sales board with the returns board")
    system = "\n".join(b["text"] for b in fm.calls[0]["system"])
    assert "company-wide analytics assistant" in system and "DASHBOARDS this user can see (3)" in system
    assert "- Sales board [key sales-board, domain sales]: Net sales excluding GST." in system
    assert "Second sentence" not in system                                   # cards carry the first sentence only
    assert "Headline tiles: Sales board headline." in system and "Metrics: Net sales." in system
    assert [s["tool"] for s in out["steps"]] == ["get_widget_data", "get_widget_data"]
    res = [json.loads(b["content"]) for b in fm.tool_results(1)]
    assert res[0]["rows"] == [["₹1,160"]] and "Sale date" in res[0]["notes"][0]   # each dashboard's own default filters
    assert res[1]["rows"] == [["4"]]
    with _db() as db:
        c = db.get(m.Conversation, out["conversation_id"])
        assert c.scope_type == "global" and c.dashboard_key is None
        assert db.query(m.AuditEvent).filter_by(action="assistant_ask", target="global").count() >= 1


def test_streaming_on_the_ask_page(client, ws, on, fake_claude):
    fake_claude(turn(tool_call("run_query", {"spec": {**NS, "time_range": AUG_SEP}, "title": "Net sales"})), "Net sales were ₹1,160.")
    with client.stream("POST", api(ws, "/assistant/ask/stream"), json={"question": "net sales Aug-Sep 2026"}) as r:
        body = "".join(r.iter_text())
    events = [line[7:] for line in body.splitlines() if line.startswith("event: ")]
    assert events == ["step", "step_done", "answer"]
    answer = json.loads(body.split("event: answer\ndata: ")[1].split("\n\n")[0])["answer"]
    assert answer["text"] == "Net sales were ₹1,160." and answer["engine"] == "claude"


def test_old_threads_continue_and_are_listed(client, ws, on, fake_claude, monkeypatch):
    monkeypatch.setattr(get_settings(), "assistant_global", False)
    fake_claude({"kind": "spec", "title": "t", "chart": "auto", "assumptions": [], "clarification": "", "spec": json.dumps(NS), "sql": ""},
                "₹1,160.")
    old = ask(client, ws, "net sales")
    monkeypatch.setattr(get_settings(), "assistant_global", True)
    fm = fake_claude("Still ₹1,160.")
    again = ask(client, ws, "and again?", conv=old["conversation_id"])
    assert again["conversation_id"] == old["conversation_id"]                # the older thread continues
    assert "net sales" in json.dumps(fm.calls[0]["messages"])
    listed = {c["id"]: c["scope_type"] for c in client.get(api(ws, "/conversations")).json()}
    assert listed[old["conversation_id"]] == "workspace"
    fake_claude("New.")
    new = ask(client, ws, "something new")
    assert client.get(api(ws, "/conversations")).json()[0]["id"] == new["conversation_id"]


def test_only_admins_get_it_and_the_semantic_engine_stays_offline(client, ws, on, fake_claude):
    fm = fake_claude({"kind": "spec", "title": "t", "chart": "auto", "assumptions": [], "clarification": "", "spec": json.dumps(NS), "sql": ""},
                     "₹1,160.")
    out = ask(client, ws, "net sales", user=V)
    assert "steps" not in out and "tools" not in fm.calls[0]                  # a viewer keeps the Phase 0 path
    fm = fake_claude()
    out = ask(client, ws, "net sales Aug-Sep 2026", engine="semantic")
    assert out["engine"] == "semantic" and fm.calls == []


def test_the_ask_page_can_still_create_a_dashboard(client, ws, on, fake_claude):
    fake_claude()
    out = ask(client, ws, "Create a dashboard showing monthly net sales and units returned")
    assert out["type"] == "dashboard" and out["dashboard_id"]
    client.delete(api(ws, f"/dashboards/{out['dashboard_id']}"))


def test_without_the_flag_nothing_changes(client, ws, fake_claude, monkeypatch):
    monkeypatch.setattr(get_settings(), "assistant_agent_loop", True)
    fm = fake_claude({"kind": "spec", "title": "t", "chart": "auto", "assumptions": [], "clarification": "", "spec": json.dumps(NS), "sql": ""},
                     "₹1,160.")
    out = ask(client, ws, "net sales")
    assert "steps" not in out and "tools" not in fm.calls[0]
    with _db() as db:
        assert db.get(m.Conversation, out["conversation_id"]).scope_type == "workspace"


# ----------------------------------------------------------------------------------------------- memory

def test_memories_from_every_scope_say_where_they_came_from(client, ws, on, fake_claude):
    with _db() as db:
        w = db.get(m.Workspace, ws)
        here, _ = memory.save(db, w, "owner@local", "On the returns board, count only customer returns", "preference",
                              scope="dashboard:returns-board")
        dec, _ = memory.save(db, w, "owner@local", "Stop discounting Gizmo", "decision", scope="domain:sales",
                             rationale="margin too thin")
        ids = (here.id, dec.id)
    fm = fake_claude(f"You decided to stop discounting Gizmo (memory #{ids[1]}).")
    out = ask(client, ws, "what did I decide about Gizmo discounts?")
    p = fm.calls[0]["messages"][-1]["content"]
    assert f"#{ids[0]} [preference, returns-board dashboard" in p and f"#{ids[1]} [decision, sales dashboards" in p
    assert [x["id"] for x in out["memories_used"]] == [ids[1]]


def test_remember_on_the_ask_page_is_global(client, ws, on, fake_claude):
    fake_claude(turn(tool_call("propose_memory", {"text": "Show amounts in lakhs", "kind": "preference", "scope": "this_dashboard"})), "Saved.")
    out = ask(client, ws, "remember to show amounts in lakhs")
    assert out["memories_saved"][0]["scope"] == "global" and out["memories_saved"][0]["status"] == "active"


# ----------------------------------------------------------------------------------------------- permissions

def test_a_dashboard_the_person_cannot_see_does_not_exist_for_them(client, ws, on):
    with _db() as db:
        w = as_person(db, ws, V, "viewer")
        cat = load_catalog(db, w)
        index = global_scope.build_index(db, w, cat)
        assert "(2)" in index and "Secret board" not in index and "secret-board" not in index
        ctx = T.ToolContext(db=db, ws=w, cat=cat, user=V, memory_on=True)
        for name, args in (("get_dashboard_context", {"dashboard_key": "secret-board"}),
                           ("get_widget_data", {"dashboard_key": "secret-board", "widget": "Secret board headline"})):
            out = T.execute(ctx, name, args)
            assert not out.ok and "secret-board" not in out.content.split("Keys:")[-1], out.content
        # an admin sees all three
        a = as_person(db, ws, "owner@local", "admin")
        assert "(3)" in global_scope.build_index(db, a, load_catalog(db, a))


def test_no_memories_or_issues_about_a_hidden_dashboard(client, ws, on):
    with _db() as db:
        owner = as_person(db, ws, "owner@local", "admin")
        mem, _ = memory.save(db, owner, "owner@local", "Secret board numbers are provisional", "caveat",
                             scope="dashboard:secret-board")
        memory.act(db, owner, "owner@local", mem, "share")            # a team fact suggestion...
        memory.act(db, owner, "owner@local", mem, "approve_share")    # ...approved: visible to members who can see it
        db.add(m.DataIssue(workspace_id=ws, code="D-990", title="Secret board feed is late", status="open",
                           affects={"dashboards": ["secret-board"]}))
        db.add(m.DataIssue(workspace_id=ws, code="D-991", title="Returns lag a week", status="open",
                           affects={"dashboards": ["returns-board"]}))
        db.commit()
        v = as_person(db, ws, V, "viewer")
        got = memory.retrieve(db, v, V, None, "secret board numbers", everywhere=True)
        assert got == []
        a = as_person(db, ws, "owner@local", "admin")
        assert [x.id for x in memory.retrieve(db, a, "owner@local", None, "secret board numbers", everywhere=True)] == [mem.id]
        v = as_person(db, ws, V, "viewer")
        ctx = T.ToolContext(db=db, ws=v, cat=load_catalog(db, v), user=V)
        codes = [i["code"] for i in json.loads(T.execute(ctx, "get_data_issues", {}).content)["issues"]]
        assert codes == ["D-991"]
        index = global_scope.build_index(db, v, load_catalog(db, v))
        assert "D-990" not in index and "Open data issues: 1 (D-991)" in index


# ----------------------------------------------------------------------------------------------- size

@pytest.mark.parametrize("n", [10, 30])
def test_the_index_stays_within_budget(client, on, n):
    r = client.post("/api/workspaces", json={"name": f"many-{n}"})
    w = r.json()["id"]
    try:
        from conftest import upload_csv

        ds = upload_csv(client, w, "s.csv", "d,amount\n2026-01-01,5\n", name="Sales")["dataset"]
        client.post(api(w, "/metrics"), json={"kind": "simple", "name": "amt", "label": "Amount", "dataset_id": ds["id"],
                                              "expression": "SUM(amount)", "time_column": "d"})
        for i in range(n):
            d = client.post(api(w, "/dashboards"), json={"name": f"Dashboard number {i:02d}", "key": f"d{i:02d}",
                                                         "description": ("A long description sentence about this board " * 12) + "."}).json()
            for j in range(12):
                client.post(api(w, f"/dashboards/{d['id']}/widgets"), json={"title": f"Tile {j} with a fairly long title", "chart_type": "kpi",
                                                                           "spec": {"measures": [{"metric": "amt"}]}})
        with _db() as db:
            x = as_person(db, w, "owner@local", "admin")
            index = global_scope.build_index(db, x, load_catalog(db, x))
        assert len(index) <= global_scope.INDEX_CHAR_BUDGET + 2000          # cards within budget + the overflow list
        assert all(f"d{i:02d}" in index for i in range(n))                  # every dashboard is at least named
        assert index.count("[key ") >= min(n, 10)
    finally:
        client.delete(f"/api/workspaces/{w}")


def test_index_shows_issues_and_worth_a_look(client, ws, on):
    with _db() as db:
        db.add(m.DataIssue(workspace_id=ws, code="D-995", title="x", status="open", affects={"metrics": ["net_sales"]}))
        db.add(m.DashboardInsight(workspace_id=ws, dashboard_key="sales-board", fingerprint="f", items=[
            {"kind": "vs_last_year", "metric": "net_sales", "text": "Net sales: down 12.0% on the same period last year."},
            {"kind": "stale", "metric": None, "text": "The data ends on 15 Sep 2026."}]))
        db.commit()
        a = as_person(db, ws, "owner@local", "admin")
        index = global_scope.build_index(db, a, load_catalog(db, a))
    card = index.split("- Sales board")[1].split("\n- ")[0]
    assert "Open data issues: 1 (D-995)" in card and "Worth a look: Net sales: down 12.0%" in card and "data ends" not in card


# ----------------------------------------------------------------------------------------------- eval set

def test_global_set_is_well_formed():
    from evals.runner import load_set

    cases = load_set("global")
    assert len(cases) == 25 and not any(c.get("dashboard") for c in cases)       # all asked on the Ask page
    for c in cases:
        for ex in [c.get("expect") or {}] + list(c.get("also_expect") or []):
            if "widget" in ex:
                assert ex.get("dashboard"), c["id"]
        assert "context_dashboards" in c, c["id"]


def test_runner_checks_both_numbers_of_a_comparison(client, ws, on, fake_claude):
    from evals.runner import run_set

    from test_dashboard_chat import _InProcess

    case = {"question": "compare", "expect": {"dashboard": "sales-board", "widget": "Sales board headline"},
            "also_expect": [{"dashboard": "returns-board", "widget": "Returns board headline"}],
            "context_dashboards": ["sales-board", "returns-board"]}
    reads = turn(tool_call("get_widget_data", {"dashboard_key": "sales-board", "widget": "Sales board headline"}),
                 tool_call("get_widget_data", {"dashboard_key": "returns-board", "widget": "Returns board headline"}))
    fake_claude(reads, "Sales board ₹1,160; returns board 4 units.")
    (good,) = run_set(_InProcess(client), ws, [{"id": "good", **case}], engine="auto")
    assert good.passed, good.problems
    fake_claude(turn(tool_call("get_widget_data", {"dashboard_key": "sales-board", "widget": "Sales board headline"})), "Sales board ₹1,160.")
    (bad,) = run_set(_InProcess(client), ws, [{"id": "bad", **case}], engine="auto")
    assert not bad.passed and "Returns board headline" in bad.problems[-1]
