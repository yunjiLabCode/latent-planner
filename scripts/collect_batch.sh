#!/usr/bin/env bash
# batch01 — 10 LIBERO-PRO episodes on shared vLLM + pi0.5/SAM3.
#
# Launch inside tmux session batch01. This script does not create that
# session and does not start itself.
#
#   tmux new-session -s batch01
#   ROOT=/data/yunji/latent-planner-work bash scripts/collect_batch.sh
#
# Log: $ROOT/logs/batch01.log (printed again after startup).
#
# Suites in AgenticRoboRL/harnesses/rpent_libero/tasks.jsonl (8 x 10 tasks):
#   libero_spatial_task, libero_spatial_swap,
#   libero_object_task, libero_object_swap,
#   libero_goal_task, libero_goal_swap,
#   libero_10_task, libero_10_swap.
#
# Excluded: both libero_spatial suites. The stage-5 smoke already collected
# libero_spatial_task task 0 init 11, and this batch was asked to leave
# spatial out.
#
# Chosen 4, preferring goal, object, and long (libero_10):
#   libero_goal_task, libero_object_task, libero_10_task, libero_goal_swap.
# The first three are the *_task suite of each preferred family. The fourth
# is the goal swap, so one preferred family is collected in both layouts.
# Init is 11 only: the first training init (11-44). Eval inits 1-10 are not used.
# Tasks are the first entries of each suite in tasks.jsonl, 2 or 3 per suite.
#
#   libero_goal_task    tasks 0, 1, 2   init 11
#   libero_object_task  tasks 0, 1      init 11
#   libero_10_task      tasks 0, 1, 2   init 11
#   libero_goal_swap    tasks 0, 1      init 11
#   10 episodes.
#
# Do not put CUDA_VISIBLE_DEVICES in env.sh. This script sets it per process:
# vLLM on 0,1; pi0.5, SAM3, and each env server on 2. GPU 3 is never used.
set -euo pipefail

ROOT="${ROOT:-/data/yunji/latent-planner-work}"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

LOG="$ROOT/logs/batch01.log"
RUNLOG="$ROOT/logs/batch01"
STATE="$RUNLOG/state"
N_WORKERS=4
MODEL_PORT="${MODEL_PORT:-18100}"
VLA_PORT="${VLA_PORT:-18300}"
SAM3_PORT="${SAM3_PORT:-18400}"
VLLM_READY_S=1800
SERVICE_READY_S=900
GPU_LOG_S=60

reject_gpu3() {
    local cvd="${CUDA_VISIBLE_DEVICES:-}"
    local dev trimmed=""
    if [[ -z "${cvd//[[:space:]]/}" ]]; then
        echo "CUDA_VISIBLE_DEVICES is empty; refusing to start" >&2
        exit 1
    fi
    local IFS=','
    for dev in $cvd; do
        dev="${dev//[[:space:]]/}"
        trimmed+="${trimmed:+,}${dev}"
        if [[ "$dev" == "3" ]]; then
            echo "CUDA_VISIBLE_DEVICES=${cvd} contains 3; refusing GPU 3" >&2
            exit 1
        fi
    done
    CUDA_VISIBLE_DEVICES="$trimmed"
}

require_var() {
    local name=$1
    if [[ -z "${!name:-}" ]]; then
        echo "$name is unset after sourcing $ROOT/env.sh" >&2
        exit 1
    fi
}

reject_gpu3
if [[ ! -f "$ROOT/env.sh" ]]; then
    echo "missing $ROOT/env.sh" >&2
    exit 1
fi
set +u
# shellcheck disable=SC1091
source "$ROOT/env.sh"
set -u
reject_gpu3

require_var RPENT_DIR
require_var RPENT_ENV
require_var PLANNER_ENV
require_var PI05_CHECKPOINT
require_var SAM3_CHECKPOINT
require_var PLANNER_WEIGHTS
if [[ ! -f "$REPO_ROOT/src/trace/converter.py" ]]; then
    echo "missing $REPO_ROOT/src/trace/converter.py" >&2
    exit 1
fi
if [[ ! -x "$PLANNER_ENV/bin/vllm" ]]; then
    echo "missing $PLANNER_ENV/bin/vllm" >&2
    exit 1
