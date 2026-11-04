"""Polityki jakości retrieval per temat (kanoniczne źródła, boost/kara, force-hits)."""
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
            {"url": r"stypendia-socjalne", "w": 5},
            {"url": r"stypendia-socjalne", "text": r"obywatel Ukrainy|Stypendium dla cudzoziemc|ochrony czasowej", "w": 8},
            {"url": r"stypendia-socjalne", "text": r"2099|dochód na osobę|Wirtualny Dziekanat", "w": 3},
            {"url": r"Zalacznik-Nr-8-Ukraina", "w": 10, "if_pobyt": "ukr"},
            {"url": r"Zalacznik-Nr-8-Ukraina", "w": 2},
            {"url": r"R-41-2025|R-32-2024", "title": r"swiadczen|świadcze|socjal", "w": 4},
            {"text": r"obywatel Ukrainy.{0,80}stypendium socjalne", "w": 6, "if_pobyt": "ukr"},
        ],
    },
    "stypendium_rektora": {
        "prefer": ["student"],
        "query_extra": "stypendium rektora średnia ocen regulamin świadczeń",
        "query_by_status": {
            "cudzoziemiec": "stypendium rektora cudzoziemcy uprawnienia",
        },
        "boost_url": r"stypendium-rektora|stypendia-rektora|swiadczenia|świadczenia|r-41|r-32",
        "penalize_url": r"rekrutacja\.|konferenc|erasmus",
        "boost_mult": 3.0,
        "penalize_mult": 0.1,
        "canonical": r"stypendium-rektora|stypendia-rektora|swiadczenia-dla-studentow|R-41|R-32",
        "substance": r"rektor|średni|ocen|stypendi|wniosek|regulamin|cudzoziem",
        "force_rules": [
            {"url": r"stypendium-rektora|stypendia-rektora", "w": 8},
            {"url": r"swiadczenia-dla-studentow", "text": r"rektor", "w": 5},
            {"url": r"R-41-2025|R-32-2024", "title": r"swiadczen|świadcze", "w": 4},
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
    "oplaty": {
        "prefer": ["rekrutacja", "student", "bip"],
        "query_extra": "opłaty czesne wysokość opłat za usługi edukacyjne zarządzenie",
        "query_by_status": {
            "pl": "opłaty obywatel polski studia stacjonarne",
            "cudzoziemiec": "opłaty cudzoziemców rekrutacja czesne",
        },
        "boost_url": r"op[lł]at|czesne|us[lł]ugi-edukacyjne|akty-prawne-op[lł]at|wysokosc-op[lł]at|rekrutacja-cudzoziemcow-op[lł]at",
        "penalize_url": r"konferenc|monografia|isbn|mstudia|erasmus",
        "boost_mult": 2.8,
        "penalize_mult": 0.12,
        "canonical": r"op[lł]at|czesne|us[lł]ugi.edu|rekrutacja.*op[lł]at|R-\d+",
        "substance": r"op[lł]at|czesne|zł|euro|bezp[lł]atn|tuition|fee",
        "force_rules": [
            {"url": r"rekrutacja-cudzoziemcow-op[lł]at|oplaty", "w": 6},
            {"url": r"akty-prawne-op[lł]at|Wysokosc-op[lł]at|uslugi-edukacyjne", "w": 7},
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


def apply_policy_scores(sc, chunks, topics, profile):
    """Modyfikuje wektor scorerów według TOPIC_POLICY (+ lekkie reguły oplaty/plan poza tabelą)."""
    topics = set(topics or [])
    status = (profile or {}).get("status")
    pobyt = (profile or {}).get("pobyt")
    for topic in topics:
        pol = TOPIC_POLICY.get(topic)
        if not pol:
            continue
        boost_re = pol.get("boost_url")
        pen_re = pol.get("penalize_url")
        bm = pol.get("boost_mult", 2.5)
        pm = pol.get("penalize_mult", 0.1)
        for i, c in enumerate(chunks):
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
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for _, c in scored:
        if c["url"] in seen:
            continue
        seen.add(c["url"])
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
