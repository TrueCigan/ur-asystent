import os, sys, time, collections, threading, ipaddress
sys.path.insert(0, os.path.dirname(__file__))
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import rag
from security import redact_secrets, strip_untrusted_wrappers

app = FastAPI(title="Asystent UR", docs_url=None, redoc_url=None, openapi_url=None)

@app.on_event("startup")
def _warm():
    threading.Thread(target=rag.load, daemon=True).start()

MAXQ, MAXH, LIMIT, WIN, GLOBAL = 500, 10, 20, 600, 1000
hits = collections.defaultdict(collections.deque)
glob = collections.deque()
lock = threading.Lock()
sem = threading.Semaphore(3)

class Q(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAXQ)
    history: list = Field(default_factory=list)

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

@app.post("/api/chat")
def chat(q: Q, r: Request):
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
    k = ip(r)
    lang = rag.detect_lang(question, latest=question)
    limit_msg = {
        "pl": "Limit: 20 pytań na 10 minut. Spróbuj później.",
        "en": "Limit: 20 questions per 10 minutes. Please try again later.",
        "uk": "Ліміт: 20 запитань на 10 хвилин. Спробуйте пізніше.",
        "mn": "Хязгаар: 10 минутад 20 асуулт. Дараа дахин оролдоно уу.",
    }.get(lang, "Limit: 20 questions per 10 minutes. Please try again later.")
    glob_msg = {
        "pl": "Dzienny/godzinny limit serwisu wyczerpany. Spróbuj później.",
        "en": "Service hourly limit reached. Please try again later.",
        "uk": "Годинний ліміт сервісу вичерпано. Спробуйте пізніше.",
        "mn": "Үйлчилгээний цагийн хязгаар дууссан. Дараа дахин оролдоно уу.",
    }.get(lang, "Service hourly limit reached. Please try again later.")
    with lock:
        d = hits[k]
        while d and now - d[0] > WIN:
            d.popleft()
        while glob and now - glob[0] > 3600:
            glob.popleft()
        if len(d) >= LIMIT:
            raise HTTPException(429, limit_msg)
        if len(glob) >= GLOBAL:
            raise HTTPException(429, glob_msg)
        d.append(now)
        glob.append(now)
    if not sem.acquire(timeout=60):
        raise HTTPException(503, "Serwer zajęty, spróbuj za chwilę.")
    try:
        return rag.answer(question, hist)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Wewnętrzny błąd serwera. Spróbuj ponownie.")
    finally:
        sem.release()

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/api/status")
def status():
    if rag.IDX is None:
        rag.load()
    return {
        "chunks": len(rag.IDX["chunks"]),
        "llm": rag.llm_enabled(),
        "provider": "gemini" if os.getenv("LLM_PROVIDER", "").lower() == "gemini" else (
            "on" if rag.llm_enabled() else "off"
        ),
    }

@app.exception_handler(Exception)
async def _unhandled(_, exc):
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return JSONResponse({"detail": "Wewnętrzny błąd serwera."}, status_code=500)

app.mount("/assets", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="assets")
