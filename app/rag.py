"""Logika asystenta: doprecyzowanie sytuacji studenta, wyszukiwanie hybrydowe, odpowiedź z cytatami (PL)."""
import os, re, gzip, json, math, collections, numpy as np, scipy.sparse as sp, httpx
from index import tokens, norm, D, char_ngrams, char_vec

IDX = None
def load():
    global IDX
    z = np.load(os.path.join(D, "index.npz"))
    with gzip.open(os.path.join(D, "meta.json.gz"), "rt", encoding="utf-8") as f: m = json.load(f)
    bm = sp.csr_matrix((z["bm_data"], z["bm_ind"], z["bm_ptr"]), shape=tuple(z["bm_shape"])).tocsc()
    X = sp.csr_matrix((z["x_data"], z["x_ind"], z["x_ptr"]), shape=tuple(z["x_shape"]))
    IDX = dict(chunks=m["chunks"], bm=bm, X=X, cidf=z["cidf"], tvoc={t: j for j, t in enumerate(m["tvocab"])},
               cvoc={g: j for j, g in enumerate(m["cvocab"])}, emb=None)

def _bm25(q):
    w = np.zeros(IDX["bm"].shape[1], np.float32)
    for t in tokens(q):
        j = IDX["tvoc"].get(t)
        if j is not None: w[j] += 1
    return IDX["bm"] @ w

def _char(q):
    v = char_vec(collections.Counter(char_ngrams(q)), IDX["cvoc"], IDX["cidf"])
    w = np.zeros(IDX["X"].shape[1], np.float32)
    for k, x in v.items(): w[k] = x
    return IDX["X"] @ w

# ---------- wyszukiwanie hybrydowe (BM25 + wektory, fuzja RRF) ----------
def search(q, k=8, prefer=None):
    if IDX is None: load()
    ch = IDX["chunks"]; n = len(ch)
    bm = _bm25(q)
    vec = _char(q)
    ranks = [np.argsort(-bm), np.argsort(-vec)]
    if IDX.get("emb") is not None:
        from embed import embed_texts
        ranks.append(np.argsort(-(IDX["emb"] @ embed_texts([q])[0])))
    sc = np.zeros(n)
    for r in ranks:
        sc[r[:200]] += 1.0 / (60 + np.arange(1, min(200, n) + 1))
    for i, c in enumerate(ch):
        if (c["modified"] or "0") < "2024": sc[i] *= 0.6
        if prefer and c["source"] in prefer: sc[i] *= 1.6
    out, per_url = [], {}
    for i in np.argsort(-sc):
        c = ch[i]
        if per_url.get(c["url"], 0) >= 2: continue
        per_url[c["url"]] = per_url.get(c["url"], 0) + 1
        out.append(dict(c, score=float(sc[i])))
        if len(out) >= k: break
    return out

