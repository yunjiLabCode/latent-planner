# Hawaii 설치 로그

## 단계 1 — 경로와 환경 변수 (2026-10-28)

완료. 단계 2는 시작하지 않음. GPU는 사용하지 않음.

### 만든 것

`/data/yunji/latent-planner-work/` 아래 `cache/hf`, `cache/pip`, `cache/uv`, `cache/conda`, `cache/xdg`, `cache/torch`, `tmp`, `outputs`, `envs`, `src`, `logs`.

`env.sh`가 `HF_HOME`, `HF_HUB_CACHE`, `TRANSFORMERS_CACHE`, `PIP_CACHE_DIR`, `UV_CACHE_DIR`, `CONDA_PKGS_DIRS`, `TMPDIR`, `XDG_CACHE_HOME`, `TORCH_HOME`을 이 디렉터리 아래로 내보낸다. `CUDA_VISIBLE_DEVICES`는 주석만 있다.

### RPent 체크아웃

Hawaii에 `agrl-f70d720`이 없다. `yunjiLabCode/RPent` clone은 GitHub 인증이 없어 실패했다. `src/`는 비어 있다. 클라우드 체크아웃은 `/workspace/RPent`, 브랜치 `agrl-f70d720`, 커밋 `3984a4e`.

아래 3–5는 Hawaii의 다른 트리 `/data/crestlux/rpent_project/rpent`(origin `RLinf/RPent`, `main` `38a4f4b`)에서 본 것이다. `agrl-f70d720`에서의 확인은 아직이다.

### 출력 디렉터리

`--output-dir` (`rpent/cli/main.py`). 생략하면 `<repo>/logs/<timestamp>_<suite>_t<task>_s<seed>`. 수집 때는 `/data/yunji/latent-planner-work/outputs`를 넘겨야 한다. 확인 필요: `agrl-f70d720`에서 같은 플래그인지.

### `/tmp/primitive_videos`

`robots/libero/env_server.py` `build_env_cfg`의 하드코딩 문자열이다. `TMPDIR`을 따르지 않고, 환경 변수로 바꿀 수 없다. 코드를 고치지 않고 돌리는 방법은 `/tmp/primitive_videos` → `/data/yunji/latent-planner-work/outputs/primitive_videos` 심볼릭 링크다. `/tmp`에 쓰는 일이라 아직 만들지 않았다. 확인 필요: `agrl-f70d720`도 같은 상수인지.

### RPent-memory

`rpent/utils/resources.py`의 `ensure_resources`. 기본 저장소는 `RLinf/RPent-memory` (`RPENT_RESOURCES_HF_REPO`). `snapshot_download`는 `cache_dir` 없이 `local_dir=<repo>/resources`다. 풀린 파일은 레포 안에 남는다. 허브 캐시만 `HF_HOME` / `HF_HUB_CACHE`를 탈 수 있다. 레포가 홈에 있으면 메모리 코퍼스가 루트 디스크로 간다. 확인 필요: `agrl-f70d720`.

## 출력 경로 — 이 체크아웃에서 확인 (2026-10-28)

확인한 트리: `/workspace/RPent`, 브랜치 `collect`, 커밋 `50717fadc3ba472c7b6d94dd413acb4847d1cfec`.
`3984a4ebb70e13ba71ce27e618f86ccd1dafc095` (`agrl-f70d720`)의 자손이고, 그 커밋과의 diff는 `robots/libero/env_server.py`의 `video_base_dir`뿐이다. 아래 출력 경로 코드는 두 커밋에서 같다. 프로세스는 실행하지 않았다. 소스에서 읽은 것과, 실행해 보지 않은 것을 나눈다.

### 확인함 (이 체크아웃 소스)

`rpent` 진입점은 `pyproject.toml`의 `rpent = rpent.cli.main:main`이다.

`--output-dir`은 `rpent/cli/main.py`에서 `default=None`으로만 등록된다. 이 플래그를 읽는 환경 변수는 없다.

대시보드가 아닐 때 `main()`은 `robot_spec.parse_config(args)`가 고른 경로를 `init_output_dir`에 넘긴다.

LIBERO `robots/libero/robot_spec.py` `_parse_config`:

- `args.output_dir`가 None이면 `get_repo_root() / "logs" / f"{timestamp}_{suite}_t{task}_s{seed}"`. timestamp는 `datetime.now().strftime("%Y%m%d-%H:%M:%S")`.
- 값이 있으면 `Path(args.output_dir)`를 그대로 실행 디렉터리로 쓴다. timestamp 자식을 붙이지 않고, 여기서 `.resolve()`도 하지 않는다.
- `get_repo_root()` (`rpent/utils/config.py`): `RPENT_REPO_ROOT`가 있으면 expanduser 후 resolve. 없으면 `rpent/utils/config.py` 기준 상위 두 단계, 즉 RPent 저장소 루트.

`init_output_dir` (`rpent/utils/logging.py`):

- 인자가 None이면 `<repo>/logs`. LIBERO `_parse_config`는 항상 Path를 넘기므로, 일반 `rpent --robot libero` 경로에서는 이 분기를 타지 않는다.
- `mkdir(parents=True, exist_ok=True)`. 디렉터리가 이미 비어 있지 않으면 stderr에 경고.
- `<output_dir>/run.log`를 연다. `.resolve()`는 하지 않는다. 상대 `--output-dir`는 프로세스 cwd 기준이다.

같은 디렉터리에 `main()`이 `transcript_{recipe_tag}.json`을 쓴다. `recipe_tag`는 `{suite에서 libero_를 뺀 이름}_t{task}_s{seed}`. `--explore`이면 툴킷 상태는 `{output_dir}/sessions/session_{번호}`이고, transcript는 부모 `output_dir`에 남는다.

