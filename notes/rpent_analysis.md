---
cursor:
  subagentId: "bc-84dbf0a8-66e4-5916-ba2d-1a2b9a3ed1c6"
---

# RPent LIBERO-PRO 분석

대상: `/workspace/RPent`, 커밋 `a744bd5f128ebef3cb8c6736cf7cd98adff681f1` (`https://github.com/yunjiLabCode/RPent.git`). `git submodule update --init RPent`만 실행했다. 다른 서브모듈, 브랜치, 커밋, 코드 수정, 패키지 설치는 하지 않았다.

평가 모드(`--explore` 없음)를 기준으로 적는다. `--planner flash`는 LLM이 없고, 아래 2번에서 따로 구분한다.

## 1. LIBERO-PRO eval 에피소드는 어디서 시작하고 끝나는가

### 코드에서 확인

한 번의 `rpent` 프로세스가 에피소드 하나다. `main()`은 `--explore`가 아니면 `sessions = 1`로 고정하고, `LiberoToolkit`는 evaluation 모드에서 `reset` 도구를 등록하지 않는다.

- 진입: `rpent/cli/main.py`의 `main()`.
- 태스크 식별: `robots/libero/robot_spec.py`의 `_parse_config()`. `--suite`, `--task`, `--seed`로 `recipe_tag`(`{suite without libero_}_t{task}_s{seed}`)와 출력 디렉터리를 만든다. 기본 경로는 `<repo>/logs/<timestamp>_<suite>_t<task>_s<seed>/`.
- 변형: `_spawn_env_server()`가 `LIBERO_TYPE`을 `args.libero_type` 또는 `get_libero_type()`(`rpent/utils/config.py`, 기본 `"pro"`)으로 넘긴다. 문서(`docs/source-en/rst_source/simulators/libero.rst`)의 pro suite 예: `libero_object_task`, `libero_object_swap`.
- 시뮬레이터 생성: `robots/libero/env_server.py`의 `make_env()` → `build_env_cfg()`. `auto_reset: False`, `is_eval: True`, `use_fixed_reset_state_ids: True`, `specific_reset_id = 이전 task init-state 개수 합 + (seed % trials)`. 환경 클래스는 외부 패키지 `rlinf.envs.sim.libero.libero_env.LiberoEnv`다. 이 저장소에는 그 소스가 없다.
- 에피소드 시작(시뮬레이터 reset): `LiberoToolkit.init_primitives()` → `LiberoPrimitives.reset()` → `LiberoEnvClient.reset()` → RPC `env.reset` → `LiberoEnvFacade.reset()` → `LiberoEnv.reset()`. 직후 `dump_state()`가 step 0을 기록하고 `start_recording()`이 켜진다.
- 에이전트 루프 시작: `main()`의 `planner.solve()`.
- 물리 에피소드 종료 래치: `LiberoEnvClient.check_done()`이 `step`/`chunk_step` 반환의 `terminated`/`truncated`를 OR한다. 그 뒤 `step`/`chunk_step`은 assert로 거부된다. `max_episode_steps` 기본값은 10000 (`build_env_cfg`, CLI `--max-episode-steps`).
- 런 종료: `planner.solve()`가 반환된 뒤 `toolkit.close()` → `LiberoToolkit.close()`가 flywheel을 닫고 `episode.mp4`를 저장한다. 이어서 `main()`이 데몬을 멈추고 `transcript_<recipe_tag>.json`을 쓴다. 플래너 쪽 종료 조건은 `finish` 도구, `max_turns`(기본 100), timeout(`CELL_TIMEOUT_S` 또는 1200초), 예외다.

### 추론

프롬프트(`robots/libero/prompts/evaluate.py`)는 “reset 없는 one-shot”이라고 말한다. 도구 등록과 `sessions = 1`이 그 제약을 코드로 뒷받침한다. BDDL 성공 판정 식 자체는 `LiberoEnv` 안에 있어 이 트리에서는 확인하지 못했다.

## 2. planner(LLM) 요청은 어디서 보내고 응답은 어디서 받는가

### 코드에서 확인

공통 인터페이스는 `rpent/planner/base.py`의 `Planner.solve()` / `build_planner()`.

