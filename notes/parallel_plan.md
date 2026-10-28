# 공유 pi0.5 / SAM3 서버와 N개 env 서버

2026-10-28. 워크스페이스의 RPent만 읽었다. RPent와 AgenticRoboRL은 수정하지 않았다. 에피소드는 돌리지 않았다.

결론: 동시 클라이언트는 추론이 겹치지 않게 잠겨 있다. HTTP와 socket 모두 연결은 스레드로 받고, 실제 호출은 한 번에 하나다. 대기 중인 요청을 모아 하나의 forward로 합치는 코드는 없다. N개 env가 서버 하나를 공유하면 GPU 추론은 줄을 선다.

## pi0.5 서버

파일: `rpent/robots/components/pi05_vla_server.py`, `vla_facade_base.py`, `rpent/utils/rpc/rpc.py`.

`Pi05VLAFacade`는 기동 때 모델을 한 번 올려 `self._model`에 둔다. 세션 객체, 클라이언트 id, 요청 사이 캐시는 없다. `predict`는 그 호출의 observation으로 `env_obs`를 만들고 `predict_action_batch`를 `torch.no_grad` 안에서 한 번 호출한다. 반환 텐서는 `.cpu().numpy()`로 복사한 뒤 락을 놓는다.

배치 차원은 그 요청 안에만 있다. `main_images`는 `[B,H,W,3]`, `states`는 `[B,state_dim]`, `task_descriptions`는 길이 B다. LIBERO 클라이언트 `Pi05VLAClient.predict_action_batch`는 이미지와 state 앞에 크기 1인 축을 붙여 B=1로 보낸다. 서버는 여러 연결의 요청을 모아 B를 키우지 않는다.

잠금은 두 겹이다.

- `RpcFacade.serve`가 `threading.Lock`으로 `healthz`를 뺀 모든 RPC를 직렬화한다. `healthz`는 락 없이 `{"status": "ok"}`를 돌려준다.
- `BaseVLAFacade._dispatch`가 `vla.predict`를 `RWLock`의 write로 한 번 더 감싼다. 등록된 메서드는 `vla.predict`뿐이고, read-only 집합은 비어 있다. 주석은 모델이 스레드 안전하지 않다고 적고, 서브클래스가 `serve`를 바꿔도 이 락이 남게 파사드에 두었다. pi0.5는 `serve`를 바꾸지 않으므로 RPC 락만으로도 호출은 겹치지 않는다.

전송은 `ThreadingHTTPServer` 또는 `ThreadingTCPServer`다. 요청마다 핸들러 스레드가 뜨고, 그 스레드가 위의 락에서 기다린다. 소켓 클라이언트는 호출마다 연결을 새로 연다. HTTP 클라이언트도 호출마다 POST 한 번이다. 클라이언트 쪽 공유 소켓은 없다.

`vla.predict` 타임아웃은 클라이언트 `BaseVLAClient`에서 120초다. 줄을 서다 이 시간을 넘기면 클라이언트는 실패하고, 서버 핸들러는 그 호출을 취소하지 않는다. 응답을 쓸 때 연결이 끊기면 `BrokenPipeError`를 로그하고 다음 요청으로 간다.

서버 코드가 요청 사이에 들고 있는 가변 상태는 모델 객체다. 호출끼리는 락으로 갈린다. rlinf `predict_action_batch` 안쪽 버퍼는 이 노트에서 열지 않았다. 서버는 그 호출이 겹치지만 않으면 된다고 보고 락을 건다.

## SAM3 서버

파일: `rpent/robots/components/sam3_server.py`.

`Sam3Engine` 주석은 추론을 직렬화하고 마지막 이미지의 backbone 상태를 캐시한다고 적는다. `segment` 전체가 `self._lock`(`threading.Lock`) 안에 있다. 그 바깥에서 `RpcFacade.serve`의 락이 `segment` RPC 전체를 한 번 더 직렬화한다. 텍스트 프롬프트와 point 프롬프트는 한 요청에 하나씩이다. 여러 이미지를 한 forward에 넣는 경로는 없다.

공유 가변 상태는 한 칸짜리 캐시다. `_image_digest`는 이미지 바이트의 sha256이고, `_image_state`는 `processor.set_image`가 돌려준 dict다. 같은 바이트가 다시 오면 그 dict를 그대로 쓴다. 다른 이미지면 캐시를 바꾼다. `set_text_prompt`와 `predict_inst`에는 이 dict를 복사 없이 넘긴다. 락은 두 호출이 그 dict를 동시에 쓰지 않게 한다. 클라이언트별 상태 칸은 없다. 프롬프트가 그 dict에 무엇을 남기는지는 SAM3 라이브러리 안이고, 이 서버는 그 객체를 요청마다 비우지 않는다.

