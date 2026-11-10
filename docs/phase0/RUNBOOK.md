# Local runbook

This is how to start the current Python app, move a file-index revision, and react to a provider outage. It is not a launch approval and it does not deploy anything.

## Start locally

From the repo root, with no provider key:

```sh
cd app
EVAL_REAL=0 LLM_PROVIDER=fake PORT=10000 uvicorn server:app --host 0.0.0.0 --port 10000
```

`GET /healthz` should return `ok`. Leave `EVAL_REAL=0`. Do not put API keys in the page or in git.

## Update the index

Publish and rollback use the Phase 1 revision directory. A dry-run only reports the revision id. Publish writes that directory and the `CURRENT` pointer after confirmation in `/admin/ai`. It does not crawl the web. It does not replace the running `data/index.npz`. The server keeps reading that shipped file until a separate, explicit copy is made into a directory you choose.

## Provider outage

A timeout, a refusal, or an unreachable provider returns the existing verified fallback. The answer path does not make a second repair call. After 5 provider errors in 30 seconds, generation pauses for 60 seconds and the same fallback is served. If the evidence for that answer does not contain an amount, the fallback must not invent one.

## Roll back

An admin confirms rollback to an existing revision id. That moves `CURRENT` back to the previous revision. It still does not silently replace `data/index.npz`.
