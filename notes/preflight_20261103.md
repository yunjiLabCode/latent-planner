# 재부팅 후 점검 (2026-11-03 21:16 KST)

스크립트 `bb330b5`. Hawaii HEAD도 그 커밋이다. 서버는 다시 띄우지 않았다.

다섯 조건은 모두 맞다.

| 항목 | 값 |
| --- | --- |
| CE 합계 | 0. 인식된 DIMM 7개, 각각 0 |
| 메모리 | `free -g` Mem total 440, used 4, available 435 |
| 루트 여유 | 65,418,432,512바이트 (약 61GB) |
| GPU 3 | 사용 안 함. 메모리 6MiB, 계산 프로세스 없음 |
| 캐시, TMPDIR | `env.sh` 경로 전부 `/data` 아래 |

`bash scripts/preflight_check.sh`는 기준 파일이 없으면 측정만 하고 종료 코드 1이다. 이번 실패 이유는 `/data/yunji/latent-planner-work/logs/preflight.baseline`이 없는 것뿐이다. `kern.log`는 433,378바이트다.

원본은 `/data/yunji/latent-planner-work/logs/preflight_20261103.md`이다.
