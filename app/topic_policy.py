"""Polityki jakości retrieval per temat (kanoniczne źródła, boost/kara, force-hits)."""
import os
import re

TOPIC_POLICY = {
    "stypendium_socjalne": {
        "prefer": ["student"],
        "query_extra": "stypendium socjalne regulamin świadczeń student",
        "query_by_pobyt": {
            "ukr": "obywatel Ukrainy ochrona czasowa oświadczenie załącznik Nr 8",
        },
        "query_by_status": {
            "cudzoziemiec": "stypendium dla cudzoziemców uprawnienia świadczenia",
        },
        "boost_url": r"stypendia-socjalne|swiadczenia|świadczenia|r-41|r-32|pomoc-materialn",
        "penalize_url": r"rekrutacja\.|konferenc|monografia",
        "boost_mult": 3.0,
        "penalize_mult": 0.08,
        "canonical": r"stypendia-socjalne|swiadczenia-dla-studentow|R-41-2025|R-32-2024|Zalacznik-Nr-8-Ukraina",
        "substance": r"stypendi|dochód|2099|wniosek|oświadczen|Ukrain|socjaln|zł|Wirtualny",
        "force_rules": [
            {"url": r"stypendia-socjalne", "text": r"2099", "w": 20},
            {"url": r"stypendia-socjalne", "text": r"Wirtualny Dziekanat", "w": 12},
            {"url": r"stypendia-socjalne", "text": r"obywatel Ukrainy.{0,120}(stypendium socjalne|ochrony czasowej)|O stypendium socjalne.{0,80}cudzoziem", "w": 18},
            {"url": r"stypendia-socjalne", "text": r"Stypendium dla cudzoziemc", "w": 10},
            {"url": r"stypendia-socjalne", "w": 4},
            {"url": r"Zalacznik-Nr-8-Ukraina", "w": 16, "if_pobyt": "ukr"},
            {"url": r"Zalacznik-Nr-8-Ukraina", "w": 2},
            {"url": r"R-41-2025|R-32-2024", "title": r"swiadczen|świadcze|socjal", "w": 4},
            {"url": r"R-32-2024", "text": r"Ukrain|ochrony czasowej|cudzoziem", "w": 8},
        ],
    },
    "stypendium_rektora": {
        "prefer": ["student"],
        "query_extra": "stypendium rektora średnia ocen regulamin świadczeń wniosek",
        "query_by_status": {
            "cudzoziemiec": "stypendium rektora cudzoziemcy uprawnienia",
            "pl": "stypendium rektora średnia ocen",
        },
        "query_by_pobyt": {
            "ukr": "stypendium rektora cudzoziemcy Ukraina",
        },
        "boost_url": r"stypendium-rektora|stypendia-rektora|Stypendium-Rektora",
        "penalize_url": r"rekrutacja\.|konferenc|erasmus|stypendia-socjalne|Zalacznik-Nr-8-Ukraina",
        "boost_mult": 4.0,
        "penalize_mult": 0.05,
        "canonical": r"stypendium-rektora|stypendia-rektora|Stypendium-Rektora",
        "substance": r"rektor|średni|ocen|stypendi|wniosek|regulamin|cudzoziem|ranking",
        "force_rules": [
            {"url": r"stypendium-rektora|stypendia-rektora", "w": 20},
            {"url": r"Stypendium-Rektora", "w": 18},
            {"url": r"swiadczenia-dla-studentow", "text": r"stypendium Rektora|Stypendium rektora", "w": 8},
            {"url": r"R-41-2025|R-32-2024", "text": r"rektor", "w": 6},
        ],
    },
    "stypendium_niepeln": {
        "prefer": ["student"],
        "query_extra": "stypendium dla osób niepełnosprawnych orzeczenie świadczenia",
        "boost_url": r"niepe[lł]nospraw|swiadczenia|świadczenia|stypend",
        "penalize_url": r"rekrutacja\.|konferenc",
        "boost_mult": 3.0,
        "penalize_mult": 0.1,
        "canonical": r"niepe[lł]nospraw|swiadczenia-dla-studentow",
        "substance": r"niepe[lł]nospraw|orzeczen|stypendi|wniosek",
        "force_rules": [
            {"url": r"niepe[lł]nospraw", "w": 8},
            {"url": r"swiadczenia-dla-studentow", "text": r"niepe[lł]nospraw", "w": 6},
        ],
    },
    "doktoranckie": {
        "prefer": ["student"],
        "query_extra": "stypendium doktoranckie szkoła doktorska wysokość",
        "boost_url": r"doktoranc|doktorsk|szkola-doktorsk|szko[lł]a-doktorsk",
        "penalize_url": r"rekrutacja\.|czesne|konferenc",
        "boost_mult": 3.0,
        "penalize_mult": 0.12,
        "canonical": r"doktoranc|doktorsk|szkola-doktorsk|szko[lł]a",
        "substance": r"doktorant|stypendi|szko[lł]a doktorsk|zł|wysoko",
        "force_rules": [
            {"url": r"doktoranc|doktorsk", "w": 8},
            {"title": r"doktoranc|doktorsk|Szko[lł]a Doktorsk", "w": 5},
        ],
    },
    "akademik": {
        "prefer": ["student"],
        "query_extra": "domy studenckie akademik opłaty za miejsce termin wniosków",
        "boost_url": r"domy-studenckie|akademik|internet-w-akademikach",
        "penalize_url": r"rekrutacja\.|czesne|stypendia-socjalne|konferenc",
        "boost_mult": 3.5,
        "penalize_mult": 0.08,
        "canonical": r"domy-studenckie|akademik",
        "substance": r"akademik|dom\w*\s*studen|zł|opłat|miejsce|termin|wniosek",
        "force_rules": [
            {"url": r"domy-studenckie", "w": 20},
            {"url": r"akademik", "w": 10},
            {"title": r"Domy studenckie|akademik", "w": 8},
        ],
    },
    "oplaty": {
        "prefer": ["rekrutacja", "student", "bip"],
        "query_extra": "opłaty czesne wysokość opłat za usługi edukacyjne zarządzenie R-8/2026",
        "query_by_status": {
            "pl": "opłaty obywatel polski studia niestacjonarne R-08-2026",
            "cudzoziemiec": "opłaty cudzoziemców rekrutacja czesne english programme",
        },
        "boost_url": r"op[lł]at|czesne|R-0?8-2026|rekrutacja-cudzoziemcow-op[lł]at|us[lł]ugi-edukacyjne",
        "penalize_url": r"konferenc|monografia|isbn|mstudia|erasmus|2018|2019-20|R-38-2020",
        "boost_mult": 2.8,
        "penalize_mult": 0.12,
        "canonical": r"R-0?8-2026|rekrutacja.*op[lł]at|czesne|op[lł]at",
        "substance": r"op[lł]at|czesne|zł|euro|bezp[lł]atn|tuition|fee",
        "force_rules": [
            {"url": r"R-0?8-2026", "w": 10},
            {"url": r"rekrutacja-cudzoziemcow-op[lł]at|oplaty", "w": 6},
            {"url": r"uslugi-edukacyjne|wysokosc-op[lł]at", "w": 4},
            {"title": r"wysokość opłat|usługi edukacyjne|opłaty", "w": 4},
        ],
    },
    "erasmus": {
        "prefer": ["dwz"],
        "query_extra": "Erasmus+ wymiana mobilność wyjazd rekrutacja studenci",
        "boost_url": r"dwz\.|erasmus|mobilno|wymian",
        "penalize_url": r"stypendia-socjalne|stypendium-rektora|konferenc",
        "boost_mult": 3.2,
        "penalize_mult": 0.15,
        "canonical": r"dwz\.uniwersytetradom\.pl|erasmus",
        "substance": r"Erasmus|mobilno|wymian|wyjazd|stypendi|aplikac|dokument",
        "force_rules": [
            {"url": r"dwz\.uniwersytetradom\.pl", "title": r"Erasmus|mobilno|wymian|wyjazd", "w": 8},
            {"url": r"erasmus", "w": 6},
            {"source": "dwz", "title": r"Erasmus", "w": 5},
        ],
    },
    "plan": {
        "prefer": None,  # ustawiane dynamicznie
        "query_extra": "plan zajęć rozkład harmonogram",
        "boost_url": r"plany-zajec|plan-zajec",
        "penalize_url": r"bip\.|plan\s*studi|program\s*studi|uchwa",
        "boost_mult": 2.5,
        "penalize_mult": 0.08,
        "canonical": r"plany-zajec|plan-zajec|wteii\.|weif\.|wpia\.|wm\.|wnminoz\.|wfp\.",
        "substance": r"plan|zaj[eę]ć|rozk[lł]ad|pdf|wydzia",
        "force_rules": [],
    },
    "cudzoziemcy": {
        "prefer": ["rekrutacja", "dwz", "student"],
        "query_extra": "cudzoziemcy rekrutacja dokumenty karta pobytu",
        "boost_url": r"rekrutacja-cudzoziemcow|cudzoziem",
        "penalize_url": r"konferenc|erasmus.*lista",
        "boost_mult": 2.5,
        "penalize_mult": 0.2,
        "canonical": r"rekrutacja-cudzoziemcow|rekrutacja\.uniwersytetradom",
        "substance": r"cudzoziem|dokument|rekrutacj|pobyt|opłat|wiz",
        "force_rules": [
            {"url": r"rekrutacja-cudzoziemcow", "w": 7},
        ],
    },
    "dwa_kierunki": {
        "prefer": ["student"],
        "query_extra": "drugi kierunek świadczenia jeden kierunek regulamin",
        "boost_url": r"swiadczenia|świadczenia|stypend|regulamin",
        "penalize_url": r"rekrutacja\.|konferenc",
        "boost_mult": 2.5,
        "penalize_mult": 0.12,
        "canonical": r"swiadczenia-dla-studentow|stypendia|regulamin",
        "substance": r"kierun|świadcze|stypendi|jedn\w*\s*kierun|równoleg",
        "force_rules": [
            {"url": r"swiadczenia-dla-studentow", "text": r"kierun|jednym kierunku|równoleg", "w": 7},
            {"url": r"stypendia-socjalne", "text": r"kierun", "w": 4},
        ],
    },
}


