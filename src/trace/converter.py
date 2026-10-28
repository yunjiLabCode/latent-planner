"""Convert one RPent output directory into trace schema v0.2.

Reads ``states.json`` and ``transcript_*.json`` written by RPent ``f70d720``
plus ``AgenticRoboRL/patches/rpent/rpent_f70d720.patch``. Does not read images
and does not use transcript ``solved`` or ``environment_success``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trace.rules import classify_labels, primitive_success, relation_to_failed
from trace.schema import (
    SCHEMA_VERSION,
    ContextCall,
    Decision,
    Episode,
    TeacherText,
)
from trace.tool_classes import (
    EXECUTION_TOOLS,
    MEMORY_READ_TOOLS,
    QUERY_TOOLS,
    is_memory_path,
)

_TASK_KEYS = ("suite", "task", "seed", "model")


@dataclass
class _Call:
    name: str
    arguments: dict[str, Any]
    tool_call_id: str | None = None
    context_calls: list[_Call] = field(default_factory=list)
    text: str = ""
    thinking: str = ""
    cites_memory: bool = False


def convert_episode(
    rpent_output: Path | str,
    traces_root: Path | str,
    *,
    run_id: str | None = None,
    episode_id: str | None = None,
) -> Path:
    """Write ``traces_root/run_id/episode_id/episode.json`` and ``decisions.jsonl``.

    Returns the episode directory. ``run_id`` defaults to the RPent output
    directory name. ``episode_id`` defaults to the ``transcript_<id>.json`` stem.
    """
    source_dir = Path(rpent_output)
    states_path = source_dir / "states.json"
    if not states_path.is_file():
        raise FileNotFoundError(states_path)
    transcript_path, transcript_warnings = _find_transcript(source_dir)
    transcript = json.loads(transcript_path.read_text())
    if not isinstance(transcript, dict):
        raise ValueError(f"{transcript_path} is not a JSON object")
    manifest = json.loads(states_path.read_text())
    steps = manifest.get("steps")
    if not isinstance(steps, list):
        raise ValueError(f"{states_path} has no steps list")

    warnings = list(transcript_warnings)
    messages = transcript.get("messages")
    if not isinstance(messages, list):
        warnings.append("transcript has no messages list")
        messages = []
    executions, trailing, n_memory_reads, parse_warnings = _walk_messages(messages)
    warnings.extend(parse_warnings)

    commanded = [step for step in steps if isinstance(step, dict) and step.get("command")]
    if len(executions) != len(commanded):
        warnings.append(
            "execution count disagrees: "
            f"transcript={len(executions)} states.json={len(commanded)}"
        )

    raw: list[dict[str, Any]] = []
    limit = min(len(executions), len(commanded))
    for index, step in enumerate(commanded):
        command = step.get("command")
        if not isinstance(command, dict):
            warnings.append(f"states.json step index {index} command is not an object")
            command = {}
        primitive = command.get("action")
        if not isinstance(primitive, str) or not primitive:
            primitive = ""
            warnings.append(f"states.json commanded step {index} has no command.action")
        arguments = {key: value for key, value in command.items() if key != "action"}
        result = step.get("result")
        if not isinstance(result, dict):
            warnings.append(f"step {step.get('step_idx')} {primitive or '?'} result is not an object")
            result = {}
        bound: _Call | None = None
        if index < limit:
            call = executions[index]
            if call.name != primitive:
                warnings.append(
                    f"decision {index} transcript tool {call.name!r} "
                    f"!= states.json command.action {primitive!r}"
                )
            else:
                bound = call
                if call.arguments != arguments:
                    warnings.append(
                        f"step {step.get('step_idx')} {primitive} arguments differ "
                        "between transcript and states.json"
                    )
        position = _step_position(steps, step)
        obs = _obs_before(steps, position)
        if obs["step_idx"] is None and position == 0:
            warnings.append(
                f"step {step.get('step_idx')} {primitive or '?'} has no preceding state step"
            )
        context = [_context_call(item) for item in bound.context_calls] if bound else []
        teacher = (
            TeacherText(
                text=bound.text,
                thinking=bound.thinking,
                cites_memory=bound.cites_memory,
            )
            if bound
            else TeacherText()
        )
        raw.append(
            {
                "decision_index": index,
                "step_idx": step.get("step_idx"),
                "primitive": primitive,
                "arguments": arguments,
                "tool_call_id": bound.tool_call_id if bound else None,
                "obs_before": obs,
                "context_calls": context,
                "teacher_text": teacher.model_dump(),
                "result": result,
                "terminated": step.get("terminated") is True,
                "truncated": step.get("truncated") is True,
                "elapsed_s": step.get("elapsed_s"),
                "labels": {
                    "primitive_success": None,
                    "relation_to_failed": None,
                    "type": "unlabeled",
                },
            }
        )

    roles, recovery_episodes = classify_labels(raw)
    for index, record in enumerate(raw):
        success = primitive_success(
            record["primitive"], record["result"], record["arguments"]
        )
        role = roles[index]["role"]
        record["labels"] = {
            "primitive_success": success,
            "relation_to_failed": relation_to_failed(raw, index),
            "role": role,
            "type": role,
            "recovery_episode_id": roles[index]["recovery_episode_id"],
        }
        _warn_missing_signal(record, warnings)

    if not steps:
        warnings.append("states.json has no steps")
        outcome = {"success": False, "terminated": False, "truncated": False}
    else:
        last = steps[-1]
        if not isinstance(last, dict) or "terminated" not in last:
            warnings.append("last states.json step has no terminated field")
            outcome = {"success": False, "terminated": False, "truncated": False}
        else:
            outcome = {
                "success": last.get("terminated") is True,
                "terminated": last.get("terminated") is True,
                "truncated": last.get("truncated") is True,
            }

    matched = not _disagreement(warnings)
    n_context = sum(len(record["context_calls"]) for record in raw) + len(trailing.context_calls)
    resolved_run = run_id or source_dir.name
    resolved_episode = episode_id or _episode_id_from_transcript(transcript_path)
    task = {key: transcript[key] for key in _TASK_KEYS if key in transcript}
    episode = Episode(
        schema_version=SCHEMA_VERSION,
        run_id=resolved_run,
        episode_id=resolved_episode,
        source={
            "rpent": "f70d720+AgenticRoboRL/patches/rpent/rpent_f70d720.patch",
            "states": "states.json",
            "transcript": transcript_path.name,
        },
        task=task,
        outcome=outcome,
        conversion={"matched": matched, "warnings": warnings},
        stats={
            "n_memory_reads": n_memory_reads,
            "n_decisions": len(raw),
            "n_context_calls": n_context,
        },
        recovery_episodes=recovery_episodes,
        trailing_context_calls=[
            _context_call(item) for item in trailing.context_calls
        ],
        trailing_teacher_text=TeacherText(
            text=trailing.text,
            thinking=trailing.thinking,
            cites_memory=trailing.cites_memory,
        ),
    )
    decisions = [Decision.model_validate(record) for record in raw]
    out = Path(traces_root) / resolved_run / resolved_episode
    out.mkdir(parents=True, exist_ok=True)
    (out / "episode.json").write_text(
        json.dumps(episode.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    )
    lines = [
        json.dumps(decision.model_dump(mode="json"), ensure_ascii=False) for decision in decisions
    ]
    (out / "decisions.jsonl").write_text("".join(line + "\n" for line in lines))
    return out


def _disagreement(warnings: list[str]) -> bool:
    """True when counts, names, or the files needed to align them are wrong."""
    markers = (
        "execution count disagrees",
        "transcript tool",
        "no command.action",
        "command is not an object",
        "result is not an object",
        "no steps",
        "no terminated field",
        "no messages list",
        "expected one transcript",
    )
    return any(any(marker in warning for marker in markers) for warning in warnings)


def _warn_missing_signal(record: dict[str, Any], warnings: list[str]) -> None:
    primitive = record["primitive"]
    result = record["result"]
    step_idx = record["step_idx"]
    if primitive == "pi0_pick" and "success" not in result:
        warnings.append(f"step {step_idx} pi0_pick result has no success")
    if primitive == "move_to" and "final_dist_m" not in result:
        warnings.append(f"step {step_idx} move_to result has no final_dist_m")


def _find_transcript(source_dir: Path) -> tuple[Path, list[str]]:
    found = sorted(source_dir.glob("transcript_*.json"))
    if not found:
        raise FileNotFoundError(f"no transcript_*.json in {source_dir}")
    warnings: list[str] = []
    if len(found) != 1:
        warnings.append(
            f"expected one transcript_*.json, found {len(found)}; using {found[0].name}"
        )
    return found[0], warnings


def _episode_id_from_transcript(path: Path) -> str:
    name = path.name
    prefix = "transcript_"
    if name.startswith(prefix) and name.endswith(".json"):
        return name[len(prefix) : -len(".json")]
    return path.stem


def _walk_messages(
    messages: list[Any],
) -> tuple[list[_Call], _Call, int, list[str]]:
    warnings: list[str] = []
    executions: list[_Call] = []
    pending: list[_Call] = []
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    cites = False
    n_memory = 0

    def _take_turn() -> None:
        nonlocal cites
        pending.clear()
        text_parts.clear()
        thinking_parts.clear()
        cites = False

    for message in messages:
        if not isinstance(message, dict):
            warnings.append("transcript message is not an object")
            continue
        role = message.get("role")
        if role == "assistant":
            for kind, payload, block_warnings in _assistant_events(message.get("content")):
                warnings.extend(block_warnings)
                if kind == "text":
                    text_parts.append(payload)
                elif kind == "thinking":
                    thinking_parts.append(payload)
                elif kind == "tool":
                    call = payload
                    if call.name in EXECUTION_TOOLS:
                        executions.append(
                            _Call(
                                name=call.name,
                                arguments=call.arguments,
                                tool_call_id=call.tool_call_id,
                                context_calls=list(pending),
                                text=_join(text_parts),
                                thinking=_join(thinking_parts),
                                cites_memory=cites,
                            )
                        )
                        _take_turn()
                    else:
                        if call.name not in QUERY_TOOLS:
                            warnings.append(
                                f"unclassified tool {call.name!r}; treated as a query "
                                "and not matched to a states.json step"
                            )
                        if call.name in MEMORY_READ_TOOLS and is_memory_path(
                            str(call.arguments.get("path") or "")
                        ):
                            n_memory += 1
                            cites = True
                        pending.append(call)
        elif role in {"tool", "user"}:
            continue
        else:
            warnings.append(f"unrecognized transcript role {role!r}")

    trailing = _Call(
        name="",
        arguments={},
        context_calls=list(pending),
        text=_join(text_parts),
        thinking=_join(thinking_parts),
        cites_memory=cites,
    )
    return executions, trailing, n_memory, warnings


def _assistant_events(content: Any) -> list[tuple[str, Any, list[str]]]:
    """Content blocks in order: ``("text"|"thinking"|"tool", payload, warnings)``."""
    if content is None:
        return []
    if isinstance(content, str):
        return [("text", content, [])]
    if not isinstance(content, list):
        return [("text", "", ["assistant content is not a list"])]
    events: list[tuple[str, Any, list[str]]] = []
    for block in content:
        if isinstance(block, str):
            events.append(("text", block, []))
            continue
        if not isinstance(block, dict):
            events.append(("text", "", ["assistant content block is not an object"]))
            continue
        kind = block.get("type")
        if kind == "text":
            events.append(("text", str(block.get("text") or ""), []))
        elif kind == "thinking":
            events.append(("thinking", str(block.get("thinking") or ""), []))
        elif kind == "tool_use":
            block_warnings: list[str] = []
            name = block.get("name")
            if not isinstance(name, str) or not name:
                events.append(("text", "", ["assistant tool_use has no name"]))
                continue
            arguments = _arguments(block.get("input"), block_warnings)
            call_id = block.get("id")
            events.append(
                (
                    "tool",
                    _Call(
                        name=name,
                        arguments=arguments,
                        tool_call_id=call_id if isinstance(call_id, str) else None,
                    ),
                    block_warnings,
                )
            )
        elif kind == "image":
            continue
        else:
            events.append(("text", "", [f"unrecognized assistant block type {kind!r}"]))
    return events


def _arguments(value: Any, warnings: list[str]) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            warnings.append("tool_use input is not a JSON object")
            return {}
        if isinstance(loaded, dict):
            return loaded
    if value is not None:
        warnings.append("tool_use input is not an object")
    return {}


def _join(parts: list[str]) -> str:
    return "\n\n".join(part for part in parts if part)


def _context_call(call: _Call) -> dict[str, Any]:
    return ContextCall(
        name=call.name,
        arguments=call.arguments,
        tool_call_id=call.tool_call_id,
    ).model_dump()


def _step_position(steps: list[Any], step: dict[str, Any]) -> int:
    for index, candidate in enumerate(steps):
        if candidate is step:
            return index
    return 0


def _obs_before(steps: list[Any], position: int) -> dict[str, Any]:
    if position <= 0:
        return {"step_idx": None, "paths": []}
    previous = steps[position - 1]
    if not isinstance(previous, dict):
        return {"step_idx": None, "paths": []}
    step_idx = previous.get("step_idx")
    paths: list[str] = []
    if isinstance(step_idx, int) and not isinstance(step_idx, bool):
        for name in previous.get("artifacts") or []:
            if isinstance(name, str):
                paths.append(_artifact_relpath(name, step_idx))
    else:
        step_idx = None
    return {"step_idx": step_idx, "paths": paths}


def _artifact_relpath(name: str, step_idx: int) -> str:
    """Match ``EnvState._artifact_file`` at f70d720: ``<name>/<step:02d><suffix>``."""
    suffix = Path(name).suffix
    return f"{name}/{step_idx:02d}{suffix}"
