"""Fake ports for Phase 0. Real providers are not replaced by fakes.

EVAL_REAL=0 (the default) blocks this module from opening a network call.
LLM_PROVIDER=fake returns a fixed string and does not read the API key.
A real provider plus a key stays on the existing rag.call_llm path; this
module will not call that path unless EVAL_REAL=1, which Phase 0 tests reject.
"""
from __future__ import annotations

import hashlib
import math
import os

FAKE_EMBED_DIM = 8
FAKE_EMBED_MODEL = "fake-v0"
_MODES = ("ok", "timeout", "quota", "unavailable", "invalid_json", "forbidden_citation")

# Fixed shape only. Not an official answer and not a scholarship amount.
_FAKE_OK = (
    '{"lang":"pl","template":"FAKE","fact_ids":[],"source_ids":[],"computed_need":[]}'
)
_FAKE_INVALID = "{"
_FAKE_FORBIDDEN = (
    '{"lang":"pl","template":"FAKE","fact_ids":[],'
    '"source_ids":["forbidden-chunk-not-in-manifest"],"computed_need":[]}'
)


class AdapterError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def eval_real_enabled() -> bool:
    return os.getenv("EVAL_REAL", "0").strip() == "1"


def llm_provider() -> str:
    return (os.getenv("LLM_PROVIDER") or "").strip().lower()


def embeddings_provider() -> str:
    raw = os.getenv("EMBEDDINGS_PROVIDER")
    if raw is None or raw.strip() == "":
        raw = os.getenv("EMBED_PROVIDER") or "disabled"
    return raw.strip().lower()


def production_llm_would_use_fake() -> bool:
    """True only when the process is explicitly in fake mode.

    A configured real provider is never reported as fake, with or without a key.
    """
    return llm_provider() in ("fake",)


def fake_mode() -> str:
    mode = (os.getenv("FAKE_LLM_MODE") or "ok").strip().lower()
    if mode == "429":
        mode = "quota"
    if mode not in _MODES:
        raise AdapterError("invalid_output")
    return mode


def fake_llm_complete() -> str:
    """Fixed result. Does not touch the network or the API key."""
    mode = fake_mode()
    if mode == "timeout":
        raise AdapterError("timeout")
    if mode == "quota":
        raise AdapterError("quota")
    if mode == "unavailable":
        raise AdapterError("unavailable")
    if mode == "invalid_json":
        return _FAKE_INVALID
    if mode == "forbidden_citation":
        return _FAKE_FORBIDDEN
    return _FAKE_OK


def complete(messages, temperature=0.25) -> str:
    """Eval entry. Refuses a paid call when EVAL_REAL is not 1.

    messages and temperature are accepted so callers match call_llm.
    Fake mode ignores them. They are not logged.
    """
    del messages, temperature
    provider = llm_provider()
    if provider in ("", "fake", "off", "disabled"):
        return fake_llm_complete()
    if not eval_real_enabled():
        raise AdapterError("unavailable")
    # EVAL_REAL=1 is out of Phase 0 scope. Refuse here as well so a mistaken
    # flag cannot spend a call from this harness.
    raise AdapterError("unavailable")


def fake_embeddings(texts) -> list[list[float]]:
    """Deterministic unit vectors. Dimension is 8, not the production 1536."""
    rows = []
    for text in texts:
        digest = hashlib.sha256(("fake-v0\0" + str(text)).encode("utf-8")).digest()
        raw = []
        while len(raw) < FAKE_EMBED_DIM:
            digest = hashlib.sha256(digest).digest()
            raw.extend(((b / 127.5) - 1.0) for b in digest)
        vec = raw[:FAKE_EMBED_DIM]
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        rows.append([v / norm for v in vec])
    return rows


def embed(texts) -> list[list[float]]:
    """Embeddings port. disabled/fake never call the network.

    A real embeddings provider with EVAL_REAL=0 raises unavailable.
    It does not return fake vectors in place of a paid embedding.
    """
    mode = embeddings_provider()
    if mode in ("", "disabled", "off", "none"):
        raise AdapterError("unavailable")
    if mode == "fake":
        return fake_embeddings(texts)
    if not eval_real_enabled():
        raise AdapterError("unavailable")
    raise AdapterError("unavailable")