def policy_for(topic: str) -> dict:
    return TOPIC_POLICY.get(topic) or {}


_CORPUS_CACHE: dict | None = None


def load_corpus_policy() -> dict:
    global _CORPUS_CACHE
    if _CORPUS_CACHE is not None:
        return _CORPUS_CACHE
    try:
        import yaml
        path = os.path.join(os.path.dirname(__file__), "..", "data", "corpus_policy.yaml")
        _CORPUS_CACHE = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception:
        _CORPUS_CACHE = {}
    return _CORPUS_CACHE


def is_denied_chunk(chunk: dict, topics: set | None = None) -> bool:
    """Hard exclude conference/staff-mobility / superseded fee docs (R5-9)."""
    pol = load_corpus_policy()
    url = (chunk.get("url") or "")
    title = (chunk.get("title") or "")
    blob = f"{url} {title}"
    for sub in pol.get("deny_url_substrings") or []:
        if sub and sub.lower() in blob.lower():
            return True
    for sub in pol.get("deny_title_substrings") or []:
        if sub and sub.lower() in title.lower():
            return True
    by_topic = pol.get("deny_url_substrings_for_topic") or {}
    for t in topics or []:
        for sub in by_topic.get(t) or []:
            if sub and sub.lower() in url.lower():
                return True
    return False


