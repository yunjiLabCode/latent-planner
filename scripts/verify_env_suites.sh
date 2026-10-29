#!/usr/bin/env bash
# Reset three LIBERO-PRO suites, one env server at a time, and save an
# agentview image from each. Does not start vLLM, pi0.5, or SAM3, and
# does not launch rpent.cli.main.
#
# The incoming CUDA_VISIBLE_DEVICES must be non-empty and must not
# contain 3. After that check (repeated after sourcing env.sh), this
# script pins the env server to CUDA_VISIBLE_DEVICES=2 and
# MUJOCO_EGL_DEVICE_ID=2. It does not pass --cuda-device: env_server
# clears CUDA_VISIBLE_DEVICES when that flag is set. It does not write
# CUDA_VISIBLE_DEVICES into env.sh.
#
#   CUDA_VISIBLE_DEVICES=2 MUJOCO_EGL_DEVICE_ID=2 \
#     ROOT=/data/yunji/latent-planner-work \
#     bash scripts/verify_env_suites.sh
#
# Images: $ROOT/outputs/env_verify/<suite>_task0_agentview.png
# ROOT defaults to /data/yunji/latent-planner-work.
# Each suite is task 0, seed 0. The server is stopped before the next
# suite starts.
set -euo pipefail

ROOT="${ROOT:-/data/yunji/latent-planner-work}"
OUT="$ROOT/outputs/env_verify"

reject_gpu3() {
    local cvd="${CUDA_VISIBLE_DEVICES:-}"
    local dev
    if [[ -z "${cvd//[[:space:]]/}" ]]; then
        echo "CUDA_VISIBLE_DEVICES is empty; refusing to start" >&2
        exit 1
    fi
    local IFS=','
    for dev in $cvd; do
        dev="${dev//[[:space:]]/}"
        [[ -n "$dev" ]] || continue
        if [[ "$dev" == "3" ]]; then
            echo "CUDA_VISIBLE_DEVICES contains 3; refusing GPU 3" >&2
            exit 1
        fi
    done
}

reject_gpu3
if [[ ! -f "$ROOT/env.sh" ]]; then
    echo "missing $ROOT/env.sh" >&2
    exit 1
fi
root_before=$ROOT
set +u
# shellcheck disable=SC1091
source "$ROOT/env.sh"
set -u
ROOT=$root_before
reject_gpu3

if [[ -z "${RPENT_DIR:-}" || -z "${RPENT_ENV:-}" ]]; then
    echo "RPENT_DIR or RPENT_ENV is unset after sourcing $ROOT/env.sh" >&2
    exit 1
fi
if [[ ! -x "$RPENT_ENV/bin/python" ]]; then
    echo "missing $RPENT_ENV/bin/python" >&2
    exit 1
fi
SERVER="$RPENT_DIR/robots/libero/env_server.py"
if [[ ! -f "$SERVER" ]]; then
    echo "missing $SERVER" >&2
    exit 1
fi

export CUDA_VISIBLE_DEVICES=2
export MUJOCO_EGL_DEVICE_ID=2
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export LIBERO_TYPE=pro
export ROBOT_PLATFORM=LIBERO
export PYTHONPATH="${RPENT_DIR}${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$OUT"

current_server=

kill_tree() {
    local pid=$1 sig=$2
    local child
    local children
    children=$(ps -o pid= --ppid "$pid" 2>/dev/null || true)
    for child in $children; do
        kill_tree "$child" "$sig"
    done
    kill "-$sig" "$pid" 2>/dev/null || true
}

stop_server() {
    if [[ -z "${current_server}" ]]; then
        return 0
    fi
    local pid=$current_server
    current_server=
    kill_tree "$pid" TERM
    local i
    for i in $(seq 1 20); do
        if ! kill -0 "$pid" 2>/dev/null; then
            wait "$pid" || true
            return 0
        fi
        sleep 0.5
    done
    kill_tree "$pid" KILL
    wait "$pid" || true
}

trap stop_server EXIT

