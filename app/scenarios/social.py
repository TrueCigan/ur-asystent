"""Social scholarship verified scenario — card + Decimal estimate, no LLM figures."""
from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from facts import Fact, income_group, load_facts

_ROOT = Path(__file__).resolve().parents[2]
_SCENARIO_PATH = _ROOT / "data" / "scenarios" / "social_scholarship.yaml"
_SCENARIO_CACHE: dict | None = None

_MONEY_QUANT = Decimal("0.01")


def scenario_social_enabled() -> bool:
    """Product switch — default OFF."""
    return os.getenv("SCENARIO_SOCIAL", "").strip().lower() in ("1", "true", "on", "yes")


def _load_scenario() -> dict:
    global _SCENARIO_CACHE
    if _SCENARIO_CACHE is not None:
        return _SCENARIO_CACHE
    with open(_SCENARIO_PATH, encoding="utf-8") as f:
        _SCENARIO_CACHE = yaml.safe_load(f) or {}
    return _SCENARIO_CACHE


def reload_scenario_cache() -> None:
    global _SCENARIO_CACHE
    _SCENARIO_CACHE = None


def _fact_map() -> dict[str, Fact]:
    return {f.id: f for f in load_facts()}


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v).replace(",", ".").replace(" ", "").replace("\u00a0", ""))
    except (InvalidOperation, ValueError):
        return None
    return d.quantize(_MONEY_QUANT)


def _fmt_money(d: Decimal | None, lang: str = "pl") -> str:
    if d is None:
        return ""
    q = d.quantize(_MONEY_QUANT)
    if q == q.to_integral_value():
        whole = f"{int(q)}"
        return f"{whole} zł" if lang != "en" else f"{whole} PLN"
    s = f"{q:.2f}"
    if lang == "en":
        return f"{s} PLN"
    return f"{s.replace('.', ',')} zł"


def _i18n(lang: str) -> dict:
    sc = _load_scenario()
    pack = (sc.get("i18n") or {}).get(lang) or (sc.get("i18n") or {}).get("pl") or {}
    return dict(pack)


def _fact_payload(f: Fact | None, lang: str) -> dict | None:
    if not f:
        return None
    label = (f.i18n_label or {}).get(lang) or (f.i18n_label or {}).get("pl") or f.id
    src = f.source or {}
    return {
        "id": f.id,
        "label": label,
        "value": f.value,
        "unit": f.unit,
        "academic_year": f.academic_year,
        "status": f.status,
        "verification": "confirmed" if f.status == "verified" else "unconfirmed",
        "source": {
            "url": src.get("url"),
            "ordinance": src.get("ordinance"),
            "document_date": src.get("document_date"),
            "checked": src.get("checked"),
        },
        "deadline": f.deadline,
    }


def amounts_confirmed_for_year(year: str, facts: dict[str, Fact] | None = None) -> bool:
    facts = facts or _fact_map()
    sc = _load_scenario()
    fid = (sc.get("fact_refs") or {}).get("income_and_amounts")
    f = facts.get(fid) if fid else None
    return bool(f and f.status == "verified" and f.academic_year == year and isinstance(f.value, dict))


