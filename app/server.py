import os, sys, time, collections, threading
sys.path.insert(0, os.path.dirname(__file__))
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import rag
app = FastAPI(title="Asystent UR", docs_url=None, redoc_url=None, openapi_url=None)
@app.on_event("startup")
def _warm(): threading.Thread(target=rag.load, daemon=True).start()
MAXQ, MAXH, LIMIT, WIN, GLOBAL = 500, 10, 20, 600, 300
hits = collections.defaultdict(collections.deque); glob = collections.deque(); lock = threading.Lock()
sem = threading.Semaphore(3)
class Q(BaseModel):
    question: str
    history: list = []
def ip(r: Request):
    return r.headers.get("cf-connecting-ip") or (r.headers.get("x-forwarded-for") or "").split(",")[0].strip() or r.client.host
@app.get("/", response_class=HTMLResponse)
def home(): return open(os.path.join(os.path.dirname(__file__), "static", "index.html"), encoding="utf-8").read()
@app.post("/api/chat")
def chat(q: Q, r: Request):
    if not q.question.strip() or len(q.question) > MAXQ:
        raise HTTPException(400, f"Pytanie musi mieć od 1 do {MAXQ} znaków.")
    hist = [{"role": h.get("role"), "content": str(h.get("content", ""))[:3000]} for h in q.history[-MAXH:] if isinstance(h, dict) and h.get("role") in ("user", "assistant")]
    now = time.time(); k = ip(r)
    with lock:
        d = hits[k]
        while d and now - d[0] > WIN: d.popleft()
        while glob and now - glob[0] > 3600: glob.popleft()
        if len(d) >= LIMIT: raise HTTPException(429, "Limit: 20 pytań na 10 minut. Spróbuj później.")
        if len(glob) >= GLOBAL: raise HTTPException(429, "Dzienny/godzinny limit serwisu wyczerpany. Spróbuj później.")
        d.append(now); glob.append(now)
    if not sem.acquire(timeout=60): raise HTTPException(503, "Serwer zajęty, spróbuj za chwilę.")
    try: return rag.answer(q.question.strip(), hist)
    finally: sem.release()
@app.get("/healthz")
def healthz(): return {"ok": True}
@app.get("/api/status")
def status():
    if rag.IDX is None: rag.load()
    return {"chunks": len(rag.IDX["chunks"]), "llm": rag.llm_enabled(), "provider": os.getenv("LLM_PROVIDER", "none")}

app.mount("/assets", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="assets")
