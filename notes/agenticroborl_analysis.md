---
cursor:
  subagentId: "bc-2cbed74a-14a3-5b01-bf0c-1b118bdd8468"
---

# AgenticRoboRL 분석

대상: `/workspace/AgenticRoboRL`, 커밋 `74dca18633f9f3be02d00c243130e691da5cda21` (`https://github.com/yunjiLabCode/AgenticRoboRL.git`). 체크아웃이 비어 있어 `/workspace`에서 `git submodule update --init AgenticRoboRL`만 실행했다. 다른 서브모듈, 브랜치, 커밋, 코드 수정, 패키지 설치, worktree는 하지 않았다.

비교 기준은 `/workspace/notes/rpent_analysis.md`의 RPent 커밋 `a744bd5f128ebef3cb8c6736cf7cd98adff681f1`이다. AgenticRoboRL이 요구하는 RPent는 그와 다른 트리(`RLinf/RPent` `f70d720` + `patches/rpent/rpent_f70d720.patch`)다.

## 1. `rl/proxy.py`는 planner 호출을 어떻게 기록하는가

### 코드에서 확인

프록시는 harness와 vLLM 사이의 OpenAI chat-completions HTTP 프록시다. 플래너는 GPU당 하나인 프록시의 에피소드별 URL로 보내고, 프록시가 샘플링을 덮어쓴 뒤 upstream vLLM으로 전달한다.

- 진입: `rl/proxy.py`의 `main()` → `build_app()` → `POST /ep/{key:path}/v1/chat/completions`의 `chat()`.
- URL: 모듈 docstring과 `rl/harness_cfg.py`의 `episode_vars()`. 학습 롤아웃의 `model_url`은 `http://127.0.0.1:<proxy_port>/ep/<episode key>/v1`. `<episode key>`는 run 출력 루트 아래 상대 경로다. RPent harness의 키 템플릿은 `harnesses/rpent_libero/harness.yaml`의 `episode.dir`: `local/{suite}/task_{task:02d}/seed_{init_id:03d}/attempt_{attempt:02d}`.
- 기동: `rl/local_ctl.py`의 `Stack.__init__()`. `proxy=True`일 때 `rl/proxy.py --port --upstream --out-root --policy-version --timeout-s`를 띄운다. `--out-root`는 그 라운드/평가의 에피소드 루트(`rounds/rK/eps` 또는 `eval/<tag>/eps`)다.
- 키 검사: `Recorder.episode_dir()`. 정규식 `^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$`, 경로 조각에 `..` 금지. 실패 시 HTTP 400.
- 스트림: `body["stream"]`이 참이면 HTTP 400. 기록하지 않는다.
- 샘플링 덮어쓰기: `sent = {**body, **RL_SAMPLING, **ADDED_KEYS}`. `rl/rl_sampling.py`의 `RL_SAMPLING`은 `temperature=1.0`, `top_p=1.0`, `top_k=0`, `min_p=0.0`, `presence_penalty=0.0`, `frequency_penalty=0.0`, `repetition_penalty=1.0`. `ADDED_KEYS`는 `logprobs=True`, `return_token_ids=True`. `top_logprobs`는 제거한다.
- 재시도: `send()`. timeout, 연결 오류, 408, 429, 5xx면 1초, 2초, 4초 뒤 재시도. 네 번째 실패는 플래너에 502.
- 기록 조건: upstream JSON이 200일 때만 `Recorder.write()`. 200이 아니거나 JSON이 아니면 응답만 되돌리고 파일을 쓰지 않는다.
- 파일: `<out-root>/<key>/rl_turns/turn_NNN.json.gz`. `NNN`은 그 디렉터리의 `turn_*.json.gz` 개수(0부터). gzip(`compresslevel=1`)된 JSON, 구분자 `( ",", ":" )`. 같은 에피소드 키는 `asyncio.Lock`으로 직렬화. 임시 파일에 쓴 뒤 `rename`.
- 이미지: `Recorder.strip_images()`. `messages[].content[]`에서 `type=="image_url"`이고 URL이 `data:<mime>;base64,...`인 파트만 바꾼다. 바이트의 sha1로 `<key>/rl_images/<sha1>.<ext>`에 한 번 저장(`png`/`jpg`/`webp`, 그 외 `bin`). 메시지 안에서는 `{"type":"image_ref","sha1","mime","bytes","path":"rl_images/<name>"}`와, 있으면 `detail`. 그 외 content는 그대로 둔다.
- 한 레코드의 필드 (`chat()`이 만드는 dict, 이후 `write()`가 `turn_index`와 `messages`를 넣음):

