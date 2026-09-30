#!/usr/bin/env bash
# Verify the FORGE-v0 agent sandbox. Each check prints PASS/FAIL; the log is the evidence.
#   scripts/geomodel/verify_sandbox.sh [LOGFILE]
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG=${1:-/data/matt/sci-sim-op/geomodel/sandbox/verify_$(date +%Y%m%dT%H%M%S).log}
ID=verify_$(date +%s)
RUNNER="$REPO/scripts/geomodel/run_pi_agent.sh"

INSIDE=$(cat <<'EOF'
pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; }
chk() { local name=$1; shift; if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi; }
nchk() { local name=$1; shift; if "$@" >/dev/null 2>&1; then fail "$name"; else pass "$name"; fi; }

echo "== network (must fail)"
nchk "curl https://gdr.openei.org fails"      curl -sS -m 10 https://gdr.openei.org
nchk "curl https://www.google.com fails"      curl -sS -m 10 https://www.google.com
nchk "curl http://1.1.1.1 (no DNS) fails"     curl -sS -m 10 http://1.1.1.1
nchk "curl https://openrouter.ai direct fails" curl -sS -m 10 https://openrouter.ai/api/v1/models
nchk "python urllib to pypi fails"            python3 -c "import urllib.request;urllib.request.urlopen('https://pypi.org',timeout=10)"
nchk "pip install fails"                      timeout 60 python3 -m pip install --no-cache-dir requests-toolbelt
echo "   interfaces: $(ls /sys/class/net 2>/dev/null | tr '\n' ' ')"

echo "== model gate"
R=$(curl -sS -m 120 http://127.0.0.1:8080/api/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"xiaomi/mimo-v2.6-flash","messages":[{"role":"user","content":"Reply with the single word: pong"}],"max_tokens":400}')
echo "$R" | grep -qi pong && pass "model API works via gate" || fail "model API works via gate: ${R:0:300}"
R=$(curl -sS -m 30 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"openai/gpt-4o-mini:online","messages":[{"role":"user","content":"hi"}]}')
[[ $R == 403 ]] && pass "other model refused (403)" || fail "other model refused: $R"
R=$(curl -sS -m 30 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/v1/key)
[[ $R == 403 ]] && pass "GET /key refused (403)" || fail "GET /key refused: $R"
R=$(curl -sS -m 30 -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8080/api/v1/responses -d '{}')
[[ $R == 403 ]] && pass "other endpoint refused (403)" || fail "other endpoint refused: $R"
env | grep -qi 'OPENROUTER_API_KEY\|sk-or-' && fail "no API key in env" || pass "no API key in env"
grep -rqs 'sk-or-' /home/agent /work /task /etc 2>/dev/null && fail "no API key in visible files" || pass "no API key in visible files"

echo "== host visibility (must be invisible)"
nchk "/data absent"            ls /data
nchk "/home/matt absent"       ls /home/matt
nchk "repo absent"             ls /home/matt/projects/sci-sim-op
nchk "/root absent"            ls /root
nchk "/mnt absent"             ls /mnt
nchk "/srv absent"             ls /srv
nchk "no .git under /site"     test -n "$(find /site -name .git -print -quit)"
nchk "no manifest under /site" test -n "$(find /site -iname 'manifest*' -print -quit)"
nchk "no meta/ under /site"    test -d /site/meta
echo "   / contains: $(ls / | tr '\n' ' ')"
echo "   host pids visible: $(ls /proc | grep -c '^[0-9]')"
echo "== mounts"
nchk "/site read-only"         touch /site/_w
chk  "/work writable"          touch /work/_w
rm -f /work/_w
nchk "/usr read-only"          touch /usr/_w
nchk "/opt/py read-only"       touch /opt/py/_w
echo "== tools"
for m in numpy scipy pandas openpyxl lasio dlisio shapely pyproj matplotlib pyvista; do
  chk "python import $m" python3 -c "import $m"
done
chk "pdftotext" which pdftotext
chk "unzip" which unzip
chk "pi" which pi
EOF
)

{
  echo "# sandbox verification $(date -Is) run=$ID"
  "$RUNNER" --shell "$ID" -- bash -c "$INSIDE" 2>&1
} 2>&1 | tee "$LOG"
echo "gate log:"; cat /data/matt/sci-sim-op/geomodel/sandbox/shell_runs/$ID/gate_usage.jsonl 2>/dev/null | tee -a "$LOG"
echo "log: $LOG"
