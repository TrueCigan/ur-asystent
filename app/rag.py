"""Logika asystenta: doprecyzowanie sytuacji studenta, wyszukiwanie hybrydowe, odpowiedź z cytatami (PL/EN/UK/MN)."""
import os, re, gzip, json, math, collections, numpy as np, scipy.sparse as sp, httpx
from index import tokens, norm, D, char_ngrams, char_vec
from security import (
    SECURITY_RULES, is_security_probe, refuse_message, wrap_untrusted,
    redact_secrets, safe_error, strip_untrusted_wrappers,
)
from topic_policy import (
    TOPIC_POLICY, apply_policy_scores, force_topic_hits, hits_match_canonical,
    query_extras, prefer_sources, policy_for,
)
from lang import (
    LANG_NAME, map_policy, resolve_session_lang, output_lang_ok,
    sticky_lang_from_user_turns,
)
from deadlines import deadline_passed_note, strip_llm_deadline_notes
from decimal import Decimal
from facts import (
    load_facts, select_facts, render_facts_block, amounts_in, fact_amounts,
    extract_income, computed_income_line, income_group,
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

# ---------- język (PL / EN / UK / MN) — sticky sesja; RU → UK (polityka) ----------
# LANG_NAME imported from lang.py

def detect_lang(*parts, latest="", session_lang=None):
    """Compat wrapper for harness + callers. Sticky session language; never returns ru."""
    turns = []
    for p in parts:
        if not p or p == latest:
            continue
        turns.extend(t for t in re.split(r"\n+", p) if t.strip())
    state = map_policy(session_lang) if session_lang else None
    for t in turns:
        state = resolve_session_lang(state, t)
    msg = latest if latest is not None and latest != "" else (turns[-1] if turns else "")
    return resolve_session_lang(state, msg) if msg or state else "pl"

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
  ("doktorant", r"doktorant|doktoranc|doctoral\s*school|phd\s*student|i'?m\s*a?\s*phd|doctoral\s*student|школ\w*\s*доктор|докторант|докторантур"),
  ("bezpanstwowiec", r"bezpa[nń]stw|bez obywatel|stateless|без\s*громадян|апатрид|харьяалалгүй|иргэншилгүй"),
  ("pl", r"\b(a\s+pole\b|i\s*am\s*(a\s*)?pole\b|\bpole\b|polak|polk[aąi]|\bpola[kc]\b|polish\s*citizen|i(?:'?m|\s+am)\s+polish|we\s+are\s+polish|citizen\s+of\s+poland|nationality\s+polish|from\s+poland|obywatel\w*\s*polsk|polskie\s*obywatel|jestem\s+z\s+polski|z\s+polski\s+jestem|dow[oó]d\w*\s+(mam\s+)?polsk|polsk\w*\s+dow[oó]d|polsk\w*\s+paszport|urodzi\w+\s+w\s+(polsce|radomiu)|громадянин\w*\s*польщ|я\s+поляк|польськ\w*\s*громадян|гражданин\w*\s*польш|из\s*польш|\bполяк\b|\bполька\b|польш\s*иргэн|би\s+польш|польш\s*улсын\s*иргэн)"),
  ("cudzoziemiec", r"cudzozie|obcokraj|zagranicz|international\s*student|foreign\s*student|\bforeigner\b|i'?m\s*a?\s*foreign|i\s*am\s*from\s+(?!poland|polsk)|from\s+(india|china|ukraine|belarus|vietnam|nigeria|turkey|georgia)|non[- ]polish|residence\s*permit|pole'?s?\s*card|temporary\s*protection|ukrai|ukraine|belarus|bia[lł]oru|karta\s*polaka|kart\w*\s*pobytu|ochron\w*\s*czasow|uchod[zź]|інозем|громадян\w*\s*украї|з\s*україн|карта\s*поляка|карт\w*\s*побут\w*|тимчасов\w*\s*захист|біжен|иностранец|карт\w*\s*побыт\w*|временн\w*\s*защит|гадаад\s*оюутан|гадаадын\s*иргэн|оршин\s*суух|польшийн\s*карт|дүрвэгч|украин"),
 ],
 "tryb": [
  ("stacjonarne", r"(?<!nie)stacjonar|\bstationary\b|\bstacionar|dzienn|\bdaily\b|full[-\s]?time|on[- ]campus|pe[lł]ny\s*etat|денн\w*|стаціонар\w*|дневн\w*|\bочн\w*\b|өдрийн|бүтэн\s*цаг"),
  ("niestacjonarne", r"niestacjonar|zaoczn|weekend|weekends?\s*only|part[-\s]?time|extramural|заочн\w*|вечірнь|вихідн|не\s*вдень|zjazd|sobot|niedziel|эчнээ|цагийн\s*сургалт"),
 ],
 "poziom": [
  ("SD", r"szko[lł]\w*\s*doktorsk|doctoral\s*school|phd\b|doktoranc|докторантур|докторант(?!\w)"),
  ("jednolite", r"jednolit|long[-\s]?cycle|undivided\s*master|єдин\w*\s*магістер|нэгдсэн\s*магистр"),
  ("II", r"\bii\s*stop|\b2\s*stop|drugi\w*\s*stop|second[-\s]?cycle|master'?s?\b|\bmgr\b|magisterk|магістратур|graduate\s*program|magist(?!.*jednolit)|uzupe[lł]niaj|іі\s*ступ|\b2\s*ступ|другого\s*ступ|магістр(?:атур)?|магистр(?:атур)?|ii\s*зэрэг|2\s*зэрэг"),
  ("I", r"\bi\s*stop|\b1\s*stop|pierwsz\w*\s*stop|first[-\s]?cycle|1st\s*degre|first\s*degre|bachelor|bachel?or|undergrad|licencj|in[zż]ynier|і\s*ступ|\b1\s*ступ|перш\w*\s*ступ|бакалавр\w*|інженер|i\s*зэрэг|1\s*зэрэг"),
 ],
 "rok": [
  ("1", r"(\b1\s*(rok|year|рік|курс|жил)\b|\byear\s*1\b|\b1(st)?\s*year\b|\bpierwsz\w*\s*rok|\bfirst\s*year|\bfreshman|\bперш\w*\s*рік|\b(?:na|jestem na)\s+i\s+roku|\bpierwszoroczn|^\s*1\s*$)"),
  ("2", r"(\b2\s*(rok|year|рік|курс|жил)\b|\byear\s*2\b|\b2(nd)?\s*year\b|\bii\s*rok|\bdrugi\w*\s*rok|\bsecond\s*year|\bsophomore|\bдруг\w*\s*рік|\b(?:na|jestem na)\s+ii\s+roku|^\s*2\s*$)"),
  ("3", r"(\b3\s*(rok|year|рік|курс|жил)\b|\byear\s*3\b|\b3(rd)?\s*year\b|\biii\s*rok|\btrzeci\w*\s*rok|\bthird\s*year|\bтрет\w*\s*рік|\b(?:na|jestem na)\s+iii\s+roku|^\s*3\s*$)"),
  ("4", r"(\b4\s*(rok|year|рік|курс|жил)\b|\byear\s*4\b|\b4(th)?\s*year\b|\biv\s*rok|\bczwart\w*\s*rok|\b(?:na|jestem na)\s+iv\s+roku|^\s*4\s*$)"),
  ("5", r"(\b5\s*(rok|year|рік|курс|жил)\b|\byear\s*5\b|\b5(th)?\s*year\b|\bv\s*rok|\bpi[aą]t\w*\s*rok|^\s*5\s*$)"),
  ("6", r"(\b6\s*(rok|year|рік|курс|жил)\b|\byear\s*6\b|\b6(th)?\s*year\b|^\s*6\s*$)"),
 ],
 "drugi_kierunek": [
  # „nie” najpierw – unikaj fałszywego „tak” przy „nie posiadam dyplomu” / „no second degree”
  ("nie", r"(?i)(?:^\s*(nie|no|ні|үгүй)\.?\s*$|(?:,\s*|\s+)(nie|no|ні)\.?\s*$|^\s*(ні|nie|no)\b.{0,60}не\s*навч|jedyn\w*\s*kierun|jeden\s*kierun|jednokierunkow|\bjedno\b|tylko\s*jed|tylko\s+ten\s+kierun|tylko\s*(w\s*)?(uczelni|na\s*ur|tu)\b|jedyn\w*\s*uczel|only\s*one(?:\s*,?\s*no)?|only\s*one\s*(program|programme|major|degree|field)|just\s*one\s*(program|programme|major|degree)|single\s*(major|program|programme)|one\s*program\s*only|(?:one|single)\s+(?:major|programme|program)\s+only|nothing\s*else|no\s*(?:second|other)\s*(?:degree|program|programme|major|field)|(?:do\s*not|don'?t)\s+study\s+(?:a\s+)?(?:second|another|other)|no\s+(?:previous|prior|other)\s+(?:degree|diploma)|without\s*(?:a\s*)?second\s*(?:degree|program|programme)|nie\s*studiuj\w*\s*(r[oó]wnoleg|drug)|nie\s*mam\s+drug|first\s*degree\s*only|nie\s*(?:mam|posiadam)\s*(?:żadn\w*\s*)?(?:innego|drugiego|uko|dyplom)|brak\s*dyplom|żadn\w*\s*dyplom|bez\s*dyplom|nie\s*mam\s*jeszcze\s*(żadn\w*\s*)?dyplom|один\s*(напрям|спеціальн)|лише\s*один|тільки\s*один|тільки\s*(в|на)\s*цьому|(?:^|[,;]\s*)(jeden|jedna|jeden|jedno|один|одна|one)\s*(?:$|[,;.])|нігде\s*більше\s*не\s*навч|ніде\s*більше|не\s*навча\w*\s*(більше|ніде|нігде|на\s*друг)|не\s*маю\s*(жодн\w*\s*|інш\w*\s*)?диплом|немаю\s*(жодн\w*\s*|інш\w*\s*)?диплом|немає\s*(жодн\w*\s*|інш\w*\s*)?диплом|немає\s*(інш\w*\s*)?диплом|нема\b|в\s*мене\s*нема|диплом\w*\s*не\s*ма(ю|є)|диплом\w*\s*цього\s*рівн|інш\w*\s*диплом\w*\s*не|друг\w*\s*напрям\w*\s*чи\s*диплом\w*\s*не\s*ма|нет\s*втор|без\s*диплом|только\s*одно|зөвхөн\s*нэг|ганц\s*мэргэжил)"),
  ("tak", r"(?i)(?:(?:mam|posiadam)\s+(?:ju[zż]\s+)?(?:uko[nń]czon\w*\s+)?(?:tytu[lł]|licencjat|in[zż]ynier|magister|dyplom)(?!\w)|(?:studiuj[eę]|mam)\s+drugi\w*\s*kierun|dw[ao]\w*\s*kierun|r[oó]wnoleg|second\s*(degree|major|program|programme|field)|double\s*major|parallel\s*stud|already\s*(graduated|have\s*a\s*degree)|completed\s*(studies|a\s*degree)|ju[zż]\s*uko[nń]czy|(?:навча\w*|маю)\s+друг\w*\s*(напрям|спеціальн|спеціал)|паралельн|вже\s*(маю|закінч)\w*\s*диплом|хоёр\s*мэргэжил|зэрэгцээ|дипломтой|төгссөн)"),
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
 ("stypendium_socjalne", r"socjaln|zapomog|dochod|pomoc\w*\s*materialn|[sś]wiadcze|social\s*scholarship|\bsocial\b(?=.{0,40}scholarship)|scholarship\s*for\s*foreign|maintenance\s*grant|need[-\s]?based|стипенд\w*\s*соціал|соціальн\w*\s*стипенд|социальн\w*\s*стипенд|стипенд\w*\s*для\s*(иностран|cudzoziem)|матеріальн\w*\s*допомог|тэтгэлэг|нийгмийн\s*тэтгэлэг|амьжиргааны", ["status", "drugi_kierunek", "tryb", "poziom"]),
 ("stypendium_rektora", r"rektor|najlepsz|[sś]redni\w*\s*ocen|rector'?s?\s*scholarship|\brector\b(?=.{0,40}scholarship)|merit\s*scholarship|academic\s*excellence|науков\w*\s*досягнен|стипенд\w*\s*ректор|ректор|гол\s*тэтгэлэг|ректорын\s*тэтгэлэг", ["status", "drugi_kierunek", "poziom"]),
 ("stypendium_niepeln", r"niepe[lł]nospraw|disability\s*scholarship|інвалід|инвалидн|хөгжлийн\s*бэрхшээл", ["status", "niepelnosprawnosc", "drugi_kierunek"]),
 ("doktoranckie", r"doktorant|doktorsk|doktoranck|phd\b|doctoral|doctoral\s*stipend|докторант|докторантур|докторск\w*\s*стипенд|стипенд\w*\s*доктор", ["status"]),
 ("akademik", r"akademik|dom\w*\s*studen|miejsce\s*w\s*akadem|dormitor|student\s*hous|residence\s*hall|общежит|гуртожит|дотуур\s*байр", []),
 ("oplaty", r"op[lł]at|czesne|p[lł]aci[cć]|bezp[lł]atn|tuition|fees?\b|english\s*program|program\w*\s*in\s*english|cost\s*of\s*stud|price\s*of\s*stud|(?:ile\s*kosztuj|how\s*much|скільки|сколько|хэд).{0,40}(?:stud|czesn|tuition|fee|навч|сургалт|програм|opłat|english|business)|оплат|вартіст|кошту|цін[ауи]\s*навч|плата\s*за\s*навч|төлбөр|сургалтын\s*төлбөр", ["status", "tryb", "poziom"]),
 ("erasmus", r"erasmus|wyjazd|wymian|mobilno|exchange\s*program|study\s*abroad|мобільніст|обмін|солилцоо|гадаадад\s*суралц", ["status", "poziom", "rok"]),
 ("plan", r"plan\w*\s*zaj|rozk[lł]ad|harmonogram\s*zaj|zaj[eę]cia\s*w|kiedy\s*mam\s*zaj|timetable|class\s*schedule|course\s*schedule|розклад|розклад\s*занят|хичээлийн\s*хуваарь|хуваарь", ["kierunek", "tryb", "poziom", "rok"]),
 ("cudzoziemcy", r"cudzozie|bezpa[nń]stw|bez\s*obywatel|karta\s*polaka|kart\w*\s*pobytu|legaliz|wiz\w*\b|ochron\w*\s*czasow|international\s*student|foreign\s*student|residence\s*permit|інозем|без\s*громадян|карта\s*поляка|гадаад\s*оюутан|оршин\s*суух", ["status"]),
 ("dwa_kierunki", r"dw[ao]\w*\s*kierun|drugi\w*\s*kierun|r[oó]wnoleg|second\s*(major|program|programme)|double\s*major|друг\w*\s*напрям|паралельн(?!\w*\s*не)|хоёр\s*мэргэжил|зэрэгцээ", ["status", "drugi_kierunek", "tryb"]),
]

