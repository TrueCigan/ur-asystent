"""Offline regressions for the six live failures on 3133929. No LLM."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

os.environ["LLM_PROVIDER"] = ""
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("SCENARIO_SOCIAL", None)

import rag  # noqa: E402
from facts import Fact, doctoral_components, load_facts  # noqa: E402

_URL = re.compile(r"https?://[^\s)>\]]+")


def _urls(text):
    return [u.rstrip(".,;") for u in _URL.findall(text or "")]


def _answer(question, history=None):
    return rag.answer(question, history or [])


def test_fact_source_is_traceable_and_hallucinated_url_is_not_added():
    facts = load_facts()
    stipend = next(f for f in facts if f.id == "doctoral_stipend_amount")
    assert stipend.status == "verified"
    hit = {
        "n": 1,
        "title": "Świadczenia",
        "url": "https://student.uniwersytetradom.pl/stypendia-socjalne/",
        "modified": None,
        "outdated": False,
        "snippet": "see https://evil.example/phish for details",
    }
    cited = [facts.index(stipend) + 1]
    sources = rag.merge_official_sources([hit], facts, cited)
    urls = [s["url"] for s in sources]
    assert hit["url"] in urls
    assert stipend.source["url"] in urls
    traced = next(s for s in sources if s["url"] == stipend.source["url"])
    assert traced["fact_ids"] == ["doctoral_stipend_amount"]
    assert all("evil.example" not in s["url"] for s in sources)
    unverified = Fact(
        id="made_up", topic=["doktoranckie"], value="1", unit=None,
        academic_year=None, applies_to={}, source={"url": "https://evil.example/fact"},
        status="unverified", i18n_label={"pl": "x"},
    )
    sources2 = rag.merge_official_sources([hit], [unverified], [1])
    assert all("evil.example" not in s["url"] for s in sources2)
    text = rag.finalize_answer_urls(
        "Official page plus https://evil.example/phish",
        [{"title": "h", "url": hit["url"], "modified": None, "text": ""}],
        fact_urls=[stipend.source["url"]],
    )
    assert "evil.example" not in text


def test_rector_and_dorm_answers_only_cite_official_sources():
    rector = _answer(
        "Привет, я студент из Польши, учусь на бакалавре. Как получить ректорскую стипендию и сколько платят?"
    )
    dorm = _answer("Баярлалаа. Дотуур байрны үнэ хэд вэ?")
    for name, result in (("rector", rector), ("dorm", dorm)):
        src_urls = [(s.get("url") or "").rstrip("/") for s in result.get("sources") or []]
        for url in _urls(result.get("answer") or ""):
            assert url.rstrip("/") in src_urls, (name, url)
        for src in result.get("sources") or []:
            ids = src.get("fact_ids") or []
            if ids:
                assert src.get("url")
                assert all(isinstance(i, str) and i for i in ids)


def test_ukrainian_doctoral_self_id_variants_and_amounts():
    from rag import extract_profile
    for text in (
        "я аспірант",
        "я аспірантка",
        "я аспіранткою",
        "є аспірантом",
        "Я аспірантці",
    ):
        prof = extract_profile(text)
        assert prof.get("status") == "doktorant", text
        assert prof.get("poziom") == "SD", text
    bare = extract_profile("Розкажіть про аспірантуру в університеті")
    assert bare.get("status") != "doktorant"
    result = _answer(
        "Привіт, я аспірантка 3 року після оцінки середньоперіодичної, маю інвалідність. Яка стипендія?"
    )
    assert result.get("clarify") is False, (result.get("answer") or "")[:240]
    assert result.get("lang") == "uk"
    ans = result.get("answer") or ""
    assert "5500,50" in ans
    assert "1071,15" in ans
    assert "6571,65" in ans
    assert "2026/2027" in ans
    assert "01.01.2026" in ans


def test_doctoral_disability_total_uses_verified_decimals():
    fact = next(f for f in load_facts() if f.id == "doctoral_stipend_amount")
    parts = doctoral_components(fact)
    assert parts["przed"] == parts["przed"].quantize(parts["przed"])  # constructed
    assert str(parts["top"]) == "1071.15"
    assert str(parts["total_po"]) == "6571.65"
    assert str(parts["po"]) == "5500.50"
    assert str(parts["przed"]) == "3570.50"
    result = _answer(
        "Jestem doktorantką po ocenie śródokresowej z orzeczeniem o niepełnosprawności. Ile dostanę?"
    )
    ans = result.get("answer") or ""
    assert result.get("clarify") is False
    assert "6571,65" in ans
    assert "1071,15" in ans
    assert "5500,50" in ans
    assert "3570,50" in ans
    assert "2026/2027" in ans
    assert "37%" in ans
    assert not re.search(r"(?i)zwiększen\w*[^\.\n]{0,50}37\s*%", ans)


def test_english_tuition_followups_keep_language_and_amount():
    first = _answer("foreign student, residence permit, full-time, 1st degree")
    hist = [
        {"role": "user", "content": "foreign student, residence permit, full-time, 1st degree"},
        {"role": "assistant", "content": first.get("answer") or ""},
    ]
    second = _answer("how much for english programs? business", hist)
    ans = second.get("answer") or ""
    assert second.get("lang") == "en"
    assert second.get("clarify") is False
    assert re.search(r"2[ ,.]?100\s*(EUR|euro)", ans, re.I)
    assert (second.get("profile") or {}).get("status") == "cudzoziemiec"

    intro = _answer(
        "Hi, I am a foreign student from India. How much is the tuition fee for English-language study programmes at Radom University?"
    )
    hist2 = [
        {"role": "user", "content": "Hi, I am a foreign student from India. How much is the tuition fee for English-language study programmes at Radom University?"},
        {"role": "assistant", "content": intro.get("answer") or ""},
    ]
    follow = _answer(
        "I want to do a masters, the 2nd cycle, and I will study on weekends only because I also work in the city.",
        hist2,
    )
    assert follow.get("lang") == "en"
    assert follow.get("clarify") is False
    text = follow.get("answer") or ""
    assert re.search(r"2[ ,.]?100", text)
    assert (follow.get("profile") or {}).get("poziom") == "II"


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as exc:
                failed += 1
                print("FAIL", name, exc)
    print(f"\n{failed} failed")
    raise SystemExit(1 if failed else 0)
