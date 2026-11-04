"""Logika asystenta: doprecyzowanie sytuacji studenta, wyszukiwanie hybrydowe, odpowiedź z cytatami (PL/EN/UK/MN)."""
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

# ---------- język (PL / EN / UK / MN) ----------
LANG_NAME = {"pl": "polski", "en": "English", "uk": "українська", "mn": "монгол"}

def detect_lang(*parts):
    text = "\n".join(p for p in parts if p) or ""
    if re.search(r"[өүӨҮ]", text): return "mn"
    if re.search(r"[іїєґІЇЄҐ]", text): return "uk"
    if re.search(r"[а-яА-ЯёЁ]", text):
        if re.search(r"тэтгэлэг|оюутан|суралц|төлбөр|иргэн|мэргэжил|докторант", text, re.I): return "mn"
        return "uk"
    if re.search(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", text): return "pl"
    if re.search(r"\b(the|and|how|what|when|where|scholarship|tuition|fees?|i'?m|i am|full[- ]time|part[- ]time|bachelor|master'?s?|phd|doctoral|citizen|foreign)\b", text, re.I): return "en"
    if re.search(r"\b(jak|czy|stypendium|opłat|jestem|studiuj|cudzoziem|rektor|zajęć)\b", text, re.I): return "pl"
    if re.search(r"\b(як|чи|стипенд|оплат|громадян|інозем|навчан)\b", text, re.I): return "uk"
    return "pl"

# ---------- profil studenta i doprecyzowanie (PL/EN/UK/MN) ----------
SLOT_Q = {
 "status": {
  "pl": "Jaki jest Twój status: obywatel Polski, cudzoziemiec (np. Karta Polaka, karta pobytu, uchodźca/ochrona UKR), bezpaństwowiec, czy doktorant Szkoły Doktorskiej?",
  "en": "What is your status: Polish citizen, international student (e.g. Pole’s Card, residence permit, refugee/UKR temporary protection), stateless person, or doctoral student?",
  "uk": "Який ваш статус: громадянин Польщі, іноземець (напр. Карта поляка, карта побуту, біженець/тимчасовий захист UKR), особа без громадянства чи докторант?",
  "mn": "Таны статус юу вэ: Польш иргэн, гадаадын оюутан (ж.нь. Польшийн карт, оршин суух зөвшөөрөл, дүрвэгч/UKR), харьяалалгүй хүн, эсвэл докторант уу?",
 },
 "tryb": {
  "pl": "Studiujesz stacjonarnie czy niestacjonarnie?",
  "en": "Do you study full-time or part-time?",
  "uk": "Ви навчаєтесь на денній (стаціонар) чи заочній формі?",
  "mn": "Та өдрийн (бүтэн цагийн) эсвэл эчнээ (цагийн) хэлбэрээр суралцдаг уу?",
 },
 "poziom": {
  "pl": "Poziom: I stopień (licencjat/inżynier), II stopień (magister), jednolite magisterskie czy Szkoła Doktorska?",
  "en": "Level: first-cycle (bachelor/engineer), second-cycle (master), long-cycle master’s, or doctoral school?",
  "uk": "Рівень: І ступінь (бакалавр/інженер), ІІ ступінь (магістр), єдиний магістерський чи докторантура?",
  "mn": "Түвшин: I зэрэг (бакалавр/инженер), II зэрэг (магистр), нэгдсэн магистр, эсвэл докторантур уу?",
 },
 "rok": {
  "pl": "Na którym roku studiów jesteś?",
  "en": "Which year of study are you in?",
  "uk": "На якому ви році навчання?",
  "mn": "Та хэд дэх курст суралцаж байна вэ?",
 },
 "drugi_kierunek": {
  "pl": "Czy studiujesz równolegle drugi kierunek albo masz już ukończone studia tego poziomu? (świadczenia zwykle tylko na jednym kierunku)",
  "en": "Are you studying a second programme in parallel, or have you already completed a degree at this level? (benefits usually cover one programme)",
  "uk": "Чи навчаєтесь паралельно на другому напрямі або вже маєте диплом цього рівня? (виплати зазвичай лише на одному напрямі)",
  "mn": "Та зэрэгцээ хоёр мэргэжил сурдаг уу, эсвэл энэ түвшний дипломтой юу? (тэтгэлэг ихэвчлэн нэг мэргэжилд)",
 },
 "niepelnosprawnosc": {
  "pl": "Czy masz orzeczenie o niepełnosprawności?",
  "en": "Do you have a disability certificate / official disability ruling?",
  "uk": "Чи маєте посвідчення/висновок про інвалідність?",
  "mn": "Танд хөгжлийн бэрхшээлийн гэрчилгээ/шийдвэр бий юу?",
 },
 "kierunek": {
  "pl": "Podaj kierunek, stopień, rok i tryb (np. Informatyka, I stopień, 1 rok, stacjonarne).",
  "en": "Give your programme, level, year and mode (e.g. Computer Science, bachelor, year 1, full-time).",
  "uk": "Вкажіть напрям, рівень, рік і форму (напр. Інформатика, І ступінь, 1 рік, денна).",
  "mn": "Мэргэжил, түвшин, курс, хэлбэрээ бичнэ үү (ж.нь. Информатик, I зэрэг, 1-р курс, өдрийн).",
 },
}

SLOT_OPTS = {
 "status": [
  ("doktorant", r"doktorant|doktoranc|doctoral\s*school|phd\s*student|i'?m\s*a?\s*phd|doctoral\s*student|школ\w*\s*доктор|докторант|докторантур|докторант"),
  ("bezpanstwowiec", r"bezpa[nń]stw|bez obywatel|stateless|без\s*громадян|апатрид|харьяалалгүй|иргэншилгүй"),
  ("pl", r"\b(polak|polk[aąi]|polish\s*citizen|i(?:'?m|\s+am)\s+polish|we\s+are\s+polish|citizen\s+of\s+poland|nationality\s+polish|from\s+poland|obywatel\w*\s*polsk|polskie\s*obywatel|jestem\s+z\s+polski|громадянин\w*\s*польщ|я\s+поляк|польськ\w*\s*громадян|польш\s*иргэн|би\s+польш|польш\s*улсын\s*иргэн)"),
  ("cudzoziemiec", r"cudzozie|obcokraj|zagranicz|international\s*student|foreign\s*student|i'?m\s*a?\s*foreign|non[- ]polish|residence\s*permit|pole'?s?\s*card|temporary\s*protection|ukrai|ukraine|belarus|bia[lł]oru|karta\s*polaka|kart\w*\s*pobytu|ochron\w*\s*czasow|uchod[zź]|інозем|громадян\w*\s*украї|з\s*україн|карта\s*поляка|карта\s*побуту|тимчасов\w*\s*захист|біжен|гадаад\s*оюутан|гадаадын\s*иргэн|оршин\s*суух|польшийн\s*карт|дүрвэгч|украин"),
 ],
 "tryb": [
  ("stacjonarne", r"(?<!nie)stacjonar|dzienn|full[-\s]?time|on[- ]campus|денн|стаціонар|очна\s*форм|өдрийн|бүтэн\s*цаг"),
  ("niestacjonarne", r"niestacjonar|zaoczn|weekend|part[-\s]?time|extramural|заочн|вечірнь|эчнээ|цагийн\s*сургалт"),
 ],
 "poziom": [
  ("SD", r"szko[lł]\w*\s*doktorsk|doctoral\s*school|phd\b|doktoranc|докторантур|докторант(?!\w)"),
  ("jednolite", r"jednolit|long[-\s]?cycle|undivided\s*master|єдин\w*\s*магістер|нэгдсэн\s*магистр"),
  ("II", r"\bii\s*stop|drugi\w*\s*stop|second[-\s]?cycle|master'?s?\b|graduate\s*program|magist(?!.*jednolit)|uzupe[lł]niaj|іі\s*ступ|другого\s*ступ|магістр|ii\s*зэрэг|2\s*зэрэг|магистр"),
  ("I", r"\bi\s*stop|pierwsz\w*\s*stop|first[-\s]?cycle|bachelor|undergraduate|licencj|in[zż]ynier|і\s*ступ|бакалавр|інженер|i\s*зэрэг|1\s*зэрэг"),
 ],
 "rok": [
  ("rok", r"(\b[1-6]\s*(rok|year|курс|жил|курс[т]?)\b|\byear\s*[1-6]\b|\b[1-6](st|nd|rd|th)\s*year\b|\bi+\s*rok|\bpierwsz\w*\s*rok|\bdrugi\w*\s*rok|\btrzeci\w*\s*rok|\bczwart\w*\s*rok|\bpi[aą]t\w*\s*rok|\bfirst\s*year|\bsecond\s*year|\bthird\s*year|\bfreshman|\bsophomore|\bперш\w*\s*рік|\bдруг\w*\s*рік|\bтрет\w*\s*рік|\b[1-6][- ]?р\s*курс|\b(?:na|jestem na)\s+(?:i|ii|iii|iv|v)\s+roku|\bpierwszoroczn)"),
 ],
 "drugi_kierunek": [
  ("tak", r"(drugi\w*\s*kierun|dw[ao]\w*\s*kierun|r[oó]wnoleg|second\s*(degree|major|program|programme|field)|double\s*major|parallel\s*stud|already\s*(graduated|have\s*a\s*degree)|completed\s*(studies|a\s*degree)|ju[zż]\s*(mam|uko[nń]czy)|mam\s*(tytu[lł]|licencjat|dyplom)|друг\w*\s*(напрям|спеціальн|спеціал)|паралельн|вже\s*(маю|закінч)|диплом|хоёр\s*мэргэжил|зэрэгцээ|дипломтой|төгссөн)"),
  ("nie", r"(jedyn\w*\s*kierun|jeden\s*kierun|tylko\s*jed|only\s*one\s*(program|programme|major|degree|field)|single\s*(major|program|programme)|one\s*program\s*only|nie\s*studiuj\w*\s*(r[oó]wnoleg|drug)|first\s*degree\s*only|nie\s*mam\s*(innego|drugiego|uko)|один\s*(напрям|спеціальн)|лише\s*один|тільки\s*один|зөвхөн\s*нэг|ганц\s*мэргэжил)"),
 ],
 "niepelnosprawnosc": [
  ("tak", r"(mam\s*orzeczenie|z\s*niepe[lł]nosprawno|orzeczen\w*\s*o\s*(niepe|stop)|disability\s*(certificate|ruling|status)|i\s*have\s*a?\s*disability|інвалід|посвідчен\w*\s*про\s*інвал|хөгжлийн\s*бэрхшээл)"),
  ("nie", r"(nie\s*mam\s*orzecz|bez\s*orzecz|nie\s*jestem\s*(osob\w*\s*)?niepe[lł]no|no\s*disability|without\s*disability|не\s*маю\s*(інвал|посвідч)|бэрхшээлгүй|хөгжлийн\s*бэрхшээл\s*гүй)"),
 ],
 "kierunek": [
  ("kierunek", r"informaty|computer\s*science|elektrotechn|electrical|transport|ekonom|economics|prawo|law\b|piel[eę]g|nursing|medycy|pedagog|mechani|logisty|filolog|filozof|socjolog|turysty|kosmetolog|інформатик|електротех|економік|право|педагог|механік|логістик|информатик|цахилгаан|эдийн\s*засаг"),
 ],
}

# keep SLOTS shape used elsewhere: (default PL question, opts dict)
SLOTS = {k: (SLOT_Q[k]["pl"], {val: rx for val, rx in opts}) for k, opts in SLOT_OPTS.items()}

TOPICS = [
 ("stypendium_socjalne", r"socjaln|zapomog|dochod|pomoc\w*\s*materialn|[sś]wiadcze|social\s*scholarship|maintenance\s*grant|need[-\s]?based|стипенд\w*\s*соціал|соціальн\w*\s*стипенд|матеріальн\w*\s*допомог|тэтгэлэг|нийгмийн\s*тэтгэлэг|амьжиргааны", ["status", "drugi_kierunek", "tryb", "poziom"]),
 ("stypendium_rektora", r"rektor|najlepsz|[sś]redni\w*\s*ocen|rector'?s?\s*scholarship|merit\s*scholarship|academic\s*excellence|стипенд\w*\s*ректор|ректорськ|гол\s*тэтгэлэг|ректорын\s*тэтгэлэг", ["status", "drugi_kierunek", "poziom", "rok"]),
 ("stypendium_niepeln", r"niepe[lł]nospraw|disability\s*scholarship|інвалід|хөгжлийн\s*бэрхшээл", ["status", "niepelnosprawnosc", "drugi_kierunek"]),
 ("doktoranckie", r"doktorant|doktorsk|doktoranck|phd\b|doctoral|докторант|докторантур", ["status"]),
 ("oplaty", r"op[lł]at|czesne|ile\s*kosztuj|p[lł]aci[cć]|bezp[lł]atn|tuition|fees?|how\s*much\s*(does|do|is)|cost\s*of\s*stud|оплат|вартість\s*навчан|плата\s*за\s*навчан|төлбөр|сургалтын\s*төлбөр|хэд\s*вэ", ["status", "tryb", "poziom"]),
 ("erasmus", r"erasmus|wyjazd|wymian|mobilno|exchange\s*program|study\s*abroad|мобільніст|обмін|солилцоо|гадаадад\s*суралц", ["status", "poziom", "rok"]),
 ("plan", r"plan\w*\s*zaj|rozk[lł]ad|harmonogram\s*zaj|zaj[eę]cia\s*w|kiedy\s*mam\s*zaj|timetable|class\s*schedule|course\s*schedule|розклад|розклад\s*занят|хичээлийн\s*хуваарь|хуваарь", ["kierunek", "tryb"]),
 ("cudzoziemcy", r"cudzozie|bezpa[nń]stw|bez\s*obywatel|karta\s*polaka|kart\w*\s*pobytu|legaliz|wiz\w*\b|ochron\w*\s*czasow|international\s*student|foreign\s*student|residence\s*permit|інозем|без\s*громадян|карта\s*поляка|гадаад\s*оюутан|оршин\s*суух", ["status"]),
 ("dwa_kierunki", r"dw[ao]\w*\s*kierun|drugi\w*\s*kierun|r[oó]wnoleg|second\s*(major|program|programme)|double\s*major|друг\w*\s*напрям|паралельн|хоёр\s*мэргэжил|зэрэгцээ", ["status", "drugi_kierunek", "tryb"]),
]

TOPIC_PL_QUERY = {
 "stypendium_socjalne": "stypendium socjalne pomoc materialna dochód",
 "stypendium_rektora": "stypendium rektora średnia ocen",
 "stypendium_niepeln": "stypendium dla osób niepełnosprawnych",
 "doktoranckie": "stypendium doktoranckie szkoła doktorska",
 "oplaty": "opłaty czesne koszt studiów",
 "erasmus": "Erasmus wymiana mobilność",
 "plan": "plan zajęć rozkład WTEiI",
 "cudzoziemcy": "cudzoziemcy rekrutacja karta pobytu",
 "dwa_kierunki": "drugi kierunek świadczenia",
}

CLARIFY = {
 "pl": ("Zanim odpowiem – zasady na UR zależą od Twojej sytuacji. Proszę, doprecyzuj:",
        "Możesz odpowiedzieć jednym zdaniem, np. „cudzoziemiec z kartą pobytu, stacjonarne, I stopień, 2 rok, jeden kierunek”."),
 "en": ("Before I answer – UR rules depend on your situation. Please clarify:",
        "You can reply in one sentence, e.g. “international student with a residence permit, full-time, bachelor, year 2, one programme”."),
 "uk": ("Перш ніж відповісти – правила UR залежать від вашої ситуації. Уточніть, будь ласка:",
        "Можна однією фразою, напр. «іноземець з картою побуту, денна, І ступінь, 2 рік, один напрям»."),
 "mn": ("Хариулахаас өмнө – UR-ийн дүрэм таны нөхцөл байдлаас хамаарна. Тодруулна уу:",
        "Нэг өгүүлбэрээр хариулж болно, ж.нь. «оршин суух зөвшөөрөлтэй гадаадын оюутан, өдрийн, I зэрэг, 2-р курс, нэг мэргэжил»."),
}

def extract_profile(text):
    t = text.lower()
    prof = {}
    for slot, opts in SLOT_OPTS.items():
        for val, rx in opts:
            if re.search(rx, t, re.I):
                prof[slot] = val
                break
    if prof.get("status") == "doktorant":
        prof.setdefault("poziom", "SD"); prof.setdefault("tryb", "stacjonarne"); prof.setdefault("rok", "rok")
    if prof.get("poziom") == "SD":
        prof.setdefault("status_doktor", True)
    if re.search(r"drugi\w*\s*kierun|dw[ao]\w*\s*kierun|r[oó]wnoleg|second\s*(major|program|programme)|double\s*major|друг\w*\s*напрям|хоёр\s*мэргэжил", t, re.I) and \
       re.search(r"czy\s*(mog|moż)|can\s*i|is\s*it\s*possible|чи\s*мож|болох\s*уу", t, re.I):
        prof.setdefault("drugi_kierunek", "pytanie")
    return prof

def needed(question, history_text):
    q = question.lower()
    topics = [(n, s) for n, rx, s in TOPICS if re.search(rx, q, re.I)]
    if not topics:
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

def clarify_text(lang, missing):
    head, tip = CLARIFY.get(lang, CLARIFY["pl"])
    qs = "\n".join(f"{i}. {SLOT_Q[m].get(lang, SLOT_Q[m]['pl'])}" for i, m in enumerate(missing, 1))
    return f"{head}\n{qs}\n\n{tip}"

SYSTEM = """You are an information assistant for students of Kazimierz Pułaski University of Radom (Uniwersytet Radomski, UR).
HARD RULES:
1. Answer in {lang_name}. The user language code is {lang}. Keep official names (UR, Biuro Obsługi Studenta, zarządzenie codes) as in the sources when useful, but explain in the user language.
2. Use ONLY the source fragments in ŹRÓDŁA / SOURCES. No outside knowledge. If missing, say clearly that indexed UR materials do not cover it and point to Biuro Obsługi Studenta, Dział Współpracy Zagranicznej, or Szkoła Doktorska.
3. Ground every claim with [n]. End with a “Sources:” / “Źródła:” / “Джерела:” / “Эх сурвалж:” list (matching the answer language) with URL and update date.
4. Mark “⚠️ may be outdated” ONLY for sources before 2024-01-01 or with no date. Never mark 2024+ as outdated. Quote amounts/deadlines only if present in sources, with the academic year / ordinance (e.g. R-41/2025). Today: {today}. If a deadline has passed, say so.
5. List each URL once. Do not invent source numbers.
6. CLARIFY first when rules depend on student situation (citizenship/foreigner/stateless, doctoral school, full-time/part-time, level/year, second programme or prior diploma, disability, programme/group) and PROFIL lacks data — ask short numbered questions only, then answer after the reply.
7. Describe rules for the user’s category only; mention exceptions briefly.
8. No legal advice; for individual cases refer to the proper UR unit. Do not invent URLs."""

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

PROF_LABEL = {
 "pl": {"status": "status", "tryb": "tryb", "poziom": "poziom", "rok": "rok", "drugi_kierunek": "drugi kierunek / dyplom", "niepelnosprawnosc": "orzeczenie o niepełnosprawności", "kierunek": "kierunek/grupa"},
 "en": {"status": "status", "tryb": "mode", "poziom": "level", "rok": "year", "drugi_kierunek": "second programme / diploma", "niepelnosprawnosc": "disability certificate", "kierunek": "programme/group"},
 "uk": {"status": "статус", "tryb": "форма", "poziom": "рівень", "rok": "рік", "drugi_kierunek": "другий напрям / диплом", "niepelnosprawnosc": "інвалідність", "kierunek": "напрям/група"},
 "mn": {"status": "статус", "tryb": "хэлбэр", "poziom": "түвшин", "rok": "курс", "drugi_kierunek": "хоёр мэргэжил / диплом", "niepelnosprawnosc": "хөгжлийн бэрхшээл", "kierunek": "мэргэжил/бүлэг"},
}
NO_LLM = {
 "pl": "**Tryb bez modelu językowego** – najtrafniejsze fragmenty z oficjalnych stron UR (profil: {prof}). Zweryfikuj w źródle:",
 "en": "**No-LLM mode** – top matching excerpts from official UR pages (profile: {prof}). Verify in the source:",
 "uk": "**Режим без мовної моделі** – найближчі фрагменти з офіційних сторінок UR (профіль: {prof}). Перевірте в джерелі:",
 "mn": "**Хэлний загваргүй горим** – UR-ийн албан ёсны хуудаснуудаас олдсон хэсгүүд (профайл: {prof}). Эх сурвалжаас шалгана уу:",
}
SRC_HDR = {"pl": "Źródła", "en": "Sources", "uk": "Джерела", "mn": "Эх сурвалж"}
OUTDATED = {"pl": "informacja może być nieaktualna", "en": "may be outdated", "uk": "може бути неактуальною", "mn": "хуучирсан байж болно"}
LLM_ERR = {
 "pl": "(Błąd LLM: {e}. Pokazuję tryb wyszukiwania.)\n\n",
 "en": "(LLM error: {e}. Showing search mode.)\n\n",
 "uk": "(Помилка LLM: {e}. Показую режим пошуку.)\n\n",
 "mn": "(LLM алдаа: {e}. Хайлтын горим.)\n\n",
}

def answer(question, history):
    """history: lista {'role','content'}; zwraca dict(answer, sources, mode, clarify, lang)"""
    hist_user = "\n".join(m["content"] for m in history if m["role"] == "user")
    lang = detect_lang(question, hist_user)
    topics, prof, missing = needed(question, hist_user)
    if missing:
        return dict(clarify=True, mode="doprecyzowanie", sources=[], profile=prof, lang=lang,
                    answer=clarify_text(lang, missing))
    base_q = question
    if history:
        prev = [m["content"] for m in history if m["role"] == "user" and any(re.search(rx, m["content"], re.I) for _, rx, _ in TOPICS)]
        if prev: base_q = prev[-1] + " " + question
    q = base_q + " " + " ".join(str(v) for k, v in prof.items() if k in ("status",) and v in ("cudzoziemiec", "bezpanstwowiec", "doktorant"))
    q += " " + " ".join(TOPIC_PL_QUERY[t] for t in topics if t in TOPIC_PL_QUERY)
    PREF = {"plan": ["wteii"], "erasmus": ["dwz"], "cudzoziemcy": ["rekrutacja", "dwz", "student"], "oplaty": ["rekrutacja", "student"],
            "doktoranckie": ["student"], "stypendium_socjalne": ["student"], "stypendium_rektora": ["student"], "dwa_kierunki": ["student"]}
    tp = [t for t in topics if t != "cudzoziemcy"] or topics
    prefer = sorted({x for t in tp for x in PREF.get(t, [])})
    if tp is not topics:
        q = re.sub(r"(?i)\b(jako\s+)?cudzoziem\w*|international\s+student|foreign\s+student|інозем\w*|гадаад\s+оюутан", " ", q)
    hits = search(q, k=8, prefer=prefer)
    if "plan" in topics:
        files = sorted({(c["title"], c["url"], c["modified"]) for c in IDX["chunks"] if c["source"] == "wteii" and c["kind"] == "file"})
        lst = "\n".join(f"- {t.split(' – ')[-1]} → {u} (aktualizacja: {m})" for t, u, m in files)
        hits = [dict(title="WTEiI – lista plików z planami zajęć (nazwa pliku = kod kierunku: IN=Informatyka, IT, E=Elektrotechnika, TiL/TIL=Transport i logistyka; _I/_II/_III/_IV lub R1–R4 = rok; _all = niestacjonarne/zjazdy)",
                     url="https://wteii.uniwersytetradom.pl/plany-zajec/", modified=max(f[2] or "" for f in files) or None, text=lst, source="wteii", kind="list")] + hits[:6]
    srcs = [dict(n=i, title=h["title"], url=h["url"], modified=h["modified"], outdated=outdated(h["modified"]), snippet=h["text"][:400]) for i, h in enumerate(hits, 1)]
    labels = PROF_LABEL.get(lang, PROF_LABEL["pl"])
    prof_txt = ", ".join(f"{labels.get(k, k)}: {v}" for k, v in prof.items() if k in labels) or "—"
    if llm_enabled():
        import datetime
        sys = (SYSTEM.replace("{today}", datetime.date.today().isoformat())
                     .replace("{lang}", lang)
                     .replace("{lang_name}", LANG_NAME.get(lang, "polski")))
        msgs = [{"role": "system", "content": sys}] + history[-8:] + [{"role": "user", "content":
                f"PROFIL STUDENTA: {prof_txt}\nLANG: {lang}\n\nŹRÓDŁA:\n{fmt_sources(hits)}\n\nPYTANIE: {question}"}]
        try:
            return dict(clarify=False, mode="llm", sources=srcs, profile=prof, lang=lang, answer=call_llm(msgs))
        except Exception as e:
            err = LLM_ERR.get(lang, LLM_ERR["pl"]).format(e=e)
    else:
        err = ""
    warn_l = OUTDATED.get(lang, OUTDATED["pl"])
    lines = [err + NO_LLM.get(lang, NO_LLM["pl"]).format(prof=prof_txt)]
    for s, h in zip(srcs[:4], hits[:4]):
        warn = f" ⚠️ {warn_l}" if s["outdated"] else ""
        snip = re.sub(r"\s+", " ", h["text"])[:500]
        lines.append(f"\n[{s['n']}] **{s['title']}** ({s['modified'] or '—'}{warn})\n„{snip}…”")
    lines.append(f"\n{SRC_HDR.get(lang, 'Źródła')}:\n" + "\n".join(f"[{s['n']}] {s['url']} – {s['modified'] or '—'}" for s in srcs[:4]))
    return dict(clarify=False, mode="wyszukiwanie", sources=srcs, profile=prof, lang=lang, answer="\n".join(lines))
