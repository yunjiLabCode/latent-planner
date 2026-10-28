# Project context

## 목표
HarnessVLA(RPent) 구조에서 큰 LLM planner(teacher)가 시행착오로 배운
primitive 선택·재시도·복구 전략을, 토큰을 생성하지 않는 경량 latent planner로 이전한다.

## 이번 단계 범위
Teacher 실행 기록(trace)을 수집하는 인프라만 만든다. 모델 학습 코드는 아직 만들지 않는다.

## 구성
- Harness: RPent (HarnessVLA 공개 코드), 벤치마크 LIBERO-PRO
- Frozen VLA: RPent 기본 π0.5 RLinf checkpoint (변경 금지)
- Teacher planner: AgenticRoboRL 공개 Qwen3.5-9B checkpoint (vLLM 서빙)
- 데이터 분리: teacher 수집은 initial state 11~44, 평가는 1~10 (AgenticRoboRL과 동일)

## 규칙
- 기존 RPent / AgenticRoboRL 동작을 바꾸지 않는다. trace는 RPent 출력 파일을 src/trace 변환기로 바꿔서 만든다. RPent 수정이 꼭 필요하면 collect 브랜치에서 기본 동작이 같도록 최소한으로 한다.
- 존재가 확인되지 않은 API는 쓰지 않는다. 확실하지 않으면 코드를 쓰기 전에 "확인 필요"라고 말한다.
- 실패 에피소드도 반드시 저장한다.
- 실행은 공용 GPU 서버에서 한다. sudo, 시스템 패키지 설치 금지. hawaii에서는 /data/yunji/latent-planner-work/ 안에서만 파일을 만들고 수정한다. 홈(/)은 디스크가 거의 차 있어서 쓰지 않는다. /tmp도 공용이라 쓰지 않는다.
- GPU는 CUDA_VISIBLE_DEVICES로 지정된 것만 사용한다.
- 30분 이상 걸리는 실행은 직접 돌리지 말고 tmux로 실행하는 스크립트만 만든다.
- 각 단계 시작 전 git commit 상태를 확인한다.
- 코드 수정, 커밋, push는 이 작업 공간에서만 한다.
- hawaii는 실행 전용이다. hawaii에서 코드를 수정하거나 커밋, push하지 않는다. hawaii는 읽기 전용 토큰으로 clone/pull만 한다.
- 실행 결과와 로그는 hawaii의 /data/yunji/latent-planner-work/ 에만 둔다.