- `api`: `rpent/planner/api_loop.py`의 `ApiAgentLoop.solve()` → `_solve()`. pydantic-ai `Agent`를 만들고 `_Session.run()` → `_run_conversation()` → `agent.run(...)`이 모델 요청과 응답을 SDK에 맡긴다. 모델 객체는 `build_api_model()`(`infer_model`). 설정은 `_build_model_settings()`.
- `claude_code`: `rpent/planner/claude_code.py`의 `ClaudeCodePlanner._solve_async()`. `claude_agent_sdk.query(prompt=..., options=...)`의 async iterator가 응답 메시지다. 각 메시지는 `_emit()`에서 JSONL과 텍스트로 기록된다.
- `codex`: `rpent/planner/codex.py`의 `CodexPlanner`. 세션 스트림 이벤트를 `_Recorder.observe()`가 소비한다. 출력은 `codex_<recipe_tag>.txt`와 `.stream.jsonl`.
- `flash`: `rpent/planner/flash.py`의 `FlashPlanner.solve()`는 LLM을 호출하지 않는다. `RobotSpec.run_flash` → `robots/libero/flash/replay.py`의 `execute()`가 기록된 plan을 `toolkit.execute_tool`로 재생한다.

세 LLM 백엔드는 도구 실행 전에 MCP 또는 pydantic-ai toolset으로 toolkit을 노출한다. Claude/Codex용 HTTP MCP는 `rpent/planner/utils/http_mcp_server.py`의 `build_mcp_server()`.

### 추론

Qwen/vLLM teacher를 이 트리의 `api` planner에 붙이려면 `--model`과 `--base-url`로 `build_api_model()` 경로를 쓰는 형태가 맞다. 그 조합이 이 커밋에서 검증된 설정인지는 확인하지 않았다.

## 3. planner tool call(primitive call)은 어디서 파싱되고 실행되는가

### 코드에서 확인

선언은 `rpent/tools/base.py`의 `@tool`이 함수 시그니처로 JSON schema를 만든다. LIBERO primitive는 `robots/libero/tools.py`의 `LiberoPrimitives` 메서드다. `LiberoToolkit._register_libero_tools()`가 이를 등록하고, primitive는 `_execute_primitive()`로 감싼다.

실행의 단일 지점:

1. 플래너가 인자 dict를 만든다.
   - api: `ApiAgentLoop._HarnessToolkit.execute()`가 JSON Schema(`Draft202012Validator`)로 검사한 뒤 `execute_tool()`.
   - claude/codex: MCP `build_mcp_server()`의 `_call_tool()`이 prefix를 벗기고 `execute_tool()`.
   - flash: `robots/libero/flash/replay.py`의 `execute()`가 `toolkit.execute_tool()`을 직접 호출.
2. `rpent/planner/base.py`의 `execute_tool()`이 `Toolkit.execute_tool`을 스레드에서 호출한다.
3. `rpent/tools/toolkit.py`의 `Toolkit.execute_tool()`이 `tool.args_schema.model_validate(input_dict, strict=True)`로 다시 검증하고 `tool(**kwargs)`를 호출한다.
4. 상태가 바뀌는 도구는 이어서 `LiberoToolkit.get_env_state()` → `dump_state()`.

### 추론

파싱은 플래너 SDK(pydantic-ai / Claude Agent SDK / Codex SDK)가 tool-call JSON을 dict로 바꾸는 구간이고, 이 저장소가 그 JSON을 직접 자르지는 않는다. 이 저장소에서 확인되는 경계는 schema 검증과 `Toolkit.execute_tool`이다.

## 4. `vla_act`의 `prompt`, `max_chunks`, `stop`은 어디서 처리되는가

### 코드에서 확인

이 커밋의 Python 코드에 `vla_act`라는 함수나 도구는 없다. 문자열은 RoboCasa 프롬프트(`robots/robocasa/prompts/evaluate.py`)의 역사적 이름과 테스트 fixture에만 있다.

LIBERO VLA primitive는 `LiberoPrimitives.pi0_pick(prompt, max_chunks=24, ...)`와 `pi0_doubled(prompt, max_chunks=20)`이다. `stop`이라는 인자는 없다.

