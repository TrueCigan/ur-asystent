"""Opcjonalne embeddingi przez API zgodne z OpenAI (EMBED_API_KEY, EMBED_BASE_URL, EMBED_MODEL)."""
import os, httpx, numpy as np
def embed_texts(texts, bs=64):
    gem = os.getenv("EMBED_PROVIDER", "").lower() == "gemini"
    key = os.getenv("GEMINI_API_KEY") if gem else os.environ["EMBED_API_KEY"]
    url = ("https://generativelanguage.googleapis.com/v1beta/openai" if gem else os.getenv("EMBED_BASE_URL", "https://api.openai.com/v1")) + "/embeddings"
    model = os.getenv("EMBED_MODEL", "gemini-embedding-001" if gem else "text-embedding-3-small"); out = []
    if gem: bs = min(bs, 50)
    for i in range(0, len(texts), bs):
        r = httpx.post(url, headers={"Authorization": "Bearer " + key},
                       json={"model": model, "input": texts[i:i+bs]}, timeout=120); r.raise_for_status()
        out += [d["embedding"] for d in r.json()["data"]]
    a = np.array(out, dtype="float32"); return a / np.linalg.norm(a, axis=1, keepdims=True)