fi
if [[ ! -x "$RPENT_ENV/bin/python" ]]; then
    echo "missing $RPENT_ENV/bin/python" >&2
    exit 1
fi
need_cmd() {
    command -v "$1" >/dev/null || {
        echo "missing command: $1" >&2
        exit 1
    }
}
need_cmd setsid
need_cmd flock
need_cmd nvidia-smi

mkdir -p "$RUNLOG/episodes" "$STATE/running"
: >"$STATE/completed"
rm -f "$STATE/abort" "$STATE/stop"
QUEUE="$STATE/queue"
cat >"$QUEUE" <<'EOF'
libero_goal_task 0 11
libero_goal_task 1 11
libero_goal_task 2 11
libero_object_task 0 11
libero_object_task 1 11
libero_10_task 0 11
libero_10_task 1 11
libero_10_task 2 11
libero_goal_swap 0 11
libero_goal_swap 1 11
EOF

mkdir -p "$(dirname "$LOG")"
echo "log: $LOG"
exec > >(tee -a "$LOG") 2>&1
echo "log: $LOG"
echo "batch01 root: $ROOT"
echo "episodes: 10  workers: $N_WORKERS  gpus: vLLM=0,1 pi05/sam3/env=2"

declare -a SERVER_PIDS=()
declare -a WORKER_PIDS=()
MONITOR_PID=""