def normalize_query(q: str) -> str:
    """Typos + lowercase helpers before BM25 (R5-9)."""
    if not q:
        return q
    out = q
    typos = (load_corpus_policy().get("typo_map") or {})
    for bad, good in typos.items():
        out = re.sub(rf"(?i)\b{re.escape(bad)}\b", good, out)
    # light: jedno → 1 for year/person noise
    out = re.sub(r"(?i)\bjedno\b", "1", out)
    return out


def apply_policy_scores(sc, chunks, topics, profile):
    """Modyfikuje wektor scorerów według TOPIC_POLICY (+ lekkie reguły oplaty/plan poza tabelą)."""
    topics = set(topics or [])
    status = (profile or {}).get("status")
    pobyt = (profile or {}).get("pobyt")
    # Hard deny → score ~0
    for i, c in enumerate(chunks):
        if is_denied_chunk(c, topics):
            sc[i] *= 0.0
            continue
        # Recency boost for ≥2025
        mod = (c.get("modified") or "")[:4]
        if mod >= "2025":
            sc[i] *= 1.15
    for topic in topics:
        pol = TOPIC_POLICY.get(topic)
        if not pol:
            continue
        boost_re = pol.get("boost_url")
        pen_re = pol.get("penalize_url")
        bm = pol.get("boost_mult", 2.5)
        pm = pol.get("penalize_mult", 0.1)
        for i, c in enumerate(chunks):
            if sc[i] == 0:
                continue
            title = (c.get("title") or "").lower()
            url = (c.get("url") or "").lower()
            blob = title + " " + url
            if pen_re and re.search(pen_re, blob, re.I):
                sc[i] *= pm
            if boost_re and re.search(boost_re, blob, re.I):
                sc[i] *= bm
            if topic == "stypendium_socjalne" and pobyt == "ukr":
                text = (c.get("text") or "")[:800]
                if re.search(r"ukrain|ukr|za[lł][aą]cznik|ochron\w*\s*czasow|cudzoziem", title + " " + text, re.I):
                    sc[i] *= 2.0
            if topic == "oplaty":
                text = (c.get("text") or "")[:1500]
                if re.search(r"usługi edukacyjne|wysokość opłat|akty-prawne-opłat|opłaty\b", title):
                    sc[i] *= 1.4
                if re.search(r"\br-\d{1,3}-\d{4}\b", title) and re.search(r"\d[\d\s]*zł", text, re.I):
                    sc[i] *= 1.5
                if "cudzoziem" in title:
                    sc[i] *= 2.2 if status == "cudzoziemiec" else (0.25 if status == "pl" else 1.0)
                elif status == "pl" and re.search(r"\d[\d\s]*zł", text, re.I) and re.search(r"opłat|czesne|r-\d+", title):
                    sc[i] *= 1.5
    return sc