- `prompt`: 두 메서드가 `instr = prompt`로 받은 뒤 `_vlm_chunk(instr)`에 넘긴다. `_vlm_chunk()`는 `obs["task_descriptions"]`를 그 문자열로 덮고 `Pi05VLAClient.predict()`를 호출한 다음 `finally`에서 원래 task 문장을 복구한다.
- `max_chunks`: `for c in range(max_chunks)`의 상한이다.
- 조기 종료: `pi0_pick`은 하강·재상승·그리퍼 닫힘 휴리스틱이 맞거나 `env.terminated`/`truncated`이면 `break`. `pi0_doubled`은 `terminated`/`truncated`일 때만 `break`. 인자 `stop`이 아니다.
- 이름만 비슷한 `LiberoPrimitives.stop_recording()`은 프레임 버퍼를 비우는 함수다.

`Pi05VLAClient.predict()`(`rpent/robots/components/pi05_vla_client.py`)는 `_encode_obs_libero()`로 관측을 만든 뒤 `BaseVLAClient.predict()`가 RPC `vla.predict`를 호출한다. 서버 `Pi05VLAServer.predict()`는 `options["mode"]`(기본 `"eval"`)만 보고 `predict_action_batch()`를 호출한다. `stop` 옵션은 없다.

### 추론

AgenticRoboRL식 `vla_act(..., stop=...)`를 이 코드에 그대로 넣을 자리는 없다. teacher trace에서 그에 해당하는 필드는 `pi0_pick`/`pi0_doubled`의 `prompt`, `max_chunks`, 그리고 루프 `break`다.

## 5. primitive 실행 후 성공/실패(post-condition)는 어디서 결정되는가

### 코드에서 확인

primitive 반환값과 환경 `terminated`는 서로 다르다.

- `pi0_pick`: 시작 EEF z 대비 `descent_thresh`(기본 0.10m) 하강 후, `lift_thresh`(기본 0.05m) 재상승, 그리고 `gripper_open_thresh <= grip < gripper_closed_thresh`이면 `success = True`이고 루프를 멈춘다. 그 전에 환경이 끝나면 `success = self.env.terminated`.
- `pi0_doubled`: `success`와 `task_success`는 `self.env.terminated`만 반영한다. docstring은 중간 contact skill에서 `success=false`가 실패를 뜻하지 않는다고 적는다.
- `move_to`: `success` 키가 없다. 거리 `tol`과 yaw면 `break`하고 `final_dist_m`을 반환한다. `terminated`/`truncated`도 같이 넣는다.
- 실행 직후 `LiberoToolkit.get_env_state()`가 `dump_state()`로 그 시점의 `primitives.env.terminated`를 `StepRecord`에 넣고 `self._solved |= record.terminated`를 한다. 도구가 돌려준 `success`와는 별개다.
- 프롬프트 `robots/libero/prompts/evaluate.py`는 `pi0_pick.success`를 hint로 두고, 목표를 top-level `terminated == true`라고 쓴다.
- flash 재생만 `robots/libero/flash/replay.py`의 `pick_succeeded()`가 `pi0_pick` 결과의 `success is True`를 읽는다.

### 추론

공식 task 성공의 술어(어떤 물체가 목표 region에 있는지)는 `LiberoEnv.step`이 돌려주는 `terminated` 안에 있다. 그 계산은 이 저장소에 없고 RLinf `LiberoEnv`에 있다.

## 6. Task Specific Memory와 Global Memory는 어디서 읽고 쓰는가

### 코드에서 확인

평가 기본 프로필은 `hf`다. `robots/libero/memory.py`의 `prepare_memory()` → `sync_version()`이 Hugging Face `RLinf/RPent-memory`(또는 `RPENT_MEMORY_HF_REPO`)에서 코퍼스를 받고 `config.prompt_vars["memory_dir"]`에 넣는다. 버전은 `select_version()`: auto일 때 planner가 flash면 `GPT_5.5_xhigh`, 아니면 `select_model_version()`(`gpt-5.5` → `GPT_5.5_xhigh`, `gpt-6-astra` → `GPT_6_astra_low`, 그 외 기본 `GPT_5.5_xhigh`).

`robots/libero/robot_spec.py`의 `get_toolkit()`은 `MemoryManager(memory_access="read_only")`를 만든다. explore일 때만 `"inbox_write"`이고 inbox는 `_internal/inbox/<recipe_tag>`다.