TOPIC_PL_QUERY = {
 "stypendium_socjalne": "stypendium socjalne pomoc materialna dochód",
 "stypendium_rektora": "stypendium rektora średnia ocen",
 "stypendium_niepeln": "stypendium dla osób niepełnosprawnych",
 "doktoranckie": "stypendium doktoranckie szkoła doktorska",
 "akademik": "domy studenckie akademik opłaty za miejsce termin składania wniosków",
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
        "Можна однією фразою, напр. «громадянин Польщі, денна, І ступінь, тільки цей напрям, без диплома»."),
 "mn": ("Хариулахаас өмнө – UR-ийн дүрэм таны нөхцөл байдлаас хамаарна. Тодруулна уу:",
        "Нэг өгүүлбэрээр хариулж болно, ж.нь. «оршин суух зөвшөөрөлтэй гадаадын оюутан, өдрийн, I зэрэг, 2-р курс, нэг мэргэжил»."),
}

def _negated_before(text, start, window=28):
    """True if a negation word sits in the few tokens before `start`."""
    pre = (text or "")[max(0, start - window):start]
    return bool(re.search(
        r"(?i)\b(no|not|don'?t|do\s+not|nie|ні|не|нема|without|bez)\b",
        pre,
    ))


def extract_profile(text, conflicts_out=None):
    t = text.lower()
    prof = {}
    for slot, opts in SLOT_OPTS.items():
        if slot == "drugi_kierunek":
            hit_nie = hit_tak = None
            for val, rx in opts:
                m = re.search(rx, t, re.I)
                if not m:
                    continue
                if val == "tak" and _negated_before(t, m.start()):
                    continue  # "do not study a second programme" etc.
                if val == "nie":
                    hit_nie = m
                elif val == "tak":
                    hit_tak = m
            if hit_nie and hit_tak:
                prof["drugi_kierunek"] = "nie"
                if conflicts_out is not None:
                    conflicts_out.append({"slot": "drugi_kierunek", "old": "tak", "new": "nie", "reason": "negation"})
            elif hit_nie:
                prof["drugi_kierunek"] = "nie"
            elif hit_tak:
                prof["drugi_kierunek"] = "tak"
            continue
        for val, rx in opts:
            if re.search(rx, t, re.I):
                prof[slot] = val
                break
    # Podstawa pobytu — karta pobytu NIE jest automatycznie „ochrona UKR” (BUG-R2-06)
    has_ukr_protection = bool(re.search(
        r"pesel\s*ukr|\bukr\b|ochron\w*\s*czasow|temporary\s*protection|"
        r"specjaln\w*\s*ustaw\w*\s*ukrain|тимчасов\w*\s*захист|временн\w*\s*защит",
        t, re.I,
    ))
    has_karta_pobytu = bool(re.search(
        r"pobyt\w*\s*czasow|temporary\s*resid|kart\w*\s*pobytu|"
        r"карт\w*\s*побут\w*|карт\w*\s*побыт\w*|residence\s*permit|оршин\s*суух",
        t, re.I,
    ))
    if has_ukr_protection and not has_karta_pobytu:
        prof["pobyt"] = "ukr"
        prof.setdefault("status", "cudzoziemiec")
    elif re.search(r"kart\w*\s*polaka|pole'?s?\s*card|карта\s*поляка", t, re.I):
        prof["pobyt"] = "karta_polaka"
        prof.setdefault("status", "cudzoziemiec")
    elif re.search(r"pobyt\w*\s*sta[lł]|permanent\s*resid|сталий\s*побут|постоянн\w*\s*пребыв", t, re.I):
        prof["pobyt"] = "pobyt_staly"
        prof.setdefault("status", "cudzoziemiec")
    elif has_karta_pobytu:
        prof["pobyt"] = "pobyt_czasowy"
        prof.setdefault("status", "cudzoziemiec")
    elif re.search(r"громадян\w*\s*украї|з\s*україн|гражданин\w*\s*украин|from\s*ukraine", t, re.I):
        # obywatelstwo UA bez PESEL UKR / ochrony → cudzoziemiec, bez wymuszania „ochrona czasowa”
        prof.setdefault("status", "cudzoziemiec")
    # krótkie tak/nie jako uzupełnienie ostatniego slotu (drugi_kierunek / niepełnosprawność)
    if re.match(r"^\s*(tak|yes|так|тийм)\s*\.?\s*$", t, re.I):
        prof.setdefault("drugi_kierunek", "tak")
    if re.match(r"^\s*(nie|no|ні|үгүй)\s*\.?\s*$", t, re.I):
        prof.setdefault("drugi_kierunek", "nie")
    # „nie, 1” przy clarify (drugi kierunek + I stopień)
    if re.match(r"^\s*(nie|no|ні)\s*,\s*1\s*$", t, re.I):
        prof["drugi_kierunek"] = "nie"
        prof.setdefault("poziom", "I")
    # „Очна, ні” / „stacjonarne, nie” – drugi slot w krótkiej odpowiedzi
    if re.search(r"(?:,|;)\s*(nie|no|ні|үгүй)\s*\.?\s*$", t, re.I):
        prof.setdefault("drugi_kierunek", "nie")
    if re.search(r"(?:,|;)\s*(tak|yes|так|тийм)\s*\.?\s*$", t, re.I):
        prof.setdefault("drugi_kierunek", "tak")
    # Negacja dyplomu/2. kierunku wygrywa z echo pytania („drugiego kierunku czy…”)
    if re.search(
        r"(?i)(nie\s*mam|nie\s*posiadam|не\s*маю|немаю|немає|в\s*мене\s*нема|brak\s*dyplom|"
        r"інш\w*\s*диплом\w*\s*не|диплом\w*\s*не\s*ма(ю|є)|диплом\w*\s*цього\s*рівн|"
        r"тільки\s*(в|на)\s*цьому|tylko\s*(w\s*)?(tej\s*)?(uczelni|na\s*ur)|"
        r"нігде\s*більше|ніде\s*більше|jedyn\w*\s*kierun|jednokierunkow|один\s*напрям|"
        r"nothing\s*else|no\s*(?:second|other)\s*(?:degree|program|programme)|"
        r"^\s*(ні|nie|no)\b.{0,80}(не\s*навч|диплом|напрям|kierun|dyplom))",
        t,
    ):
        prof["drugi_kierunek"] = "nie"
    # Samo „ні/nie/no” po dopytaniu o 2. kierunek – zawsze zamyka slot
    if re.match(r"^\s*(nie|no|ні|үгүй)\b", t, re.I) and not re.search(
        r"(?i)(mam\s+drug|posiadam\s+dyplom|маю\s+друг|маю\s+диплом|yes\s+i\s+have)", t
    ):
        if len(t) < 80 or re.search(r"(?i)диплом|напрям|kierun|dyplom|навч|stud|degree|program", t):
            prof["drugi_kierunek"] = "nie"
    # Doktorant ⇒ poziom SD; NIE wymyślaj tryb/rok (BUG-05)
    if prof.get("status") == "doktorant":
        prof.setdefault("poziom", "SD")
    if prof.get("poziom") == "SD":
        prof.setdefault("status_doktor", True)
    if re.search(r"drugi\w*\s*kierun|dw[ao]\w*\s*kierun|r[oó]wnoleg|second\s*(major|program|programme)|double\s*major|друг\w*\s*напрям|хоёр\s*мэргэжил", t, re.I) and \
       re.search(r"czy\s*(mog|moż)|can\s*i|is\s*it\s*possible|чи\s*мож|болох\s*уу", t, re.I):
        prof.setdefault("drugi_kierunek", "pytanie")
    return prof