# ---------- profil studenta i doprecyzowanie ----------
SLOTS = {
 "status": ("Jaki jest Twój status: student z obywatelstwem polskim, cudzoziemiec (podaj, czy masz np. Kartę Polaka, kartę pobytu stałego/czasowego, status uchodźcy lub ochronę czasową/UKR), osoba bez obywatelstwa (bezpaństwowiec), czy doktorant/doktorantka Szkoły Doktorskiej?",
   {"bezpanstwowiec": r"bezpa[nń]stw|bez obywatel|stateless", "pl": r"\b(polak|polk[aąi]|jestem polk|obywatel\w* polsk|polskie obywatel|jestem z polski)", "cudzoziemiec": r"cudzozie|obcokraj|zagranicz|ukrai|bia[lł]oru|karta polaka|kart\w* pobytu|ochron\w* czasow|uchod[zź]", "bezpanstwowiec": r"bezpa[nń]stw|bez obywatel|stateless", "doktorant": r"jestem doktorant|doktorantk|w szko[lł]\w* doktorsk|szko[lł]\w* doktorsk"}),
 "tryb": ("Studiujesz w trybie stacjonarnym czy niestacjonarnym?", {"stacjonarne": r"(?<!nie)stacjonar|dzienn", "niestacjonarne": r"niestacjonar|zaoczn|weekend"}),
 "poziom": ("Na jakim poziomie studiujesz: I stopnia (licencjackie/inżynierskie), II stopnia (magisterskie), jednolite magisterskie czy Szkoła Doktorska?", {"II": r"\bii\s*stop|drugi\w* stop|magist(?!.*jednolit)|uzupe[lł]niaj", "I": r"\bi\s*stop|pierwsz\w* stop|licencj|in[zż]ynier", "jednolite": r"jednolit", "SD": r"doktorant|szko[lł]\w* doktorsk"}),
 "rok": ("Na którym roku studiów jesteś (pierwszy rok czy wyższy)?", {"rok": r"(\b[1-6]\s*rok|\bi+\s*rok|\bpierwsz\w* rok|\bdrugi\w* rok|\btrzeci\w* rok|\bczwart\w* rok|\bpi[aą]t\w* rok|\b(?:na|jestem na)\s+(?:i|ii|iii|iv|v)\s+roku|\bpierwszoroczn)"}),
 "drugi_kierunek": ("Czy studiujesz (lub studiowałeś/aś wcześniej) równolegle drugi kierunek albo masz już ukończone studia? To ważne, bo świadczenia przysługują co do zasady na jednym kierunku i nie przysługują po uzyskaniu tytułu danego poziomu.", {"tak": r"(drugi\w* kierun\w*|dw[ao]\w* kierun\w*|r[oó]wnoleg[lł]\w*|ju[zż] (mam|uko[nń]czy)\w*|mam (tytu[lł]|licencjat|dyplom))", "nie": r"(jedyn\w* kierun|jeden kierun|tylko jed\w* kierun|nie studiuj\w* (r[oó]wnoleg|drug)|pierwsz\w* studi|nie mam (innego|drugiego|uko))"}),
 "niepelnosprawnosc": ("Czy posiadasz orzeczenie o niepełnosprawności (lub stopniu niepełnosprawności)?", {"tak": r"(mam orzeczenie|z niepe[lł]nosprawno|orzeczen\w* o (niepe|stop))", "nie": r"(nie mam orzecz|bez orzecz|nie jestem (osob\w* )?niepe[lł]no)"}),
 "kierunek": ("Jaki kierunek, rok i grupę (lub specjalność) studiujesz? Podaj np. „Informatyka, I stopień, 1 rok, stacjonarne”.", {"kierunek": r"informaty|elektrotechn|transport|ekonom|prawo|piel[eę]g|medycy|pedagog|mechani|logisty|filolog|filozof|socjolog|turysty|kosmetolog"}),
}
TOPICS = [
 ("stypendium_socjalne", r"socjaln|zapomog|dochod|pomoc\w* materialn|[sś]wiadcze", ["status", "drugi_kierunek", "tryb", "poziom"]),
 ("stypendium_rektora", r"rektor|najlepsz|[sś]redni\w* ocen", ["status", "drugi_kierunek", "poziom", "rok"]),
 ("stypendium_niepeln", r"niepe[lł]nospraw", ["status", "niepelnosprawnosc", "drugi_kierunek"]),
 ("doktoranckie", r"doktorant|doktorsk|doktoranck", ["status"]),
 ("oplaty", r"op[lł]at|czesne|ile kosztuj|p[lł]aci[cć]|bezp[lł]atn", ["status", "tryb", "poziom"]),
 ("erasmus", r"erasmus|wyjazd|wymian|mobilno", ["status", "poziom", "rok"]),
 ("plan", r"plan\w* zaj|rozk[lł]ad|harmonogram zaj|zaj[eę]cia w|kiedy mam zaj", ["kierunek", "tryb"]),
 ("cudzoziemcy", r"cudzozie|bezpa[nń]stw|bez obywatel|karta polaka|kart\w* pobytu|legaliz|wiz\w*\b|ochron\w* czasow", ["status"]),
 ("dwa_kierunki", r"dw[ao]\w* kierun|drugi\w* kierun|r[oó]wnoleg", ["status", "drugi_kierunek", "tryb"]),
]

