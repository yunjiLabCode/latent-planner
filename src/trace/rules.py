"""Primitive success and decision labels for trace schema v0.2.

Targets RPent ``f70d720`` (``robots/libero/tools.py``). The AgenticRoboRL
patch does not change these function bodies.

``move_to`` has no ``success`` field. Its loop stops when
``dist < tol`` with ``tol`` default ``0.012``. That commit has no
``yaw_tol``; ``target_yaw`` does not enter the stop check, and the result
has no yaw error. ``a744bd5`` adds ``yaw_tol`` (default 0.02) and requires
both position and yaw. This module follows ``f70d720``.

Role rules read :func:`primitive_success`. False is a failure. None is not.
``labels.type`` is the same string as ``labels.role``.
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
    if (
        primitive_success(
            current["primitive"], current.get("result") or {}, current.get("arguments") or {}
        )
        is not True
    ):
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
    failed = primitive_success(
        earlier["primitive"], earlier.get("result") or {}, earlier.get("arguments") or {}
    )
    if failed is False:
        return RESTAGE_RETRY
    return None


def _success_of(record: Mapping[str, Any]) -> bool | None:
    return primitive_success(
        str(record.get("primitive") or ""),
        record.get("result") or {},
        record.get("arguments") or {},
    )


def _closed_episode(open_episode: dict[str, Any], *, resolved: bool) -> dict[str, Any]:
    return {
        "id": open_episode["id"],
        "failed_primitive": open_episode["failed_primitive"],
        "start_decision": open_episode["start_decision"],
        "end_decision": open_episode["end_decision"],
        "n_attempts": open_episode["n_attempts"],
        "resolved": resolved,
    }


def classify_labels(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Assign ``role`` and ``recovery_episode_id``, and list recovery episodes.

    A failure is ``primitive_success is False``. None does not open or extend
    one. While a failure is open:

    - the same primitive with no staging since the previous attempt is ``retry``
    - a ``STAGING`` primitive is ``restage``
    - the failed primitive after staging is ``restage_retry``
    - any other primitive is ``recovery`` and handles the failure

    A successful retry or restage_retry handles the failure. Another failure
    on that retry keeps the same id. An episode still open after the last
    decision is unresolved. Ids start at 1.
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
                open_episode = {
                    "id": episode_id,
                    "failed_primitive": primitive,
                    "start_decision": index,
                    "end_decision": index,
                    "n_attempts": 1,
                    "saw_staging": False,
                }
        elif primitive == open_episode["failed_primitive"]:
            role = ROLE_RESTAGE_RETRY if open_episode["saw_staging"] else ROLE_RETRY
            episode_id = open_episode["id"]
            open_episode["n_attempts"] += 1
            open_episode["end_decision"] = index
            open_episode["saw_staging"] = False
            if success is True:
                episodes.append(_closed_episode(open_episode, resolved=True))
                open_episode = None
        elif primitive in STAGING:
            role = ROLE_RESTAGE
            episode_id = open_episode["id"]
            open_episode["saw_staging"] = True
            open_episode["end_decision"] = index
        else:
            role = ROLE_RECOVERY
            episode_id = open_episode["id"]
            open_episode["end_decision"] = index
            episodes.append(_closed_episode(open_episode, resolved=True))
            open_episode = None
        roles.append({"role": role, "recovery_episode_id": episode_id})

    if open_episode is not None:
        episodes.append(_closed_episode(open_episode, resolved=False))
    return roles, episodes


def decision_type(records: Sequence[Mapping[str, Any]], index: int) -> str:
    """``labels.type``, kept equal to ``labels.role``."""
    if index < 0 or index >= len(records):
        raise IndexError(index)
    roles, _episodes = classify_labels(records)
    return roles[index]["role"]
