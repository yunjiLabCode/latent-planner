#!/bin/sh
# Pull the workspace checkout on Hawaii and record the commits that were pulled.
# Does not commit, push, or reset.
set -eu
cd /data/yunji/latent-planner-work/src/latent-planner
git pull
git submodule update --init --recursive
mkdir -p /data/yunji/latent-planner-work/logs
{
  printf 'latent-planner %s\n' "$(git rev-parse HEAD)"
  printf 'RPent %s\n' "$(git -C RPent rev-parse HEAD)"
} > /data/yunji/latent-planner-work/logs/code_version.txt
