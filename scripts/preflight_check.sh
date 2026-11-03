#!/usr/bin/env bash
# Read EDAC correctable-error counts, free -g, root free space, kern.log
# growth, GPU 3, and whether cache/TMPDIR from env.sh are under /data.
#
# Does not use sudo, does not start a server, and does not edit env.sh.
# Does not set CUDA_VISIBLE_DEVICES.
#
#   bash scripts/preflight_check.sh /data/yunji/latent-planner-work/logs/preflight.baseline
#   bash scripts/preflight_check.sh --record /path/to/preflight.baseline
#
# --record writes the current CE sum and a kern.log size/time sample to
# BASELINE_FILE, then runs the same checks. Without --record, BASELINE_FILE
# must already contain:
#
#   ce_sum=<integer>
#   kern_bytes=<integer>
#   kern_epoch=<integer seconds since epoch>
#
# Exit 1 when any of these is true:
#   - CE sum is greater than ce_sum in the baseline
#   - /var/log/kern.log grew by 10MiB or more per minute versus that sample
#   - space available on / is under 5GiB (5 * 1024^3 bytes)
# GPU 3 and the cache/TMPDIR lines are printed either way.
#
# ROOT is the directory that holds env.sh. Default:
# /data/yunji/latent-planner-work. KERN_LOG defaults to /var/log/kern.log.
# EDAC_ROOT defaults to /sys/devices/system/edac/mc. The walk is
# $EDAC_ROOT/mc*/dimm*/.
set -euo pipefail

ROOT="${ROOT:-/data/yunji/latent-planner-work}"
KERN_LOG="${KERN_LOG:-/var/log/kern.log}"
EDAC_ROOT="${EDAC_ROOT:-/sys/devices/system/edac/mc}"
LIMIT_BYTES=$((10 * 1024 * 1024))
ROOT_MIN_BYTES=$((5 * 1024 * 1024 * 1024))

usage() {
    echo "usage: bash scripts/preflight_check.sh [--record] BASELINE_FILE" >&2
    exit 2
}

record=0
baseline=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --record)
            record=1
            shift
            ;;
        -h|--help)
            usage
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "unknown option: $1" >&2
            usage
            ;;
        *)
            if [[ -n "$baseline" ]]; then
                usage
            fi
            baseline=$1
            shift
            ;;
    esac
