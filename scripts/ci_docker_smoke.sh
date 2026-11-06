#!/bin/sh
# Runtime check of the image already tagged ur-asystent-ci. No production deploy.
set -eu
PORT=10000
NAME=ur-smoke
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -p "${PORT}:${PORT}" \
  -e PORT="$PORT" \
  -e SCENARIO_SOCIAL=1 \
  -e LLM_PROVIDER= \
  -e SESSION_SECRET=ci-only \
  ur-asystent-ci
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

ready=
i=0
while [ "$i" -lt 40 ]; do
  if curl -fsS "http://127.0.0.1:${PORT}/healthz" -o /tmp/ur-health.json; then
    ready=1
    break
  fi
  i=$((i + 1))
  sleep 3
done
if [ -z "$ready" ]; then
  docker logs "$NAME" 2>&1 | tail -n 40 >&2
  echo "container healthz did not become ready" >&2
  exit 1
fi

docker exec "$NAME" test -f /srv/data/scenarios/social_scholarship.yaml

docker exec -i -e PYTHONPATH=/srv/app "$NAME" python - <<'PY'
import os
import sys
sys.path.insert(0, "/srv/app")
secret = os.environ.get("SESSION_SECRET") or ""
if not secret or secret == "dev-only-change-me":
    raise SystemExit("SESSION_SECRET is unset or the development fallback")
from session import SessionState, encode, decode
token = encode(SessionState(profile={"status": "student"}, conv_id="smoke"))
back = decode(token)
if back is None or back.profile.get("status") != "student":
    raise SystemExit("signed session did not round-trip")
if decode(token[:-8] + "deadbeef") is not None:
    raise SystemExit("tampered session was accepted")
print("session_config_ok")
PY

python3 - <<PY
import json, urllib.request
base = "http://127.0.0.1:${PORT}"
health = json.load(urllib.request.urlopen(base + "/healthz", timeout=30))
if health.get("ok") is not True or not health.get("chunks"):
    raise SystemExit(f"healthz failed: {health!r}")
status = json.load(urllib.request.urlopen(base + "/api/status", timeout=30))
if status.get("scenario_social") is not True or status.get("llm") is not False:
    raise SystemExit(f"status failed: keys={sorted(status)}")
card = json.load(urllib.request.urlopen(base + "/api/scenarios/social-scholarship", timeout=30))
year = (card.get("amounts") or {}).get("academic_year")
if not card.get("title") or year != "2025/2026":
    raise SystemExit(f"card failed: year={year!r}")
print("docker_smoke_ok", "chunks", health.get("chunks"))
PY
