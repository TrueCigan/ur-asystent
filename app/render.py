"""Server-side fact/computed rendering — LLM must not emit monetary digits (redesign P1)."""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

FACT_PLACEHOLDER_RE = re.compile(r"\{\{F:([a-zA-Z0-9_.]+)\}\}")
COMPUTED_PLACEHOLDER_RE = re.compile(r"\{\{C:([a-zA-Z0-9_]+)\}\}")
# Raw money in a model template (reject)
_RAW_MONEY_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"
    r"|\d{1,3}(?:[ .\u00a0]\d{3})+(?:,\d{1,2})?"
    r"|\d+[.,]\d{2}"
    r"|\d{3,5})"
    r"\s*(?:zł|zl|PLN|EUR|euro|€)",
    re.I,
)
_CITE_RE = re.compile(r"\[(?:F|Fn|FN)?(\d+)\]")


def format_amount(value: Any, unit: str | None = None, lang: str = "pl") -> str:
    """Locale amount: 5500,50 zł (pl/uk) or 5500.50 PLN (en)."""
    if value is None:
        return ""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    u = (unit or "").strip()
    currency = "PLN"
    if re.search(r"(?i)eur|€", u):
        currency = "EUR"
    elif re.search(r"(?i)zł|zl|pln", u) or not u or "/person" in u.lower() or "/month" in u.lower() or "/semester" in u.lower():
        currency = "PLN"
    # Keep one decimal place for .5 / .15 style facts
    if d == d.to_integral_value():
        num_en = f"{int(d)}"
    else:
        num_en = f"{d:.2f}".rstrip("0").rstrip(".") if "." in f"{d:.2f}" else f"{d}"
        # normalize 5500.50
        try:
            num_en = f"{Decimal(num_en):.2f}".rstrip("0").rstrip(".")
            if "." not in num_en:
                pass
            else:
                # keep two decimals when fractional
                q = Decimal(str(value))
                if q != q.to_integral_value():
                    num_en = f"{q:.2f}"
        except Exception:
            num_en = str(d)
    if lang == "en":
        suffix = f" {currency}" if currency else ""
        return f"{num_en}{suffix}".strip()
    # pl / uk: comma decimal
    num_loc = num_en.replace(".", ",")
    if currency == "EUR":
        return f"{num_loc} EUR"
    return f"{num_loc} zł"


def _fact_by_id(facts: list, fid: str):
    for f in facts or []:
        if getattr(f, "id", None) == fid:
            return f
    return None


def resolve_fact_path(facts: list, path: str) -> tuple[Any, str | None]:
    """Resolve ``fact_id`` or ``fact_id.nested.key`` → (value, unit)."""
    parts = (path or "").split(".")
    if not parts or not parts[0]:
        return None, None
    fact = _fact_by_id(facts, parts[0])
    if not fact:
        return None, None
    unit = getattr(fact, "unit", None)
    cur: Any = fact.value
    for key in parts[1:]:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None, unit
    return cur, unit


