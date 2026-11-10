"""Phase 7 of the AI assistants plan: scheduled domain agents in the app. Alerts read from the warehouse views
(here: CSV datasets with the same columns), decisions (who, when, refused on a resolved alert, saved as decision
memories), notices after a sync (once each), the executive briefing (facts in code, numbers checked, same facts = same
briefing), the domain assistants and get_alerts, admins only, the switch. Claude is scripted (tests/fakes.py)."""
import json

import pytest

from app import models as m
from app.config import get_settings
from app.db import SessionLocal, get_engine
from app.services import domain_agents as da, jobs
from app.services.agent import tools as T
from app.services.catalog import load_catalog
from app.services.permissions import set_acting

from conftest import api, build_mini, upload_csv
from fakes import tool_call, turn

AUG_SEP = {"from": "2026-08-01", "to": "2026-09-30"}
V = "viewer-agents@example.com"
ALERT_HEAD = ("alert_id,alert_code,rule_name,agent,severity,status,sku_code,product_name,location_code,location_name,"
              "document_ref,metric_value,threshold_value,message,details,raised_date,last_seen_at,handled_by,handled_at,"
              "raised_as_of_date,last_seen_as_of_date\n")
A1 = ('1,STK-A01,Stock-out with demand,STOCK,CRITICAL,OPEN,P1,Widget,BAGRU,Bagru Warehouse,,0,0,'
      '"Widget (P1) has no sellable stock at Bagru Warehouse; in the 30 days to 15 Sep 2026 it sold 12 units there.",'
      '"{""units_sold_30d"": 12, ""units_sent_30d"": 0, ""sellable_qty"": 0}",2026-11-10,2026-11-10 10:00:00,,,2026-09-15,2026-09-15\n')
A2 = ('2,STK-A02,Low cover,STOCK,WARNING,OPEN,P2,Gadget,FBA1,Amazon FBA 1,,3.5,7,'
      '"Gadget (P2) at Amazon FBA 1: 7 sellable units last 3.5 days at 2.00 units a day, below the 7-day threshold.",'
      '"{""sellable_qty"": 7, ""days_of_cover"": 3.5}",2026-11-10,2026-11-10 10:00:00,,,2026-09-15,2026-09-15\n')
A3 = ('3,OPS-A02,Purchase order overdue,OPERATIONS,CRITICAL,OPEN,,,,,PO/10,42,14,'
      '"Purchase order PO/10 from Fair Pack: 563 units on 3 lines still pending, 42 days past the due date of 15 Aug 2026.",'
      '"{""pending_units"": 563, ""days_overdue"": 42}",2026-11-10,2026-11-10 10:00:00,,,2026-09-15,2026-09-15\n')
A4 = ('4,OPS-A02,Purchase order overdue,OPERATIONS,WARNING,RESOLVED,,,,,PO/9,5,14,'
      '"Purchase order PO/9 from Smart Art: 40 units on 1 line still pending, 5 days past the due date of 10 Sep 2026.",'
      '"{}",2026-11-01,2026-11-01 10:00:00,operations_ai,2026-11-05 10:00:00,2026-09-15,2026-09-15\n')
A5 = ('5,STK-A01,Stock-out with demand,STOCK,CRITICAL,OPEN,P3,Gizmo,BAGRU,Bagru Warehouse,,0,0,'
      '"Gizmo (P3) has no sellable stock at Bagru Warehouse; in the 30 days to 15 Sep 2026 it sold 4 units there.",'
      '"{""units_sold_30d"": 4}",2026-11-11,2026-11-11 10:00:00,,,2026-09-15,2026-09-15\n')
RULES = ("alert_code,rule_name,description,agent,metric,threshold,severity,is_active,process_name,current_settings\n"
         "OPS-A02,Purchase order overdue,A purchase order has units pending after its due date,OPERATIONS,days past due,"
         "past due; CRITICAL above ops.po_overdue_critical_days,WARNING,true,Purchasing,ops.po_overdue_critical_days = 14\n"
         "STK-A01,Stock-out with demand,A continued product has no sellable stock where it sold,STOCK,sellable units,"
         "sellable = 0 with demand,CRITICAL,true,Stock position,\n"
         "STK-A02,Low cover,Stock lasts fewer days than the threshold,STOCK,days of cover,days of cover < stock.low_cover_days,"
         "WARNING,true,Stock position,stock.low_cover_days = 7\n")
