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
#
# vLLM keeps the stage-4 serve settings (TP=2, dtype half, util 0.85,
# max-model-len 262144, prefix caching) and adds --disable-custom-all-reduce.
# That process only: NCCL_P2P_DISABLE=1, NCCL_DEBUG=WARN, NCCL log
# $ROOT/logs/nccl_vllm.log. Every 30s this script checks /health. A request
# that emits no tokens for 5 minutes is stalled. On stall or death it pauses
# workers, restarts vLLM, waits until /health and /v1/models answer, then
# resumes workers. The in-flight attempt is failure_kind=infrastructure and
# is rerun as a new attempt. That rerun does not use the one infrastructure
# retry. Each restart appends the time and the previous vLLM log tail to
# $ROOT/logs/vllm_restarts.log.
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
VLLM_HEALTH_S=30
VLLM_STALL_S=300
VLLM_LOG_TAIL=200
NCCL_LOG="$ROOT/logs/nccl_vllm.log"
VLLM_RESTART_LOG="$ROOT/logs/vllm_restarts.log"
VLLM_PID=""

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
        pid=$(basename "$f" .rpent)
        kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    done
    eval "$restore"
}

pause_workers() {
    local pid
    for pid in "${WORKER_PIDS[@]:-}"; do
        [[ -n "$pid" ]] || continue
        kill -STOP "$pid" 2>/dev/null || true
    done
}

resume_workers() {
    local pid
    for pid in "${WORKER_PIDS[@]:-}"; do
        [[ -n "$pid" ]] || continue
        kill -CONT "$pid" 2>/dev/null || true
    done
}

