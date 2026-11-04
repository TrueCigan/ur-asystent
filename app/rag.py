"""Logika asystenta: doprecyzowanie sytuacji studenta, wyszukiwanie hybrydowe, odpowiedź z cytatami (PL/EN/UK/MN)."""
import os, re, gzip, json, math, collections, numpy as np, scipy.sparse as sp, httpx
from index import tokens, norm, D, char_ngrams, char_vec
from security import (
    SECURITY_RULES, is_security_probe, refuse_message, wrap_untrusted,
    redact_secrets, safe_error,
)
from topic_policy import (
    TOPIC_POLICY, apply_policy_scores, force_topic_hits, hits_match_canonical,
    query_extras, prefer_sources, policy_for,
)

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
def search(q, k=8, prefer=None, topics=None, profile=None):
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
    topics = set(topics or [])
    for i, c in enumerate(ch):
        if (c["modified"] or "0") < "2024":
            sc[i] *= 0.6
        if prefer and c["source"] in prefer:
            sc[i] *= 1.6
    apply_policy_scores(sc, ch, topics, profile)
    # plan: preferencja wydziału po kierunku
    if "plan" in topics:
        kier = (profile or {}).get("kierunek")
        fac = KIEROUNEK_FACULTY.get(kier) if kier else None
        for i, c in enumerate(ch):
            title = (c.get("title") or "").lower()
            if c.get("source") == "bip" or re.search(r"plan\s*studi|program\s*studi|opis\s*programu|uchwa[łl]a", title):
                sc[i] *= 0.08
            if re.search(r"plan\s*zaj|rozk[lł]ad|timetable", title) or c.get("source") in PLAN_SOURCES:
                sc[i] *= 2.0
            if c.get("kind") == "file" and (c.get("modified") or "0") < "2025" and c.get("source") in PLAN_SOURCES:
                sc[i] *= 0.25
            if fac and c.get("source") == fac:
                sc[i] *= 2.0
            elif fac and c.get("source") in PLAN_SOURCES and c.get("source") != fac:
                sc[i] *= 0.15
    out, per_url = [], {}
    for i in np.argsort(-sc):
        c = ch[i]
        if per_url.get(c["url"], 0) >= 2:
            continue
        per_url[c["url"]] = per_url.get(c["url"], 0) + 1
        out.append(dict(c, score=float(sc[i])))
        if len(out) >= k:
            break
    return out

# ---------- język (PL / EN / UK / MN) ----------
LANG_NAME = {"pl": "polski", "en": "English", "uk": "українська", "mn": "монгол"}