RUNS_HEAD = "run_id,agent,data_as_of_date,status,started_at,finished_at,notes\n"
RUNS = (RUNS_HEAD + "1,STOCK,2026-09-15,SUCCEEDED,2026-11-10 09:00:00,2026-11-10 09:01:00,STK-A01: 1 raised\n"
        "2,OPERATIONS,2026-09-15,SUCCEEDED,2026-11-10 09:01:00,2026-11-10 09:02:00,OPS-A02: 1 raised\n")


def _db():
    get_engine()
    return SessionLocal()


@pytest.fixture(scope="module")
def ws(client):
    mini = build_mini(client, "agents")
    w = mini["ws"]
    ids = {}
    for name, content in (("agent_rules", RULES), ("agent_runs", RUNS), ("agent_alerts", ALERT_HEAD + A1 + A2 + A3 + A4)):
        ids[name] = upload_csv(client, w, f"{name}.csv", content, name=name)["dataset"]["id"]
    ns = {"measures": [{"metric": "net_sales", "alias": "net_sales"}]}
    for key, name, spec, domain in (("executive-overview", "Executive overview", ns, "executive"),
                                    ("stock-board", "Stock board", {"measures": [{"metric": "stock_on_hand", "alias": "s"}]}, "stock"),
                                    ("ops-board", "Ops board", {"measures": [{"metric": "units_returned", "alias": "u"}]}, "operations")):
        d = client.post(api(w, "/dashboards"), json={"name": name, "key": key, "description": f"{name}.", "domain": domain, "filters": [
            {"id": "period", "type": "date_range", "label": "Date", "field": "@time", "value": AUG_SEP}]}).json()
        client.post(api(w, f"/dashboards/{d['id']}/widgets"), json={"title": f"{name} headline", "chart_type": "kpi", "spec": spec})
    client.put(api(w, "/members"), json={"user_email": V, "role": "viewer"})
    return {"ws": w, "ids": ids}


def replace(client, ws, name, content):
    upload_csv(client, ws["ws"], f"{name}.csv", content, mode="replace", dataset_id=ws["ids"][name])


@pytest.fixture()
def on(monkeypatch):
    s = get_settings()
    for flag in ("assistant_dashboard_chat", "assistant_agent_loop", "assistant_global", "assistant_memory",
                 "assistant_data_issues", "assistant_scheduled"):
        monkeypatch.setattr(s, flag, True)


@pytest.fixture(autouse=True)
def clean(ws, client):
    yield
    with _db() as db:
        for t in (m.AgentDecision, m.Briefing, m.Notification, m.Memory, m.DataIssue, m.DashboardInsight):
            db.query(t).filter_by(workspace_id=ws["ws"]).delete()
        db.query(m.AgentSyncState).filter_by(workspace_id=ws["ws"]).delete()
        db.query(m.Job).delete()
        db.commit()


def cat_of(db, w):
    return load_catalog(db, db.get(m.Workspace, w))


# ----------------------------------------------------------------------------------------------- switch and access

def test_switched_off_by_default(client, ws, monkeypatch):
    monkeypatch.setattr(get_settings(), "assistant_scheduled", False)
    assert client.get(api(ws["ws"], "/agents/summary")).status_code == 403
    assert client.post(api(ws["ws"], "/agents/alerts/1/decision"), json={"decision": "acknowledged"}).status_code == 403


def test_alerts_are_for_admins_only(client, ws, on):
    h = {"X-User-Email": V}
    assert client.get(api(ws["ws"], "/agents/summary"), headers=h).status_code == 403
    assert client.get(api(ws["ws"], "/agents/alerts"), headers=h).status_code == 403
    assert client.post(api(ws["ws"], "/agents/alerts/1/decision"), json={"decision": "dismissed"}, headers=h).status_code == 403