_BENEFIT_TOPICS = {
    "stypendium_socjalne", "stypendium_rektora", "stypendium_niepeln",
    "oplaty", "akademik", "erasmus", "doktoranckie", "dwa_kierunki", "plan",
}
_STIPEND_TOPICS = {
    "stypendium_socjalne", "stypendium_rektora", "stypendium_niepeln", "doktoranckie",
}

def merge_profile_from_turns(history_text, question, conflicts_out=None):
    """Parsuj każdą wypowiedź osobno – kotwice ^nie$ działają na turę, nie na sklejony blob."""
    prof = {}
    for part in [p.strip() for p in re.split(r"\n+", history_text or "") if p.strip()]:
        prof.update(extract_profile(part, conflicts_out=conflicts_out))
    prof.update(extract_profile(question or "", conflicts_out=conflicts_out))
    return prof

def _benefit_topics_in_order(text):
    """Kolejność wzmianek benefit-tematów w tekście (od lewej)."""
    found = []
    for n, rx, s in TOPICS:
        if n not in _BENEFIT_TOPICS:
            continue
        for m in re.finditer(rx, text, re.I):
            found.append((m.start(), n, s))
    found.sort(key=lambda x: x[0])
    # unikalne z zachowaniem pierwszej pozycji; last() bierzemy z końca listy wystąpień
    return found

def _primary_benefit_topic(question, candidates):
    """Jeden temat do sticky historii – ostatnia wzmianka / kontrast (nie faworyzuj akademika)."""
    if len(candidates) == 1:
        return candidates[0]
    q = question or ""
    names = {n for n, _ in candidates}
    # „socjalne już jasne, a rektor?” / „interesuje mnie rektora”
    if "stypendium_rektora" in names and re.search(
        r"(?i)(rektor|ректор)|(socjal\w*|соціальн\w*).{0,50}(zrozum|jasn|ok|зрозум|ясн).{0,40}(rektor|ректор)"
        r"|(nie\s+socjal)|(а\s+що\s+стосовно\s+ректор)|(interesuje.{0,20}rektor)",
        q,
    ):
        return next(t for t in candidates if t[0] == "stypendium_rektora")
    # akademik + „ile kosztuje” bez stypendium/czesne → akademik
    if "akademik" in names and not (names & (_STIPEND_TOPICS | {"oplaty"})):
        return next(t for t in candidates if t[0] == "akademik")
    ordered = _benefit_topics_in_order(q)
    for _pos, n, s in reversed(ordered):
        if n in names:
            return (n, s)
    return candidates[0]

def _order_benefit_topics(question, cur_benefit):
    """Wszystkie benefit-tematy z bieżącej wiadomości (BUG-R2-04 multi-topic)."""
    names = {n for n, _ in cur_benefit}
    by_name = {n: s for n, s in cur_benefit}
    ordered, seen = [], set()
    for _pos, n, s in _benefit_topics_in_order(question):
        if n in names and n not in seen:
            ordered.append((n, by_name.get(n, s)))
            seen.add(n)
    for n, s in cur_benefit:
        if n not in seen:
            ordered.append((n, s))
            seen.add(n)
    return ordered

_DWA_KIER_NEG = (
    r"(?i)паралельн\w*\s*не|не\s+навча\w*.{0,20}паралел|"
    r"nie\s+(studiuj\w*\s*)?r[oó]wnoleg|równolegle\s*nie|"
    r"nie\s+mam\s+drug|nie\s+mam\s+żadn|nie\s+posiadam\s+dyplom|"
    r"no\s+second\s+(program|degree|major)|nothing\s+else|nic\s+wi[eę]cej|"
    r"jednokierunkow|tylko\s+jeden|tylko\s+ten\s+kierun|один\s+напрям|тільки\s+один|"
    r"друг\w*\s*напрям\w*\s*нема|нема\s*.{0,20}друг|диплом\w*\s*.{0,20}не\s*ма|не\s*маю\s*.{0,15}диплом"
)

def _drop_negated_dwa_kierunki(topics, text):
    if any(n == "dwa_kierunki" for n, _ in topics) and re.search(_DWA_KIER_NEG, text or ""):
        return [(n, s) for n, s in topics if n != "dwa_kierunki"]
    return topics

def _recent_benefits_from_history(history_text):
    """Wszystkie benefit-tematy z ostatniej merytorycznej wiadomości (multi-topic sticky)."""
    if not history_text:
        return []
    parts = [p.strip() for p in re.split(r"\n+", history_text) if p.strip()]
    for part in reversed(parts):
        hits = [(n, s) for n, rx, s in TOPICS if n in _BENEFIT_TOPICS and re.search(rx, part, re.I)]
        hits = _drop_negated_dwa_kierunki(hits, part)
        if hits:
            return _order_benefit_topics(part, hits)
    return []

def _recent_benefit_from_history(history_text):
    """Compat: pojedynczy sticky (ostatni z multi)."""
    many = _recent_benefits_from_history(history_text)
    return many[-1] if many else None

