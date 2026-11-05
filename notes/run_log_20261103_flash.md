# 2단계 flash replay (2026-11-03)

처리량 측정은 시작하지 않았다. git 수정은 없다. GPU 3은 쓰지 않았다. 중단 조건은 없었다. 원본 로그는 `/data/yunji/latent-planner-work/logs/run_log_20261103_flash.md`이다.

## 시작 전 (2026-11-03 16:38 KST)

| 항목 | 값 |
| --- | --- |
| `/` 여유 | 61G (65,370,046,464바이트) |
| `dimm_ce_count` | 0 |
| `kern.log` | 4,695바이트 |
| GPU 2 | 계산 프로세스 없음. Xorg만 |
| 경로 | 캐시, `TMPDIR`, 이번 출력과 로그는 `/data` 아래 |

## 실행

이 체크아웃에는 `--planner flash`가 없다. batch01 goal task 1, init 11의 `states.json` 명령을 `LiberoToolkit.execute_tool`로 두 번 재생했다. π0.5 `sample_noise`는 시드를 받지 않고, VLA 서버는 `mode` 외 predict 옵션을 거절한다. 두 재생 모두 시드 없는 한 서버에서 돌렸다.

## 상태 비교

reset과 명령 0 `move_to`는 두 재생과 원본이 비트 단위로 같다. 처음 어긋나는 명령은 1번 `pi0_pick`(step 2)이다. 시드 없는 A 대 원본, B 대 원본, A 대 B 모두 여기서 갈라진다. `terminated`는 매 단계 같았고 마지막도 `true`다. eef 차이가 가장 큰 곳은 두 번째 `pi0_pick`에서 B 대 원본 0.306 m다.

## 복원

두 재생 모두 `LiberoPrimitives.reset` 복원에 성공했다. 복원 후 eef, gripper, `terminated`는 원본 step 0과 같다. 최대 절대차는 0이다. 복원 전에는 끝난 자세에 `terminated` true였고, 복원 후에는 홈에 `terminated` false다. eef 최대 절대 변화는 A 0.220 m, B 0.220 m다.

## 끝

`dimm_ce_count`는 0이다. `kern.log`는 5,001바이트로 306바이트 늘었다. 루트 여유는 5GB 위다. 끝난 뒤 계산 프로세스는 없고 GPU 메모리는 0–3 모두 6MiB다.

출력은 `/data/yunji/latent-planner-work/outputs/flash_replay_20261103/unseeded_a`와 `unseeded_b`다.
