# batch01 vLLM 종료 (2026-10-29 13:22 KST)

`batch01-goal-retry`는 건드리지 않았다. 스크립트는 수정하지 않았다.

Hawaii 원문: `/data/yunji/latent-planner-work/logs/batch01_vllm_crash.md`

## 확인된 것

vLLM이 스스로 종료했다. 시각은 13:22:30–31.

- EngineCore pid 2364068이 RPC `sample_tokens`에서 타임아웃했다.
- 13:18:31부터 13:21:31까지 60초마다 `shm_broadcast` 경고가 있었다.
- 마지막 메트릭은 13:17:46, 0.0 tok/s, running 2, KV 19.2%다. 스케줄러도 `kv_cache_usage` 0.1916, running 2, waiting 0이다.
- API pid 2362777이 `EngineDeadError`를 남기고 HTTP 500 네 건을 반환한 뒤 EngineCore를 강제 종료했다.
- Worker_TP0은 parent exit를 기록했다. Worker_TP1은 그 시각에 아무것도 쓰지 않았다.
- vLLM 로그에 OOM, `Killed`, Xid, CUDA error, ENOSPC는 없다.

GPU 0·1 메모리는 13:15:41부터 13:19:43까지 19682 MiB이고, 13:27:35에도 그 값이다. 13:28:35에 10 MiB, 13:30:25에 7 MiB다. 13:20–13:26 샘플은 없다. 스크립트 간격이 60초다. 13:30까지 `nvidia-smi`가 숫자를 돌려줬으므로, 그 구간까지 GPU가 응답은 했다.

dmesg는 `Operation not permitted`다. journalctl은 이 사용자가 `adm`, `systemd-journal`에 없어 권한이 없다. `kern.log`, `syslog`, `/var/log/dmesg`는 `640 root:adm`이라 읽지 못했다. OOM killer 기록은 확인하지 못했다.

GPU 0·1에 다른 사용자 프로세스가 있었다는 이름은 없다. batch 로그는 합계 MiB만 있고, vllm.log는 자기 pid만 적는다. 프로세스 계정 디렉터리는 없다. 13:15–13:27 사이 메모리가 두 번째 할당으로 계단처럼 오르지도 않았다.

원래 실행은 tmux `batch01`이었다. 재실행은 tmux `batch01-goal-retry`이고, 로그는 `/data/yunji/latent-planner-work/logs/batch01_goal_retry.log`다.

## 추측

워커가 `sample_tokens` 안에서 멈춘 것으로 보인다. CUDA fault, deadlock, 드라이버 stall 중 무엇인지는 로그로 갈리지 않는다. 13:20–13:26에 `nvidia-smi` 샘플이 비어 있는 것은 드라이버 호출이 멈춘 경우와 맞다. 커널 OOM과 다른 사용자의 프로세스는 확인되지 않았다.

## 재실행이 같은 이유로 죽을 수 있는지

있다. `batch01-goal-retry`의 vLLM 설정은 기존과 같다. TP=2, dtype half, max-model-len 262144, gpu-memory-utilization 0.85, prefix caching. 로그는 18:52:13, pid 2423938에서 시작했다. health 확인과 자동 재시작은 없다. 이번 조사에서 그 프로세스는 바꾸지 않았다.

## 다음 배치용 스크립트 개선 (적용하지 않음)

`collect_batch`의 다음 버전만 바꾼다. 지금 도는 `batch01-goal-retry`에는 넣지 않는다.

- vLLM healthz를 주기적으로 본다. 죽으면 워커를 일시정지한다.
- vLLM을 다시 띄운 뒤 워커를 재개한다.
- 서버가 없는 동안의 실패는 인프라 재시도 1회를 소모하지 않는다.
- 그렇게 끊긴 에피소드는 `failure_kind=infrastructure`로 표시하고, 복구 통계와 성공률에서 뺀다.

## 에피소드 구분

복구 통계와 성공률에는 teacher가 끝까지 돈 에피소드만 넣는다. 아래는 프로세스 종료 기준이다. task 성공(`terminated`)은 완료본의 `states.json`을 따로 봐야 한다.

| 에피소드 | 구분 | 근거 |
|---|---|---|
| libero_object_task task 0, 1 | 인프라 | env 기동 `TypeError`. planner 이전 |
| libero_10_task task 0, 1 | 인프라 | 같은 `TypeError` |
| libero_10_task task 2 | 인프라 | 빈 init, `ZeroDivisionError`. 수집·평가에서 제외 |
| libero_goal_task task 1 | teacher 실행 | rc=0, 22턴, 13:04 종료. vLLM 사망 전 |
| libero_goal_swap task 0 | 인프라 | 12턴에서 `ModelServerError` 500. 재시도 없음 |
| libero_goal_task task 0 | 인프라 | 22턴에서 `ModelConnectionError`, 재시도도 연결 실패 |
| libero_goal_task task 2 | 인프라 | 22턴에서 같은 연결 실패 |
| libero_goal_swap task 1 | 인프라 | 7턴에서 같은 연결 실패 |

task 0, task 2, swap 0, swap 1은 `batch01-goal-retry`에서 다시 돌고 있다. 그 결과는 이 표에 아직 없다.
