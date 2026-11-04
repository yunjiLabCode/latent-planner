"""Decision match, match by role, and inference time per decision."""

from __future__ import annotations

import time
from typing import Sequence

import numpy as np

from models.direct_mlp.model import DirectMLP, Prediction
from models.direct_mlp.vocab import ROLES


def matches(prediction: Prediction, primitive_id: int, object_id: int, gripper_id: int) -> bool:
    """A decision matches when primitive, target object, and gripper all match."""
    return (
        prediction.primitive_id == primitive_id
        and prediction.object_id == object_id
        and prediction.gripper_id == gripper_id
    )


def evaluate(model: DirectMLP, examples: Sequence) -> dict[str, object]:
    """Score ``examples``. Inference time is one batched MLP forward, divided by N.

    Features are already on the examples. Cache and stub encoding are not
    included. One untimed forward runs first.
    """
    if not examples:
        return {
            "n": 0,
            "decision_match": None,
            "primitive_match": None,
            "object_match": None,
            "gripper_match": None,
            "by_role": {role: {"n": 0, "match": None} for role in ROLES},
            "inference_s_per_decision": None,
        }
    x = np.stack([example.x for example in examples]).astype(np.float64)
    embs = [np.asarray(example.object_embs, dtype=np.float64) for example in examples]
    model.predict(x, embs)
    started = time.perf_counter()
    predictions, primitive_logits, gripper_logits, scores = model.predict(x, embs)
    elapsed = time.perf_counter() - started
    del primitive_logits, gripper_logits, scores

    decision_hits: list[bool] = []
    primitive_hits: list[bool] = []
    object_hits: list[bool] = []
    gripper_hits: list[bool] = []
    by_role: dict[str, list[bool]] = {role: [] for role in ROLES}
    for example, prediction in zip(examples, predictions):
        primitive_ok = prediction.primitive_id == example.primitive_id
        object_ok = prediction.object_id == example.object_id
        gripper_ok = prediction.gripper_id == example.gripper_id
        ok = primitive_ok and object_ok and gripper_ok
        decision_hits.append(ok)
        primitive_hits.append(primitive_ok)
        object_hits.append(object_ok)
        gripper_hits.append(gripper_ok)
        by_role.setdefault(example.role, []).append(ok)
    return {
        "n": len(examples),
        "decision_match": _rate(decision_hits),
        "primitive_match": _rate(primitive_hits),
        "object_match": _rate(object_hits),
        "gripper_match": _rate(gripper_hits),
        "by_role": {
            role: {"n": len(hits), "match": _rate(hits)} for role, hits in by_role.items()
        },
        "inference_s_per_decision": elapsed / len(examples),
    }


def conflicting_inputs(examples: Sequence) -> list[list[int]]:
    """Indexes whose inputs match but whose labels do not."""
    groups: dict[bytes, list[int]] = {}
    for index, example in enumerate(examples):
        key = np.asarray(example.x, dtype=np.float64).tobytes()
        groups.setdefault(key, []).append(index)
    conflicts: list[list[int]] = []
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        labels = {
            (examples[index].primitive_id, examples[index].object_id, examples[index].gripper_id)
            for index in indexes
        }
        if len(labels) > 1:
            conflicts.append(indexes)
    return conflicts


def _rate(hits: Sequence[bool]) -> float | None:
    if not hits:
        return None
    return float(sum(hits) / len(hits))