| 필드 | 내용 |
| --- | --- |
| `key` | URL의 episode key |
| `policy_version` | `--policy-version` |
| `turn_index` | 디스크에 이미 있는 turn 파일 수 |
| `t_start`, `t_end`, `latency_s` | upstream 호출 전후 `time.time()`, latency는 소수 4자리 |
| `client_sampling` | 원 요청의 `RL_SAMPLING` 키와 `seed`, `logprobs`, `top_logprobs` |
| `sent_sampling` | 실제로 보낸 `RL_SAMPLING` 키와 `seed` |
| `request` | 원 body에서 `messages`를 뺀 나머지 |
| `messages` | 이미지 치환 후의 원 `messages` |
| `prompt_token_ids` | vLLM 응답의 `prompt_token_ids` |
| `output_token_ids` | `choices[0].token_ids` |
| `output_logprobs` | `choices[0].logprobs.content[].logprob` |
| `finish_reason`, `stop_reason` | choice |
| `message` | `choices[0].message` (본문, tool_calls, reasoning이 여기 있으면 그대로) |
| `usage` | 응답 `usage` |

플래너로 돌려주는 JSON에서는 `prompt_token_ids`와 choice의 `token_ids`를 지운다. 클라이언트가 `logprobs`를 요구하지 않았으면 choice의 `logprobs`를 `null`로 둔다.

`GET /healthz`는 `{ok, policy_version}`만 반환한다. `GET /ep/{key}/v1/models`는 upstream `/v1/models`를 그대로 전달하고 기록하지 않는다.

### 추론

이 프록시가 보는 것은 플래너가 chat completion으로 보낸 요청과 vLLM이 200으로 돌려준 응답이다. 도구 실행 결과, 시뮬레이터 상태, 에피소드 성공은 이 파일에 별도 필드로 들어가지 않는다. 다음 턴의 `messages`에 하네스가 도구 결과를 다시 넣었다면 그 텍스트는 다음 레코드의 `messages`로만 남는다.

## 2. `sft/rpent/replay_build.py`는 teacher transcript를 student 요청으로 어떻게 바꾸는가

### 코드에서 확인

스크립트 docstring: `RPENT_DIR`(패치가 적용된 RPent)를 `sys.path`에 넣고 그 디렉터리로 `chdir`한 뒤, 같은 `ApiAgentLoop`와 pydantic-ai OpenAI 매핑으로 teacher transcript를 재생한다. 사용법:

`RPENT_DIR=<patched RPent> python sft/rpent/replay_build.py <cell dir> <out_dir> <episode key>`

출력은 `<out_dir>/<episode key>.json` 한 객체: `meta`, `system_prompt`, `user_message`, `samples`.

`main()` 순서:

1. `<cell dir>/transcript_*.json` 첫 파일을 읽는다. 첫 user 메시지에서 정규식 `- output_dir: (\S+)`로 teacher의 `output_dir`을 꺼낸다. 없으면 assert.
2. `parse_transcript()`가 `messages`를 assistant 턴과 tool 결과로 나눈다. assistant content 타입 `thinking` / `text` / `tool_use`를 `think`, `text`, `calls[{id,name,input}]`로 모은다. tool 메시지는 `tool_call_id` → `content`. `read_text_file`와 `list_dir`만 `classify_path()`로 `guide` / `own_run` / `memory` / `out_of_scope`를 붙인다. 그 외 도구는 `other`.
3. `classify_path()`: 절대 경로가 아니면 `RPENT_DIR` 기준. `robots/libero/guides` 아래 또는 경로 문자열에 `robots/libero/guides`가 있으면 `guide`. teacher `output_dir` 자신 또는 그 아래면 `own_run`. 경로에 `resources/libero`, `results_`, 또는 `memory`(대소문자 무시)가 있으면 `memory`. 나머지는 `out_of_scope`. `REFUSED`는 `memory`와 `out_of_scope`.
4. `annotate()`가 턴마다 `disposition`을 정한다.
   - `only_memory`(호출이 전부 REFUSED) → `drop_turn`. 히스토리에서 빠진다.
   - REFUSED 호출이 있거나, 남은 텍스트/think/도구 인자에 메모리 키워드(`KW`) 또는 메모리 n-gram(`MEM_NG`, `resources/libero`의 md/json에서 guides를 뺀 8-gram)이 있거나, 제거된 도구 결과에만 있던 소수(소수점 2자리 이상을 소수 3자리로 반올림)가 보이면 → `keep_history_no_target`.
   - 그 외 → `target`.
   - 이후 턴이 볼 수 있는 숫자에는 drop이 아닌 턴의 text, 유지된 도구 인자, 유지된 결과만 더한다. thinking은 다시 보내지 않는다고 주석에 적혀 있다. REFUSED 결과의 숫자는 `removed`로만 쌓인다.
