"""Closed /admin/ai on the in-process Phase 4 notes.

Roles are viewer, editor, and admin. There is no external identity provider.
Secrets are not rendered and are not written to the admin log. Samples never
keep the raw question, a network id, a session id, or a user id.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

import phase4

log = logging.getLogger("ur.admin")
ROOT = Path(__file__).resolve().parents[1]
router = APIRouter()
RANK = {"viewer": 1, "editor": 2, "admin": 3}
AUDIT: list[dict] = []
FAQ_ACTIVE: dict[str, bool] = {}
PAGE = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Admin AI</title></head>
<body>
<h1>Admin AI</h1>
<p>This page has no embedded secret. Paste a role token issued by the session route.</p>
<p>Latency percentiles are not measured. The 40-case score is not measured.</p>
<label>Token <input id="token" autocomplete="off"></label>
<label>CSRF <input id="csrf" autocomplete="off"></label>
<pre id="out"></pre>
<script>
async function loadOverview() {
  const res = await fetch("/api/admin/ai/overview", {headers: {Authorization: "Bearer " + document.getElementById("token").value}});
  document.getElementById("out").textContent = await res.text();
}
</script>
<button type="button" onclick="loadOverview()">Overview</button>
</body>
</html>
"""


class AdminError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def _secret() -> bytes:
    raw = (os.getenv("ADMIN_TOKEN_SECRET") or os.getenv("SESSION_SECRET") or "").strip()
    if not raw:
        raw = "admin-token-unset"
    return raw.encode("utf-8")


def _password_role(password: str) -> str | None:
    if not password:
        return None
    for role, env in (
        ("admin", "ADMIN_ADMIN_PASSWORD"),
        ("editor", "ADMIN_EDITOR_PASSWORD"),
        ("viewer", "ADMIN_VIEWER_PASSWORD"),
    ):
        expected = os.getenv(env) or ""
        if expected and hmac.compare_digest(password, expected):
            return role
    return None


