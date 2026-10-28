# Trace schema v0.1

`notes/rpent_version_diff.md`는 저장소에 없다. 아래 형태는 RPent 객체 `f70d720`의 `git show f70d720:<path>`와 `AgenticRoboRL/patches/rpent/rpent_f70d720.patch`로 확인했다. 체크아웃 브랜치는 바꾸지 않았다. 패치는 primitive 본문, `states.json` writer, transcript 메시지 직렬화를 고치지 않는다.

변환기는 읽기 전용이다. 출력은 `traces/{run_id}/{episode_id}/episode.json`과 `decisions.jsonl`이다. `run_id`를 생략하면 RPent 출력 디렉터리 이름, `episode_id`를 생략하면 `transcript_<id>.json`의 `<id>`다.

## 버전 차이 중 변환에 반영한 것

| 항목 | f70d720 + 패치 | 체크아웃 a744bd5 | 변환기 |
| --- | --- | --- | --- |
| `move_to` 정지 | `dist < tol`만. `tol` 기본 **0.012**. `yaw_tol` 인자 없음. `target_yaw`는 조향에만 쓰이고 정지 조건에 없다 | `dist < tol`이고 yaw 오차 `< yaw_tol`(기본 0.02) | 거리만. `final_dist_m < tol` |
| `pi0_pick` 성공 비트 | 하강 0.10 m는 하드코드. 닫힘은 `grip < gripper_closed_thresh`. 환경이 먼저 끝나면 `success = env.terminated` | `descent_thresh`(기본 0.1), `gripper_open_thresh`(기본 0.0). 닫힘은 `gripper_open_thresh <= grip < gripper_closed_thresh` | `result.success`를 그대로 읽는다. 임계값을 다시 계산하지 않는다 |
| `pi0_pick` 결과 이름 | 반환 `name`은 `"pick"`. `states.json`의 `command.action`은 도구 이름 `"pi0_pick"` | 반환 이름도 `"pick"` | 맞춤은 `command.action` |
| 메모리 경로 | `get_memory_dir` = `resources/<robot>/memory`. 프롬프트는 `MEMORY.md`, `global/`, `suite/`, `task/` | 분석 노트 기준 `global`, `task-family`, `task-specific` | 경로 성분 `memory` 또는 파일명 `MEMORY.md` |
| transcript 최상위 | 패치가 `solved`, `agent_error`를 추가. `environment_success`는 없음 | `environment_success`. `solved` 키는 없음 | 둘 다 성공 라벨로 쓰지 않음 |
| `states.json` | `rpent/tools/state.py`의 `StepRecord`: `step_idx`, `state`, `terminated`, `truncated`, `artifacts`, 그리고 있을 때만 `command`, `result`, `elapsed_s`, `extras` | 같은 필드가 `rpent/session/base.py`에 있음 | 이 필드만 읽음 |
| 아티팩트 경로 | `<name>/<step:02d><suffix>` (`agentview.png/00.png`) | 같은 `_artifact_file` | `obs_before.paths`에 상대 경로만 기록. 파일은 열지 않음 |

메시지 형태는 f70d720 `api` planner다. assistant `content[]`의 `text` / `thinking` / `tool_use`(`id`, `name`, `input`). tool 역할 메시지는 `name`, `tool_call_id`, `content` 문자열이다. 실행 결과는 tool 메시지(관측 `view_env_state` 텍스트)가 아니라 `states.json`의 `result`다. `execute_tool`이 핸들러 반환값을 `states.json`에 넣고, LLM에 돌려주는 값은 그 다음 `get_env_state`다.

패치가 `solved = False`를 루프 앞에 넣지만, f70d720 `main`은 세션 안에서 이미 `solved = toolkit.solved()`를 대입한다. 루프가 돌면 transcript `solved`는 그 값이다. 분석 노트의 "항상 false"는 패치 diff만 본 결론이라 여기 규칙에 쓰지 않았다. 변환기는 `solved`를 읽지 않는다.

부수 확인: f70d720 `api_loop._build_stats`는 `requests`를 넣는다. 변환기는 그 값을 쓰지 않는다.

## 도구 분류

한 줄은 `states.json` 스텝을 만드는 실행 primitive 하나다. `@readonly`가 아닌 핸들러만 `Toolkit.execute_tool`이 `get_env_state`를 호출한다.

실행 (`src/trace/tool_classes.py` `EXECUTION_TOOLS`): `reset`(explore에서만 등록), `move_to`, `pi0_pick`, `pi0_doubled`, `release`, `set_gripper`, `rotate_wrist`, `rotate_pitch`, `move_pose`.

질의 (`QUERY_TOOLS`): `view_env_state`, `view_camera_meta`, `back_project`, `segment`, `read_text_file`, `write_text_file`, `list_dir`, `finish`.

질의 호출은 다음 실행 기록의 `context_calls`다. `read_text_file` / `list_dir`의 경로가 메모리면 `stats.n_memory_reads`를 1 올리고, 그 호출을 받은 기록의 `teacher_text.cites_memory`를 true로 둔다. 빈 `list_dir` 경로는 출력 디렉터리라 메모리가 아니다.