pick_port() {
    python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

save_agentview() {
    local url=$1 png=$2
    "$RPENT_ENV/bin/python" - "$url" "$png" <<'PY'
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rpent.utils.rpc.http_rpc import HttpRpcClient

url, png = sys.argv[1], sys.argv[2]
client = HttpRpcClient(url)
result = client.call("env.reset", timeout_s=300.0)
if not (isinstance(result, list) and len(result) == 2 and isinstance(result[0], dict)):
    raise SystemExit(f"unexpected env.reset result: {type(result).__name__}")
obs = result[0]
img = obs.get("agentview_image")
if img is None:
    rendered = client.call(
        "env.render_camera",
        kwargs={
            "camera_name": "agentview",
            "height": 256,
            "width": 256,
            "depth": False,
        },
        timeout_s=120.0,
    )
    if isinstance(rendered, list) and rendered and hasattr(rendered[0], "shape"):
        img = rendered[0]
    else:
        img = rendered
arr = np.asarray(img)
if arr.ndim == 3 and arr.shape[-1] not in (3, 4) and arr.shape[0] in (3, 4):
    arr = np.transpose(arr, (1, 2, 0))
if arr.dtype != np.uint8:
    arr = np.clip(arr, 0, 255).astype(np.uint8)
# robots/libero/tools.py saves agentview.png as a vertical flip of the
# raw buffer so the image is upright.
arr = np.ascontiguousarray(arr[::-1])
Path(png).parent.mkdir(parents=True, exist_ok=True)
Image.fromarray(arr).save(png)
print(png, tuple(arr.shape))
try:
    client.call("shutdown", timeout_s=30.0)
except Exception as exc:
    print(f"shutdown: {exc}", file=sys.stderr)
PY
}

run_suite() {
    local suite=$1
    local port srvlog png url
    port=$(pick_port)
    srvlog="$OUT/${suite}_task0_env_server.log"
    png="$OUT/${suite}_task0_agentview.png"
    echo "start env server $suite task=0 seed=0 port=$port -> $png"
    # No --cuda-device and no --parent-watch. --cuda-device clears
    # CUDA_VISIBLE_DEVICES. --parent-watch would exit because stdin is
    # /dev/null. vLLM, pi0.5, and SAM3 are not started.
    env \
        CUDA_VISIBLE_DEVICES=2 \
        MUJOCO_EGL_DEVICE_ID=2 \
        MUJOCO_GL=egl \
        PYOPENGL_PLATFORM=egl \
        LIBERO_TYPE=pro \
        ROBOT_PLATFORM=LIBERO \
        PYTHONPATH="$PYTHONPATH" \
        "$RPENT_ENV/bin/python" -u "$SERVER" \
        --suite "$suite" \
        --task 0 \
        --seed 0 \
        --max-episode-steps 10000 \
        --transport http \
        --host 127.0.0.1 \
        --port "$port" \
        >"$srvlog" 2>&1 </dev/null &
    current_server=$!

    url=""
    local i
    for i in $(seq 1 600); do
        if ! kill -0 "$current_server" 2>/dev/null; then
            echo "env server exited before listening: $suite" >&2
            tail -n 40 "$srvlog" >&2 || true
            exit 1
        fi
        if grep -q "RPC server listening on " "$srvlog"; then
            url=$(sed -n 's/.*RPC server listening on //p' "$srvlog" | head -n 1)
            break
        fi
        sleep 1
    done
    if [[ -z "$url" ]]; then
        echo "env server did not listen within 600s: $suite" >&2
        tail -n 40 "$srvlog" >&2 || true
        exit 1
    fi
    echo "listening $url"
    if ! save_agentview "$url" "$png"; then
        echo "reset failed: $suite" >&2
        tail -n 40 "$srvlog" >&2 || true
        exit 1
    fi
    if [[ ! -s "$png" ]]; then
        echo "missing agentview image: $png" >&2
        exit 1
    fi
    stop_server
    echo "stopped $suite"
}

run_suite libero_object_task
run_suite libero_10_task
run_suite libero_goal_task
echo "saved agentview images under $OUT"
