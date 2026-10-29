# batch01 env 기동 실패 (2026-10-29)

goal 5개, tmux `batch01`, vLLM, π0.5, SAM3는 건드리지 않았다. GPU 2가 이미 약 15 GiB라 추가 env 서버는 띄우지 않았고, GPU 3은 쓰지 않았다. 설치와 코드 수정은 하지 않았다.

Hawaii 원문: `/data/yunji/latent-planner-work/logs/batch01_env_failures.md`

## 1. ZeroDivisionError — libero_10_task task 2

`env_server.py`의 `make_env`는 `seed % len(get_task_init_states(task_id))`를 한다. task index 2는 `KITCHEN_SCENE3_turn_on_the_stove_and_put_the_moka_pot_on_it`이다.

- 파일은 있다: `init_files/libero_10_task/...pruned_init` (364 bytes)
- `torch.load` 결과는 ndarray shape `(0,)`이라 `len`이 0이고 나눗셈이 실패한다
- 같은 폴더의 다른 9개 태스크는 길이 50
- `tasks.jsonl`의 suite 이름 `libero_10_task`는 benchmark 클래스, `bddl_files/`, `init_files/`와 맞다. BDDL도 있다
- 빈 텐서가 원인이고, suite 문자열이 틀린 것은 아니다
- 같은 나눗셈은 RPent `f70d720`에도 있다

`attempt_00`과 `attempt_01` 모두 같은 오류다.

## 2. TypeError — object task 0·1, libero_10 task 0·1

로그의 예외는 `TypeError: 'str' object is not callable`이다. 해당 env 로그:

- `outputs/batch01/libero_object_task/task_00/seed_011/attempt_00/env_server.log`
- `outputs/batch01/libero_object_task/task_01/seed_011/attempt_00/env_server.log`
- `outputs/batch01/libero_10_task/task_00/seed_011/attempt_00/env_server.log`
- `outputs/batch01/libero_10_task/task_01/seed_011/attempt_00/env_server.log`

호출 지점은 설치된 robosuite `models/bases/robot_base_factory.py` 29행이다.

```python
BASE_MAPPING.get(name, "Unknown base name: {}".format(name))
```

이 반환값을 호출한다. `name`이 `None`이면 `.get`의 기본값이 문자열이고, 그 문자열을 호출해서 `TypeError`가 난다.

`None`은 `OnTheGroundPanda.default_base`다. floor와 living-room 문제는 로봇을 `OnTheGroundPanda`로 바꾼다. object task 0·1과 libero_10 task 0·1이 이 경우다. goal scene은 `MountedPanda`이고 `default_base`가 `"RethinkMount"`라 맵에 있어서 기동된다.

### 버전

| 패키지 | 설치본 | 요구 |
|---|---|---|
| robosuite | PyPI 1.5.2 | `rpent-liberopro` 0.2.0의 `robosuite>=1.5.2`. `f70d720` libero-pro extra와 같다 |
| rpent-rlinf | 0.3.0, `--no-deps` | robosuite에 의존하지 않음. ray, wandb, liger, torch-range 등을 건너뜀 |
| LIBERO-PRO | `rpent-liberopro` 0.2.0 | suite 이름과 파일 경로는 일치 |

RLinf의 robosuite git pin은 robocasa extra용이고, 이 env가 쓴 핀이 아니다. `--no-deps`는 이번 두 오류의 원인이 아니다.

## 3. 제안 (적용하지 않음)

1. 빈 `.pruned_init`을 `zhouxueyang/LIBERO-Pro` 원본으로 바꾼다. 기본 `libero_10` init을 복사하지 않는다.
2. `OnTheGroundPanda.default_base`가 `"NullMount"`를 반환하게 한다.

이미 돌아가는 goal 에피소드에는 둘 다 영향이 없다. goal은 `MountedPanda`를 쓰고, init 파일도 이미 로드했다.

`rpent-rlinf`를 `--no-deps` 없이 다시 설치하거나, torch, mujoco, robosuite 네이티브 라이브러리를 바꾸는 업그레이드는 살아있는 프로세스에 영향을 줄 수 있다. 그 변경으로 이 두 버그는 고쳐지지 않는다.

## 4. 기존 수정이 있는지 (2026-10-29, 적용하지 않음)

goal 배치와 서버는 건드리지 않았다. 패키지 설치, 패치 적용, 커밋은 하지 않았다.

### OnTheGroundPanda.default_base

로컬에는 수정이 없다.

- 설치된 `rpent-libero` 0.2.0과 `rpent-liberopro` 0.2.0 모두 `default_base`가 `None`을 반환한다. pro env는 liberopro 쪽 클래스를 쓴다.
- RPent `f70d720`과 AgenticRoboRL 전체에서 `OnTheGroundPanda`, `default_base`, `NullMount`, `BASE_MAPPING` 일치가 없다.
- `f70d720`은 SHA가 아니라 `rpent-libero>=0.2.0`, `rpent-liberopro>=0.2.0`을 지정한다. 설치된 휠이 그 0.2.0이다 (libero 2026-08-13, liberopro 2026-08-12 업로드). PyPI에 더 새 릴리스가 없어서 버전만 올려서는 수정이 들어오지 않는다.

GitHub `rpent` 브랜치에는 수정이 있다. 반환값은 `"NullMount"`가 아니라 `"NullBase"`다.