목록에 없는 도구는 질의로 보고 warning만 남긴다. 실제로 스텝을 만들면 개수 불일치로 `matched`가 false가 된다.

## episode.json

```json
{
  "schema_version": "0.1",
  "run_id": "demo-run",
  "episode_id": "demo-ep",
  "source": {
    "rpent": "f70d720+AgenticRoboRL/patches/rpent/rpent_f70d720.patch",
    "states": "states.json",
    "transcript": "transcript_object_t1_s12.json"
  },
  "task": {"suite": "libero_object", "task": 1, "seed": 12, "model": "openai-chat:qwen"},
  "outcome": {"success": true, "terminated": true, "truncated": false},
  "conversion": {"matched": true, "warnings": []},
  "stats": {"n_memory_reads": 0, "n_decisions": 3, "n_context_calls": 3},
  "trailing_context_calls": [
    {"name": "finish", "arguments": {"status": "success", "summary": "picked"}, "tool_call_id": "a6"}
  ],
  "trailing_teacher_text": {"text": "", "thinking": "", "cites_memory": false}
}
```

`outcome.success`는 마지막 `states.json` 스텝의 `terminated`가 JSON `true`인지다. `truncated`만 true면 실패다. `environment_success`와 transcript `solved`는 보지 않는다. 실패 에피소드도 같은 파일을 쓴다.

`conversion.matched`는 실행 도구 호출 개수와 `command`가 있는 스텝 개수가 같고, 그 순서의 이름이 `command.action`과 같을 때 true다. 개수나 이름이 다르면 false이고 `warnings`에 양쪽 이름과 개수를 적는다. 인자만 다르면 warning이고 `matched`는 그대로다. 스텝이 없거나, 마지막 스텝에 `terminated`가 없거나, transcript가 둘 이상이거나, `messages`가 없으면 false다.

`stats.n_context_calls`는 결정에 붙은 질의와 `trailing_context_calls`를 합친 수다.

## decisions.jsonl

한 줄이 실행 primitive 하나다. 예는 `pi0_pick` 실패 → `move_to` → `pi0_pick` 성공이다.

```json
{"decision_index": 0, "step_idx": 1, "primitive": "pi0_pick", "arguments": {"prompt": "pick up the bowl"}, "tool_call_id": "a2", "obs_before": {"step_idx": 0, "paths": ["agentview.png/00.png"]}, "context_calls": [{"name": "view_env_state", "arguments": {"step": 0}, "tool_call_id": "a1"}], "teacher_text": {"text": "Try the pick.", "thinking": "", "cites_memory": false}, "result": {"name": "pick", "success": false, "terminated": false, "truncated": false}, "terminated": false, "truncated": false, "elapsed_s": 2.0, "labels": {"primitive_success": false, "relation_to_failed": null, "type": "unlabeled"}}
{"decision_index": 1, "step_idx": 2, "primitive": "move_to", "arguments": {"xyz": [0.1, 0.0, 0.2], "gripper": 1}, "tool_call_id": "a4", "obs_before": {"step_idx": 1, "paths": ["wrist.png/01.png"]}, "context_calls": [{"name": "segment", "arguments": {"prompt": "bowl", "camera": "agentview"}, "tool_call_id": "a3"}], "teacher_text": {"text": "Restage above the bowl.", "thinking": "", "cites_memory": false}, "result": {"name": "move_to", "final_dist_m": 0.004, "terminated": false, "truncated": false}, "terminated": false, "truncated": false, "elapsed_s": 0.8, "labels": {"primitive_success": true, "relation_to_failed": null, "type": "unlabeled"}}
{"decision_index": 2, "step_idx": 3, "primitive": "pi0_pick", "arguments": {"prompt": "pick up the bowl"}, "tool_call_id": "a5", "obs_before": {"step_idx": 2, "paths": ["agentview.png/02.png"]}, "context_calls": [], "teacher_text": {"text": "Pick again.", "thinking": "", "cites_memory": false}, "result": {"name": "pick", "success": true, "terminated": true, "truncated": false}, "terminated": true, "truncated": false, "elapsed_s": 1.2, "labels": {"primitive_success": true, "relation_to_failed": "restage_retry", "type": "restage_retry"}}
```

`obs_before`는 그 primitive 바로 앞 스텝의 아티팩트 상대 경로다. 이미지는 복사하지 않는다. `arguments`와 `result`는 `states.json`의 `command`(키 `action` 제외)와 `result`다. `terminated` / `truncated` / `elapsed_s`도 그 스텝 값이다.

`teacher_text.text`와 `thinking`은 이전 실행 호출 이후의 assistant 블록을 순서대로 모아 `\n\n`으로 잇는다. 메모리 읽기가 그 `context_calls` 안에 있으면 `cites_memory`가 true다.

