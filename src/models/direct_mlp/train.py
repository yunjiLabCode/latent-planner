"""Train the direct MLP by summing the three classification losses."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from models.direct_mlp.metrics import evaluate
from models.direct_mlp.model import DirectMLP


def fit(
    model: DirectMLP,
    examples: Sequence,
    *,
    epochs: int = 800,
    lr: float = 0.02,
) -> dict[str, object]:
    """Full-batch Adam. Stops early once decision match is 1."""
    if not examples:
        raise ValueError("no examples")
    x = np.stack([example.x for example in examples]).astype(np.float64)
    embs = [np.asarray(example.object_embs, dtype=np.float64) for example in examples]
    primitive_y = np.asarray([example.primitive_id for example in examples], dtype=np.int64)
    object_y = np.asarray([example.object_id for example in examples], dtype=np.int64)
    gripper_y = np.asarray([example.gripper_id for example in examples], dtype=np.int64)
    loss = 0.0
    metrics: dict[str, object] = {}
    ran = 0
    for epoch in range(epochs):
        loss, grads = model.loss_grads(x, embs, primitive_y, object_y, gripper_y)
        model.adam(grads, lr)
        ran = epoch + 1
        if ran == 1 or ran == epochs or ran % 25 == 0:
            metrics = evaluate(model, examples)
            match = metrics["decision_match"]
            if match == 1.0:
                break
    if not metrics:
        metrics = evaluate(model, examples)
    return {"epochs_ran": ran, "loss": loss, **metrics}
