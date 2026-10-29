#!/usr/bin/env bash
# Apply patches/env/onthegroundpanda_nullbase.patch to the installed
# rpent-libero and rpent-liberopro copies of on_the_ground_panda.py.
#
# Does not set CUDA_VISIBLE_DEVICES. Do not put CUDA_VISIBLE_DEVICES in
# env.sh. This script does not edit env.sh and does not start a process
# that uses a GPU.
#
#   RPENT_ENV  default /data/yunji/latent-planner-work/envs/rpent
#   ROOT       work tree. When set, the log is $ROOT/logs/env_patches.log.
#              When unset, the log is <repo>/logs/env_patches.log.
#              The work tree to pass is /data/yunji/latent-planner-work.
#
#   bash scripts/apply_env_patches.sh --dry-run
#   ROOT=/data/yunji/latent-planner-work bash scripts/apply_env_patches.sh
#
# --dry-run prints the files, sha256, backup path, and diff. It does not
# write the installed files, the backup directory, or the log.
#
# Re-running is safe. A file whose default_base already returns "NullBase"
# is skipped. Originals are copied to
# /data/yunji/latent-planner-work/backups/onthegroundpanda_nullbase/<UTC>/
# before a file is changed.
#
# If any rpent or env_server process is running, print a warning and exit
# without patching. --dry-run still prints the plan, writes nothing, and
# exits 1 in that case.
set -euo pipefail

ROOT_UNSET=0
if [[ -z "${ROOT+x}" ]]; then
    ROOT_UNSET=1
fi
RPENT_ENV="${RPENT_ENV:-/data/yunji/latent-planner-work/envs/rpent}"
BACKUP_PARENT="/data/yunji/latent-planner-work/backups/onthegroundpanda_nullbase"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
PATCH="$REPO_ROOT/patches/env/onthegroundpanda_nullbase.patch"

if [[ "$ROOT_UNSET" -eq 1 ]]; then
    LOG="$REPO_ROOT/logs/env_patches.log"
else
    if [[ -z "${ROOT}" ]]; then
        echo "ROOT is set but empty" >&2
        exit 1
    fi
    LOG="$ROOT/logs/env_patches.log"
fi

