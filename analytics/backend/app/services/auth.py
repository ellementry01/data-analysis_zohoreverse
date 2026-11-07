"""Sign-in with Google Workspace (OpenID Connect, authorisation code flow with PKCE), sessions and API tokens.

Flow: /api/auth/login stores a state, nonce and PKCE verifier and sends the browser to Google, limited to the company
domain (hd). Google redirects to /api/auth/callback; the code is exchanged server-side (with the client secret and the
verifier) for an ID token, whose RS256 signature is checked against Google's published keys and whose claims are
checked: issuer, audience (our client id), expiry, nonce, email verified, and the hosted domain. A session is then
created: the browser gets a random token in an HttpOnly cookie; the database keeps only its SHA-256.

Secrets (the client secret, tokens) are never logged or returned. Scripts use API tokens (Authorization: Bearer).
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from sqlalchemy.orm import Session

from .. import models as m
from ..config import Settings, get_settings

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
SESSION_COOKIE = "ellementry_session"
LOGIN_TTL = timedelta(minutes=10)
CLOCK_SKEW_S = 120
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

_jwks_cache: dict = {"at": 0.0, "keys": {}}


class AuthError(Exception):
    """Sign-in refused. The message is safe to show to the user."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def is_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


def base_origin(s: Settings | None = None) -> str:
    u = urlparse((s or get_settings()).public_base_url)
    return f"{u.scheme}://{u.netloc}"


def secure_cookies(s: Settings | None = None) -> bool:
    return (s or get_settings()).public_base_url.lower().startswith("https://")


def check_startup(s: Settings) -> None:
    """Refuse to start in an unsafe configuration."""
    if s.auth_mode == "dev" and not is_local(s.public_base_url):
        raise RuntimeError("AUTH_MODE=dev trusts an X-User-Email header and is only allowed when PUBLIC_BASE_URL is "
                           "localhost. Set AUTH_MODE=google for any shared deployment.")
    if s.auth_mode == "google":
        missing = [n for n, v in (("GOOGLE_CLIENT_ID", s.google_client_id), ("GOOGLE_CLIENT_SECRET", s.google_client_secret),
                                   ("GOOGLE_ALLOWED_DOMAIN", s.google_allowed_domain)) if not v]
        if missing:
            raise RuntimeError(f"AUTH_MODE=google needs {', '.join(missing)} (see docs/context/07-operations.md)")
        if not is_local(s.public_base_url) and not s.public_base_url.lower().startswith("https://"):
            raise RuntimeError("PUBLIC_BASE_URL must use https:// outside localhost")


def safe_next(path: str | None) -> str:
    """Only same-site relative paths, so the sign-in can't be used to redirect elsewhere."""
    p = (path or "/").strip()
    if not p.startswith("/") or p.startswith("//") or "\\" in p or "://" in p:
        return "/"
    return p[:500]


def redirect_uri(s: Settings | None = None) -> str:
    return (s or get_settings()).public_base_url.rstrip("/") + "/api/auth/callback"


# ----------------------------------------------------------------------------------------------- the Google flow

def begin_login(db: Session, next_path: str | None) -> str:
    s = get_settings()
    db.query(m.LoginState).filter(m.LoginState.created_at < now() - LOGIN_TTL).delete()
    state, nonce, verifier = new_token(), new_token(), secrets.token_urlsafe(64)
    db.add(m.LoginState(state=state, nonce=nonce, code_verifier=verifier, next_path=safe_next(next_path)))
    db.commit()
    params = {"client_id": s.google_client_id, "redirect_uri": redirect_uri(s), "response_type": "code",
              "scope": "openid email profile", "state": state, "nonce": nonce,
              "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
              "hd": s.google_allowed_domain, "prompt": "select_account"}
    return f"{GOOGLE_AUTH}?{urlencode(params)}"


def exchange_code(code: str, verifier: str) -> dict:
    """Swap the authorisation code for tokens (server to server, with the client secret). Tests replace this."""
    import httpx

    s = get_settings()
    r = httpx.post(GOOGLE_TOKEN, data={"code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
                                       "redirect_uri": redirect_uri(s), "grant_type": "authorization_code",
                                       "code_verifier": verifier}, timeout=15)
    if r.status_code != 200:
        raise AuthError("Google did not accept the sign-in code. Please try again.")
    return r.json()


def fetch_jwks() -> dict:
    """Google's current signing keys by key id, cached for an hour. Tests replace this."""
    import httpx

    if time.time() - _jwks_cache["at"] < 3600 and _jwks_cache["keys"]:
        return _jwks_cache["keys"]
    r = httpx.get(GOOGLE_JWKS, timeout=15)
    r.raise_for_status()
    keys = {k["kid"]: k for k in r.json().get("keys", [])}
    _jwks_cache.update(at=time.time(), keys=keys)
    return keys