로드 때 `torch.cuda.set_device(0)`이다. `--cuda-device`는 로드 전에 `CUDA_VISIBLE_DEVICES`로 바꿔 그 0번이 고른 GPU가 되게 한다. TF32 플래그는 프로세스에 한 번 설정한다.

클라이언트 `Sam3Client`의 기본 타임아웃은 120초다. pi0.5와 같이, 타임아웃은 대기 중인 서버 작업을 취소하지 않는다.

## 엔드포인트와 붙는 방식

LIBERO `robots/libero/robot_spec.py`에 `--vla-endpoint`와 `--sam3-endpoint`가 있다. `--env-endpoint`도 있다. 형식은 `[protocol://]host:port`이고, protocol은 `http` 또는 `socket`, 생략하면 `http`다. `make_rpc_client`가 클라이언트를 만든다.

플래그가 있으면 `_spawn_vla_server` / `_spawn_sam3_server`는 프로세스를 만들지 않고 `(None, client)`를 돌려준다. 없으면 `127.0.0.1`의 빈 포트에 http로 자식을 띄우고 `--parent-watch`를 붙인다. 그 자식은 부모 stdin이 끊기면 끝난다. 공유 서버는 이 경로로 띄우면 안 된다. `pi05_vla_server`와 `sam3_server`를 `--parent-watch` 없이 각각 한 번 띄우고, 그 주소를 플래그로 넘긴다. `--cuda-device`는 각 서버 프로세스의 기동 인자라, 나중에 붙는 rpent의 `--cuda-device`가 이미 떠 있는 서버의 GPU를 바꾸지 않는다.

N개 env와의 연결은 rpent 프로세스가 한다. env 서버는 VLA와 SAM3 소켓을 열지 않는다.

- 각 rpent는 `--vla-endpoint`와 `--sam3-endpoint`로 공유 서버에 붙는다.
- 각 rpent는 자기 `env_server.py`를 띄운다. `--suite`, `--task`, `--seed`가 그 프로세스의 시뮬레이터 하나다. `--parent-watch`와, rpent에 `--cuda-device`가 있으면 그 값이 env 자식에게 넘어간다.
- 이미 떠 있는 env에 붙이려면 그 프로세스의 `--env-endpoint`를 쓴다. 주소 하나는 시뮬레이터 하나다.

`_init_runtime`은 env, sam3, vla 순으로 `healthz`를 기다린 뒤 `LiberoEnvClient`, `Sam3Client`, `Pi05VLAClient`를 만든다. primitive는 `tools.py`에서 VLA를 B=1로 부르고, `segment`는 SAM3 클라이언트로 부른다. `pi0_pick`처럼 청크를 여러 번 부르는 동안 락은 호출마다 놓이므로, 다른 env의 `vla.predict`가 청크 사이에서 들어온다. 서버는 그 사이에 클라이언트별 recurrent state를 들고 있지 않다.

robocasa와 robotwin의 `robot_spec.py`에는 `--vla-endpoint`만 있고 `--sam3-endpoint`는 없다. 이 수집 경로는 LIBERO 스펙이다.

## GPU 2 env-server 메모리 측정

프로세스를 멈춘 뒤 GPU 2만 보았다. GPU 3은 그대로다. 유휴 baseline은 7 MiB.

- env 서버만: 카드 540 MiB, 유휴보다 533 MiB. reset 후에도 같다. CUDA 연산 앱이 아니고, 533 MiB는 카드 증가분이다.
- pi0.5 bf16 + SAM3, env 전: 11074 MiB. pi0.5 7332, SAM3 3732.
- 풀 스택: 11607 MiB.
- 모델이 있는 상태에서 env가 더하는 양: 533 MiB.

에피소드 피크는 앞서 17320 / 24576 MiB였다 (`notes/smoke_episode_01.md`). RPC 락이 VLA와 SAM3를 직렬화하므로 추론 피크는 공유분으로 둔다. 공유 피크는 17320−11607 = 5713 MiB다.

## 용량

산수: `11074 + (17320−11607) + N×533 <= 24576 − 2048`. 좌변의 고정분은 16787 MiB이고, 2 GiB를 남기면 N은 약 10까지다. N=10은 22117 MiB, N=11은 남는 여유가 2048 MiB보다 작다. N=4는 18919 MiB다. 이 값은 렌더러 N개를 동시에 띄워 잰 것이 아니다.

배치는 4에서 시작한다.

vLLM KV cache는 546697 토큰이다. 이 에피소드 컨텍스트는 56937으로 57k 근처에서 피크였다. prefix를 공유하지 않으면 동시 시퀀스는 약 9개다.