def needed(question, history_text):
    q = question.lower()
    topics = [(n, s) for n, rx, s in TOPICS if re.search(rx, q, re.I)]
    # Negacja drugiego kierunku ≠ pytanie o dwa kierunki (BUG-R2-04)
    topics = _drop_negated_dwa_kierunki(topics, q)
    hist_topics = [(n, s) for n, rx, s in TOPICS if re.search(rx, history_text.lower(), re.I)]
    benefit_hist = _recent_benefits_from_history(history_text)
    benefit_hist_last = benefit_hist[-1] if benefit_hist else None
    cur_benefit = [(n, s) for n, s in topics if n in _BENEFIT_TOPICS]
    # „how much money / ile punktów” przy stypendium ≠ czesne
    if (
        cur_benefit
        and all(n == "oplaty" for n, _ in cur_benefit)
        and benefit_hist_last
        and benefit_hist_last[0] in _STIPEND_TOPICS
        and re.search(r"(?i)how\s*much|ile\s*(dost|punkt|kasy|pien)|points|money|сколько", q)
        and not re.search(r"(?i)tuition|czesne|opłat\w*\s*za\s*stud|fee\s*for\s*stud|english\s*program|business", q)
    ):
        cur_benefit = [benefit_hist_last]
        topics = cur_benefit
    # Zachowaj WSZYSTKIE benefit-tematy z pytania (socjalne + akademik, stypendium + czesne…)
    if cur_benefit:
        ordered = _order_benefit_topics(question, cur_benefit)
        others = [(n, s) for n, s in topics if n not in _BENEFIT_TOPICS and n != "cudzoziemcy"]
        topics = ordered + others
    elif benefit_hist:
        names = {n for n, _ in topics}
        if not topics or names <= {"cudzoziemcy", "dwa_kierunki"}:
            topics = list(benefit_hist)
        else:
            topics = [(n, s) for n, s in topics if n != "cudzoziemcy"] or list(benefit_hist)
    elif not topics and hist_topics:
        topics = [hist_topics[-1]]
    # R5-4: keep prior topics from history when a follow-up adds a new one (Erasmus after dorm+social)
    seen = {n for n, _ in topics}
    for part in [p.strip() for p in re.split(r"\n+", history_text or "") if p.strip()]:
        for n, rx, s in TOPICS:
            if n == "cudzoziemcy" or n in seen:
                continue
            if re.search(rx, part, re.I):
                if n == "dwa_kierunki" and _drop_negated_dwa_kierunki([(n, s)], part) == []:
                    continue
                topics.append((n, s))
                seen.add(n)
    # każda tura osobno (BUG-01: kotwice nie giną po sklejeniu historii)
    prof = merge_profile_from_turns(history_text, question)
    req = []
    for _, s in topics:
        for x in s:
            if x not in req:
                req.append(x)
    if prof.get("status") == "doktorant" or prof.get("poziom") == "SD":
        req = [x for x in req if x not in ("tryb", "poziom", "rok", "kierunek", "drugi_kierunek")]
    # PL-language tuition question without foreigner markers → do not demand status (R5-5)
    topic_names = [n for n, _ in topics]
    blob = f"{question or ''}\n{history_text or ''}"
    if (
        "oplaty" in topic_names
        and "status" in req
        and re.search(r"(?i)języku\s*polsk|polish[- ]language|czesne.*(?:polsk|niestacjon)|niestacjonarn\w*.*czesn", question or "")
        and not re.search(r"(?i)cudzoziem|foreign|international|інозем|гадаад|english\s*program", blob)
    ):
        req = [x for x in req if x != "status"]
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
- Ask ONLY about these missing fields: {missing_labels}. Never re-ask fields already listed in Known profile.
- 1–2 sentence intro why you ask, then a short numbered list (max {n} questions).
- Invite a single-sentence reply with a natural example (NO internal topic ids like stypendium_socjalne, NO English field keys).
- No URLs, no invented rules, no legal advice.
{security_rules}
Known profile so far: {profile}
"""

# Deterministyczny clarify domyślnie – LLM często pętli i wycieka id tematów.
# Włącz styl LLM: CLARIFY_LLM=1
def _clarify_llm_enabled():
    return os.getenv("CLARIFY_LLM", "").strip() == "1" and llm_enabled()

SYSTEM = """You are a helpful campus information assistant for students of Kazimierz Pułaski University of Radom (Uniwersytet Radomski, UR).
Your job is to SAVE the student’s time: extract concrete rules from the provided source fragments (who may apply, amounts, deadlines, documents, where to submit) so they rarely need to dig through PDFs themselves.
Tone: clear, calm, practical — like a well-informed staff member at Biuro Obsługi Studenta. Not a bureaucratic form, not a chatbot script.

HARD RULES:
1. Answer in {lang_name} (lang={lang}). NEVER answer in Russian. If the user writes Russian or asks for Russian (“по-русски”, “in Russian”), answer in Ukrainian and do NOT offer or promise Russian. Keep official names (UR, Biuro Obsługi Studenta, zarządzenie codes) when useful. If the user asks to switch language (“po polsku”, “на польській”, “in English”), switch language — do NOT treat that as a question about tuition “in the Polish language”.
2. Use ONLY the FACTS block (if present) and the source fragments below. No outside knowledge. Numbers, prices, caps, deadlines: use ONLY the FACTS block or quote a source chunk verbatim; if neither has it, say it is not available. ALWAYS first give every concrete fact that IS in the sources (eligibility yes/no for THIS profile, income thresholds, document lists, deadlines, submission channel, links). FORBIDDEN: an answer that only says you don’t know / contact BOS when sources contain a relevant section (e.g. “Stypendium dla cudzoziemców”, “obywatel Ukrainy”). Mention Biuro Obsługi Studenta / DWZ only as a short last-line tip when a personal decision or missing individual document remains — never instead of the rules.
3. Structure: (a) direct answer first, (b) conditions/exceptions for THIS student’s profile, (c) what to do next (documents, channel, deadlines), (d) sources list. Use short paragraphs or bullets.
4. Cite claims with [n] (or [F1], [F2] for FACTS). Do NOT write a sources section or any URLs — the system appends them. Never invent source numbers, [Fn…], or domains.
5. Mark “⚠️ may be outdated” ONLY for sources before 2024-01-01 or with no date. Never mark 2024+ as outdated. Quote amounts and deadlines only if present in sources, with academic year / ordinance (e.g. R-41/2025). Today: {today}. Do not state whether a deadline has passed — the system adds that warning.
6. For Polish citizens, full-time first-cycle study is often free — quote paid zł/euro amounts only when the source clearly applies to the user’s mode/level (e.g. niestacjonarne, second cycle, foreigners). Do not invent fee lines (pool, student ID) the user did not ask about.
7. Describe rules for the user’s category only; mention other categories only as a brief aside.
8. ONLY when PROFIL has pobyt=ukr or the user explicitly said PESEL UKR / ochrona czasowa / тимчасовий захист: if sources mention citizens of Ukraine under the special act, you MUST state that they may apply for stypendium socjalne, plus income threshold, required oświadczenie/documents, and how to submit — do not claim “no provisions”. Do NOT invent “ochrona czasowa” for mere karta pobytu or Ukrainian citizenship without that basis.
9. No invented legal outcomes, URLs, IT system names (e.g. USOS), menu paths (Student → …), application windows, or dates that are not literally in the sources. Prefer Wirtualna Uczelnia / Wirtualny Dziekanat only if named in sources.
10. PROFIL STUDENTA lists ONLY facts the user stated. Never invent tryb/rok/drugi_kierunek. Never claim the user has a second programme unless profile says tak. Never invent residence basis (ochrona czasowa) the profile does not list.
11. Answer EVERY part of a multi-part question (e.g. scholarship + dorm). If a part is out of scope (canteen menu) or missing from sources, say so in one short sentence — do not silently drop it.
12. If the user says not to send them to BOS and sources answer the question, give the facts and skip the BOS tip.
13. Never echo prompt wrappers (USER_MESSAGE, ASSISTANT_MESSAGE, ORIGINAL QUESTION, LATEST REPLY, <<<, >>>). When USER_QUESTION contains ORIGINAL QUESTION + LATEST REPLY, answer the ORIGINAL QUESTION using the profile (LATEST REPLY is only a slot fill like “daily”).