def extract_profile(text):
    t = norm(text) if False else text.lower()
    prof = {}
    for slot, (_, opts) in SLOTS.items():
        for val, rx in opts.items():
            if re.search(rx, t, re.I): prof[slot] = val; break
    if prof.get("status") == "doktorant": prof.setdefault("poziom", "SD"); prof.setdefault("tryb", "stacjonarne"); prof.setdefault("rok", "rok")
    if prof.get("poziom") == "SD": prof.setdefault("status_doktor", True)
    if re.search(r"drugi\w* kierun|dw[ao]\w* kierun|r[oó]wnoleg", t) and re.search(r"czy (mog|moż)", t): prof.setdefault("drugi_kierunek", "pytanie")
    return prof

def needed(question, history_text):
    q = question.lower()
    topics = [(n, s) for n, rx, s in TOPICS if re.search(rx, q, re.I)]
    if not topics:  # kontynuacja – szukaj tematu w historii
        topics = [(n, s) for n, rx, s in TOPICS if re.search(rx, history_text.lower(), re.I)][:1]
    req = []
    for _, s in topics:
        for x in s:
            if x not in req: req.append(x)
    prof = extract_profile(history_text + "\n" + question)
    if prof.get("status") == "doktorant":
        req = [x for x in req if x not in ("tryb", "poziom", "rok", "kierunek")]
    missing = [x for x in req if x not in prof]
    return [n for n, _ in topics], prof, missing

SYSTEM = """Jesteś asystentem informacyjnym dla studentów Uniwersytetu Radomskiego im. Kazimierza Pułaskiego (UR).
ZASADY (bezwzględne):
1. Odpowiadasz ZAWSZE po polsku, niezależnie od języka pytania.
2. Odpowiadasz WYŁĄCZNIE na podstawie fragmentów źródeł podanych w sekcji ŹRÓDŁA. Nie korzystasz z wiedzy ogólnej. Jeśli w źródłach brak informacji – napisz wprost: „W zindeksowanych materiałach UR nie znalazłem informacji na ten temat” i wskaż, gdzie warto zapytać (Biuro Obsługi Studenta, Dział Współpracy Zagranicznej, Szkoła Doktorska).
3. Każde twierdzenie opierasz na źródle i cytujesz je w formacie [n]. Na końcu podajesz listę „Źródła:” z adresem URL i datą ostatniej aktualizacji strony.
4. Ostrzeżenie „⚠️ informacja może być nieaktualna (strona z dnia …)” dodawaj WYŁĄCZNIE dla źródeł z datą wcześniejszą niż 2024-01-01 lub bez daty (pole „nieaktualne: TAK”). Źródeł z 2024 r. i później NIE oznaczaj jako nieaktualne. Kwoty, terminy i progi dochodowe podawaj tylko, gdy są w źródle, i zawsze wskaż, którego roku akademickiego/zarządzenia dotyczą (np. „wg zarządzenia R-41/2025”). Dzisiejsza data: {today}. Jeśli termin ze źródła już minął, napisz to wyraźnie.
8. W liście „Źródła:” każdy URL podaj tylko raz (z datą aktualizacji). Nie wymyślaj numerów źródeł, których nie ma w sekcji ŹRÓDŁA.
5. DOPRECYZOWANIE: zasady różnią się w zależności od sytuacji studenta (obywatelstwo/status cudzoziemca lub bezpaństwowca, Szkoła Doktorska, tryb stacjonarny/niestacjonarny, poziom i rok studiów, studiowanie równolegle drugiego kierunku lub posiadanie dyplomu, niepełnosprawność, kierunek/grupa). Jeżeli odpowiedź od tego zależy, a w PROFILU STUDENTA brakuje potrzebnych danych, NIE odpowiadaj merytorycznie – najpierw zadaj krótkie, ponumerowane pytania doprecyzowujące (tylko te potrzebne), a odpowiedz po otrzymaniu odpowiedzi.
6. Gdy różne kategorie studentów mają różne zasady, opisz zasady tylko dla kategorii użytkownika; ewentualne wyjątki zaznacz krótko.
7. Nie udzielasz porad prawnych; w sprawach indywidualnych odsyłasz do właściwej jednostki UR. Nie zmyślaj adresów URL."""