def test_workspace_without_the_warehouse_views(client, on):
    w = client.post("/api/workspaces", json={"name": "no-agents-views"}).json()["id"]
    s = client.get(api(w, "/agents/summary")).json()
    assert s["available"] is False and s["open"] == 0
    assert client.post(api(w, "/agents/briefing")).status_code == 409


# ----------------------------------------------------------------------------------------------- reading the alerts

def test_summary_and_lists(client, ws, on):
    s = client.get(api(ws["ws"], "/agents/summary")).json()
    assert s["available"] and s["open"] == 3 and s["critical"] == 2 and s["undecided"] == 3 and s["as_of"] == "2026-09-15"
    by = {r["alert_code"]: r for r in s["rules"]}
    assert by["STK-A01"]["open"] == 1 and by["OPS-A02"]["critical"] == 1 and by["STK-A02"]["current_settings"] == "stock.low_cover_days = 7"
    assert {r["agent"] for r in s["runs"]} == {"STOCK", "OPERATIONS"}
    stock = client.get(api(ws["ws"], "/agents/alerts?domain=stock")).json()
    assert [a["alert_id"] for a in stock] == [1, 2]                      # critical first
    assert stock[0]["details"]["units_sold_30d"] == 12 and stock[0]["decision"] is None
    assert [a["document_ref"] for a in client.get(api(ws["ws"], "/agents/alerts?status=resolved")).json()] == ["PO/9"]
    assert [a["alert_id"] for a in client.get(api(ws["ws"], "/agents/alerts?q=po/10")).json()] == [3]
    assert len(client.get(api(ws["ws"], "/agents/alerts?status=all")).json()) == 4
    assert client.get(api(ws["ws"], "/agents/alerts?domain=marketing")).status_code == 400


# ----------------------------------------------------------------------------------------------- decisions