done
if [[ -z "$baseline" || $# -gt 0 ]]; then
    usage
fi

fail=0

note_fail() {
    fail=1
    echo "FAIL: $1" >&2
}

read_sysfs() {
    local path=$1
    local value
    if [[ ! -r "$path" ]]; then
        return 1
    fi
    # head keeps an empty label. `read` returns 1 on a file with no newline.
    value=$(head -n 1 "$path") || return 1
    value=${value%$'\r'}
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

echo "edac:"
ce_sum=0
dimm_found=0
ce_ok=1
shopt -s nullglob
for dimm in "$EDAC_ROOT"/mc*/dimm*/; do
    dimm_found=1
    dimm="${dimm%/}"
    label="(missing)"
    if [[ -e "$dimm/dimm_label" ]]; then
        if ! label=$(read_sysfs "$dimm/dimm_label"); then
            echo "dimm $dimm label=(unreadable) ce=(unread)"
            note_fail "unreadable $dimm/dimm_label"
            ce_ok=0
            continue
        fi
    fi
    if ! ce=$(read_sysfs "$dimm/dimm_ce_count"); then
        echo "dimm $dimm label=$(printf '%q' "$label") ce=(unreadable)"
        note_fail "unreadable $dimm/dimm_ce_count"
        ce_ok=0
        continue
    fi
    if [[ ! "$ce" =~ ^[0-9]+$ ]]; then
        echo "dimm $dimm label=$(printf '%q' "$label") ce=$(printf '%q' "$ce")"
        note_fail "non-integer ce count at $dimm/dimm_ce_count"
        ce_ok=0
        continue
    fi
    echo "dimm $dimm label=$(printf '%q' "$label") ce=$ce"
    ce_sum=$((ce_sum + ce))
done
shopt -u nullglob
if [[ "$dimm_found" -eq 0 ]]; then
    echo "dimm entries: 0"
fi
echo "ce_sum=$ce_sum"

echo "free -g:"
if ! free -g; then
    echo "free -g failed" >&2
fi

root_avail=""
if root_avail=$(df -B1 -P / | awk 'NR==2 {print $(NF-2)}') && [[ "$root_avail" =~ ^[0-9]+$ ]]; then
    echo "root_avail_bytes=$root_avail"
    if (( root_avail < ROOT_MIN_BYTES )); then
        note_fail "root available ${root_avail} bytes is under ${ROOT_MIN_BYTES}"
    fi
else
    echo "root_avail_bytes=(unknown)"
    note_fail "could not read available bytes on /"
    root_avail=""
fi

kern_bytes=""
if [[ -e "$KERN_LOG" ]]; then
    if kern_bytes=$(stat -c %s "$KERN_LOG" 2>/dev/null) && [[ "$kern_bytes" =~ ^[0-9]+$ ]]; then
        echo "kern_log=$KERN_LOG"
        echo "kern_bytes=$kern_bytes"
    else
        echo "kern_log=$KERN_LOG"
        echo "kern_bytes=(unreadable)"
        note_fail "could not stat $KERN_LOG"
        kern_bytes=""
    fi
else
    echo "kern_log=$KERN_LOG"
    echo "kern_bytes=(missing)"
    note_fail "missing $KERN_LOG"
fi

now_epoch=$(date +%s)

if [[ "$record" -eq 1 ]]; then
    if [[ -n "$kern_bytes" && "$ce_ok" -eq 1 ]]; then
        baseline_dir=$(dirname "$baseline")
        mkdir -p "$baseline_dir"
        tmp="${baseline}.tmp.$$"
        printf 'ce_sum=%s\nkern_bytes=%s\nkern_epoch=%s\n' \
            "$ce_sum" "$kern_bytes" "$now_epoch" >"$tmp"
        mv "$tmp" "$baseline"
        echo "recorded baseline=$baseline"
    else
        note_fail "baseline not recorded"
    fi
fi

ce_base=""
kern_base=""
kern_epoch=""
if [[ ! -f "$baseline" ]]; then
    note_fail "baseline file not found: $baseline"
else
    while IFS= read -r line || [[ -n "$line" ]]; do
        case "$line" in
            ''|\#*)
                ;;
            ce_sum=*)
                ce_base=${line#ce_sum=}
                ;;
            kern_bytes=*)
                kern_base=${line#kern_bytes=}
                ;;
            kern_epoch=*)
                kern_epoch=${line#kern_epoch=}
                ;;
            *)
                note_fail "bad baseline line: $line"
                ;;
        esac
    done <"$baseline"
    if [[ ! "$ce_base" =~ ^[0-9]+$ || ! "$kern_base" =~ ^[0-9]+$ || ! "$kern_epoch" =~ ^[0-9]+$ ]]; then
        note_fail "baseline missing ce_sum, kern_bytes, or kern_epoch"
    else
        echo "baseline_ce_sum=$ce_base"
        echo "baseline_kern_bytes=$kern_base"
        echo "baseline_kern_epoch=$kern_epoch"
        if (( ce_sum > ce_base )); then
            note_fail "ce_sum $ce_sum is greater than baseline $ce_base"
        fi
        if [[ -n "$kern_bytes" ]]; then
            delta=$((kern_bytes - kern_base))
            elapsed=$((now_epoch - kern_epoch))
            echo "kern_delta_bytes=$delta"
            echo "kern_elapsed_s=$elapsed"
            if (( delta < 0 )); then
                echo "kern_bytes_per_min=(shrunk)"
            elif (( elapsed <= 0 )); then
                echo "kern_bytes_per_min=(elapsed_nonpositive)"
                if (( delta >= LIMIT_BYTES )); then
                    note_fail "kern.log grew ${delta} bytes with no elapsed time (limit ${LIMIT_BYTES} bytes/min)"
                fi
            else
                rate=$((delta * 60 / elapsed))
                echo "kern_bytes_per_min=$rate"
                if (( delta * 60 >= LIMIT_BYTES * elapsed )); then
                    note_fail "kern.log grew ${rate} bytes/min (limit ${LIMIT_BYTES})"
                fi
            fi
        fi
    fi
fi

echo "gpu3:"
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "gpu3_in_use=unknown"
    echo "gpu3_detail=nvidia-smi missing"
else
    gpu3_query=$(nvidia-smi -i 3 --query-compute-apps=pid,process_name,used_gpu_memory --format=csv,noheader 2>/dev/null || true)
    gpu3_mem=$(nvidia-smi -i 3 --query-gpu=memory.used --format=csv,noheader 2>/dev/null || true)
    if [[ -n "$gpu3_mem" ]]; then
        echo "gpu3_memory_used=$gpu3_mem"
    else
        echo "gpu3_memory_used=(unknown)"
    fi
    if [[ -n "${gpu3_query//[[:space:]]/}" ]]; then
        echo "gpu3_in_use=yes"
        printf '%s\n' "$gpu3_query"
    elif [[ -z "$gpu3_mem" ]]; then
        echo "gpu3_in_use=unknown"
    else
        echo "gpu3_in_use=no"
    fi
fi

cache_name() {
    case "$1" in
        TMPDIR|TORCH_HOME|XDG_CACHE_HOME|HF_HOME|HF_HUB_CACHE|TRANSFORMERS_CACHE|PIP_CACHE_DIR|UV_CACHE_DIR|CONDA_PKGS_DIRS|TRITON_CACHE_DIR|CUDA_CACHE_PATH|VLLM_CACHE_ROOT|TORCHINDUCTOR_CACHE_DIR|*CACHE*|*TMPDIR*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

under_data() {
    local path=$1 resolved
    [[ -n "$path" ]] || return 1
    if resolved=$(readlink -f "$path" 2>/dev/null) && [[ -n "$resolved" ]]; then
        path=$resolved
    fi
    [[ "$path" == /data || "$path" == /data/* ]]
}

echo "env.sh:"
env_sh="$ROOT/env.sh"
if [[ ! -f "$env_sh" ]]; then
    echo "env_sh=missing"
    echo "cache_tmpdir_under_data=unknown"
else
    set +u
    set +e
    # shellcheck disable=SC1090
    source "$env_sh"
    env_rc=$?
    set -e
    set -u
    echo "env_sh=$env_sh"
    echo "env_sh_source_rc=$env_rc"
    cache_ok=1
    # Names install_log says env.sh exports. Each must be set and under /data.
    # Any other exported cache or TMPDIR name must be under /data too.
    primary_name() {
        case "$1" in
            HF_HOME|HF_HUB_CACHE|TRANSFORMERS_CACHE|PIP_CACHE_DIR|UV_CACHE_DIR|CONDA_PKGS_DIRS|TMPDIR|XDG_CACHE_HOME|TORCH_HOME)
                return 0
                ;;
            *)
                return 1
                ;;
        esac
    }
    report_path() {
        local name=$1
        local value
        if [[ -z "${!name+x}" ]]; then
            echo "$name=(unset) under_data=no"
            cache_ok=0
            return
        fi
        value=${!name}
        if [[ -z "$value" ]]; then
            echo "$name=(empty) under_data=no"
            cache_ok=0
            return
        fi
        if under_data "$value"; then
            echo "$name=$value under_data=yes"
        else
            echo "$name=$value under_data=no"
            cache_ok=0
        fi
    }
    for name in HF_HOME HF_HUB_CACHE TRANSFORMERS_CACHE PIP_CACHE_DIR UV_CACHE_DIR \
        CONDA_PKGS_DIRS TMPDIR XDG_CACHE_HOME TORCH_HOME; do
        report_path "$name"
    done
    while IFS= read -r name; do
        cache_name "$name" || continue
        primary_name "$name" && continue
        report_path "$name"
    done < <(compgen -e | sort || true)
    if [[ "$cache_ok" -eq 1 ]]; then
        echo "cache_tmpdir_under_data=yes"
    else
        echo "cache_tmpdir_under_data=no"
    fi
fi

if (( fail != 0 )); then
    echo "preflight_exit=1"
    exit 1
fi
echo "preflight_exit=0"
exit 0
