"""Phase 5 admin guards. No network, no live eval, no secrets on the page."""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ["EVAL_REAL"] = "0"
os.environ["SCENARIO_SOCIAL"] = "0"
os.environ["LLM_PROVIDER"] = "fake"
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)
os.environ["ADMIN_VIEWER_PASSWORD"] = "viewer-test-pass"
os.environ["ADMIN_EDITOR_PASSWORD"] = "editor-test-pass"
os.environ["ADMIN_ADMIN_PASSWORD"] = "admin-test-pass"
os.environ["ADMIN_TOKEN_SECRET"] = "phase5-test-secret"

import admin_ai  # noqa: E402
import phase4  # noqa: E402
from admin_ai import AdminError  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402


def _reset():
    phase4.NOTES.clear()
    phase4.OVERRIDES.clear()
    phase4.LEDGER.usd["queries"] = 0.0
    phase4.LEDGER.usd["ingestion"] = 0.0
    phase4.LEDGER.unknown["queries"] = 0
    phase4.LEDGER.unknown["ingestion"] = 0
    admin_ai.AUDIT.clear()
    admin_ai.FAQ_ACTIVE.clear()


def _login(client: TestClient, password: str) -> dict:
    response = client.post("/api/admin/ai/session", json={"password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _auth(issued: dict, csrf: bool = False) -> dict:
    headers = {"Authorization": f"Bearer {issued['token']}"}
    if csrf:
        headers["X-CSRF-Token"] = issued["csrf"]
    return headers


def test_admin_routes_reject_a_missing_role():
    _reset()
    client = TestClient(server.app)
    page = client.get("/admin/ai")
    overview = client.get("/api/admin/ai/overview")
    assert page.status_code == 401
    assert overview.status_code == 401
    issued = _login(client, "viewer-test-pass")
    allowed = client.get("/api/admin/ai/overview", headers=_auth(issued))
    assert allowed.status_code == 200
    editor = _login(client, "editor-test-pass")
    blocked = client.post(
        "/api/admin/ai/settings",
        headers=_auth(editor, csrf=True),
        json={"patch": {"response_ttl_s": 30}, "preview_id": "nope", "confirm": True},
    )
    assert blocked.status_code == 403
    missing_csrf = client.post(
        "/api/admin/ai/sources/dry-run",
        headers=_auth(editor),
        json={"docs": []},
    )
    assert missing_csrf.status_code == 403


def test_secrets_stay_off_the_page_and_out_of_logs():
    _reset()
    records = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Grab()
    logger = logging.getLogger("ur.admin")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        client = TestClient(server.app)
        refused = client.post("/api/admin/ai/session", json={"password": "sk-testvalue"})
        assert refused.status_code == 401
        issued = _login(client, "admin-test-pass")
        page = client.get("/admin/ai", headers=_auth(issued))
        assert page.status_code == 200
        blob = page.text + refused.text + json.dumps(records)
        for secret in ("viewer-test-pass", "editor-test-pass", "admin-test-pass", "sk-testvalue", "phase5-test-secret"):
            assert secret not in blob
        assert "API_KEY" not in page.text
        assert "SESSION_SECRET" not in page.text
        bad = client.post(
            "/api/admin/ai/settings/preview",
            headers=_auth(issued, csrf=True),
            json={"patch": {"api_key": "sk-testvalue"}},
        )
        assert bad.status_code == 400
        assert "sk-testvalue" not in bad.text
        assert "sk-testvalue" not in "\n".join(records)
    finally:
        logger.removeHandler(handler)


def test_settings_validation_preview_and_audit():
    _reset()
    try:
        admin_ai.preview_settings({"response_ttl_s": 99999})
        raise AssertionError("ttl above the cap should fail")
    except AdminError as exc:
        assert exc.code == "range"
    try:
        admin_ai.preview_settings({"llm_api_key": "sk-testvalue"})
        raise AssertionError("secret field should fail")
    except AdminError as exc:
        assert exc.code == "secret"
    try:
        admin_ai.save_settings("viewer", {"response_ttl_s": 30}, "x", True)
        raise AssertionError("viewer must not save")
    except AdminError as exc:
        assert exc.status == 403
    preview = admin_ai.preview_settings({"response_ttl_s": 30, "prices": {"input": None}})
    assert preview["saved"] is False
    assert preview["changes"]["response_ttl_s"]["to"] == 30
    saved = admin_ai.save_settings("admin", {"response_ttl_s": 30, "prices": {"input": None}}, preview["preview_id"], True)
    assert saved["ok"] is True
    assert phase4.OVERRIDES["response_ttl_s"] == 30
    assert phase4.load_prices()["input"] is None
    assert admin_ai.AUDIT[-1]["role"] == "admin"
    assert "sk-" not in json.dumps(admin_ai.AUDIT)
    client = TestClient(server.app)
    editor = _login(client, "editor-test-pass")
    publish = client.post(
        "/api/admin/ai/faq/publish",
        headers=_auth(editor, csrf=True),
        json={"patches": [{"id": "faq-submission-channel", "active": False}], "confirm": True},
    )
    assert publish.status_code == 403
    finally_clear = True
    assert finally_clear
    phase4.OVERRIDES.clear()


def test_overview_matches_a_control_request():
    _reset()
    phase4.note_chat({
        "mode": "faq",
        "cache": "hit",
        "sources": [{"chunk_id": "chunk-1"}],
        "contract": {"status": "answered"},
    }, 12.5)
    report = admin_ai.overview()
    assert report["requests_today"] == 1
    assert report["faq_percent"]["numerator"] == 1
    assert report["faq_percent"]["denominator"] == 1
    assert report["faq_percent"]["of"] == "requests today"
    assert report["faq_percent"]["value"] == 100.0
    assert report["generated_percent"]["numerator"] == 0
    assert report["cache_hit_percent"]["numerator"] == 1
    assert report["cache_hit_percent"]["of"] == "cache lookups today (hit + miss)"
    assert report["latency_p50_ms"] == "not measured"
    assert report["latency_p95_ms"] == "not measured"
    assert report["score_40"] == "not measured"
    assert report["unknown_marker"] == "unknown"
    assert report["usd_today"]["queries"] is None
    assert "input" in report["unknown_prices"]
    quality = admin_ai.quality_report()
    assert quality["score_40"] == "not measured"
    assert "admissions" in quality["schema_topics_without_faq"]


def test_samples_drop_email_and_phone():
    _reset()
    phase4.NOTES.add({
        "created_at": "2026-11-09",
        "path": "template",
        "question": "write me at student@example.com or +48123456789",
        "error_code": "timeout",
        "source_ids": ["chunk-1"],
        "stage_ms": {"total": 10, "parse": "not measured"},
        "prompt_version": "v1",
        "index_revision": "rev",
        "model": "unconfigured",
    })
    rows = admin_ai.list_samples(date="2026-11-09", path="template", error="yes")
    blob = json.dumps(rows)
    assert "student@example.com" not in blob
    assert "+48123456789" not in blob
    assert "@" not in blob
    assert rows[0]["source_ids"] == ["chunk-1"]
    assert rows[0]["path"] == "template"
    assert admin_ai.list_samples(error="no") == []


def test_faq_preview_and_index_dry_run_do_not_invent_facts():
    _reset()
    conflicts = admin_ai.faq_conflicts()
    blob = json.dumps(conflicts)
    assert "3556" not in blob
    overlap_ids = {item for row in conflicts["entry_overlaps"] for item in row["ids"]}
    assert "faq-cap-2025-2026" in overlap_ids
    assert "faq-income-group-2025-2026" in overlap_ids
    root = Path("/tmp/ur-phase5-revisions")
    if root.exists():
        shutil.rmtree(root)
    docs = [{"url": "https://student.uniwersytetradom.pl/a", "text": "one"}]
    preview = admin_ai.dry_run_reindex(docs, root)
    assert preview["published"] is False
    assert not (root / "CURRENT").exists()
    try:
        admin_ai.publish_index("editor", docs, True, root)
        raise AssertionError("editor must not publish")
    except AdminError as exc:
        assert exc.status == 403
    published = admin_ai.publish_index("admin", docs, True, root)
    assert published["published"] is True
    assert admin_ai.AUDIT[-1]["action"] == "index_publish"
    assert admin_ai.AUDIT[-1]["role"] == "admin"
    again = admin_ai.dry_run_reindex(docs, root)
    assert again["already_exists"] is True and again["published"] is False
    os.environ["ADMIN_INDEX_ROOT"] = str(root)
    try:
        client = TestClient(server.app)
        admin = _login(client, "admin-test-pass")
        rolled = client.post(
            "/api/admin/ai/sources/rollback",
            headers=_auth(admin, csrf=True),
            json={"revision": published["revision"], "confirm": True},
        )
        assert rolled.status_code == 200, rolled.text
        assert "admin-test-pass" not in rolled.text
    finally:
        os.environ.pop("ADMIN_INDEX_ROOT", None)
        shutil.rmtree(root, ignore_errors=True)


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