- 읽기: `rpent/tools/common.py`의 `CommonTools.read_text_file()` / `list_dir()` → `MemoryManager.authorize_read()` / `list_directory()`. 허용 prefix는 `global`, `task-family`, `task-specific`, `results`, 그리고 루트의 `*.md` (`MemoryManager._authorize()`).
- 평가 중 쓰기: 같은 함수가 memory root 아래 쓰기를 `PermissionError`로 거절한다. `CommonTools.write_text_file()`은 출력 디렉터리의 audit/recipe처럼 memory root 밖만 쓸 수 있다.
- 프롬프트가 가리키는 경로 (`prompts/evaluate.py`의 `LOCAL_MEMORY_PROFILE`): `{{memory_dir}}/global/`, `task-family/`, `task-specific/{{reference_tag}}.json`과 `_recipe.jsonl`. `reference_tag`는 같은 suite/task의 seed 0 (`_parse_config`).
- 출판 쓰기: explore가 끝나고 `main()`이 `MemoryManager.merge_memory()`를 호출할 때다. inbox의 `*.md`는 frontmatter `scope`에 따라 `global/` 또는 `task-family/`로 합쳐지고, solved이고 audit+recipe가 둘 다 있으면 `task-specific/`로 복사된다. `rebuild_index()`가 `MEMORY.md`를 다시 쓴다. 조건은 `--explore`, `--auto-merge-memory`(기본 on), `agent_error` 없음, operator abort 없음이다. 평가 런은 이 분기에 들어가지 않는다.

### 추론

HF eval은 디스크의 출판 파일을 도구로 읽는 구조다. 모델이 실제로 어떤 파일을 열었는지는 `read_text_file` 호출로만 남고, 별도의 memory-access 로그 파일은 없다.

## 7. 에피소드의 최종 성공은 어디서 결정되는가

### 코드에서 확인

LIBERO `RobotSpec`(`get_robot_spec()`)은 `finalize_run`을 설정하지 않는다. 기본값은 `None` (`rpent/robots/robot_spec.py`). 그래서 `main()`에서 `environment_success`를 채우는 분기(`if robot_spec.finalize_run is not None`)는 LIBERO에서 실행되지 않고, transcript의 `environment_success`는 `None`으로 남는다.

실제로 쓰이는 플래그:

- `LiberoToolkit._solved`는 primitive 이후 `get_env_state()`에서 `record.terminated`가 한 번이라도 참이면 참이 된다. `solved()`가 그 값을 반환한다.
- `main()`은 `supports_exploration`이 참이면(LIBERO는 참) 세션 끝에서 `toolkit.solved()`를 `solved`에 넣고, 참일 때만 `write_recipe()` → `write_recipe_from_states()`로 `*_recipe.jsonl`을 쓴다. 이 호출은 explore 전용이 아니다.
- 문서 `docs/source-en/rst_source/simulators/libero.rst`: 성공은 최종 상태의 top-level `terminated`다. step limit이나 planner `finish`는 성공 라벨이 아니다. `view_env_state(step=-1)`이 그 필드를 보여 준다.
- `CommonTools.finish(status, summary)`는 에이전트 루프만 멈춘다. `status`는 환경 성공이 아니다.
- flywheel(`--collect-flywheel-data`)을 켠 경우에만 `robots/libero/flywheel.py`의 `success_mask()`가 transition의 `terminated`를 쓰고, `EpisodeWriter`가 `episode.json`의 `is_success`를 그 마스크의 training step 유무로 쓴다. 기본 eval은 flywheel이 꺼져 있다.

### 추론

trace에 넣을 최종 라벨은 transcript의 `environment_success`가 아니라, 마지막 `states.json` step의 `terminated` 또는 close 직전의 `LiberoToolkit.solved()`다. `truncated`만 참인 경우는 성공이 아니다 (`check_done`은 둘을 따로 래치한다).

## 8. 이미 저장되는 로그

### 코드에서 확인

출력 루트는 `_parse_config()`와 `init_output_dir()` (`rpent/utils/logging.py`). 문서 표: `docs/source-en/rst_source/guides/cli.rst`의 “Output Files”.