5. `build_prompts()`는 `robots/libero/robot_spec.py`의 `get_robot_spec().prompts.render("system"|"user")`를 호출한다. `prompt_vars`에 `knowledge_profile: "proven"`, `memory_profile: "hf"`, `mode: "eval"`, `session_number/max: 1`을 넣는다. `output_dir`은 teacher 경로 그대로다. 학생 모델 상수는 `STUDENT_MODEL = "Qwen/Qwen3.5-9B"`.
6. `ReplayToolkit`이 학생 도구 스펙을 제공한다. `student_tool_specs()`는 `rpent.tools.common.TOOLS_SPEC` 전부, LIBERO `TOOLS_SPEC`에서 `reset`은 빼고, `view_env_state` / `view_camera_meta` / `back_project` / `segment`는 항상, 나머지 primitive는 `LiberoPrimitives`에 메서드가 있을 때만 넣는다. `execute_tool()`은 이번 턴에 기록된 같은 이름·같은 인자의 `result_text`를 텍스트 블록으로 돌려준다. 인자가 다르면 이름만 맞추고 `mismatch`에 남긴다. `move_to`, `pi0_pick`, `pi0_doubled`, `release`, `set_gripper`, `rotate_wrist`, `rotate_pitch`, `move_pose`, `reset`, `view_env_state`는 결과 JSON의 `step`으로 `libero_tools.view_env_state()`를 다시 호출해 이미지 바이트를 붙인다. `segment`는 `overlay_artifact`를 `EnvState.load_bytes()`로 읽는다. 스텝 상태는 `<cell>/states.json`을 `StepRecord`로 다시 넣는다.
7. `OpenAIChatModel.request`를 `fake_request`로 바꾼다. `prepare_request`와 `_map_messages`로 학생 쪽 OpenAI 메시지와 tool schema를 만든 뒤, 그 객체를 `records`에 넣고 teacher의 think/text/유지된 tool call로 `ModelResponse`를 반환한다. REFUSED 호출과 `result_text is None`인 호출은 응답에서 뺀다. 빠진 호출은 `response.dropped_memory_calls`에 `kind:name:path`로 남긴다. 모델 객체는 `OpenAIChatModel(STUDENT_MODEL, base_url="http://127.0.0.1:9/v1", profile=OpenAIModelProfile(openai_chat_send_back_thinking_parts=False))`. `ApiAgentLoop(..., no_images=False, reasoning_effort="low", sampling={temperature:1.0, top_p:0.95, top_k:20, presence_penalty:1.5})`의 `solve(..., max_turns=100)`가 루프를 돈다. 스케줄이 끝나면 빈 `TextPart`로 끝낸다.
8. 각 sample의 `messages` 안 `image_url` data URL은 `{type: image_ref, sha1, bytes, path}`로 바꾼다. 바이트 복사는 `glob.glob(os.path.join(cell_dir, "*.png", "*.png"))`로 찾은 파일만 `<out_dir>/images/<sha1>.png`에 복사한다. 못 찾으면 `path`는 `null`이고 `meta.images_unresolved`가 증가한다.

한 sample의 필드: `turn_index`(원 teacher 턴 번호), `disposition`, `reasons`, `mem_keywords`, `mem_ngram_hits`, `numbers_from_removed`, `messages`, `tools`, `response`.

`meta`에는 episode, cell_dir, suite/task/seed, recipe_tag, teacher_output_dir, student_model, 턴 수, target 수, disposition/reason/refused 카운트, transcript sha256, `finish`, `error`, `replay_mismatch`, 이미지 수, system prompt sha1이 있다.

파일 상단은 `from robots.libero.prompts import knowledge_eval`를 실행한다. 이 모듈은 패치가 추가한다 (`patches/rpent/README.md`, `knowledge_eval.py` 신규).

### 추론

학생 요청의 본문은 이 스크립트가 JSON을 조립한 것이 아니라, 패치된 RPent의 `ApiAgentLoop`가 도구 결과를 히스토리에 넣은 뒤 pydantic-ai `OpenAIChatModel._map_messages`가 만든 Chat Completions 메시지다. 메모리 파일 읽기 자체는 요청에서 빠지지만, 메모리 내용을 말로 옮긴 think/text는 이 단계에서는 지우지 않고 `keep_history_no_target`으로만 표시한다. 문장 삭제는 4번의 `teacher_rewrite/`다.

`glob`이 `cell_dir/*.png/*.png`만 본다. RPent 분석의 스텝 산출물(`<output>/<name>/<step>.png`, 스텝 디렉터리의 `agentview.png` 등)은 이 패턴 밖에 있다. 그래서 `image_ref.sha1`는 남아도 `path`가 비는 경우가 이 코드만으로 예상된다. 그 glob을 실제로 돌려 보지는 않았다.

## 3. RPent 어댑터는 planner 호출과 에피소드 결과를 어떻게 잇는가

### 코드에서 확인

연결은 한 디렉터리에 두 산출물이 같이 있는 것이다. 프록시 레코드는 `<episode dir>/rl_turns/turn_NNN.json.gz`, 결과는 같은 디렉터리의 `transcript_*.json`이다. `rl/adapters/__init__.py`는 이 둘을 분리해 둔다. 호출 기록은 프록시, 그룹과 종료는 어댑터.

`rl/adapters/rpent_libero.py`:

- `find_episodes(root)`는 `transcript_*.json`을 재귀 검색한다. 경로에 `/attempt_`가 있고 `.stale_`이 없는 파일만 본다.
- `read_verdict()`의 `_ATTEMPT`는 `/<suite>/task_<task>/seed_<seed>/attempt_<attempt>/transcript_*.json`만 받는다. `suite`는 `libero_`로 시작한다. harness 키의 `local/` 접두사는 이 정규식에 없다.
- transcript JSON 객체에서 `agent_error`, `solved`, `elapsed_s`, `stats.turns_used`, `stats.tool_calls`, `stats.total_input_tokens`, `stats.total_output_tokens`를 읽는다. 파일이 없거나 JSON이 아니면 `failure_kind=infrastructure`, `solved=None`.
- `classify_failure()`: `agent_error`가 비면 `None`(정상 종료). context overflow 문구면 `context_overflow`. 연결/CUDA/OOM/MuJoCo/EGL 등 또는 502/503/504면 `infrastructure`. 그 외 문자열은 `agent`.
- `"solved"` 키가 없으면 `failure_kind`를 `infrastructure`로 덮어쓴다. infrastructure가 아니면 `solved`는 `bool(rec["solved"])`.
- `valid`는 `failure_kind != "infrastructure"`. `reward`는 valid일 때 solved면 `1.0`, 아니면 `0.0`. `requests`는 `stats["requests"]`다. 그 키가 없으면 `None`.

`rl/build_round.py`의 `episode_rows()`가 같은 디렉터리의 `rl_turns/turn_*.json.gz`를 센다.

- valid인데 `requests`가 숫자이고 레코드 수와 다르면 `invalid_records`.
- 레코드가 0개여도 `invalid_records`.
- 첫 레코드와 마지막 레코드의 `policy_version`이 `--policy-version`과 같아야 `valid`. 가운데 레코드는 검사하지 않는다.
- 그룹 키는 `(suite, task, seed)`. 이름은 `{suite}/t{task}/s{seed}`. attempt가 다르면 같은 그룹의 다른 에피소드다.
- `episode_extras()`는 각 gzip의 `message.tool_calls[].function.name`만 센다. `n_calls`, `n_back_project`, `n_move_to`, `longest_same_call_run`.
- `--drop-post-success`일 때 `post_success_turns()`가 transcript의 assistant 메시지 수와 rl_turns 개수가 같을 때만 맞춘다. 다르면 `None`이고 필터하지 않는다. 맞으면 assistant 턴 바로 뒤의 tool 메시지 텍스트에 `"terminated"\s*:\s*true`가 처음 나온 턴을 성공 턴으로 보고, 그 다음 턴 중 `finish`가 아닌 tool_use를 샘플에서 뺀다.

보상은 프록시 레코드가 아니라 transcript의 `solved`다. 프록시 레코드는 그 보상을 어느 턴 샘플에 붙일지의 재료다. `samples.jsonl` 한 줄은 `episode_dir`, `turn_file`, `turn`, `reward`, `advantage`를 가진다 (`build_round.main()`).

공개 패치 `patches/rpent/rpent_f70d720.patch`의 `rpent/cli/main.py` 변경:

- `solved = False`를 루프 앞에 추가한다.
- transcript 객체에 `"solved": solved`, `"agent_error": agent_error`를 추가한다.
- 패치 전체에서 `solved`를 `True`로 바꾸거나 `toolkit.solved()`를 호출하는 줄은 없다.

`patches/rpent/README.md`는 이 패치가 transcript에 시뮬레이터 성공 플래그 `solved`와 `agent_error`를 남긴다고 적는다. 같은 문서는 논문 롤아웃이 이 패치보다 나중 파일이었고, 그 나중 버전은 환경 변수가 켜질 때만 시뮬레이터 상태를 추가로 기록했으며 그 기록은 이 패치에 없다고 적는다.

`/workspace/RPent` (`a744bd5`, `rpent/cli/main.py`의 `main()`)는 `solved = bool(toolkit.solved())`를 지원 로봇에서 계산하지만, transcript에 넣는 키는 `error`와 `environment_success`다. `solved`와 `agent_error` 키는 없다. LIBERO는 `finalize_run`이 없어 `environment_success`가 `None`으로 남는다 (`notes/rpent_analysis.md` 7번과 같은 코드). stats 키는 `turns_used`이지 `requests`가 아니다 (`rpent/planner/api_loop.py`의 `ApiAgentLoop`가 돌려주는 `PlannerResult.stats`).

### 추론

공개된 패치만 적용한 transcript는 `solved` 키가 항상 false다. 그러면 어댑터는 인프라 실패가 아닌 에피소드를 전부 `reward=0.0`으로 본다. README가 말하는 성공 보상은 이 패치 파일만으로는 만들어지지 않는다. 논문이 쓴 나중 RPent가 `solved`를 참 성공으로 채우는지는 이 트리에 소스가 없다. 확인 필요.

`/workspace/RPent` transcript에는 `solved` 키가 없으므로 `read_verdict()`는 그 파일을 infrastructure로 분류한다. 이 어댑터를 현재 체크아웃의 transcript에 그대로 붙이면 태스크 성공이 보상이 되지 않는다.

