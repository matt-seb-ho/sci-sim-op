#!/usr/bin/env bash
# Run the pi coding agent on FORGE-v0 inside a bubblewrap sandbox.
#
#   scripts/geomodel/run_pi_agent.sh --run-id ID [--site DIR] [--seed N]
#       [--prompt FILE] [--spec FILE] [--hours 3] [--cap-usd 3]
#   scripts/geomodel/run_pi_agent.sh --shell ID -- CMD...   # same sandbox, run CMD instead of pi
#
# Isolation (verify with scripts/geomodel/verify_sandbox.sh):
#   - bwrap --unshare-all: own network namespace (loopback only), pid, ipc, uts, user.
#   - Visible: /usr (+ /bin,/lib symlinks), a few /etc files, /opt/{py,node,pi} (read-only
#     toolchain), /site (read-only), /task (read-only: output spec), /work (rw output),
#     /home/agent (rw; pi config + session). Nothing else from the host: no repo, no
#     /data/.../raw, no real $HOME.
#   - The only way out is /run/llm/llm.sock -> scripts/geomodel/llm_gate.py on the host,
#     which forwards POST chat/completions for one model to OpenRouter, injects the key
#     (the key never enters the sandbox), strips web plugins and enforces the $ cap.
# Outputs: $RUNS/<id>/{work/, pi_events.jsonl, session/, gate_usage.jsonl, meta.json, stderr.log}
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GEO=/data/matt/sci-sim-op/geomodel
SB=$GEO/sandbox
RUNS=$GEO/forge/runs
MODEL=xiaomi/mimo-v2.6-flash
SITE=$GEO/forge/site_v0A
PROMPT=$REPO/docs/geomodel/FORGE_v0_AGENT_PROMPT.md
SPEC=$REPO/docs/geomodel/FORGE_v0_OUTPUT_SPEC.md
HOURS=3
CAP=3
SEED=""
RUN_ID=""
SHELL_MODE=0
THINKING=medium

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id) RUN_ID=$2; shift 2;;
    --site) SITE=$2; shift 2;;
    --seed) SEED=$2; shift 2;;
    --prompt) PROMPT=$2; shift 2;;
    --spec) SPEC=$2; shift 2;;
    --hours) HOURS=$2; shift 2;;
    --cap-usd) CAP=$2; shift 2;;
    --thinking) THINKING=$2; shift 2;;
    --shell) SHELL_MODE=1; RUN_ID=$2; shift 2;;
    --) shift; break;;
    *) echo "unknown arg $1" >&2; exit 2;;
  esac
done
[[ -n "$RUN_ID" ]] || { echo "--run-id required" >&2; exit 2; }

PYHOME=$(ls -d "$SB"/pyhome/cpython-3.12.*-linux-x86_64-gnu | head -1)
RUN=$RUNS/$RUN_ID
[[ $SHELL_MODE == 1 ]] && RUN=$SB/shell_runs/$RUN_ID
if [[ $SHELL_MODE == 0 && -e $RUN ]]; then echo "run dir exists: $RUN" >&2; exit 2; fi
mkdir -p "$RUN"/{work,home/.pi/agent,etc,sock,task}
if [[ -f $SPEC ]]; then cp "$SPEC" "$RUN/task/FORGE_v0_OUTPUT_SPEC.md"; elif [[ $SHELL_MODE == 0 ]]; then echo "missing spec $SPEC" >&2; exit 2; fi

# Minimal /etc for the sandbox.
printf 'agent:x:1000:1000:agent:/home/agent:/bin/bash\n' > "$RUN/etc/passwd"
printf 'agent:x:1000:\n' > "$RUN/etc/group"
printf '127.0.0.1 localhost\n' > "$RUN/etc/hosts"
: > "$RUN/etc/resolv.conf"

# pi config: the built-in openrouter provider, pointed at the in-sandbox relay.
cat > "$RUN/home/.pi/agent/models.json" <<'EOF'
{"providers": {"openrouter": {"baseUrl": "http://127.0.0.1:8080/api/v1", "apiKey": "no-key-in-sandbox"}}}
EOF
cat > "$RUN/home/.pi/agent/settings.json" <<EOF
{"defaultProvider": "openrouter", "defaultModel": "$MODEL", "defaultThinkingLevel": "$THINKING",
 "defaultProjectTrust": "never", "enableInstallTelemetry": false, "quietStartup": true,
 "retry": {"enabled": true, "maxRetries": 5}}
EOF

