## Summary
<!-- What / why (1–3 bullets). -->

## Redesign checklist
- [ ] No new answer-mutating regex in `app/rag.py` (figures via `app/render.py` + FACTS)
- [ ] Output language stays in `{pl, en, uk}`; Russian input → Ukrainian
- [ ] Unit green: `python tests/eval_dialogues.py --repo . --layer unit`
- [ ] If touching answer path / facts / corpus: critical e2e subset (`e2e_pr: true`) considered

## Test plan
- [ ] …