`stats.requests`는 이 패치가 추가하지 않는다. 현재 RPent stats에도 없다. 키가 없으면 어댑터의 호출 수 검사는 건너뛰고, 레코드가 1개 이상이며 첫·끝 `policy_version`만 맞으면 valid가 될 수 있다. f70d720 원본 stats에 `requests`가 있는지는 패치만으로 확인되지 않는다. 확인 필요.

`post_success`의 성공 신호는 프록시의 tool call이 아니라 transcript tool 결과 문자열의 `"terminated": true`다. RPent 분석 5번과 같이 primitive 반환의 `success`와 환경 `terminated`는 다르다. 어댑터는 후자 문자열만 본다.

## 4. `teacher_rewrite/`는 teacher 추론에서 메모리 참조를 어떻게 빼는가

### 코드에서 확인

이 디렉터리는 실행 중 프롬프트를 가로채지 않는다. `sft/rpent/replay_build.py`가 만든 리플레이 shard(에피소드 JSON의 tar)를 오프라인으로 고친다. `teacher_rewrite/README.md`의 순서와 스크립트가 일치한다.

1. `extract_turns.py`: shard의 각 sample에서 `think`, `text`, tool call, disposition, `reasons`, `mem_keywords`, `mem_ngram_hits`, `numbers_from_removed`만 `turns/turns_<i>.jsonl.gz`로 뺀다. 메시지 히스토리와 이미지는 건너뛴다.
2. `make_number_lists.py`: 메모리 디렉터리의 소수·긴 정수를 `hidden_corpus_numbers.json`으로, 턴별 제거된 메모리 결과의 숫자를 `numbers_from_removed_all.json`으로 만든다.
3. `make_turn_plan_full.py`: 턴을 문장 span으로 쪼갠다.
4. `number_provenance.py`, `strict_visibility.py`: 숫자가 그 턴 이전에 학생에게 보였는지 본다. 보이는 범위는 system prompt, 첫 user 메시지, tool 결과, tool-call 인자다. 이전 assistant의 자유 텍스트는 보이지 않은 것으로 친다 (`strict_visibility.visible_text()`).
5. `source_rules.py`의 `classify()`가 문장이 학생이 볼 수 없는 출처를 가리키는지 판정한다. 항상 출처로 보는 패턴은 seed-0/s0, `results_*`/`_pert`, `MEMORY.md`와 memory library/file, "memory says/notes", recipe/audit/reference, "they did/used/...", "documented/winning/proven", 이전 attempt 번호 등이다. `proven levers`는 `proven` 규칙에서 제외한다. recipe/audit를 이번 런의 자기 파일로 쓴다는 문맥(`OWN_FILE`)이면 `recipe_cited`/`audit_cited`는 출처가 아니다.
6. `build_pilot_inputs_v2.py`가 턴을 가른다.
   - reason에 `reads_memory` → `history_reads_memory` (고치지 않고 히스토리).
   - tool 인자가 `classify`에 걸리면 `history_tool_args_cite_source`.
   - 출처 문장이 3개 이상이면 `history_gate_3plus_flagged`.
   - 걸린 문장이 없고 원래 target이면 `target_clean`. 원래 히스토리면 `judge_only`.
   - 그 외 `llm`: `requests.jsonl`로 27B에게 보낸다.
   - 숨은 숫자는 (제거된 메모리 결과의 숫자, 그리고 출처를 인용한 턴이면 메모리 코퍼스와 겹치는 숫자) 가운데 학생에게 안 보인 것이고, 이번 턴 tool 인자에는 없는 것이다. 그 숫자를 담은 문장은 `hidden_number`로 표시한다.
7. `rewrite_client_v2.py`: `serve_gpu.sh`가 띄운 `qwen27`에 temperature 0, thinking 끄고 JSON schema로 문장별 `delete` / `drop_source` / `keep`을 받는다. 시스템 프롬프트(`RULES`)는 메모리 라이브러리, seed-0 recipe/audit, 저자의 이전 attempt를 HIDDEN으로 정의한다. `delete`는 그 내용과, 헤더면 `through`까지의 블록을 지운다. `drop_source`는 이번 에피소드의 계획·시스템 프롬프트·이번 도구 결과에 있는 내용에서 출처 표현만 빼고, 새 사실과 새 숫자를 넣지 못하게 한다.
8. `check_edits_v2.py`: 숨은 숫자가 남은 문장은 자동 삭제. `drop_source` 결과에 출처 단어, 금지 대체어, 결과 단정 단어, 새 숫자, 4개 이상의 새 단어가 있으면 실패. 적용 후 출처 문장이나 숨은 숫자가 남거나 삭제 비율이 50%를 넘으면 실패. 통과한 수정 턴만 판사로 간다.
9. `judge_client.py`: 같은 27B가 AFTER를 OK / MINOR / BAD로 본다. 남은 출처 힌트와 날조를 BAD로 보도록 프롬프트가 적혀 있다.
10. `finalize_v2.py`: `target_clean`은 그대로 target. `history_*`는 history. 수정 턴은 판사 OK일 때만 target. 무수정 `judge_only`는 OK 또는 MINOR이면 target. 나머지는 history.
11. `apply_rewrite_to_shards.py`: `changes.jsonl`의 think/text로 sample의 `response.think`/`response.text`를 바꾸고 disposition을 고친다. 같은 에피소드의 나중 sample 히스토리에서 그 assistant 텍스트도 바꾼다. 이미지는 바이트 그대로 복사한다. tool call 인자는 이 스크립트가 수정하지 않는다.