def detect_lang(*parts, latest=""):
    # jawna prośba o język odpowiedzi w bieżącej wiadomości
    if latest:
        if re.search(r"(po\s*polsku|in\s*polish|на\s*польськ|по\s*польськ|польською|польш\s*хэлээр)", latest, re.I): return "pl"
        if re.search(r"(in\s*english|po\s*angielsku|англійськ|english\s*please)", latest, re.I): return "en"
        if re.search(r"(українськ|in\s*ukrainian|по\s*україн)", latest, re.I): return "uk"
        if re.search(r"(монгол|in\s*mongolian|по\s*монгольськ)", latest, re.I): return "mn"
    text = "\n".join(p for p in parts if p) or ""
    if re.search(r"[өүӨҮ]", text): return "mn"
    if re.search(r"[іїєґІЇЄҐ]", text): return "uk"
    if re.search(r"[а-яА-ЯёЁ]", text):
        if re.search(r"тэтгэлэг|оюутан|суралц|төлбөр|иргэн|мэргэжил|докторант", text, re.I): return "mn"
        return "uk"
    if re.search(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", text): return "pl"
    if re.search(r"\b(the|and|how|what|when|where|scholarship|tuition|fees?|i'?m|i am|full[- ]time|part[- ]time|bachelor|master'?s?|phd|doctoral|citizen|foreign)\b", text, re.I): return "en"
    if re.search(r"\b(jak|czy|stypendium|opłat|jestem|studiuj|cudzoziem|rektor|zajęć)\b", text, re.I): return "pl"
    if re.search(r"\b(як|чи|стипенд|оплат|громадян|інозем|навчан|кошту)\b", text, re.I): return "uk"
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
  ("stacjonarne", r"(?<!nie)stacjonar|dzienn|full[-\s]?time|on[- ]campus|pe[lł]ny\s*etat|денн|стаціонар|очна\s*форм|өдрийн|бүтэн\s*цаг"),
  ("niestacjonarne", r"niestacjonar|zaoczn|weekend|part[-\s]?time|extramural|заочн|вечірнь|эчнээ|цагийн\s*сургалт"),
 ],
 "poziom": [
  ("SD", r"szko[lł]\w*\s*doktorsk|doctoral\s*school|phd\b|doktoranc|докторантур|докторант(?!\w)"),
  ("jednolite", r"jednolit|long[-\s]?cycle|undivided\s*master|єдин\w*\s*магістер|нэгдсэн\s*магистр"),
  ("II", r"\bii\s*stop|drugi\w*\s*stop|second[-\s]?cycle|master'?s?\b|graduate\s*program|magist(?!.*jednolit)|uzupe[lł]niaj|іі\s*ступ|другого\s*ступ|магістр|ii\s*зэрэг|2\s*зэрэг|магистр"),
  ("I", r"\bi\s*stop|pierwsz\w*\s*stop|first[-\s]?cycle|bachelor|undergraduate|licencj|in[zż]ynier|і\s*ступ|бакалавр|інженер|i\s*зэрэг|1\s*зэрэг"),
 ],
 "rok": [
  ("1", r"(\b1\s*(rok|year|курс|жил)\b|\byear\s*1\b|\b1(st)?\s*year\b|\bpierwsz\w*\s*rok|\bfirst\s*year|\bfreshman|\bперш\w*\s*рік|\b(?:na|jestem na)\s+i\s+roku|\bpierwszoroczn|^\s*1\s*$)"),
  ("2", r"(\b2\s*(rok|year|курс|жил)\b|\byear\s*2\b|\b2(nd)?\s*year\b|\bii\s*rok|\bdrugi\w*\s*rok|\bsecond\s*year|\bsophomore|\bдруг\w*\s*рік|\b(?:na|jestem na)\s+ii\s+roku|^\s*2\s*$)"),
  ("3", r"(\b3\s*(rok|year|курс|жил)\b|\byear\s*3\b|\b3(rd)?\s*year\b|\biii\s*rok|\btrzeci\w*\s*rok|\bthird\s*year|\bтрет\w*\s*рік|\b(?:na|jestem na)\s+iii\s+roku|^\s*3\s*$)"),
  ("4", r"(\b4\s*(rok|year|курс|жил)\b|\byear\s*4\b|\b4(th)?\s*year\b|\biv\s*rok|\bczwart\w*\s*rok|\b(?:na|jestem na)\s+iv\s+roku|^\s*4\s*$)"),
  ("5", r"(\b5\s*(rok|year|курс|жил)\b|\byear\s*5\b|\b5(th)?\s*year\b|\bv\s*rok|\bpi[aą]t\w*\s*rok|^\s*5\s*$)"),
  ("6", r"(\b6\s*(rok|year|курс|жил)\b|\byear\s*6\b|\b6(th)?\s*year\b|^\s*6\s*$)"),
 ],
 "drugi_kierunek": [
  # „nie” najpierw – unikaj fałszywego „tak” przy „nie posiadam dyplomu”
  ("nie", r"(?i)(?:^\s*nie\.?\s*$|(?:,\s*|\s+)nie\.?\s*$|jedyn\w*\s*kierun|jeden\s*kierun|tylko\s*jed|tylko\s*(w\s*)?(uczelni|na\s*ur|tu)\b|jedyn\w*\s*uczel|only\s*one\s*(program|programme|major|degree|field)|single\s*(major|program|programme)|one\s*program\s*only|nie\s*studiuj\w*\s*(r[oó]wnoleg|drug)|first\s*degree\s*only|nie\s*(?:mam|posiadam)\s*(?:żadn\w*\s*)?(?:innego|drugiego|uko|dyplom)|brak\s*dyplom|żadn\w*\s*dyplom|bez\s*dyplom|nie\s*mam\s*jeszcze\s*(żadn\w*\s*)?dyplom|один\s*(напрям|спеціальн)|лише\s*один|тільки\s*один|не\s*маю\s*(жодн\w*\s*)?диплом|зөвхөн\s*нэг|ганц\s*мэргэжил)"),
  ("tak", r"(?i)(?:(?:mam|posiadam)\s+(?:ju[zż]\s+)?(?:uko[nń]czon\w*\s+)?(?:tytu[lł]|licencjat|in[zż]ynier|magister|dyplom)(?!\w)|drugi\w*\s*kierun|dw[ao]\w*\s*kierun|r[oó]wnoleg|second\s*(degree|major|program|programme|field)|double\s*major|parallel\s*stud|already\s*(graduated|have\s*a\s*degree)|completed\s*(studies|a\s*degree)|ju[zż]\s*uko[nń]czy|друг\w*\s*(напрям|спеціальн|спеціал)|паралельн|вже\s*(маю|закінч)\w*\s*диплом|хоёр\s*мэргэжил|зэрэгцээ|дипломтой|төгссөн)"),
 ],
 "niepelnosprawnosc": [
  ("tak", r"(mam\s*orzeczenie|z\s*niepe[lł]nosprawno|orzeczen\w*\s*o\s*(niepe|stop)|disability\s*(certificate|ruling|status)|i\s*have\s*a?\s*disability|інвалід|посвідчен\w*\s*про\s*інвал|хөгжлийн\s*бэрхшээл)"),
  ("nie", r"(nie\s*mam\s*orzecz|bez\s*orzecz|nie\s*jestem\s*(osob\w*\s*)?niepe[lł]no|no\s*disability|without\s*disability|не\s*маю\s*(інвал|посвідч)|бэрхшээлгүй|хөгжлийн\s*бэрхшээл\s*гүй)"),
 ],
 "kierunek": [
  # kolejność ma znaczenie – bardziej konkretne najpierw
  ("finanse", r"finanse\s*i\s*rachunk|finanse\s*i\s*finans|finance\s*and\s*account|фінанс\w*\s*i\s*облік|санхүү"),
  ("weif_wydzial", r"ekonom\w*\s*i\s*finans|wydzia[łl]\s*ekonom|weif\b|faculty\s*of\s*economics|економ\w*\s*і\s*фінанс"),
  ("ekonomia", r"ekonom(?:ia|ja|ii|ię|ią)\b|economics?\b|економik|эдийн\s*засаг"),
  ("ai_biznes", r"sztuczn\w*\s*inteligenc|artificial\s*intelligence|штучн\w*\s*інтелект|informatyk\w*\s*i\s*analityk\w*\s*w\s*biznes"),
  ("informatyka_techniczna", r"informatyk\w*\s*technicz|it\s*technicz|technical\s*informatics"),
  ("informatyka", r"informatyk|computer\s*science|інформатик|информатик"),
  ("elektrotechnika", r"elektrotechn|electrical\s*eng|електротех|цахилгаан"),
  ("transport", r"transport\s*i\s*logist|til\b|\bti[lł]\b|transport\b|логістик"),
  ("prawo", r"\bprawo\b|\blaw\b|право(?!\s*jazdy)"),
  ("administracja", r"administracj|administration\b|адміністрац"),
  ("bezpieczenstwo", r"bezpiecze[nń]stwo\s*wewn|internal\s*security|безпек\w*\s*внутріш"),
  ("pielegniarstwo", r"piel[eę]gniar|nursing|медсестрин"),
  ("kosmetologia", r"kosmetolog"),
  ("medycyna", r"\bmedycyn|\bmedicine\b|лікарськ|медицин"),
  ("fizjoterapia", r"fizjoterap|physiotherap"),
  ("pedagogika", r"pedagog|педагог"),
  ("filologia", r"filolog|philology|філолог"),
  ("mechanika", r"mechanika\s*i\s*budowa|mi[bm]\b|mechanical\s*eng|механік"),
  ("budownictwo", r"budownictw|civil\s*eng|будівниц"),
  ("zarzadzanie", r"zarz[aą]dzanie(?!\s*i\s*in[zż])|management\b|управлінн|менеджмент"),
  ("analityka", r"analityk\w*\s*gospodarcz|business\s*analytics|аналітик"),
  ("turystyka", r"turystyk|recreation|туризм"),
  ("bhp", r"\bbhp\b|bezpiecze[nń]stwo\s*i\s*higien"),
 ],
}

