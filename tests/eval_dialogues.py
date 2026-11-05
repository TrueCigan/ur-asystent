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


KNOWN_CASE_KEYS = {
    "id", "origin", "turns", "unit", "per_turn_lang_not", "e2e", "deadline_note",
    "output_lang_check", "income_group_table", "scrub_check", "amount_strip_check",
    "property_check", "render_check", "expect_fail_until", "prompt_budget", "fault",
}


def run_unit(ctx, case):
    fails, rag, hist = [], ctx.rag, []
    exp = case.get("unit") or {}
    lang = topics = prof = missing = None

    # R5-1: pre-seeded state with empty history
    if "state_profile" in exp:
        import time
        from session import SessionState, encode
        st = SessionState(profile=dict(exp["state_profile"]), updated_at=int(time.time()))
        token = encode(st)
        q0 = case["turns"][0]
        r = rag.answer(q0, [], state_token=token)
        topics = r.get("topics") or []
        prof = r.get("profile") or {}
        # Recompute missing via merge with empty history
        topics_n, prof_n, _ = rag.needed(q0, "")
        prof, missing = rag.merge_state_profile(st, prof_n, topics_n, [])
        lang = r.get("lang")
        if not r.get("clarify") and "status" in (exp.get("missing") or []):
            fails.append("expected clarify with empty history + stale state")
    else:
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
    for k, v in (exp.get("profile_not") or {}).items():
        if prof.get(k) == v:
            fails.append(f"profile.{k} unexpectedly {v}")
    if "missing" in exp and missing != exp["missing"]:
        fails.append(f"missing={missing} want {exp['missing']}")
    for m in exp.get("missing_not", []):
        if m in missing:
            fails.append(f"still asks {m}")
    if "income_group" in exp:
        try:
            from facts import income_group, load_facts
            ig = exp["income_group"]
            groups = None
            for fact in load_facts():
                if fact.id in ("social_amount_groups", "social_income_threshold") and fact.value:
                    groups = fact.value
                    break
            g, _amt = income_group(ig["income"], groups)
            if g != ig.get("expect_group"):
                fails.append(f"income_group={g} want {ig.get('expect_group')}")
        except Exception as e:
            fails.append(f"income_group error: {e}")
    if "retrieval" in exp:
        try:
            q = case["turns"][-1]
            hu = "\n".join(case["turns"][:-1])
            topics = topics or []
            if not topics:
                topics, prof, _ = rag.needed(q, hu)
            else:
                _, prof, _ = rag.needed(q, hu)
            query = rag.build_query(q, case["turns"][:-1], topics, prof)
            # BM25-only: temporarily disable embeddings if present
            emb = None
            if getattr(rag, "IDX", None) and rag.IDX.get("emb") is not None:
                emb = rag.IDX["emb"]
                rag.IDX["emb"] = None
            try:
                hits = rag.search(query, k=5, topics=topics, profile=prof)
            finally:
                if emb is not None and rag.IDX is not None:
                    rag.IDX["emb"] = emb
            urls = " ".join((h.get("url") or "") for h in hits)
            for sub in (exp["retrieval"].get("must_not_match_urls") or []):
                if sub in urls:
                    fails.append(f"retrieval url contains forbidden {sub!r}")
            for sub in (exp["retrieval"].get("top5_must_match_url") or []):
                if sub.lower() not in urls.lower():
                    fails.append(f"top5 missing url substring {sub!r} in {urls[:200]!r}")
        except Exception as e:
            fails.append(f"retrieval error: {e}")
    return fails


def run_deadline(ctx, case):
    d = case["deadline_note"]
    today = None
    if d.get("today"):
        from datetime import date
        today = date.fromisoformat(d["today"])
    # Mirror production: strip LLM inline notes, then code-owned warnings
    cleaned = d["text"]
    try:
        from deadlines import parse_deadlines, render_deadline_notes, strip_llm_deadline_notes
        cleaned = strip_llm_deadline_notes(d["text"])
        if today is not None:
            notes = render_deadline_notes(parse_deadlines(cleaned, today), d.get("lang", "pl"), today)
        else:
            notes = ctx.rag.deadline_passed_note(cleaned, d.get("lang", "pl"))
        out = notes
        combined = cleaned + (notes or "")
    except Exception:
        out = ctx.rag.deadline_passed_note(d["text"], d.get("lang", "pl"))
        combined = out
    n = out.count("⚠️")
    f = [] if n == d["expect_count"] else [f"deadline notes={n} want {d['expect_count']}: {out!r}"]
    for rx in d.get("must_not_match", []):
        if re.search(rx, out):
            f.append(f"note matches forbidden {rx}")
    for rx in d.get("body_must_not_match", []):
        if re.search(rx, cleaned):
            f.append(f"body matches forbidden {rx}")
    for rx in d.get("must_match", []):
        if not re.search(rx, combined):
            f.append(f"note missing /{rx}/")
    return f