{security_rules}"""

SLOT_LABEL = {
 "pl": {"status": "status / obywatelstwo", "tryb": "tryb studiów", "poziom": "poziom studiów", "rok": "rok studiów", "drugi_kierunek": "drugi kierunek lub dyplom", "niepelnosprawnosc": "orzeczenie o niepełnosprawności", "kierunek": "kierunek / grupa", "pobyt": "podstawa pobytu"},
 "en": {"status": "status / citizenship", "tryb": "full-time or part-time", "poziom": "study level", "rok": "year of study", "drugi_kierunek": "second programme or diploma", "niepelnosprawnosc": "disability certificate", "kierunek": "programme / group", "pobyt": "residence basis"},
 "uk": {"status": "статус / громадянство", "tryb": "форма навчання", "poziom": "рівень навчання", "rok": "рік навчання", "drugi_kierunek": "другий напрям або диплом", "niepelnosprawnosc": "інвалідність", "kierunek": "напрям / група", "pobyt": "підстава перебування"},
 "mn": {"status": "статус / иргэншил", "tryb": "сургалтын хэлбэр", "poziom": "түвшин", "rok": "курс", "drugi_kierunek": "хоёр мэргэжил эсвэл диплом", "niepelnosprawnosc": "хөгжлийн бэрхшээл", "kierunek": "мэргэжил / бүлэг", "pobyt": "оршин суух үндэслэл"},
}

def clarify_answer(lang, missing, question, history, topics, prof):
    """Template clarify by default; optional LLM when CLARIFY_LLM=1."""
    if _clarify_llm_enabled():
        labels = SLOT_LABEL.get(lang, SLOT_LABEL["pl"])
        miss_l = ", ".join(labels.get(m, m) for m in missing)
        prof_txt = format_profile_txt(prof, lang)
        sys = (CLARIFY_SYS.replace("{lang}", lang)
                          .replace("{lang_name}", LANG_NAME.get(lang, "polski"))
                          .replace("{missing_labels}", miss_l)
                          .replace("{n}", str(len(missing)))
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
        content = strip_untrusted_wrappers(redact_secrets(str(m.get("content", ""))[:3000]))
        # Wrap tylko USER – owinięcie ASSISTANT powoduje wyciek „ASSISTANT_MESSAGE <<<” do odpowiedzi (BUG-07)
        if role == "user":
            content = wrap_untrusted("USER_MESSAGE", content)
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

def dedupe_hits_by_url(hits):
    """Stable URL dedup before numbering (R5-6)."""
    seen, out = set(), []
    for h in hits or []:
        u = (h.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(h)
    return out


def fmt_sources(hits):
    out = []
    for n, h in enumerate(dedupe_hits_by_url(hits), 1):
        out.append(
            f"[{n}] {h['title']} | URL: {h['url']} | aktualizacja: {h['modified'] or 'brak daty'} | "
            f"nieaktualne: {'TAK' if outdated(h['modified'], h.get('url') or '') else 'nie'}\n{h['text'][:2500]}"
        )
    return "\n\n".join(out)

def outdated(m, url=""):
    """Formularze (Załącznik UKR) mogą mieć starą datę pliku, a nadal być obowiązujące."""
    if url and re.search(r"Zalacznik-Nr-8-Ukraina|zalacznik.*ukrain|oswiadczen", url, re.I):
        return False
    return (not m) or m[:4] < "2024"

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

_ANTHROPIC_TIMEOUT = httpx.Timeout(connect=5.0, read=45.0, write=10.0, pool=5.0)
REQUEST_BUDGET_SEC = 55.0


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
                if r.status_code == 429:
                    time.sleep(min(60, 5 * 2 ** att)); continue
                if r.status_code in (500, 503) and att < 3:
                    time.sleep(min(20, 2 * 2 ** att)); continue
                break  # 404/400 / wyczerpane retry -> następny model
        raise RuntimeError(f"Gemini niedostępny ({last})")
    if prov == "anthropic":
        import time, random, logging
        log = logging.getLogger("ur.llm")
        last = None
        for att in range(2):
            t0 = time.monotonic()
            try:
                r = httpx.post(
                    "https://api.anthropic.com/v1/messages",
                    timeout=_ANTHROPIC_TIMEOUT,
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                    json={
                        "model": model or "claude-sonnet-4-5",
                        "max_tokens": 900,
                        "system": messages[0]["content"],
                        "messages": messages[1:],
                        "temperature": temperature,
                    },
                )
            except httpx.TimeoutException as e:
                last = e
                if att == 0:
                    time.sleep(1.0 + random.random())
                    continue
                raise RuntimeError("Anthropic timeout") from e
            rid = r.headers.get("request-id") or r.headers.get("x-request-id") or ""
            log.info("anthropic status=%s latency=%.2fs request-id=%s", r.status_code, time.monotonic() - t0, rid)
            if r.status_code == 200:
                return r.json()["content"][0]["text"]
            last = f"HTTP {r.status_code}"
            if r.status_code in (429, 500, 529) and att == 0:
                time.sleep(1.0 + random.random())
                continue
            raise RuntimeError(f"Anthropic niedostępny (HTTP {r.status_code})")
        raise RuntimeError(f"Anthropic niedostępny ({last})")
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
# Canonical slot values → display in target reply language (avoid Polish tokens leaking into EN/UK/MN).
PROF_VAL = {
 "pl": {},
 "en": {
  "pl": "Polish citizen", "cudzoziemiec": "international student", "doktorant": "doctoral student",
  "bezpanstwowiec": "stateless", "stacjonarne": "full-time", "niestacjonarne": "part-time",
  "I": "1st cycle", "II": "2nd cycle", "SD": "doctoral school", "jednolite": "long-cycle",
  "tak": "yes", "nie": "no", "pobyt_czasowy": "temporary residence", "pobyt_staly": "permanent residence",
  "karta_polaka": "Pole's Card", "ukr": "UKR temporary protection",
 },
 "uk": {
  "pl": "громадянин Польщі", "cudzoziemiec": "іноземець", "doktorant": "докторант",
  "bezpanstwowiec": "особа без громадянства", "stacjonarne": "денна", "niestacjonarne": "заочна",
  "I": "І ступінь", "II": "ІІ ступінь", "SD": "докторантура", "jednolite": "єдиний магістерський",
  "tak": "так", "nie": "ні", "pobyt_czasowy": "тимчасове перебування", "pobyt_staly": "постійне перебування",
  "karta_polaka": "Карта поляка", "ukr": "тимчасовий захист UKR",
 },
 "mn": {
  "pl": "Польш иргэн", "cudzoziemiec": "гадаадын оюутан", "doktorant": "докторант",
  "bezpanstwowiec": "харьяалалгүй", "stacjonarne": "өдрийн", "niestacjonarne": "эчнээ",
  "I": "I зэрэг", "II": "II зэрэг", "SD": "докторантур", "jednolite": "нэгдсэн магистр",
  "tak": "тийм", "nie": "үгүй", "pobyt_czasowy": "түр оршин суух", "pobyt_staly": "байнгын оршин суух",
  "karta_polaka": "Польшийн карт", "ukr": "UKR түр хамгаалалт",
 },
}


def format_profile_txt(prof, lang="pl"):
    """Profile line with labels+values in the reply language (never mix scripts)."""
    labels = PROF_LABEL.get(lang, PROF_LABEL["pl"])
    vals = PROF_VAL.get(lang, {})
    parts = []
    for k, v in (prof or {}).items():
        if k not in labels:
            continue
        disp = vals.get(v, v) if isinstance(v, str) else v
        parts.append(f"{labels.get(k, k)}: {disp}")
    return ", ".join(parts) or "—"

NO_LLM = {
 "pl": "Na podstawie oficjalnych stron UR (profil: {prof}):",
 "en": "Based on official UR pages (profile: {prof}):",
 "uk": "На основі офіційних сторінок UR (профіль: {prof}):",
 "mn": "UR-ийн албан ёсны хуудаснууд дээр үндэслэн (профайл: {prof}):",
}
SRC_HDR = {"pl": "Źródła", "en": "Sources", "uk": "Джерела", "mn": "Эх сурвалж"}
OUTDATED = {"pl": "informacja może być nieaktualna", "en": "may be outdated", "uk": "може бути неактуальною", "mn": "хуучирсан байж болно"}
_URL_RE = re.compile(r"https?://[^\s)\]\"'<>]+", re.I)
_SRC_HEAD_RE = re.compile(r"(?im)^\s*(źródła|sources|джерела|источники|эх\s*сурвалж)\s*:?\s*$")
_SYSTEM_NAME_RE = re.compile(r"(?i)\b(USOS|SIRK|Wirtualn\w+\s+\w+)\b")

def render_sources(hits, lang="pl", max_n=5, fact_entries=None):
    """Code-owned sources list in the session language. Numbers match body citations."""
    lines = []
    for h in dedupe_hits_by_url(hits)[:max_n]:
        u = (h.get("url") or "").strip()
        warn = ""
        if outdated(h.get("modified"), u):
            warn = f" ⚠️ {OUTDATED.get(lang, OUTDATED['pl'])}"
        lines.append(f"[{len(lines)+1}] {u} – {h.get('modified') or '—'}{warn}")
    for fe in fact_entries or []:
        # already formatted as [F1] title – url
        lines.append(fe)
    if not lines:
        return ""
    return f"\n\n{SRC_HDR.get(lang, 'Źródła')}:\n" + "\n".join(lines)


_CITE_RE = re.compile(r"\[(?:F|Fn|FN)?(\d+)\]")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def align_citations(body: str, hits, fact_urls=None) -> tuple[str, list, list[str]]:
    """Renumber [n]/[Fk] to cited-only 1..k / F1..; drop dangling markers (R5-6)."""
    hits = dedupe_hits_by_url(hits)
    fact_urls = [u for u in (fact_urls or []) if u]
    cited_order, fact_order = [], []
    # Normalize [Fn8] → treat as fact marker; bare [8] as source index
    def _collect(m):
        raw = m.group(0)
        num = int(m.group(1))
        is_fact = bool(re.match(r"\[F", raw, re.I))
        if is_fact:
            if 1 <= num <= max(len(fact_urls), num) and num not in fact_order:
                # keep fact index if we have that many facts; else drop later
                if num not in fact_order:
                    fact_order.append(num)
            return raw
        if 1 <= num <= len(hits):
            if num not in cited_order:
                cited_order.append(num)
            return raw
        return ""  # dangling

    # First pass: drop dangling, remember cited
    tmp = _CITE_RE.sub(_collect, body or "")
    # Rebuild maps old→new
    src_map = {old: i for i, old in enumerate(cited_order, 1)}
    # Fact markers: renumber in order of first appearance among those with urls
    valid_facts = [n for n in fact_order if 1 <= n <= len(fact_urls)]
    fact_map = {old: i for i, old in enumerate(valid_facts, 1)}

    def _rewrite(m):
        raw = m.group(0)
        num = int(m.group(1))
        if re.match(r"\[F", raw, re.I):
            if num in fact_map:
                return f"[F{fact_map[num]}]"
            return ""
        if num in src_map:
            return f"[{src_map[num]}]"
        return ""

    new_body = _CITE_RE.sub(_rewrite, tmp)
    cited_hits = [hits[i - 1] for i in cited_order if 1 <= i <= len(hits)]
    # If nothing cited, fall back to top hits for transparency
    if not cited_hits and hits:
        cited_hits = hits[:5]
        # strip any leftover markers already handled
    fact_entries = []
    for old in valid_facts:
        new_i = fact_map[old]
        u = fact_urls[old - 1]
        fact_entries.append(f"[F{new_i}] {u}")
    return new_body, cited_hits, fact_entries


def finalize_answer_urls(text, hits, fact_urls=None, lang="pl", hits_blob=""):
    """Strip LLM sources section + unknown URLs; align citations; append sources."""
    if not text:
        text = ""
    lines, cut = [], False
    for line in text.splitlines():
        if _SRC_HEAD_RE.match(line.strip()):
            cut = True
            break
        lines.append(line)
    body = "\n".join(lines).rstrip()
    # Official UR emails only if present in retrieved text
    blob = hits_blob or _hit_blob(hits)
    def _email(m):
        e = m.group(0)
        if re.search(r"@(?:uthrad\.pl|uniwersytetradom\.pl)\b", e, re.I) and e.lower() in (blob or "").lower():
            return e
        return ""
    body = _EMAIL_RE.sub(_email, body)
    allowed = {(h.get("url") or "").rstrip("/") for h in (hits or []) if h.get("url")}
    for u in fact_urls or []:
        if u:
            allowed.add(u.rstrip("/"))
    def _keep(m):
        u = m.group(0).rstrip(".,;)")
        return u if u.rstrip("/") in allowed or u in allowed else ""
    body = _URL_RE.sub(_keep, body)
    body, cited_hits, fact_entries = align_citations(body, hits, fact_urls=fact_urls)
    body = cleanup_answer_artifacts(body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).rstrip()
    return body + render_sources(cited_hits, lang, max_n=8, fact_entries=fact_entries)


def cleanup_answer_artifacts(text: str) -> str:
    """Collapse empty (), ****, dangling labels after scrub/URL strip."""
    if not text:
        return text
    t = text
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"\*{3,}", "", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" +\n", "\n", t)
    t = re.sub(r"(?i)\b(w systemie|in the(?:\s+\w+)?\s+system|в системі|системд)\s+$",
               r"\1", t, flags=re.M)
    # Drop lines that are only a label ending with colon
    kept = []
    for line in t.splitlines():
        if re.match(r"(?i)^\s*[\wА-Яа-яІіЇїЄєҐґӨөҮү ./\-]{1,40}:\s*$", line):
            continue
        kept.append(line)
    return "\n".join(kept)
LLM_ERR = {
 "pl": "(Model językowy chwilowo niedostępny – poniżej zestawienie z oficjalnych źródeł.)\n\n",
 "en": "(Language model temporarily unavailable – below is a summary from official sources.)\n\n",
 "uk": "(Мовна модель тимчасово недоступна – нижче стислий виклад з офіційних джерел.)\n\n",
 "mn": "(Хэлний загвар түр ажиллахгүй байна – доор албан ёсны эх сурвалжаас товчлол.)\n\n",
}

def _hit_blob(hits):
    return "\n".join((h.get("text") or "") for h in hits)

def extract_source_facts(hits):
    """Wyciągnij konkretne fakty z fragmentów (na fallback bez LLM)."""
    blob = _hit_blob(hits)
    facts = {}
    m = re.search(r"(?:wynosi|wysokość[^.]{0,40}?)\s*([0-9][0-9\s]*(?:,\d+)?)\s*zł", blob, re.I)
    if not m:
        m = re.search(r"(2099(?:[.,]\d+)?)\s*zł", blob, re.I)
    if m:
        facts["income_cap"] = re.sub(r"\s+", "", m.group(1)) + " zł"
    m = re.search(r"(termin[^.]{0,20}wniosk[^.]{0,80}|od\s*\d{2}[./]\d{2}[./]\d{4}\s*do\s*\d{2}[./]\d{2}[./]\d{4})", blob, re.I)
    if m:
        facts["deadline"] = re.sub(r"\s+", " ", m.group(0)).strip()
    if re.search(r"Wirtualny Dziekanat", blob, re.I):
        facts["submit"] = "Wirtualny Dziekanat"
    if re.search(r"obywatel Ukrainy|ochrony czasowej|PESEL\s*UKR|Załącznik\s*Nr\s*8|Zalacznik-Nr-8-Ukraina", blob, re.I):
        facts["ukr_ok"] = True
    if re.search(r"Stypendium dla cudzoziemc|cudzoziemc\w*\s*(mogą|może)\s*ubiega", blob, re.I):
        facts["foreign_ok"] = True
    urls = []
    for h in hits:
        u = h.get("url") or ""
        if u and u not in urls:
            urls.append(u)
        if len(urls) >= 5:
            break
    facts["urls"] = urls
    # kluczowe zdania
    sents = []
    for pat in [
        r".{0,40}2099(?:[.,]\d+)?\s*zł.{0,80}",
        r".{0,30}obywatel Ukrainy.{0,120}",
        r".{0,20}Wirtualny Dziekanat.{0,80}",
        r".{0,20}ochrony czasowej.{0,100}",
    ]:
        m = re.search(pat, blob, re.I | re.S)
        if m:
            sents.append(re.sub(r"\s+", " ", m.group(0)).strip())
    facts["sents"] = sents[:4]
    return facts

def compose_fallback_answer(lang, topics, prof, hits, prof_txt, err="", facts_block=""):
    """Czytelna odpowiedź bez LLM – fakty + kroki + URL, nie surowy dump."""
    facts = extract_source_facts(hits)
    lines = [err + NO_LLM.get(lang, NO_LLM["pl"]).format(prof=prof_txt)]
    if facts_block:
        lines.append("\n" + facts_block)
    tset = set(topics or [])

    if "stypendium_socjalne" in tset:
        is_ukr = prof.get("pobyt") == "ukr"
        is_pl = prof.get("status") == "pl"
        show_ukr_form = is_ukr and any("Zalacznik-Nr-8-Ukraina" in u for u in facts.get("urls", []))
        if lang == "uk":
            if is_ukr:
                lines.append(
                    "\n**Так — за правилами UR громадяни України (зокрема захист / PESEL UKR) можуть претендувати "
                    "на соціальну стипендію**, якщо виконуються умови доходу та один напрям навчання."
                )
            elif is_pl:
                lines.append(
                    "\n**Так — громадяни Польщі можуть подати заяву на соціальну стипендію**, "
                    "якщо дохід сім’ї не перевищує порогу і стипендія береться лише на одному напрямі."
                )
            else:
                lines.append("\n**Соціальна стипендія** залежить від доходу сім’ї та статусу студента (див. джерела нижче).")
            if facts.get("income_cap"):
                lines.append(f"- Поріг доходу (з офіційної сторінки): **{facts['income_cap']}** на особу в сім’ї.")
            if facts.get("submit"):
                lines.append(f"- Подання заяви: **{facts['submit']}** (і документи за списком на сторінці стипендій).")
            if show_ukr_form:
                lines.append("- Для громадян України потрібна **заява (Załącznik nr 8)** — PDF у джерелах.")
            lines.append("- Далі: відкрийте сторінку стипендій, перевірте список документів і терміни на поточний навчальний рік.")
        elif lang == "en":
            if is_ukr:
                lines.append(
                    "\n**Yes — under UR rules, citizens of Ukraine (temporary protection / PESEL UKR) may apply "
                    "for a social scholarship** if income and single-programme rules are met."
                )
            elif is_pl:
                lines.append(
                    "\n**Yes — Polish citizens may apply for a social scholarship** if family income is within "
                    "the threshold and the benefit is taken for one programme only."
                )
            else:
                lines.append("\n**Social scholarship** depends on family income and student status (see sources).")
            if facts.get("income_cap"):
                lines.append(f"- Income threshold (official page): **{facts['income_cap']}** per family member.")
            if facts.get("submit"):
                lines.append(f"- Submit via **{facts['submit']}** with the required documents.")
            lines.append("- Next: open the scholarship page, check documents and deadlines for the current year.")
        else:  # pl / mn
            if is_ukr:
                lines.append(
                    "\n**Tak — według zasad UR obywatele Ukrainy (ochrona czasowa / PESEL UKR) mogą ubiegać się "
                    "o stypendium socjalne**, jeśli spełniają warunki dochodowe i zasady jednego kierunku."
                )
            elif is_pl:
                lines.append(
                    "\n**Tak — obywatel Polski może ubiegać się o stypendium socjalne**, jeśli dochód rodziny "
                    "nie przekracza progu i świadczenie dotyczy jednego kierunku."
                )
            else:
                lines.append("\n**Stypendium socjalne** zależy od dochodu rodziny i statusu studenta (szczegóły w źródłach).")
            if facts.get("income_cap"):
                lines.append(f"- Próg dochodu (oficjalna strona): **{facts['income_cap']}** na osobę w rodzinie.")
            if facts.get("submit"):
                lines.append(f"- Złożenie wniosku: **{facts['submit']}** + wymagane dokumenty.")
            if show_ukr_form:
                lines.append("- Dla obywateli Ukrainy: **oświadczenie – Załącznik nr 8** (PDF w źródłach).")
            lines.append("- Dalej: sprawdź listę dokumentów i terminy na stronie stypendiów na bieżący rok.")
        sents = facts.get("sents") or []
        if is_pl:
            sents = [s for s in sents if not re.search(r"Ukrain|ochrony czasowej|PESEL\s*UKR", s, re.I)]
        elif not is_ukr:
            sents = [s for s in sents if not re.search(r"ochrony czasowej|PESEL\s*UKR", s, re.I)]
        if sents:
            frag_h = {"pl": "Fragmenty ze źródeł:", "en": "Source excerpts:", "uk": "Уривки з джерел:", "mn": "Эх сурвалжийн хэсэг:"}.get(lang, "Fragmenty ze źródeł:")
            lines.append(f"\n{frag_h}")
            for s in sents:
                lines.append(f"- „{s}…”")
    elif "stypendium_rektora" in tset:
        head = {
            "uk": "\n**Стипендія ректора (stypendium rektora)** — умови з офіційних сторінок UR:",
            "en": "\n**Rector’s scholarship** — from official UR pages:",
            "pl": "\n**Stypendium rektora** — na podstawie oficjalnych stron UR:",
            "mn": "\n**Ректорын тэтгэлэг** — UR-ийн албан ёсны хуудаснаас:",
        }.get(lang, "\n**Stypendium rektora:**")
        lines.append(head)
        if prof.get("rok") == "1":
            note = {
                "uk": "- На **1 курсі** критерії часто інші (напр. результати з попередньої школи / олімпіади) — перевірте на сторінці стипендії ректора.",
                "en": "- In **year 1**, criteria often differ (e.g. previous school results) — check the Rector’s scholarship page.",
                "pl": "- Na **1 roku** kryteria bywają inne (np. wyniki ze szkoły średniej) – sprawdź stronę stypendium rektora.",
            }.get(lang, "- Na 1 roku sprawdź osobne kryteria na stronie stypendium rektora.")
            lines.append(note)
        for i, h in enumerate(hits[:3], 1):
            snip = re.sub(r"\s+", " ", h.get("text") or "")[:320]
            lines.append(f"\n[{i}] **{h.get('title') or 'Źródło'}**\n„{snip}…”")
        lines.append({
            "uk": "- Далі: сторінка stypendium rektora + PDF із правилами; заява через канали, вказані на сайті UR.",
            "en": "- Next: open the Rector’s scholarship page and the rules PDF; apply via the channel listed there.",
            "pl": "- Dalej: strona stypendium rektora i PDF z regulaminem; wniosek według instrukcji na stronie UR.",
        }.get(lang, "- Dalej: strona stypendium rektora i PDF z regulaminem."))
    else:
        # ogólny fallback – krótsze cytaty zamiast ściany tekstu
        for i, h in enumerate(hits[:3], 1):
            snip = re.sub(r"\s+", " ", h.get("text") or "")[:280]
            lines.append(f"\n[{i}] **{h.get('title') or 'Źródło'}**\n„{snip}…”")

    src_lines, seen_u = [], set()
    for h in hits:
        u = h.get("url") or ""
        if not u or u in seen_u:
            continue
        seen_u.add(u)
        warn = ""
        if outdated(h.get("modified"), u):
            warn = f" ⚠️ {OUTDATED.get(lang, OUTDATED['pl'])}"
        src_lines.append(f"[{len(src_lines)+1}] {u} – {h.get('modified') or '—'}{warn}")
        if len(src_lines) >= 4:
            break
    lines.append(f"\n{SRC_HDR.get(lang, 'Źródła')}:\n" + "\n".join(src_lines))
    tip = {
        "pl": "\nNa indywidualną decyzję komisji możesz dopytać Biuro Obsługi Studenta — po sprawdzeniu dokumentów z listy powyżej.",
        "en": "\nFor an individual committee decision, you can ask the Student Service Office after checking the documents above.",
        "uk": "\nЩодо індивідуального рішення комісії можна звернутися до Biuro Obsługi Studenta — після перевірки документів зі списку вище.",
        "mn": "\nХувь хүний шийдвэрийн талаар дээрх баримт бичгээ шалгасны дараа Biuro Obsługi Studenta-аас асууж болно.",
    }
    if "stypendium_socjalne" in tset or "stypendium_rektora" in tset:
        lines.append(tip.get(lang, tip["pl"]))
    return "\n".join(lines)

def _last_assistant_was_clarify(history):
    for m in reversed(history or []):
        if m.get("role") == "assistant":
            c = m.get("content") or ""
            return bool(re.search(
                r"(?i)zanim odpowiem|before i answer|перш ніж|doprecyzuj|please clarify|уточн|"
                r"jaki jest tw[oó]j status|what is your status|який ваш статус|"
                r"studiujesz stacjonarnie|full-time or part-time|денній\s*\(стаціонар\)|"
                r"на якому ви році|which year of study|czy studiujesz równolegle|"
                r"are you studying a second",
                c,
            ))
    return False

def _topic_names_in(text):
    return [n for n, rx, _ in TOPICS if n != "cudzoziemcy" and re.search(rx, text or "", re.I)]


def _accumulate_topics(topics, *texts, prior=None):
    """Union topic names from prior intents + current + any user texts (R5-4)."""
    acc = []
    for n in list(prior or []) + list(topics or []):
        if n and n not in acc and n != "cudzoziemcy":
            acc.append(n)
    for text in texts:
        for n in _topic_names_in(text or ""):
            if n not in acc:
                acc.append(n)
    return acc


def _user_question_for_llm(question, history, state=None):
    """ORIGINAL QUESTION(S) + FOLLOW-UP so clarify/follow-ups never drop the first ask (R5-4)."""
    substantive = []
    if state and getattr(state, "original_question", None):
        oq = state.original_question.strip()
        if oq:
            substantive.append(oq)
    for m in history or []:
        if m.get("role") != "user":
            continue
        c = (m.get("content") or "").strip()
        if not c:
            continue
        if any(re.search(rx, c, re.I) for _, rx, _ in TOPICS):
            if c not in substantive:
                substantive.append(c)
    q = (question or "").strip()
    # After a clarify turn, short slot replies are not new questions — keep ORIGINAL + LATEST REPLY
    if _last_assistant_was_clarify(history) and q and q.lower() not in [s.lower() for s in substantive]:
        if not _topic_names_in(q) or len(q.split()) <= 12:
            orig = substantive[-1] if substantive else (state.original_question if state else None)
            if orig and orig.lower() != q.lower():
                return f"ORIGINAL QUESTION: {orig}\nLATEST REPLY: {question}"
    originals = [s for s in substantive if s.lower() != q.lower()]
    if not originals:
        return question
    # New topical follow-up (e.g. Erasmus after dorm+social): answer ALL pending items
    if q and (_topic_names_in(q) or not _last_assistant_was_clarify(history)):
        body = "ORIGINAL QUESTION(S):\n" + "\n".join(f"- {o}" for o in originals)
        if q:
            body += f"\nFOLLOW-UP: {q}"
        body += "\n\nAnswer every item in ORIGINAL QUESTION(S) first, in order, then FOLLOW-UP."
        return body
    orig = originals[-1]
    return f"ORIGINAL QUESTION: {orig}\nLATEST REPLY: {question}"


def search_topics(base_q, topics, prof, k_per=4, fac=None):
    """Retrieve per pending topic and merge (max k_per each, stable URL dedup)."""
    topics = [t for t in (topics or []) if t]
    if not topics:
        return search(base_q, k=12, prefer=prefer_sources([], fac=fac), topics=[], profile=prof)
    merged, seen = [], set()
    for t in topics:
        q = (base_q or "") + " " + TOPIC_PL_QUERY.get(t, t)
        q += " " + query_extras([t], prof)
        prefer = prefer_sources([t], fac=fac if t == "plan" else None)
        for h in search(q, k=k_per, prefer=prefer, topics=[t], profile=prof):
            key = (h.get("url") or "", (h.get("text") or "")[:60])
            if key in seen:
                continue
            seen.add(key)
            merged.append(h)
    return merged[:12]

_NEUTRAL_SYSTEM = {
    "pl": "w systemie uczelni",
    "en": "in the university system",
    "uk": "в системі університету",
    "mn": "их сургуулийн системд",
}


def _scrub_hallucinations(text, hits_blob="", lang="pl"):
    """Replace unknown system names with a neutral phrase; clean empty () / **** (R5-6)."""
    if not text:
        return text
    blob = hits_blob or ""
    neutral = _NEUTRAL_SYSTEM.get(lang, _NEUTRAL_SYSTEM["pl"])

    def _repl(m):
        name = m.group(1)
        key = name.split()[0]
        if re.search(re.escape(key), blob, re.I):
            return m.group(0)
        return neutral

    text = _SYSTEM_NAME_RE.sub(_repl, text)
    text = cleanup_answer_artifacts(text)
    return re.sub(r"[ \t]{2,}", " ", text)

_GENERAL_PROFILE_SLOTS = {"status", "poziom", "rok", "tryb", "kierunek", "drugi_kierunek"}
_SENSITIVE_PROFILE_SLOTS = {"niepelnosprawnosc", "pobyt"}

def merge_state_profile(state, prof, topics, history):
    """Carry only conversation-scoped slots; never reuse sensitive slots on empty history (R5-1)."""
    prof = dict(prof or {})
    topics = list(topics or [])
    hist = history or []
    if not hist:
        # Empty visible history → ignore state.profile entirely (privacy)
        carried = {}
    else:
        carried = {}
        prev = dict(getattr(state, "profile", None) or {})
        tset = set(topics)
        for k, v in prev.items():
            if k in _SENSITIVE_PROFILE_SLOTS:
                # Disability only when the current topic is disability scholarship
                if k == "niepelnosprawnosc" and "stypendium_niepeln" not in tset:
                    continue
                # pobyt only for topics that need residence basis
                if k == "pobyt" and not (tset & {
                    "stypendium_socjalne", "stypendium_rektora", "stypendium_niepeln",
                    "oplaty", "cudzoziemcy", "doktoranckie", "dwa_kierunki",
                }):
                    continue
            if k in _GENERAL_PROFILE_SLOTS or k in _SENSITIVE_PROFILE_SLOTS:
                carried[k] = v
            elif k in prev:
                carried[k] = v
        # Topic family switch: drop disability unless disability topic
        if "stypendium_niepeln" not in tset:
            carried.pop("niepelnosprawnosc", None)
    merged = dict(carried)
    merged.update(prof)  # this turn wins
    req = []
    for name in topics:
        for n, _rx, slots in TOPICS:
            if n == name:
                for x in slots:
                    if x not in req:
                        req.append(x)
    if merged.get("status") == "doktorant" or merged.get("poziom") == "SD":
        req = [x for x in req if x not in ("tryb", "poziom", "rok", "kierunek", "drugi_kierunek")]
    missing = [x for x in req if x not in merged]
    return merged, missing

def _attach_state(result, state):
    try:
        from session import encode
        result["state"] = encode(state)
    except Exception:
        pass
    return result

def answer(question, history, session_lang=None, state_token=None, conv_id=None):
    """history: lista {'role','content'}; zwraca dict(answer, sources, mode, clarify, lang, state)"""
    import time as _time
    _t_deadline = _time.monotonic() + REQUEST_BUDGET_SEC
    from session import resolve_state
    question = redact_secrets((question or "").strip())
    history = [
        {"role": m.get("role"), "content": redact_secrets(str(m.get("content", ""))[:3000])}
        for m in (history or [])
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
    ]
    state = resolve_state(state_token, history, conv_id=conv_id)
    hist_user = "\n".join(m["content"] for m in history if m["role"] == "user")
    user_turns = [m["content"] for m in history if m["role"] == "user"]
    seed_lang = session_lang or state.lang
    if seed_lang:
        lang = resolve_session_lang(map_policy(seed_lang), question)
    else:
        lang = sticky_lang_from_user_turns(user_turns, question)
    state.lang = lang
    # Deterministyczna bramka: klucze API, konta wykładowców, jailbreak – bez wywołania LLM
    if is_security_probe(question) or is_security_probe(hist_user[-500:], question):
        return _attach_state(dict(clarify=False, mode="security", sources=[], profile={}, topics=[], lang=lang,
                    answer=refuse_message(lang)), state)
    turn_conflicts = []
    topics, prof, missing = needed(question, hist_user)
    # Re-parse latest turn with conflict logging (needed() already merged regex profile)
    extract_profile(question, conflicts_out=turn_conflicts)
    if turn_conflicts:
        state.conflicts.extend(turn_conflicts)
    prof, missing = merge_state_profile(state, prof, topics, history)
    state.profile = dict(prof)
    # Accumulate pending intents across clarify + follow-ups (R5-4)
    topics = _accumulate_topics(
        topics,
        question,
        state.original_question or "",
        *user_turns,
        prior=state.intents,
    )
    state.intents = list(topics)
    prev_pending = list(state.pending_slots or [])
    if missing and prev_pending and question.strip():
        # User answered a clarify but slots still missing → try LLM extractor, then one targeted Q
        try:
            from extract import extract_turn, apply_extraction
            data = extract_turn(question, prof, state.pending_question, prev_pending, call_llm)
            if data:
                prof2, confs = apply_extraction(prof, data)
                # Never invent disability unless the turn mentions it
                if "niepelnosprawnosc" in prof2 and "niepelnosprawnosc" not in prof:
                    if not re.search(r"(?i)niepe[lł]nospraw|disability|інвалід|хөгжлийн\s*бэрхшээл", question):
                        prof2.pop("niepelnosprawnosc", None)
                state.conflicts.extend(confs)
                prof = prof2
                state.profile = dict(prof)
                _, missing = merge_state_profile(state, prof, topics, history)
        except Exception:
            pass
        if missing and set(missing) & set(prev_pending):
            # Do not re-ask the full list — one remaining slot only
            missing = [m for m in missing if m in prev_pending][:1] or missing[:1]
    if missing:
        state.pending_slots = list(missing)
        if not state.original_question and any(re.search(rx, question, re.I) for _, rx, _ in TOPICS):
            state.original_question = question
        text, mode = clarify_answer(lang, missing, question, history, topics, prof)
        state.pending_question = text
        return _attach_state(dict(clarify=True, mode=mode, sources=[], profile=prof, topics=topics, lang=lang, answer=text), state)
    state.pending_slots = []
    state.pending_question = None
    base_q = question
    if history:
        prev = [m["content"] for m in history if m["role"] == "user" and any(re.search(rx, m["content"], re.I) for _, rx, _ in TOPICS)]
        if prev:
            base_q = prev[-1] + " " + question
    if state.original_question and state.original_question not in base_q:
        base_q = state.original_question + " " + base_q
    llm_q = _user_question_for_llm(question, history, state=state)
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
    if tp is not topics:
        q = re.sub(r"(?i)\b(jako\s+)?cudzoziem\w*|international\s+student|foreign\s+student|інозем\w*|гадаад\s+оюутан", " ", q)
    if "plan" in topics and fac:
        q += " " + FACULTY_LABEL.get(fac, fac) + " plan zajęć"
        if prof.get("kierunek") == "weif_wydzial":
            q += " Ekonomia Finanse i rachunkowość (wydział WEiF – wybierz konkretny kierunek na stronie)"
        elif prof.get("kierunek"):
            q += " " + prof["kierunek"]
    hits = search_topics(q, tp, prof, k_per=4, fac=fac)
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
    srcs = [dict(n=i, title=h["title"], url=h["url"], modified=h["modified"],
                 outdated=outdated(h["modified"], h.get("url") or ""), snippet=h["text"][:400])
            for i, h in enumerate(hits, 1)]
    prof_txt = format_profile_txt(prof, lang)
    selected_facts = select_facts(load_facts(), topics, prof)
    computed_lines = []
    income_val = extract_income(f"{hist_user}\n{question}")
    if income_val is not None and "stypendium_socjalne" in topics:
        social = next((f for f in selected_facts if f.id == "social_income_threshold"), None)
        groups_src = social.value if social else None
        if groups_src is None:
            for f in load_facts():
                if f.id in ("social_income_threshold", "social_amount_groups") and f.value:
                    groups_src = f.value
                    social = f
                    break
        line = computed_income_line(
            income_val, groups_src,
            getattr(social, "academic_year", None) if social else None,
            lang,
        )
        if line:
            computed_lines.append(line)
    facts_block = render_facts_block(selected_facts, lang, computed_lines=computed_lines)
    allowed_amounts = fact_amounts(selected_facts) | amounts_in(_hit_blob(hits[:8]))
    if income_val is not None:
        allowed_amounts.add(Decimal(str(income_val)))
        _g, amt = income_group(
            income_val,
            next((f.value for f in selected_facts if f.id == "social_income_threshold"), None),
        )
        if amt is not None:
            allowed_amounts.add(Decimal(str(amt)))

    def _postcheck_amounts(text):
        if not selected_facts or not text:
            return text
        unknown = amounts_in(text) - allowed_amounts
        if not unknown:
            return text
        # Strip unknown zł/EUR amounts (keep structure); annotate once
        def _strip_amt(m):
            raw = m.group(0)
            got = amounts_in(raw)
            return "" if got and got <= unknown else raw
        cleaned = re.sub(
            r"(?<!\d)(\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{1,2})?|\d+[.,]\d{2}|\d{3,5})\s*(?:zł|zl|PLN|EUR|euro|€)",
            _strip_amt,
            text,
            flags=re.I,
        )
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).rstrip()
        note = {
            "pl": "\n(Kwoty spoza FACTS/ŹRÓDEŁ usunięto — sprawdź oficjalne zarządzenie.)",
            "en": "\n(Amounts not in FACTS/sources were removed — check the official ordinance.)",
            "uk": "\n(Суми поза FACTS/джерелами прибрано — перевірте офіційне розпорядження.)",
            "mn": "\n(FACTS/эх сурвалжид байхгүй дүнг хаслаа.)",
        }.get(lang, "")
        return cleaned + note

    if llm_enabled():
        import datetime
        sys = (SYSTEM.replace("{today}", datetime.date.today().isoformat())
                     .replace("{lang}", lang)
                     .replace("{lang_name}", LANG_NAME.get(lang, "polski"))
                     .replace("{security_rules}", SECURITY_RULES))
        lang_guard = (
            f"Respond ONLY in {LANG_NAME.get(lang, 'polski')} (lang={lang}). "
            "Never use Russian. Never offer Russian.\n\n"
        )
        facts_section = (facts_block + "\n\n") if facts_block else ""
        msgs = [{"role": "system", "content": lang_guard + sys}] + _safe_history(history, 8) + [{"role": "user", "content":
                f"PROFIL STUDENTA: {prof_txt}\nLANG: {lang}\nTEMATY: {', '.join(topics) or '—'}\n"
                "QUALITY: Use FACTS and canonical UR pages first. Give eligibility/amounts/steps when present. "
                "Never answer with only “contact BOS” if fragments already answer the question. "
                "Never invent USOS, menu paths, or dates absent from sources. Never write the word ŹRÓDŁA.\n\n"
                + facts_section
                + f"SOURCES:\n{fmt_sources(hits)}\n\n"
                + wrap_untrusted("USER_QUESTION", llm_q)
                + "\n\nNapisz konkretną, naturalną odpowiedź według zasad systemowych."}]
        try:
            blob6 = _hit_blob(hits[:6])
            out = strip_untrusted_wrappers(redact_secrets(call_llm(msgs, temperature=0.3)))
            out = _scrub_hallucinations(out, blob6, lang=lang)
            if not output_lang_ok(out, lang):
                # Skip language regen if remaining budget < 20s → fallback (R5-8)
                if _time.monotonic() + 20 > _t_deadline:
                    out = compose_fallback_answer(lang, topics, prof, hits, prof_txt, err="", facts_block=facts_block)
                else:
                    msgs[0] = {
                        "role": "system",
                        "content": (
                            f"CRITICAL: Respond ONLY in {LANG_NAME.get(lang, 'polski')} (lang={lang}). "
                            "Never use Russian. Never mix Latin and Cyrillic letters in the same word "
                            "(no forms like Statус / diплом). Sources header language must match the body.\n\n"
                            + sys
                        ),
                    }
                    try:
                        out = strip_untrusted_wrappers(redact_secrets(call_llm(msgs, temperature=0.2)))
                        out = _scrub_hallucinations(out, blob6, lang=lang)
                    except Exception:
                        out = ""
                    if not out or not output_lang_ok(out, lang):
                        out = compose_fallback_answer(lang, topics, prof, hits, prof_txt, err="", facts_block=facts_block)
            out = strip_llm_deadline_notes(out)
            out = _postcheck_amounts(out)
            fact_urls = [f.source.get("url") for f in selected_facts if f.source.get("url")]
            out = finalize_answer_urls(out, hits[:6], fact_urls=fact_urls, lang=lang, hits_blob=blob6)
            out += deadline_passed_note(out, lang)
            state.original_question = None
            return _attach_state(dict(clarify=False, mode="llm", sources=srcs, profile=prof, topics=topics, lang=lang, answer=out), state)
        except Exception:
            err = LLM_ERR.get(lang, LLM_ERR["pl"])
    else:
        err = ""
    blob6 = _hit_blob(hits[:6])
    ans = strip_untrusted_wrappers(redact_secrets(compose_fallback_answer(lang, topics, prof, hits, prof_txt, err=err, facts_block=facts_block)))
    ans = _scrub_hallucinations(ans, blob6, lang=lang)
    ans = strip_llm_deadline_notes(ans)
    fact_urls = [f.source.get("url") for f in selected_facts if f.source.get("url")]
    ans = finalize_answer_urls(ans, hits[:6], fact_urls=fact_urls, lang=lang, hits_blob=blob6)
    ans += deadline_passed_note(ans, lang)
    state.original_question = None
    return _attach_state(dict(clarify=False, mode="wyszukiwanie", sources=srcs, profile=prof, topics=topics, lang=lang, answer=ans), state)