`serve_gpu.sh`는 `PLANNER_ENV`의 vLLM 0.28로 `Qwen/Qwen3.8-27B`(`--revision 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`, `--served-model-name qwen27`)를 GPU 하나에 띄운다. 이 서버는 9B planner가 아니다.

### 추론

메모리 참조를 빼는 동작은 한 함수의 치환이 아니다. 2번이 호출과 숫자를 걸러 학습 대상에서 빼고, 이 디렉터리가 남은 문장을 지우거나 출처 표현만 뺀 뒤 판사를 통과한 턴만 target으로 올린다. tool 인자에 출처가 있으면 문장을 고치지 않고 그 턴 전체를 히스토리로 남긴다. 논문 README의 27,110 → 40,047 숫자는 이 저장소가 재현한 결과가 아니라 README에 적힌 논문 데이터 수치다.

## 5. 공개 9B를 RPent planner로 붙여 평가하는 방법

### 코드와 문서에서 확인

체크포인트 URL은 `README.md`의 표뿐이다. 다운로드 명령은 없다.

| 이름 | 경로 |
| --- | --- |
| SFT step 563 | `https://huggingface.co/ciciciciliu/AgenticRoboRL-Qwen3.5-9B` 의 `sft/` |
| RL round 6 | 같은 저장소의 `rl-v006/` |

RPent를 Paper 설정으로 맞추는 명령은 `patches/rpent/README.md`에 있다.

```bash
git clone https://github.com/RLinf/RPent.git && cd RPent
git checkout f70d720
git apply --check /path/to/AgenticRoboRL/patches/rpent/rpent_f70d720.patch
git apply /path/to/AgenticRoboRL/patches/rpent/rpent_f70d720.patch
```

환경 변수는 `README.md` Prerequisites와 `harnesses/rpent_libero/harness.yaml` 머리말.

| 변수 | 문서상의 의미 |
| --- | --- |
| `RPENT_DIR` | `f70d720`에 위 패치를 적용한 체크아웃 |
| `RPENT_ENV` | LIBERO-PRO가 있는 RPent Python |
| `PLANNER_ENV` | vLLM 0.28이 있는 환경. `serve`는 `$PLANNER_ENV/bin/vllm` |
| `TRAIN_ENV` | `rl/train_rl.py`용. 평가 명령 템플릿은 `$TRAIN_ENV`를 쓰지 않는다 |
| `PI05_CHECKPOINT` | frozen VLA `RLinf-Pi05-LIBERO-130-fullshot-SFT` |
| `SAM3_CHECKPOINT` | `sam3.pt` |

에피소드 프로세스가 추가로 받는 값(`harness.yaml`의 `episode.env`와 `services`): `MUJOCO_GL=egl`, `PYOPENGL_PLATFORM=egl`, `OPENAI_API_KEY=EMPTY`. 서비스 명령이 `PI05_CHECKPOINT_PATH=$PI05_CHECKPOINT`, `SAM3_CHECKPOINT_PATH=$SAM3_CHECKPOINT`를 넣는다. vLLM 명령이 `CUDA_VISIBLE_DEVICES={gpu}`를 넣는다.

vLLM은 사람이 따로 치는 명령으로 문서화되어 있지 않다. `local_ctl.Stack`이 `model.serve_cmd`를 실행하고 `<model.url>/v1/models`가 열릴 때까지 기다린다 (`ready_timeout_s: 1800`). `harness.yaml`의 serve 줄:

```text
CUDA_VISIBLE_DEVICES={gpu} $PLANNER_ENV/bin/vllm serve {weights} --served-model-name {weights}
--host 127.0.0.1 --port {model_port} --tensor-parallel-size 1 --max-model-len 262144 --max-num-seqs 4
--gpu-memory-utilization 0.62 --limit-mm-per-prompt.video 0 --limit-mm-per-prompt.image 128
--enable-prefix-caching --enable-auto-tool-choice --generation-config auto
--tool-call-parser qwen3_coder --reasoning-parser qwen3
```

`{weights}`는 `local_ctl.weights_arg()`가 로컬 디렉터리면 절대 경로로, 아니면 준 문자열 그대로 넣는다. `--served-model-name`도 그 문자열이다. 에피소드는 `--model openai-chat:{weights}`를 쓴다.