kill_rpents() {
    local f pid restore
    restore=$(shopt -p nullglob)
    shopt -s nullglob
    for f in "$STATE/running"/*.rpent; do
        pid=$(<"$f")
        kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    done
    eval "$restore"
}

stop_servers() {
    local pid
    kill_rpents
    for pid in "${SERVER_PIDS[@]:-}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    sleep 2
    kill_rpents
    for pid in "${SERVER_PIDS[@]:-}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
        fi
    done
}

on_signal() {
    echo "signal: stopping workers and servers" >&2
    echo 1 >"$STATE/abort"
    echo 1 >"$STATE/stop"
    kill_rpents
    local pid
    for pid in "${WORKER_PIDS[@]:-}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    if [[ -n "$MONITOR_PID" ]]; then
        kill -TERM "$MONITOR_PID" 2>/dev/null || true
    fi
    exit 130
}
trap on_signal INT TERM
trap stop_servers EXIT

port_free() {
    "$RPENT_ENV/bin/python" - "$1" <<'PY'
import socket, sys
s = socket.socket()
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

for port in "$MODEL_PORT" "$VLA_PORT" "$SAM3_PORT"; do
    if ! port_free "$port"; then
        echo "port $port is already in use" >&2
        exit 1
    fi
done

episode_dir() {
    local suite=$1 task=$2 init=$3 attempt=$4
    printf '%s/outputs/batch01/%s/task_%02d/seed_%03d/attempt_%02d' \
        "$ROOT" "$suite" "$task" "$init" "$attempt"
}

for spec in "libero_goal_task 0" "libero_goal_task 1" "libero_goal_task 2" \
            "libero_object_task 0" "libero_object_task 1" \
            "libero_10_task 0" "libero_10_task 1" "libero_10_task 2" \
            "libero_goal_swap 0" "libero_goal_swap 1"; do
    # shellcheck disable=SC2086
    set -- $spec
    for attempt in 0 1; do
        out=$(episode_dir "$1" "$2" 11 "$attempt")
        if [[ -e "$out" ]]; then
            echo "refusing to reuse existing $out" >&2
            exit 1
        fi
    done
done

start_server() {
    local name=$1
    shift
    local log="$RUNLOG/${name}.log"
    echo "starting $name -> $log"
    setsid "$@" >>"$log" 2>&1 &
    local pid=$!
    SERVER_PIDS+=("$pid")
    echo "$pid" >"$RUNLOG/${name}.pid"
    echo "started $name pid=$pid"
}

wait_url() {
    local name=$1 url=$2 timeout=$3 kind=$4 pid=$5
    local deadline=$((SECONDS + timeout))
    while (( SECONDS < deadline )); do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "$name exited while starting (log: $RUNLOG/${name}.log)" >&2
            return 1
        fi
        if "$RPENT_ENV/bin/python" - "$kind" "$url" <<'PY'
import json, sys, urllib.request
kind, url = sys.argv[1], sys.argv[2]
try:
    if kind == "get":
        with urllib.request.urlopen(url, timeout=5) as r:
            sys.exit(0 if r.status < 500 else 1)
    body = json.dumps({"method": "healthz", "args": [], "kwargs": {}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        payload = json.loads(r.read().decode())
    ok = payload.get("ok") and isinstance(payload.get("result"), dict) and payload["result"].get("status") == "ok"
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
PY
        then
            echo "$name ready ($url)"
            return 0
        fi
        sleep 2
    done
    echo "$name not ready after ${timeout}s ($url)" >&2
    return 1
}

# Stage-4 vLLM: TP=2, dtype half, gpu-memory-utilization 0.85,
# max-model-len 262144, prefix caching, qwen3_coder + qwen3.
# The image limit, auto tool choice, and max-num-seqs match harness.yaml
# serve_cmd so the eval.cmd tool calls still work. GPUs 0 and 1 only.
start_server vllm \
    env CUDA_VISIBLE_DEVICES=0,1 \
    "$PLANNER_ENV/bin/vllm" serve "$PLANNER_WEIGHTS" \
    --served-model-name "$PLANNER_WEIGHTS" \
    --host 127.0.0.1 --port "$MODEL_PORT" \
    --tensor-parallel-size 2 \
    --dtype half \
    --max-model-len 262144 \
    --max-num-seqs 4 \
    --gpu-memory-utilization 0.85 \
    --limit-mm-per-prompt.video 0 \
    --limit-mm-per-prompt.image 128 \
    --enable-prefix-caching \
    --enable-auto-tool-choice \
    --generation-config auto \
    --tool-call-parser qwen3_coder \
    --reasoning-parser qwen3

# pi0.5 checkpoint is bf16. No fp16 wrapper. No --parent-watch.
start_server pi05 \
    env CUDA_VISIBLE_DEVICES=2 PI05_CHECKPOINT_PATH="$PI05_CHECKPOINT" \
    "$RPENT_ENV/bin/python" -m rpent.robots.components.pi05_vla_server \
    --transport http --host 127.0.0.1 --port "$VLA_PORT" --cuda-device 2

start_server sam3 \
    env CUDA_VISIBLE_DEVICES=2 SAM3_CHECKPOINT_PATH="$SAM3_CHECKPOINT" \
    "$RPENT_ENV/bin/python" -m rpent.robots.components.sam3_server \
    --transport http --host 127.0.0.1 --port "$SAM3_PORT" --cuda-device 2

wait_url vllm "http://127.0.0.1:${MODEL_PORT}/v1/models" "$VLLM_READY_S" get "${SERVER_PIDS[0]}"
wait_url pi05 "http://127.0.0.1:${VLA_PORT}/call" "$SERVICE_READY_S" rpc "${SERVER_PIDS[1]}"
wait_url sam3 "http://127.0.0.1:${SAM3_PORT}/call" "$SERVICE_READY_S" rpc "${SERVER_PIDS[2]}"

servers_alive() {
    local pid
    for pid in "${SERVER_PIDS[@]}"; do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 1
        fi
    done
}

log_gpu() {
    local gpu running completed
    if ! gpu=$(nvidia-smi --query-gpu=index,memory.used --format=csv,noheader -i 0,1,2 2>&1); then
        gpu="nvidia-smi failed: ${gpu}"
    fi
    gpu=${gpu//$'\n'/'; '}
    running=$(find "$STATE/running" -name '*.rpent' -type f 2>/dev/null | wc -l | tr -d ' ')
    if [[ -f "$STATE/completed" ]]; then
        completed=$(wc -l <"$STATE/completed" | tr -d ' ')
    else
        completed=0
    fi
    echo "[$(date -Is)] gpu=${gpu} running=${running} completed=${completed}"
}

monitor() {
    while [[ ! -f "$STATE/stop" ]]; do
        log_gpu || true
        sleep "$GPU_LOG_S" || true
    done
}
monitor &
MONITOR_PID=$!

# Matches AgenticRoboRL/rl/adapters/rpent_libero.py classify_failure.
# Exit 0: infrastructure (retry once). Exit 1: agent, task, or context overflow (keep).
is_infra() {
    local dir=$1 rc=$2
    "$RPENT_ENV/bin/python" - "$dir" "$rc" <<'PY'
import json, re, sys
from pathlib import Path

directory = Path(sys.argv[1])
rc = int(sys.argv[2])
infra = (
    "connection refused", "connection error", "connection reset", "apiconnectionerror",
    "server disconnected", "remote end closed", "read timeout", "readtimeout",
    "temporarily unavailable", "service unavailable", "bad gateway",
    "internal server error", "cuda", "out of memory", "no such device", "env server",
    "environment server", "failed to start", "address already in use", "broken pipe",
    "killed", "mujoco", "egl",
)
status = re.compile(r"(?<!\d)(?:502|503|504)(?!\d)")
overflow = (
    "maximum context length", "context length is", "context window",
    "context_length_exceeded", "prompt is too long", "too many tokens",
)

def infra_text(text: str) -> bool:
    low = text.lower()
    if any(p in low for p in overflow):
        return False
    return any(p in low for p in infra) or status.search(low) is not None

transcripts = sorted(directory.glob("transcript_*.json"))
if not transcripts:
    # No transcript: the episode never produced a verdict. Same class as
    # rpent_libero.read_verdict on a missing file (server disconnect, OOM,
    # MuJoCo/EGL crash, killed process).
    sys.exit(0)

try:
    rec = json.loads(transcripts[-1].read_text(encoding="utf-8"))
    if not isinstance(rec, dict) or "solved" not in rec:
        sys.exit(0)
except (OSError, ValueError):
    sys.exit(0)

err = rec.get("agent_error")
if not err:
    sys.exit(1)
text = str(err)
low = text.lower()
if any(p in low for p in overflow):
    sys.exit(1)
if infra_text(text) or rc in (9, 134, 137, 139):
    sys.exit(0)
sys.exit(1)
PY
}

convert_attempt() {
    local dir=$1 suite=$2 task=$3 init=$4 attempt=$5
    local eid
    eid=$(printf '%s_t%02d_seed%03d_attempt%02d' "$suite" "$task" "$init" "$attempt")
    if ! PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}" \
        "$RPENT_ENV/bin/python" - "$dir" "$ROOT/outputs/batch01/traces" batch01 "$eid" <<'PY'
import sys
from pathlib import Path
from trace.converter import convert_episode
out = convert_episode(Path(sys.argv[1]), Path(sys.argv[2]), run_id=sys.argv[3], episode_id=sys.argv[4])
print(out)
PY
    then
        echo "converter failed for $dir (schema v0.2.1)" >&2
        return 1
    fi
}

run_rpent() {
    local suite=$1 task=$2 init=$3 attempt=$4 out=$5 elog=$6
    # Own session so a stop can kill rpent and the env server it spawns.
    # No --env-endpoint: rpent starts that env server. MUJOCO_EGL_DEVICE_ID=2
    # is inherited; --cuda-device 2 makes the env server clear
    # CUDA_VISIBLE_DEVICES and keep the EGL pin. VLA and SAM3 stay shared.
    (
        cd "$RPENT_DIR"
        setsid env \
            CUDA_VISIBLE_DEVICES=2 \
            MUJOCO_EGL_DEVICE_ID=2 \
            MUJOCO_GL=egl \
            PYOPENGL_PLATFORM=egl \
            OPENAI_API_KEY=EMPTY \
            "$RPENT_ENV/bin/python" -m rpent.cli.main \
            --robot libero \
            --libero-type pro \
            --suite "$suite" \
            --task "$task" \
            --seed "$init" \
            --output-dir "$out" \
            --cuda-device 2 \
            --base-url "http://127.0.0.1:${MODEL_PORT}/v1" \
            --vla-endpoint "http://127.0.0.1:${VLA_PORT}" \
            --sam3-endpoint "http://127.0.0.1:${SAM3_PORT}" \
            --planner api \
            --model "openai-chat:${PLANNER_WEIGHTS}" \
            --knowledge-profile proven \
            --no-send-back-thinking \
            --reasoning-effort low \
            --max-turns 100 \
            --max-tokens 32768 \
            --planner-timeout-s 7200 \
            --temperature 1.0 \
            --top-p 0.95 \
            --top-k 20 \
            --presence-penalty 1.5 \
            --generation-seed 3407 \
            >"$elog" 2>&1 &
        rpid=$!
        pf="$STATE/running/${rpid}.rpent"
        echo "$rpid" >"$pf"
        set +e
        wait "$rpid"
        rc=$?
        set -e
        rm -f "$pf"
        exit "$rc"
    )
}

convert_if_ready() {
    local dir=$1
    if [[ ! -f "$dir/states.json" ]] || ! compgen -G "$dir/transcript_*.json" >/dev/null; then
        echo "converter skipped (no states.json or transcript): $dir"
        return 0
    fi
    convert_attempt "$@" || true
}

run_attempt() {
    local suite=$1 task=$2 init=$3 attempt=$4
    local out elog rc
    out=$(episode_dir "$suite" "$task" "$init" "$attempt")
    elog=$(printf '%s/episodes/%s_t%02d_s%03d_a%02d.log' "$RUNLOG" "$suite" "$task" "$init" "$attempt")
    mkdir -p "$(dirname "$out")" "$(dirname "$elog")"
    echo "start $suite task=$task init=$init attempt=$attempt -> $out"
    set +e
    run_rpent "$suite" "$task" "$init" "$attempt" "$out" "$elog"
    rc=$?
    set -e
    echo "finish $suite task=$task init=$init attempt=$attempt rc=$rc"
    if [[ -f "$STATE/abort" ]]; then
        return 1
    fi
    if is_infra "$out" "$rc"; then
        echo "infra $out rc=$rc"
        convert_if_ready "$out" "$suite" "$task" "$init" "$attempt"
        return 2
    fi
    convert_if_ready "$out" "$suite" "$task" "$init" "$attempt"
    return 0
}

run_episode() {
    local suite=$1 task=$2 init=$3 status
    if [[ -f "$STATE/abort" ]]; then
        return 1
    fi
    if ! servers_alive; then
        echo "shared server died; aborting" >&2
        echo 1 >"$STATE/abort"
        return 1
    fi
    set +e
    run_attempt "$suite" "$task" "$init" 0
    status=$?
    set -e
    if [[ "$status" -eq 2 && ! -f "$STATE/abort" ]]; then
        echo "retry once -> attempt_01 $suite task=$task init=$init"
        set +e
        run_attempt "$suite" "$task" "$init" 1
        status=$?
        set -e
        if [[ "$status" -eq 2 ]]; then
            echo "infra again for $suite task=$task init=$init; not retrying" >&2
            echo "$suite $task $init infra" >>"$STATE/completed"
            return 0
        fi
    fi
    if [[ "$status" -eq 0 ]]; then
        echo "$suite $task $init done" >>"$STATE/completed"
    fi
    return "$status"
}

pop_job() {
    if [[ -f "$STATE/abort" ]]; then
        return 1
    fi
    (
        flock -x 9
        if [[ -f "$STATE/abort" || ! -s "$QUEUE" ]]; then
            exit 1
        fi
        head -n 1 "$QUEUE"
        tail -n +2 "$QUEUE" >"$QUEUE.next"
        mv "$QUEUE.next" "$QUEUE"
    ) 9>"$STATE/queue.lock"
}

worker() {
    local id=$1 job suite task init
    echo "worker $id ready"
    while job=$(pop_job); do
        # shellcheck disable=SC2086
        set -- $job
        suite=$1
        task=$2
        init=$3
        run_episode "$suite" "$task" "$init" || echo "worker $id stopped on $job"
        if [[ -f "$STATE/abort" ]]; then
            break
        fi
    done
    echo "worker $id exit"
}

log_gpu || true
for ((i = 0; i < N_WORKERS; i++)); do
    worker "$i" &
    WORKER_PIDS+=("$!")
done

worker_rc=0
for pid in "${WORKER_PIDS[@]}"; do
    if ! wait "$pid"; then
        worker_rc=1
    fi
done
echo 1 >"$STATE/stop"
kill -TERM "$MONITOR_PID" 2>/dev/null || true
wait "$MONITOR_PID" || true
log_gpu || true
echo "batch01 finished completed=$(wc -l <"$STATE/completed" | tr -d ' ') log=$LOG"
if [[ -f "$STATE/abort" ]]; then
    exit 1
fi
exit "$worker_rc"
