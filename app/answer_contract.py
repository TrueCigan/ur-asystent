"""Phase 3 answer contract. One generation, no repair call, server-side citations.

The model may return only the TZ answer object. URL, title, and page are copied
from the server manifest. Invalid output becomes a template or no_answer.
"""
from __future__ import annotations

import html
import json
import re
import uuid
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = ROOT / "data" / "prompts"
ANSWER_LANGS = {"pl", "en", "uk"}
HELP_CHUNK_ID = "help:swiadczenia"
HELP_URL = "https://student.uniwersytetradom.pl/swiadczenia-dla-studentow-pomoc-materialna/"
HELP_TITLE = {
    "pl": "Świadczenia dla studentów",
    "en": "Student benefits",
    "uk": "Виплати для студентів",
}
_CITE = re.compile(r"\[(\d+)\]")
_YEAR = re.compile(r"^\d{4}/\d{4}$")


class IntentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str
    answer_lang: str
    faculty_id: str | None
    program_id: str | None
    academic_year: str | None
    source_lang: str | None
    temporal_mode: str
    needs_clarification: bool
    clarification_question: str | None


class CitationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = Field(ge=1)
    chunk_id: str = Field(min_length=1)


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    language: str
    answer: str
    citations: list[CitationIn]
    follow_up: str | None


TOPICS = {"admissions", "programs", "fees", "schedule", "housing", "contacts", "other"}
STATUSES = {"answered", "partial", "clarification", "no_answer"}
TEMPORAL = {"current", "historical", "unspecified"}


def load_prompt_settings() -> dict:
    import yaml
    raw = yaml.safe_load((PROMPT_DIR / "manifest.yaml").read_text(encoding="utf-8"))
    version = raw["version"]
    return {
        "version": version,
        "temperature": raw["temperature"],
        "allow_two_calls": bool(raw["allow_two_calls"]),
        "parse_max_tokens": int(raw["parse_max_tokens"]),
        "answer_max_tokens": int(raw["answer_max_tokens"]),
        "context_max_tokens": int(raw["context_max_tokens"]),
        "parse_timeout_s": int(raw["parse_timeout_s"]),
        "answer_timeout_s": int(raw["answer_timeout_s"]),
        "budget_s": int(raw["budget_s"]),
        "parse_prompt": (PROMPT_DIR / raw["parse"]).read_text(encoding="utf-8").strip(),
        "answer_prompt": (PROMPT_DIR / raw["answer"]).read_text(encoding="utf-8").strip(),
    }


def parse_json_object(raw: str) -> tuple[dict | None, str | None]:
    """Return (object, None) or (None, reason). No second model call."""
    text = (raw or "").strip()
    if not text:
        return None, "invalid_schema"
    if text.startswith("```"):
        return None, "invalid_schema"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, "truncated" if text.startswith("{") else "invalid_schema"
    if not isinstance(data, dict):
        return None, "invalid_schema"
    return data, None


def validate_intent(data: dict, *, known_faculties: set[str] | None = None, known_programs: set[str] | None = None):
    try:
        intent = IntentIn.model_validate(data)
    except ValidationError:
        return None
    if intent.topic not in TOPICS or intent.temporal_mode not in TEMPORAL:
        return None
    if intent.answer_lang not in ANSWER_LANGS:
        return None
    if intent.academic_year is not None and not _YEAR.match(intent.academic_year):
        return None
    faculties = known_faculties if known_faculties is not None else set()
    programs = known_programs if known_programs is not None else set()
    if intent.faculty_id is not None and intent.faculty_id not in faculties:
        return None
    if intent.program_id is not None and intent.program_id not in programs:
        return None
    if intent.needs_clarification:
        if not intent.clarification_question:
            return None
    elif intent.clarification_question is not None:
        return None
    return intent


def apply_explicit_filters(intent: IntentIn, explicit: dict | None) -> IntentIn:
    """Server filters win. A model null must not erase a year the user stated."""
    explicit = explicit or {}
    updates = {}
    for key in ("faculty_id", "program_id", "academic_year", "source_lang"):
        if explicit.get(key) not in (None, ""):
            updates[key] = explicit[key]
    if not updates:
        return intent
    return intent.model_copy(update=updates)