평가 명령은 `harness.yaml` 머리말과 `eval` 블록. `eval.direct: true`라서 `episode_vars(..., direct=True)`가 `model_url`을 `http://127.0.0.1:{model_port}/v1`로 두고 프록시를 켜지 않는다 (`local_ctl.cmd_eval`). 샘플링은 에피소드 명령에 적힌 값 그대로다.

한 GPU 평가 (`harness.yaml` 주석, `--init-key`는 필수. README도 eval에 기본 init이 없다고 한다):

```bash
python rl/local_ctl.py eval --config harnesses/rpent_libero/harness.yaml --run-dir runs/x/g0 --weights <ckpt dir> --tag v000 \
       --init-key val_init_ids --shard 0/8 --var gpu=0 --var model_port=18100 --var proxy_port=18200 --var vla_port=18300 --var sam3_port=18400
```

논문이 보고한 숫자용 init은 `eval_init_ids`다. `harnesses/rpent_libero/tasks.jsonl`에서 train은 11–44, eval은 1–10, val은 45–49다. README의 보고 평가는 8 suite × 10 task × init 1–10이고, 플래너가 모델 서버에 직접 말한다.

여러 기계는 README의 이 명령이다. `--weights` 예는 `/shared/ckpt/sft`다.

```bash
python rl/multi_node_ctl.py eval  --cluster cluster.yaml --config harnesses/rpent_libero/harness.yaml \
       --run-dir /shared/runs/rpent --weights /shared/ckpt/sft --tag val_v000 --init-key val_init_ids
```

`cluster.yaml`은 `rl/cluster.example.yaml`을 복사해 채우라고 README가 말한다. 그 예시를 그대로 쓰는 명령은 없다.

평가 에피소드 명령(`eval.cmd`)은 `$RPENT_ENV/bin/python -m rpent.cli.main`에 `--robot libero --libero-type pro --suite --task --seed --output-dir --cuda-device --base-url {model_url} --vla-endpoint --sam3-endpoint --planner api --model openai-chat:{weights} --knowledge-profile proven --no-send-back-thinking --reasoning-effort low --max-turns 100 --max-tokens 32768 --planner-timeout-s 7200 --temperature 1.0 --top-p 0.95 --top-k 20 --presence-penalty 1.5 --generation-seed 3407`을 붙인다.

패치가 추가하는 플래그는 `--knowledge-profile`, `--no-send-back-thinking`, `--temperature`, `--top-p`, `--top-k`, `--presence-penalty`, `--generation-seed`다 (`rpent_f70d720.patch`의 `main.py`). `/workspace/RPent`의 `rpent/cli/main.py`와 저장소 검색에는 `knowledge_profile`, `knowledge-profile`, `no-send-back-thinking`, `send_back_thinking` 문자열이 없다. `--planner`, `--model`, `--base-url`, `--libero-type`, `--vla-endpoint`, `--sam3-endpoint`, `--cuda-device`는 이 체크아웃에 있다.

### 확인 필요

- Hugging Face에서 `sft/` 또는 `rl-v006/`를 받는 명령. 저장소에 없다. `{weights}`에 허브 id를 넘기면 vLLM이 받는지, 로컬 디렉터리여야 하는지도 이 저장소는 말하지 않는다.
- `RPENT_ENV`를 만드는 설치 명령. AgenticRoboRL은 변수 이름만 적고, RPent의 `uv pip install`은 이 저장소에 없다. RPent 분석 10번의 설치는 `/workspace/RPent`용이다.
- `/workspace/RPent`(`a744bd5`)에 위 `eval.cmd`를 그대로 실행하는 것. `--knowledge-profile`과 샘플링 플래그가 이 체크아웃에 없다.
- 평가 중 프록시 기록을 남기는 방법. 문서화된 RPent 평가는 `eval.direct: true`라 프록시를 시작하지 않는다. 학습용 `episode.cmd`는 프록시를 통하지만 `rl/proxy.py`가 샘플링을 temperature 1, top_p 1, top_k 0으로 덮어쓴다. 평가 샘플링을 유지한 채 기록하는 플래그는 없다.
- `rl/cluster.example.yaml`의 호스트를 채우기 전의 `multi_node_ctl` 실행.

## 6. 이 프록시를 우리 trace logger의 일부로 쓸 수 있는가

### 판정

프록시는 planner와 vLLM 사이 경계를 기록하는 부품으로는 재사용할 수 있다. teacher trace 로거 전체로는 부족하다. 관측 원본, 로봇 상태, `sim_state`, `decision.type`, primitive 실행 결과는 RPent 쪽에 아직 훅이 필요하다.

재사용해도 되는 범위는 `rl/proxy.py`의 `chat()`이 200 응답마다 쓰는 gzip JSON이다. 그 코드는 샘플링을 `RL_SAMPLING`으로 바꾸고, 스트림을 거절하고, 200이 아닌 호출은 파일을 쓰지 않는다. 공개 RPent 평가 경로는 이 프록시를 켜지 않는다. 우리 수집이 평가 프로토콜(init 1–10, temperature 1, top_p 0.95, top_k 20, presence penalty 1.5)의 모델 입력을 그대로 남겨야 하면, 문서화된 eval 명령만으로는 기록이 생기지 않는다.

