"""Phase 3: Google Workspace sign-in (with a simulated Google), sessions, API tokens, user administration, the audit
log, and access rules applied to people and to the assistant alike."""
import base64
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from app import models as m
from app.config import Settings, get_settings
from app.db import SessionLocal, get_engine
from app.main import app
from app.services import auth

from conftest import api, build_mini
from fakes import tool_call, turn

DOMAIN = "ellementry.test"
CLIENT_ID = "test-client.apps.googleusercontent.com"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class FakeGoogle:
    """Signs ID tokens like Google and serves the matching public key."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nums = self.key.public_key().public_numbers()
        self.jwks = {"k1": {"kid": "k1", "kty": "RSA", "alg": "RS256",
                            "n": _b64(nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big")),
                            "e": _b64(nums.e.to_bytes((nums.e.bit_length() + 7) // 8, "big"))}}
        self.next_claims: dict = {}
        self.sign_with = None
        self.alg = "RS256"

    def token(self, nonce: str) -> str:
        t = int(time.time())
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1", "iat": t, "exp": t + 3600,
                  "nonce": nonce, "email": f"ea@{DOMAIN}", "email_verified": True, "hd": DOMAIN, "name": "E A",
                  **self.next_claims}
        header = {"alg": self.alg, "kid": "k1", "typ": "JWT"}
        signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
        sig = (self.sign_with or self.key).sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input}.{_b64(sig)}"


@pytest.fixture(scope="module")
def spaces(client):
    """Workspaces made by owner@local before the app is switched to Google sign-in."""
    return {name: build_mini(client, name)["ws"] for name in ("identity", "identity-members", "identity-tokens")}


@pytest.fixture()
def google(client, spaces, monkeypatch):
    s = get_settings()
    for k, v in {"auth_mode": "google", "google_client_id": CLIENT_ID, "google_client_secret": "test-secret",
                 "google_allowed_domain": DOMAIN, "public_base_url": "http://localhost:8000", "bootstrap_admins": ""}.items():
        monkeypatch.setattr(s, k, v)
    g = FakeGoogle()
    states = {}

    def exchange(code, verifier):
        assert code == "good-code" and verifier
        return {"id_token": g.token(states["nonce"])}
    monkeypatch.setattr(auth, "exchange_code", exchange)
    monkeypatch.setattr(auth, "fetch_jwks", lambda: g.jwks)
    g.states = states
    return g


def _browser():
    return TestClient(app, base_url="http://localhost:8000")


def sign_in(g, email=None, **claims):
    b = _browser()
    r = b.get("/api/auth/login?next=/w/1/dashboards", follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    g.states["nonce"] = q["nonce"][0]
    g.next_claims = {**({"email": email} if email else {}), **claims}
    r = b.get(f"/api/auth/callback?code=good-code&state={q['state'][0]}", follow_redirects=False)
    return b, r


def _session():
    get_engine()
    return SessionLocal()


def _audit(action, who=None):
    with _session() as db:
        q = db.query(m.AuditEvent).filter_by(action=action)
        if who:
            q = q.filter_by(user_email=who)
        return q.order_by(m.AuditEvent.id.desc()).first()


# ----------------------------------------------------------------------------------------------- sign-in

def test_login_sends_the_browser_to_google_with_pkce_and_the_domain(client, google):
    r = _browser().get("/api/auth/login?next=/w/34", follow_redirects=False)
    u = urlparse(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert u.netloc == "accounts.google.com"
    assert q["client_id"] == CLIENT_ID and q["response_type"] == "code" and q["scope"] == "openid email profile"
    assert q["redirect_uri"] == "http://localhost:8000/api/auth/callback" and q["hd"] == DOMAIN
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) >= 43 and q["state"] and q["nonce"]
    assert "test-secret" not in r.headers["location"]


def test_successful_sign_in_creates_a_secure_session(client, google):
    b, r = sign_in(google)
    assert r.status_code == 302 and r.headers["location"] == "/w/1/dashboards"
    cookie = r.headers["set-cookie"]
    assert auth.SESSION_COOKIE in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    me = b.get("/api/me").json()
    assert me["email"] == f"ea@{DOMAIN}" and me["auth_mode"] == "google" and me["name"] == "E A"
    with _session() as db:
        token = b.cookies.get(auth.SESSION_COOKIE)
        assert db.get(m.AuthSession, auth.hash_token(token)) is not None       # only the hash is stored
        assert db.query(m.AuthSession).filter_by(token_hash=token).first() is None
    assert _audit("sign_in", f"ea@{DOMAIN}") is not None


@pytest.mark.parametrize("claims, reason", [
    ({"aud": "someone-else"}, "not issued for this app"),
    ({"iss": "https://evil.example"}, "not issued by Google"),
    ({"exp": int(time.time()) - 3600}, "expired"),
    ({"nonce": "wrong"}, "matched to this browser"),
    ({"email_verified": False}, "not verified"),
    ({"hd": "gmail.com"}, f"Only {DOMAIN}"),
    ({"email": "someone@gmail.com"}, f"Only {DOMAIN}"),
])
def test_sign_in_refusals(client, google, claims, reason):
    b, r = sign_in(google, **claims)
    assert r.status_code == 403 and reason in r.text
    assert b.get("/api/me").status_code == 401
    assert reason in _audit("sign_in_failed").detail["reason"]


def test_forged_tokens_are_refused(client, google):
    google.sign_with = google.other                       # signed with a key Google never published
    _, r = sign_in(google)
    assert r.status_code == 403 and "signature" in r.text
    google.sign_with, google.alg = None, "none"
    _, r = sign_in(google)
    assert r.status_code == 403 and "algorithm" in r.text


def test_state_is_single_use_and_must_exist(client, google):
    b = _browser()
    assert b.get("/api/auth/callback?code=good-code&state=made-up", follow_redirects=False).status_code == 403
    r = b.get("/api/auth/login", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    google.states["nonce"] = q["nonce"][0]
    assert b.get(f"/api/auth/callback?code=good-code&state={q['state'][0]}", follow_redirects=False).status_code == 302
    assert b.get(f"/api/auth/callback?code=good-code&state={q['state'][0]}", follow_redirects=False).status_code == 403


def test_redirects_stay_on_this_site():
    for bad in ("//evil.example", "https://evil.example/x", "/\\evil", "evil", ""):
        assert auth.safe_next(bad) == "/"
    assert auth.safe_next("/w/34/dashboards/195?x=1") == "/w/34/dashboards/195?x=1"


def test_the_header_is_ignored_in_google_mode(client, google):
    b = _browser()
    assert b.get("/api/me", headers={"X-User-Email": "owner@local"}).status_code == 401
    b, _ = sign_in(google)
    assert b.get("/api/me", headers={"X-User-Email": "owner@local"}).json()["email"] == f"ea@{DOMAIN}"


def test_sign_out_and_session_expiry(client, google, monkeypatch):
    b, _ = sign_in(google)
    assert b.post("/api/auth/logout").status_code == 204
    assert b.get("/api/me").status_code == 401
    b, _ = sign_in(google)
    token = b.cookies.get(auth.SESSION_COOKIE)
    with _session() as db:
        db.get(m.AuthSession, auth.hash_token(token)).last_seen_at = datetime.now(timezone.utc) - timedelta(hours=5)
        db.commit()
    assert b.get("/api/me").status_code == 401                                 # idle too long
    b, _ = sign_in(google)
    token = b.cookies.get(auth.SESSION_COOKIE)
    with _session() as db:
        db.get(m.AuthSession, auth.hash_token(token)).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert b.get("/api/me").status_code == 401                                 # past its absolute lifetime


def test_cross_site_writes_are_refused(client, google):
    b, _ = sign_in(google)
    assert b.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert b.post("/api/auth/logout", headers={"Origin": "http://localhost:8000"}).status_code == 204


def test_bootstrap_admin_and_deactivation(client, spaces, google, monkeypatch):
    monkeypatch.setattr(get_settings(), "bootstrap_admins", f"boss@{DOMAIN}")
    ws = spaces["identity"]                            # created in dev mode by owner@local
    boss, _ = sign_in(google, email=f"boss@{DOMAIN}")
    me = boss.get("/api/me").json()
    assert me["is_platform_admin"] is True
    assert boss.get(api(ws)).json()["role"] == "admin"             # made admin of existing workspaces
    staff, _ = sign_in(google, email=f"staff@{DOMAIN}")
    assert staff.get("/api/me").json()["is_platform_admin"] is False
    assert staff.get("/api/admin/users").status_code == 403
    users = {u["email"]: u for u in boss.get("/api/admin/users").json()}
    assert users[f"staff@{DOMAIN}"]["active"] is True
    assert boss.patch(f"/api/admin/users/boss@{DOMAIN}", json={"active": False}).status_code == 400   # not yourself
    assert boss.patch(f"/api/admin/users/staff@{DOMAIN}", json={"active": False}).json()["active"] is False
    assert staff.get("/api/me").status_code == 401                                 # switched off at once
    _, r = sign_in(google, email=f"staff@{DOMAIN}")
    assert r.status_code == 403 and "switched off" in r.text
    assert _audit("user_updated", f"boss@{DOMAIN}").target == f"staff@{DOMAIN}"
    log = boss.get("/api/admin/audit?action=sign_in").json()
    assert {e["user_email"] for e in log} >= {f"boss@{DOMAIN}", f"staff@{DOMAIN}"}


def test_members_must_be_company_accounts(client, spaces, google, monkeypatch):
    monkeypatch.setattr(get_settings(), "bootstrap_admins", f"boss@{DOMAIN}")
    ws = spaces["identity-members"]
    boss, _ = sign_in(google, email=f"boss@{DOMAIN}")
    assert boss.put(api(ws, "/members"), json={"user_email": "friend@gmail.com", "role": "viewer"}).status_code == 400
    assert boss.put(api(ws, "/members"), json={"user_email": f"coo@{DOMAIN}", "role": "viewer"}).status_code == 200
    assert _audit("member_set", f"boss@{DOMAIN}").target == f"coo@{DOMAIN}"


def test_api_tokens_for_scripts(client, spaces, google, monkeypatch):
    monkeypatch.setattr(get_settings(), "bootstrap_admins", f"boss@{DOMAIN}")
    ws = spaces["identity-tokens"]
    boss, _ = sign_in(google, email=f"boss@{DOMAIN}")
    made = boss.post("/api/admin/tokens", json={"name": "dashboard builds", "days": 30}).json()
    raw = made["token"]
    assert raw.startswith("ella_") and "token" not in boss.get("/api/admin/tokens").json()[0]   # shown once only
    script = _browser()
    h = {"Authorization": f"Bearer {raw}"}
    assert script.get("/api/me", headers=h).json()["email"] == f"boss@{DOMAIN}"
    assert script.get(api(ws, "/dashboards"), headers=h).status_code == 200
    assert script.get("/api/me", headers={"Authorization": "Bearer ella_wrong"}).status_code == 401
    boss.delete(f"/api/admin/tokens/{made['id']}")
    assert script.get("/api/me", headers=h).status_code == 401
    with _session() as db:
        assert db.query(m.ApiToken).filter_by(token_hash=raw).first() is None    # only the hash is stored


def test_unsafe_configurations_refuse_to_start():
    with pytest.raises(RuntimeError, match="only allowed when PUBLIC_BASE_URL is localhost"):
        auth.check_startup(Settings(auth_mode="dev", public_base_url="https://analytics.ellementry.com"))
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        auth.check_startup(Settings(auth_mode="google", public_base_url="http://localhost:8000"))
    with pytest.raises(RuntimeError, match="https"):
        auth.check_startup(Settings(auth_mode="google", public_base_url="http://analytics.ellementry.com",
                                    google_client_id="x", google_client_secret="y", google_allowed_domain=DOMAIN))
    auth.check_startup(Settings(auth_mode="dev", public_base_url="http://localhost:8000"))
    with pytest.raises(ValueError):
        Settings(auth_mode="none")


# ----------------------------------------------------------------------------------------------- access rules (dev mode)

@pytest.fixture(scope="module")
def shop(client):
    mini = build_mini(client, "access")
    ws = mini["ws"]
    fin = client.post(api(ws, "/dashboards"), json={"name": "Finance board", "key": "finance-board", "domain": "finance"}).json()
    client.post(api(ws, f"/dashboards/{fin['id']}/widgets"),
                json={"title": "Net sales", "chart_type": "kpi", "spec": {"measures": [{"metric": "net_sales"}]}})
    open_ = client.post(api(ws, "/dashboards"), json={"name": "Open board", "key": "open-board", "domain": "sales"}).json()
    client.post(api(ws, f"/dashboards/{open_['id']}/widgets"),
                json={"title": "Units", "chart_type": "kpi", "spec": {"measures": [{"metric": "units_sold"}]}})
    for email, role in (("viewer@x.test", "viewer"), ("cfo@x.test", "viewer"), ("editor@x.test", "editor")):
        client.put(api(ws, "/members"), json={"user_email": email, "role": role})
    assert client.post(api(ws, "/access-rules"), json={"target_type": "domain", "target": "finance", "principal_type": "user",
                                                       "principal": "cfo@x.test"}).status_code == 201
    assert client.post(api(ws, "/access-rules"), json={"target_type": "dataset", "target": "spend", "principal_type": "role",
                                                       "principal": "editor"}).status_code == 201
    return {"ws": ws, "fin": fin["id"], "open": open_["id"], "spend": mini["ds"]["spend"]}


def as_(who):
    return {"X-User-Email": who}


def test_restricted_dashboards_disappear_for_others(client, shop):
    ws = shop["ws"]
    viewer_keys = {d["key"] for d in client.get(api(ws, "/dashboards"), headers=as_("viewer@x.test")).json()}
    assert "finance-board" not in viewer_keys and "open-board" in viewer_keys
    for path in (f"/dashboards/{shop['fin']}", "/dashboards/key/finance-board", f"/dashboards/{shop['fin']}/values?field=channels.channel"):
        assert client.get(api(ws, path), headers=as_("viewer@x.test")).status_code == 404, path
    w = client.get(api(ws, f"/dashboards/{shop['fin']}")).json()["widgets"][0]["id"]
    assert client.post(api(ws, f"/dashboards/{shop['fin']}/widgets/{w}/data"), json={}, headers=as_("viewer@x.test")).status_code == 404
    # the person named in the rule, and workspace admins, see it
    assert client.get(api(ws, "/dashboards/key/finance-board"), headers=as_("cfo@x.test")).status_code == 200
    assert client.get(api(ws, "/dashboards/key/finance-board")).status_code == 200      # owner@local is admin


def test_restricted_datasets_disappear_everywhere(client, shop):
    ws, sp = shop["ws"], shop["spend"]
    v = as_("viewer@x.test")
    assert "spend" not in {d["slug"] for d in client.get(api(ws, "/datasets"), headers=v).json()}
    assert client.get(api(ws, f"/datasets/{sp}/rows"), headers=v).status_code == 404
    assert "spend" not in {d["slug"] for d in client.get(api(ws, "/model"), headers=v).json()["datasets"]}
    assert client.post(api(ws, "/query"), json={"measures": [{"field": "spend.spend", "agg": "sum"}]}, headers=v).status_code == 400
    assert client.post(api(ws, "/sql"), json={"sql": "SELECT SUM(spend) FROM spend"}, headers=v).status_code == 400
    # editors (the rule's minimum role) and admins still see it
    e = as_("editor@x.test")
    assert client.post(api(ws, "/sql"), json={"sql": "SELECT SUM(spend) FROM spend"}, headers=e).status_code == 200
    assert client.get(api(ws, f"/datasets/{sp}/rows"), headers=e).status_code == 200


def test_the_assistant_sees_only_what_the_asker_sees(client, shop, fake_claude, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "assistant_dashboard_chat", True)
    monkeypatch.setattr(s, "assistant_agent_loop", True)
    ws = shop["ws"]
    client.put(api(ws, "/members"), json={"user_email": "viewer-admin@x.test", "role": "admin"})
    client.post(api(ws, "/access-rules"), json={"target_type": "domain", "target": "finance", "principal_type": "user",
                                                "principal": "cfo@x.test"})
    # an admin-role asker who is not the CFO: admins see everything, so restrict with a viewer-level asker instead
    client.put(api(ws, "/members"), json={"user_email": "chat-viewer@x.test", "role": "viewer"})
    # (the chat is admins-only until sign-in is live, so check the tools directly as a viewer would be)
    from app.services.agent import tools as T
    from app.services.catalog import load_catalog
    from app.services.permissions import set_acting

    with _session() as db:
        wso = set_acting(db.get(m.Workspace, ws), "chat-viewer@x.test", "viewer")
        dash = db.query(m.Dashboard).filter_by(workspace_id=ws, key="open-board").one()
        ctx = T.ToolContext(db=db, ws=wso, cat=load_catalog(db, wso), user="chat-viewer@x.test", dashboard=dash)
        hidden = T.execute(ctx, "get_dashboard_context", {"dashboard_key": "finance-board"})
        missing = T.execute(ctx, "get_dashboard_context", {"dashboard_key": "no-such-board"})
        # a hidden dashboard looks exactly like one that doesn't exist, and isn't in the list of keys offered
        assert not hidden.ok and hidden.content.replace("finance-board", "K") == missing.content.replace("no-such-board", "K")
        assert "Keys: open-board" in hidden.content
        assert not T.execute(ctx, "get_widget_data", {"dashboard_key": "finance-board", "widget": "Net sales"}).ok
        assert not T.execute(ctx, "run_query", {"spec": {"measures": [{"field": "spend.spend", "agg": "sum"}]}}).ok
        assert T.execute(ctx, "run_query", {"spec": {"measures": [{"metric": "units_sold"}]}}).ok
    # through the streaming chat, as an admin who can see it, the thread's own workspace copy keeps the asker
    fake_claude(turn(tool_call("get_dashboard_context", {"dashboard_key": "finance-board"})), "Seen.")
    r = client.post(api(ws, "/dashboards/key/open-board/assistant/ask/stream"), json={"question": "finance?"},
                    headers=as_("viewer-admin@x.test"))
    assert '"ok": true' in r.text


def test_rules_are_validated_and_audited(client, shop):
    ws = shop["ws"]
    bad = [{"target_type": "dashboard", "target": "nope", "principal_type": "role", "principal": "viewer"},
           {"target_type": "domain", "target": "astrology", "principal_type": "role", "principal": "viewer"},
           {"target_type": "dataset", "target": "nope", "principal_type": "role", "principal": "viewer"},
           {"target_type": "dashboard", "target": "open-board", "principal_type": "role", "principal": "boss"},
           {"target_type": "dashboard", "target": "open-board", "principal_type": "user", "principal": "not-an-email"}]
    for b in bad:
        assert client.post(api(ws, "/access-rules"), json=b).status_code == 400, b
    rule = {"target_type": "dashboard", "target": "open-board", "principal_type": "role", "principal": "editor"}
    rid = client.post(api(ws, "/access-rules"), json=rule).json()["id"]
    assert client.post(api(ws, "/access-rules"), json=rule).status_code == 409
    assert client.get(api(ws, "/dashboards/key/open-board"), headers=as_("viewer@x.test")).status_code == 404
    assert client.get(api(ws, "/dashboards/key/open-board"), headers=as_("editor@x.test")).status_code == 200
    assert client.post(api(ws, "/access-rules"), json=rule, headers=as_("editor@x.test")).status_code == 403   # admins only
    assert client.delete(api(ws, f"/access-rules/{rid}")).status_code == 204
    assert client.get(api(ws, "/dashboards/key/open-board"), headers=as_("viewer@x.test")).status_code == 200
    assert _audit("access_rule_removed").target == "dashboard:open-board"


def test_assistant_questions_are_audited(client, shop, fake_claude, monkeypatch):
    monkeypatch.setattr(get_settings(), "assistant_dashboard_chat", True)
    fake_claude({"kind": "spec", "title": "t", "chart": "auto", "assumptions": [], "clarification": "",
                 "spec": json.dumps({"measures": [{"metric": "units_sold"}]}), "sql": ""}, "ok")
    client.post(api(shop["ws"], "/dashboards/key/open-board/assistant/ask"), json={"question": "units?"})
    e = _audit("assistant_ask", "owner@local")
    assert e.target == "dashboard:open-board" and e.workspace_id == shop["ws"]


def test_lineage_hides_what_the_user_cannot_see(client, shop):
    nodes = client.get(api(shop["ws"], "/lineage"), headers=as_("viewer@x.test")).json()["nodes"]
    labels = {n["label"] for n in nodes}
    assert "Spend" not in labels and "Finance board" not in labels and "Open board" in labels
    admin_labels = {n["label"] for n in client.get(api(shop["ws"], "/lineage")).json()["nodes"]}
    assert {"Spend", "Finance board"} <= admin_labels