`--dashboard`는 `parse_config` 전에 `rpent/cli/dashboard.py` `run_dashboard_session`으로 빠진다.

- None이면 `<repo>/logs/{timestamp}_dashboard_session`.
- 값이 있으면 그 경로가 세션 루트다.
- 각 task는 `{session_root}/tasks/{번호 4자리}_{slug}` (`rpent/dashboard/state.py` `wait_for_task`)이고, 그 경로를 `task_args.output_dir`에 넣은 뒤 `parse_config`를 호출한다. 대시보드 task는 LIBERO timestamp 기본 경로를 쓰지 않는다.

`rpent/` 안에 output dir용 환경 변수는 없다. `RPENT_REPO_ROOT`는 기본 `logs/`의 부모만 옮긴다.

primitive 영상은 `--output-dir` 밖이다. `collect` `50717fa`의 `robots/libero/env_server.py` `video_base_dir`는 `os.environ.get("RPENT_PRIMITIVE_VIDEO_DIR", "/tmp/primitive_videos")`다. `os` import는 원래 있었다.

### 추론 (실행하지 않음)

`--output-dir /data/yunji/latent-planner-work/outputs`를 넘기면 timestamp 자식이 생기지 않고, 그 디렉터리에 `run.log`와 transcript가 직접 쓰인다. 이미 파일이 있으면 경고가 난다. 실행마다 디렉터리를 나누려면 그 하위 경로를 플래그 값에 넣어야 한다.

수집 로그를 레포 `logs/`에 두지 않으려면 `--output-dir`에 `/data/yunji/latent-planner-work/outputs/` 아래 절대 경로를 넘겨야 한다.

### Hawaii env.sh에 넣을 줄

sync 뒤에 Hawaii의 `env.sh`에 아래 한 줄을 추가한다. 이 작업 공간에서는 Hawaii 파일을 고치지 않았다.

```
RPENT_PRIMITIVE_VIDEO_DIR=/data/yunji/latent-planner-work/outputs/primitive_videos
```

- env.sh의 모든 변수는 export로 선언한다. 빠진 줄은 `export RPENT_PRIMITIVE_VIDEO_DIR=/data/yunji/latent-planner-work/outputs/primitive_videos`
- --output-dir는 에피소드마다 고유 경로 outputs/{run_id}/{suite}/task_{task:02d}/seed_{seed:03d}/attempt_{attempt:02d}/ 를 넘긴다. 같은 폴더를 재사용하면 결과가 섞인다.

## GPU — CUDA_VISIBLE_DEVICES (2026-10-28)

`CUDA_VISIBLE_DEVICES`는 `env.sh`에 두지 않는다. vLLM은 GPU 0, 1을 쓰고, pi0.5와 SAM3는 GPU 2를 쓴다.

단계 2부터의 모든 실행 스크립트는 `CUDA_VISIBLE_DEVICES`가 비어 있거나 `3`을 포함하면 exit 1로 끝낸다.

단계 2 EGL 렌더 확인에서는 렌더링 중에 `nvidia-smi`를 실행하고, 프로세스가 어느 GPU에 있는지 기록한다. GPU 3이면 `MUJOCO_EGL_DEVICE_ID`를 바꿔 프로세스가 GPU 2에 있을 때까지 반복한다.

단계 2는 시작하지 않음.

## 단계 2 — 환경과 EGL 렌더 (2026-10-28)

완료. 단계 3은 시작하지 않음. Hawaii 파일은 고치지 않았다.

### 환경

`RPENT_ENV`는 `/data/yunji/latent-planner-work/envs/rpent`이다. torch는 `2.7.1+cu128`.

에셋은 `/data` HF 캐시 아래에 있다.

환경 서버가 import하므로 두 패키지를 추가했다. collect의 `libero-pro` extra에는 없다.

- `omegaconf==2.3.1`. `pip install 'omegaconf>=2.3,<2.4'`라서 `--no-deps`가 아니다. `antlr4-python3-runtime==4.9.3`도 같이 설치됐다.
- `rpent-rlinf==0.3.0`만 `pip install --no-deps`다. `ray`, `wandb`, `liger`는 freeze에 없다.

freeze: `notes/env/rpent_env_freeze.txt`. Hawaii 원본은 `/data/yunji/latent-planner-work/logs/rpent_env_freeze.txt` (2026-10-28T16:27:15+09:00).

### GPU 2 bf16 (단계 3 전)

`CUDA_VISIBLE_DEVICES=2`. TITAN RTX, `get_device_capability()` `(7, 5)`. `get_arch_list()`에 `sm_75`가 있다.

`is_bf16_supported()` 기본값은 `True`(에뮬레이션 포함). `including_emulation=False`는 `False`라서 하드웨어 bf16은 없다. 1024 matmul은 bf16 0.412 ms, fp16 0.041 ms, 비율 약 9.97이다. torch `2.7.1+cu128`.

### EGL 렌더

렌더는 `MUJOCO_EGL_DEVICE_ID=2`와 `CUDA_VISIBLE_DEVICES=2`를 썼다. `nvidia-smi`에서 python은 GPU 2에만 있었다.

이미지: `/data/yunji/latent-planner-work/outputs/libero_pro_reset.png`.

`/tmp/primitive_videos`는 없다. 새 primitive 영상도 없다. `~/.libero`와 `~/.liberopro`도 없다.

전체 실행 로그: `/data/yunji/latent-planner-work/logs/install_log.md`.