`decision.type`이라는 필드는 AgenticRoboRL 전체와 `/workspace/RPent`의 LIBERO 로거에 없다. 결정에 해당하는 것은 모델 `message.tool_calls[].function.name`과 인자, 그리고 RPent `states.json`의 `command`다.

### 코드에서 확인한 대조

| 우리 trace에 필요한 것 | 프록시가 이미 남기는 것 | RPent 쪽에 아직 훅할 것 |
| --- | --- | --- |
| planner가 모델에 보낸 메시지 | `rl_turns/turn_NNN.json.gz`의 `messages`. data URL 이미지는 `image_ref`와 `<episode>/rl_images/<sha1>.<ext>` | 평가(`eval.direct`)는 프록시를 안 거친다. 학습 경로만 이 파일이 생긴다. 샘플링은 원 요청이 아니라 `RL_SAMPLING`으로 바뀐 뒤의 토큰이다. `client_sampling`에 원 값은 남는다 |
| 모델이 낸 도구 호출 | `message.tool_calls`, `output_token_ids`, `output_logprobs`, `finish_reason` | 호출이 실행됐는지는 여기 없다. 비-200, 스트림, 502는 파일이 없다 |
| 관측 이미지 | 요청 본문에 들어온 `image_url` data URL만 sha1로 저장 | RPent `dump_state`가 쓰는 `agentview`/`wrist` png, depth, world npz, high 해상도 (`notes/rpent_analysis.md` 8번). 프록시는 그 경로를 색인하지 않는다. depth·상태 배열은 이미지 data URL이 아니면 레코드에 없다 |
| 로봇 상태 | 해당 필드 없음. 텍스트로 메시지에 있으면 `messages` 문자열로만 남는다 | LIBERO 스텝의 로봇/EEF 상태. 프록시와 어댑터 모두 별도 필드를 쓰지 않는다. RPent `states.json`의 step state가 후보 (`EnvState` / `dump_state`) |
| `sim_state` | 없음. `patches/rpent/README.md`는 시뮬레이터 상태 기록이 이 패치에 없고, 나중 버전에서도 플래너에 들어가지 않는다고 한다 | RPent 분석 9번: 이 체크아웃에 `sim.get_state`/`set_state` 호출이 없다. 중간 상태 save/restore는 확인되지 않았다. 확인 필요 |
| `decision.type` | 이름 있는 필드 없음. 가장 가까운 값은 `message.tool_calls[].function.name`과 `function.arguments` | 실행된 primitive 이름·인자는 `Toolkit.execute_tool` 경계다 (`notes/rpent_analysis.md`의 훅 후보 1). 모델이 낸 호출과 실행된 호출이 같다는 보장은 프록시에 없다 |
| primitive 실행 결과 | 다음 요청의 `messages`에 하네스가 도구 결과를 다시 넣었을 때만 텍스트로 있음. 전용 결과 필드 없음 | `states.json`의 `command`/`result`/`terminated`/`truncated`, primitive 반환의 `success` (`pi0_pick`/`pi0_doubled`). 어댑터의 보상은 transcript `solved`인데, 공개 패치는 그 값을 항상 false로 두고 현재 RPent transcript에는 그 키가 없다 |
| 에피소드 성공/실패 | 프록시는 성공을 쓰지 않는다. 어댑터가 같은 디렉터리의 transcript `solved`로 `reward`를 붙인다 | 실패 에피소드도 `rl_turns`는 200 호출이 있었으면 남는다. 그러나 우리 체크아웃의 성공 라벨은 transcript `environment_success`가 아니라 마지막 `terminated` 또는 `LiberoToolkit.solved()`다 (`notes/rpent_analysis.md` 7번). 그 값을 프록시 레코드에 조인하는 코드는 없다 |
| VLA chunk (`prompt`, `max_chunks`, action) | 없음. planner 도구 인자의 `prompt`/`max_chunks`는 tool call JSON에 있을 수 있다 | `LiberoPrimitives._vlm_chunk`의 chunk별 관측과 action (`notes/rpent_analysis.md` 훅 후보 2). 기본 경로에는 파일로 남지 않는다 |

### 추론

로거는 두 겹이 필요하다. 안쪽은 이 프록시처럼 planner HTTP를 남기되, 우리 수집에서는 샘플링 덮어쓰기와 `eval.direct`를 그대로 쓰면 안 된다. 바깥쪽은 RPent `Toolkit.execute_tool`과 `dump_state`/`solved()`에서 관측 파일, 스텝 상태, primitive 반환, 최종 `terminated`를 같은 에피소드 키로 남겨 프록시의 `turn_index`와 맞추는 래퍼다. 그 조인은 `build_round.py`가 디렉터리와 assistant 턴 개수로 맞추는 방식과 같다. `decision.type`과 `sim_state`는 맞출 기존 필드가 없다.
