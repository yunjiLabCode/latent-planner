# Trace schema v0.2.1

v0.2의 맞춤, `outcome.success`, `obs_before`, `primitive_success` 계산은 그대로다. 바뀐 것은 같은 시도의 판정, 실패한 recovery가 새 episode를 여는 방식, `closed_by`, 그리고 `relabel`이 `episode.json`의 `recovery_episodes`를 다시 쓰는 것이다. `schema_version`은 `"0.2.1"`다.

`labels.type`은 `labels.role`과 같다. `relation_to_failed`는 v0.1 함수 그대로다. 역할 판정에는 쓰지 않는다.

## 실패

실패는 `primitive_success()`가 False인 실행이다. None은 실패가 아니다. `pi0_doubled`의 중간 false는 None이라 실패가 아니다.

변환기는 그 값을 `labels.primitive_success`에 저장한다. `relabel`은 저장된 `primitive_success`와 `relation_to_failed`를 고치지 않는다. `role`, `type`, `recovery_episode_id`는 `result`로 다시 계산한다.

## 같은 시도

`same_attempt(a, b)`는 `b`가 `a`와 같은 시도인지 본다.

`pi0_pick`과 `pi0_doubled`은 primitive 이름과 `arguments.prompt`가 둘 다 같을 때만 같은 시도다. prompt가 다르면 `retry`도 `restage_retry`도 아니고, 그 호출은 이전 episode의 `n_attempts`에 들어가지 않는다. 그 결정은 `recovery`다.

그 외 primitive는 이름만 비교한다. 실패한 `move_to` 직후의 `move_to`는 `retry`다. 실패한 `pi0_pick` 뒤의 `move_to`는 이름이 다르고 `STAGING`이라 `restage`다.

## role

열린 실패가 없으면 `new`. 그 결정이 실패면 recovery episode가 거기서 시작한다.

실패가 열려 있는 동안:

| role | 조건 |
| --- | --- |
| `retry` | `same_attempt`이고, 직전 시도 이후 staging이 없음 |
| `restage` | `STAGING` 실행 |
| `restage_retry` | staging 뒤에 `same_attempt` |
| `recovery` | staging도 아니고 같은 시도도 아님. 이 결정에서 이전 episode가 닫힌다 |

`STAGING` = `move_to`, `move_pose`, `rotate_wrist`, `rotate_pitch`, `set_gripper`, `release`.

성공한 `retry` 또는 `restage_retry`가 실패를 닫는다. 같은 시도가 다시 실패하면 같은 `recovery_episode_id`가 유지된다. staging은 실패를 닫지 않는다. staging이 `primitive_success == False`여도 역할은 `restage`이고, 새 episode를 열지 않는다.

`recovery`는 이전 episode를 그 결정에서 닫는다. `end_decision`은 그 recovery 결정이다. 그 결정의 `primitive_success`가 False가 아니면 라벨의 `recovery_episode_id`는 닫히는 episode의 id이고, 새 episode는 열리지 않는다. False이면 같은 결정에서 새 recovery episode가 시작한다. 그 결정의 `recovery_episode_id`는 새 id다. 이전 episode의 구간과 새 episode의 `start_decision`이 그 인덱스를 같이 가리킨다. 새 episode의 `n_attempts`는 1부터다.

에피소드가 끝날 때 실패가 아직 열려 있으면 그 recovery episode는 `resolved: false`다.

## closed_by

`recovery_episodes`의 각 항목은 `closed_by`를 가진다.

| closed_by | 언제 |
| --- | --- |
| `success` | 성공한 `retry` 또는 `restage_retry`로 닫힘. `resolved`는 true |
| `recovery` | `recovery` 결정으로 닫힘. `resolved`는 true. 그 결정이 실패여도 이전 episode의 `closed_by`는 `recovery`다 |
| `episode_end` | 마지막 결정 뒤에도 열려 있음. `resolved`는 false |

```json
{
  "id": 1,
  "failed_primitive": "pi0_pick",
  "start_decision": 0,
  "end_decision": 1,
  "n_attempts": 1,
  "resolved": true,
  "closed_by": "recovery"
}
```

`n_attempts`는 그 episode 안에서 `same_attempt`인 호출 수다. 처음 실패와 이후 retry / restage_retry가 들어간다. staging, 다른 prompt, recovery는 세지 않는다.

## relabel

`relabel`은 `decisions.jsonl`의 `role`, `type`, `recovery_episode_id`를 다시 쓴다. 같은 계산으로 옆의 `episode.json`에서 `recovery_episodes`만 바꾼다. `outcome`, `conversion`, `stats`, `obs`에 해당하는 필드와 그 외 episode 필드는 그대로다. `episode.json`이 없으면 decisions만 다시 쓴다.

## 예

| 실행 | role | episode |
| --- | --- | --- |
| pick 실패 → 같은 prompt pick 성공 | `new`, `retry` | n_attempts 2, `closed_by` `success` |
| pick(`bowl`) 실패 → pick(`plate`) 성공 | `new`, `recovery` | 하나, n_attempts 1, `closed_by` `recovery`. id는 둘 다 1 |
| pick 실패 → `pi0_doubled` (`primitive_success` None) | `new`, `recovery` | 하나, n_attempts 1, `closed_by` `recovery` |
| pick(`bowl`) 실패 → pick(`plate`) 실패 → pick(`plate`) 성공 | `new`, `recovery`, `retry` | 두 episode, 둘 다 resolved. 라벨 id는 1, 2, 2. 첫 episode는 `closed_by` `recovery`, 둘째는 `success` |
| pick 실패 → move_to → pick 실패 → move_to → pick 성공 | `new`, `restage`, `restage_retry`, `restage`, `restage_retry` | 하나, n_attempts 3, `closed_by` `success` |
| pick 실패로 종료 | `new` | `resolved` false, `closed_by` `episode_end` |