def run_output_lang_check(ctx, case):
    from lang import output_lang_ok
    c = case["output_lang_check"]
    ok = output_lang_ok(c["text"], c["target"])
    if bool(ok) != bool(c["expect_ok"]):
        return [f"output_lang_ok={ok} want {c['expect_ok']}"]
    return []


def run_property_check(ctx, case):
    """Pure fixture guards: forbidden patterns / numbers ⊆ facts (no LLM)."""
    from decimal import Decimal
    pc = case["property_check"]
    text = pc.get("answer_fixture") or ""
    f = []
    for rx in pc.get("must_match", []) or []:
        if not re.search(rx, text):
            f.append(f"property missing /{rx}/ in {text!r}")
    for rx in pc.get("must_not_match", []) or []:
        if re.search(rx, text):
            f.append(f"property forbidden /{rx}/ in {text!r}")
    if pc.get("numbers_subset_of_facts"):
        try:
            from facts import amounts_in, fact_amounts, load_facts
            facts = load_facts()
            ids = pc.get("fact_ids") or []
            allowed = fact_amounts([x for x in facts if x.id in ids] if ids else facts)
            bad = amounts_in(text) - allowed
            if bad:
                f.append(f"property amounts not in facts: {sorted(bad, key=str)}")
        except Exception as e:
            f.append(f"property numbers_subset_of_facts error: {e}")
    if pc.get("output_lang_target"):
        from lang import output_lang_ok
        if not output_lang_ok(text, pc["output_lang_target"]):
            f.append(f"property output_lang_ok failed for target={pc['output_lang_target']}")
    return f


def run_render_check(ctx, case):
    """Server-side template renderer (Phase 1+). Skip cleanly if render.py not ready."""
    try:
        from render import render_answer, build_computed
    except ImportError:
        return ["render_check: app/render.py not available (Phase 1)"]
    rc = case["render_check"]
    try:
        from facts import load_facts
        facts = load_facts()
        want_ids = set(rc.get("fact_ids") or [])
        selected = [f for f in facts if not want_ids or f.id in want_ids]
        computed = build_computed(selected, rc.get("computed_need") or [])
        out = render_answer(
            rc["template"],
            selected,
            computed=computed,
            lang=rc.get("lang", "pl"),
        )
    except Exception as e:
        return [f"render_check error: {e}"]
    f = []
    for rx in rc.get("must_match", []) or []:
        if not re.search(rx, out):
            f.append(f"render missing /{rx}/ in {out!r}")
    for rx in rc.get("must_not_match", []) or []:
        if re.search(rx, out):
            f.append(f"render forbidden /{rx}/ in {out!r}")
    return f


def run_prompt_budget(ctx, case):
    b = case["prompt_budget"]
    sys = getattr(ctx.rag, "SYSTEM", "") or ""
    f = []
    if len(sys) > b.get("max_chars", 10**9):
        f.append(f"SYSTEM len={len(sys)} > {b['max_chars']}")
    for rx in b.get("must_not_match", []):
        if re.search(rx, sys):
            f.append(f"SYSTEM matches forbidden /{rx}/")
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


def check_answer(r, exp, elapsed=None):
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
    if exp.get("max_seconds") is not None and elapsed is not None and elapsed > exp["max_seconds"]:
        f.append(f"took {elapsed:.1f}s > {exp['max_seconds']}s")
    if exp.get("urls_subset_of_sources"):
        src = json.dumps(r.get("sources") or [], ensure_ascii=False)
        bad = [u for u in URL.findall(ans) if u.rstrip(".,;") not in src]
        if bad:
            f.append(f"urls not in sources: {bad[:3]}")
    if exp.get("citations_subset_of_sources"):
        # Body [n] must be ≤ listed sources under Źródła/Sources/Джерела
        body, _, src_block = ans.partition("Źródła:")
        if "Sources:" in ans and "Źródła:" not in ans:
            body, _, src_block = ans.partition("Sources:")
        if "Джерела:" in ans:
            body, _, src_block = ans.partition("Джерела:")
        n_src = len(re.findall(r"(?m)^\s*\[\d+\]\s*https?://", src_block or ""))
        cites = [int(x) for x in re.findall(r"\[(\d+)\]", body)]
        bad = [c for c in cites if c < 1 or (n_src and c > n_src)]
        if bad:
            f.append(f"citations not in sources list: {bad[:5]} (n_src={n_src})")
    return f


