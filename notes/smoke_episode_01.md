# 단계 5 스모크 에피소드 (2026-10-29)

성공 (`success` true). `libero_spatial_task` task 0, init/seed 11. `states.json` 마지막 `step_idx` 10, action `release`, `terminated` true.

벽시계 1235 s. 에이전트 루프 1214.2 s. 턴 36/100. vLLM 요청 36. 서버는 끝난 뒤 멈췄다. tmux 세션 `stage5-episode`는 정지됨. GPU 3은 쓰지 않았고 7 MiB를 유지했다. 종료 후 GPU 0–3은 유휴, 7 MiB.

## 경로

- 출력: `/data/yunji/latent-planner-work/outputs/smoke/libero_spatial_task/task_00/seed_011/attempt_00`
- 로그: `/data/yunji/latent-planner-work/logs/stage5_episode.log`, `vllm_serve_stage5.log`, `install_log.md`, `smoke_episode_01.md`

## 시간 (1235 s)

- planner 1126.34 s. vLLM `e2e_request_latency_seconds` 합.
- VLA 9.43 s. `states.json` `elapsed_s`. `pi0_pick` 9.43 s, `pi0_doubled` 0 s.
- SAM3 9 s. segment 호출 3. `run.log` 구간은 1초. `states.json`에는 없다.
- 나머지 90.23 s. `move_to` 9.71 s, `set_gripper` 0.49 s, `release` 0.20 s, 그리고 시작과 1초 미만 읽기 전용 툴.

## prefix cache

히트 88.27% (1441440/1632978). 쿼리 수는 prompt 토큰 수와 같다. 첫 요청은 cold miss. prompt 토큰 12356에서 히트 0. 로그 마지막 문장: `Prefix cache hit rate: 88.3%`.

## 턴별 컨텍스트 토큰과 e2e 초

| 턴 | 컨텍스트 토큰 | e2e (s) |
|---:|---:|---:|
| 1 | 12356 | 8.86 |
| 2 | 23095 | 12.28 |
| 3 | 31289 | 13.31 |
| 4 | 34709 | 7.36 |
| 5 | 37386 | 65.50 |
| 6 | 37975 | 5.04 |
| 7 | 38187 | 4.17 |
| 8 | 38386 | 17.30 |
| 9 | 38601 | 4.47 |
| 10 | 38832 | 71.58 |
| 11 | 40122 | 10.91 |
| 12 | 41389 | 14.16 |
| 13 | 41630 | 9.96 |
| 14 | 41829 | 14.22 |
| 15 | 43077 | 222.06 |
| 16 | 43481 | 92.42 |
| 17 | 44702 | 26.66 |
| 18 | 45733 | 25.56 |
| 19 | 46895 | 29.65 |
| 20 | 47713 | 43.17 |
| 21 | 49616 | 91.47 |
| 22 | 49883 | 50.41 |
| 23 | 50906 | 34.82 |
| 24 | 51013 | 32.34 |
| 25 | 52001 | 28.22 |
| 26 | 53830 | 37.59 |
| 27 | 54061 | 31.86 |
| 28 | 54319 | 6.49 |
| 29 | 55079 | 30.10 |
| 30 | 55844 | 41.14 |
| 31 | 56056 | 5.97 |
| 32 | 56210 | 3.69 |
| 33 | 56351 | 5.87 |
| 34 | 56672 | 5.31 |
| 35 | 56813 | 11.17 |
| 36 | 56937 | 11.25 |

prompt 토큰 합 1632978. 지연 합 1126.34 s.

## trace

변환기 스키마 v0.2.1. 출력 `outputs/smoke/traces/smoke/libero_spatial_task_t00_seed011`. `matched` true. `conversion.warnings` 비어 있음. decisions 10. primitive: `move_to` 7, `pi0_pick` 1, `set_gripper` 1, `release` 1. roles `new` 10. `recovery_episodes` 비어 있음. context 호출 32. decisions에 넣지 않음.

## 영상