def build_computed(selected_facts: list, need: list[str] | None = None, profile: dict | None = None) -> dict[str, Decimal]:
    """Code-owned derived amounts (never LLM arithmetic)."""
    need = list(need or [])
    out: dict[str, Decimal] = {}
    by_id = {getattr(f, "id", None): f for f in (selected_facts or [])}

    def _dec(v) -> Decimal | None:
        try:
            return Decimal(str(v))
        except Exception:
            return None

    doctoral = by_id.get("doctoral_stipend_amount")
    topup_f = by_id.get("doctoral_disability_topup_monthly")
    topup = _dec(topup_f.value) if topup_f is not None else None
    if doctoral and isinstance(doctoral.value, dict):
        przed = _dec(doctoral.value.get("przed_ocena_srodokresowa"))
        po = _dec(doctoral.value.get("po_ocenie_srodokresowej"))
        # Disability top-up = disability_topup_percent_of_przed% of pre-evaluation (default 30%), NOT 37%
        pct_top = doctoral.value.get("disability_topup_percent_of_przed")
        if przed is not None and pct_top is not None:
            derived_topup = (przed * _dec(pct_top) / Decimal("100")).quantize(Decimal("0.01"))
            if topup is None:
                topup = derived_topup
            out["doctoral_disability_topup"] = derived_topup
        if topup is None:
            topup = _dec(doctoral.value.get("zwiekszenie_niepelnosprawnosc"))
        if przed is not None and topup is not None:
            out["doctoral_with_disability_przed"] = przed + topup
        if po is not None and topup is not None:
            out["doctoral_with_disability_po"] = po + topup
        if topup is not None and "doctoral_disability_topup" not in out:
            out["doctoral_disability_topup"] = topup

    social = by_id.get("social_income_threshold")
    if social and isinstance(social.value, dict):
        amounts = social.value.get("amounts") or {}
        bonus = _dec(social.value.get("zwiekszenie_akademik")) or Decimal("0")
        for g, amt in amounts.items():
            a = _dec(amt)
            if a is None:
                continue
            out[f"social_{g}_plus_dorm"] = a + bonus
            if g == "II":
                out["social_ii_plus_dorm"] = a + bonus
            out[f"social_group_{g}"] = a
        out["social_plus_dorm_bonus"] = bonus
        if "social_ii_plus_dorm" in out:
            out["social_plus_dorm"] = out["social_ii_plus_dorm"]

    # Combined social+rector cap = percent_of_professor * professor_salary (must match fact 3667)
    salary_f = by_id.get("professor_salary_monthly")
    pct_f = by_id.get("rector_social_cap_percent_of_professor")
    if salary_f is not None and pct_f is not None:
        sal = _dec(salary_f.value)
        pct = _dec(pct_f.value)
        if sal is not None and pct is not None:
            out["rector_social_cap"] = (sal * pct / Decimal("100")).quantize(Decimal("1"))

    # If caller asked for specific keys not yet filled, leave them absent (render will keep placeholder)
    if need:
        pass
    return out


def render_answer(
    template: str,
    selected_facts: list,
    computed: dict | None = None,
    lang: str = "pl",
) -> str:
    """Substitute {{F:…}} / {{C:…}} from facts + computed registry."""
    if not template:
        return ""
    computed = computed or {}

    def _fact_sub(m: re.Match) -> str:
        path = m.group(1)
        val, unit = resolve_fact_path(selected_facts, path)
        if val is None:
            return m.group(0)
        if isinstance(val, (dict, list)):
            return str(val)
        return format_amount(val, unit, lang)

    def _comp_sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in computed:
            return m.group(0)
        return format_amount(computed[name], "PLN/month", lang)

    text = FACT_PLACEHOLDER_RE.sub(_fact_sub, template)
    text = COMPUTED_PLACEHOLDER_RE.sub(_comp_sub, text)
    return text


def template_has_raw_money(template: str) -> bool:
    return bool(_RAW_MONEY_RE.search(template or ""))


def validate_answer_numbers(text: str, allowed: set[Decimal]) -> list[str]:
    """Return tokens that look like currency amounts not in ``allowed``."""
    from facts import amounts_in

    bad = amounts_in(text or "") - (allowed or set())
    return [str(x) for x in sorted(bad, key=str)]


def validate_citations(text: str, n_sources: int) -> list[str]:
    bad = []
    for m in _CITE_RE.finditer(text or ""):
        n = int(m.group(1))
        if n < 1 or n > max(0, n_sources):
            bad.append(m.group(0))
    return bad


def parse_model_json(raw: str) -> dict | None:
    """Extract a JSON object from model output; None if invalid."""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    # Accept template or prose_template
    if "template" not in data and "prose_template" in data:
        data["template"] = data["prose_template"]
    if not data.get("template"):
        return None
    return data


def fact_cards(selected_facts: list, lang: str = "pl") -> list[dict]:
    """Compact cards for the LLM prompt only (never dump into user answer)."""
    from facts import format_fact_value

    cards = []
    for f in selected_facts or []:
        label = (f.i18n_label or {}).get(lang) or (f.i18n_label or {}).get("pl") or f.id
        preview = format_fact_value(f.value, unit=f.unit or "", lang=lang)
        if len(preview) > 400:
            preview = preview[:400] + "…"
        cards.append({
            "id": f.id,
            "label": label,
            "unit": f.unit,
            "value_preview": preview,
            "paths": _list_paths(f.id, f.value),
        })
    return cards


def _list_paths(fid: str, val: Any, prefix: str = "") -> list[str]:
    base = f"{fid}.{prefix}".rstrip(".") if prefix else fid
    if isinstance(val, dict):
        out = []
        for k, v in val.items():
            if k == "note":
                continue
            out.extend(_list_paths(fid, v, f"{prefix}.{k}".lstrip(".") if prefix else k))
        return out or [fid]
    return [base if prefix else fid]
