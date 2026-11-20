"""Alert creation, de-duplication, rate limiting and delivery.

Channels: in-app (always, stored + pushed over WebSocket), desktop (the dashboard
shows a browser notification when permitted), optional email (SMTP) and optional
webhook (e.g. an ntfy.sh topic URL for phone push). External channels are off
unless configured in .env.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import Alert, AppSetting

log = logging.getLogger(__name__)

SEVERITY_ORDER = {"info": 0, "notice": 1, "warning": 2, "critical": 3}
DEFAULT_PREFS: dict[str, Any] = {
    "enabled_kinds": ["signal", "trade", "risk", "summary", "event", "system", "market"],
    "min_severity_in_app": "info",
    "min_severity_desktop": "notice",
    "min_severity_email": "warning",
    "min_severity_webhook": "warning",
    "max_per_hour": 40,
    "default_cooldown_minutes": 240,
}


def get_prefs(s: Session) -> dict[str, Any]:
    row = s.get(AppSetting, "alert_prefs")
    return {**DEFAULT_PREFS, **(row.value if row else {})}


def set_prefs(s: Session, prefs: dict[str, Any]) -> dict[str, Any]:
    merged = {**get_prefs(s), **{k: v for k, v in prefs.items() if k in DEFAULT_PREFS}}
    s.merge(AppSetting(key="alert_prefs", value=merged))
    return merged


def alert_to_dict(a: Alert) -> dict[str, Any]:
    return {"id": a.id, "ts": a.ts.isoformat(), "kind": a.kind, "severity": a.severity, "symbol": a.symbol,
            "title": a.title, "body": a.body, "signal_id": a.signal_id, "read": a.read, "channels": a.channels}


class AlertService:
    def __init__(self, hub: Any | None = None) -> None:
        self.hub = hub
        self._pending: set[asyncio.Task[Any]] = set()

    def create(self, s: Session, *, kind: str, title: str, body: str, dedupe_key: str, severity: str = "info",
               symbol: str | None = None, signal_id: int | None = None, cooldown_minutes: int | None = None,
               now: datetime | None = None) -> Alert | None:
        prefs = get_prefs(s)
        now = now or datetime.now(timezone.utc)
        if kind not in prefs["enabled_kinds"] and severity != "critical":
            return None
        if SEVERITY_ORDER[severity] < SEVERITY_ORDER[prefs["min_severity_in_app"]]:
            return None
        cooldown = prefs["default_cooldown_minutes"] if cooldown_minutes is None else cooldown_minutes
        recent = s.execute(select(Alert.id).where(Alert.dedupe_key == dedupe_key,
                                                  Alert.ts >= now - timedelta(minutes=cooldown))).first()
        if recent:
            return None  # duplicate within cooldown window
        hour_count = s.execute(select(func.count(Alert.id)).where(Alert.ts >= now - timedelta(hours=1))).scalar_one()
        if hour_count >= prefs["max_per_hour"] and severity != "critical":
            log.info("alert rate limit reached; suppressed %s", dedupe_key)
            return None
        channels = ["in_app"]
        if SEVERITY_ORDER[severity] >= SEVERITY_ORDER[prefs["min_severity_desktop"]]:
            channels.append("desktop")
        a = Alert(ts=now, kind=kind, severity=severity, symbol=symbol, title=title[:200], body=body,
                  dedupe_key=dedupe_key, signal_id=signal_id, channels=channels)
        s.add(a)
        s.flush()
        payload = alert_to_dict(a)
        if self.hub is not None:
            self.hub.publish({"type": "alert", "data": payload})
        self._deliver_external(payload, prefs)
        return a

    def _deliver_external(self, payload: dict[str, Any], prefs: dict[str, Any]) -> None:
        st = get_settings()
        sev = SEVERITY_ORDER[payload["severity"]]
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # called outside the event loop (tests / scripts): no external delivery
        if st.smtp_host and st.alert_email_to and sev >= SEVERITY_ORDER[prefs["min_severity_email"]]:
            t = loop.create_task(asyncio.to_thread(self._send_email, payload))
            self._pending.add(t)
            t.add_done_callback(self._pending.discard)
        if st.alert_webhook_url and sev >= SEVERITY_ORDER[prefs["min_severity_webhook"]]:
            t = loop.create_task(self._send_webhook(payload))
            self._pending.add(t)
            t.add_done_callback(self._pending.discard)

    @staticmethod
    def _send_email(payload: dict[str, Any]) -> None:
        st = get_settings()
        msg = EmailMessage()
        msg["Subject"] = f"[MarketPilot] {payload['title']}"
        msg["From"] = st.smtp_user or "marketpilot@localhost"
        msg["To"] = st.alert_email_to
        msg.set_content(f"{payload['body']}\n\nPaper trading / analysis only. Not financial advice.")
        try:
            with smtplib.SMTP(st.smtp_host, st.smtp_port, timeout=20) as smtp:  # type: ignore[arg-type]
                smtp.starttls()
                if st.smtp_user and st.smtp_password:
                    smtp.login(st.smtp_user, st.smtp_password.get_secret_value())
                smtp.send_message(msg)
        except Exception as e:  # pragma: no cover - network
            log.warning("email delivery failed: %s", e)

    @staticmethod
    async def _send_webhook(payload: dict[str, Any]) -> None:
        st = get_settings()
        url = st.alert_webhook_url.get_secret_value()  # type: ignore[union-attr]
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                if "ntfy" in url:
                    await c.post(url, content=payload["body"][:3500].encode(), headers={"Title": payload["title"][:200]})
                else:
                    await c.post(url, json=payload)
        except Exception as e:  # pragma: no cover - network
            log.warning("webhook delivery failed: %s", e)
