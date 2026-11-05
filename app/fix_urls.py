"""One-off / repeatable migration: normalize URLs in data/meta.json.gz and docs.jsonl.gz."""
from __future__ import annotations

import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from url_norm import normalize_url


def fix_meta(path: str) -> int:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        meta = json.load(f)
    n = 0
    for c in meta.get("chunks") or []:
        u = c.get("url") or ""
        nu = normalize_url(u)
        if nu != u:
            c["url"] = nu
            n += 1
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    return n


def fix_docs(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    tmp = path + ".tmp"
    n = 0
    with gzip.open(path, "rt", encoding="utf-8") as fin, gzip.open(tmp, "wt", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            row = json.loads(line)
            u = row.get("url") or ""
            nu = normalize_url(u)
            if nu != u:
                row["url"] = nu
                n += 1
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return n


def main():
    root = os.path.join(os.path.dirname(__file__), "..", "data")
    meta = os.path.join(root, "meta.json.gz")
    docs = os.path.join(root, "docs.jsonl.gz")
    nm = fix_meta(meta) if os.path.isfile(meta) else 0
    nd = fix_docs(docs) if os.path.isfile(docs) else 0
    print(f"normalized meta chunks={nm} docs={nd}")
    # verify
    if os.path.isfile(meta):
        with gzip.open(meta, "rt", encoding="utf-8") as f:
            m = json.load(f)
        left = sum(1 for c in m.get("chunks") or [] if "%25" in (c.get("url") or ""))
        print(f"remaining %25 urls={left}")


if __name__ == "__main__":
    main()