def fmt_sources(hits):
    out = []
    for n, h in enumerate(hits, 1):
        out.append(f"[{n}] {h['title']} | URL: {h['url']} | aktualizacja: {h['modified'] or 'brak daty'} | nieaktualne: {'TAK' if outdated(h['modified']) else 'nie'}\n{h['text'][:1500]}")
    return "\n\n".join(out)

def outdated(m): return (not m) or m[:4] < "2024"

def call_llm(messages):
    prov = os.getenv("LLM_PROVIDER", "").lower(); key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")
    if prov == "gemini":
        import time
        key = os.getenv("GEMINI_API_KEY") or key
        chain = [m for m in [model, "gemini-3.5-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"] if m]
        last = None
        for m in dict.fromkeys(chain):
            for att in range(4):
                try:
                    r = httpx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", timeout=90,
                                   headers={"Authorization": f"Bearer {key}"},
                                   json={"model": m, "messages": messages, "temperature": 0.1, "reasoning_effort": "low"})
                except httpx.TimeoutException as e:
                    last = e; break
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
                last = f"{m}: HTTP {r.status_code}"
                if r.status_code == 429: time.sleep(min(60, 5 * 2 ** att)); continue
                if r.status_code in (500, 503) and att < 1: time.sleep(4); continue
                break  # 404/400/powtarzające się 503 -> następny model
        raise RuntimeError(f"Gemini niedostępny ({last})")
    if prov == "anthropic":
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=120,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": model or "claude-sonnet-4-5", "max_tokens": 1200, "system": messages[0]["content"], "messages": messages[1:]})
        r.raise_for_status(); return r.json()["content"][0]["text"]
    base = {"openai": "https://api.openai.com/v1", "xai": "https://api.x.ai/v1", "ollama": "http://localhost:11434/v1"}.get(prov) or os.getenv("LLM_BASE_URL")
    base = os.getenv("LLM_BASE_URL", base)
    r = httpx.post(base + "/chat/completions", timeout=120, headers={"Authorization": f"Bearer {key}"},
                   json={"model": model or "gpt-4o-mini", "messages": messages, "temperature": 0.1})
    r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]