def manifest_index(manifest: list[dict]) -> dict[str, dict]:
    return {row["chunk_id"]: row for row in manifest or [] if row.get("chunk_id")}


def validate_answer(data: dict, manifest: list[dict], *, language: str):
    try:
        answer = AnswerIn.model_validate(data)
    except ValidationError:
        return None, "invalid_schema"
    if answer.status not in STATUSES or answer.language not in ANSWER_LANGS:
        return None, "invalid_schema"
    if answer.language != language:
        return None, "lang"
    text = answer.answer
    if not (1 <= len(text) <= 3000):
        return None, "invalid_schema"
    if len(answer.citations) > 5:
        return None, "forbidden_citation"
    numbers = [item.n for item in answer.citations]
    ids = [item.chunk_id for item in answer.citations]
    if len(numbers) != len(set(numbers)) or len(ids) != len(set(ids)):
        return None, "forbidden_citation"
    by_id = manifest_index(manifest)
    bound = []
    for item in answer.citations:
        row = by_id.get(item.chunk_id)
        if row is None or int(row.get("n") or 0) != item.n:
            return None, "forbidden_citation"
        if answer.status == "no_answer" and item.chunk_id != HELP_CHUNK_ID:
            return None, "forbidden_citation"
        if answer.status == "clarification":
            return None, "forbidden_citation"
        bound.append({
            "n": item.n,
            "chunk_id": item.chunk_id,
            "url": row.get("url") or "",
            "title": row.get("title") or "",
            "page": row.get("page"),
        })
    cited = {int(m.group(1)) for m in _CITE.finditer(text)}
    listed = {item.n for item in answer.citations}
    if cited != listed:
        return None, "forbidden_citation"
    if answer.status in ("answered", "partial") and not bound:
        return None, "forbidden_citation"
    return {
        "status": answer.status,
        "language": answer.language,
        "answer": text,
        "citations": bound,
        "follow_up": answer.follow_up,
    }, None


def trim_evidence(evidence: list[dict], max_tokens: int) -> list[dict]:
    """Rough token cap: 4 characters ≈ 1 token. Drops tail evidence, not filters."""
    budget = max_tokens * 4
    kept = []
    used = 0
    for row in evidence or []:
        text = row.get("text") or ""
        room = budget - used
        if room <= 0:
            break
        if len(text) > room:
            row = dict(row, text=text[:room])
        kept.append(row)
        used += len(row.get("text") or "")
    return kept


def help_manifest(lang: str) -> list[dict]:
    return [{
        "n": 1,
        "chunk_id": HELP_CHUNK_ID,
        "title": HELP_TITLE.get(lang, HELP_TITLE["pl"]),
        "url": HELP_URL,
        "page": None,
        "text": "",
    }]


def fallback_contract(lang: str, manifest: list[dict], reason: str) -> dict:
    lang = lang if lang in ANSWER_LANGS else "pl"
    usable = [row for row in manifest or [] if row.get("url") and row.get("chunk_id") != HELP_CHUNK_ID]
    usable = usable[:3]
    if usable:
        bits = []
        citations = []
        for i, row in enumerate(usable, 1):
            bits.append(f"[{i}]")
            citations.append({
                "n": i,
                "chunk_id": row["chunk_id"],
                "url": row.get("url") or "",
                "title": row.get("title") or "",
                "page": row.get("page"),
            })
        lead = {
            "pl": "Oficjalne materiały w tej sprawie: " + " ".join(bits),
            "en": "Official material on this subject: " + " ".join(bits),
            "uk": "Офіційні матеріали з цього питання: " + " ".join(bits),
        }[lang]
        status = "partial"
    else:
        lead = {
            "pl": "W dostępnych oficjalnych materiałach nie znalazłem potwierdzenia. [1]",
            "en": "I could not confirm this in the available official material. [1]",
            "uk": "У доступних офіційних матеріалах я не знайшов підтвердження. [1]",
        }[lang]
        row = help_manifest(lang)[0]
        citations = [{
            "n": 1,
            "chunk_id": row["chunk_id"],
            "url": row["url"],
            "title": row["title"],
            "page": None,
        }]
        status = "no_answer"
    return {
        "status": status,
        "language": lang,
        "answer": lead,
        "citations": citations,
        "follow_up": None,
        "degraded": reason,
    }


