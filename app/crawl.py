"""Uprzejmy crawler korpusu Uniwersytetu Radomskiego (tylko publiczne strony)."""
import re, json, time, html, hashlib, subprocess, tempfile, os, sys
from urllib.parse import urljoin, unquote
import httpx
from bs4 import BeautifulSoup

UA = "UR-Assistant-Prototype/0.1 (student project; polite crawler)"
DELAY = float(os.getenv("CRAWL_DELAY", "1.0"))
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "docs.jsonl")
cli = httpx.Client(headers={"User-Agent": UA}, timeout=40, follow_redirects=True)
seen = set(); docs = []

def get(url):
    time.sleep(DELAY)
    try:
        r = cli.get(url); r.raise_for_status(); return r
    except Exception as e:
        print("ERR", url, e, file=sys.stderr); return None

def clean_html(h):
    s = BeautifulSoup(h, "html.parser")
    for t in s(["script", "style", "nav", "header", "footer", "noscript", "form"]): t.decompose()
    txt = s.get_text("\n")
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\xa0]+", " ", txt)).strip()

def file_text(url):
    r = get(url)
    if not r: return None
    ext = url.lower().split("?")[0].rsplit(".", 1)[-1]
    ct0 = r.headers.get("content-type", "")
    if ext not in ("pdf", "docx", "doc"): ext = "pdf" if ("pdf" in ct0 or r.content[:4] == b"%PDF") else ("docx" if "officedocument" in ct0 or r.content[:2] == b"PK" else "bin")
    with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as f:
        f.write(r.content); p = f.name
    try:
        ct = r.headers.get("content-type", "")
        if ext == "pdf" or "pdf" in ct:
            t = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True, timeout=120).stdout
        elif ext == "docx" or "officedocument" in ct:
            import docx; t = "\n".join(x.text for x in docx.Document(p).paragraphs)
        else: t = None
    except Exception as e:
        print("ERRTXT", url, e, file=sys.stderr); t = None
    os.unlink(p)
    return t, r.headers.get("last-modified")

def add(url, title, text, modified, source, kind, scanned=False):
    if url in seen or not text: return
    seen.add(url)
    d = dict(url=url, title=title.strip(), text=text, modified=modified, source=source, kind=kind, scanned=scanned)
    docs.append(d)
    with open(OUT, "a") as f: f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"+ [{source}/{kind}] {title[:70]} ({modified}) {len(text)}ch")

def add_file(url, parent_title, source, modified_hint=None, max_files=None):
    if url in seen: return
    res = file_text(url)
    if not res: return
    t, lm = res
    from email.utils import parsedate_to_datetime
    mod = modified_hint
    if lm:
        try: mod = parsedate_to_datetime(lm).date().isoformat()
        except Exception: pass
    m = re.search(r"/uploads/(?:sites/\d+/)?(\d{4})/(\d{2})/", url)
    if not mod and m: mod = f"{m.group(1)}-{m.group(2)}-01"
    name = unquote(url.rsplit("/", 1)[-1])
    scanned = t is not None and len(t.strip()) < 200
    add(url, f"{parent_title} – {name}", t if t and t.strip() else "[dokument bez warstwy tekstowej – prawdopodobnie skan]", mod, source, "file", scanned)

def file_links(h, base):
    return sorted({urljoin(base, a) for a in re.findall(r'href="([^"]+\.(?:pdf|docx))"', h, re.I)})

def wp_site(host, types=("pages", "posts"), source=None, filt=None, files=True, max_posts=200):
    for t in types:
        page = 1
        while True:
            r = get(f"https://{host}/wp-json/wp/v2/{t}?per_page=50&page={page}&_fields=link,title,modified,content")
            if not r or r.status_code != 200: break
            items = r.json()
            if not items: break
            for it in items:
                url = it["link"]; title = html.unescape(re.sub("<[^>]+>", "", it["title"]["rendered"]))
                if filt and not filt(url, title): continue
                body = it["content"]["rendered"]
                add(url, title, clean_html(body), it["modified"][:10], source or host, "page")
                if files:
                    for f in file_links(body, url): add_file(f, title, source or host)
            if len(items) < 50 or page * 50 >= max_posts: break
            page += 1