def run_e2e(ctx, case, url, runs):
    import time
    exp = case.get("e2e") or {}
    fault = case.get("fault") or {}
    if not exp and not fault:
        return []
    # R5-8: monkeypatch LLM timeout
    orig_llm = None
    if fault.get("llm") == "timeout" and not url:
        import httpx
        orig_llm = ctx.rag.call_llm
        def _boom(*_a, **_k):
            raise httpx.ReadTimeout("simulated")
        ctx.rag.call_llm = _boom
    fails, captures = [], []
    try:
        for _ in range(runs):
            hist = []
            r = {}
            for i, q in enumerate(case["turns"]):
                t0 = time.monotonic()
                r = ask(ctx, url, q, hist)
                elapsed = time.monotonic() - t0
                if exp.get("every_turn") or i == len(case["turns"]) - 1:
                    fails += [f"turn{i+1}: {x}" for x in check_answer(r, exp or {}, elapsed=elapsed)]
                hist += [{"role": "user", "content": q}, {"role": "assistant", "content": r.get("answer", "")}]
            for rx in (exp or {}).get("stable_across_runs", []):
                m = re.search(rx, r.get("answer", ""), re.I | re.S)
                captures.append(m.group(1) if m else None)
        if (exp or {}).get("stable_across_runs") and len(set(captures)) > 1:
            fails.append(f"unstable across runs: {captures}")
    finally:
        if orig_llm is not None:
            ctx.rag.call_llm = orig_llm
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
    skipped = 0
    for c in cases:
        if a.only and not re.search(a.only, c["id"]):
            continue
        # allow nested unit keys freely; flag unknown top-level only
        unknown = {k for k in c if k not in KNOWN_CASE_KEYS}
        total += 1
        if c.get("expect_fail_until"):
            skipped += 1
            print(f"SKIP {c['id']:<34} until {c['expect_fail_until']} {c.get('origin', '')}")
            continue
        f = []
        if unknown:
            f.append(f"unknown case keys: {sorted(unknown)} (harness must implement or reject)")
        if "deadline_note" in c:
            f += run_deadline(ctx, c)
        elif "output_lang_check" in c:
            f += run_output_lang_check(ctx, c)
        elif "prompt_budget" in c:
            f += run_prompt_budget(ctx, c)
        elif "property_check" in c:
            f += run_property_check(ctx, c)
        elif "render_check" in c:
            f += run_render_check(ctx, c)
        elif "scrub_check" in c:
            sc = c["scrub_check"]
            out = ctx.rag._scrub_hallucinations(
                sc["text"],
                sc.get("hits_blob", ""),
                lang=sc.get("lang", "en"),
                facts_blob=sc.get("facts_blob", ""),
            )
            for rx in sc.get("must_match", []):
                if not re.search(rx, out):
                    f.append(f"scrub missing /{rx}/ in {out!r}")
            for rx in sc.get("must_not_match", []):
                if re.search(rx, out):
                    f.append(f"scrub left forbidden /{rx}/ in {out!r}")
        elif "amount_strip_check" in c:
            from decimal import Decimal
            from facts import strip_unknown_amounts
            ac = c["amount_strip_check"]
            allowed = {Decimal(str(x)) for x in (ac.get("allowed") or [])}
            out, _ = strip_unknown_amounts(ac["text"], allowed)
            for rx in ac.get("must_match", []):
                if not re.search(rx, out):
                    f.append(f"amount_strip missing /{rx}/ in {out!r}")
            for rx in ac.get("must_not_match", []):
                if re.search(rx, out):
                    f.append(f"amount_strip left forbidden /{rx}/ in {out!r}")
        elif "income_group_table" in c:
            try:
                from facts import income_group, load_facts
                groups = None
                # Prefer CI fixture so boundaries don't depend on owner edits
                fix = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "facts_test.yaml")
                for fact in (load_facts(fix) if os.path.isfile(fix) else []) + load_facts():
                    if fact.id in ("social_amount_groups", "social_income_threshold") and fact.value:
                        groups = fact.value
                        break
                for row in (c["income_group_table"].get("cases") or []):
                    g, _amt = income_group(row["income"], groups)
                    if g != row["expect"]:
                        f.append(f"income {row['income']} → {g} want {row['expect']}")
            except Exception as e:
                f.append(f"income_group_table error: {e}")
        else:
            if a.layer in ("unit", "all") and ("unit" in c or "per_turn_lang_not" in c or "turns" in c):
                if "unit" in c or "per_turn_lang_not" in c:
                    f += run_unit(ctx, c)
            # fault cases exercise answer() even on unit layer (deterministic mock)
            if c.get("fault") and a.layer in ("unit", "e2e", "all"):
                f += run_e2e(ctx, c, a.url if a.layer != "unit" else None, a.runs if a.layer != "unit" else 1)
            elif a.layer in ("e2e", "all"):
                f += run_e2e(ctx, c, a.url, a.runs)
        print(("FAIL " if f else "PASS ") + f"{c['id']:<34} {c.get('origin','')}" + ("".join(f"\n     - {x}" for x in f)))
        failed += bool(f)
    print(f"\n{total} cases, {failed} failed, {skipped} skipped")
    sys.exit(min(failed, 100))


if __name__ == "__main__":
    main()
