#!/usr/bin/env python3
"""Regression harness for ur-asystent. Replays QA dialogues from rounds 1-3 and asserts expectations.

Usage:
  # unit layer (deterministic, no LLM, no network) - run on every commit / in CI
  python tests/eval_dialogues.py --repo . --layer unit
  # e2e layer against rag.answer() in-process (needs LLM key) or a deployed URL
  python tests/eval_dialogues.py --repo . --layer e2e [--url https://ur-asystent.onrender.com] [--runs 3]
Exit code = number of failed cases (0 = green). Cases: cases.yaml (one entry per dialogue).

Case schema (all keys optional except id/turns):
  id, origin (r1-S4 ...), turns: [str],
  unit:   # checked after the LAST turn via rag.needed()/rag.detect_lang()
    lang: uk | lang_not: [ru] | topics_include: [..] | topics_exclude: [..]
    profile: {status: pl, ...} | missing: [] | missing_not: [status]
  per_turn_lang_not: [ru]           # detect_lang on every turn
  e2e:    # checked on final (or every, with every_turn: true) answer text
    every_turn: false
    lang_in: [uk, pl, en] | must_match: [regex] | must_not_match: [regex]
    max_count: {"⚠️": 1} | urls_subset_of_sources: true | stable_across_runs: [regex-capture]
  deadline_note: {text: "...", lang: pl, expect_count: 1}   # pure function test
"""
import argparse, importlib, json, os, re, sys, urllib.request
import yaml

RU = re.compile(r"[ыэъЫЭЪ]|\b(что|спасибо|вот|сколько|можно)\b", re.I)
UK = re.compile(r"[іїєґІЇЄҐ]")
MN = re.compile(r"[өүӨҮ]")
PL = re.compile(r"[ąćęłńóśźż]", re.I)
URL = re.compile(r"https?://[^\s)\]\"'<>]+")


def guess_lang(text):
    """Cheap output-language detector for assertions (replace with fastText/lingua if available)."""
    cyr = len(re.findall(r"[а-яА-ЯёЁіїєґөүІЇЄҐӨҮ]", text))
    lat = len(re.findall(r"[a-zA-Z]", text))
    if cyr > lat:
        if MN.search(text):
            return "mn"
        if RU.search(text) and len(re.findall(r"[ыэъ]", text)) >= len(UK.findall(text)):
            return "ru"
        return "uk"
    return "pl" if PL.search(text) else "en"


class Ctx:
    def __init__(self, repo):
        sys.path.insert(0, os.path.join(repo, "app"))
        os.chdir(os.path.join(repo, "app"))
        self.rag = importlib.import_module("rag")


def run_unit(ctx, case):
    fails, rag, hist = [], ctx.rag, []
    exp = case.get("unit") or {}
    lang = topics = prof = missing = None
    for i, q in enumerate(case["turns"]):
        hu = "\n".join(hist)
        lang = rag.detect_lang(q, hu, latest=q)
        if lang in case.get("per_turn_lang_not", []):
            fails.append(f"turn{i+1}: detect_lang={lang}")
        topics, prof, missing = rag.needed(q, hu)
        hist.append(q)
    if not exp:
        return fails
    if "lang" in exp and lang != exp["lang"]:
        fails.append(f"lang={lang} want {exp['lang']}")
    for t in exp.get("topics_include", []):
        if t not in topics:
            fails.append(f"topic {t} missing in {topics}")
    for t in exp.get("topics_exclude", []):
        if t in topics:
            fails.append(f"topic {t} present")
    for k, v in (exp.get("profile") or {}).items():
        if prof.get(k) != v:
            fails.append(f"profile.{k}={prof.get(k)} want {v}")
    if "missing" in exp and missing != exp["missing"]:
        fails.append(f"missing={missing} want {exp['missing']}")
    for m in exp.get("missing_not", []):
        if m in missing:
            fails.append(f"still asks {m}")
    return fails


def run_deadline(ctx, case):
    d = case["deadline_note"]
    out = ctx.rag.deadline_passed_note(d["text"], d.get("lang", "pl"))
    n = out.count("⚠️")
    f = [] if n == d["expect_count"] else [f"deadline notes={n} want {d['expect_count']}: {out!r}"]
    for rx in d.get("must_not_match", []):
        if re.search(rx, out):
            f.append(f"note matches forbidden {rx}")
    return f


def ask(ctx, url, q, hist):
    if url:
        req = urllib.request.Request(
            url.rstrip("/") + "/api/chat",
            method="POST",
            data=json.dumps({"question": q, "history": hist}).encode(),
            headers={"Content-Type": "application/json"},
        )
        return json.load(urllib.request.urlopen(req, timeout=120))
    return ctx.rag.answer(q, hist)


def check_answer(r, exp):
    f, ans = [], r.get("answer") or ""
    if exp.get("lang_in") and guess_lang(ans) not in exp["lang_in"]:
        f.append(f"answer lang={guess_lang(ans)} not in {exp['lang_in']}")
    for rx in exp.get("must_match", []):
        if not re.search(rx, ans, re.I | re.S):
            f.append(f"missing /{rx}/")
    for rx in exp.get("must_not_match", []):
        if re.search(rx, ans, re.I | re.S):
            f.append(f"forbidden /{rx}/")
    for s, mx in (exp.get("max_count") or {}).items():
        if ans.count(s) > mx:
            f.append(f"'{s}' x{ans.count(s)} > {mx}")
    if exp.get("urls_subset_of_sources"):
        src = json.dumps(r.get("sources") or [], ensure_ascii=False)
        bad = [u for u in URL.findall(ans) if u.rstrip(".,;") not in src]
        if bad:
            f.append(f"urls not in sources: {bad[:3]}")
    return f


def run_e2e(ctx, case, url, runs):
    exp = case.get("e2e") or {}
    if not exp:
        return []
    fails, captures = [], []
    for _ in range(runs):
        hist = []
        r = {}
        for i, q in enumerate(case["turns"]):
            r = ask(ctx, url, q, hist)
            if exp.get("every_turn") or i == len(case["turns"]) - 1:
                fails += [f"turn{i+1}: {x}" for x in check_answer(r, exp)]
            hist += [{"role": "user", "content": q}, {"role": "assistant", "content": r.get("answer", "")}]
        for rx in exp.get("stable_across_runs", []):
            m = re.search(rx, r.get("answer", ""), re.I | re.S)
            captures.append(m.group(1) if m else None)
    if exp.get("stable_across_runs") and len(set(captures)) > 1:
        fails.append(f"unstable across runs: {captures}")
    return sorted(set(fails))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--cases", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.yaml"))
    ap.add_argument("--layer", choices=["unit", "e2e", "all"], default="unit")
    ap.add_argument("--url")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only")
    a = ap.parse_args()
    cases = yaml.safe_load(open(a.cases, encoding="utf-8"))
    ctx = Ctx(os.path.abspath(a.repo))
    failed = 0
    total = 0
    for c in cases:
        if a.only and not re.search(a.only, c["id"]):
            continue
        total += 1
        f = []
        if "deadline_note" in c:
            f += run_deadline(ctx, c)
        else:
            if a.layer in ("unit", "all"):
                f += run_unit(ctx, c)
            if a.layer in ("e2e", "all"):
                f += run_e2e(ctx, c, a.url, a.runs)
        print(("FAIL " if f else "PASS ") + f"{c['id']:<34} {c.get('origin','')}" + ("".join(f"\n     - {x}" for x in f)))
        failed += bool(f)
    print(f"\n{total} cases, {failed} failed")
    sys.exit(min(failed, 100))


if __name__ == "__main__":
    main()