def build_card(lang: str = "pl") -> dict:
    """Assemble card JSON from fact refs + static i18n (no duplicated amounts)."""
    lang = lang if lang in ("pl", "en", "uk") else "pl"
    sc = _load_scenario()
    facts = _fact_map()
    refs = sc.get("fact_refs") or {}
    t = _i18n(lang)

    income_f = facts.get(refs.get("income_and_amounts"))
    caps = [_fact_payload(facts.get(cid), lang) for cid in (refs.get("caps") or [])]
    caps = [c for c in caps if c]
    window_f = facts.get(refs.get("application_window"))
    channel_f = facts.get(refs.get("submission_channel"))
    ua_f = facts.get(refs.get("ua_temporary_protection"))

    amount_year = income_f.academic_year if income_f else None
    groups = []
    max_income = None
    dorm_topup = None
    dorm_rule = None
    if income_f and isinstance(income_f.value, dict):
        max_income = _dec(income_f.value.get("max"))
        amounts = income_f.value.get("amounts") or {}
        ranges = income_f.value.get("groups") or {}
        for g in ("I", "II", "III", "IV"):
            if g in amounts:
                groups.append({
                    "group": g,
                    "income_range": ranges.get(g),
                    "amount": str(_dec(amounts[g])),
                    "amount_display": _fmt_money(_dec(amounts[g]), lang),
                })
        dorm_topup = _dec(income_f.value.get("zwiekszenie_akademik"))
        dorm_rule = income_f.value.get("zwiekszenie_akademik_rule")

    links = []
    for item in sc.get("official_links") or []:
        if item.get("fact_id"):
            fp = _fact_payload(facts.get(item["fact_id"]), lang)
            if fp and fp["source"].get("url"):
                links.append({
                    "url": fp["source"]["url"],
                    "label": fp["label"],
                    "academic_year": fp["academic_year"],
                    "checked": fp["source"].get("checked"),
                })
        elif item.get("url"):
            links.append({
                "url": item["url"],
                "label": t.get(item.get("label_key") or "", item["url"]),
            })

    return {
        "id": sc.get("id"),
        "lang": lang,
        "enabled": scenario_social_enabled(),
        "title": t.get("title"),
        "badge_verified": t.get("badge_verified"),
        "intro": t.get("intro"),
        "conditions": {
            "title": t.get("conditions_title"),
            "body": t.get("conditions_body"),
            "ua_note": (ua_f.value if ua_f else None),
            "ua_fact": _fact_payload(ua_f, lang),
        },
        "amounts": {
            "title": t.get("amounts_title"),
            "note": t.get("amounts_note"),
            "academic_year": amount_year,
            "verification": "confirmed" if amounts_confirmed_for_year(amount_year or "", facts) else "unconfirmed",
            "max_income": str(max_income) if max_income is not None else None,
            "max_income_display": _fmt_money(max_income, lang),
            "groups": groups,
            "fact": _fact_payload(income_f, lang),
            "year_banner": (t.get("year_banner_confirmed") or "").format(year=amount_year or ""),
        },
        "dorm_topup": {
            "title": t.get("dorm_topup_title"),
            "amount": str(dorm_topup) if dorm_topup is not None else None,
            "amount_display": _fmt_money(dorm_topup, lang),
            "rule": dorm_rule,
            "auto_included": False,
            "academic_year": amount_year,
            "fact_id": refs.get("income_and_amounts"),
        },
        "caps": caps,
        "deadlines": {
            "title": t.get("deadlines_title"),
            "fact": _fact_payload(window_f, lang),
            "value": window_f.value if window_f else None,
            "academic_year": window_f.academic_year if window_f else None,
        },
        "channel": _fact_payload(channel_f, lang),
        "documents": {
            "title": t.get("documents_title"),
            "body": t.get("documents_body"),
            "status": t.get("documents_status"),  # partial — not a full checklist in FACTS
        },
        "links": {"title": t.get("links_title"), "items": links},
        "form_labels": {
            "title": t.get("form_title"),
            "income": t.get("form_income"),
            "year": t.get("form_year"),
            "dorm": t.get("form_dorm"),
            "submit": t.get("form_submit"),
            "hint": t.get("form_hint"),
        },
        "default_estimate_year": sc.get("default_estimate_year") or amount_year,
        "checked_at": (income_f.source or {}).get("checked") if income_f else None,
    }


def estimate(
    income: Any,
    *,
    academic_year: str | None = None,
    interested_in_dorm_topup: bool = False,
    dorm_conditions_met: bool | None = None,
    profile: dict | None = None,
    lang: str = "pl",
) -> dict:
    """Code-only amount estimate. Never claims entitlement from income alone."""
    lang = lang if lang in ("pl", "en", "uk") else "pl"
    t = _i18n(lang)
    sc = _load_scenario()
    facts = _fact_map()
    year = academic_year or sc.get("default_estimate_year") or "2025/2026"
    refs = sc.get("fact_refs") or {}
    income_f = facts.get(refs.get("income_and_amounts"))

    base: dict[str, Any] = {
        "lang": lang,
        "academic_year": year,
        "eligibility": "unknown",
        "eligibility_note": t.get("result_not_eligibility"),
        "dorm_topup_included": False,
        "interested_in_dorm_topup": bool(interested_in_dorm_topup),
    }

    if not amounts_confirmed_for_year(year, facts):
        return {
            **base,
            "ok": False,
            "result": "amounts_not_confirmed",
            "message": (t.get("err_year") or "").format(year=year)
            if "{year}" in (t.get("err_year") or "")
            else t.get("err_year"),
            "year_banner": (t.get("year_banner_unconfirmed") or "").format(year=year),
        }

    inc = _dec(income)
    if inc is None or inc < 0:
        return {**base, "ok": False, "result": "input_error", "message": t.get("err_input")}

    # Zero is a valid income input (maps into group I when table starts at 0).
    groups_val = income_f.value if income_f else None
    max_income = _dec((groups_val or {}).get("max")) if isinstance(groups_val, dict) else None
    if max_income is not None and inc > max_income:
        return {
            **base,
            "ok": False,
            "result": "over_threshold",
            "message": t.get("err_over"),
            "income": str(inc),
            "max_income": str(max_income),
            "max_income_display": _fmt_money(max_income, lang),
        }

    g, amt = income_group(inc, groups_val)
    base_amt = _dec(amt)
    if not g or base_amt is None:
        return {**base, "ok": False, "result": "input_error", "message": t.get("err_input")}

    topup = _dec((groups_val or {}).get("zwiekszenie_akademik")) if isinstance(groups_val, dict) else None
    topup_block = None
    if interested_in_dorm_topup and topup is not None:
        topup_block = {
            "amount": str(topup),
            "amount_display": _fmt_money(topup, lang),
            "included_in_total": False,
            "conditions_met": dorm_conditions_met,
            "rule": (groups_val or {}).get("zwiekszenie_akademik_rule"),
            "label": t.get("result_topup_conditional"),
        }
        # Only fold into total when conditions explicitly confirmed true
        if dorm_conditions_met is True:
            topup_block["included_in_total"] = True

    total = base_amt
    if topup_block and topup_block["included_in_total"]:
        total = (base_amt + topup).quantize(_MONEY_QUANT)
        base["dorm_topup_included"] = True
    else:
        total = base_amt

    # Entitlement is a separate question — income estimate never sets eligible=true
    profile = profile or {}
    eligibility_missing = [
        k for k in ("status", "tryb", "poziom", "drugi_kierunek")
        if k not in profile
    ]
    eligibility_result = "eligibility_unknown"
    eligibility_msg = t.get("err_eligibility") if eligibility_missing else t.get("result_not_eligibility")

    return {
        **base,
        "ok": True,
        "result": "amount_estimate",
        "income": str(inc),
        "income_group": g,
        "base_amount": str(base_amt),
        "base_amount_display": _fmt_money(base_amt, lang),
        "conditional_dorm_topup": topup_block,
        "total_display_amount": str(total),
        "total_display": _fmt_money(total, lang),
        "labels": {
            "group": t.get("result_group"),
            "base": t.get("result_base"),
            "total": t.get("result_total_base_only"),
            "not_eligibility": t.get("result_not_eligibility"),
        },
        "eligibility": "unknown",
        "eligibility_result": eligibility_result,
        "eligibility_message": eligibility_msg,
        "eligibility_missing_fields": eligibility_missing,
        "year_banner": (t.get("year_banner_confirmed") or "").format(year=year),
        "message": t.get("result_not_eligibility"),
        "fact_id": refs.get("income_and_amounts"),
    }


