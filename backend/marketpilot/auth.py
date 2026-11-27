"""Optional password protection for remote access (e.g. through a Cloudflare Tunnel).

* Local mode (default): the API listens on 127.0.0.1 only and needs no login.
* Public mode (PUBLIC_MODE=true): every request except /api/health and /api/auth/* needs a
  valid session cookie obtained by logging in with APP_PASSWORD. The backend refuses to start
  in public mode without a password of at least 12 characters.
* Fail-safe: when NOT in public mode, any request that arrived through Cloudflare (Cf-Ray /
  Cf-Connecting-Ip headers) is refused, so an accidentally exposed local instance stays closed.

Sessions are HMAC-signed cookies (HttpOnly, SameSite=Strict, Secure over HTTPS). Changing the
password invalidates every existing session. Failed logins are rate-limited per client IP.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from typing import Any

from .config import Settings

COOKIE = "mp_session"
SESSION_SECONDS = 7 * 24 * 3600
MAX_FAILS_PER_IP = 5
MAX_FAILS_GLOBAL = 30
FAIL_WINDOW = 15 * 60
OPEN_PATHS = ("/api/health", "/api/auth/")
CF_HEADERS = ("cf-ray", "cf-connecting-ip")


class AuthConfigError(RuntimeError):
    pass


def validate_settings(st: Settings) -> None:
    if st.public_mode:
        pw = st.app_password.get_secret_value() if st.app_password else ""
        if len(pw) < 12:
            raise AuthConfigError("PUBLIC_MODE=true requires APP_PASSWORD with at least 12 characters in backend/.env")


class SessionManager:
    def __init__(self, settings: Settings, server_secret: str) -> None:
        self.settings = settings
        pw = settings.app_password.get_secret_value() if settings.app_password else ""
        # The key depends on the password, so changing APP_PASSWORD logs everyone out.
        self._key = hashlib.sha256(f"{server_secret}:{pw}".encode()).digest()
        self._pw = pw
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._global: deque[float] = deque()

    @property
    def required(self) -> bool:
        return self.settings.public_mode

    # ------------------------------------------------------------ cookies
    def issue(self, now: float | None = None) -> str:
        exp = int((now or time.time()) + SESSION_SECONDS)
        nonce = secrets.token_urlsafe(12)
        sig = hmac.new(self._key, f"{exp}.{nonce}".encode(), hashlib.sha256).hexdigest()
        return f"{exp}.{nonce}.{sig}"

    def valid(self, token: str | None, now: float | None = None) -> bool:
        if not token or token.count(".") != 2:
            return False
        exp, nonce, sig = token.split(".")
        good = hmac.new(self._key, f"{exp}.{nonce}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            return False
        try:
            return int(exp) > (now or time.time())
        except ValueError:
            return False

    # ------------------------------------------------------------- login
    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] > FAIL_WINDOW:
            q.popleft()

    def check_password(self, password: str, client: str, now: float | None = None) -> tuple[bool, str]:
        now = now or time.time()
        q = self._fails[client]
        self._prune(q, now)
        self._prune(self._global, now)
        if len(q) >= MAX_FAILS_PER_IP or len(self._global) >= MAX_FAILS_GLOBAL:
            return False, "too_many_attempts"
        if self._pw and hmac.compare_digest(password.encode(), self._pw.encode()):
            q.clear()
            return True, "ok"
        q.append(now)
        self._global.append(now)
        return False, "invalid"


def client_ip(headers: Any, fallback: str | None) -> str:
    ip = headers.get("cf-connecting-ip") or (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return ip or fallback or "unknown"


def via_cloudflare(headers: Any) -> bool:
    return any(headers.get(h) for h in CF_HEADERS)


def is_https(headers: Any, scheme: str) -> bool:
    return scheme == "https" or headers.get("x-forwarded-proto", "").startswith("https") or via_cloudflare(headers)


def path_is_open(path: str) -> bool:
    return path == "/api/health" or path.startswith("/api/auth/")
