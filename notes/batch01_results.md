# batch01 goal 5개 (2026-10-30)

실행은 하지 않았다. task 1은 `outputs/batch01/`의 rc=0 실행이다. task 0, task 2, swap 0, swap 1은 `outputs/batch01-retry2/`의 attempt_00이다. 재시작 기록 파일은 없다.

Hawaii 원문: `/data/yunji/latent-planner-work/logs/batch01_results.md`

## 1. rc=1

`RPent/rpent/cli/main.py`의 `main()`은 `agent_error`가 있을 때만 1을 반환한다 (574행). 태스크 실패(`terminated` false)만으로는 1이 아니다.

| 에피소드 | agent_error | finish | 마지막 |
|---|---|---|---|
| goal task 1 | 없음 | status success | rc=0 |
| goal task 0 | planner timeout 7200초 | 없음 | 요청 시간 초과 |
| goal task 2 | ModelTimeoutError | 없음 | 다음 요청 시간 초과 |
| goal swap 0 | planner timeout 7200초 | 없음 | 요청 시간 초과 |
| goal swap 1 | planner timeout 7200초 | 없음 | 요청 시간 초과 |

## 2. 에피소드

시간은 초. `vllm_restarts.log`는 없어서 다섯 구간 모두 재시작이 없다.

| suite | task | 턴 | 시간 | rc | terminated | 분류 |
|---|---:|---:|---:|---:|---|---|
| libero_goal_task | 1 | 22 | 2310 | 0 | true | 성공 |
| libero_goal_task | 0 | 34 | 7254 | 1 | false | agent 에러 |
| libero_goal_task | 2 | 30 | 6461 | 1 | false | agent 에러 |
| libero_goal_swap | 0 | 33 | 7230 | 1 | false | agent 에러 |
| libero_goal_swap | 1 | 44 | 7327 | 1 | false | agent 에러 |

teacher가 태스크를 실패로 끝낸 행은 없다. 인프라로 끊긴 행도 없다. 4개는 planner 시간 제한이다.

## 3. trace (schema v0.2.1)

변환 출력: `logs/batch01_results_traces`.

| 에피소드 | matched | 결정 | primitive | role | recovery |
|---|---|---:|---|---|---|
| goal task 1 | true | 7 | move_to 4, pi0_pick 2, set_gripper 1 | new 2, restage 4, restage_retry 1 | pi0_pick, 2회, resolved false, closed_by episode_end |
| goal task 0 | false | 12 | move_to 6, pi0_pick 2, pi0_doubled 1, set_gripper 1, move_pose 2 | new 3, recovery 1, restage 8 | pi0_pick 1회 resolved true closed_by recovery. pi0_pick 1회 resolved false closed_by episode_end |
| goal task 2 | true | 17 | move_to 8, pi0_pick 4, move_pose 3, set_gripper 1, release 1 | new 8, restage 6, recovery 3 | pi0_pick 1회 resolved true 가 3개. move_to 1회 resolved false closed_by episode_end |
| goal swap 0 | false | 14 | pi0_doubled 4, move_to 7, move_pose 3 | new 9, retry 5 | move_to, 6회, resolved true, closed_by success |
| goal swap 1 | false | 18 | move_to 13, pi0_pick 2, move_pose 2, set_gripper 1 | new 9, retry 5, restage 2, restage_retry 1, recovery 1 | move_to 6회 resolved true closed_by success. move_to 2회 resolved true closed_by recovery |

합계: new 31, restage 20, retry 10, recovery 5, restage_retry 2. 실패가 하나 이상 있는 에피소드는 5개 전부다. task 1도 `pi0_pick` recovery가 `episode_end`로 닫혔지만 마지막 `terminated`는 true다.

## 4. goal task 2의 끝

`pi0_pick` 다음에 `move_to`를 반복했다. 빈 그릇에 release한 뒤 다음 planner 요청이 `ModelTimeoutError`로 끊겼다. 영상은 `outputs/batch01-retry2/libero_goal_task/task_02/seed_011/attempt_00/episode.mp4`다.

## 5. AgenticRoboRL 평가와 다른 점

harness.yaml eval과 비교해 확인된 것만.

- vLLM `--dtype half`
- `--disable-custom-all-reduce`
- `NCCL_P2P_DISABLE=1`
- tensor parallel 2, gpu-memory-utilization 0.85. 평가는 TP=1, util 0.62

동시 4개는 같다 (`episodes_parallel` 4, `max-num-seqs` 4). temperature 1.0, top_p 0.95, top_k 20, presence_penalty 1.5, seed 3407, knowledge_profile proven, max_turns 100도 같다.

## 6. retry2 속도와 스모크 (2026-10-30)

