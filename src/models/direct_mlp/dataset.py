"""Decisions from ``decisions.jsonl`` as direct-MLP examples.

One example is one executed primitive. Inputs are cached image features for
the agentview and wrist frames in ``obs_before``, a frozen encoding of the
task text, and the previous ``K`` decisions (primitive, target, result).
Labels are the primitive, the target object, and discrete arguments.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from models.direct_mlp.encoders import (
    DINO_V2_S_DIM,
    TEXT_DIM,
    FeatureCache,
    StubImageEncoder,
    StubTextEncoder,
)
from models.direct_mlp.vocab import (
    NONE_OBJECT,
    PRIMITIVES,
    RESULTS,
    gripper_index,
    primitive_index,
    result_index,
    target_object,
    task_object_list,
    task_text,
)

HISTORY_K = 5


@dataclass
class Example:
    episode_id: str
    decision_index: int
    role: str
    x: np.ndarray
    object_embs: np.ndarray
    object_names: tuple[str, ...]
    primitive_id: int
    object_id: int
    gripper_id: int
    image_sources: tuple[str, str]


def history_slot_dim(text_dim: int = TEXT_DIM) -> int:
    """One past decision: primitive one-hot, result one-hot, target text."""
    return (len(PRIMITIVES) + 1) + (len(RESULTS) + 1) + text_dim


def input_dim(
    text_dim: int = TEXT_DIM,
    image_dim: int = DINO_V2_S_DIM,
    k: int = HISTORY_K,
) -> int:
    return image_dim * 2 + text_dim + k * history_slot_dim(text_dim)


def find_episode_dirs(root: Path) -> list[Path]:
    """Episode directories under ``root`` that contain ``decisions.jsonl``."""
    root = Path(root)
    if (root / "decisions.jsonl").is_file():
        return [root]
    return sorted(path.parent for path in root.rglob("decisions.jsonl"))


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a JSON object")
    return payload


def _read_decisions(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(row)
    rows.sort(key=lambda row: int(row.get("decision_index", 0)))
    return rows


def _camera_paths(paths: Sequence[Any]) -> tuple[str | None, str | None]:
    agentview: str | None = None
    wrist: str | None = None
    for item in paths:
        if not isinstance(item, str):
            continue
        stem = item.split("/", 1)[0].lower()
        if "depth" in stem:
            continue
        if stem.startswith("wrist") and wrist is None:
            wrist = item
        elif stem.startswith("agentview") and agentview is None:
            agentview = item
    return agentview, wrist


def _prompts(decisions: Sequence[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for row in decisions:
        arguments = row.get("arguments")
        if not isinstance(arguments, dict):
            continue
        prompt = arguments.get("prompt")
        if isinstance(prompt, str):
            found.append(prompt)
    return found


class DecisionDataset:
    """All decisions under a set of episode directories.

    Image vectors come from ``feature_cache`` when the file exists and from
    :class:`StubImageEncoder` otherwise. The text encoder is the stub. Both
    encoders are frozen: this object stores vectors, not weights.
    """

    def __init__(
        self,
        episode_dirs: Sequence[Path],
        feature_cache: Path | None = None,
        *,
        k: int = HISTORY_K,
    ):
        self.k = k
        self.image_encoder = StubImageEncoder()
        self.text_encoder = StubTextEncoder()
        self.cache = FeatureCache(feature_cache)
        self.examples: list[Example] = []
        for episode_dir in episode_dirs:
            self.examples.extend(self._load_episode(Path(episode_dir)))

    @classmethod
    def from_root(
        cls,
        root: Path,
        feature_cache: Path | None = None,
        *,
        k: int = HISTORY_K,
    ) -> DecisionDataset:
        dirs = find_episode_dirs(root)
        if not dirs:
            raise FileNotFoundError(f"no decisions.jsonl under {root}")
        return cls(dirs, feature_cache, k=k)

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> Example:
        return self.examples[index]

    @property
    def image_source(self) -> str:
        sources = {source for example in self.examples for source in example.image_sources}
        sources.discard("missing")
        if not sources:
            return "missing"
        if sources == {"cache"}:
            return "dinov2_s"
        if sources == {"stub"}:
            return "stub"
        return "mixed"

    def _load_episode(self, episode_dir: Path) -> list[Example]:
        decisions = _read_decisions(episode_dir / "decisions.jsonl")
        episode_path = episode_dir / "episode.json"
        episode = _read_json(episode_path) if episode_path.is_file() else {}
        episode_id = str(episode.get("episode_id") or episode_dir.name)
        task = episode.get("task") if isinstance(episode.get("task"), dict) else {}
        objects = task_object_list(task, _prompts(decisions))
        text = task_text(task)
        if not text:
            text = episode_id
        text_vector = self.text_encoder.encode(text).astype(np.float64)
        history: list[tuple[int, int, str]] = []
        examples: list[Example] = []
        for row in decisions:
            arguments = row.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
            primitive = str(row.get("primitive") or "other")
            target = target_object(arguments, objects)
            obs = row.get("obs_before") if isinstance(row.get("obs_before"), dict) else {}
            paths = obs.get("paths") if isinstance(obs.get("paths"), list) else []
            agent_path, wrist_path = _camera_paths(paths)
            agent, agent_source = self._image(episode_id, agent_path)
            wrist, wrist_source = self._image(episode_id, wrist_path)
            feature = np.concatenate(
                [
                    agent,
                    wrist,
                    text_vector,
                    self._history_vector(history),
                ]
            )
            names = tuple(objects) + (NONE_OBJECT,)
            examples.append(
                Example(
                    episode_id=episode_id,
                    decision_index=int(row.get("decision_index", len(examples))),
                    role=str(labels.get("role") or "unknown"),
                    x=feature,
                    object_embs=self._object_matrix(names),
                    object_names=names,
                    primitive_id=primitive_index(primitive),
                    object_id=names.index(target),
                    gripper_id=gripper_index(arguments),
                    image_sources=(agent_source, wrist_source),
                )
            )
            success = labels.get("primitive_success")
            if success is not True and success is not False:
                success = None
            history.append((primitive_index(primitive), result_index(success), target))
        return examples

    def _image(self, episode_id: str, relpath: str | None) -> tuple[np.ndarray, str]:
        if relpath is None:
            return np.zeros(DINO_V2_S_DIM, dtype=np.float64), "missing"
        cached = self.cache.get(episode_id, relpath)
        if cached is not None:
            return cached.astype(np.float64), "cache"
        return self.image_encoder.encode(episode_id, relpath).astype(np.float64), "stub"

    def _object_matrix(self, names: Sequence[str]) -> np.ndarray:
        rows = [self.text_encoder.encode(name).astype(np.float64) for name in names]
        return np.stack(rows)

    def _history_vector(self, history: Sequence[tuple[int, int, str]]) -> np.ndarray:
        window = list(history)[-self.k :]
        pad = self.k - len(window)
        slots = [self._pad_slot() for _ in range(pad)]
        slots.extend(self._filled_slot(item) for item in window)
        return np.concatenate(slots)

    def _pad_slot(self) -> np.ndarray:
        primitive = np.zeros(len(PRIMITIVES) + 1, dtype=np.float64)
        primitive[-1] = 1.0
        result = np.zeros(len(RESULTS) + 1, dtype=np.float64)
        result[-1] = 1.0
        return np.concatenate([primitive, result, np.zeros(TEXT_DIM, dtype=np.float64)])

    def _filled_slot(self, item: tuple[int, int, str]) -> np.ndarray:
        primitive_id, result_id, target = item
        primitive = np.zeros(len(PRIMITIVES) + 1, dtype=np.float64)
        primitive[primitive_id] = 1.0
        result = np.zeros(len(RESULTS) + 1, dtype=np.float64)
        result[result_id] = 1.0
        text = self.text_encoder.encode(target).astype(np.float64)
        return np.concatenate([primitive, result, text])
