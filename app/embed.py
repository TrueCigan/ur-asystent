"""Opcjonalne embeddingi przez API zgodne z OpenAI (EMBED_API_KEY, EMBED_BASE_URL, EMBED_MODEL)."""
import os, httpx, numpy as np
def embed_texts(texts, bs=64):
    # disabled/fake: no network. A real provider does not receive fake vectors.
    # Paid embed HTTP stays behind EVAL_REAL=1; the shipped index does not call this.
    from adapters import AdapterError, embeddings_provider, eval_real_enabled, fake_embeddings
    mode = embeddings_provider()
    if mode in ("", "disabled", "off", "none"):
        raise AdapterError("unavailable")
    if mode == "fake":
        rows = fake_embeddings(texts)
        return np.array(rows, dtype="float32")
    if not eval_real_enabled():
        raise AdapterError("unavailable")
    gem = mode == "gemini" or os.getenv("EMBED_PROVIDER", "").lower() == "gemini"
    key = os.getenv("GEMINI_API_KEY") if gem else os.environ["EMBED_API_KEY"]
    url = ("https://generativelanguage.googleapis.com/v1beta/openai" if gem else os.getenv("EMBED_BASE_URL", "https://api.openai.com/v1")) + "/embeddings"
    model = os.getenv("EMBED_MODEL", "gemini-embedding-001" if gem else "text-embedding-3-small"); out = []
    if gem: bs = min(bs, 50)
    for i in range(0, len(texts), bs):
        r = httpx.post(url, headers={"Authorization": "Bearer " + key},
                       json={"model": model, "input": texts[i:i+bs]}, timeout=120); r.raise_for_status()
        out += [d["embedding"] for d in r.json()["data"]]
    a = np.array(out, dtype="float32"); return a / np.linalg.norm(a, axis=1, keepdims=True)
