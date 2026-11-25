"""Operator alerts: account health and other conditions, delivered to a webhook.

Conditions are edge-triggered. A condition that appears is announced once, announced again after
the cooldown while it persists, and announced as recovered when it clears. With no webhook
configured the conditions are still tracked and shown in the console.

The webhook receives a JSON POST. ``text`` and ``content`` carry the same one-line message, so
Slack, Discord, Telegram (``sendMessage``) and most chat webhooks accept it unchanged.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

CHECK_INTERVAL_SECONDS = 60
DEFAULT_LOW_CREDITS = 500
DEFAULT_COOLDOWN_MINUTES = 360
MAX_EVENT_HISTORY = 100
DELIVERY_TIMEOUT_SECONDS = 10
MAX_WEBHOOK_URL_LENGTH = 2000

SEVERITIES = ("info", "warning", "critical")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_webhook_url(value: Optional[str]) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if len(url) > MAX_WEBHOOK_URL_LENGTH or parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("webhook_url must be an http(s) URL")
    return url


class AlertService:
    def __init__(
        self,
        db,
        tokens: Callable[[], Awaitable[List[Any]]],
        *,
        clock: Callable[[], float] = time.time,
        sender: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.db = db
        self._tokens = tokens
        self._clock = clock
        self._send = sender or self._post_json
        self._ready = False
        self._task: Optional[asyncio.Task] = None
        self.webhook_url = ""
        self.enabled = False
        self.low_credits = DEFAULT_LOW_CREDITS
        self.cooldown_minutes = DEFAULT_COOLDOWN_MINUTES
        self.conditions: Dict[str, Dict[str, Any]] = {}
        self.history: List[Dict[str, Any]] = []

    # ----- settings -----

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with self.db._connect(write=True) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    webhook_url TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 0,
                    low_credits INTEGER NOT NULL DEFAULT 500,
                    cooldown_minutes INTEGER NOT NULL DEFAULT 360
                )
            """)
            await conn.execute("INSERT OR IGNORE INTO alert_settings (id) VALUES (1)")
            await conn.commit()
        self._ready = True

    async def load(self) -> None:
        await self._ensure_table()
        async with self.db._connect() as conn:
            row = await (await conn.execute(
                "SELECT webhook_url, enabled, low_credits, cooldown_minutes FROM alert_settings WHERE id = 1"
            )).fetchone()
        self.webhook_url, self.enabled, self.low_credits, self.cooldown_minutes = (
            row[0], bool(row[1]), int(row[2]), int(row[3])
        )

    async def update_settings(
        self,
        *,
        webhook_url: Optional[str] = None,
        enabled: Optional[bool] = None,
        low_credits: Optional[int] = None,
        cooldown_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        await self.load()
        url, active = self.webhook_url, self.enabled
        low, cooldown = self.low_credits, self.cooldown_minutes
        if webhook_url is not None:
            url = validate_webhook_url(webhook_url)
            if not url:
                active = False  # nowhere to send to any more
        if enabled is not None:
            active = bool(enabled)
        if low_credits is not None:
            if isinstance(low_credits, bool) or not 0 <= int(low_credits) <= 10_000_000:
                raise ValueError("low_credits must be between 0 and 10000000")
            low = int(low_credits)
        if cooldown_minutes is not None:
            if isinstance(cooldown_minutes, bool) or not 1 <= int(cooldown_minutes) <= 10_080:
                raise ValueError("cooldown_minutes must be between 1 and 10080")
            cooldown = int(cooldown_minutes)
        if active and not url:
            raise ValueError("set a webhook_url before enabling alerts")
        self.webhook_url, self.enabled, self.low_credits, self.cooldown_minutes = url, active, low, cooldown
        async with self.db._connect(write=True) as conn:
            await conn.execute(
                "UPDATE alert_settings SET webhook_url = ?, enabled = ?, low_credits = ?, cooldown_minutes = ? WHERE id = 1",
                (self.webhook_url, int(self.enabled), self.low_credits, self.cooldown_minutes),
            )
            await conn.commit()
        return self.describe_settings()

    def describe_settings(self) -> Dict[str, Any]:
        # The URL can embed a bot token or secret, so show only where it points.
        parsed = urlparse(self.webhook_url) if self.webhook_url else None
        return {
            "enabled": self.enabled,
            "webhook_configured": bool(self.webhook_url),
            "webhook_host": parsed.hostname if parsed else "",
            "low_credits": self.low_credits,
            "cooldown_minutes": self.cooldown_minutes,
        }

    # ----- conditions -----

    async def raise_condition(self, key: str, message: str, *, severity: str = "warning", details: Optional[dict] = None) -> None:
        """Announce a problem now, and again after the cooldown while it lasts."""
        now = self._clock()
        current = self.conditions.get(key)
        if current is not None:
            current["message"], current["details"] = message, details or {}
            if now - current["notified_at"] < self.cooldown_minutes * 60:
                return
            current["notified_at"] = now
            await self._notify(key, "reminder", severity, message, details)
            return
        self.conditions[key] = {
            "key": key, "severity": severity, "message": message, "details": details or {},
            "since": _now_iso(), "notified_at": now,
        }
        await self._notify(key, "raised", severity, message, details)

    async def clear_condition(self, key: str, message: str = "") -> None:
        current = self.conditions.pop(key, None)
        if current is not None:
            await self._notify(key, "recovered", "info", message or f"Recovered: {current['message']}", current["details"])

    async def announce(self, key: str, message: str, *, severity: str = "info", details: Optional[dict] = None) -> None:
        """A one-off event (nothing to recover from)."""
        await self._notify(key, "event", severity, message, details)

    async def _notify(self, key: str, kind: str, severity: str, message: str, details: Optional[dict]) -> None:
        event = {
            "time": _now_iso(), "key": key, "kind": kind, "severity": severity,
            "message": message, "delivered": None, "error": "",
        }
        if self.enabled and self.webhook_url:
            body = {
                "event": key, "kind": kind, "severity": severity, "message": message,
                "text": f"[Flow2API {severity}] {message}", "content": f"[Flow2API {severity}] {message}",
                "details": details or {}, "time": event["time"],
            }
            try:
                await self._send(self.webhook_url, body)
                event["delivered"] = True
            except Exception as exc:  # noqa: BLE001 - a broken webhook must not break the service
                event["delivered"] = False
                event["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        self.history.append(event)
        del self.history[:-MAX_EVENT_HISTORY]

    async def send_test(self) -> Dict[str, Any]:
        await self.load()
        if not self.webhook_url:
            raise ValueError("no webhook_url configured")
        await self._send(self.webhook_url, {
            "event": "test", "kind": "event", "severity": "info", "message": "Test alert from Flow2API",
            "text": "[Flow2API info] Test alert from Flow2API", "content": "[Flow2API info] Test alert from Flow2API",
            "details": {}, "time": _now_iso(),
        })
        return {"delivered": True}

    @staticmethod
    async def _post_json(url: str, body: Dict[str, Any]) -> None:
        def post() -> None:
            request = urllib.request.Request(
                url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "Flow2API-alerts"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=DELIVERY_TIMEOUT_SECONDS) as response:  # noqa: S310 - operator-configured URL
                if response.status >= 400:
                    raise urllib.error.HTTPError(url, response.status, "webhook rejected the alert", response.headers, None)

        await asyncio.to_thread(post)

    # ----- account health -----

    async def check_accounts(self) -> None:
        """Compare accounts with what a healthy deployment needs and raise or clear conditions."""
        tokens = await self._tokens()
        async with self.db._connect() as conn:
            sessions = {
                row[0]: (row[1], row[2])
                for row in await (await conn.execute("SELECT token_id, enabled, status FROM managed_browser_sessions")).fetchall()
            }
        signed_out = {token_id for token_id, (enabled, status) in sessions.items() if enabled and status in {"needs_login", "error"}}
        # An account flagged active whose browser session needs a new sign-in cannot generate.
        usable = [token for token in tokens if token.is_active and token.id not in signed_out]
        wanted: Dict[str, tuple] = {}
        if tokens and not usable:
            wanted["no_usable_account"] = ("critical", f"No account can generate: all {len(tokens)} are disabled or signed out.", {})
        elif len(tokens) > 1 and len(usable) == 1:
            wanted["single_usable_account"] = (
                "warning", f"Only one of {len(tokens)} accounts can generate ({usable[0].email}); a failure there stops all traffic.",
                {"usable": [usable[0].email]},
            )
        for token in tokens:
            enabled, status = sessions.get(token.id, (0, "not_configured"))
            if enabled and status in {"needs_login", "error"}:
                wanted[f"account_needs_login:{token.id}"] = (
                    "warning", f"Account {token.email} needs to sign in again (browser session: {status}).",
                    {"token_id": token.id, "email": token.email, "status": status},
                )
            if token.is_active and self.low_credits > 0 and token.credits < self.low_credits:
                wanted[f"credits_low:{token.id}"] = (
                    "warning", f"Account {token.email} has {token.credits} credits left (alert below {self.low_credits}).",
                    {"token_id": token.id, "email": token.email, "credits": token.credits},
                )
        health_keys = {"no_usable_account", "single_usable_account"}
        for key in [k for k in self.conditions if (k in health_keys or k.startswith(("account_needs_login:", "credits_low:"))) and k not in wanted]:
            await self.clear_condition(key)
        for key, (severity, message, details) in wanted.items():
            await self.raise_condition(key, message, severity=severity, details=details)

    # ----- lifecycle -----

    async def start(self) -> None:
        await self.load()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        await asyncio.sleep(20)  # let accounts finish their first refresh before judging them
        while True:
            try:
                await self.check_accounts()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"[alerts] account check failed: {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def status(self) -> Dict[str, Any]:
        return {
            "settings": self.describe_settings(),
            "conditions": sorted(self.conditions.values(), key=lambda item: (SEVERITIES.index(item["severity"]) * -1, item["key"])),
            "history": list(reversed(self.history[-30:])),
        }
