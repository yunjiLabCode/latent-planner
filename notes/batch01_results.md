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
