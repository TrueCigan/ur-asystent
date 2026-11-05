"""Client-carried HMAC-signed session state. No server DB on Render free."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field

STATE_TTL_SEC = 30 * 60  # 30 min


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
    conv_id: str | None = None
    updated_at: int = 0


def _secret() -> bytes:
    return (os.getenv("SESSION_SECRET") or "dev-only-change-me").encode("utf-8")


def encode(state: SessionState, secret: bytes | None = None) -> str:
    state.updated_at = int(time.time())
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
        conv_id=raw.get("conv_id"),
        updated_at=int(raw.get("updated_at") or 0),
    )


def fresh(conv_id: str | None = None) -> SessionState:
    return SessionState(conv_id=conv_id or str(uuid.uuid4()), updated_at=int(time.time()))


def resolve_state(token: str | None, history: list | None, conv_id: str | None = None) -> SessionState:
    """Drop stale / orphaned state. Empty history ⇒ fresh profile (privacy)."""
    state = decode(token)
    now = int(time.time())
    hist = history or []
    if state is None:
        return fresh(conv_id)
    if not hist:
        # Visible history empty → do not reuse profile (reload / new tab with leftover token)
        keep_lang = state.lang
        s = fresh(conv_id or state.conv_id)
        # Lang only if client still sends session_lang separately; do not keep profile
        s.lang = None
        return s
    if state.updated_at and now - state.updated_at > STATE_TTL_SEC:
        return fresh(conv_id or state.conv_id)
    if conv_id and state.conv_id and state.conv_id != conv_id:
        return fresh(conv_id)
    if conv_id and not state.conv_id:
        state.conv_id = conv_id
    return state