마지막 실행 뒤에 남은 질의(`finish`, `write_text_file` 등)는 다음 primitive가 없다. `episode.json`의 `trailing_context_calls`와 `trailing_teacher_text`에 둔다. 그 구간의 메모리 읽기도 `n_memory_reads`에 들어간다.

`relabel(decisions.jsonl)`은 파일을 다시 읽고 `labels.type`만 고친다. `primitive_success`와 `relation_to_failed` 저장값은 유지한다. `type`은 `primitive` / `result` / `arguments`로 다시 계산한다.

## 규칙

### primitive_success

| primitive | 반환 | 근거 |
| --- | --- | --- |
| `pi0_pick` | `result.success is True`면 True, 키가 있고 true가 아니면 False, 키가 없으면 None | f70d720이 하강·재상승·그리퍼 휴리스틱을 이 비트에 기록. 환경이 먼저 끝나면 `success = env.terminated` |
| `pi0_doubled` | `success` 또는 `terminated`가 true면 True. false여도 None | 성공은 환경 `terminated`만. 중간 false는 실패가 아님 |
| `move_to` | `final_dist_m < tol`. `tol`이 인자에 없으면 **0.012**. `final_dist_m`이 없으면 None | `success` 키 없음. yaw는 보지 않음 |
| `release`, `set_gripper`, `rotate_wrist`, `rotate_pitch`, `move_pose`, `reset` | None | 반환에 `success`가 없고, 노트가 임계값을 정하지 않음 |

### relation_to_failed / type

| 함수 결과 | 조건 |
| --- | --- |
| `relation_to_failed` = `restage_retry`, `type` = `restage_retry` | 이 기록이 성공한 `pi0_pick`이고, 바로 앞이 `move_to`가 하나 이상이고, 그 앞이 실패한 `pi0_pick` |
| `relation_to_failed` = null, `type` = `unlabeled` | 그 외 전부 |

`move_to`가 거리 기준으로 실패해도 패턴은 성립한다. 사이에 `release` 같은 다른 실행이 있으면 성립하지 않는다. `pi0_doubled`의 false는 실패가 아니라서 앞선 실패로 세지 않는다. 질의 호출은 결정 목록에 없으므로 패턴을 끊지 않는다.

## 노트가 정하지 않아 둔 것

- 스키마 버전 문자열 `0.1`과 위 JSON 키 이름.
- `type`의 기본값 `unlabeled`. `restage_retry` 외 라벨은 만들지 않았다.
- `relation_to_failed`는 `restage_retry` 또는 null만 쓴다. 지금 구현에서 `type`이 `restage_retry`인 경우는 이 관계와 같다.
- restage 창은 `move_to`를 한 번 이상으로 본다.
- 결정의 본체는 `states.json` 실행 스텝이고, transcript는 문맥·교사 텍스트·개수/이름 맞춤에 쓴다.
- 교사 텍스트는 이전 실행 이후 assistant 블록을 모은다.
- 메모리 인용 플래그는 그 읽기를 `context_calls`로 받은 다음 실행 기록에 둔다. 읽기와 실행이 다른 assistant 메시지여도 그렇게 붙인다.
- 끝부분 질의는 `trailing_*`에 둔다.
- 인자 불일치는 warning만 하고 `matched`를 내리지 않는다.
- 맞춤에 필요한 필드가 없거나 transcript가 둘 이상이면 `matched`를 false로 둔다.

## 확인 필요

- `restage_retry` 이외의 type. 같은 primitive 즉시 재시도, `release` 후 재시도, `pi0_doubled` 복구, `move_to`가 아닌 실행이 사이에 있는 재배치. 코드와 노트에 이름이 없어 `unlabeled`다.
- `release`, `set_gripper`, `rotate_wrist`, `rotate_pitch`, `move_pose`, `reset`의 성공 규칙. f70d720 반환에는 `success`가 없다. `rotate_*`는 `final_err`, `move_pose`는 `final_dist_m`만 있다.
- restage가 `move_to` 정확히 한 번인지, 그 `move_to`가 거리 안이어야 하는지. 구현은 하나 이상이고 거리 성공은 요구하지 않는다.
- 메모리 읽기 판정. 경로 성분이 `memory`가 아니고 파일명도 `MEMORY.md`가 아닌 `--memory-dir`, 또는 a744bd5의 `task-family` / `task-specific` 경로는 세지 않는다. f70d720 기본 `resources/<robot>/memory`는 센다.
- explore 레이아웃. 세션별 `states.json`과 런 루트의 transcript가 갈라지는 경우는 한 디렉터리에 둘 다 있다고 가정한다.
- 한 디렉터리에 `transcript_*.json`이 둘 이상일 때 어느 파일이 teacher 기록인지. 정렬상 첫 파일을 쓰고 `matched=false`.
- 마지막 실행 뒤의 `finish` / `write_text_file`을 이전 결정에 붙일지, 버릴지, 지금처럼 `trailing_*`에 둘지.
- 메모리 읽기와 실행이 다른 assistant 턴일 때 `cites_memory`를 어느 턴의 `teacher_text`에 둘지. 지금은 다음 실행 기록에 둔다.