def verify_id_token(id_token: str, nonce: str) -> dict:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    s = get_settings()
    try:
        head_b64, body_b64, sig_b64 = id_token.split(".")
        header = json.loads(_b64d(head_b64))
        claims = json.loads(_b64d(body_b64))
    except (ValueError, json.JSONDecodeError) as e:
        raise AuthError("The sign-in token was malformed.") from e
    if header.get("alg") != "RS256":
        raise AuthError("The sign-in token used an unexpected algorithm.")
    jwk = fetch_jwks().get(header.get("kid"))
    if not jwk:
        raise AuthError("The sign-in token was signed with an unknown key.")
    pub = RSAPublicNumbers(int.from_bytes(_b64d(jwk["e"]), "big"), int.from_bytes(_b64d(jwk["n"]), "big")).public_key()
    try:
        pub.verify(_b64d(sig_b64), f"{head_b64}.{body_b64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as e:
        raise AuthError("The sign-in token's signature is not valid.") from e
    t = time.time()
    if claims.get("iss") not in ISSUERS:
        raise AuthError("The sign-in token was not issued by Google.")
    aud = claims.get("aud")
    if aud != s.google_client_id and not (isinstance(aud, list) and s.google_client_id in aud):
        raise AuthError("The sign-in token was not issued for this app.")
    if float(claims.get("exp", 0)) < t - CLOCK_SKEW_S or float(claims.get("iat", t)) > t + CLOCK_SKEW_S:
        raise AuthError("The sign-in token has expired. Please sign in again.")
    if not nonce or claims.get("nonce") != nonce:
        raise AuthError("The sign-in could not be matched to this browser. Please try again.")
    if claims.get("email_verified") is not True:
        raise AuthError("Your Google account's email address is not verified.")
    domain = (s.google_allowed_domain or "").lower()
    email = str(claims.get("email", "")).lower()
    if (claims.get("hd") or "").lower() != domain or not email.endswith("@" + domain):
        raise AuthError(f"Only {domain} Google accounts can sign in.")
    return claims


def complete_login(db: Session, state: str, code: str, ip: str = "", user_agent: str = "") -> tuple[m.User, str, str]:
    """Finish a sign-in: returns (user, session token for the cookie, path to go to)."""
    st = db.get(m.LoginState, state or "")
    if not st:
        raise AuthError("This sign-in link has expired or was already used. Please sign in again.")
    db.delete(st)
    db.commit()
    created = st.created_at if st.created_at.tzinfo else st.created_at.replace(tzinfo=timezone.utc)
    if created < now() - LOGIN_TTL:
        raise AuthError("This sign-in took too long. Please sign in again.")
    tokens = exchange_code(code, st.code_verifier)
    claims = verify_id_token(tokens.get("id_token", ""), st.nonce)
    email = claims["email"].lower()
    user = db.get(m.User, email)
    if user is None:
        user = m.User(email=email, name=str(claims.get("name") or "")[:200])
        db.add(user)
    elif not user.active:
        raise AuthError("Your access to Ellementry Analytics has been switched off. Ask an administrator.")
    if claims.get("name"):
        user.name = str(claims["name"])[:200]
    user.last_login_at = now()
    bootstrap(db, user)
    db.commit()
    return user, create_session(db, email, ip, user_agent), st.next_path or "/"


def bootstrap(db: Session, user: m.User) -> None:
    """Emails in BOOTSTRAP_ADMINS become platform admins and admins of every workspace (the first owner's way in)."""
    admins = {e.strip().lower() for e in get_settings().bootstrap_admins.split(",") if e.strip()}
    if user.email not in admins:
        return
    user.is_platform_admin = True
    for ws in db.query(m.Workspace).all():
        mem = next((x for x in ws.members if x.user_email == user.email), None)
        if mem is None:
            ws.members.append(m.WorkspaceMember(user_email=user.email, role="admin"))
        elif mem.role != "admin":
            mem.role = "admin"


# ----------------------------------------------------------------------------------------------- sessions and tokens

def create_session(db: Session, email: str, ip: str = "", user_agent: str = "") -> str:
    s = get_settings()
    token = new_token()
    db.add(m.AuthSession(token_hash=hash_token(token), user_email=email, expires_at=now() + timedelta(hours=s.session_hours),
                         ip=ip[:64], user_agent=user_agent[:300]))
    db.commit()
    return token


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def user_from_session(db: Session, token: str | None) -> str | None:
    if not token:
        return None
    sess = db.get(m.AuthSession, hash_token(token))
    if not sess:
        return None
    t = now()
    idle = timedelta(hours=get_settings().session_idle_hours)
    if _aware(sess.expires_at) < t or _aware(sess.last_seen_at) < t - idle:
        db.delete(sess)
        db.commit()
        return None
    user = db.get(m.User, sess.user_email)
    if not user or not user.active:
        return None
    if _aware(sess.last_seen_at) < t - timedelta(seconds=60):
        sess.last_seen_at = t
        db.commit()
    return user.email


def revoke_session(db: Session, token: str | None) -> None:
    if token:
        db.query(m.AuthSession).filter_by(token_hash=hash_token(token)).delete()
        db.commit()


def create_api_token(db: Session, email: str, name: str, days: int | None = 90) -> tuple[m.ApiToken, str]:
    token = "ella_" + new_token()
    row = m.ApiToken(token_hash=hash_token(token), user_email=email, name=name[:200],
                     expires_at=now() + timedelta(days=days) if days else None)
    db.add(row)
    db.commit()
    return row, token


def user_from_api_token(db: Session, token: str | None) -> str | None:
    if not token:
        return None
    row = db.query(m.ApiToken).filter_by(token_hash=hash_token(token)).one_or_none()
    if not row or row.revoked or (row.expires_at and _aware(row.expires_at) < now()):
        return None
    user = db.get(m.User, row.user_email)
    if not user or not user.active:
        return None
    if not row.last_used_at or _aware(row.last_used_at) < now() - timedelta(minutes=5):
        row.last_used_at = now()
        db.commit()
    return user.email


def deactivate(db: Session, user: m.User) -> None:
    """Switch a user off: every session and token stops working at once."""
    user.active = False
    db.query(m.AuthSession).filter_by(user_email=user.email).delete()
    db.query(m.ApiToken).filter_by(user_email=user.email).update({"revoked": True})
    db.commit()
