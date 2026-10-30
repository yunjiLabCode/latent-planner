"""Primitive success and decision labels for trace schema v0.3.

Targets RPent ``f70d720`` (``robots/libero/tools.py``). The AgenticRoboRL
patch does not change these function bodies.

``move_to`` has no ``success`` field. Its loop stops when
``dist < tol`` with ``tol`` default ``0.012``. That commit has no
``yaw_tol``; ``target_yaw`` does not enter the stop check, and the result
has no yaw error. ``a744bd5`` adds ``yaw_tol`` (default 0.02) and requires
both position and yaw. This module follows ``f70d720``.

Role rules read :func:`primitive_success`. False is a failure. None is not.
``labels.type`` is the same string as ``labels.role``.

A ``pi0_pick`` whose heuristic ``success`` is false, whose prompt is not
picked again, and whose episode ends ``terminated`` true is stored as
``labels.primitive_success`` None with ``labels.success_overridden``
``terminal_success``. :func:`_success_of` honors that flag so role and
``relation_to_failed`` follow the override. :func:`primitive_success` itself
stays the heuristic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# robots/libero/tools.py LiberoPrimitives.move_to, and TOOLS_SPEC description.
MOVE_TO_TOL_M = 0.012

RESTAGE_RETRY = "restage_retry"

# Primitives whose motion does not itself count as a new strategy.
STAGING = frozenset(
    {
        "move_to",
        "move_pose",
        "rotate_wrist",
        "rotate_pitch",
        "set_gripper",
        "release",
    }
)

ROLE_NEW = "new"
ROLE_RETRY = "retry"
ROLE_RESTAGE = "restage"
ROLE_RESTAGE_RETRY = "restage_retry"
ROLE_RECOVERY = "recovery"

# Same name is not the same attempt when the VLA prompt differs.
PROMPT_ATTEMPT_PRIMITIVES = frozenset({"pi0_pick", "pi0_doubled"})

CLOSED_BY_SUCCESS = "success"
CLOSED_BY_RECOVERY = "recovery"
CLOSED_BY_EPISODE_END = "episode_end"


def same_attempt(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Whether ``b`` continues the attempt started by ``a``.

    ``pi0_pick`` and ``pi0_doubled`` match only when the primitive name and
    ``arguments.prompt`` are both equal. Every other primitive matches by name.
    """
    name_a = str(a.get("primitive") or "")
    name_b = str(b.get("primitive") or "")
    if name_a != name_b:
        return False
    if name_a in PROMPT_ATTEMPT_PRIMITIVES:
        prompt_a = (a.get("arguments") or {}).get("prompt")
        prompt_b = (b.get("arguments") or {}).get("prompt")
        return prompt_a == prompt_b
    return True


