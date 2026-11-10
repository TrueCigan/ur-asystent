"""FAQ fast path. Zero LLM calls and zero embedding calls.

Score = 0.65 * alias_match + 0.25 * token_coverage + 0.10 * scope_match.
An exact approved alias has alias_match 1. The path opens only at
confidence >= 0.95 and margin >= 0.15, and only when the alias is unique
for that language. Thresholds are the TZ constants, not fitted on holdout.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from facts import load_facts, render_facts_for_user
from hard_filter import apply_hard_filters
from intent_code import parse_intent
from query_norm import normalize_query

ROOT = Path(__file__).resolve().parents[1]
CONFIDENCE_MIN = 0.95
MARGIN_MIN = 0.15
BLOCKED_FACTS = {
    "tuition_english_programmes",
    "tuition_polish_part_time_I",
    "disability_amounts",
    "doctoral_disability_topup_monthly",
}

_CATALOG = None


def heuristic(alias_match: float, token_coverage: float, scope_match: float) -> float:
    return 0.65 * alias_match + 0.25 * token_coverage + 0.10 * scope_match


def token_coverage(query: str, alias: str) -> float:
    wanted = alias.split()
    if not wanted:
        return 0.0
    have = set(query.split())
    return sum(1 for token in wanted if token in have) / len(wanted)


def scope_match(entry_year, query_year) -> float:
    if query_year and entry_year:
        return 1.0 if query_year == entry_year else 0.0
    if query_year or entry_year:
        return 0.0
    return 1.0


def load_catalog():
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    faq = yaml.safe_load((ROOT / "data" / "faq.yaml").read_text(encoding="utf-8"))
    synonyms = yaml.safe_load((ROOT / "data" / "synonyms.yaml").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in faq["entries"]}
    facts = {fact.id: fact for fact in load_facts()}
    aliases = []
    for row in synonyms["aliases"]:
        entry = by_id[row["entry"]]
        for fact_id in entry["fact_ids"]:
            if fact_id in BLOCKED_FACTS or fact_id not in facts:
                raise ValueError(f"{entry['id']} uses unsigned fact {fact_id}")
            if facts[fact_id].status != "verified":
                raise ValueError(f"{fact_id} is not verified")
        aliases.append({
            "entry": entry["id"],
            "topic": entry["topic"],
            "lang": row["lang"],
            "search": normalize_query(row["text"]).search,
        })
    _CATALOG = {
        "revision": faq["active_revision"],
        "entries": by_id,
        "aliases": aliases,
    }
    return _CATALOG


def _candidates(catalog, query: str, lang: str, intent):
    scored = []
    grouped = {}
    for alias in catalog["aliases"]:
        if alias["lang"] != lang:
            continue
        exact = 1.0 if query == alias["search"] else 0.0
        entry = catalog["entries"][alias["entry"]]
        coverage = token_coverage(query, alias["search"]) if exact else 0.0
        scope = scope_match(entry.get("academic_year"), intent.academic_year)
        score = heuristic(exact, coverage, scope)
        item = {
            "entry": entry,
            "alias": alias,
            "alias_match": exact,
            "coverage": coverage,
            "scope": scope,
            "score": score,
        }
        scored.append(item)
        if exact:
            grouped.setdefault((lang, alias["search"]), set()).add(entry["topic"])
    return scored, grouped


def try_fast_path(question: str, lang: str, catalog=None):
    """Return an answer dict, or None to continue with normal search."""
    catalog = catalog or load_catalog()
    intent = parse_intent(question)
    if intent.unknown_id:
        return _clarify(lang)
    if intent.negated or intent.compound or intent.relative_deadline:
        return None
    query = normalize_query(question).search
    if len(query.split()) < 2:
        return None
    scored, grouped = _candidates(catalog, query, lang, intent)
    exact = [row for row in scored if row["alias_match"] == 1.0]
    if not exact:
        return None
    topics = grouped.get((lang, query), set())
    if len(topics) != 1:
        return None
    exact.sort(key=lambda row: row["score"], reverse=True)
    best = exact[0]
    if len(best["alias"]["search"].split()) < 2:
        return None
    second = exact[1]["score"] if len(exact) > 1 else 0.0
    if best["score"] < CONFIDENCE_MIN or best["score"] - second < MARGIN_MIN:
        return None
    constraints = {"active_revision": catalog["revision"]}
    if intent.academic_year:
        constraints["academic_year"] = intent.academic_year
    kept = apply_hard_filters([best["entry"]], constraints)
    if not kept:
        return None
    return _answer(kept[0], lang, best["score"])


_PL_PROSE = re.compile(
    r"(?i)[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]|\b(albo|sekcja|elektronicznie|składa|wniosek|strona internetowa)\b"
)


def missing_faq_translations() -> list[tuple[str, str]]:
    """FAQ ids that have no approved lead in English or Ukrainian. Not machine-translated."""
    catalog = load_catalog()
    missing = []
    for entry in catalog["entries"].values():
        lead = entry.get("lead") or {}
        for lang in ("en", "uk"):
            if not str(lead.get(lang) or "").strip():
                missing.append((entry["id"], lang))
    return missing


def _without_untranslated_polish(body: str) -> str:
    kept = [line for line in (body or "").splitlines() if line.strip() and not _PL_PROSE.search(line)]
    return "\n".join(kept)


def _answer(entry: dict, lang: str, score: float) -> dict:
    facts = [fact for fact in load_facts() if fact.id in entry["fact_ids"]]
    leads = entry.get("lead") or {}
    lead = leads.get(lang) or ""
    body = render_facts_for_user(facts, lang)
    if lang in ("en", "uk") and lead:
        body = _without_untranslated_polish(body)
    elif not lead:
        lead = leads.get("pl") or ""
    text = (lead + "\n" + body).strip()
    sources = []
    for fact in facts:
        url = (fact.source or {}).get("url") or ""
        if url and url not in {item["url"] for item in sources}:
            sources.append({"title": (fact.i18n_label or {}).get(lang) or fact.id, "url": url, "fact_ids": [fact.id]})
    from answer_contract import faq_contract
    contract = faq_contract(lang, text, sources)
    return {
        "clarify": False,
        "mode": "faq",
        "sources": sources,
        "profile": {},
        "topics": [entry["topic"]],
        "answer": contract["answer"],
        "faq_id": entry["id"],
        "faq_score": score,
        "contract": contract,
    }


def _clarify(lang: str) -> dict:
    text = {
        "pl": "Nie mam oficjalnego identyfikatora wydziału ani kierunku. Nie zgaduję go.",
        "en": "There is no official faculty or programme id on file. I will not guess one.",
        "uk": "Офіційного ідентифікатора факультету чи програми немає. Я його не вгадую.",
    }.get(lang, "Nie mam oficjalnego identyfikatora wydziału ani kierunku. Nie zgaduję go.")
    return {
        "clarify": True,
        "mode": "clarify",
        "sources": [],
        "profile": {},
        "topics": [],
        "answer": text,
        "faq_id": None,
        "faq_score": 0.0,
    }
