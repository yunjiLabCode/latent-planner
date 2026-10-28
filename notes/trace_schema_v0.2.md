# Trace schema v0.2

v0.1의 맞춤, `outcome.success`, `obs_before`, `primitive_success` 계산은 그대로다. 바뀐 것은 결정 라벨과 `episode.json`의 `recovery_episodes`다. `schema_version`은 `"0.2"`다.

`labels.type`은 `labels.role`과 같다. `relation_to_failed`는 v0.1 함수 그대로다. 역할 판정에는 쓰지 않는다.

## 실패

실패는 `primitive_success()`가 False인 실행이다. None은 실패가 아니다. `pi0_doubled`의 중간 false는 None이라 실패가 아니다.

변환기는 그 값을 `labels.primitive_success`에 저장한다. `relabel`은 저장된 `primitive_success`와 `relation_to_failed`를 고치지 않고, `result`로 다시 계산한 성공 여부로 `role`, `type`, `recovery_episode_id`만 다시 쓴다. `episode.json`은 다시 쓰지 않는다.

## role

열린 실패가 없으면 `new`. 그 결정이 실패면 recovery episode가 거기서 시작한다.

실패가 열려 있는 동안:

| role | 조건 |
| --- | --- |
| `retry` | 실패한 primitive를, 직전 시도 이후 staging 없이 다시 호출 |
| `restage` | `STAGING` 실행 |
| `restage_retry` | staging 뒤에 실패한 primitive를 다시 호출 |
| `recovery` | staging도 아니고 같은 primitive도 아님. 이 결정에서 그 실패는 처리된다 |

`STAGING` = `move_to`, `move_pose`, `rotate_wrist`, `rotate_pitch`, `set_gripper`, `release`.

성공한 `retry` 또는 `restage_retry`가 실패를 닫는다. 재시도가 다시 실패하면 같은 `recovery_episode_id`가 유지된다. staging은 실패를 닫지 않는다. 에피소드가 끝날 때 실패가 아직 열려 있으면 그 recovery episode는 `resolved: false`다.

staging이 `primitive_success == False`여도 역할은 `restage`이고, 새 episode를 열지 않는다. `recovery` 실행 자신의 `primitive_success`가 False여도 이전 실패는 그 결정에서 닫히고, 같은 결정에 두 번째 episode를 열지 않는다.

## recovery_episode_id

실패 결정부터 그 실패가 처리되는 결정까지 같은 정수다. 번호는 1부터다. 열린 실패가 없는 성공 실행은 null이다.

`episode.json`의 `recovery_episodes`:

```json
{
  "id": 1,
  "failed_primitive": "pi0_pick",
  "start_decision": 0,
  "end_decision": 4,
  "n_attempts": 3,
  "resolved": true
}
```

`n_attempts`는 그 episode 안에서 실패한 primitive를 호출한 횟수다. 처음 실패와 이후 retry / restage_retry가 들어간다. staging과 recovery는 세지 않는다. `end_decision`은 그 id를 가진 마지막 결정이다.

## 예

| 실행 | role | episode |
| --- | --- | --- |
| pick 실패 → pick 성공 | `new`, `retry` | n_attempts 2, resolved |
| pick 실패 → move_to → pick 실패 → move_to → pick 성공 | `new`, `restage`, `restage_retry`, `restage`, `restage_retry` | 하나, n_attempts 3, resolved |
| pick 실패 → release → move_to → pick 성공 | `new`, `restage`, `restage`, `restage_retry` | resolved |
| pick 실패 → pi0_doubled | `new`, `recovery` | n_attempts 1, resolved |
| pick 실패로 종료 | `new` | resolved false |