def issue_token(role: str, now: float | None = None) -> dict:
    if role not in RANK:
        raise AdminError(403, "role")
    now = time.time() if now is None else now
    csrf = hmac.new(_secret(), f"{role}:{int(now)}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    payload = {"role": role, "exp": int(now) + 8 * 3600, "csrf": csrf}
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    import base64
    text = base64.urlsafe_b64encode(body).decode("ascii")
    sig = hmac.new(_secret(), text.encode("ascii"), hashlib.sha256).hexdigest()
    return {"token": f"{text}.{sig}", "csrf": csrf, "role": role, "expires_at": payload["exp"]}


def read_token(header: str | None) -> dict | None:
    if not header or not header.lower().startswith("bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    if "." not in token:
        return None
    text, sig = token.rsplit(".", 1)
    expect = hmac.new(_secret(), text.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    import base64
    try:
        payload = json.loads(base64.urlsafe_b64decode(text.encode("ascii")))
    except Exception:
        return None
    if payload.get("role") not in RANK or int(payload.get("exp") or 0) < time.time():
        return None
    return payload


def require(header: str | None, minimum: str, csrf: str | None = None, mutating: bool = False) -> str:
    payload = read_token(header)
    if payload is None:
        raise AdminError(401, "role")
    if RANK[payload["role"]] < RANK[minimum]:
        raise AdminError(403, "role")
    if mutating and not hmac.compare_digest(str(csrf or ""), str(payload.get("csrf") or "")):
        raise AdminError(403, "csrf")
    return payload["role"]


def purge_audit(today) -> None:
    kept = []
    for row in AUDIT:
        stamp = row.get("at") or ""
        if stamp and phase4.age_days(stamp, today) >= phase4.TECHNICAL_DAYS:
            continue
        kept.append(row)
    AUDIT[:] = kept


if purge_audit not in phase4.PURGE_HOOKS:
    phase4.PURGE_HOOKS.append(purge_audit)


def _audit(role: str, action: str, detail: dict) -> None:
    safe = {key: value for key, value in detail.items() if "secret" not in key and "password" not in key and "token" not in key}
    AUDIT.append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "role": role, "action": action, "detail": safe})
    log.info("admin action=%s role=%s", action, role)
    phase4.purge_expired()


def overview() -> dict:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    rows = [row for row in phase4.NOTES.samples if row.get("created_at") == today]
    requests = len(rows)
    faq = sum(1 for row in rows if row.get("path") == "faq")
    generated = sum(1 for row in rows if row.get("path") == "generation")
    no_answer = sum(1 for row in rows if row.get("path") == "no_answer")
    clarification = sum(1 for row in rows if row.get("path") == "clarification")
    errors = sum(1 for row in rows if row.get("error_code"))
    lookups = [row for row in rows if row.get("cache_lookup")]
    hits = sum(1 for row in lookups if row.get("cache_hit"))
    prices = phase4.load_prices()
    missing = [name for name in ("input", "output", "cached_input", "embedding") if prices.get(name) is None]
    book = phase4.LEDGER
    unknown = bool(missing) or book.unknown["queries"] or book.unknown["ingestion"]

    def percent(numerator: int, denominator: int, of: str) -> dict:
        if denominator == 0:
            return {"value": None, "numerator": numerator, "denominator": 0, "of": of}
        return {
            "value": round(100 * numerator / denominator, 1),
            "numerator": numerator,
            "denominator": denominator,
            "of": of,
        }

    report = {
        "requests_today": requests,
        "requests_denominator": "in-process redacted notes for this UTC date; not a reconstructed history",
        "faq_percent": percent(faq, requests, "requests today"),
        "generated_percent": percent(generated, requests, "requests today"),
        "cache_hit_percent": percent(hits, len(lookups), "cache lookups today (hit + miss)"),
        "no_answer": no_answer,
        "clarification": clarification,
        "errors": errors,
        "tokens": None,
        "tokens_note": "token counts are recorded only when a provider usage object exists; none is invented",
        "usd_today": {
            "queries": None if unknown else book.usd["queries"],
            "ingestion": None if unknown else book.usd["ingestion"],
            "cost_status": "unknown" if unknown else "estimated",
        },
        "budget_usd": phase4.daily_budget(),
        "unknown_prices": missing,
        "unknown_marker": "unknown" if unknown else None,
        "latency_p50_ms": "not measured",
        "latency_p95_ms": "not measured",
        "score_40": "not measured",
    }
    phase4.remember_summary(today, {
        "requests": requests,
        "faq": faq,
        "generated": generated,
        "unknown": report["unknown_marker"],
    })
    return report


def list_samples(date: str | None = None, path: str | None = None, error: str | None = None) -> list[dict]:
    rows = []
    banned = ("question", "query", "ip", "session", "user", "state", "answer", "email", "phone")
    for row in phase4.NOTES.samples:
        if date and row.get("created_at") != date:
            continue
        if path and row.get("path") != path:
            continue
        has_error = bool(row.get("error_code"))
        if error == "yes" and not has_error:
            continue
        if error == "no" and has_error:
            continue
        clean = {}
        for key, value in row.items():
            if any(word in key.lower() for word in banned):
                continue
            text = json.dumps(value, ensure_ascii=False)
            if "@" in text or "+48" in text:
                continue
            clean[key] = value
        rows.append(clean)
    return rows


def _load_yaml(name: str) -> dict:
    import yaml
    return yaml.safe_load((ROOT / "data" / name).read_text(encoding="utf-8")) or {}


def faq_catalog() -> list[dict]:
    raw = _load_yaml("faq.yaml")
    rows = []
    for entry in raw.get("entries") or []:
        active = FAQ_ACTIVE.get(entry["id"], bool(entry.get("active")))
        rows.append({
            "id": entry["id"],
            "topic": entry.get("topic"),
            "academic_year": entry.get("academic_year"),
            "valid_from": entry.get("valid_from"),
            "valid_to": entry.get("valid_to"),
            "fact_ids": list(entry.get("fact_ids") or []),
            "active": active,
            "revision": entry.get("revision"),
        })
    return rows


def faq_conflicts() -> dict:
    rows = faq_catalog()
    groups: dict[tuple, list[str]] = {}
    for row in rows:
        if not row["active"]:
            continue
        key = (row["topic"], row["academic_year"])
        groups.setdefault(key, []).append(row["id"])
    clashes = [
        {"topic": topic, "academic_year": year, "ids": ids}
        for (topic, year), ids in groups.items() if len(ids) > 1
    ]
    aliases = _load_yaml("synonyms.yaml").get("aliases") or []
    seen: dict[tuple, str] = {}
    alias_clashes = []
    for alias in aliases:
        key = (alias.get("lang"), (alias.get("text") or "").strip().lower())
        previous = seen.get(key)
        if previous and previous != alias.get("entry"):
            alias_clashes.append({"lang": key[0], "entries": [previous, alias.get("entry")]})
        seen[key] = alias.get("entry")
    return {"entry_overlaps": clashes, "alias_overlaps": alias_clashes, "published": False}


def publish_faq(role: str, patches: list[dict], confirm: bool) -> dict:
    if role != "admin":
        raise AdminError(403, "role")
    if confirm is not True:
        raise AdminError(400, "confirm")
    known = {row["id"] for row in faq_catalog()}
    for patch in patches:
        if set(patch) - {"id", "active"}:
            raise AdminError(400, "faq_fields")
        if patch.get("id") not in known:
            raise AdminError(400, "unknown_faq")
        if not isinstance(patch.get("active"), bool):
            raise AdminError(400, "faq_fields")
        FAQ_ACTIVE[patch["id"]] = patch["active"]
    _audit(role, "faq_publish", {"ids": [patch["id"] for patch in patches]})
    return {"ok": True, "conflicts": faq_conflicts()}


def sources_report(root: Path | None = None) -> dict:
    root = Path(root or os.getenv("ADMIN_INDEX_ROOT") or (ROOT / "data" / "revisions"))
    from index_revision import current_id
    pointer = current_id(root)
    index = ROOT / "data" / "index.npz"
    stale = []
    for row in faq_catalog():
        if row.get("valid_to"):
            stale.append({"id": row["id"], "valid_to": row["valid_to"]})
    return {
        "current_revision": pointer,
        "shipped_index_present": index.is_file(),
        "last_successful_update": "not recorded" if pointer is None else pointer,
        "stale": stale,
        "extraction_quality": "not measured",
        "published_by_this_report": False,
    }


def dry_run_reindex(docs: list[dict], root: Path | None = None) -> dict:
    from index_revision import document_digest
    root = Path(root or os.getenv("ADMIN_INDEX_ROOT") or (ROOT / "data" / "revisions"))
    digest = document_digest(docs)
    rev = digest[:20]
    exists = (root / "revisions" / rev / "manifest.json").is_file()
    return {"revision": rev, "already_exists": exists, "published": False, "documents": len(docs)}


def _build_stub(staging: Path, docs: list[dict]) -> None:
    (staging / "index.npz").write_bytes(b"dry-" + str(len(docs)).encode("ascii"))
    (staging / "meta.json.gz").write_bytes(b"{}")


def publish_index(role: str, docs: list[dict], confirm: bool, root: Path | None = None) -> dict:
    if role != "admin":
        raise AdminError(403, "role")
    if confirm is not True:
        raise AdminError(400, "confirm")
    from index_revision import publish
    root = Path(root or os.getenv("ADMIN_INDEX_ROOT") or (ROOT / "data" / "revisions"))
    revision = publish(root, docs, _build_stub)
    _audit(role, "index_publish", {"revision": revision, "documents": len(docs)})
    return {"revision": revision, "published": True}


def rollback_index(role: str, revision: str, confirm: bool, root: Path | None = None) -> dict:
    if role != "admin":
        raise AdminError(403, "role")
    if confirm is not True:
        raise AdminError(400, "confirm")
    from index_revision import rollback
    root = Path(root or os.getenv("ADMIN_INDEX_ROOT") or (ROOT / "data" / "revisions"))
    previous = rollback(root, revision)
    _audit(role, "index_rollback", {"revision": revision, "previous": previous})
    return {"current": revision, "previous": previous}


def quality_report() -> dict:
    from answer_contract import TOPICS
    covered = {row["topic"] for row in faq_catalog() if row["active"]}
    gaps = sorted(topic for topic in TOPICS if topic not in covered)
    return {
        "schema_topics_without_faq": gaps,
        "faq_topics": sorted(covered),
        "score_40": "not measured",
        "score_note": "The 40-case 0-4 score has not been measured. This page does not run that eval.",
    }


WRITABLE = {
    "response_ttl_s": 15 * 60,
    "deadline_ttl_s": 5 * 60,
    "no_answer_ttl_s": 60,
    "intent_ttl_s": 24 * 60 * 60,
    "faq_ttl_s": 24 * 60 * 60,
    "limit_per_minute": 20,
    "limit_per_day": 200,
    "global_per_minute": 60,
    "max_generations": 10,
}
SECRET_MARKERS = ("secret", "password", "token", "api_key", "apikey", "authorization", "bearer")


def settings_view() -> dict:
    prices = phase4.load_prices()
    current = {name: phase4.OVERRIDES.get(name, default) for name, default in WRITABLE.items()}
    current["model"] = phase4.OVERRIDES.get("model") or (os.getenv("LLM_MODEL") or "unconfigured")
    current["prices"] = {name: prices.get(name) for name in ("input", "output", "cached_input", "embedding")}
    return {
        "values": current,
        "flags": {
            "eval_real": os.getenv("EVAL_REAL", "0"),
            "scenario_social": os.getenv("SCENARIO_SOCIAL", "0"),
            "mongolian_answers": "off",
        },
        "flags_writable": False,
        "secrets_accepted": False,
    }


def _reject_secret_text(text: str) -> None:
    lowered = text.lower()
    if any(marker in lowered for marker in ("sk-", "aiza", "begin private", "api_key", "session_secret")):
        raise AdminError(400, "secret")


def preview_settings(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise AdminError(400, "settings")
    for key in patch:
        if any(marker in key.lower() for marker in SECRET_MARKERS):
            raise AdminError(400, "secret")
    _reject_secret_text(json.dumps(patch))
    changes = {}
    proposed = {}
    for key, value in patch.items():
        if key == "prices":
            if not isinstance(value, dict):
                raise AdminError(400, "price")
            clean = {}
            for name in ("input", "output", "cached_input", "embedding"):
                if name not in value:
                    continue
                price = value[name]
                if price is None:
                    clean[name] = None
                elif isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0:
                    raise AdminError(400, "price")
                else:
                    clean[name] = float(price)
            if set(value) - set(clean):
                raise AdminError(400, "price")
            proposed["prices"] = clean
            changes["prices"] = clean
            continue
        if key == "model":
            if not isinstance(value, str) or not value.strip() or len(value) > 64:
                raise AdminError(400, "model")
            _reject_secret_text(value)
            proposed["model"] = value.strip()
            changes["model"] = proposed["model"]
            continue
        if key not in WRITABLE:
            raise AdminError(400, "unknown_setting")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > WRITABLE[key]:
            raise AdminError(400, "range")
        proposed[key] = value
        changes[key] = {"from": phase4.OVERRIDES.get(key, WRITABLE[key]), "to": value}
    preview_id = hashlib.sha256(json.dumps(proposed, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {"changes": changes, "preview_id": preview_id, "saved": False}


def save_settings(role: str, patch: dict, preview_id: str, confirm: bool) -> dict:
    if role != "admin":
        raise AdminError(403, "role")
    if confirm is not True:
        raise AdminError(400, "confirm")
    preview = preview_settings(patch)
    if not hmac.compare_digest(preview["preview_id"], str(preview_id or "")):
        raise AdminError(400, "preview")
    for key, value in patch.items():
        if key == "prices":
            phase4.OVERRIDES["prices"] = preview["changes"]["prices"]
        else:
            phase4.OVERRIDES[key] = preview["changes"][key]["to"] if isinstance(preview["changes"][key], dict) else preview["changes"][key]
    _audit(role, "settings_save", {"keys": sorted(patch)})
    return {"ok": True, "values": settings_view()["values"]}


def _guard(authorization: str | None, minimum: str, csrf: str | None = None, mutating: bool = False) -> str:
    try:
        return require(authorization, minimum, csrf, mutating)
    except AdminError as exc:
        raise HTTPException(exc.status, exc.code) from exc


@router.post("/api/admin/ai/session")
def open_session(body: dict):
    role = _password_role(str(body.get("password") or ""))
    if role is None:
        log.info("admin session refused")
        raise HTTPException(401, "role")
    issued = issue_token(role)
    log.info("admin session role=%s", role)
    return {"token": issued["token"], "csrf": issued["csrf"], "role": role}


@router.get("/admin/ai", response_class=HTMLResponse)
def admin_page(authorization: str | None = Header(default=None)):
    _guard(authorization, "viewer")
    return PAGE


@router.get("/api/admin/ai/overview")
def admin_overview(authorization: str | None = Header(default=None)):
    _guard(authorization, "viewer")
    return overview()


@router.get("/api/admin/ai/samples")
def admin_samples(
    authorization: str | None = Header(default=None),
    date: str | None = None,
    path: str | None = None,
    error: str | None = None,
):
    _guard(authorization, "viewer")
    return {"samples": list_samples(date, path, error)}


@router.get("/api/admin/ai/sources")
def admin_sources(authorization: str | None = Header(default=None)):
    _guard(authorization, "viewer")
    return sources_report()


@router.post("/api/admin/ai/sources/dry-run")
def admin_dry_run(body: dict, authorization: str | None = Header(default=None), x_csrf_token: str | None = Header(default=None)):
    _guard(authorization, "editor", x_csrf_token, mutating=True)
    docs = body.get("docs") or []
    if not isinstance(docs, list):
        raise HTTPException(400, "docs")
    return dry_run_reindex(docs)


@router.post("/api/admin/ai/sources/publish")
def admin_publish(body: dict, authorization: str | None = Header(default=None), x_csrf_token: str | None = Header(default=None)):
    role = _guard(authorization, "admin", x_csrf_token, mutating=True)
    try:
        return publish_index(role, list(body.get("docs") or []), body.get("confirm") is True)
    except AdminError as exc:
        raise HTTPException(exc.status, exc.code) from exc


@router.post("/api/admin/ai/sources/rollback")
def admin_rollback(body: dict, authorization: str | None = Header(default=None), x_csrf_token: str | None = Header(default=None)):
    role = _guard(authorization, "admin", x_csrf_token, mutating=True)
    try:
        return rollback_index(role, str(body.get("revision") or ""), body.get("confirm") is True)
    except AdminError as exc:
        raise HTTPException(exc.status, exc.code) from exc


@router.get("/api/admin/ai/faq")
def admin_faq(authorization: str | None = Header(default=None)):
    _guard(authorization, "viewer")
    return {"entries": faq_catalog(), "conflicts": faq_conflicts()}


@router.post("/api/admin/ai/faq/publish")
def admin_faq_publish(body: dict, authorization: str | None = Header(default=None), x_csrf_token: str | None = Header(default=None)):
    role = _guard(authorization, "admin", x_csrf_token, mutating=True)
    try:
        return publish_faq(role, list(body.get("patches") or []), body.get("confirm") is True)
    except AdminError as exc:
        raise HTTPException(exc.status, exc.code) from exc


@router.get("/api/admin/ai/quality")
def admin_quality(authorization: str | None = Header(default=None)):
    _guard(authorization, "viewer")
    return quality_report()


@router.get("/api/admin/ai/settings")
def admin_settings(authorization: str | None = Header(default=None)):
    _guard(authorization, "viewer")
    return settings_view()


@router.post("/api/admin/ai/settings/preview")
def admin_settings_preview(body: dict, authorization: str | None = Header(default=None), x_csrf_token: str | None = Header(default=None)):
    _guard(authorization, "editor", x_csrf_token, mutating=True)
    try:
        return preview_settings(body.get("patch") or {})
    except AdminError as exc:
        raise HTTPException(exc.status, exc.code) from exc


@router.post("/api/admin/ai/settings")
def admin_settings_save(body: dict, authorization: str | None = Header(default=None), x_csrf_token: str | None = Header(default=None)):
    role = _guard(authorization, "admin", x_csrf_token, mutating=True)
    try:
        return save_settings(role, body.get("patch") or {}, str(body.get("preview_id") or ""), body.get("confirm") is True)
    except AdminError as exc:
        raise HTTPException(exc.status, exc.code) from exc


@router.get("/api/admin/ai/audit")
def admin_audit(authorization: str | None = Header(default=None)):
    _guard(authorization, "viewer")
    return {"audit": AUDIT[-50:]}
