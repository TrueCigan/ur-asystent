"""Budowa indeksu: chunking + BM25 + TF-IDF (char n-gram) -> data/index.npz + data/meta.json.gz
Lekka wersja (tylko numpy/scipy, float32, ograniczony słownik n-gramów) – mieści się w 512 MB (Render free)."""
import json, re, os, math, gzip, unicodedata, collections
import numpy as np, scipy.sparse as sp
D = os.path.join(os.path.dirname(__file__), "..", "data")
NGRAM = (3, 5)
MAX_FEATURES = int(os.getenv("MAX_NGRAMS", "60000"))  # < 65536 -> indeksy uint16
TOPK = int(os.getenv("TOPK_NGRAMS", "400"))  # najwyżej TOPK najsilniejszych n-gramów na fragment
K1, B, EPS = 1.5, 0.75, 0.25

def norm(s):
    s = unicodedata.normalize("NFKD", s.lower().replace("ł", "l"))
    return "".join(c for c in s if not unicodedata.combining(c))

STOP = set("i w z na do o a sie ze to jest nie lub oraz dla od po przez jak czy co ktore ktory ktora jego ich tym ten ta te by sa".split())
def tokens(s):
    return [w[:6] for w in re.findall(r"[a-z0-9]+", norm(s)) if w not in STOP and len(w) > 1]

def char_ngrams(s):
    """Odpowiednik analyzer='char_wb' ze scikit-learn."""
    out = []
    for w in norm(s).split():
        w = " " + w + " "; L = len(w)
        for n in range(NGRAM[0], NGRAM[1] + 1):
            out.append(w[0:n])
            if L <= n: break
            out.extend(w[i:i + n] for i in range(1, L - n + 1))
    return out

def chunk(text, size=1200, overlap=200):
    text = re.sub(r"[ \t]+", " ", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        while len(p) > size:
            out.append((cur + "\n" + p[:size]).strip()); cur = ""; p = p[size - overlap:]
        if len(cur) + len(p) > size and cur:
            out.append(cur.strip()); cur = cur[-overlap:]
        cur += "\n" + p
    if cur.strip(): out.append(cur.strip())
    return [c for c in out if len(c) > 60]

def _csr(rows, vocab_size):
    ind, ptr, val = [], [0], []
    for r in rows:
        ind.extend(r.keys()); val.extend(r.values()); ptr.append(len(ind))
    return sp.csr_matrix((np.array(val, np.float32), np.array(ind, np.int32), np.array(ptr, np.int64)), shape=(len(rows), vocab_size))

def char_vec(counts, voc, idf):
    """sublinear tf * idf, normalizacja L2 -> dict {kolumna: waga}"""
    r = {voc[g]: (1 + math.log(c)) * idf[voc[g]] for g, c in counts.items() if g in voc}
    n = math.sqrt(sum(v * v for v in r.values())) or 1.0
    return {k: v / n for k, v in r.items()}

def build():
    from topic_policy import is_denied_chunk
    fp = os.path.join(D, "docs.jsonl")
    f = open(fp, encoding="utf-8") if os.path.exists(fp) else gzip.open(fp + ".gz", "rt", encoding="utf-8")
    chunks = []
    skipped = 0
    for l in f:
        d = json.loads(l)
        for i, c in enumerate(chunk(d["text"])):
            row = dict(url=d["url"], title=d["title"], modified=d["modified"], source=d["source"],
                       kind=d["kind"], scanned=d.get("scanned", False), text=c, i=i)
            # Global deny lists only (topics=None); per-topic denies stay query-time (R6-6)
            if is_denied_chunk(row, topics=None):
                skipped += 1
                continue
            chunks.append(row)
    N = len(chunks)
    if skipped:
        print(f"skipped_denied_chunks={skipped}")
    # --- BM25 (Okapi, jak rank_bm25) jako macierz wag dokument x termin ---
    toks = [collections.Counter(tokens(c["title"] + " " + c["text"])) for c in chunks]
    df = collections.Counter(t for c in toks for t in c)
    tvoc = {t: j for j, t in enumerate(sorted(df))}
    idf = {t: math.log(N - n + 0.5) - math.log(n + 0.5) for t, n in df.items()}
    avg_idf = sum(idf.values()) / len(idf)
    idf = {t: (v if v >= 0 else EPS * avg_idf) for t, v in idf.items()}
    dl = [sum(c.values()) for c in toks]; avgdl = sum(dl) / N
    bm = _csr([{tvoc[t]: idf[t] * n * (K1 + 1) / (n + K1 * (1 - B + B * dl[i] / avgdl)) for t, n in c.items()} for i, c in enumerate(toks)], len(tvoc))
    del toks
    # --- char n-gram TF-IDF (char_wb 3-5, sublinear, słownik ograniczony do MAX_FEATURES) ---
    cdf = collections.Counter()
    for c in chunks: cdf.update(set(char_ngrams(c["title"] + " " + c["text"])))
    keep = [g for g, n in sorted(cdf.items(), key=lambda x: (-x[1], x[0])) if n >= 2][:MAX_FEATURES]
    keep.sort(); cvoc = {g: j for j, g in enumerate(keep)}
    cidf = np.array([math.log((1 + N) / (1 + cdf[g])) + 1 for g in keep], np.float32)
    cdf = {g: cdf[g] for g in keep}
    def pruned(c):
        v = char_vec(collections.Counter(char_ngrams(c["title"] + " " + c["text"])), cvoc, cidf)
        return dict(sorted(v.items(), key=lambda x: -x[1])[:TOPK])
    X = _csr([pruned(c) for c in chunks], len(cvoc))
    X = sp.csr_matrix((X.data.astype(np.float16), X.indices.astype(np.uint16), X.indptr.astype(np.int32)), shape=X.shape)
    np.savez_compressed(os.path.join(D, "index.npz"), bm_data=bm.data.astype(np.float16), bm_ind=bm.indices.astype(np.uint16), bm_ptr=bm.indptr.astype(np.int32), bm_shape=bm.shape,
                        x_data=X.data, x_ind=X.indices, x_ptr=X.indptr, x_shape=X.shape, cidf=cidf)
    with gzip.open(os.path.join(D, "meta.json.gz"), "wt", encoding="utf-8") as g:
        json.dump(dict(chunks=chunks, tvocab=sorted(df), cvocab=keep), g, ensure_ascii=False)
    print(f"docs/chunks={N} bm25_terms={len(tvoc)} ngrams={len(cvoc)} nnz_bm25={bm.nnz} nnz_char={X.nnz}")

if __name__ == "__main__":
    build()