_SOCIAL_Q = re.compile(
    r"(?i)socjaln|social\s*scholarship|\bsocial\b.{0,30}scholarship|"
    r"стипенд\w*\s*соціал|соціальн\w*\s*стипенд|социальн\w*\s*стипенд|"
    r"pomoc\w*\s*materialn|доход.{0,20}стипенд|doch[oó]d.{0,30}stypend",
)


def looks_like_social_question(text: str, topics: list[str] | None = None) -> bool:
    if topics and "stypendium_socjalne" in topics:
        return True
    return bool(_SOCIAL_Q.search(text or ""))


def format_chat_answer(
    lang: str,
    *,
    estimate_result: dict | None = None,
    used_form_income: bool = False,
) -> dict:
    """Fully localized, no-LLM answer pointing at the verified card/estimate."""
    lang = lang if lang in ("pl", "en", "uk") else "pl"
    t = _i18n(lang)
    card = build_card(lang)
    lines = [
        t.get("chat_card_header") or "",
        "",
        card.get("intro") or "",
        "",
        f"**{card['amounts']['title']}** ({card['amounts'].get('academic_year')})",
        card["amounts"].get("year_banner") or "",
    ]
    for g in card["amounts"].get("groups") or []:
        lines.append(f"- {g['group']}: {g.get('income_range')} → {g['amount_display']}")
    dorm = card.get("dorm_topup") or {}
    if dorm.get("amount_display"):
        lines += [
            "",
            f"**{dorm.get('title')}**: {dorm['amount_display']} — {t.get('result_topup_conditional') or ''}",
        ]
        if dorm.get("rule"):
            lines.append(str(dorm["rule"])[:400])
    dl = card.get("deadlines") or {}
    if dl.get("value"):
        lines += ["", f"**{dl.get('title')}** ({dl.get('academic_year')}): {dl['value']}"]
    ch = card.get("channel") or {}
    if ch.get("value"):
        lines += ["", f"{ch.get('label')}: {ch['value']}"]
    lines += ["", t.get("chat_see_form") or ""]

    if estimate_result:
        lines += ["", "—"]
        if used_form_income:
            lines.append(t.get("chat_no_reask") or "")
        if estimate_result.get("ok"):
            lines.append(
                f"{estimate_result.get('labels', {}).get('group')}: {estimate_result.get('income_group')} → "
                f"{estimate_result.get('base_amount_display')}"
            )
            top = estimate_result.get("conditional_dorm_topup")
            if top:
                lines.append(f"{top.get('label')}: {top.get('amount_display')} (≠ total)")
            lines.append(estimate_result.get("message") or t.get("result_not_eligibility"))
        else:
            lines.append(estimate_result.get("message") or "")

    # Sources from card facts only
    sources = []
    seen = set()
    for item in (card.get("links") or {}).get("items") or []:
        url = item.get("url")
        if url and url not in seen:
            seen.add(url)
            sources.append({"n": len(sources) + 1, "title": item.get("label"), "url": url, "modified": None})

    text = "\n".join(x for x in lines if x is not None)
    # Guard: never leave placeholders
    if "{{" in text or "FACTS (" in text:
        text = t.get("chat_card_header") or "Social scholarship"
    return {
        "answer": text,
        "clarify": False,
        "mode": "scenario-social",
        "sources": sources,
        "lang": lang,
        "topics": ["stypendium_socjalne"],
        "profile": {},
        "scenario": {"id": "social_scholarship", "card": True, "estimate": estimate_result},
    }