턴별 출력 토큰은 `run.log` usage 차이다. vLLM 로그에는 요청별 e2e 히스토그램이 없다. 출력 2000토큰 이상인 턴의 클라이언트 간격은 토큰당 0.074–0.15초, 중앙값 0.108초다. 스모크의 긴 턴은 0.026–0.044초였다. 스모크의 느린 끝보다 약 2.5배, 빠른 끝보다 약 4배다. 출력 길이와 간격의 상관은 0.67이고 스모크는 0.96이었다.

최대 프롬프트: goal task 0은 60,167, task 2는 58,612, swap 0은 52,930, swap 1은 64,685. 스모크 최대 56,937보다 큰 것이 3개다. 떠 있던 TP=2, util 0.85 로그의 KV 캐시는 598,814토큰이다. GPU 한 장 값은 아니다.

수집 pane은 죽었는데 vLLM pid 2433462와 π0.5, SAM3가 GPU를 잡고 있어, TP=1 util 0.90 측정은 아직 하지 않았다. 그 프로세스를 내린 뒤 짧게 잰다.

## 7. matched=false

task 0, swap 0, swap 1은 첫 명령 전에 어긋난다. transcript의 tool 실행은 0건이고 `states.json` 단계는 12, 14, 18개다. `episode.json`에 `truncated: true`를 두고 일치하는 접두의 결정만 남기면, 그 접두는 비어 있다. 구현하지 않았다.

## 8. 라벨

goal task 1의 첫 `pi0_pick`(step 2): 하강 0.1646 완료, 상승 0.0095, 그리퍼 0.0108, success false. teacher는 안 들어올렸다고 적었다. 두 번째(step 4): 하강 0.0147 미완, 상승 0.0174, success false. teacher는 실패 문장 없이 성공으로 끝냈다. recovery를 부풀린 것은 이 두 번째다.

`move_to`의 `final_dist_m`이 0.012–0.03인 것은 1개다. swap 0의 0.0175이고, 다음 명령도 `move_to`다. 0.012 기준이 recovery 수를 부풀리지는 않았다.

## 9. budget_timeout

retry2의 4개는 `failure_kind=budget_timeout`으로 두는 안이 맞다. teacher 실패나 인프라 끊김과 섞지 않는다. 코드는 바꾸지 않았다.

## 10. timeout transcript (collect, 제안)

collect는 `50717fa`다. `f70d720` 위에 패치가 있다. RPent는 고치지 않았다.

`main()`은 `messages`를 `[]`로 시작한다 (`rpent/cli/main.py` 437행). `planner.solve()`가 돌아온 뒤에만 `messages += result.messages`를 한다 (504행). 그 리스트를 `_serialize_messages`로 이미지를 빼고 `transcript_*.json`의 `messages`에 쓴다 (541–553행). `solve()`가 예외를 던지면 이 덧셈은 실행되지 않고, `except`가 `agent_error`만 `ModelTimeoutError: ...` 형태로 남긴 채 `messages`는 빈 리스트다 (528–530행).

벽시계 timeout은 예외로 빠져나오지 않는다. `ApiAgentLoop.solve`가 `_solve`를 `asyncio.wait_for`로 감싼다 (`rpent/planner/api_loop.py` 136–147행). `TimeoutError`면 취소된 코루틴 안에서 observer가 붙여 가던 리스트는 버려지고, 반환 `messages`는 시작 user 메시지 하나다. `finish_result`는 None, `stats`는 `{}`, `error`는 `API planner timed out after {초}s`다. `main()`은 그 한 줄을 쓴다. task 0, swap 0, swap 1의 tool 실행 0건이 이 경로다.

`ModelTimeoutError`는 `_solve`의 `except Exception`이 잡는다 (275–286행). observer가 이미 붙인 `messages`로 `PlannerResult`를 반환한다. `error`는 `ModelTimeoutError: ...`다. `main()`은 그 대화를 그대로 붙인다. 시간 초과가 난 그 요청은 응답이 없어 `observe_response`가 돌지 않으므로 메시지가 아니다. 그 전까지의 턴은 남는다. task 2가 matched인 이유다.

가장 작은 변경은 `api_loop.py`의 `ApiAgentLoop.solve`와 `_solve`뿐이다. `solve`가 user 메시지로 리스트를 만든 뒤 `_solve`에 넘긴다. observer는 그 리스트에 붙인다. `TimeoutError` 분기만 그 리스트를 반환한다. `finish_result=None`, `stats={}`, error 문자열은 지금과 같다. `_solve`는 리스트를 안 받으면 지금처럼 직접 만든다. 정상 종료, `ModelTimeoutError`, `UsageLimitExceeded`는 같은 리스트를 반환하므로 그 transcript는 같다. interactive와 dashboard는 인자 없이 호출해 그대로다. `main()`은 고치지 않는다. `result.messages`를 쓰는 동작이 이미 맞다. 취소는 await 경계에서만 일어나서, 공유 리스트에는 timeout 전에 append된 완전한 메시지만 있다.
