"""Label vocabularies for the direct MLP.

The model classifies a primitive, a target object drawn from the task object
list, and discrete arguments. ``move_to`` / ``move_pose`` coordinates are not
labels. A coordinate-only command has target ``none``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

# Execution tools that can appear as a decision, plus ``other`` for a name
# this experiment has not listed. History padding is a separate index.
PRIMITIVES: tuple[str, ...] = (
    "move_to",
    "move_pose",
    "pi0_pick",
    "pi0_doubled",
    "release",
    "set_gripper",
    "rotate_wrist",
    "rotate_pitch",
    "reset",
    "other",
)

GRIPPER: tuple[str, ...] = ("absent", "open", "closed")

# ``labels.primitive_success`` of an earlier decision. Padding is separate.
RESULTS: tuple[str, ...] = ("success", "failure", "unknown")

ROLES: tuple[str, ...] = ("new", "retry", "restage", "restage_retry", "recovery")

NONE_OBJECT = "none"

_LANGUAGE_KEYS = ("language", "text", "task_language", "instruction")
_PREPOSITIONS = frozenset(
    {"in", "on", "to", "from", "into", "onto", "and", "with", "of", "then", "near"}
)
_THE = re.compile(r"\bthe\s+", re.IGNORECASE)


def primitive_index(name: str) -> int:
    try:
        return PRIMITIVES.index(name)
    except ValueError:
        return PRIMITIVES.index("other")


def gripper_index(arguments: Mapping[str, Any]) -> int:
    """Map a logged ``gripper`` argument to ``absent``, ``open``, or ``closed``.

    LIBERO uses ``+1`` to keep the gripper closed and ``-1`` to open it.
    A missing key stays ``absent``: the implicit runtime default is not a
    logged argument, so it is not the training target.
    """
    if "gripper" not in arguments:
        return GRIPPER.index("absent")
    value = arguments.get("gripper")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return GRIPPER.index("absent")
    if number < 0:
        return GRIPPER.index("open")
    return GRIPPER.index("closed")


def result_index(primitive_success: bool | None) -> int:
    if primitive_success is True:
        return RESULTS.index("success")
    if primitive_success is False:
        return RESULTS.index("failure")
    return RESULTS.index("unknown")


def language_of(task: Mapping[str, Any] | None) -> str:
    """Return the task sentence when the episode stored one."""
    if not isinstance(task, Mapping):
        return ""
    for key in _LANGUAGE_KEYS:
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def task_text(task: Mapping[str, Any] | None) -> str:
    """Text fed to the frozen text encoder.

    A stored instruction wins. Otherwise the suite, task index, and seed
    identify the cell. That string is still task text, not a teacher turn.
    """
    language = language_of(task)
    if language:
        return language
    if not isinstance(task, Mapping):
        return ""
    parts: list[str] = []
    for key in ("suite", "task", "seed"):
        if key in task and task[key] is not None:
            parts.append(f"{key}={task[key]}")
    return " ".join(parts)


def nouns(text: str) -> list[str]:
    """Object phrases after ``the``, stopping at a preposition."""
    names: list[str] = []
    for part in _THE.split(text)[1:]:
        words: list[str] = []
        for word in re.findall(r"[A-Za-z0-9_]+", part):
            if word.lower() in _PREPOSITIONS:
                break
            words.append(word.lower())
            if len(words) == 4:
                break
        if words:
            names.append(" ".join(words))
    return names


def _unique(names: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        key = name.strip().lower()
        if not key or key == NONE_OBJECT or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def task_object_list(task: Mapping[str, Any] | None, prompts: Sequence[str]) -> list[str]:
    """Objects the target head is allowed to choose, excluding ``none``.

    ``task["objects"]`` is the list when the episode has one. Otherwise the
    list is the nouns of the task sentence. Prompt nouns are only a fallback
    for traces that stored neither.
    """
    if isinstance(task, Mapping):
        raw = task.get("objects")
        if isinstance(raw, list):
            explicit = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
            if explicit:
                return _unique(explicit)
    language = language_of(task)
    if language:
        return _unique(nouns(language))
    collected: list[str] = []
    for prompt in prompts:
        if isinstance(prompt, str):
            collected.extend(nouns(prompt))
    return _unique(collected)


def target_object(arguments: Mapping[str, Any], objects: Sequence[str]) -> str:
    """Object name in ``objects``, or ``none``.

    Reads ``object``, ``target``, and ``prompt`` only. Coordinate fields such
    as ``xyz`` are ignored.
    """
    listed = _unique([name for name in objects if isinstance(name, str)])
    for key in ("object", "target"):
        value = arguments.get(key)
        if isinstance(value, str):
            matched = _match_name(value, listed)
            if matched is not None:
                return matched
    prompt = arguments.get("prompt")
    if isinstance(prompt, str):
        matched = _match_name(prompt, listed)
        if matched is not None:
            return matched
    return NONE_OBJECT


def _match_name(text: str, objects: Sequence[str]) -> str | None:
    best: str | None = None
    for name in objects:
        if re.search(rf"\b{re.escape(name)}\b", text, flags=re.IGNORECASE):
            if best is None or len(name) > len(best):
                best = name
    return best
