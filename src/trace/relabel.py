"""Recompute role labels in a decisions.jsonl file."""

from __future__ import annotations

import json
from pathlib import Path

from trace.rules import classify_labels


def relabel(decisions_path: Path | str) -> None:
    """Reread ``decisions_path`` and rewrite role label fields.

    ``role``, ``type`` (equal to ``role``), and ``recovery_episode_id`` are
    computed again from ``primitive``, ``result``, and ``arguments``.
    ``primitive_success`` and ``relation_to_failed`` already stored on each
    line are left as they are. ``episode.json`` is not rewritten.
    """
    path = Path(decisions_path)
    records: list[dict] = []
    for line in path.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))
    roles, _episodes = classify_labels(records)
    for index, record in enumerate(records):
        labels = record.get("labels")
        if not isinstance(labels, dict):
            raise ValueError(f"decision {index} has no labels object")
        labels["role"] = roles[index]["role"]
        labels["type"] = roles[index]["role"]
        labels["recovery_episode_id"] = roles[index]["recovery_episode_id"]
    body = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    path.write_text(body)
