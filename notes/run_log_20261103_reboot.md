# 재부팅 (2026-11-03)

flash replay 결과는 유효하다. 다시 돌리지 않는다. 이 노트는 서버를 시작하지 않는다.

## flash replay

시작은 2026-11-03T16:38:48+09:00이다. 실행은 16:47 KST 전에 끝났다. 워커 보고가 16:47 KST에 도착했다. 끝 상태는 `dimm_ce_count` 0, `kern.log` 5001바이트다. 전원 재시작은 17:31 KST라서 flash가 끝난 뒤다.

상세는 `notes/run_log_20261103_flash.md`이다. 출력은 `/data/yunji/latent-planner-work/outputs/flash_replay_20261103/unseeded_a`와 `unseeded_b`다.

## 재부팅으로 내려간 것

이 로그인의 백그라운드가 같이 내려갔다.

- tmux 세션. `agent-worker`는 없었다.
- vLLM
- pi0.5
- SAM3
- env 서버
- 그 로그인에 있던 다른 백그라운드 작업

## 다시 올려야 하는 것

수집을 이어서 할 때 다시 띄울 것은 vLLM, pi0.5, SAM3, env 서버, 그리고 그것을 붙잡고 있을 tmux다. GPU 3은 쓰지 않는다. vLLM은 GPU 0과 1, TP=2, `--disable-custom-all-reduce`, `NCCL_P2P_DISABLE=1`이다. pi0.5, SAM3, EGL은 GPU 2다.

새 serve 플래그는 없다. 아래는 `scripts/collect_batch.sh`, Hawaii `env.sh`에 대해 `notes/install_log.md`가 적은 내용, 그리고 그 설치 로그의 실행 명령만이다. `agent-worker`를 대신하는 별도 명령은 이 파일들에 없다.

`CUDA_VISIBLE_DEVICES`는 `env.sh`에 넣지 않는다. 설치 로그에서 `env.sh`는 `HF_HOME`, `HF_HUB_CACHE`, `TRANSFORMERS_CACHE`, `PIP_CACHE_DIR`, `UV_CACHE_DIR`, `CONDA_PKGS_DIRS`, `TMPDIR`, `XDG_CACHE_HOME`, `TORCH_HOME`을 `/data/yunji/latent-planner-work` 아래로 내보낸다. `CUDA_VISIBLE_DEVICES`는 주석만이다. 같은 로그에 적어 둔 추가 줄은 다음이다.

```
export TRITON_CACHE_DIR=/data/yunji/latent-planner-work/cache/triton
export CUDA_CACHE_PATH=/data/yunji/latent-planner-work/cache/cuda
export VLLM_CACHE_ROOT=/data/yunji/latent-planner-work/cache/vllm
export TORCHINDUCTOR_CACHE_DIR=/data/yunji/latent-planner-work/cache/torchinductor
export RPENT_PRIMITIVE_VIDEO_DIR=/data/yunji/latent-planner-work/outputs/primitive_videos
```

2026-11-03 기록에는 `RPENT_DIR`과 `RPENT_ENV`가 `env.sh`에 없고, 실행 명령에서 `/data` 아래로 지정했다. `scripts/collect_batch.sh`는 `$ROOT/env.sh`를 읽은 뒤 `RPENT_DIR`, `RPENT_ENV`, `PLANNER_ENV`, `PI05_CHECKPOINT`, `SAM3_CHECKPOINT`, `PLANNER_WEIGHTS`가 비어 있으면 끝낸다. `RPENT_ENV`는 설치 로그의 `/data/yunji/latent-planner-work/envs/rpent`이다. 이 노트는 그 값들의 새 경로를 만들지 않는다. 스크립트는 이어서 `HOME`을 `/data/yunji/latent-planner-work/tmp/install-home`으로 둔다.

띄우는 방법은 스크립트 주석 그대로다. 이 스크립트가 vLLM, pi0.5, SAM3를 띄운다. 각 에피소드의 env 서버는 rpent가 띄운다.

```bash
tmux new-session -s batch01
ROOT=/data/yunji/latent-planner-work bash scripts/collect_batch.sh
```

vLLM은 그 스크립트의 `start_vllm`이다. `MODEL_PORT` 기본값은 18100이다. GPU 0, 1만 쓴다. 이 프로세스만 `NCCL_P2P_DISABLE=1`, `NCCL_DEBUG=WARN`이고, NCCL 로그는 `$ROOT/logs/nccl_vllm.log`다.

```bash
CUDA_VISIBLE_DEVICES=0,1 \
NCCL_P2P_DISABLE=1 \
NCCL_DEBUG=WARN \
NCCL_DEBUG_FILE="$ROOT/logs/nccl_vllm.log" \
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
  --reasoning-parser qwen3
```

pi0.5는 같은 스크립트의 `start_server pi05`다. `VLA_PORT` 기본값은 18300이다. 체크포인트는 bf16 그대로다. fp16 래퍼는 없고 `--parent-watch`도 없다. GPU 2다.

```bash
CUDA_VISIBLE_DEVICES=2 PI05_CHECKPOINT_PATH="$PI05_CHECKPOINT" \
  "$RPENT_ENV/bin/python" -m rpent.robots.components.pi05_vla_server \
  --transport http --host 127.0.0.1 --port "$VLA_PORT" --cuda-device 2
```

SAM3는 `start_server sam3`다. `SAM3_PORT` 기본값은 18400이다. GPU 2다.

```bash
CUDA_VISIBLE_DEVICES=2 SAM3_CHECKPOINT_PATH="$SAM3_CHECKPOINT" \
  "$RPENT_ENV/bin/python" -m rpent.robots.components.sam3_server \
  --transport http --host 127.0.0.1 --port "$SAM3_PORT" --cuda-device 2
```

env 서버를 `collect_batch.sh`가 따로 띄우지는 않는다. 에피소드 프로세스는 `CUDA_VISIBLE_DEVICES=2`, `MUJOCO_EGL_DEVICE_ID=2`, `MUJOCO_GL=egl`, `PYOPENGL_PLATFORM=egl`을 물려받고 `--cuda-device 2`를 넘긴다. env 서버는 그 플래그에서 `CUDA_VISIBLE_DEVICES`를 지우고 EGL 핀은 유지한다.

설치 로그에서 env 서버만 확인하는 명령은 다음이다. vLLM, pi0.5, SAM3는 시작하지 않는다.

```bash
CUDA_VISIBLE_DEVICES=2 MUJOCO_EGL_DEVICE_ID=2 \
  ROOT=/data/yunji/latent-planner-work \
  bash scripts/verify_env_suites.sh
```