def accept_model_answer(raw: str, manifest: list[dict], language: str):
    data, reason = parse_json_object(raw)
    if data is None:
        return None, reason
    return validate_answer(data, manifest, language=language)


def looks_like_json(raw: str) -> bool:
    return (raw or "").lstrip().startswith(("{", "[", "```"))


def faq_contract(lang: str, text: str, sources: list[dict]) -> dict:
    """Bind an approved FAQ answer to server sources. Does not add facts."""
    lang = lang if lang in ANSWER_LANGS else "pl"
    citations = []
    marks = []
    body = text or ""
    for i, source in enumerate(sources or [], 1):
        if i > 5:
            break
        fact_ids = source.get("fact_ids") or []
        chunk_id = fact_ids[0] if fact_ids else f"faq-source-{i}"
        citations.append({
            "n": i,
            "chunk_id": chunk_id,
            "url": source.get("url") or "",
            "title": source.get("title") or chunk_id,
            "page": source.get("page"),
        })
        marks.append(f"[{i}]")
    if marks and not _CITE.search(body):
        body = (body.rstrip() + " " + " ".join(marks)).strip()
    return {
        "status": "answered",
        "language": lang,
        "answer": body,
        "citations": citations,
        "follow_up": None,
    }


def escape_client_text(text: str) -> str:
    return html.escape(text or "", quote=True)


def buffered_events(result: dict, request_id: str | None = None) -> list[dict]:
    """Events after validation. No raw model JSON and no unverified tokens."""
    request_id = request_id or uuid.uuid4().hex
    contract = result.get("contract") or {}
    answer = contract.get("answer") or result.get("answer") or ""
    sources = []
    for row in contract.get("citations") or result.get("sources") or []:
        url = (row.get("url") or "").strip()
        if not url:
            continue
        sources.append({
            "n": row.get("n"),
            "title": row.get("title") or "",
            "url": url,
            "page": row.get("page"),
        })
    events = [
        {"event": "status", "data": {"request_id": request_id, "stage": "validated"}},
        {"event": "sources", "data": {"request_id": request_id, "sources": sources}},
    ]
    step = 80
    for start in range(0, max(len(answer), 1), step):
        portion = answer[start:start + step]
        if not portion and start:
            break
        events.append({
            "event": "answer",
            "data": {"request_id": request_id, "text": portion},
        })
        if not answer:
            break
    events.append({
        "event": "done",
        "data": {
            "request_id": request_id,
            "status": contract.get("status") or "partial",
            "language": contract.get("language") or result.get("lang") or "pl",
            "clarify": bool(result.get("clarify")),
            "state": result.get("state") or "",
            "mode": result.get("mode") or "",
        },
    })
    return events


def format_sse(events: list[dict]) -> str:
    chunks = []
    for event in events:
        payload = json.dumps(event["data"], ensure_ascii=False)
        chunks.append(f"event: {event['event']}\ndata: {payload}\n\n")
    return "".join(chunks)


def provider_failure_reason(exc: Exception) -> str:
    text = str(exc).lower()
    if "timeout" in text:
        return "timeout"
    if "429" in text or "rate" in text:
        return "rate_limit"
    return "unavailable"


def error_event(message: str, request_id: str | None = None) -> str:
    text = " ".join((message or "error").split())
    lowered = text.lower()
    if "traceback" in lowered or "provider" in lowered or len(text) > 180:
        text = "error"
    safe = escape_client_text(text)
    data = {"request_id": request_id or uuid.uuid4().hex, "message": safe}
    return "event: error\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n"