| 무엇 | 경로 | 형식 | 쓰는 곳 |
| --- | --- | --- | --- |
| 프로세스 로그 | `<output>/run.log` | 텍스트, `YYYY-MM-DD HH:MM:SS LEVEL [name] message` | `init_output_dir` |
| 플래너 transcript | `<output>/transcript_<recipe_tag>.json` | JSON 한 객체. messages, finish, stats, error. `environment_success`는 LIBERO에서 null. 이미지는 placeholder | `main()` |
| 상태·액션 타임라인 | `<output>/states.json` | JSON. `run_artifacts`, `steps[]` (`command`, `result`, `terminated`, `truncated`, `elapsed_s`, `artifacts`) | `EnvState._write_manifest()` |
| 스텝 관측 | `<output>/<name>/<step:02d>.<ext>` | png, npz(`array` 키), json | `dump_state` / `_save_observation_artifacts` |
| 에피소드 영상 | `<output>/episode.mp4` | H.264, 20 fps | `LiberoToolkit.close` |
| primitive 클립 | `action_<tool>.mp4`를 스텝 디렉터리에 | mp4. dashboard sink가 켜진 경우만 | `LiberoToolkit.get_env_state` |
| env/vla/sam3 서버 stdout | `env_server.log`, `vla_server.log`, `sam3_server.log` | 텍스트 | `ProcessDaemon` log_path |
| 성공 시 recipe | `<output>/<recipe_tag>_recipe.jsonl` | JSONL command | `write_recipe_from_states`, `solved()`일 때 |
| claude | `<output>/claude_<recipe_tag>.txt`와 `.txt.stream.jsonl` | 텍스트 / JSONL | `ClaudeCodePlanner` |
| codex | `<output>/codex_<recipe_tag>.txt`, `.stream.jsonl`, `.last` | 텍스트 / JSONL | `CodexPlanner` |
| api | 별도 raw stream 없음. transcript JSON이 대화 기록 | JSON | `ApiAgentLoop`가 messages를 돌려주고 `main()`이 저장 |
| dashboard timeline | 메모리 `DashboardState._timeline` | 프로세스 안 JSON. 파일로 저장하지 않음 | `on_step()` |
| flywheel (플래그 필요) | `<flywheel-root>/raw/libero/<suite>/task_XX/seed_YYY/episode_*/` | `episode.json`, `transitions.npz`, `proposals.npz` | `EpisodeWriter` |

스텝 파일 예: `agentview.png`, `agentview_policy.png`, `agentview_depth.npz`, `agentview_world.npz`, `agentview_metadata.json`, `wrist.png`, `wrist_depth.npz`, `wrist_world.npz`, `wrist_metadata.json`, `agentview_high.png`, `agentview_world_high.npz`, `wrist_high.png`, `wrist_world_high.npz`.

`build_env_cfg()`의 `video_cfg.save_video=True`, `video_base_dir="/tmp/primitive_videos"`는 `LiberoEnv`에 전달된다. 그 영상을 쓰는 코드는 이 저장소에 없다.

VLA `predict` 입출력(프롬프트, action chunk)은 기본으로 파일에 남지 않는다. flywheel의 `proposals.npz`에만 instruction과 action이 들어간다.

### 추론

“action timeline”이라는 이름의 파일은 없다. 디스크의 타임라인은 `states.json`의 `steps`다. dashboard의 timeline은 그 레코드의 실시간 투영이다.

## 9. 시뮬레이터 상태 save/restore API가 있는가

### 코드에서 확인

이 트리에서 `sim.get_state`, `sim.set_state`, MuJoCo `MjSimState` save/restore 호출은 없다.

robosuite를 건드리는 곳은 `LiberoEnvFacade.get_action_spec()`뿐이다. `worker.env_call("__getattribute__", args=["action_spec"], target="robosuite")`와 `robot_configs` 조회다. 상태 저장이 아니다.

장면 복원은 `LiberoPrimitives.reset()` → `LiberoEnv.reset()`이다. explore의 `reset` 도구(`LiberoToolkit._reset_episode`)만 이를 다시 호출한다. 평가는 그 도구가 없다. reset이 복원하는 것은 `make_env()`가 고른 `specific_reset_id`의 초기 상태다. 임의 중간 상태를 저장했다가 되돌리는 API는 이 저장소에 없다.

### 추론

