import os, sys, time, threading, ipaddress
sys.path.insert(0, os.path.dirname(__file__))
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import rag
from security import redact_secrets, strip_untrusted_wrappers

app = FastAPI(title="Asystent UR", docs_url=None, redoc_url=None, openapi_url=None)

@app.on_event("startup")
def _warm():
    threading.Thread(target=rag.load, daemon=True).start()

MAXQ, MAXH = 500, 10
# At most 10 generations at once. A full set returns 503.
sem = threading.Semaphore(10)
_RATE_SECRET = None

class Q(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAXQ)
    history: list = Field(default_factory=list)
    session_lang: str | None = Field(default=None, max_length=8)
    state: str | None = Field(default=None, max_length=8000)
    conv_id: str | None = Field(default=None, max_length=64)
    # Optional form context for verified social scenario (no PII beyond income estimate inputs)
    scenario_context: dict | None = None

def _public_ip(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        ip = ipaddress.ip_address(s.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return None
        return str(ip)
    except ValueError:
        return None

def ip(r: Request):
    """Prefer Cloudflare; otherwise last public hop in XFF (spoof-resistant vs client-leftmost)."""
    cf = (r.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf
    xff = r.headers.get("x-forwarded-for") or ""
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    for cand in reversed(parts):
        pub = _public_ip(cand)
        if pub:
            return pub
    if parts:
        return parts[-1]
    return r.client.host if r.client else "unknown"

@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    # Widget na stronach UR: pozwól iframe tylko z domen uczelni
    resp.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' https://*.uniwersytetradom.pl https://uniwersytetradom.pl"
    )
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp

@app.get("/", response_class=HTMLResponse)
def home():
    path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(path, encoding="utf-8") as f:
        return f.read()

def _rate_secret() -> bytes:
    global _RATE_SECRET
    raw = (os.getenv("RATE_LIMIT_SECRET") or os.getenv("SESSION_SECRET") or "").strip()
    if raw:
        return raw.encode("utf-8")
    if _RATE_SECRET is None:
        _RATE_SECRET = os.urandom(32)
    return _RATE_SECRET


def _answer_request(q: Q, r: Request):
    question = q.question.strip()
    if not question or len(question) > MAXQ:
        raise HTTPException(400, f"Pytanie musi mieć od 1 do {MAXQ} znaków.")
    hist = []
    for h in (q.history or [])[-MAXH:]:
        if not isinstance(h, dict):
            continue
        role = h.get("role")
        if role not in ("user", "assistant"):
            continue
        hist.append({
            "role": role,
            "content": strip_untrusted_wrappers(redact_secrets(str(h.get("content", ""))[:3000])),
        })
    now = time.time()
    hist_user = "\n".join(m["content"] for m in hist if m["role"] == "user")
    lang = rag.detect_lang(question, hist_user, latest=question, session_lang=q.session_lang)
    from phase4 import LIMITER, Overloaded, contains_pii
    # The network id is hashed inside the limiter and is not stored or logged.
    allowed, retry_after, scope = LIMITER.check(ip(r), _rate_secret(), now)
    if not allowed:
        detail = {
            "pl": "Limit: 20 pytań na minutę i 200 na dobę." if scope != "global" else "Limit serwisu: 60 pytań na minutę.",
            "en": "Limit: 20 questions per minute and 200 per day." if scope != "global" else "Service limit: 60 questions per minute.",
            "uk": "Ліміт: 20 запитань на хвилину і 200 на добу." if scope != "global" else "Ліміт сервісу: 60 запитань на хвилину.",
        }.get(lang, "Limit: 20 questions per minute and 200 per day.")
        raise HTTPException(429, detail, headers={"Retry-After": str(retry_after)})
    busy = {
        "pl": "Serwer zajęty, spróbuj za chwilę.",
        "en": "Server busy, please try again shortly.",
        "uk": "Сервер зайнятий, спробуйте за мить.",
    }.get(lang, "Serwer zajęty, spróbuj za chwilę.")

    def compute():
        if not sem.acquire(timeout=0):
            raise Overloaded()
        try:
            return rag.answer(
                question, hist,
                session_lang=q.session_lang,
                state_token=q.state,
                conv_id=q.conv_id,
                scenario_context=q.scenario_context,
            )
        finally:
            sem.release()

    t0 = time.time()
    try:
        private = contains_pii(question) or contains_pii(hist_user) or bool(q.scenario_context)
        result = _cached_or_compute(question, q.session_lang, lang, now, compute, private)
        if isinstance(result, dict) and not result.get("state"):
            result["state"] = q.state
        return result
    except Overloaded:
        raise HTTPException(503, busy)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Wewnętrzny błąd serwera. Spróbuj ponownie.")
    finally:
        try:
            import logging
            logging.getLogger("ur.api").info("chat done in %.2fs", time.time() - t0)
        except Exception:
            pass


def _cached_or_compute(question, session_lang, lang, now, compute, private: bool):
    """Rate limiting already happened. A down cache still runs compute()."""
    from datetime import datetime
    from phase4 import (
        CACHE, CacheUnavailable, faq_fingerprint, load_settings, remember_intent,
        response_cache_key, ttl_seconds, index_revision,
    )
    from query_norm import normalize_query
    from answer_contract import load_prompt_settings
    from clock import timezone_name, zone

    if private:
        return compute()
    norm = normalize_query(question).search
    intent = remember_intent(question, str(load_settings().get("university_id") or ""))
    filters = {
        "topics": list(intent.get("topics") or []),
        "academic_year": intent.get("academic_year"),
        "faculty_id": intent.get("faculty_id"),
        "program_id": intent.get("program_id"),
        "answer_lang": lang,
    }
    relative = bool(intent.get("relative_deadline"))
    if relative:
        filters["resolved_date"] = datetime.now(zone()).date().isoformat()
        filters["timezone"] = timezone_name()
    settings = load_settings()
    revision = index_revision()
    settings_revision = f"{settings.get('revision') or ''}|faq:{faq_fingerprint()}"
    prompt_version = str(load_prompt_settings().get("version") or "")
    model_version = (os.getenv("LLM_MODEL") or "unconfigured").strip()
    key = response_cache_key(
        university_id=str(settings.get("university_id") or ""),
        normalized_query=norm,
        answer_lang=lang or session_lang or "",
        canonical_filters=filters,
        index_revision=revision,
        settings_revision=settings_revision,
        prompt_version=prompt_version,
        model_version=model_version,
    )
    CACHE.note_fingerprint("|".join([revision, settings_revision, prompt_version, model_version]))
    faq_fp = faq_fingerprint()
    try:
        hit = CACHE.get(key, now, faq_fingerprint=faq_fp)
    except CacheUnavailable:
        return compute()
    if hit is not None:
        hit["cache"] = "hit"
        return hit
    try:
        result = CACHE.single_flight(key, compute, 60, now, faq_fingerprint=faq_fp)
    except CacheUnavailable:
        return compute()
    if isinstance(result, dict) and result.get("cache") != "hit":
        # The in-flight copy used a short TTL. Replace it with the real one.
        kind, deadline = _cache_kind(result, relative)
        moment = datetime.now(zone())
        ttl = ttl_seconds(kind, moment, contains_deadline=deadline, relative_date=relative)
        try:
            public = {k: v for k, v in result.items() if k not in ("state", "session")}
            public["cache"] = "miss"
            CACHE.put(key, public, ttl, now, faq_fingerprint=faq_fp)
        except CacheUnavailable:
            pass
        result = dict(result)
        result["cache"] = "miss"
    return result


def _cache_kind(result: dict, relative: bool) -> tuple[str, bool]:
    contract = result.get("contract") or {}
    status = str(contract.get("status") or "")
    answer = (result.get("answer") or "").lower()
    deadline = relative or any(word in answer for word in ("termin", "deadline", "до "))
    if status == "no_answer":
        return "no_answer", deadline
    if result.get("mode") == "faq":
        return "faq", deadline
    return "response", deadline

@app.post("/api/chat")
def chat(q: Q, r: Request):
    return _answer_request(q, r)

@app.post("/api/chat/stream")
def chat_stream(q: Q, r: Request):
    """Buffered SSE. The model text is validated before any answer event."""
    from answer_contract import buffered_events, error_event, format_sse
    request_id = uuid_request()
    try:
        result = _answer_request(q, r)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "error"
        return StreamingResponse(
            iter([error_event(detail, request_id)]),
            media_type="text/event-stream",
            status_code=exc.status_code,
            headers=dict(exc.headers or {}),
        )
    except Exception:
        return StreamingResponse(
            iter([error_event("error", request_id)]),
            media_type="text/event-stream",
            status_code=500,
        )
    return StreamingResponse(
        iter([format_sse(buffered_events(result, request_id))]),
        media_type="text/event-stream",
    )

def uuid_request():
    import uuid
    return uuid.uuid4().hex

@app.get("/healthz")
def healthz():
    # Warm index on health checks so Render cold starts finish before traffic
    if rag.IDX is None:
        try:
            rag.load()
        except Exception:
            return JSONResponse({"ok": False}, status_code=503)
    return {"ok": True, "chunks": len(rag.IDX["chunks"]) if rag.IDX else 0}

@app.get("/api/status")
def status():
    if rag.IDX is None:
        rag.load()
    from scenarios.social import scenario_social_enabled
    prov = (os.getenv("LLM_PROVIDER") or "").lower()
    if not rag.llm_enabled():
        provider = "off"
    elif prov in ("anthropic", "gemini", "openai", "xai", "ollama"):
        provider = prov
    else:
        provider = "on"
    return {
        "chunks": len(rag.IDX["chunks"]),
        "llm": rag.llm_enabled(),
        "provider": provider,
        "scenario_social": scenario_social_enabled(),
    }


class SocialEstimateIn(BaseModel):
    income: str | float | int = Field(...)
    academic_year: str | None = Field(default=None, max_length=16)
    interested_in_dorm_topup: bool = False
    dorm_conditions_met: bool | None = None
    lang: str | None = Field(default="pl", max_length=8)
    profile: dict | None = None


@app.get("/api/scenarios/social-scholarship")
def social_scholarship_card(lang: str = "pl"):
    """Verified social-scholarship card — no LLM."""
    from scenarios.social import build_card
    from lang import map_policy
    lang = map_policy((lang or "pl").lower())
    if lang not in ("pl", "en", "uk"):
        lang = "pl"
    return build_card(lang)


@app.post("/api/scenarios/social-scholarship/estimate")
def social_scholarship_estimate(body: SocialEstimateIn):
    """Code-only income → group/amount estimate (not an entitlement decision)."""
    from scenarios.social import estimate
    from lang import map_policy
    lang = map_policy((body.lang or "pl").lower())
    if lang not in ("pl", "en", "uk"):
        lang = "pl"
    return estimate(
        body.income,
        academic_year=body.academic_year,
        interested_in_dorm_topup=body.interested_in_dorm_topup,
        dorm_conditions_met=body.dorm_conditions_met,
        profile=body.profile or {},
        lang=lang,
    )

@app.exception_handler(Exception)
async def _unhandled(_, exc):
    if isinstance(exc, HTTPException):
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=dict(exc.headers or {}),
        )
    return JSONResponse({"detail": "Wewnętrzny błąd serwera."}, status_code=500)

app.mount("/assets", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="assets")
