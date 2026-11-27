"""Remote-access protection: public mode login, sessions, rate limiting, Cloudflare fail-safe."""
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from marketpilot.auth import AuthConfigError, SessionManager, validate_settings
from marketpilot.config import get_settings

PW = "correct horse battery"


def _settings(**kw):
    return get_settings().model_copy(update=kw)


def test_public_mode_requires_strong_password():
    with pytest.raises(AuthConfigError):
        validate_settings(_settings(public_mode=True, app_password=None))
    with pytest.raises(AuthConfigError):
        validate_settings(_settings(public_mode=True, app_password=SecretStr("short")))
    validate_settings(_settings(public_mode=True, app_password=SecretStr(PW)))


def test_sessions_expire_tamper_and_rotate_with_password():
    sm = SessionManager(_settings(public_mode=True, app_password=SecretStr(PW)), "secret")
    tok = sm.issue(now=1000)
    assert sm.valid(tok, now=2000)
    assert not sm.valid(tok, now=1000 + 8 * 24 * 3600)
    exp, nonce, sig = tok.split(".")
    assert not sm.valid(f"{int(exp) + 999}.{nonce}.{sig}", now=2000)
    assert not sm.valid("garbage", now=2000) and not sm.valid(None)
    other = SessionManager(_settings(public_mode=True, app_password=SecretStr(PW + "!")), "secret")
    assert not other.valid(tok, now=2000)


def test_login_rate_limit():
    sm = SessionManager(_settings(public_mode=True, app_password=SecretStr(PW)), "s")
    for _ in range(5):
        assert sm.check_password("nope", "1.2.3.4", now=100) == (False, "invalid")
    assert sm.check_password(PW, "1.2.3.4", now=101) == (False, "too_many_attempts")
    assert sm.check_password(PW, "5.6.7.8", now=101) == (True, "ok")
    assert sm.check_password(PW, "1.2.3.4", now=100 + 16 * 60) == (True, "ok")


def test_public_mode_end_to_end(db):
    from marketpilot.app import create_app

    app = create_app(_settings(public_mode=True, app_password=SecretStr(PW)))
    with TestClient(app, base_url="https://testserver") as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/status").status_code == 401
        assert c.get("/api/experiments").status_code == 401
        assert c.post("/api/emergency-stop", json={}).status_code == 401
        assert c.get("/openapi.json").status_code == 401
        assert c.get("/api/auth/status").json() == {"required": True, "authenticated": False}
        with pytest.raises(Exception):
            with c.websocket_connect("/api/ws"):
                pass
        assert c.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        r = c.post("/api/auth/login", json={"password": PW})
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "secure" in cookie
        assert c.get("/api/experiments").status_code == 200
        token = c.cookies.get("mp_session")
        # The test client opens ws:// (not wss://), so it would not send a Secure cookie; browsers on wss:// do.
        with c.websocket_connect("/api/ws", headers={"cookie": f"mp_session={token}"}) as ws:
            assert ws.receive_json()["type"] == "hello"
        c.post("/api/auth/logout")
        assert c.get("/api/experiments").status_code == 401


def test_local_mode_refuses_requests_arriving_via_cloudflare(db):
    from marketpilot.app import create_app

    with TestClient(create_app(_settings(public_mode=False))) as c:
        assert c.get("/api/experiments").status_code == 200
        r = c.get("/api/experiments", headers={"Cf-Ray": "abc123", "Cf-Connecting-Ip": "203.0.113.9"})
        assert r.status_code == 403 and r.json()["code"] == "remote_disabled"
        assert c.get("/api/auth/status").json()["required"] is False