LIBERO는 robosuite 기반이라는 문서 설명과 `env_call(..., target="robosuite")`는 맞다. robosuite `MjSim.get_state`/`set_state`를 RPent가 쓰지는 않는다. RLinf `LiberoEnv`가 내부에서 쓸 가능성은 이 체크아웃만으로는 확인되지 않았다. 확인 필요.

## 10. 설치·실행 의존성과 GPU 요구

### 코드와 문서에서 확인

- Python: `pyproject.toml`은 `>=3.10,<3.13`. 문서 quickstart와 LIBERO 페이지는 3.11을 쓴다.
- 설치: `uv pip install -e ".[libero-pro]"`. extra `libero-pro`는 `rpent[libero]`와 `rpent-liberopro @ git+https://github.com/RLinf/LIBERO-PRO.git@rpent`. `libero`는 `rpent[rlinf,sam3]`, `rpent-openpi @ git+https://github.com/RLinf/openpi.git@rpent`, `rpent-libero @ git+https://github.com/RLinf/LIBERO.git@rpent`, `mujoco==3.3.0`.
- Torch: quickstart는 OpenPI 요구로 `torch==2.7.1`, `torchvision==0.22.1`, GPU/드라이버에 맞는 CUDA 빌드. `pyproject.toml` classifier는 `NVIDIA CUDA :: 12 :: 12.4`.
- 자산: `liberopro-download-assets --skip-existing`.
- 가중치: `PI05_CHECKPOINT_PATH` = Hugging Face `RLinf/RLinf-Pi05-LIBERO-130-fullshot-SFT`. `SAM3_CHECKPOINT_PATH` = `facebook/sam3`의 `sam3.pt`.
- 실행: `MUJOCO_GL=egl` (`_spawn_env_server` env_overrides). GPU는 `--cuda-device`. env 서버는 `CUDA_VISIBLE_DEVICES`를 비우고 `MUJOCO_EGL_DEVICE_ID`와 `torch.cuda.set_device`로 고정한다 (`env_server.py` `main`). VLA 서버는 `--cuda-device`일 때 `CUDA_VISIBLE_DEVICES`를 그 번호로 덮어쓴다 (`pi05_vla_server.py` `main`).
- 플래너 키: api Anthropic `ANTHROPIC_API_KEY`, OpenAI `OPENAI_API_KEY`, claude `ANTHROPIC_BASE_URL`, codex `CODEX_API_KEY` / `CODEX_BASE_URL` (`docs/source-en/rst_source/guides/cli.rst`).
- OS: 문서 기준 Linux, NVIDIA GPU, CUDA, EGL. 한 환경에 LIBERO variant는 하나만.

### 추론

필요 VRAM GB 숫자는 이 문서와 `pyproject.toml`에 없다. OOM은 quickstart가 다른 GPU 프로세스를 보라고만 한다.

## 트레이스 로깅 훅 후보

구현하지 않았다. 기존 동작을 바꾸지 않으려면 config 플래그 래퍼로 두는 자리가 아래 세 곳이다.

1. `rpent/tools/toolkit.py`의 `Toolkit.execute_tool`. api, claude, codex, flash가 모두 여기로 모인다. schema 검증 직후의 인자, 반환 `ToolResult`, 그리고 LIBERO면 이어지는 `get_env_state`의 `terminated`까지 한 번에 남길 수 있다. primitive 선택·재시도·복구의 타임라인이다.
2. `robots/libero/tools.py`의 `LiberoPrimitives._vlm_chunk`. `pi0_pick`/`pi0_doubled` 한 호출 안에 VLA forward가 `max_chunks`번 있다. 바깥 도구 로그만으로는 chunk별 `prompt`(덮어쓴 `task_descriptions`)와 action이 빠진다. 기본 경로에는 이 입출력이 파일로 남지 않는다.
3. `LiberoToolkit.init_primitives`(reset과 step 0)와 `LiberoToolkit.close`, 그리고 `main()`이 `toolkit.solved()`를 읽는 지점. 에피소드 경계와 최종 `terminated`가 여기 있다. transcript의 `environment_success`는 LIBERO에서 채워지지 않으므로 그 필드를 성공 라벨로 쓰면 안 된다. 실패 에피소드도 `close()`는 항상 호출된다.
