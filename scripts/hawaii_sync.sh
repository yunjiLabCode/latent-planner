#!/bin/sh
# Pull the workspace checkout on Hawaii and record the commits that were pulled.
# Does not commit, push, or reset.
# Aborts when that checkout has uncommitted changes or commits not on origin/main.
set -eu
cd /data/yunji/latent-planner-work/src/latent-planner
# Fetch updates origin/main and does not change the worktree. Check before pull.
git fetch origin
dirty=$(git status --porcelain)
ahead=$(git log origin/main..HEAD)
if [ -n "$dirty" ] || [ -n "$ahead" ]; then
  echo "WARNING: refusing to sync; Hawaii checkout is dirty or has commits not on origin/main." >&2
  echo "Checkout: /data/yunji/latent-planner-work/src/latent-planner" >&2
  echo "git status --porcelain:" >&2
  if [ -n "$dirty" ]; then
    printf '%s\n' "$dirty" >&2
  else
    echo "(empty)" >&2
  fi
  echo "git log origin/main..HEAD:" >&2
  if [ -n "$ahead" ]; then
    printf '%s\n' "$ahead" >&2
  else
    echo "(no commits)" >&2
  fi
  exit 1
fi
git pull
git submodule update --init --recursive
mkdir -p /data/yunji/latent-planner-work/logs
{
  printf 'latent-planner %s\n' "$(git rev-parse HEAD)"
  printf 'RPent %s\n' "$(git -C RPent rev-parse HEAD)"
  printf 'AgenticRoboRL %s\n' "$(git -C AgenticRoboRL rev-parse HEAD)"
} > /data/yunji/latent-planner-work/logs/code_version.txt