BIP = "https://bip.uniwersytetradom.pl"
KEY = re.compile(r"regulamin|studi|stypend|świadcz|opłat|doktor|cudzoziem|rok akadem|organizacj\w* roku|pomoc materialn|zasad|rekrutac", re.I)

def bip_list(path, years=("2025", "2026"), keyfilter=True, maxpages=5):
    for p in range(1, maxpages + 1):
        r = get(f"{BIP}{path}" + (f"?page={p}" if p > 1 else ""))
        if not r: break
        links = sorted(set(re.findall(r'href="(/(?:uchwala|artykul|zarzadzenie)/[^"#?]+)"', r.text)))
        links = [l for l in links if not re.search(r"cookies|instrukcja|slownik|zespol|ponowne|udostepnianie|poprzednie", l)]
        if not links: break
        new = 0
        for l in links:
            u = BIP + l
            if u in seen: continue
            if years and l.startswith("/uchwala/") and not any(y in l for y in years): continue
            new += 1; bip_item(u, keyfilter)
        if new == 0: break

def bip_item(u, keyfilter):
    r = get(u)
    if not r: return
    s = BeautifulSoup(r.text, "html.parser")
    main = s.find("main") or s
    txt = clean_html(str(main))
    title = (s.find("h1").get_text(" ", strip=True) if s.find("h1") else u)
    m = re.search(r"W sprawie:\s*(.+)", txt)
    subj = m.group(1).strip() if m else ""
    full = f"{title} {subj}"
    if keyfilter and not KEY.search(full): seen.add(u); return
    md = re.search(r"(\d{4}-\d{2}-\d{2})", txt)
    mod = md.group(1) if md else None
    add(u, f"BIP: {title} {('– ' + subj) if subj else ''}"[:250], txt, mod, "bip", "page")
    for a in re.findall(r'href="(/attachments/\d+/download/[^"]+)"', r.text)[:6]:
        add_file(BIP + a + ("" if a.lower().endswith(".pdf") else ""), f"BIP: {title} {subj}"[:150], "bip", mod)

if __name__ == "__main__":
    if "--fresh" in sys.argv and os.path.exists(OUT): os.remove(OUT)
    if os.path.exists(OUT):
        for l in open(OUT): seen.add(json.loads(l)["url"])
    which = [a for a in sys.argv[1:] if not a.startswith("--")] or ["student", "dwz", "rekrutacja", "bip", "wteii"]
    if "student" in which: wp_site("student.uniwersytetradom.pl", source="student")
    if "dwz" in which: wp_site("dwz.uniwersytetradom.pl", source="dwz")
    if "rekrutacja" in which:
        wp_site("rekrutacja.uniwersytetradom.pl", types=("pages",), source="rekrutacja",
                filt=lambda u, t: bool(re.search(r"cudzoziem|foreign|international|doktor|obywatel|zasady|opłat|oplat|admission", u + t, re.I)))
    if "bip" in which:
        for path in ["/artykuly/obowiazujace-akty-prawne", "/artykuly/akty-prawne", "/artykuly/uchwaly-senatu",
                     "/artykuly/uchwaly-rady-szkoly-doktorskiej", "/artykuly/zasady-i-tryb-przyjmowania-na-studia"]:
            bip_list(path)
    if "wteii" in which:
        r = get("https://wteii.uniwersytetradom.pl/plany-zajec/")
        if r:
            fl = [f for f in file_links(r.text, str(r.url)) if "/2026/" in f]
            add("https://wteii.uniwersytetradom.pl/plany-zajec/", "WTEiI – Plany zajęć", clean_html(r.text), None, "wteii", "page")
            for f in fl[:25]: add_file(f, "WTEiI – Plan zajęć", "wteii")
    print("DOCS", len(docs))