# kierunek → kod źródła planów zajęć (crawl)
KIEROUNEK_FACULTY = {
    "ekonomia": "weif", "finanse": "weif", "weif_wydzial": "weif", "analityka": "weif",
    "zarzadzanie": "weif", "ai_biznes": "weif",
    "informatyka": "wteii", "informatyka_techniczna": "wteii", "elektrotechnika": "wteii",
    "transport": "wteii", "turystyka": "wteii",
    "prawo": "wpia", "administracja": "wpia", "bezpieczenstwo": "wpia",
    "pielegniarstwo": "wnminoz", "kosmetologia": "wnminoz", "medycyna": "wnminoz", "fizjoterapia": "wnminoz",
    "pedagogika": "wfp", "filologia": "wfp",
    "mechanika": "wm", "budownictwo": "wm", "bhp": "wm",
}
FACULTY_PLAN_URL = {
    "wteii": "https://wteii.uniwersytetradom.pl/plany-zajec/",
    "weif": "https://weif.uniwersytetradom.pl/plany-zajec/",
    "wm": "https://wm.uniwersytetradom.pl/plany-zajec/",
    "wpia": "https://wpia.uniwersytetradom.pl/plany-zajec/",
    "wnminoz": "https://wnminoz.uniwersytetradom.pl/plany-zajec/",
    "wfp": "https://wfp.uniwersytetradom.pl/plan-zajec/",
    "wicit": "https://wicit.uniwersytetradom.pl/plan-zajec/",
}
FACULTY_LABEL = {
    "wteii": "WTEiI", "weif": "WEiF (Ekonomia i Finanse)", "wm": "Wydział Mechaniczny",
    "wpia": "WPiA", "wnminoz": "WNMiNoZ", "wfp": "WFP", "wicit": "WICiT",
}
PLAN_SOURCES = set(FACULTY_PLAN_URL)


# keep SLOTS shape used elsewhere: (default PL question, opts dict)
SLOTS = {k: (SLOT_Q[k]["pl"], {val: rx for val, rx in opts}) for k, opts in SLOT_OPTS.items()}

TOPICS = [
 ("stypendium_socjalne", r"socjaln|zapomog|dochod|pomoc\w*\s*materialn|[sś]wiadcze|social\s*scholarship|maintenance\s*grant|need[-\s]?based|стипенд\w*\s*соціал|соціальн\w*\s*стипенд|матеріальн\w*\s*допомог|тэтгэлэг|нийгмийн\s*тэтгэлэг|амьжиргааны", ["status", "drugi_kierunek", "tryb", "poziom"]),
 ("stypendium_rektora", r"rektor|najlepsz|[sś]redni\w*\s*ocen|rector'?s?\s*scholarship|merit\s*scholarship|academic\s*excellence|стипенд\w*\s*ректор|ректорськ|гол\s*тэтгэлэг|ректорын\s*тэтгэлэг", ["status", "drugi_kierunek", "poziom", "rok"]),
 ("stypendium_niepeln", r"niepe[lł]nospraw|disability\s*scholarship|інвалід|хөгжлийн\s*бэрхшээл", ["status", "niepelnosprawnosc", "drugi_kierunek"]),
 ("doktoranckie", r"doktorant|doktorsk|doktoranck|phd\b|doctoral|докторант|докторантур", ["status"]),
 ("oplaty", r"op[lł]at|czesne|ile\s*kosztuj|p[lł]aci[cć]|bezp[lł]atn|tuition|fees?|how\s*much|cost\s*of\s*stud|price\s*of\s*stud|оплат|вартіст|кошту|цін[ауи]\s*навч|плата\s*за\s*навч|скільки\s*.{0,20}навч|төлбөр|сургалтын\s*төлбөр|хэд\s*(вэ|төгрөг|zł)", ["status", "tryb", "poziom"]),
 ("erasmus", r"erasmus|wyjazd|wymian|mobilno|exchange\s*program|study\s*abroad|мобільніст|обмін|солилцоо|гадаадад\s*суралц", ["status", "poziom", "rok"]),
 ("plan", r"plan\w*\s*zaj|rozk[lł]ad|harmonogram\s*zaj|zaj[eę]cia\s*w|kiedy\s*mam\s*zaj|timetable|class\s*schedule|course\s*schedule|розклад|розклад\s*занят|хичээлийн\s*хуваарь|хуваарь", ["kierunek", "tryb", "poziom", "rok"]),
 ("cudzoziemcy", r"cudzozie|bezpa[nń]stw|bez\s*obywatel|karta\s*polaka|kart\w*\s*pobytu|legaliz|wiz\w*\b|ochron\w*\s*czasow|international\s*student|foreign\s*student|residence\s*permit|інозем|без\s*громадян|карта\s*поляка|гадаад\s*оюутан|оршин\s*суух", ["status"]),
 ("dwa_kierunki", r"dw[ao]\w*\s*kierun|drugi\w*\s*kierun|r[oó]wnoleg|second\s*(major|program|programme)|double\s*major|друг\w*\s*напрям|паралельн|хоёр\s*мэргэжил|зэрэгцээ", ["status", "drugi_kierunek", "tryb"]),
]