def primitive_success(
    primitive: str,
    result: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> bool | None:
    """Return True, False, or None when the log has no failure signal.

    ``pi0_pick`` stores the descent / relift / gripper heuristic in
    ``result["success"]`` (descent is hard-coded at 0.10 m, lift and gripper
    thresholds are the call arguments). False is a failed grasp.

    ``pi0_doubled`` stores official ``env.terminated`` in ``success``. A
    false value on an intermediate contact skill is not a failure, so this
    returns None instead of False.

    ``move_to`` compares ``final_dist_m`` with the call ``tol`` or
    ``MOVE_TO_TOL_M``. The comparison is strict, matching ``dist < tol``.

    Other execution primitives have no confirmed success rule and return None.
    """
    if primitive == "pi0_pick":
        if "success" not in result:
            return None
        return result.get("success") is True
    if primitive == "pi0_doubled":
        if result.get("success") is True or result.get("terminated") is True:
            return True
        return None
    if primitive == "move_to":
        if "final_dist_m" not in result:
            return None
        tol = arguments.get("tol", MOVE_TO_TOL_M)
        try:
            return float(result["final_dist_m"]) < float(tol)
        except (TypeError, ValueError):
            return None
    return None


def relation_to_failed(
    records: Sequence[Mapping[str, Any]], index: int
) -> str | None:
    """Relation of ``records[index]`` to an earlier failed primitive.

    ``restage_retry``: this record is a successful ``pi0_pick``, the records
    immediately before it are one or more ``move_to``, and the record before
    those moves is a failed ``pi0_pick``. ``move_to`` success is not required.
    Query tools are not records. Any other pattern returns None.
    """
    if index < 0 or index >= len(records):
        raise IndexError(index)
    current = records[index]
    if current.get("primitive") != "pi0_pick":
        return None
    if _success_of(current) is not True:
        return None
    cursor = index - 1
    saw_move = False
    while cursor >= 0 and records[cursor].get("primitive") == "move_to":
        saw_move = True
        cursor -= 1
    if not saw_move or cursor < 0:
        return None
    earlier = records[cursor]
    if earlier.get("primitive") != "pi0_pick":
        return None
    if _success_of(earlier) is False:
        return RESTAGE_RETRY
    return None


def _success_of(record: Mapping[str, Any]) -> bool | None:
    """Heuristic success, or None when the terminal-success override is set."""
    if record.get("success_overridden") == "terminal_success":
        return None
    labels = record.get("labels")
    if isinstance(labels, dict) and labels.get("success_overridden") == "terminal_success":
        return None
    return primitive_success(
        str(record.get("primitive") or ""),
        record.get("result") or {},
        record.get("arguments") or {},
    )


def _anchor(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "primitive": str(record.get("primitive") or ""),
        "arguments": dict(record.get("arguments") or {}),
    }


def _open_episode(record: Mapping[str, Any], index: int, episode_id: int) -> dict[str, Any]:
    return {
        "id": episode_id,
        "failed_primitive": str(record.get("primitive") or ""),
        "anchor": _anchor(record),
        "start_decision": index,
        "end_decision": index,
        "n_attempts": 1,
        "saw_staging": False,
    }


def _closed_episode(
    open_episode: dict[str, Any], *, resolved: bool, closed_by: str
) -> dict[str, Any]:
    return {
        "id": open_episode["id"],
        "failed_primitive": open_episode["failed_primitive"],
        "start_decision": open_episode["start_decision"],
        "end_decision": open_episode["end_decision"],
        "n_attempts": open_episode["n_attempts"],
        "resolved": resolved,
        "closed_by": closed_by,
    }


def classify_labels(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Assign ``role`` and ``recovery_episode_id``, and list recovery episodes.

    A failure is ``primitive_success is False``. None does not open or extend
    one. While a failure is open:

    - :func:`same_attempt` with no staging since the previous attempt is ``retry``
    - a ``STAGING`` primitive is ``restage``
    - the same attempt after staging is ``restage_retry``
    - any other primitive is ``recovery`` and closes the failure

    A different ``pi0_pick`` / ``pi0_doubled`` prompt is not the same attempt,
    so it is ``recovery`` and does not increment ``n_attempts``. A successful
    retry or restage_retry closes with ``closed_by`` ``success``. A recovery
    closes with ``closed_by`` ``recovery``. If that recovery decision itself
    has ``primitive_success is False``, a new episode starts on the same
    decision and the decision's id is the new one. An episode still open
    after the last decision has ``closed_by`` ``episode_end``. Ids start at 1.
    """
    roles: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []
    open_episode: dict[str, Any] | None = None
    next_id = 1

    for index, record in enumerate(records):
        primitive = str(record.get("primitive") or "")
        success = _success_of(record)
        failed = success is False
        if open_episode is None:
            role = ROLE_NEW
            episode_id = None
            if failed:
                episode_id = next_id
                next_id += 1
                open_episode = _open_episode(record, index, episode_id)
        elif same_attempt(open_episode["anchor"], record):
            role = ROLE_RESTAGE_RETRY if open_episode["saw_staging"] else ROLE_RETRY
            episode_id = open_episode["id"]
            open_episode["n_attempts"] += 1
            open_episode["end_decision"] = index
            open_episode["saw_staging"] = False
            if success is True:
                episodes.append(
                    _closed_episode(
                        open_episode, resolved=True, closed_by=CLOSED_BY_SUCCESS
                    )
                )
                open_episode = None
        elif primitive in STAGING:
            role = ROLE_RESTAGE
            episode_id = open_episode["id"]
            open_episode["saw_staging"] = True
            open_episode["end_decision"] = index
        else:
            role = ROLE_RECOVERY
            open_episode["end_decision"] = index
            episodes.append(
                _closed_episode(
                    open_episode, resolved=True, closed_by=CLOSED_BY_RECOVERY
                )
            )
            if failed:
                episode_id = next_id
                next_id += 1
                open_episode = _open_episode(record, index, episode_id)
            else:
                episode_id = open_episode["id"]
                open_episode = None
        roles.append({"role": role, "recovery_episode_id": episode_id})

    if open_episode is not None:
        episodes.append(
            _closed_episode(
                open_episode, resolved=False, closed_by=CLOSED_BY_EPISODE_END
            )
        )
    return roles, episodes


def decision_type(records: Sequence[Mapping[str, Any]], index: int) -> str:
    """``labels.type``, kept equal to ``labels.role``."""
    if index < 0 or index >= len(records):
        raise IndexError(index)
    roles, _episodes = classify_labels(records)
    return roles[index]["role"]