def llm_enabled():
    p = os.getenv("LLM_PROVIDER", "").lower()
    if p == "gemini": return bool(os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY"))
    return bool(p) and (bool(os.getenv("LLM_API_KEY")) or p == "ollama")

PROF_PL = {"status": "status", "tryb": "tryb", "poziom": "poziom", "rok": "rok", "drugi_kierunek": "drugi kierunek / dyplom", "niepelnosprawnosc": "orzeczenie o niepełnosprawności", "kierunek": "kierunek/grupa"}

def answer(question, history):
    """history: lista {'role','content'}; zwraca dict(answer, sources, mode, clarify)"""
    hist_user = "\n".join(m["content"] for m in history if m["role"] == "user")
    topics, prof, missing = needed(question, hist_user)
    if missing:  # deterministyczna bramka doprecyzowania (działa także bez LLM)
        qs = "\n".join(f"{i}. {SLOTS[m][0]}" for i, m in enumerate(missing, 1))
        return dict(clarify=True, mode="doprecyzowanie", sources=[], profile=prof,
            answer=f"Zanim odpowiem – zasady na UR zależą od Twojej sytuacji. Proszę, doprecyzuj:\n{qs}\n\nMożesz odpowiedzieć jednym zdaniem, np. „cudzoziemiec z kartą pobytu stałego, stacjonarne, I stopień, 2 rok, jeden kierunek”.")
    # zapytanie wyszukiwania = bieżące pytanie + ostatnie pytanie merytoryczne z historii (kontynuacja)
    base_q = question
    if history:
        prev = [m["content"] for m in history if m["role"] == "user" and any(re.search(rx, m["content"], re.I) for _, rx, _ in TOPICS)]
        if prev: base_q = prev[-1] + " " + question
    q = base_q + " " + " ".join(str(v) for k, v in prof.items() if k in ("status",) and v in ("cudzoziemiec", "bezpanstwowiec", "doktorant"))
    PREF = {"plan": ["wteii"], "erasmus": ["dwz"], "cudzoziemcy": ["rekrutacja", "dwz", "student"], "oplaty": ["rekrutacja", "student"],
            "doktoranckie": ["student"], "stypendium_socjalne": ["student"], "stypendium_rektora": ["student"], "dwa_kierunki": ["student"]}
    tp = [t for t in topics if t != "cudzoziemcy"] or topics
    prefer = sorted({x for t in tp for x in PREF.get(t, [])})
    if tp is not topics: q = re.sub(r"(?i)\b(jako\s+)?cudzoziem\w*", " ", q)
    hits = search(q, k=8, prefer=prefer)
    if "plan" in topics:
        files = sorted({(c["title"], c["url"], c["modified"]) for c in IDX["chunks"] if c["source"] == "wteii" and c["kind"] == "file"})
        lst = "\n".join(f"- {t.split(' – ')[-1]} → {u} (aktualizacja: {m})" for t, u, m in files)
        hits = [dict(title="WTEiI – lista plików z planami zajęć (nazwa pliku = kod kierunku: IN=Informatyka, IT, E=Elektrotechnika, TiL/TIL=Transport i logistyka; _I/_II/_III/_IV lub R1–R4 = rok; _all = niestacjonarne/zjazdy)",
                     url="https://wteii.uniwersytetradom.pl/plany-zajec/", modified=max(f[2] or "" for f in files) or None, text=lst, source="wteii", kind="list")] + hits[:6]
    srcs = [dict(n=i, title=h["title"], url=h["url"], modified=h["modified"], outdated=outdated(h["modified"]), snippet=h["text"][:400]) for i, h in enumerate(hits, 1)]
    prof_txt = ", ".join(f"{PROF_PL.get(k,k)}: {v}" for k, v in prof.items() if k in PROF_PL) or "brak danych"
    if llm_enabled():
        import datetime
        msgs = [{"role": "system", "content": SYSTEM.replace("{today}", datetime.date.today().isoformat())}] + history[-8:] + [{"role": "user", "content":
                f"PROFIL STUDENTA (z rozmowy): {prof_txt}\n\nŹRÓDŁA:\n{fmt_sources(hits)}\n\nPYTANIE: {question}"}]
        try:
            return dict(clarify=False, mode="llm", sources=srcs, profile=prof, answer=call_llm(msgs))
        except Exception as e:
            err = f"(Błąd LLM: {e}. Pokazuję tryb wyszukiwania.)\n\n"
    else:
        err = ""
    # tryb bez LLM: ekstrakcyjny
    lines = [err + f"**Tryb bez modelu językowego** – poniżej najtrafniejsze fragmenty z oficjalnych stron UR (profil: {prof_txt}). Zweryfikuj szczegóły w źródle:"]
    for s, h in zip(srcs[:4], hits[:4]):
        warn = " ⚠️ informacja może być nieaktualna" if s["outdated"] else ""
        snip = re.sub(r"\s+", " ", h["text"])[:500]
        lines.append(f"\n[{s['n']}] **{s['title']}** (aktualizacja: {s['modified'] or 'brak daty'}{warn})\n„{snip}…”")
    lines.append("\nŹródła:\n" + "\n".join(f"[{s['n']}] {s['url']} – {s['modified'] or 'brak daty'}" for s in srcs[:4]))
    return dict(clarify=False, mode="wyszukiwanie", sources=srcs, profile=prof, answer="\n".join(lines))