def force_topic_hits(topic, profile=None, k=4, chunks=None):
    """Wybierz kanoniczne fragmenty dla tematu."""
    pol = TOPIC_POLICY.get(topic) or {}
    rules = pol.get("force_rules") or []
    if not rules or chunks is None:
        return []
    pobyt = (profile or {}).get("pobyt")
    scored = []
    for c in chunks:
        url = c.get("url") or ""
        title = c.get("title") or ""
        text = c.get("text") or ""
        source = c.get("source") or ""
        score = 0
        for rule in rules:
            if rule.get("if_pobyt") and pobyt != rule["if_pobyt"]:
                continue
            ok = True
            if "url" in rule and not re.search(rule["url"], url, re.I):
                ok = False
            if ok and "title" in rule and not re.search(rule["title"], title, re.I):
                ok = False
            if ok and "text" in rule and not re.search(rule["text"], text, re.I):
                ok = False
            if ok and "source" in rule and source != rule["source"]:
                ok = False
            if ok:
                score += rule.get("w", 1)
        if score:
            scored.append((score, c))
    def _rich(c):
        t = c.get("text") or ""
        return (
            3 if re.search(r"2099", t) else 0,
            2 if re.search(r"obywatel Ukrainy|ochrony czasowej|Wirtualny Dziekanat", t, re.I) else 0,
            len(t),
        )

    scored.sort(key=lambda x: (-x[0], -_rich(x[1])[0], -_rich(x[1])[1], -_rich(x[1])[2]))
    out, per_url = [], {}
    for _, c in scored:
        u = c["url"]
        n = per_url.get(u, 0)
        if n >= 2:
            continue
        # 2. chunk tego URL tylko gdy wnosi 2099 / Ukraina, a pierwszego tego nie ma
        if n == 1:
            prev = next(h for h in out if h["url"] == u)
            t_new, t_old = c.get("text") or "", prev.get("text") or ""
            adds_2099 = re.search(r"2099", t_new) and not re.search(r"2099", t_old)
            adds_ukr = re.search(r"obywatel Ukrainy|ochrony czasowej", t_new, re.I) and not re.search(
                r"obywatel Ukrainy|ochrony czasowej", t_old, re.I
            )
            if not (adds_2099 or adds_ukr):
                continue
        per_url[u] = n + 1
        out.append(c)
        if len(out) >= k:
            break
    return out


def hits_match_canonical(hits, topic) -> bool:
    pol = TOPIC_POLICY.get(topic) or {}
    can = pol.get("canonical")
    if not can:
        return True
    blob = " ".join((h.get("url") or "") + " " + (h.get("title") or "") for h in hits)
    return bool(re.search(can, blob, re.I))


def query_extras(topics, profile) -> str:
    parts = []
    for t in topics:
        pol = TOPIC_POLICY.get(t) or {}
        if pol.get("query_extra"):
            parts.append(pol["query_extra"])
        qb = pol.get("query_by_pobyt") or {}
        if profile.get("pobyt") in qb:
            parts.append(qb[profile["pobyt"]])
        qs = pol.get("query_by_status") or {}
        if profile.get("status") in qs:
            parts.append(qs[profile["status"]])
    return " ".join(parts)


def prefer_sources(topics, fac=None):
    prefer = set()
    for t in topics:
        if t == "cudzoziemcy":
            continue
        pol = TOPIC_POLICY.get(t) or {}
        pref = pol.get("prefer")
        if t == "plan":
            if fac:
                prefer.add(fac)
            else:
                prefer.update(["wteii", "weif", "wm", "wpia", "wnminoz", "wfp"])
        elif pref:
            prefer.update(pref)
    return sorted(prefer)