stop_servers() {
    local pid
    resume_workers
    for pid in "${WORKER_PIDS[@]:-}"; do
        [[ -n "$pid" ]] || continue
        kill -TERM "$pid" 2>/dev/null || true
    done
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
    resume_workers
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
    out=$(printf '%s/outputs/batch01/%s/task_%02d/seed_%03d' "$ROOT" "$1" "$2" 11)
    if compgen -G "${out}/attempt_*" >/dev/null; then
        echo "refusing to reuse existing ${out}/attempt_*" >&2
        exit 1
    fi
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
# --disable-custom-all-reduce and NCCL_P2P_DISABLE=1 are the TITAN RTX
# workaround. NCCL_DEBUG=WARN goes to $NCCL_LOG, not this process's stderr.
start_vllm() {
    local log="$RUNLOG/vllm.log"
    mkdir -p "$ROOT/logs" "$RUNLOG"
    echo "starting vllm -> $log"
    echo "nccl log: $NCCL_LOG"
    setsid env \
        CUDA_VISIBLE_DEVICES=0,1 \
        NCCL_P2P_DISABLE=1 \
        NCCL_DEBUG=WARN \
        NCCL_DEBUG_FILE="$NCCL_LOG" \
        "$PLANNER_ENV/bin/vllm" serve "$PLANNER_WEIGHTS" \
        --served-model-name "$PLANNER_WEIGHTS" \
        --host 127.0.0.1 --port "$MODEL_PORT" \
        --tensor-parallel-size 2 \
        --disable-custom-all-reduce \
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
        --reasoning-parser qwen3 \
        >>"$log" 2>&1 &
    VLLM_PID=$!
    SERVER_PIDS[0]=$VLLM_PID
    echo "$VLLM_PID" >"$RUNLOG/vllm.pid"
    echo "started vllm pid=$VLLM_PID"
}

start_vllm

# pi0.5 checkpoint is bf16. No fp16 wrapper. No --parent-watch.
start_server pi05 \
    env CUDA_VISIBLE_DEVICES=2 PI05_CHECKPOINT_PATH="$PI05_CHECKPOINT" \
    "$RPENT_ENV/bin/python" -m rpent.robots.components.pi05_vla_server \
    --transport http --host 127.0.0.1 --port "$VLA_PORT" --cuda-device 2

start_server sam3 \
    env CUDA_VISIBLE_DEVICES=2 SAM3_CHECKPOINT_PATH="$SAM3_CHECKPOINT" \
    "$RPENT_ENV/bin/python" -m rpent.robots.components.sam3_server \
    --transport http --host 127.0.0.1 --port "$SAM3_PORT" --cuda-device 2

wait_vllm_serving() {
    local timeout=$1 start left pid
    start=$SECONDS
    pid=$(<"$RUNLOG/vllm.pid")
    if ! wait_url vllm "http://127.0.0.1:${MODEL_PORT}/health" "$timeout" get "$pid"; then
        return 1
    fi
    left=$((timeout - (SECONDS - start)))
    if (( left < 1 )); then
        left=1
    fi
    pid=$(<"$RUNLOG/vllm.pid")
    wait_url vllm "http://127.0.0.1:${MODEL_PORT}/v1/models" "$left" get "$pid"
}
wait_vllm_serving "$VLLM_READY_S"
wait_url pi05 "http://127.0.0.1:${VLA_PORT}/call" "$SERVICE_READY_S" rpc "${SERVER_PIDS[1]}"
wait_url sam3 "http://127.0.0.1:${SAM3_PORT}/call" "$SERVICE_READY_S" rpc "${SERVER_PIDS[2]}"

server_pid_alive() {
    local name=$1 pid
    [[ -f "$RUNLOG/${name}.pid" ]] || return 1
    pid=$(<"$RUNLOG/${name}.pid")
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

aux_servers_alive() {
    server_pid_alive pi05 && server_pid_alive sam3
}

vllm_endpoint_ok() {
    local kind=$1
    "$RPENT_ENV/bin/python" - "$kind" "$MODEL_PORT" <<'PY'
import sys, urllib.request
kind, port = sys.argv[1], sys.argv[2]
url = f"http://127.0.0.1:{port}/health" if kind == "health" else f"http://127.0.0.1:{port}/v1/models"
try:
    with urllib.request.urlopen(url, timeout=5) as r:
        sys.exit(0 if r.status < 500 else 1)
except Exception:
    sys.exit(1)
PY
}

# One sample: "progress|idle|busy|unhealthy|unknown <token count>".
# progress: generation or prompt tokens increased, or the latest stats line
# shows throughput. busy: a request is running and neither moved.
vllm_sample() {
    local prev=$1
    "$RPENT_ENV/bin/python" - "$MODEL_PORT" "$RUNLOG/vllm.log" "$prev" <<'PY'
import re, sys
from pathlib import Path
import urllib.request

port, log_path, prev = sys.argv[1], Path(sys.argv[2]), float(sys.argv[3])

def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except Exception:
        return None, b""

status, _ = get(f"http://127.0.0.1:{port}/health")
if status is None or status >= 500:
    print(f"unhealthy {prev}")
    raise SystemExit(0)

_, body = get(f"http://127.0.0.1:{port}/metrics")
text = body.decode("utf-8", "replace")

def sum_metric(name):
    total = None
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        head, _, rest = line.partition(" ")
        metric = head.split("{", 1)[0]
        if metric != name:
            continue
        try:
            val = float(rest.split()[0])
        except (ValueError, IndexError):
            continue
        total = val if total is None else total + val
    return total

parts = []
for name in (
    "vllm:generation_tokens_total",
    "vllm:prompt_tokens_total",
    "vllm:iteration_tokens_total_sum",
):
    val = sum_metric(name)
    if val is not None:
        parts.append(val)
progress = sum(parts) if parts else None
running = sum_metric("vllm:num_requests_running")

prompt_tp = gen_tp = log_running = None
if log_path.is_file():
    data = log_path.read_bytes()
    if len(data) > 262144:
        data = data[-262144:]
    stats = re.compile(
        r"Avg prompt throughput:\s*([0-9.]+)\s*tokens/s,\s*"
        r"Avg generation throughput:\s*([0-9.]+)\s*tokens/s,\s*"
        r"Running:\s*(\d+)\s*reqs"
    )
    for line in reversed(data.decode("utf-8", "replace").splitlines()):
        match = stats.search(line)
        if match:
            prompt_tp = float(match.group(1))
            gen_tp = float(match.group(2))
            log_running = int(match.group(3))
            break
if running is None and log_running is not None:
    running = float(log_running)
throughput = (prompt_tp or 0.0) + (gen_tp or 0.0)
shown = prev if progress is None else progress
if (progress is not None and progress > prev + 0.5) or throughput > 0:
    kind = "progress"
elif running is None:
    kind = "unknown"
elif running <= 0:
    kind = "idle"
else:
    kind = "busy"
print(f"{kind} {shown}")
PY
}

mark_infrastructure() {
    local out=$1 reason=$2
    mkdir -p "$out"
    if [[ -f "$out/failure_kind.json" ]]; then
        return 0
    fi
    printf '{"failure_kind":"infrastructure","reason":"%s"}\n' "$reason" >"$out/failure_kind.json"
}

# rpent_libero.read_verdict counts a transcript that has "solved" and no
# infrastructure error as a task result. An in-flight kill must not.
stamp_infra_transcript() {
    local out=$1
    "$RPENT_ENV/bin/python" - "$out" <<'PY'
import json, sys
from pathlib import Path

directory = Path(sys.argv[1])
for path in sorted(directory.glob("transcript_*.json")):
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    if not isinstance(rec, dict):
        continue
    err = str(rec.get("agent_error") or "")
    low = err.lower()
    if any(part in low for part in ("killed", "connection", "server disconnected", "cuda")):
        continue
    rec["agent_error"] = "vLLM restarted; in-flight request killed"
    path.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

mark_and_stop_inflight() {
    local reason=$1 f pid suite task init attempt out restore
    local -a pids=()
    restore=$(shopt -p nullglob)
    shopt -s nullglob
    for f in "$STATE/running"/*.rpent; do
        pid=$(basename "$f" .rpent)
        if read -r suite task init attempt out <"$f" && [[ -n "${out:-}" ]]; then
            mark_infrastructure "$out" "vllm_${reason}"
            echo "in-flight $suite task=$task init=$init attempt=$attempt failure_kind=infrastructure ($reason)"
        fi
        pids+=("$pid")
    done
    eval "$restore"
    for pid in "${pids[@]:-}"; do
        [[ -n "$pid" ]] || continue
        kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    done
    sleep 2
    for pid in "${pids[@]:-}"; do
        [[ -n "$pid" ]] || continue
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
        fi
    done
}

append_restart_log() {
    local reason=$1
    mkdir -p "$(dirname "$VLLM_RESTART_LOG")"
    {
        echo "===== $(date -Is) reason=${reason} ====="
        if [[ -f "$RUNLOG/vllm.log" ]]; then
            tail -n "$VLLM_LOG_TAIL" "$RUNLOG/vllm.log"
        else
            echo "(no vllm log)"
        fi
        echo
    } >>"$VLLM_RESTART_LOG"
}

stop_vllm() {
    local pid i
    [[ -f "$RUNLOG/vllm.pid" ]] || return 0
    pid=$(<"$RUNLOG/vllm.pid")
    [[ -n "$pid" ]] || return 0
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    for ((i = 0; i < 30; i++)); do
        if ! kill -0 "$pid" 2>/dev/null && ! kill -0 -- "-$pid" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    kill -KILL -- "-$pid" 2>/dev/null || true
    kill -KILL "$pid" 2>/dev/null || true
    sleep 1
}

wait_port_free() {
    local port=$1 timeout=$2 deadline
    deadline=$((SECONDS + timeout))
    while (( SECONDS < deadline )); do
        if port_free "$port"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

restart_vllm() {
    local reason=$1 epoch
    echo "[$(date -Is)] vLLM ${reason}; pausing workers and restarting"
    pause_workers
    echo 1 >"$STATE/vllm_down"
    epoch=$(cat "$STATE/vllm_epoch" 2>/dev/null || echo 0)
    echo $((epoch + 1)) >"$STATE/vllm_epoch"
    mark_and_stop_inflight "$reason"
    stop_vllm
    append_restart_log "$reason"
    if ! wait_port_free "$MODEL_PORT" 60; then
        echo "vLLM port $MODEL_PORT still in use after stop" >&2
        echo 1 >"$STATE/abort"
        rm -f "$STATE/vllm_down"
        resume_workers
        return 1
    fi
    start_vllm
    if ! wait_vllm_serving "$VLLM_READY_S"; then
        echo "vLLM did not become healthy after restart" >&2
        echo 1 >"$STATE/abort"
        rm -f "$STATE/vllm_down"
        resume_workers
        return 1
    fi
    rm -f "$STATE/vllm_down"
    resume_workers
    echo "[$(date -Is)] vLLM healthy again pid=$(<"$RUNLOG/vllm.pid")"
}

any_worker_alive() {
    local pid
    for pid in "${WORKER_PIDS[@]:-}"; do
        [[ -n "$pid" ]] || continue
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    done
    return 1
}

# /health every 30s. No tokens from a running request for 5 minutes is a stall.
# Process death or a failed /health is death. Both restart vLLM.
watch_vllm() {
    local prev=-1 last_progress=$SECONDS slept status progress sample
    while true; do
        if [[ -f "$STATE/stop" || -f "$STATE/abort" ]]; then
            return 0
        fi
        if ! any_worker_alive; then
            return 0
        fi
        slept=0
        while (( slept < VLLM_HEALTH_S )); do
            if [[ -f "$STATE/stop" || -f "$STATE/abort" ]] || ! any_worker_alive; then
                return 0
            fi
            sleep 1
            slept=$((slept + 1))
        done
        if [[ -f "$STATE/vllm_down" || -f "$STATE/abort" ]]; then
            continue
        fi
        if ! server_pid_alive vllm; then
            restart_vllm death || return 1
            prev=-1
            last_progress=$SECONDS
            continue
        fi
        sample=$(vllm_sample "$prev" || true)
        if [[ -z "$sample" ]]; then
            status=unknown
            progress=$prev
        else
            read -r status progress <<<"$sample"
        fi
        case "$status" in
            progress|idle)
                last_progress=$SECONDS
                if [[ "$progress" != "none" ]]; then
                    prev=$progress
                fi
                ;;
            busy)
                if [[ "$progress" != "none" ]]; then
                    prev=$progress
                fi
                if (( SECONDS - last_progress >= VLLM_STALL_S )); then
                    restart_vllm stall || return 1
                    prev=-1
                    last_progress=$SECONDS
                fi
                ;;
            unhealthy)
                sleep 2
                if ! server_pid_alive vllm || ! vllm_endpoint_ok health; then
                    restart_vllm death || return 1
                    prev=-1
                    last_progress=$SECONDS
                fi
                ;;
            unknown)
                # No positive "request is running" sample. Do not let a blind
                # gap make the next busy sample look like a 5-minute stall.
                last_progress=$SECONDS
                ;;
            *)
                ;;
        esac
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
        printf '%s %s %s %s %s\n' "$suite" "$task" "$init" "$attempt" "$out" >"$pf"
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

# True when this attempt overlapped a vLLM stall or death. The caller reruns
# it as a new attempt and does not consume the one infrastructure retry.
vllm_outage() {
    local out=$1 epoch_before=$2 epoch_after
    if [[ -f "$out/failure_kind.json" || -f "$STATE/vllm_down" ]]; then
        return 0
    fi
    epoch_after=$(cat "$STATE/vllm_epoch" 2>/dev/null || echo 0)
    if [[ "$epoch_before" != "$epoch_after" ]]; then
        return 0
    fi
    if ! server_pid_alive vllm || ! vllm_endpoint_ok health; then
        return 0
    fi
    return 1
}

wait_vllm_for_attempt() {
    local deadline=$((SECONDS + VLLM_READY_S))
    while (( SECONDS < deadline )); do
        if [[ -f "$STATE/abort" ]]; then
            return 1
        fi
        if [[ ! -f "$STATE/vllm_down" ]] && server_pid_alive vllm \
            && vllm_endpoint_ok health && vllm_endpoint_ok models; then
            return 0
        fi
        sleep 2
    done
    echo "vLLM stayed down; aborting" >&2
    echo 1 >"$STATE/abort"
    return 1
}

run_attempt() {
    local suite=$1 task=$2 init=$3 attempt=$4
    local out elog rc epoch_before
    out=$(episode_dir "$suite" "$task" "$init" "$attempt")
    elog=$(printf '%s/episodes/%s_t%02d_s%03d_a%02d.log' "$RUNLOG" "$suite" "$task" "$init" "$attempt")
    epoch_before=$(cat "$STATE/vllm_epoch" 2>/dev/null || echo 0)
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
    # A finished episode wins over a restart marker written in the exit race.
    if [[ "$rc" -eq 0 ]] && ! is_infra "$out" "$rc"; then
        rm -f "$out/failure_kind.json"
        convert_if_ready "$out" "$suite" "$task" "$init" "$attempt"
        return 0
    fi
    if vllm_outage "$out" "$epoch_before"; then
        mark_infrastructure "$out" "vllm_down"
        stamp_infra_transcript "$out" || true
        echo "infra-free $out rc=$rc (vLLM down; retry budget not used)"
        convert_if_ready "$out" "$suite" "$task" "$init" "$attempt"
        return 3
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
    local suite=$1 task=$2 init=$3 attempt=0 infra_used=0 status
    while true; do
        if [[ -f "$STATE/abort" ]]; then
            return 1
        fi
        if ! aux_servers_alive; then
            echo "pi0.5 or SAM3 died; aborting" >&2
            echo 1 >"$STATE/abort"
            return 1
        fi
        if ! wait_vllm_for_attempt; then
            return 1
        fi
        set +e
        run_attempt "$suite" "$task" "$init" "$attempt"
        status=$?
        set -e
        if [[ -f "$STATE/abort" || "$status" -eq 1 ]]; then
            return 1
        fi
        if [[ "$status" -eq 0 ]]; then
            echo "$suite $task $init done" >>"$STATE/completed"
            return 0
        fi
        if [[ "$status" -eq 3 ]]; then
            echo "vLLM outage kept attempt_$(printf '%02d' "$attempt") as infrastructure; rerun as attempt_$(printf '%02d' "$((attempt + 1))") without using the infra retry ($suite task=$task init=$init)"
            attempt=$((attempt + 1))
            continue
        fi
        if [[ "$status" -eq 2 ]]; then
            if [[ "$infra_used" -ge 1 ]]; then
                echo "infra again for $suite task=$task init=$init; not retrying" >&2
                echo "$suite $task $init infra" >>"$STATE/completed"
                return 0
            fi
            infra_used=1
            echo "retry once -> attempt_$(printf '%02d' "$((attempt + 1))") $suite task=$task init=$init"
            attempt=$((attempt + 1))
            continue
        fi
        return "$status"
    done
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

echo 0 >"$STATE/vllm_epoch"
log_gpu || true
for ((i = 0; i < N_WORKERS; i++)); do
    worker "$i" &
    WORKER_PIDS+=("$!")
done

watch_rc=0
watch_vllm || watch_rc=1
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
if [[ -f "$STATE/abort" || "$watch_rc" -ne 0 ]]; then
    exit 1
fi
exit "$worker_rc"
