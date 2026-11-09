"""Offline checks for the Phase 1 fetch guard and file-index revisions."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ["EVAL_REAL"] = "0"
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)

import allowlist  # noqa: E402
import fetch_public  # noqa: E402
import index_revision  # noqa: E402
from facts import load_facts  # noqa: E402

PUBLIC = "8.8.8.8"
STUDENT = "https://student.uniwersytetradom.pl/domy-studenckie/"


def _allow(url: str) -> str:
    return allowlist.assert_enabled(url)


def _ok_robots(url, timeout):
    del timeout
    return (200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /\n")


def _transport(pages: dict):
    def request(url, timeout):
        del timeout
        if url not in pages:
            raise AssertionError(f"unexpected url {url}")
        item = pages[url]
        if item == "timeout":
            raise TimeoutError("timed out")
        return item
    return request


def _resolve_public(host: str):
    return [PUBLIC]


def test_allowlist_enables_only_existing_crawl_seeds():
    enabled = allowlist.enabled_hosts()
    assert "student.uniwersytetradom.pl" in enabled
    assert "dwz.uniwersytetradom.pl" in enabled
    assert "bip.uniwersytetradom.pl" in enabled
    for host in (
        "euczelnia.uniwersytetradom.pl",
        "sjo.uniwersytetradom.pl",
        "www.erasmusplus.org.pl",
        "www.gov.pl",
        "dziennikustaw.gov.pl",
    ):
        assert host in enabled
    for host in (
        "kn.uniwersytetradom.pl",
        "wicit.uniwersytetradom.pl",
        "static1.squarespace.com",
        "isap.sejm.gov.pl",
        "odyseusz.msz.gov.pl",
    ):
        assert host not in enabled
    data = allowlist.load_allowlist()
    hosts = {row["host"] for row in data["crawl"]}
    assert "static1.squarespace.com" in hosts
    assert "isap.sejm.gov.pl" in hosts
    try:
        allowlist.assert_enabled("https://static1.squarespace.com/x")
    except allowlist.AllowlistError as exc:
        assert exc.code == "forbidden_host"
    else:
        raise AssertionError("squarespace was crawlable")
    assert not hasattr(allowlist, "add_host")


def test_ssrf_blocks_private_dns_metadata_and_redirects():
    pages = {
        "https://student.uniwersytetradom.pl/robots.txt": _ok_robots("", 0)[0:3] if False else (200, {}, b"User-agent: *\nAllow: /\n"),
        STUDENT: (200, {"content-type": "text/html"}, b"<p>ok</p>"),
    }
    # The expression above is just a tuple. Rebuild plainly.
    pages = {
        "https://student.uniwersytetradom.pl/robots.txt": (200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /\n"),
        STUDENT: (200, {"content-type": "text/html"}, b"<p>ok</p>"),
    }

    def private(_host):
        return ["10.1.2.3"]

    try:
        fetch_public.fetch(STUDENT, resolve=private, request=_transport(pages), robots=_transport(pages), allow_host=_allow, sleep=lambda _s: None)
    except fetch_public.FetchError as exc:
        assert exc.code == "ssrf"
    else:
        raise AssertionError("private DNS was fetched")

    for blocked in (
        "http://127.0.0.1/latest",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "https://metadata.google.internal/computeMetadata/v1/",
    ):
        try:
            fetch_public.fetch(blocked, resolve=lambda _h: [PUBLIC], request=_transport({}), robots=_transport({}), allow_host=_allow, sleep=lambda _s: None)
        except fetch_public.FetchError as exc:
            assert exc.code == "ssrf"
        else:
            raise AssertionError(f"fetched {blocked}")

    redirect_pages = {
        "https://student.uniwersytetradom.pl/robots.txt": (200, {}, b"User-agent: *\nAllow: /\n"),
        STUDENT: (302, {"location": "http://169.254.169.254/latest/meta-data/"}, b""),
    }
    try:
        fetch_public.fetch(
            STUDENT,
            resolve=_resolve_public,
            request=_transport(redirect_pages),
            robots=_transport(redirect_pages),
            allow_host=_allow,
            sleep=lambda _s: None,
        )
    except fetch_public.FetchError as exc:
        assert exc.code == "ssrf"
    else:
        raise AssertionError("metadata redirect was followed")


def test_limits_robots_and_two_jittered_retries():
    big = {
        "https://student.uniwersytetradom.pl/robots.txt": (200, {}, b"User-agent: *\nAllow: /\n"),
        "https://student.uniwersytetradom.pl/big.html": (
            200,
            {"content-type": "text/html", "content-length": str(fetch_public.HTML_MAX_BYTES + 1)},
            b"x",
        ),
    }
    try:
        fetch_public.fetch(
            "https://student.uniwersytetradom.pl/big.html",
            resolve=_resolve_public,
            request=_transport(big),
            robots=_transport(big),
            allow_host=_allow,
            sleep=lambda _s: None,
        )
    except fetch_public.FetchError as exc:
        assert exc.code == "too_large"
    else:
        raise AssertionError("oversized html was accepted")

    pdf = b"%PDF-1.4\n" + (b"/Type /Page\n" * (fetch_public.PDF_MAX_PAGES + 1))
    pages = {
        "https://student.uniwersytetradom.pl/robots.txt": (200, {}, b"User-agent: *\nAllow: /\n"),
        "https://student.uniwersytetradom.pl/a.pdf": (200, {"content-type": "application/pdf"}, pdf),
    }
    try:
        fetch_public.fetch(
            "https://student.uniwersytetradom.pl/a.pdf",
            resolve=_resolve_public,
            request=_transport(pages),
            robots=_transport(pages),
            allow_host=_allow,
            sleep=lambda _s: None,
        )
    except fetch_public.FetchError as exc:
        assert exc.code == "pdf_pages"
    else:
        raise AssertionError("201-page pdf was accepted")

    denied = {
        "https://student.uniwersytetradom.pl/robots.txt": (200, {}, b"User-agent: *\nDisallow: /secret\n"),
        "https://student.uniwersytetradom.pl/secret": (200, {"content-type": "text/html"}, b"no"),
    }
    try:
        fetch_public.fetch(
            "https://student.uniwersytetradom.pl/secret",
            resolve=_resolve_public,
            request=_transport(denied),
            robots=_transport(denied),
            allow_host=_allow,
            sleep=lambda _s: None,
        )
    except fetch_public.FetchError as exc:
        assert exc.code == "robots"
    else:
        raise AssertionError("robots disallow was ignored")

    calls = {"n": 0, "sleeps": []}

    def flaky(url, timeout):
        del timeout
        if url.endswith("/robots.txt"):
            return (200, {}, b"User-agent: *\nAllow: /\n")
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("slow")
        return (200, {"content-type": "text/html"}, b"ok")

    response = fetch_public.fetch(
        STUDENT,
        resolve=_resolve_public,
        request=flaky,
        robots=flaky,
        allow_host=_allow,
        sleep=lambda delay: calls["sleeps"].append(delay),
        rand=lambda: 0.0,
    )
    assert response.content == b"ok"
    assert calls["n"] == 3
    assert len(calls["sleeps"]) == 2
    assert fetch_public.TIMEOUT_SEC == 15
    assert fetch_public.RETRIES == 2
    assert fetch_public.HTML_MAX_BYTES == 5 * 1024 * 1024
    assert fetch_public.PDF_MAX_BYTES == 20 * 1024 * 1024


def test_revision_is_idempotent_and_rolls_back_without_postgres():
    root = Path("/tmp/ur-phase1-revisions")
    if root.exists():
        import shutil
        shutil.rmtree(root)
    docs_a = [{"url": "https://student.uniwersytetradom.pl/a", "text": "one"}]
    docs_b = [{"url": "https://student.uniwersytetradom.pl/b", "text": "two"}]

    def build(staging, docs):
        (staging / "index.npz").write_bytes(b"index-" + docs[0]["text"].encode())
        (staging / "meta.json.gz").write_bytes(b"meta")

    first = index_revision.publish(root, docs_a, build)
    again = index_revision.publish(root, docs_a, build)
    assert first == again
    assert len(list((root / "revisions").iterdir())) == 1
    second = index_revision.publish(root, docs_b, build)
    assert second != first
    assert index_revision.current_id(root) == second
    runtime = root / "runtime"
    index_revision.activate(root, runtime)
    assert (runtime / "index.npz").read_bytes() == b"index-two"
    previous = index_revision.rollback(root, first)
    assert previous == second
    assert index_revision.current_id(root) == first
    assert (root / "revisions" / second).is_dir()
    index_revision.activate(root, runtime)
    assert (runtime / "index.npz").read_bytes() == b"index-one"

    def boom(_staging, _docs):
        raise RuntimeError("builder failed")

    try:
        index_revision.publish(root, [{"url": "https://student.uniwersytetradom.pl/c", "text": "three"}], boom)
    except RuntimeError:
        pass
    else:
        raise AssertionError("failed build published")
    assert index_revision.current_id(root) == first
    assert not (root / ".staging").exists() or not any((root / ".staging").iterdir())


def test_owner_facts_keep_years_separate_and_cover_erasmus():
    facts = {fact.id: fact for fact in load_facts(str(ROOT / "data" / "facts.yaml"))}
    cap_old = facts["rector_social_cap_monthly_2025_2026"]
    cap_new = facts["rector_social_cap_monthly"]
    assert cap_old.value == 3560.60
    assert cap_new.value == 3667.0
    assert cap_old.academic_year == "2025/2026"
    assert cap_new.academic_year == "2026/2027"
    notes = " ".join(str(item.get("note")) for item in cap_old.candidates_seen)
    assert "3556" in notes
    assert "3560" in notes
    dorm = facts["dorm_application_deadline"].value
    assert dorm["application_end"] == "2026-05-15"
    assert dorm["check_in_is_application_deadline"] is False
    assert "2026-09-29" in dorm["check_in_dates"]
    window = facts["social_rector_deadline"]
    assert window.deadline["end"] == "2026-10-05"
    who = facts["rector_cycle_eligibility"].value
    assert who["doctoral_school"] == "no"
    assert who["age_under_26_required"] is False
    assert "Moje stypendia" in facts["submission_channel"].value
    assert facts["doctoral_stipend_period"].value.startswith("podczas roku")
    erasmus = facts["erasmus_application_2026_2027"].value
    assert erasmus["written_motivation_letter_to_dean"] is False
    assert "Podanie do Prorektora" in erasmus["steps"][1]
    assert facts["erasmus_rates_2026_2027"].value["group_3_eur_month"] == 600
    assert "long-term traineeships" in facts["erasmus_rates_2026_2027"].value["table_scope"].lower() or "traineeship" in facts["erasmus_rates_2026_2027"].value["table_scope"].lower()


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as exc:
                failed += 1
                print("FAIL", name, type(exc).__name__, exc)
    print(f"\n{failed} failed")
    raise SystemExit(1 if failed else 0)
