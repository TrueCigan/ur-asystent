"""Client-carried HMAC-signed session state (Task 4). No server DB on Render free."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass, field


@dataclass
class SessionState:
    v: int = 1
    lang: str | None = None
    profile: dict = field(default_factory=dict)
    intents: list[str] = field(default_factory=list)
    pending_slots: list[str] = field(default_factory=list)
    pending_question: str | None = None
    original_question: str | None = None
    conflicts: list[dict] = field(default_factory=list)


def _secret() -> bytes:
    return (os.getenv("SESSION_SECRET") or "dev-only-change-me").encode("utf-8")


def encode(state: SessionState, secret: bytes | None = None) -> str:
    payload = json.dumps(asdict(state), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode("ascii")
    sig = hmac.new(secret or _secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def decode(token: str | None, secret: bytes | None = None) -> SessionState | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expect = hmac.new(secret or _secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    try:
        raw = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return SessionState(
        v=int(raw.get("v") or 1),
        lang=raw.get("lang"),
        profile=dict(raw.get("profile") or {}),
        intents=list(raw.get("intents") or []),
        pending_slots=list(raw.get("pending_slots") or []),
        pending_question=raw.get("pending_question"),
        original_question=raw.get("original_question"),
        conflicts=list(raw.get("conflicts") or []),
    )


def fresh() -> SessionState:
    return SessionState()