# Start the host-side gate (reads the key from .env; never echoed).
GATE_LOG=$RUN/gate_usage.jsonl
SOCK=$RUN/sock/llm.sock
(
  set -a; . "$REPO/.env"; set +a
  unset NOUS_API_KEY VENICE_API_KEY
  exec python3 "$REPO/scripts/geomodel/llm_gate.py" --socket "$SOCK" --model "$MODEL" \
       --cap-usd "$CAP" --log "$GATE_LOG" ${SEED:+--seed "$SEED"}
) 2>>"$RUN/gate.stderr" &
GATE_PID=$!
trap 'kill $GATE_PID 2>/dev/null || true' EXIT
for _ in $(seq 50); do [[ -S $SOCK ]] && break; sleep 0.1; done
[[ -S $SOCK ]] || { echo "gate did not start" >&2; cat "$RUN/gate.stderr" >&2; exit 1; }

BWRAP=(bwrap --unshare-all --die-with-parent --new-session --hostname sandbox
  --ro-bind /usr /usr
  --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/sbin /sbin
  --ro-bind /etc/ld.so.cache /etc/ld.so.cache --ro-bind /etc/ld.so.conf /etc/ld.so.conf
  --ro-bind /etc/ld.so.conf.d /etc/ld.so.conf.d --ro-bind /etc/alternatives /etc/alternatives
  --ro-bind /etc/fonts /etc/fonts --ro-bind-try /etc/localtime /etc/localtime
  --ro-bind "$RUN/etc/passwd" /etc/passwd --ro-bind "$RUN/etc/group" /etc/group
  --ro-bind "$RUN/etc/hosts" /etc/hosts --ro-bind "$RUN/etc/resolv.conf" /etc/resolv.conf
  --proc /proc --dev /dev --tmpfs /tmp
  --ro-bind "$PYHOME" /opt/py --ro-bind "$SB/node" /opt/node --ro-bind "$SB/pi" /opt/pi
  --ro-bind "$REPO/scripts/geomodel/sandbox_relay.py" /opt/relay.py
  --ro-bind "$SITE" /site --ro-bind "$RUN/task" /task
  --bind "$RUN/work" /work --bind "$RUN/home" /home/agent
  --ro-bind "$RUN/sock" /run/llm
  --uid 1000 --gid 1000 --chdir /work --clearenv
  --setenv HOME /home/agent --setenv USER agent --setenv LANG C.UTF-8 --setenv TERM dumb
  --setenv PATH /opt/py/bin:/opt/node/bin:/opt/pi/bin:/usr/bin:/bin
  --setenv MPLBACKEND Agg --setenv PI_OFFLINE 1 --setenv PI_TELEMETRY 0 --setenv TMPDIR /tmp
)
START_RELAY='python3 /opt/relay.py 8080 /run/llm/llm.sock & for i in $(seq 50); do (exec 3<>/dev/tcp/127.0.0.1/8080) 2>/dev/null && break; sleep 0.1; done;'

if [[ $SHELL_MODE == 1 ]]; then
  "${BWRAP[@]}" bash -c "$START_RELAY"' exec "$@"' _ "$@"
  exit $?
fi

PROMPT_TEXT=$(cat "$PROMPT")
cat > "$RUN/meta.json" <<EOF
{"run_id": "$RUN_ID", "model": "$MODEL", "thinking": "$THINKING", "seed": "${SEED}", "site": "$SITE",
 "prompt_file": "$PROMPT", "prompt_sha256": "$(sha256sum "$PROMPT" | cut -c1-16)",
 "spec_sha256": "$(sha256sum "$SPEC" | cut -c1-16)", "hours": $HOURS, "cap_usd": $CAP,
 "pi_version": "$("$SB/node/bin/node" "$SB/pi/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js" --version 2>/dev/null || echo ?)",
 "started": "$(date -Is)"}
EOF
set +e
timeout --signal=TERM --kill-after=60 "${HOURS}h" "${BWRAP[@]}" bash -c "$START_RELAY"' exec pi --mode json --offline -na \
    --model "openrouter/'"$MODEL"'" --tools read,bash,edit,write,grep,find,ls \
    --session-dir /home/agent/sessions "$1"' _ "$PROMPT_TEXT" \
  > "$RUN/pi_events.jsonl" 2> "$RUN/stderr.log"
RC=$?
set -e
python3 - "$RUN" "$RC" <<'EOF'
import json, sys, pathlib
run, rc = pathlib.Path(sys.argv[1]), int(sys.argv[2])
m = json.loads((run / "meta.json").read_text())
m["exit_code"] = rc
m["timed_out"] = rc == 124
spent = 0.0; n = 0
if (run / "gate_usage.jsonl").exists():
    for line in (run / "gate_usage.jsonl").read_text().splitlines():
        r = json.loads(line); n += 1; spent = max(spent, r.get("spent") or 0.0)
m["gate_requests"] = n
m["gate_spent_usd"] = round(spent, 4)
import datetime; m["finished"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
(run / "meta.json").write_text(json.dumps(m, indent=1))
print(json.dumps({k: m[k] for k in ("run_id", "exit_code", "timed_out", "gate_requests", "gate_spent_usd")}))
EOF
cp -r "$RUN/home/sessions" "$RUN/session" 2>/dev/null || true
exit 0
