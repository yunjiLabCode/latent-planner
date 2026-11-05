# 루트 디스크 조사 (2026-11-02)

지우거나 옮기지 않았다. sudo를 쓰지 않았고, yunji 소유가 아닌 파일은 읽기만 했다. 원본 로그는 Hawaii의 `/data/yunji/latent-planner-work/logs/disk_cleanup_plan.md`이다.

## 1. 마운트

`df -h /` 기준 루트(`/dev/nvme0n1p3`)는 903G 사용, 남은 공간 20KB, 100%다.

| 마운트 | 여유 | 비고 |
| --- | --- | --- |
| `/data` | 2.1T | 작업 디스크 |
| `/data_2` | 1.7T | 여유 있는 큰 디스크 |
| `/mnt` | 비어 있음 | |
| `/tmp` | 16G tmpfs | RAM 디스크 |

## 2. yunji가 루트에서 쓰는 용량

루트에서 yunji 소유는 약 4.8G이고, 거의 전부 `/home/yunji/.cursor-server` 4.7G다.

- `~/.local`은 5.0M. wandb 11G는 이미 `/data/yunji/home_backup/wandb`에 있다. 백업 디렉터리 mtime은 2026-11-02 03:08 KST.
- `/home/yunji/latent-planner` 체크아웃은 비어 있다.
- `/tmp`에서 yunji 소유 합계는 19,391,886바이트다. tmpfs라 루트 디스크를 차지하지 않는다.
- 실험 outputs 874M, logs 16M, LIBERO 데이터, conda env는 이미 `/data`에 있다.

`du`로 보이는 `/`는 약 492G이고 `df` 사용량은 약 902G다. 차이는 읽을 수 없는 경로(docker, 다른 사용자 개인 디렉터리)다. 다른 사용자 홈은 우리 것이 아니다.

## 3. 지난 정리 이후 커진 것

wandb를 `/data`로 옮긴 뒤에도 루트가 다시 가득 찼다. 지금도 커지고 있는 파일은 아래 둘이고, 소유자는 `syslog:adm`이다. yunji 소유가 아니다.

- `/var/log/syslog` 27,429,826,560바이트. mtime 2026-11-02 20:34 KST.
- `/var/log/kern.log` 27,278,934,016바이트. mtime 2026-11-02 20:34 KST.
- 2026-10-25 회전본이 각각 약 1.1G.

Cursor 서버 4.7G는 루트에 있지만, 이 두 로그가 루트를 다시 채운 원인이다.

## 4. 분류

### 남겨야 함

- 지금 쓰는 HF 가중치. 모두 `/data/yunji/latent-planner-work/cache/hf` 아래.
  - pi0.5 blob 7,473,091,464바이트
  - AgenticRoboRL Qwen 9B 18,819,722,392바이트
  - SAM3 `sam3.pt` 3,450,062,241바이트
- 실험 outputs, logs, wandb 백업, LIBERO 데이터, conda env. 이미 `/data`에 있다. 지우지 않는다. 옮길 필요도 없다.
- `/data/yunji/smolvla_runs` 15G가 있는 동안 OpenVLA 15G hub, transformers 사본 15G, SmolVLM/SmolVLA 캐시도 지우지 않는다. 이 스택(pi0.5, Qwen 9B, SAM3)은 아니지만 다른 실험이 쓴다. 이미 `/data`에 있어 루트를 비우지 못한다.

### 지워도 루트는 늘지 않음

아래는 지워도 다시 받을 수 있는 캐시지만, 이미 `/data`에 있어서 루트 여유와 무관하다.

- pip 캐시 7.2G
- conda pkgs 캐시 약 1.1G
- vLLM torch compile 캐시 777M
- Triton, CUDA, Torch, Inductor, `VLLM_CACHE_ROOT` 디렉터리는 비어 있다.
- conda env 자체는 남긴다.

### 옮겨야 함

- `/home/yunji/.cursor-server`의 옛 버전만. 지금 쓰는 버전은 `2026.10.22-27dcf5f`다. 이 에이전트가 끝난 뒤에 옮긴다. 지치지 않는다. 기껏해야 약 4.7G이고, 루트 전체를 해결하지 못한다.
- `/var/log/syslog`와 `/var/log/kern.log`가 실제 원인이다. yunji 소유가 아니라 여기서 지우거나 옮기지 않는다.

## 5. 다시 안 차게 할 경로

적용하지 않았다. Hawaii `env.sh`는 이미 아래를 `/data`로 두고 있다.

- `HF_HOME`, `XDG_CACHE_HOME`, `PIP_CACHE_DIR`, `TMPDIR`, `CONDA_PKGS_DIRS`는 `/data/yunji/latent-planner-work/cache` 또는 `tmp` 아래.
- 실험 run 디렉터리는 `/data/yunji/latent-planner-work/outputs/<run_id>`.

루트를 비우는 조치는 관리자가 syslog와 kern.log를 다루는 일이다. yunji 파일만 지워서는 116KB 상태를 풀 수 없다.
