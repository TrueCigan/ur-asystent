"""In-process cache, HMAC rate limit, and cost notes. No Redis and no embeddings.

The response key is public and stateless. It never includes a session or user id.
A missing token price stays unknown. It is not stored as zero.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESPONSE_TTL = 15 * 60
DEADLINE_TTL = 5 * 60
NO_ANSWER_TTL = 60
INTENT_TTL = 24 * 60 * 60
FAQ_TTL = 24 * 60 * 60
MINUTE = 60
DAY = 24 * 60 * 60


class CacheUnavailable(Exception):
    pass


class Overloaded(Exception):
    pass


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def response_cache_key(
    *,
    university_id: str,
    normalized_query: str,
    answer_lang: str,
    canonical_filters: dict,
    index_revision: str,
    settings_revision: str,
    prompt_version: str,
    model_version: str,
) -> str:
    """SHA256 of the TZ fields. sessionId and userId are not accepted."""
    filters = json.dumps(canonical_filters or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    material = "|".join([
        "university_id=" + (university_id or ""),
        "normalized_query=" + (normalized_query or ""),
        "answer_lang=" + (answer_lang or ""),
        "canonical_filters=" + filters,
        "index_revision=" + (index_revision or ""),
        "settings_revision=" + (settings_revision or ""),
        "prompt_version=" + (prompt_version or ""),
        "model_version=" + (model_version or ""),
    ])
    return _sha("response|" + material)


def intent_cache_key(*, university_id: str, normalized_query: str, dictionaries: str, temporal: dict) -> str:
    temporal_text = json.dumps(temporal or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha("|".join(["intent", university_id or "", normalized_query or "", dictionaries or "", temporal_text]))


def ttl_seconds(
    kind: str,
    now: datetime,
    *,
    contains_deadline: bool = False,
    valid_to: datetime | None = None,
    relative_date: bool = False,
) -> int:
    if kind == "no_answer":
        ttl = NO_ANSWER_TTL
    elif kind == "intent":
        ttl = INTENT_TTL
    elif kind == "faq":
        ttl = FAQ_TTL
    else:
        ttl = RESPONSE_TTL
    if contains_deadline:
        ttl = min(ttl, DEADLINE_TTL)
    if kind == "faq":
        ttl = min(ttl, FAQ_TTL)
    if valid_to is not None:
        remaining = int((valid_to - now).total_seconds())
        ttl = min(ttl, max(0, remaining))
    if relative_date:
        local = now.astimezone(now.tzinfo) if now.tzinfo else now
        nxt = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        ttl = min(ttl, max(1, int((nxt - local).total_seconds())))
    return ttl


class ResponseCache:
    def __init__(self):
        self.available = True
        self.store: dict[str, dict] = {}
        self.flights: dict[str, dict] = {}
        self.fingerprint = ""
        self._lock = threading.Lock()

    def note_fingerprint(self, fingerprint: str) -> None:
        if fingerprint != self.fingerprint:
            self.store.clear()
            self.fingerprint = fingerprint

    def get(self, key: str, now: float, *, faq_fingerprint: str | None = None):
        if not self.available:
            raise CacheUnavailable()
        with self._lock:
            item = self.store.get(key)
            if not item:
                return None
            if item["expires"] <= now or (faq_fingerprint is not None and item.get("faq_fingerprint") != faq_fingerprint):
                self.store.pop(key, None)
                return None
            return dict(item["value"])

    def put(self, key: str, value: dict, ttl: int, now: float, *, faq_fingerprint: str | None = None) -> None:
        if not self.available:
            raise CacheUnavailable()
        public = {k: v for k, v in value.items() if k not in ("state", "session", "user_id", "session_id")}
        with self._lock:
            self.store[key] = {
                "value": public,
                "expires": now + max(0, ttl),
                "faq_fingerprint": faq_fingerprint,
            }

    def single_flight(self, key: str, compute, ttl: int, now: float, *, faq_fingerprint: str | None = None):
        if not self.available:
            raise CacheUnavailable()
        with self._lock:
            flight = self.flights.get(key)
            if flight is None:
                flight = {"event": threading.Event(), "result": None, "error": None}
                self.flights[key] = flight
                owner = True
            else:
                owner = False
        if not owner:
            flight["event"].wait()
            if flight["error"] is not None:
                raise flight["error"]
            return flight["result"]
        try:
            result = compute()
            public = {k: v for k, v in result.items() if k not in ("state", "session", "user_id", "session_id")}
            self.put(key, public, ttl, now, faq_fingerprint=faq_fingerprint)
            flight["result"] = public
            return result
        except Exception as exc:
            flight["error"] = exc
            raise
        finally:
            flight["event"].set()
            with self._lock:
                self.flights.pop(key, None)


class Limiter:
    """20/minute and 200/day per HMAC, plus 60/minute global. Raw network ids are not stored."""

    def __init__(self):
        self._ids: dict[str, deque] = {}
        self._global: deque = deque()
        self._lock = threading.Lock()
        self.notes: list[str] = []

    def token(self, network_id: str, secret: bytes, now: float) -> str:
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        return hmac.new(secret, f"{day}:{network_id}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def check(self, network_id: str, secret: bytes, now: float) -> tuple[bool, int, str]:
        token = self.token(network_id, secret, now)
        with self._lock:
            self.notes.append(token)
            bucket = self._ids.setdefault(token, deque())
            while bucket and now - bucket[0] > DAY:
                bucket.popleft()
            recent = [stamp for stamp in bucket if now - stamp <= MINUTE]
            while self._global and now - self._global[0] > MINUTE:
                self._global.popleft()
            if len(self._global) >= 60:
                return False, max(1, int(MINUTE - (now - self._global[0])) + 1), "global"
            if len(recent) >= 20:
                return False, max(1, int(MINUTE - (now - recent[0])) + 1), "minute"
            if len(bucket) >= 200:
                return False, max(1, int(DAY - (now - bucket[0])) + 1), "day"
            bucket.append(now)
            self._global.append(now)
            return True, 0, ""


class Breaker:
    def __init__(self):
        self.errors: deque = deque()
        self.open_until = 0.0
        self._lock = threading.Lock()

    def record(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self.errors.append(now)
            while self.errors and now - self.errors[0] > 30:
                self.errors.popleft()
            if len(self.errors) >= 5:
                self.open_until = now + 60

    def is_open(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            return now < self.open_until


class Ledger:
    def __init__(self):
        self.usd = {"queries": 0.0, "ingestion": 0.0}
        self.unknown = {"queries": 0, "ingestion": 0}

    def add(self, stream: str, quote: dict) -> None:
        if stream not in self.usd:
            raise ValueError("stream")
        if quote.get("cost_status") == "unknown":
            self.unknown[stream] += 1
            return
        if quote.get("cost") is not None:
            self.usd[stream] += float(quote["cost"])


def quote_cost(usage: dict, prices: dict, provider_charge: float | None = None) -> dict:
    """TZ formula. An actual charge replaces the estimate and is not added to it."""
    if provider_charge is not None:
        return {"cost": float(provider_charge), "cost_status": "actual"}
    parts = [
        (int(usage.get("uncached_input_tokens") or 0), prices.get("input")),
        (int(usage.get("cached_input_tokens") or 0), prices.get("cached_input")),
        (int(usage.get("output_tokens") or 0), prices.get("output")),
        (int(usage.get("embedding_tokens") or 0), prices.get("embedding")),
    ]
    total = 0.0
    for tokens, price in parts:
        if not tokens:
            continue
        if price is None:
            return {"cost": None, "cost_status": "unknown"}
        total += tokens * float(price)
    return {"cost": total / 1_000_000, "cost_status": "estimated"}


def load_prices() -> dict:
    import yaml
    raw = yaml.safe_load((ROOT / "data" / "prices.yaml").read_text(encoding="utf-8")) or {}
    row = (raw.get("prices") or [{}])[0]
    per = dict((row.get("usd_per_1m") or {}))
    for name, env in (
        ("input", "PRICE_INPUT_PER_1M"),
        ("output", "PRICE_OUTPUT_PER_1M"),
        ("cached_input", "PRICE_CACHED_INPUT_PER_1M"),
        ("embedding", "PRICE_EMBEDDING_PER_1M"),
    ):
        text = (os.getenv(env) or "").strip()
        if text:
            per[name] = float(text)
    return per


def load_settings() -> dict:
    import yaml
    return yaml.safe_load((ROOT / "data" / "phase4_settings.yaml").read_text(encoding="utf-8")) or {}


def daily_budget() -> float | None:
    text = (os.getenv("DAILY_GENERATION_BUDGET_USD") or "").strip()
    if text:
        return float(text)
    value = load_settings().get("daily_generation_budget_usd")
    if value is None or value == "":
        return None
    return float(value)


def budget_open(ledger: Ledger | None = None) -> bool:
    budget = daily_budget()
    if budget is None:
        return True
    book = ledger if ledger is not None else LEDGER
    if book.unknown["queries"]:
        return False
    return book.usd["queries"] < budget


def file_fingerprint(*paths: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:20]


def faq_fingerprint() -> str:
    return file_fingerprint(ROOT / "data" / "faq.yaml", ROOT / "data" / "synonyms.yaml")


_INDEX_FP = {"mtime": None, "value": ""}


def index_revision() -> str:
    """Pointer file when a revision was published, otherwise the shipped snapshot hash."""
    from index_revision import current_id
    pointer = current_id(ROOT / "data" / "revisions")
    if pointer:
        return pointer
    path = ROOT / "data" / "index.npz"
    mtime = path.stat().st_mtime if path.is_file() else None
    if _INDEX_FP["mtime"] != mtime:
        _INDEX_FP["mtime"] = mtime
        _INDEX_FP["value"] = file_fingerprint(path) if path.is_file() else "missing"
    return _INDEX_FP["value"]


def contains_pii(text: str) -> bool:
    import re
    if not text:
        return False
    if re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, re.I):
        return True
    if re.search(r"(?<!\d)\d{9,}(?!\d)", text) or re.search(r"\+\d{8,}", text):
        return True
    if re.search(r"(?i)(?:album|numer\s+albumu|student\s*id|indeks)\s*[:#]?\s*\d{4,}", text):
        return True
    return False


CACHE = ResponseCache()
INTENT_CACHE = ResponseCache()
LIMITER = Limiter()
BREAKER = Breaker()
LEDGER = Ledger()


def remember_intent(question: str, university_id: str) -> dict:
    """24h intent cache. The key is the normalized question plus the Warsaw date."""
    from dataclasses import asdict
    from datetime import datetime

    from clock import timezone_name, zone
    from intent_code import parse_intent
    from query_norm import normalize_query

    norm = normalize_query(question).search
    moment = datetime.now(zone())
    temporal = {"resolved_date": moment.date().isoformat(), "timezone": timezone_name()}
    key = intent_cache_key(
        university_id=university_id,
        normalized_query=norm,
        dictionaries=faq_fingerprint(),
        temporal=temporal,
    )
    now = time.time()
    try:
        hit = INTENT_CACHE.get(key, now)
    except CacheUnavailable:
        hit = None
    if hit and isinstance(hit.get("intent"), dict):
        return hit["intent"]
    parsed = asdict(parse_intent(question))
    intent = {name: list(value) if isinstance(value, tuple) else value for name, value in parsed.items()}
    try:
        INTENT_CACHE.put(key, {"intent": intent}, ttl_seconds("intent", moment), now)
    except CacheUnavailable:
        pass
    return intent


def generation_allowed() -> bool:
    if BREAKER.is_open():
        return False
    return budget_open()


def note_provider_error() -> None:
    BREAKER.record()
