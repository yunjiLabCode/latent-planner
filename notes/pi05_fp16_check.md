# pi0.5 fp16 in-memory check

2026-10-28. Hawaii GPU 2, NVIDIA TITAN RTX, sm_75. `CUDA_VISIBLE_DEVICES=2`. GPU 3은 쓰지 않았다. 가중치 파일은 수정하지 않았다. 수집 dtype은 바꾸지 않았다. 단계 4는 시작하지 않았다.

- π0.5: `RLinf/RLinf-Pi05-LIBERO-130-fullshot-SFT` snapshot `6222623f635769bfc73c9472e29fab9b7fd8e027`
- SAM3: `sam3.pt` sha256 `9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e`
- 출처: `https://www.modelscope.cn/models/facebook/sam3/resolve/master/sam3.pt`
- torch `2.7.1+cu128`. `is_bf16_supported(including_emulation=False)`는 `False`.

## 시간

워밍업 3회 후 10회. `torch.cuda.synchronize()`로 감싼 wall clock.

π0.5 bf16 predict (같은 관측, action `[1, 5, 7]`): 평균 0.838771초, 중앙값 0.838269초, 최대 0.841987초.

SAM3 segment (`the robot arm`, 서로 다른 reset 이미지, float32 가중치, 내부 autocast bf16): 평균 1.179573초, 중앙값 1.179148초, 최대 1.182347초. 10회 모두 found.

## fp16 비교

`Pi05VLAFacade`가 로드한 뒤 메모리에서 bf16 파라미터와 버퍼만 `float16`으로 바꿨다. float32로 남는 patch embedding과 일부 LayerNorm은 그대로다. 변환한 파라미터 원소 수는 3,497,036,912. `model.safetensors`와 `sam3.pt`의 mtime은 전과 같다.

가중치만 바꾸면 SigLIP `layer_norm1`에서 `expected scalar type Float but found Half`로 죽는다. vision patch embedding이 float32라 activation이 float32로 들어가고, stock forward의 bf16 맞춤은 `q_proj.weight`가 아직 bf16일 때만 돈다. Linear만 맞춘 시도는 Gemma attention에서 `expected scalar type Half but found Float`로 다시 죽었다.

아래 숫자는 프로세스 안 래퍼로 잰 것이다. Linear와 Conv2d 입력을 가중치 dtype에 맞추고, LayerNorm은 가중치 dtype으로 계산한 뒤 원래 activation dtype으로 되돌린다. 파일과 수집 설정은 바꾸지 않았다.

LIBERO-PRO `libero_spatial_task` reset 20개. task 0–9의 trial 11과 28을 요청했고, task 3과 7은 이 자산에서 trial 11에 도달하는 init이 없어 빠졌다. task 0의 trial 12–15로 20개를 채웠다. 사용한 trial은 모두 11–44 안이다. 같은 시드를 bf16과 fp16 predict 직전에 다시 넣었다.

- 평균 절대 오차: `2.56317637e-03`
- 최대 절대 오차: `1.10480785e-02`
- bf16 action 평균 절대값: `2.95808823e-01`
- 평균 오차 / bf16 크기: `8.66497605e-03`
- 최대 오차 / bf16 크기: `3.73487119e-02`
- fp16 NaN: 없음. inf: 없음.

fp16 predict (워밍업 3, 측정 10): 평균 0.334972초, 중앙값 0.335304초, 최대 0.341821초. bf16 평균 / fp16 평균 = 2.504.

| # | task | trial | reset id | mean abs err | max abs err | bf16 mean abs |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 | 11 | 11 | 2.735540e-03 | 7.172666e-03 | 3.435963e-01 |
| 1 | 0 | 28 | 28 | 2.329753e-03 | 7.772088e-03 | 3.185713e-01 |
| 2 | 1 | 11 | 61 | 2.213084e-03 | 5.892456e-03 | 3.025714e-01 |
| 3 | 1 | 28 | 78 | 2.567404e-03 | 1.104808e-02 | 2.765174e-01 |
| 4 | 2 | 11 | 111 | 2.900824e-03 | 7.942915e-03 | 2.865736e-01 |
| 5 | 2 | 28 | 128 | 2.317231e-03 | 7.258927e-03 | 3.133331e-01 |
| 6 | 4 | 11 | 161 | 3.030719e-03 | 8.369654e-03 | 2.652622e-01 |
| 7 | 4 | 28 | 178 | 2.213036e-03 | 6.956741e-03 | 3.111330e-01 |
| 8 | 5 | 11 | 211 | 2.273558e-03 | 6.541877e-03 | 3.325414e-01 |
| 9 | 5 | 28 | 228 | 2.728682e-03 | 8.099139e-03 | 3.264315e-01 |
| 10 | 6 | 11 | 261 | 3.104724e-03 | 7.014707e-03 | 2.225366e-01 |
| 11 | 6 | 28 | 278 | 2.343177e-03 | 5.942458e-03 | 2.405724e-01 |
| 12 | 8 | 11 | 311 | 2.331364e-03 | 9.230919e-03 | 3.040126e-01 |
| 13 | 8 | 28 | 328 | 3.597083e-03 | 9.828655e-03 | 2.839473e-01 |
| 14 | 9 | 11 | 361 | 2.449647e-03 | 7.467508e-03 | 2.283251e-01 |
| 15 | 9 | 28 | 378 | 2.399285e-03 | 7.203735e-03 | 2.388996e-01 |
| 16 | 0 | 12 | 12 | 2.765122e-03 | 8.360326e-03 | 3.215829e-01 |
| 17 | 0 | 13 | 13 | 2.079532e-03 | 4.816553e-03 | 3.326711e-01 |
| 18 | 0 | 14 | 14 | 2.303658e-03 | 6.506527e-03 | 3.387068e-01 |
| 19 | 0 | 15 | 15 | 2.580104e-03 | 8.364916e-03 | 3.283908e-01 |

20개 agentview 이미지의 pairwise 평균 절대 차이(uint8): 최소 2.534, 최대 11.895.

## 수집 시간 추정

고정된 수: 8 suite × 10 task × init 11–44. init은 34개. 에피소드는 2720. `pi0_pick`의 `max_chunks=24`이고 chunk 하나이 predict 하나다. 상한까지 가면 env step은 120이다.

가정. 이번 실행에서 재지 않은 것이다.

- 에피소드 VLA 비용은 `pi0_pick` 하나가 24 chunk를 모두 쓰는 경우로 잡았다. 실제로는 더 일찍 끝나거나 `pi0_pick`/`pi0_doubled`를 여러 번 부를 수 있다.
- 시뮬레이터 step, 렌더, `move_to` 등 스크립트 primitive 시간은 넣지 않았다.
- SAM3는 호출당 1.180초만 알고, 에피소드당 호출 수는 모른다. 합계에 더하지 않았다.
- planner/LLM 시간은 측정하지 않았다. 벽시계 추정에 포함하지 않았다.

| | pi0_pick 24 chunk | 2720 에피소드 |
| --- | --- | --- |
| bf16 | 20.1초 | 15.210시간 |
| fp16 | 8.0초 | 6.074시간 |

bf16은 24 × 0.838771초, fp16은 24 × 0.334972초다.