DRY_RUN=0
if [[ $# -gt 1 ]]; then
    echo "usage: bash scripts/apply_env_patches.sh [--dry-run]" >&2
    exit 1
fi
if [[ $# -eq 1 ]]; then
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        *)
            echo "unknown argument: $1" >&2
            echo "usage: bash scripts/apply_env_patches.sh [--dry-run]" >&2
            exit 1
            ;;
    esac
fi

if [[ ! -f "$PATCH" ]]; then
    echo "missing patch: $PATCH" >&2
    exit 1
fi
if ! command -v patch >/dev/null; then
    echo "missing command: patch" >&2
    exit 1
fi

# Bracket the first letter so this pipeline's own argv does not match.
running_blockers() {
    ps -eo pid=,args= | grep -E '(^|[^A-Za-z0-9_])[r]pent([^A-Za-z0-9_]|$)|[e]nv_server' || true
}

BLOCKERS=$(running_blockers)
if [[ -n "$BLOCKERS" ]]; then
    echo "warning: rpent or env_server is running; not patching" >&2
    echo "$BLOCKERS" >&2
    if [[ "$DRY_RUN" -eq 0 ]]; then
        exit 1
    fi
fi

if [[ ! -d "$RPENT_ENV" ]]; then
    echo "RPENT_ENV is not a directory: $RPENT_ENV" >&2
    exit 1
fi

mapfile -t FILES < <(find "$RPENT_ENV" -type f \( \
    -path '*/site-packages/libero/libero/envs/robots/on_the_ground_panda.py' -o \
    -path '*/site-packages/liberopro/liberopro/envs/robots/on_the_ground_panda.py' \
\) | sort)

libero_n=0
pro_n=0
for f in "${FILES[@]}"; do
    case "$f" in
        */site-packages/libero/libero/envs/robots/on_the_ground_panda.py)
            libero_n=$((libero_n + 1))
            ;;
        */site-packages/liberopro/liberopro/envs/robots/on_the_ground_panda.py)
            pro_n=$((pro_n + 1))
            ;;
    esac
done
if [[ "$libero_n" -ne 1 || "$pro_n" -ne 1 ]]; then
    echo "expected one rpent-libero and one rpent-liberopro on_the_ground_panda.py under $RPENT_ENV (libero=$libero_n liberopro=$pro_n)" >&2
    if [[ ${#FILES[@]} -gt 0 ]]; then
        printf '  %s\n' "${FILES[@]}" >&2
    fi
    exit 1
fi

label_for() {
    case "$1" in
        */site-packages/libero/libero/envs/robots/on_the_ground_panda.py)
            echo rpent-libero
            ;;
        */site-packages/liberopro/liberopro/envs/robots/on_the_ground_panda.py)
            echo rpent-liberopro
            ;;
        *)
            echo "unrecognized path: $1" >&2
            return 1
            ;;
    esac
}

# Print yes when OnTheGroundPanda.default_base already returns "NullBase".
already_nullbase() {
    awk '
        BEGIN { found = 0 }
        /def default_base\(self\)/ { found = 1; next }
        found == 1 && /return / {
            if ($0 ~ /return "NullBase"/) print "yes"
            else print "no"
            found = 2
            exit
        }
        END { if (found != 2) print "missing" }
    ' "$1"
}

TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="$BACKUP_PARENT/$TS"

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "dry-run: no files will be written"
    if [[ "$ROOT_UNSET" -eq 1 ]]; then
        echo "ROOT is unset; a real apply would append to the repository log $LOG"
    else
        echo "a real apply would append to $LOG"
    fi
else
    if [[ "$ROOT_UNSET" -eq 1 ]]; then
        echo "ROOT is unset; appending to the repository log $LOG"
    else
        echo "appending to $LOG"
    fi
fi

for f in "${FILES[@]}"; do
    label=$(label_for "$f")
    sha_before=$(sha256sum "$f" | awk '{print $1}')
    state=$(already_nullbase "$f")
    backup="$BACKUP_DIR/${label}_on_the_ground_panda.py"
    if [[ "$state" == "missing" ]]; then
        echo "default_base not found in $f" >&2
        exit 1
    fi
    if [[ "$state" == "yes" ]]; then
        echo "skip $label (default_base already returns \"NullBase\"): $f"
        echo "sha256 $sha_before"
        continue
    fi
    if [[ "$state" != "no" ]]; then
        echo "could not read default_base in $f (state=$state)" >&2
        exit 1
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "would patch $label: $f"
        echo "sha256_before $sha_before"
        echo "backup $backup"
        echo "diff:"
        awk 'BEGIN { p = 0 } /^--- / { p = 1 } p' "$PATCH"
        echo
        continue
    fi

    echo "patch $label: $f"
    echo "sha256_before $sha_before"
    mkdir -p "$BACKUP_DIR"
    cp -a -- "$f" "$backup"
    work=$(mktemp -d)
    cp -a -- "$f" "$work/on_the_ground_panda.py"
    awk 'BEGIN { p = 0 } /^--- / { p = 1 } p' "$PATCH" >"$work/hunk.diff"
    if ! patch --forward --batch --no-backup-if-mismatch --reject-file=- \
        -p1 -d "$work" -i "$work/hunk.diff"; then
        echo "patch failed for $f; installed file left unchanged" >&2
        rm -rf "$work"
        exit 1
    fi
    if [[ "$(already_nullbase "$work/on_the_ground_panda.py")" != "yes" ]]; then
        echo "patched copy does not return \"NullBase\": $f" >&2
        rm -rf "$work"
        exit 1
    fi
    cat "$work/on_the_ground_panda.py" >"$f"
    rm -rf "$work"
    sha_after=$(sha256sum "$f" | awk '{print $1}')
    echo "sha256_after $sha_after"
    echo "backup $backup"
    mkdir -p "$(dirname "$LOG")"
    {
        echo "## $(date -u +%Y-%m-%dT%H:%M:%SZ) onthegroundpanda_nullbase"
        echo "file: $f"
        echo "sha256_before: $sha_before"
        echo "sha256_after: $sha_after"
        echo "backup: $backup"
        echo "diff:"
        diff -u --label "$backup" --label "$f" "$backup" "$f" || true
        echo
    } >>"$LOG"
done

if [[ -n "$BLOCKERS" ]]; then
    exit 1
fi