`RPENT_PRIMITIVE_VIDEO_DIR` `/data/yunji/latent-planner-work/outputs/primitive_videos`는 설정되어 상속됐으나 비어 있다. env 서버는 `video_cfg`를 저장하고 `RecordVideo.flush_video`는 호출하지 않는다. 에이전트 쪽 `episode.mp4`는 imageio에 ffmpeg/pyav 백엔드가 없어 실패했다. imageio 2.38.1의 FFMPEG 플러그인은 `imageio_ffmpeg`를 import하는데 그 패키지는 없고, `imageio-ffmpeg`는 설치하지 않았다. 남은 mp4는 없다. `/tmp/primitive_videos`는 만들어지지 않았다. 실행 전 스냅샷 대비 `/tmp` 새 경로 0, `/home/yunji` 증가 0. 이번 실행의 `TMPDIR`과 `HOME`은 `/data/yunji/latent-planner-work` 아래였다.

## 수집 규모

1235 s를 평균으로 두고 env 세트는 한 번에 하나.

- 2720 에피소드 (스위트 8 × task 10 × init 11–44) = 3359200 s = 933.1 h = 38.9일.
- 작은 계획: 스위트 4 × task 10 × init 11–20 = 400 에피소드 = 494000 s = 137.2 h = 5.7일.
- GPU 2 피크 17320 MiB / 24576 MiB. 풀 스택 둘이면 34640 MiB라서 한 번에 env 세트 1개. 피크 때 여유 7256 MiB.

이 에피소드는 `pi0_pick` 한 번으로 성공했고 recovery는 없다. 더 어려운 task는 더 길다. 지연은 컨텍스트 길이에 단조가 아니다.

## 출력 토큰

stage5 serve 로그에는 요청별 출력 수와 reasoning 분리가 없다. `thinking_token_budget=None`. 수는 `vllm:request_generation_tokens` 델타다. 합 27051.

r(output, latency)=0.960. r(prompt, latency)=0.018. r(output, prompt)=-0.032. prompt 길이는 위 컨텍스트 표와 같다.

가장 느린 턴이 출력도 가장 길다. 턴 15는 7862 tok, 222.06 s. 턴 16은 3304 tok, 92.42 s. 턴 21은 2070 tok, 91.47 s. 턴 10은 2758 tok, 71.58 s. 이 네 턴은 0.026–0.044 s/token이다. 출력 300 토큰 미만인데도 25–38 s가 남은 턴이 있다. 턴 17 (183, 26.66), 18 (192, 25.56), 19 (288, 29.65), 25 (187, 28.22), 26 (225, 37.59), 29 (166, 30.10).

| 턴 | 출력 토큰 | e2e (s) |
|---:|---:|---:|
| 1 | 119 | 8.86 |
| 2 | 62 | 12.28 |
| 3 | 52 | 13.31 |
| 4 | 55 | 7.36 |
| 5 | 1272 | 65.50 |
| 6 | 108 | 5.04 |
| 7 | 94 | 4.17 |
| 8 | 646 | 17.30 |
| 9 | 119 | 4.47 |
| 10 | 2758 | 71.58 |
| 11 | 159 | 10.91 |
| 12 | 384 | 14.16 |
| 13 | 329 | 9.96 |
| 14 | 477 | 14.22 |
| 15 | 7862 | 222.06 |
| 16 | 3304 | 92.42 |
| 17 | 183 | 26.66 |
| 18 | 192 | 25.56 |
| 19 | 288 | 29.65 |
| 20 | 847 | 43.17 |
| 21 | 2070 | 91.47 |
| 22 | 1680 | 50.41 |
| 23 | 397 | 34.82 |
| 24 | 305 | 32.34 |
| 25 | 187 | 28.22 |
| 26 | 225 | 37.59 |
| 27 | 995 | 31.86 |
| 28 | 160 | 6.49 |
| 29 | 166 | 30.10 |
| 30 | 466 | 41.14 |
| 31 | 125 | 5.97 |
| 32 | 89 | 3.69 |
| 33 | 148 | 5.87 |
| 34 | 89 | 5.31 |
| 35 | 324 | 11.17 |
| 36 | 315 | 11.25 |