def test_a_decision_records_who_and_when_and_becomes_a_decision_memory(client, ws, on):
    r = client.post(api(ws["ws"], "/agents/alerts/3/decision"),
                    json={"decision": "dismissed", "note": "Supplier confirmed dispatch on 12 Nov"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["decision"]["decision"] == "dismissed" and a["decision"]["decided_by"] and a["decision"]["decided_at"]
    with _db() as db:
        d = db.query(m.AgentDecision).filter_by(workspace_id=ws["ws"], alert_id=3).one()
        mem = db.get(m.Memory, d.memory_id)
        assert mem.kind == "decision" and mem.status == "active" and mem.scope == "domain:operations"
        assert mem.origin == "alert_decision" and "Supplier confirmed dispatch" in mem.text and "PO/10" in mem.text
    hist = client.get(api(ws["ws"], "/agents/decisions?alert_id=3")).json()
    assert len(hist) == 1 and hist[0]["alert_code"] == "OPS-A02" and "PO/10" in hist[0]["alert_message"]
    s = client.get(api(ws["ws"], "/agents/summary")).json()
    assert s["undecided"] == 2


def test_decisions_on_resolved_or_unknown_alerts_are_refused(client, ws, on):
    r = client.post(api(ws["ws"], "/agents/alerts/4/decision"), json={"decision": "acknowledged"})
    assert r.status_code == 409 and "no longer open" in r.json()["detail"]
    assert client.post(api(ws["ws"], "/agents/alerts/99/decision"), json={"decision": "acknowledged"}).status_code == 404
    assert client.post(api(ws["ws"], "/agents/alerts/1/decision"), json={"decision": "accepted"}).status_code == 422
    with _db() as db:
        assert db.query(m.AgentDecision).filter_by(workspace_id=ws["ws"]).count() == 0


def test_a_decision_without_memory_switched_on(client, ws, on, monkeypatch):
    monkeypatch.setattr(get_settings(), "assistant_memory", False)
    assert client.post(api(ws["ws"], "/agents/alerts/1/decision"), json={"decision": "acknowledged"}).status_code == 200
    with _db() as db:
        d = db.query(m.AgentDecision).filter_by(workspace_id=ws["ws"], alert_id=1).one()
        assert d.memory_id is None and db.query(m.Memory).filter_by(workspace_id=ws["ws"]).count() == 0


# ----------------------------------------------------------------------------------------------- after a sync

def notices(w, kind):
    with _db() as db:
        return [n.title for n in db.query(m.Notification).filter_by(workspace_id=w, kind=kind).order_by(m.Notification.id)]


def test_new_alerts_and_failed_runs_are_announced_once(client, ws, on):
    w = ws["ws"]
    with _db() as db:
        assert da.after_sync(db, w)["new_alerts"] == 3
    assert notices(w, "agent_alerts") == ["3 new alerts, 2 critical"]
    with _db() as db:
        assert da.after_sync(db, w)["new_alerts"] == 0               # a re-sync repeats nothing
    assert len(notices(w, "agent_alerts")) == 1
    replace(client, ws, "agent_alerts", ALERT_HEAD + A1 + A2 + A3 + A4 + A5)
    replace(client, ws, "agent_runs", RUNS + "3,STOCK,2026-09-15,FAILED,2026-11-11 09:00:00,2026-11-11 09:00:05,DivisionByZero\n")
    try:
        with _db() as db:
            r = da.after_sync(db, w)
        assert r["new_alerts"] == 1 and r["failed_runs"] == 1
        assert notices(w, "agent_alerts")[-1] == "1 new alert, 1 critical"
        assert notices(w, "agent_run_failed") == ["The stock agent's run failed"]
        with _db() as db:
            assert da.after_sync(db, w) == {"new_alerts": 0, "failed_runs": 0}
    finally:
        replace(client, ws, "agent_alerts", ALERT_HEAD + A1 + A2 + A3 + A4)
        replace(client, ws, "agent_runs", RUNS)


def test_the_scheduler_hook_queues_the_briefing_only_when_set(client, ws, on, monkeypatch):
    from app.services.scheduler import _after_sync

    with _db() as db:
        _after_sync(db, {ws["ws"]})
        assert db.query(m.Job).filter_by(kind="briefing").count() == 0      # briefing_every_days = 0: on request only
        db.query(m.AgentSyncState).delete()
        db.commit()
    monkeypatch.setattr(get_settings(), "briefing_every_days", 7)
    with _db() as db:
        _after_sync(db, {ws["ws"]})
        assert db.query(m.Job).filter_by(kind="briefing").count() == 1


# ----------------------------------------------------------------------------------------------- the briefing

def _facts(w):
    with _db() as db:
        return da.facts(db, db.get(m.Workspace, w), cat_of(db, w))


def test_briefing_facts_are_computed_in_code(client, ws, on):
    f = _facts(ws["ws"])
    assert f["as_of"] == "2026-09-15"
    assert f["kpis"] and f["kpis"][0].startswith("Executive overview headline: ") and "1,160" in f["kpis"][0]
    assert any(x.startswith("Stock-out with demand (STK-A01): 1 open alert") for x in f["alerts"])
    assert any("3 open alerts not yet acknowledged" in x for x in f["alerts"])
    assert f["urgent"][0].startswith("Widget (P1) has no sellable stock") and any("PO/10" in u for u in f["urgent"])
    assert f == _facts(ws["ws"])                                      # deterministic


def test_briefing_is_worded_by_sonnet_and_reused_for_the_same_facts(client, ws, on, fake_claude):
    f = _facts(ws["ws"])
    text = (f"**Headlines** Data runs to 2026-09-15. {f['kpis'][0]}.\n**Needs attention** Widget (P1) sold 12 units "
            "at Bagru but has no stock; PO/10 from Fair Pack is 42 days late with 563 units pending.")
    fm = fake_claude(text)
    b = client.post(api(ws["ws"], "/agents/briefing")).json()
    assert b["written_by"] == "claude-sonnet-5-5" and b["text"] == text and b["as_of"] == "2026-09-15"
    assert len(fm.calls) == 1 and fm.calls[0]["model"] == "claude-sonnet-5-5"
    assert "FACTS" in fm.calls[0]["messages"][0]["content"] and "Widget (P1)" in fm.calls[0]["messages"][0]["content"]
    again = client.post(api(ws["ws"], "/agents/briefing")).json()       # same facts: same briefing, no new call
    assert again["id"] == b["id"] and len(fm.calls) == 1
    assert client.get(api(ws["ws"], "/agents/summary")).json()["briefing"]["id"] == b["id"]
    assert notices(ws["ws"], "briefing") == ["New executive briefing (data to 2026-09-15)"]


def test_a_new_decision_changes_the_facts_and_the_briefing(client, ws, on, fake_claude):
    fm = fake_claude("Data runs to 2026-09-15. Three alerts are open.", "Data runs to 2026-09-15. Two alerts are open.")
    first = client.post(api(ws["ws"], "/agents/briefing")).json()
    client.post(api(ws["ws"], "/agents/alerts/1/decision"), json={"decision": "acknowledged"})
    second = client.post(api(ws["ws"], "/agents/briefing")).json()
    assert second["id"] != first["id"] and len(fm.calls) == 2
    assert any("2 open alerts not yet acknowledged" in x for x in second["facts"]["alerts"])


def test_a_briefing_with_an_invented_number_is_rewritten_once(client, ws, on, fake_claude):
    fm = fake_claude("Data runs to 2026-09-15. Net sales grew 37% to 9,999.", "Data runs to 2026-09-15. PO/10 is 42 days late.")
    b = client.post(api(ws["ws"], "/agents/briefing")).json()
    assert b["written_by"] == "claude-sonnet-5-5" and "42 days" in b["text"] and len(fm.calls) == 2
    assert "not in the facts" in fm.calls[1]["messages"][-1]["content"]


def test_a_briefing_that_keeps_inventing_numbers_falls_back_to_the_facts(client, ws, on, fake_claude):
    fake_claude("Sales were 9,999.", "Sales were 8,888.")
    b = client.post(api(ws["ws"], "/agents/briefing")).json()
    assert b["written_by"] == "code" and "9,999" not in b["text"] and "Widget (P1) has no sellable stock" in b["text"]


def test_a_briefing_without_the_model_is_the_facts(client, ws, on, monkeypatch):
    from app.services.nlq import claude

    monkeypatch.setattr(claude, "enabled", lambda: False)
    b = client.post(api(ws["ws"], "/agents/briefing")).json()
    assert b["written_by"] == "code" and b["text"].startswith("Data runs to 2026-09-15.") and "**Most urgent alerts**" in b["text"]


def test_the_briefing_job(client, ws, on, fake_claude):
    fake_claude("Data runs to 2026-09-15. PO/10 is 42 days late.")
    with _db() as db:
        jobs.enqueue(db, "briefing", {"workspace_id": ws["ws"]})
        db.commit()
    assert jobs.run_pending() == 1
    with _db() as db:
        b = db.query(m.Briefing).filter_by(workspace_id=ws["ws"]).one()
        assert b.written_by == "claude-sonnet-5-5" and b.created_by == da.BRIEFING_USER


# ----------------------------------------------------------------------------------------------- domain assistants

def ask(client, w, q, domain=None, user=None, conv=None):
    r = client.post(api(w, "/assistant/ask"), json={"question": q, "domain": domain, "conversation_id": conv},
                    headers={"X-User-Email": user} if user else {})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_stock_assistant_explains_an_alert(client, ws, on, fake_claude):
    fm = fake_claude(turn(tool_call("get_alerts", {"rule": "STK-A01"})),
                     "Alert #1 (STK-A01) fired because Widget (P1) sold 12 units at Bagru Warehouse in the 30 days to "
                     "15 Sep 2026 and has no sellable stock there. Whether to reorder is your call.")
    out = ask(client, ws["ws"], "Why was alert 1 raised?", domain="stock")
    assert "12 units" in out["text"]
    system = json.dumps(fm.calls[0]["system"])
    assert "Stock assistant" in system and "ALERT RULES" in system and "STK-A01 Stock-out with demand" in system
    assert "Stock board" in system and "Ops board" not in system and "PO/10" not in system   # its own domain only
    assert "get_alerts" in {t["name"] for t in fm.calls[0]["tools"]}
    res = json.loads(fm.calls[1]["messages"][-1]["content"][0]["content"])
    assert [a["alert_id"] for a in res["alerts"]] == [1]
    with _db() as db:
        conv = db.query(m.Conversation).filter_by(workspace_id=ws["ws"]).order_by(m.Conversation.id.desc()).first()
        assert conv.scope_type == "domain:stock"
    listed = {c["id"]: c["scope_type"] for c in client.get(api(ws["ws"], "/conversations")).json()}
    assert listed.get(out["conversation_id"]) == "domain:stock"            # continued from the Ask page's list


def test_get_alerts_in_the_operations_scope_sees_only_operations(client, ws, on, fake_claude):
    fm = fake_claude(turn(tool_call("get_alerts", {"status": "all"})), "Two purchase-order alerts: PO/10 and PO/9.")
    ask(client, ws["ws"], "Which alerts are there?", domain="operations")
    res = json.loads(fm.calls[1]["messages"][-1]["content"][0]["content"])
    assert {a["alert_code"] for a in res["alerts"]} == {"OPS-A02"} and res["count"] == 2


def test_viewers_and_the_off_switch_keep_the_old_path(client, ws, on, monkeypatch):
    out = ask(client, ws["ws"], "net sales", domain="stock", user=V)
    assert out.get("engine") in ("semantic", "claude")
    with _db() as db:
        conv = db.query(m.Conversation).filter_by(workspace_id=ws["ws"], user_email=V).order_by(m.Conversation.id.desc()).first()
        assert conv.scope_type == "workspace"


def test_get_alerts_only_on_the_global_and_domain_scopes(client, ws, on, monkeypatch):
    from app.services.nlq.assistant import AnswerScope

    with _db() as db:
        w = set_acting(db.get(m.Workspace, ws["ws"]), "admin@example.com", "admin")
        cat = load_catalog(db, w)
        dash_scope = AnswerScope("dashboard", "stock-board", "", "", None, {})
        ctx = T.ToolContext(db=db, ws=w, cat=cat, user="admin@example.com", scope=dash_scope)
        assert "get_alerts" not in {t["name"] for t in T.tools_for(ctx)}
        assert not T.execute(ctx, "get_alerts", {}).ok
        ctx.scope = AnswerScope("global", None, "", "", None, {})
        assert "get_alerts" in {t["name"] for t in T.tools_for(ctx)}
        out = T.execute(ctx, "get_alerts", {"search": "gadget"})
        assert out.ok and json.loads(out.content)["count"] == 1 and 3.5 in out.numbers
        monkeypatch.setattr(get_settings(), "assistant_scheduled", False)
        assert "get_alerts" not in {t["name"] for t in T.tools_for(ctx)}
        v = set_acting(db.get(m.Workspace, ws["ws"]), V, "viewer")
        monkeypatch.setattr(get_settings(), "assistant_scheduled", True)
        vctx = T.ToolContext(db=db, ws=v, cat=load_catalog(db, v), user=V, scope=AnswerScope("global", None, "", "", None, {}))
        assert not T.execute(vctx, "get_alerts", {}).ok


def test_the_features_flag_is_reported(client, ws, on):
    me = client.get("/api/me").json()
    feats = me.get("features") or {}
    assert feats.get("scheduled_agents") is True


def test_spelled_out_counts_are_read_and_checked():
    # Haiku starts a sentence with "Eighteen products", never "18 products": the number check must see that count
    from app.services.agent.numbers import parse_numbers, ungrounded
    assert parse_numbers("Eighteen products; twenty-one POs, forty two, 7 days, someone often") == [7.0, 18.0, 21.0, 42.0]
    assert ungrounded("Eighteen products at one site", [18.0]) == []
    assert ungrounded("Nineteen products", [18.0]) == ["Nineteen"]
