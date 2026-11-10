"""Load and lock the Phase 0 40-case skeleton. Does not score quality."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "tests" / "phase0_cases.yaml"

OWNER_REVIEW = "Kostya Prochan, chat review 2026-11-09"
EXPECTED_STATUS = {"answered", "partial", "clarification", "no_answer"}
CATEGORY_COUNTS = {
    "faq_programs_contacts": 8,
    "deadlines_years_relative": 6,
    "amounts_conditions": 4,
    "cross_language": 4,
    "typos_aliases": 4,
    "ambiguity_faculty": 4,
    "no_answer_ood": 4,
    "conflict_stale": 3,
    "injection": 3,
}
REQUIRED_KEYS = {
    "id",
    "split",
    "category",
    "query",
    "lang",
    "filters",
    "expected_status",
    "expected_document_ids",
    "required_facts",
    "forbidden_facts",
    "reference_date",
    "approved_by",
    "active",
    "version",
    "facts_approved",
    "hard_filter",
    "compound",
}


def load_cases(path: Path | None = None) -> list[dict]:
    raw = yaml.safe_load((path or CASES_PATH).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ValueError("phase0 cases file must be a mapping with a cases list")
    return raw["cases"]


def load_fact_ids() -> set[str]:
    import sys

    app = ROOT / "app"
    if str(app) not in sys.path:
        sys.path.insert(0, str(app))
    from facts import load_facts

    return {fact.id for fact in load_facts()}


def holdout_ids(cases: list[dict] | None = None) -> set[str]:
    rows = cases if cases is not None else load_cases()
    return {row["id"] for row in rows if row.get("split") == "holdout"}


def assert_allowed_for_tuning(case_ids, cases: list[dict] | None = None) -> None:
    """Holdout ids are locked. Threshold tuning must not see them."""
    locked = holdout_ids(cases)
    bad = [item for item in case_ids if item in locked]
    if bad:
        raise RuntimeError(
            "holdout cases are locked and cannot be used for threshold tuning: "
            + ", ".join(bad)
        )


def score_label(cases: list[dict] | None = None) -> str:
    """Phase 1 records the owner review and still does not score 0–4.

    A signed case is not a pass. Live scoring stays in a later phase.
    """
    del cases
    return "not measured"


def validate(cases: list[dict] | None = None, fact_ids: set[str] | None = None) -> None:
    rows = cases if cases is not None else load_cases()
    ids = fact_ids if fact_ids is not None else load_fact_ids()
    if len(rows) != 40:
        raise ValueError(f"expected 40 cases, found {len(rows)}")
    seen = set()
    counts = {key: 0 for key in CATEGORY_COUNTS}
    dev = holdout = hard = compound = 0
    for row in rows:
        missing = REQUIRED_KEYS - set(row)
        if missing:
            raise ValueError(f"{row.get('id')}: missing {sorted(missing)}")
        if row["id"] in seen:
            raise ValueError(f"duplicate id {row['id']}")
        seen.add(row["id"])
        if row["split"] not in ("dev", "holdout"):
            raise ValueError(f"{row['id']}: bad split")
        if row["split"] == "dev":
            dev += 1
        else:
            holdout += 1
            if not str(row["id"]).startswith("p0-holdout-"):
                raise ValueError(f"{row['id']}: holdout id must start with p0-holdout-")
        if row["category"] not in counts:
            raise ValueError(f"{row['id']}: unknown category")
        counts[row["category"]] += 1
        if row["expected_status"] not in EXPECTED_STATUS:
            raise ValueError(f"{row['id']}: bad expected_status")
        if not isinstance(row["query"], str) or not (1 <= len(row["query"]) <= 1000):
            raise ValueError(f"{row['id']}: query length")
        if row["approved_by"] != OWNER_REVIEW:
            raise ValueError(f"{row['id']}: approved_by is not the 2026-11-09 owner review")
        if "UNCONFIRMED" in row["required_facts"] and row["facts_approved"] is not False:
            raise ValueError(f"{row['id']}: UNCONFIRMED facts cannot be marked approved")
        if row["facts_approved"] not in (True, False):
            raise ValueError(f"{row['id']}: facts_approved")
        if row["active"] is not True or row["version"] != 1:
            raise ValueError(f"{row['id']}: active/version")
        if row["expected_document_ids"] != []:
            raise ValueError(f"{row['id']}: document ids are unknown")
        for fact in row["required_facts"]:
            if fact != "UNCONFIRMED" and fact not in ids:
                raise ValueError(f"{row['id']}: required fact {fact} is not in facts.yaml")
        if not row["required_facts"]:
            raise ValueError(f"{row['id']}: required_facts empty")
        date = str(row["reference_date"])
        if len(date) != 10:
            raise ValueError(f"{row['id']}: reference_date")
        if row["hard_filter"]:
            hard += 1
        if row["compound"]:
            compound += 1
        filters = row["filters"] or {}
        if row["hard_filter"]:
            marked = any(
                filters.get(key) not in (None, "", [])
                for key in ("faculty_id", "program_id", "academic_year", "source_lang", "as_of")
            )
            if not marked:
                raise ValueError(f"{row['id']}: hard_filter needs an explicit filter")
    if dev != 30 or holdout != 10:
        raise ValueError(f"split is {dev} dev / {holdout} holdout")
    for name, want in CATEGORY_COUNTS.items():
        if counts[name] != want:
            raise ValueError(f"{name}: {counts[name]} != {want}")
    if hard < 4:
        raise ValueError(f"hard_filter cases {hard} < 4")
    if compound < 2:
        raise ValueError(f"compound cases {compound} < 2")
    if score_label(rows) != "not measured":
        raise ValueError("40-case score must stay not measured until a later phase")