TOPIC_PL_QUERY = {
 "stypendium_socjalne": "stypendium socjalne pomoc materialna dochód",
 "stypendium_rektora": "stypendium rektora średnia ocen",
 "stypendium_niepeln": "stypendium dla osób niepełnosprawnych",
 "doktoranckie": "stypendium doktoranckie szkoła doktorska",
 "oplaty": "opłaty czesne koszt studiów wysokość opłat za usługi edukacyjne zarządzenie semestr zł",
 "erasmus": "Erasmus wymiana mobilność",
 "plan": "plan zajęć rozkład harmonogram",
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
    # Podstawa pobytu (podtyp; nie osobny slot clarify)
    if re.search(
        r"pesel\s*ukr|\bukr\b|ochron\w*\s*czasow|temporary\s*protection|"
        r"specjaln\w*\s*ustaw\w*\s*ukrain|ustaw\w*.{0,40}ukrain|"
        r"тимчасов\w*\s*захист|громадян\w*\s*украї|з\s*україн|гражданин\w*\s*украин",
        t, re.I,
    ):
        prof["pobyt"] = "ukr"
        prof.setdefault("status", "cudzoziemiec")
    elif re.search(r"kart\w*\s*polaka|pole'?s?\s*card|карта\s*поляка", t, re.I):
        prof["pobyt"] = "karta_polaka"
        prof.setdefault("status", "cudzoziemiec")
    elif re.search(r"pobyt\w*\s*sta[lł]|permanent\s*resid|сталий\s*побут|постоянн\w*\s*пребыв", t, re.I):
        prof["pobyt"] = "pobyt_staly"
        prof.setdefault("status", "cudzoziemiec")
    elif re.search(r"pobyt\w*\s*czasow|temporary\s*resid|карт\w*\s*pobytu|карта\s*побуту|оршин\s*суух", t, re.I):
        prof["pobyt"] = "pobyt_czasowy"
        prof.setdefault("status", "cudzoziemiec")
    # krótkie tak/nie jako uzupełnienie ostatniego slotu (drugi_kierunek / niepełnosprawność)
    if re.match(r"^\s*(tak|yes|так|тийм)\s*\.?\s*$", t, re.I):
        prof.setdefault("drugi_kierunek", "tak")
    if re.match(r"^\s*(nie|no|ні|үгүй)\s*\.?\s*$", t, re.I):
        prof.setdefault("drugi_kierunek", "nie")
    if prof.get("status") == "doktorant":
        prof.setdefault("poziom", "SD"); prof.setdefault("tryb", "stacjonarne"); prof.setdefault("rok", "1")
    if prof.get("poziom") == "SD":
        prof.setdefault("status_doktor", True)
    if re.search(r"drugi\w*\s*kierun|dw[ao]\w*\s*kierun|r[oó]wnoleg|second\s*(major|program|programme)|double\s*major|друг\w*\s*напрям|хоёр\s*мэргэжил", t, re.I) and \
       re.search(r"czy\s*(mog|moż)|can\s*i|is\s*it\s*possible|чи\s*мож|болох\s*уу", t, re.I):
        prof.setdefault("drugi_kierunek", "pytanie")
    return prof

_BENEFIT_TOPICS = {
    "stypendium_socjalne", "stypendium_rektora", "stypendium_niepeln",
    "oplaty", "erasmus", "doktoranckie", "dwa_kierunki", "plan",
}

def needed(question, history_text):
    q = question.lower()
    topics = [(n, s) for n, rx, s in TOPICS if re.search(rx, q, re.I)]
    hist_topics = [(n, s) for n, rx, s in TOPICS if re.search(rx, history_text.lower(), re.I)]
    # Odpowiedź profilowa („cudzoziemiec, nie”) nie może zbić tematu ze stypendium na „cudzoziemcy/rekrutacja”
    benefit_hist = [t for t in hist_topics if t[0] in _BENEFIT_TOPICS]
    if benefit_hist:
        names = {n for n, _ in topics}
        if not topics or names <= {"cudzoziemcy"}:
            topics = [benefit_hist[0]]
        else:
            topics = [(n, s) for n, s in topics if n != "cudzoziemcy"] or topics
    elif not topics and hist_topics:
        topics = hist_topics[:1]
    req = []
    for _, s in topics:
        for x in s:
            if x not in req: req.append(x)
    # bieżąca wiadomość nadpisuje historię (np. WEiF → konkretnie Ekonomia)
    prof = extract_profile(history_text)
    prof.update(extract_profile(question))
    if prof.get("status") == "doktorant":
        req = [x for x in req if x not in ("tryb", "poziom", "rok", "kierunek")]
    missing = [x for x in req if x not in prof]
    return [n for n, _ in topics], prof, missing

def clarify_text(lang, missing):
    head, tip = CLARIFY.get(lang, CLARIFY["pl"])
    qs = "\n".join(f"{i}. {SLOT_Q[m].get(lang, SLOT_Q[m]['pl'])}" for i, m in enumerate(missing, 1))
    return f"{head}\n{qs}\n\n{tip}"

CLARIFY_SYS = """You help students of Uniwersytet Radomski (UR). The user asked something that depends on their situation, and some facts are still missing.
Write a short, warm clarification in {lang_name} (lang={lang}).
Rules:
- Do NOT answer the substantive question yet.
- Ask ONLY about these missing fields: {missing_labels}.
- 1–2 sentence intro why you ask, then a short numbered list (max {n} questions).
- Invite a single-sentence reply with an example fitting the topic ({topics}).
- No URLs, no invented rules, no legal advice.
{security_rules}
Known profile so far: {profile}
"""

SYSTEM = """You are a helpful campus information assistant for students of Kazimierz Pułaski University of Radom (Uniwersytet Radomski, UR).
Your job is to SAVE the student’s time: extract concrete rules from ŹRÓDŁA (who may apply, amounts, deadlines, documents, where to submit) so they rarely need to dig through PDFs themselves.
Tone: clear, calm, practical — like a well-informed staff member at Biuro Obsługi Studenta. Not a bureaucratic form, not a chatbot script.

HARD RULES:
1. Answer in {lang_name} (lang={lang}). Keep official names (UR, Biuro Obsługi Studenta, zarządzenie codes) when useful. If the user asks to switch language (“po polsku”, “на польській”, “in English”), switch language — do NOT treat that as a question about tuition “in the Polish language”.
2. Use ONLY the fragments in ŹRÓDŁA. No outside knowledge. ALWAYS first give every concrete fact that IS in the sources (eligibility yes/no for THIS profile, income thresholds, document lists, deadlines, submission channel, links). FORBIDDEN: an answer that only says you don’t know / contact BOS when ŹRÓDŁA contain a relevant section (e.g. “Stypendium dla cudzoziemców”, “obywatel Ukrainy”). Mention Biuro Obsługi Studenta / DWZ only as a short last-line tip when a personal decision or missing individual document remains — never instead of the rules.
3. Structure: (a) direct answer first, (b) conditions/exceptions for THIS student’s profile, (c) what to do next (documents, system, deadlines), (d) sources list. Use short paragraphs or bullets.
4. Cite claims with [n]. End with a sources heading in the answer language (Źródła / Sources / Джерела / Эх сурвалж) with URL + update date. Each URL once. Do not invent source numbers.
5. Mark “⚠️ may be outdated” ONLY for sources before 2024-01-01 or with no date. Never mark 2024+ as outdated. Quote amounts and deadlines only if present in sources, with academic year / ordinance (e.g. R-41/2025). Today: {today}. If a deadline already passed, say so.
6. For Polish citizens, full-time first-cycle study is often free — quote paid zł/euro amounts only when the source clearly applies to the user’s mode/level (e.g. niestacjonarne, second cycle, foreigners).
7. Describe rules for the user’s category only; mention other categories only as a brief aside.
8. Profile pobyt=ukr / PESEL UKR / ochrona czasowa: if ŹRÓDŁA mention citizens of Ukraine under the special act, you MUST state that they may apply for stypendium socjalne, plus income threshold, required oświadczenie/documents, and how to submit — do not claim “no provisions”.
9. No invented legal outcomes for an individual case; do not invent URLs.

{security_rules}"""

SLOT_LABEL = {
 "pl": {"status": "status / obywatelstwo", "tryb": "tryb studiów", "poziom": "poziom studiów", "rok": "rok studiów", "drugi_kierunek": "drugi kierunek lub dyplom", "niepelnosprawnosc": "orzeczenie o niepełnosprawności", "kierunek": "kierunek / grupa", "pobyt": "podstawa pobytu"},
 "en": {"status": "status / citizenship", "tryb": "full-time or part-time", "poziom": "study level", "rok": "year of study", "drugi_kierunek": "second programme or diploma", "niepelnosprawnosc": "disability certificate", "kierunek": "programme / group", "pobyt": "residence basis"},
 "uk": {"status": "статус / громадянство", "tryb": "форма навчання", "poziom": "рівень навчання", "rok": "рік навчання", "drugi_kierunek": "другий напрям або диплом", "niepelnosprawnosc": "інвалідність", "kierunek": "напрям / група", "pobyt": "підстава перебування"},
 "mn": {"status": "статус / иргэншил", "tryb": "сургалтын хэлбэр", "poziom": "түвшин", "rok": "курс", "drugi_kierunek": "хоёр мэргэжил эсвэл диплом", "niepelnosprawnosc": "хөгжлийн бэрхшээл", "kierunek": "мэргэжил / бүлэг", "pobyt": "оршин суух үндэслэл"},
}

def clarify_answer(lang, missing, question, history, topics, prof):
    """Natural LLM clarification when possible; template fallback otherwise."""
    if llm_enabled():
        labels = SLOT_LABEL.get(lang, SLOT_LABEL["pl"])
        miss_l = ", ".join(labels.get(m, m) for m in missing)
        prof_txt = ", ".join(f"{k}={v}" for k, v in prof.items()) or "—"
        sys = (CLARIFY_SYS.replace("{lang}", lang)
                          .replace("{lang_name}", LANG_NAME.get(lang, "polski"))
                          .replace("{missing_labels}", miss_l)
                          .replace("{n}", str(len(missing)))
                          .replace("{topics}", ", ".join(topics) or "general")
                          .replace("{profile}", prof_txt)
                          .replace("{security_rules}", SECURITY_RULES))
        msgs = [{"role": "system", "content": sys}] + _safe_history(history, 6) + [
            {"role": "user", "content": wrap_untrusted("USER_QUESTION", question)}
        ]
        try:
            return redact_secrets(call_llm(msgs, temperature=0.35)), "doprecyzowanie-llm"
        except Exception:
            pass
    return clarify_text(lang, missing), "doprecyzowanie"

def _safe_history(history, n=8):
    out = []
    for m in history[-n:]:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = redact_secrets(str(m.get("content", ""))[:3000])
        # Klient może podrobić role=assistant – zawsze traktuj treść historii jako dane
        label = "USER_MESSAGE" if role == "user" else "ASSISTANT_MESSAGE"
        content = wrap_untrusted(label, content)
        out.append({"role": role, "content": content})
    return out

def resolve_plan_faculty(profile, question=""):
    """Zwraca kod źródła planów (weif/wteii/…) albo None jeśli nieznany kierunek."""
    kier = (profile or {}).get("kierunek")
    if kier and kier in KIEROUNEK_FACULTY:
        return KIEROUNEK_FACULTY[kier]
    blob = (question or "").lower()
    if re.search(r"wteii|transport.*elektrotechn|wydzia[łl].*informat", blob):
        return "wteii"
    if re.search(r"weif|wydzia[łl]\s*ekonom", blob):
        return "weif"
    if re.search(r"\bwpia\b|wydzia[łl]\s*prawa", blob):
        return "wpia"
    if re.search(r"\bwm\b|wydzia[łl]\s*mechan", blob):
        return "wm"
    if re.search(r"wnminoz|wydzia[łl]\s*nauk\s*med", blob):
        return "wnminoz"
    if re.search(r"\bwfp\b|filologiczno", blob):
        return "wfp"
    return None

def plan_file_hits(faculty, profile=None, k=12):
    """Lista plików planu dla wydziału; opcjonalnie filtr po kierunku/roku w nazwie."""
    if IDX is None:
        load()
    files = []
    seen_u = set()
    for c in IDX["chunks"]:
        if c.get("source") != faculty or c.get("kind") != "file":
            continue
        if c["url"] in seen_u:
            continue
        seen_u.add(c["url"])
        files.append(c)
    kier = (profile or {}).get("kierunek")
    rok = (profile or {}).get("rok")
    # kody plików WEiF/WTEiI: I_E_=Ekonomia, FiR=Finanse, IN=Informatyka, E_=Elektrotechnika
    boost = {
        "ekonomia": r"ekonom|(?:^|/)I_E_|_E_\d",
        "finanse": r"finans|rachunk|FiR|_FiR_",
        "informatyka": r"\bIN[_-]|informat|(?:^|/)I?_?IN[_-]",
        "informatyka_techniczna": r"\bIT[_-]|technicz",
        "elektrotechnika": r"(?:^|/)[IE]?_?E[_-]\d|elektrotech",
        "transport": r"TiL|TIL|transport",
        "prawo": r"prawo|PR[_-]",
        "administracja": r"admin",
        "zarzadzanie": r"zarz[aą]dz|_Z_\d|(?:^|/)I_Z_",
        "ai_biznes": r"IAwB|inteligenc|AI",
        "analityka": r"analityk",
    }.get(kier)
    # rok 1 → sem 1–2, rok 2 → 3–4, rok 3 → 5–6
    sem_rx = None
    if rok and str(rok).isdigit():
        y = int(rok)
        sems = (2 * y - 1, 2 * y)
        sem_rx = re.compile(rf"({sems[0]}|{sems[1]})\s*sem", re.I)

    def rank(c):
        blob = (c.get("title") or "") + " " + (c.get("url") or "")
        hit_kier = 0 if (boost and re.search(boost, blob, re.I)) else 1
        hit_rok = 0 if (sem_rx and sem_rx.search(blob)) else 1
        return (hit_kier, hit_rok, c.get("title") or "")

    files.sort(key=rank)
    return files[:k]

def fmt_sources(hits):
    out = []
    for n, h in enumerate(hits, 1):
        out.append(f"[{n}] {h['title']} | URL: {h['url']} | aktualizacja: {h['modified'] or 'brak daty'} | nieaktualne: {'TAK' if outdated(h['modified']) else 'nie'}\n{h['text'][:2500]}")
    return "\n\n".join(out)

def outdated(m): return (not m) or m[:4] < "2024"

def merge_forced_hits(hits, forced, k=12):
    if not forced:
        return hits[:k]
    seen = {h["url"] for h in forced}
    merged = [dict(c, score=999 - i) for i, c in enumerate(forced)]
    merged += [h for h in hits if h["url"] not in seen]
    return merged[:k]

def ensure_canonical_hits(hits, topics, profile, q):
    """Quality gate: jeśli brak kanonicznych URL – dociągnij force + ewentualnie drugi search."""
    if IDX is None:
        load()
    for topic in topics:
        if topic == "plan":
            continue
        if hits_match_canonical(hits, topic):
            forced = force_topic_hits(topic, profile, k=4, chunks=IDX["chunks"])
            hits = merge_forced_hits(hits, forced)
            continue
        forced = force_topic_hits(topic, profile, k=5, chunks=IDX["chunks"])
        hits = merge_forced_hits(hits, forced)
        if not hits_match_canonical(hits, topic):
            pol = policy_for(topic)
            extra = (pol.get("query_extra") or "") + " " + (pol.get("canonical") or "").replace("|", " ")
            prefer = prefer_sources([topic])
            more = search(q + " " + extra, k=12, prefer=prefer, topics=[topic], profile=profile)
            hits = merge_forced_hits(more, forced)
    return hits[:12]

def call_llm(messages, temperature=0.25):
    prov = os.getenv("LLM_PROVIDER", "").lower(); key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")
    if prov == "gemini":
        import time
        key = os.getenv("GEMINI_API_KEY") or key
        chain = [m for m in [model, "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"] if m]
        last = None
        for m in dict.fromkeys(chain):
            for att in range(4):
                try:
                    r = httpx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", timeout=90,
                                   headers={"Authorization": f"Bearer {key}"},
                                   json={"model": m, "messages": messages, "temperature": temperature, "reasoning_effort": "low"})
                except httpx.TimeoutException as e:
                    last = e; break
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
                last = f"HTTP {r.status_code}"
                if r.status_code == 429: time.sleep(min(60, 5 * 2 ** att)); continue
                if r.status_code in (500, 503) and att < 1: time.sleep(4); continue
                break  # 404/400/powtarzające się 503 -> następny model
        raise RuntimeError(f"Gemini niedostępny ({last})")
    if prov == "anthropic":
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=120,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": model or "claude-sonnet-4-5", "max_tokens": 1400, "system": messages[0]["content"], "messages": messages[1:], "temperature": temperature})
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic niedostępny (HTTP {r.status_code})")
        return r.json()["content"][0]["text"]
    base = {"openai": "https://api.openai.com/v1", "xai": "https://api.x.ai/v1", "ollama": "http://localhost:11434/v1"}.get(prov) or os.getenv("LLM_BASE_URL")
    base = os.getenv("LLM_BASE_URL", base)
    # block clearly non-http(s) bases to reduce SSRF risk if env is mis-set
    if not (base or "").startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise RuntimeError("LLM_BASE_URL niedozwolony")
    r = httpx.post(base + "/chat/completions", timeout=120, headers={"Authorization": f"Bearer {key}"},
                   json={"model": model or "gpt-4o-mini", "messages": messages, "temperature": temperature})
    if r.status_code >= 400:
        raise RuntimeError(f"LLM niedostępny (HTTP {r.status_code})")
    return r.json()["choices"][0]["message"]["content"]

