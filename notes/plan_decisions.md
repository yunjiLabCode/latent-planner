# 계획을 바꾸는 발견

2026-10-28. 분석 근거는 `notes/rpent_analysis.md`, `notes/agenticroborl_analysis.md`.

## 1. Teacher 수집은 f70d720 + 패치 위

우리 RPent는 `a744bd5`다. AgenticRoboRL 9B는 `f70d720`에 `patches/rpent/rpent_f70d720.patch`를 적용한 RPent에서 학습됐다. `--knowledge-profile`, `--no-send-back-thinking`, 샘플링 플래그가 우리 버전에는 없고, 프롬프트와 도구 구성도 다를 수 있다. 9B를 다른 harness에 붙이면 성능이 떨어질 가능성이 크다.

결정: teacher 수집은 `f70d720` + 패치 위에서 한다. 보고된 71% 재현도 이 조합이다.

## 2. 스키마는 pi0_pick / pi0_doubled / move_to에 맞춘다

LIBERO에는 `vla_act`와 `stop` 인자가 없다.

| primitive | 성공 신호 |
| --- | --- |
| `pi0_pick` | 하강·재상승·그리퍼 휴리스틱 → `success` |
| `pi0_doubled` | 환경 `terminated`만 반영. 중간 단계 `false`는 실패가 아님 |
| `move_to` | `success` 없음. `final_dist_m`만 |

결정: `decision`과 `outcome`을 이 구조에 맞추고, retry/recovery 판정은 primitive별로 정의한다.

## 3. sim_state API는 없고, flash replay가 대안

RPent 안에 중간 상태를 저장했다 되돌리는 코드는 없다. 시뮬레이터는 별도 프로세스의 RLinf `LiberoEnv`라, 그 기능 유무는 아직 확인되지 않았다. online 재라벨링은 여기에 달려 있다.

대안: RPent flash replay가 기록된 primitive 명령을 다시 실행한다. 같은 초기 상태에서 k번째까지 재생하면 실패 상태에 다시 도달할 수 있다. 관건은 VLA 샘플링 시드를 고정했을 때 결정론이 보장되는지다. 확인 필요.

## 4. 훅보다 기존 로그 변환이 먼저

proxy는 쓰지 않는다. 평가 경로(`eval.direct`)에서는 안 켜지고, 켜지면 샘플링을 RL용으로 덮어써서 teacher 수집에 맞지 않는다.

이미 있는 파일:

- `transcript_*.json`: api planner의 전체 대화
- `states.json`: primitive의 command, result, terminated, 소요 시간
- 스텝 폴더: `agentview.png`, `wrist.png`, depth, 메타데이터

결정: teacher를 돌린 뒤 이 파일들을 우리 스키마로 변환하는 스크립트를 먼저 만든다. 원본 RPent는 수정하지 않는다. 빠지는 것은 결정당 지연 시간과 `sim_state`다.

## 5. 수집은 pi0.5 bf16을 유지한다

2026-10-28. 측정은 `notes/pi05_fp16_check.md`에 둔다.

pi0.5 predict는 bf16 평균 0.84초, fp16 래퍼는 0.34초다. 병목은 플래너일 가능성이 커서 이 VLA 간격이 수집 시간에 크게 작용하지 않을 수 있다. fp16 래퍼는 RPent를 바꾸고 frozen-VLA와 충돌한다. HarnessVLA와 AgenticRoboRL 수치는 bf16이다. action 차이는 0.87%라 폐루프에서 쌓일 수 있다.

결정: 수집 dtype은 bf16으로 둔다. fp16 래퍼는 쓰지 않는다. 단계 5에서 VLA가 에피소드 시간의 대부분임이 보일 때만 다시 본다.

## 6. 실행 결정만 대체하면 가속이 작다

2026-10-29. 근거는 `notes/smoke_episode_01.md`.

플래너 턴 36개 중 실행 결정은 10개, 쿼리는 32개였다. 쿼리는 `segment`, `view_env_state`, `back_project` 같은 호출이다.

결정: 실행 결정만 바꾸는 latent planner의 가속은 제한적이다. 쿼리 동작, 특히 실패 감지로 쓰이는 `view_env_state`는 observation 입력과 decoder가 흡수해야 한다. part 2를 설계할 때 다시 본다.

## 7. libero_10_task task 2는 수집과 평가에서 뺀다

2026-10-29. 근거는 `notes/batch01_env_failures.md`.

`libero_10_task` task 2 (`KITCHEN_SCENE3_turn_on_the_stove_and_put_the_moka_pot_on_it`)의 `.pruned_init`은 364바이트이고 `torch.load` 결과가 shape `(0,)`이다. 로컬 휠, `RLinf/LIBERO-PRO` master, 같은 저장소 `rpent` 브랜치가 바이트 단위로 같다 (sha256 `031ef7f9af0e3d30cdae0c2bc57c4032bedbbda045ea4f2707f6ab1601320e48`). `liberopro-download-assets`가 만든 파일이 아니다. `tasks.jsonl` train 목록(init 11–44)에는 들어 있다.

결정: 빈 init의 대체 파일을 찾기 전까지 수집 목록에서 이 태스크만 제외한다. suite 전체는 빼지 않는다. 평가(init 1–10)에서도 같은 태스크를 제외한다. init 파일이 모든 소스에서 비어 있으므로 baseline도 이 태스크를 실행하지 못했을 가능성이 크다. 비교에서는 양쪽 모두 이 태스크를 제외한다.