| 저장소 | rpent tip | 수정 커밋 | 날짜 |
|---|---|---|---|
| RLinf/LIBERO | `a8323074d93a09e32bd898630a70531b1f51bc77` | `0333053e0f904fb96c592737f9426a2a2579b0bc` | 2026-09-08 |
| RLinf/LIBERO-PRO | `d1e11fb181b8544487d27742c0caa3a4d46452ad` | `730f5628cacd06f755075e27247ad28d5a099433` | 2026-09-07 |

두 수정의 blob은 같다 (`f1b5a272a464e17e99d8c829cbb8e02b79dfd2d6`). 이 커밋들은 2026-08-12 배포 커밋 이후의 유일한 변경이다. 두 저장소의 master에는 이 1.5 수정이 없다.

설치된 robosuite 1.5.2의 `BASE_MAPPING`에는 `"NullMount"`와 `"NullBase"`가 둘 다 있다. fork에 맞출 값은 `"NullBase"`다.

### 빈 init 파일

`libero_10_task/KITCHEN_SCENE3_turn_on_the_stove_and_put_the_moka_pot_on_it.pruned_init`은 휠 RECORD에 들어 있다. `liberopro-download-assets`가 쓴 파일이 아니다. 그 명령은 `RLinf/LIBERO-PRO-assets`를 symlink할 뿐이다.

로컬, LIBERO-PRO master, LIBERO-PRO `rpent`가 같다.

- 크기 364 bytes
- sha256 `031ef7f9af0e3d30cdae0c2bc57c4032bedbbda045ea4f2707f6ab1601320e48`
- git blob `78f8578b8c345ad679bf663067c6b1b4f00d5d24`

`harnesses/rpent_libero/tasks.jsonl` 63행은 `libero_10_task/2`를 train init 11–44, eval init 1–10, val init 45–49에 포함한다.

### 제안 (적용하지 않음)

goal env 서버가 끝난 뒤에만 한다.

1. 버전을 fork에 맞춘다. PyPI 버전 업으로는 안 된다. `rpent-libero`는 `a832307`, `rpent-liberopro`는 `d1e11fb`를 `--no-deps`로 설치한다. 반환값은 `"NullBase"`다.
2. 휠을 그대로 두려면 같은 한 줄을 두 패키지의 `on_the_ground_panda.py`에 적용한다. 자리만 잡아 둔다. `patches/env/onthegroundpanda_nullbase.patch`, 적용 스크립트 `scripts/apply_env_patches.sh`. 파일은 만들지 않았다.
3. `libero_10_task` task 2는 수집에서 뺀다. 이유는 `notes/plan_decisions.md` 7절. 대체 init을 찾기 전까지 suite의 다른 태스크는 유지한다.

1번의 git 재설치는 지금 돌아가는 goal 프로세스의 이미 로드된 코드에는 영향이 없고, 그 프로세스가 아직 패키지를 import하는 중이면 영향을 줄 수 있다. 배치가 끝난 뒤에 한다.

## 5. 0.2.0 휠과 rpent tip 비교 (2026-10-29)

설치하지 않았다. goal 배치와 서버는 건드리지 않았다.

`rpent-libero` 0.2.0과 `RLinf/LIBERO` `a832307`의 배포 파일 차이는 `libero/libero/envs/robots/on_the_ground_panda.py` 한 줄뿐이다. `return None`이 `return "NullBase"`가 된다. 나머지 배포 파일 467개는 같다. BDDL 135개, init 250개, `MountedPanda`, gripper, controller, `init_qpos`, `base_xpos_offset`이 같다. 커밋에만 있는 것은 `libero/configs/` Hydra YAML 30개다. 휠에는 빈 `configs/__init__.py`만 있다. 커밋에는 assets 트리가 없다. 휠 파일 중 커밋에 없는 것은 없다.

`rpent-liberopro` 0.2.0과 `RLinf/LIBERO-PRO` `d1e11fb`도 같은 한 줄이다. 자산이 아닌 배포 파일 1703개가 같다. BDDL 771개, init 848개. 휠에 없는 것은 같은 Hydra YAML 30개와 `hope_objects.py.backup`이다. `hope_objects.py` 본문은 같다. 커밋의 자산 864개(644,001,041 bytes)는 `MANIFEST.in` 때문에 휠에서 빠졌고, 설치된 HF 스냅샷 `e4b10c9adc5735c9c8776917527178e693ef10b3`과 바이트가 같다. 스냅샷에는 `.gitattributes`가 하나 더 있다. 자산 내용 차이는 없다.

배포 커밋에서 tip까지는 두 저장소 모두 커밋 2개, 파일 1개다 (LIBERO `ef63e6ee`→`a832307`, LIBERO-PRO `209f5cb`→`d1e11fb`). tip의 `pyproject.toml`과 `MANIFEST.in`은 0.2.0 배포 커밋과 같고 버전도 0.2.0이다. arena, object, region, problem, predicate, 성공/`terminated`, 카메라 배치 파일은 같다. 빈 `libero_10_task` moka-pot init도 그대로다.

추천: goal env 서버가 끝난 뒤, 설치된 `on_the_ground_panda.py` 두 파일에 한 줄 패치. pro import 경로는 liberopro다. 두 SHA를 pip으로 설치해도 추가되는 동작은 그 한 줄뿐이고, site-packages를 다시 쓰며 assets symlink가 빠질 수 있다. 지금은 설치하지 않는다. 결정은 goal 배치가 끝난 뒤에 한다.