def llm_enabled():
    p = os.getenv("LLM_PROVIDER", "").lower()
    if p == "gemini": return bool(os.getenv("GEMINI_API_KEY") or os.getenv("LLM_API_KEY"))
    return bool(p) and (bool(os.getenv("LLM_API_KEY")) or p == "ollama")

PROF_LABEL = {
 "pl": {"status": "status", "tryb": "tryb", "poziom": "poziom", "rok": "rok", "drugi_kierunek": "drugi kierunek / dyplom", "niepelnosprawnosc": "orzeczenie o niepełnosprawności", "kierunek": "kierunek/grupa", "pobyt": "pobyt"},
 "en": {"status": "status", "tryb": "mode", "poziom": "level", "rok": "year", "drugi_kierunek": "second programme / diploma", "niepelnosprawnosc": "disability certificate", "kierunek": "programme/group", "pobyt": "residence"},
 "uk": {"status": "статус", "tryb": "форма", "poziom": "рівень", "rok": "рік", "drugi_kierunek": "другий напрям / диплом", "niepelnosprawnosc": "інвалідність", "kierunek": "напрям/група", "pobyt": "перебування"},
 "mn": {"status": "статус", "tryb": "хэлбэр", "poziom": "түвшин", "rok": "курс", "drugi_kierunek": "хоёр мэргэжил / диплом", "niepelnosprawnosc": "хөгжлийн бэрхшээл", "kierunek": "мэргэжил/бүлэг", "pobyt": "оршин суух"},
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
    question = redact_secrets((question or "").strip())
    history = [
        {"role": m.get("role"), "content": redact_secrets(str(m.get("content", ""))[:3000])}
        for m in (history or [])
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
    ]
    hist_user = "\n".join(m["content"] for m in history if m["role"] == "user")
    lang = detect_lang(question, hist_user, latest=question)
    # Deterministyczna bramka: klucze API, konta wykładowców, jailbreak – bez wywołania LLM
    if is_security_probe(question) or is_security_probe(hist_user[-500:], question):
        return dict(clarify=False, mode="security", sources=[], profile={}, lang=lang,
                    answer=refuse_message(lang))
    topics, prof, missing = needed(question, hist_user)
    if missing:
        text, mode = clarify_answer(lang, missing, question, history, topics, prof)
        return dict(clarify=True, mode=mode, sources=[], profile=prof, lang=lang, answer=text)
    base_q = question
    if history:
        prev = [m["content"] for m in history if m["role"] == "user" and any(re.search(rx, m["content"], re.I) for _, rx, _ in TOPICS)]
        if prev: base_q = prev[-1] + " " + question
    stipend_topics = {"stypendium_socjalne", "stypendium_rektora", "stypendium_niepeln", "dwa_kierunki", "doktoranckie"}
    if not (set(topics) & stipend_topics):
        q = base_q + " " + " ".join(
            str(v) for k, v in prof.items() if k in ("status",) and v in ("cudzoziemiec", "bezpanstwowiec", "doktorant")
        )
    else:
        q = base_q
    q += " " + " ".join(TOPIC_PL_QUERY[t] for t in topics if t in TOPIC_PL_QUERY and t != "cudzoziemcy")
    q += " " + query_extras(topics, prof)
    fac = resolve_plan_faculty(prof, base_q) if "plan" in topics else None
    tp = [t for t in topics if t != "cudzoziemcy"] or topics
    prefer = prefer_sources(tp, fac=fac)
    if tp is not topics:
        q = re.sub(r"(?i)\b(jako\s+)?cudzoziem\w*|international\s+student|foreign\s+student|інозем\w*|гадаад\s+оюутан", " ", q)
    if "plan" in topics and fac:
        q += " " + FACULTY_LABEL.get(fac, fac) + " plan zajęć"
        if prof.get("kierunek") == "weif_wydzial":
            q += " Ekonomia Finanse i rachunkowość (wydział WEiF – wybierz konkretny kierunek na stronie)"
        elif prof.get("kierunek"):
            q += " " + prof["kierunek"]
    hits = search(q, k=12, prefer=prefer, topics=topics, profile=prof)
    hits = ensure_canonical_hits(hits, topics, prof, q)
    if "plan" in topics:
        if fac:
            files = plan_file_hits(fac, prof, k=20)
            url = FACULTY_PLAN_URL[fac]
            label = FACULTY_LABEL.get(fac, fac)
            if files:
                lst = "\n".join(
                    f"- {(c['title'].split(' – ')[-1])} → {c['url']} (aktualizacja: {c.get('modified') or '—'})"
                    for c in files
                )
                note = ""
                if fac == "wteii":
                    note = " Kody plików WTEiI: IN=Informatyka, IT=Informatyka techniczna, E=Elektrotechnika (NIE Ekonomia!), TiL/TIL=Transport i logistyka."
                if prof.get("kierunek") == "weif_wydzial":
                    note += (" „Ekonomia i Finanse” to nazwa wydziału (WEiF). Konkretne kierunki: Ekonomia, "
                             "Finanse i rachunkowość, Analityka gospodarcza, Zarządzanie, AI w biznesie – wybierz plik na stronie.")
                hits = [dict(
                    title=f"{label} – lista plików z planami zajęć.{note}",
                    url=url, modified=max((c.get("modified") or "") for c in files) or None,
                    text=lst, source=fac, kind="list",
                )] + [h for h in hits if h.get("source") == fac or h.get("kind") == "list"][:6]
            else:
                hits = [dict(
                    title=f"{label} – plany zajęć (brak PDF w indeksie asystenta)",
                    url=url, modified=None,
                    text=(f"W indeksie asystenta nie ma jeszcze plików PDF planu dla {label}. "
                          f"Aktualny plan zajęć pobierz ze strony wydziału: {url}. "
                          "Nie podawaj planów innego wydziału."),
                    source=fac, kind="list",
                )] + [h for h in hits if h.get("source") == fac][:4]
        else:
            catalog = "\n".join(f"- {FACULTY_LABEL[s]} → {FACULTY_PLAN_URL[s]}" for s in sorted(FACULTY_PLAN_URL))
            hits = [dict(
                title="Plany zajęć UR – strony wydziałów (wybierz swój kierunek)",
                url="https://uniwersytetradom.pl/", modified=None,
                text="Nie znam jeszcze Twojego kierunku, więc nie wskazuję konkretnego PDF. Oficjalne plany:\n" + catalog,
                source="student", kind="list",
            )] + hits[:5]
    srcs = [dict(n=i, title=h["title"], url=h["url"], modified=h["modified"], outdated=outdated(h["modified"]), snippet=h["text"][:400]) for i, h in enumerate(hits, 1)]
    labels = PROF_LABEL.get(lang, PROF_LABEL["pl"])
    prof_txt = ", ".join(f"{labels.get(k, k)}: {v}" for k, v in prof.items() if k in labels) or "—"
    if llm_enabled():
        import datetime
        sys = (SYSTEM.replace("{today}", datetime.date.today().isoformat())
                     .replace("{lang}", lang)
                     .replace("{lang_name}", LANG_NAME.get(lang, "polski"))
                     .replace("{security_rules}", SECURITY_RULES))
        msgs = [{"role": "system", "content": sys}] + _safe_history(history, 8) + [{"role": "user", "content":
                f"PROFIL STUDENTA: {prof_txt}\nLANG: {lang}\nTEMATY: {', '.join(topics) or '—'}\n"
                "QUALITY: Use canonical UR pages from ŹRÓDŁA first. Give eligibility/amounts/steps when present. "
                "Never answer with only “contact BOS” if fragments already answer the question.\n\n"
                f"ŹRÓDŁA:\n{fmt_sources(hits)}\n\n"
                + wrap_untrusted("USER_QUESTION", question)
                + "\n\nNapisz konkretną, naturalną odpowiedź według zasad systemowych."}]
        try:
            out = redact_secrets(call_llm(msgs, temperature=0.3))
            return dict(clarify=False, mode="llm", sources=srcs, profile=prof, lang=lang, answer=out)
        except Exception as e:
            err = LLM_ERR.get(lang, LLM_ERR["pl"]).format(e=safe_error(e))
    else:
        err = ""
    warn_l = OUTDATED.get(lang, OUTDATED["pl"])
    lines = [err + NO_LLM.get(lang, NO_LLM["pl"]).format(prof=prof_txt)]
    for s, h in zip(srcs[:4], hits[:4]):
        warn = f" ⚠️ {warn_l}" if s["outdated"] else ""
        snip = re.sub(r"\s+", " ", h["text"])[:500]
        lines.append(f"\n[{s['n']}] **{s['title']}** ({s['modified'] or '—'}{warn})\n„{snip}…”")
    lines.append(f"\n{SRC_HDR.get(lang, 'Źródła')}:\n" + "\n".join(f"[{s['n']}] {s['url']} – {s['modified'] or '—'}" for s in srcs[:4]))
    return dict(clarify=False, mode="wyszukiwanie", sources=srcs, profile=prof, lang=lang,
                answer=redact_secrets("\n".join(lines)))
