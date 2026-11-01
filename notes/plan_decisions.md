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

대안: RPent flash replay가 기록된 primitive 명령을 다시 실행한다. 같은 초기 상태에서 k번째까지 재생하면 실패 상태에 다시 도달할 수 있다. 관건은 VLA 샘플링 시드를 고정했을 때 결정론이 보장되는지다. 이 결정론은 아직 보지 않았다. 다음 수집 전에 확인할 항목으로 둔다.

## 4. 훅보다 기존 로그 변환이 먼저

proxy는 쓰지 않는다. 평가 경로(`eval.direct`)에서는 안 켜지고, 켜지면 샘플링을 RL용으로 덮어써서 teacher 수집에 맞지 않는다.

이미 있는 파일:

- `transcript_*.json`: api planner의 전체 대화
- `states.json`: primitive의 command, result, terminated, 소요 시간
- 스텝 폴더: `agentview.png`, `wrist.png`, depth, 메타데이터

결정: teacher를 돌린 뒤 이 파일들을 우리 스키마로 변환하는 스크립트를 먼저 만든다. collect 브랜치에서는 기본 동작이 같은 최소 수정만 한다. 영상 출력 경로를 `RPENT_PRIMITIVE_VIDEO_DIR`로 바꾼 것이 그 예다. 빠지는 것은 결정당 지연 시간과 `sim_state`다.

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

## 8. TITAN RTX TP=2 vLLM은 custom allreduce와 P2P를 끈다

2026-10-29.

13:22 EngineCore `sample_tokens` 행은 이 기계의 P2P/custom allreduce로 의심한다. TITAN RTX에서 TP=2 vLLM은 `--disable-custom-all-reduce`와 `NCCL_P2P_DISABLE=1`을 쓴다. `NCCL_DEBUG=WARN`은 자기 로그로 간다. pi0.5 dtype은 바꾸지 않는다.

결정: 다음 수집의 vLLM만 이 플래그와 환경 변수를 쓴다. pi0.5는 bf16 그대로다.

2026-10-29 20:33 KST 확인. `batch01-goal-retry2`는 건드리지 않았다.

- 감시와 자동 재시작은 켜져 있다. 실행 중인 `scripts/collect_batch.sh`(pid 2433427)가 `VLLM_HEALTH_S=30`, `VLLM_STALL_S=300`으로 `watch_vllm`을 돈다. 죽거나 5분 동안 토큰이 없으면 vLLM을 다시 띄운다.
- 재시작 기록 경로는 `/data/yunji/latent-planner-work/logs/vllm_restarts.log`다. 아직 파일이 없다. 재시작이 한 번도 없었다.
- `nvidia-smi topo -m`에서 GPU0–GPU1은 `NODE`다. NVLink(`NV#`)가 아니고, 같은 NUMA 안에서 PCIe와 Host Bridge를 거친다. GPU1–GPU0도 `NODE`다.

## 9. 다음 수집은 TP=2를 유지한다 (제안)

2026-10-30. 근거는 `notes/batch01_results.md` 6절. 실행하지 않았다.

GPU 0 한 장, TP=1, `--dtype half`, util 0.90, max-model-len 262144에서 엔진이 뜨지 않았다. 가중치 17.66 GiB, available KV 0.02 GiB, 262144 길이 하나에 8.1 GiB. 65k(64,685) 하나에도 약 2.0 GiB가 필요해서 동시 개수는 0이다. GPU 0과 1에 TP=1 서버를 하나씩 두고 워커를 나누는 구성은 65k 에피소드를 담지 못한다.

retry2의 긴 턴은 출력 토큰당 중앙 0.108초다. 같은 기계의 스모크(단일 에피소드)는 0.026–0.044초였다. 약 2.5–4배이고, GPU가 달라서가 아니다. 4개 동시와 P2P를 끈 설정이 겹친 값이다. TP=2 util 0.85의 KV는 598,814토큰이라 65k를 산술상 9개까지 담는다.

제안:

- vLLM은 TP=2 한 대를 유지한다. GPU 0·1. `--disable-custom-all-reduce`와 `NCCL_P2P_DISABLE=1`은 8절 그대로다.
- 동시 실행은 4가 아니라 2로 줄인다. KV는 4도 들어가지만, 토큰당 시간이 스모크의 2.5배 안에 머물게 하려는 쪽이다.
- planner timeout은 7200초에서 18000초로 올린다. 2.5배이고, 스모크의 느린 끝(0.044초) 대비 중앙값 0.108초의 비율이다. 4배(28800초)까지는 올리지 않는다.
- pi0.5는 bf16 그대로다. GPU 2. GPU 3은 쓰지 않는다.

## 10. timeout transcript는 대화를 남기고 이유를 적는다

2026-11-01. collect `8852591`. `5960405`가 메시지 목록을 공유하게 했고, 이 커밋이 끝난 이유를 붙인다. 자세한 경로는 `notes/batch01_results.md` 10절.

대화를 잃지 않는 방법은 두 가지였다.

- 턴마다 transcript 파일을 다시 쓴다. 프로세스가 죽어도 파일에 대화가 남지만, 매 턴 저장이 더 크다.
- `solve()`가 목록을 만들어 `_solve`에 넘기고, 벽시계 `TimeoutError`여도 그 목록을 반환한다. 취소는 await 경계에서만 일어나서, 목록에는 그때까지 붙은 완전한 메시지만 있다. `ModelTimeoutError`는 원래 그 목록으로 돌아온다.

더 작은 쪽인 두 번째를 썼다. `finish_result`, `stats`, error 문자열은 그대로다. 목록을 안 넘기면 `_solve`가 직접 만든다. interactive와 dashboard의 정상 경로는 그대로다.

벽시계 timeout의 `terminated_by`는 `planner_timeout`이다. `ModelTimeoutError`는 `model_timeout`이다. 정상 종료는 이 키가 없다. `main()`은 값이 있을 때만 transcript JSON에 넣는다.

변환기는 tool 호출이 있으면 `transcript_missing`으로 두지 않는다. 어긋남이 마지막 결정 하나뿐이면 그 앞까지를 맞춘 것으로 남긴다. 가운데가 어긋나거나 두 개 이상 남으면 예전처럼 `matched`가 false다.

## 11. 변환기 v0.3은 구현됐다

2026-10-30. 커밋 `4425e98`. Hawaii에서는 돌리지 않았다. 테스트 24개 통과.

- transcript에 tool 호출이 없으면 `states.json`만으로 decisions를 만든다. `teacher_text`와 `context_calls`는 비우고 `transcript_missing: true`를 둔다.
- `failure_kind`는 `success`, `agent_error`, `budget_timeout`, `infrastructure` 중 하나다.
- `pi0_pick`이 success false이고 같은 prompt로 다시 집지 않으며 에피소드가 `terminated` true로 끝나면 `primitive_success`는 None이고, `labels.success_overridden`은 `terminal_success`다.

시간 제한으로 끝난 retry2 4개는 `budget_timeout`으로 둔다. 코드의 분류 적용은 이 변환기에 들어 있다.
