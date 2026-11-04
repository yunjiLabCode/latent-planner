"""Small MLP. The loss is the sum of three classification losses.

Heads:
- primitive, over the fixed primitive list
- target object, a dot product against the frozen embeddings of this task's
  object list plus ``none``
- gripper, over ``absent`` / ``open`` / ``closed``

There is no coordinate regression head.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from models.direct_mlp.vocab import GRIPPER, PRIMITIVES


@dataclass
class Prediction:
    primitive_id: int
    object_id: int
    gripper_id: int


class DirectMLP:
    def __init__(self, in_dim: int, text_dim: int, hidden: int = 128, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.in_dim = in_dim
        self.text_dim = text_dim
        self.hidden = hidden
        self.n_primitive = len(PRIMITIVES)
        self.n_gripper = len(GRIPPER)
        self.W1 = rng.normal(0.0, np.sqrt(2.0 / in_dim), size=(in_dim, hidden))
        self.b1 = np.zeros(hidden)
        self.Wp = rng.normal(0.0, 0.01, size=(hidden, self.n_primitive))
        self.bp = np.zeros(self.n_primitive)
        self.Wg = rng.normal(0.0, 0.01, size=(hidden, self.n_gripper))
        self.bg = np.zeros(self.n_gripper)
        self.Wq = rng.normal(0.0, 0.01, size=(hidden, text_dim))
        self.bq = np.zeros(text_dim)
        self._adam = {
            name: {"m": np.zeros_like(value), "v": np.zeros_like(value)}
            for name, value in self.params().items()
        }
        self.updates = 0

    def params(self) -> dict[str, np.ndarray]:
        return {
            "W1": self.W1,
            "b1": self.b1,
            "Wp": self.Wp,
            "bp": self.bp,
            "Wg": self.Wg,
            "bg": self.bg,
            "Wq": self.Wq,
            "bq": self.bq,
        }

    def forward(
        self, x: np.ndarray, object_embs: list[np.ndarray]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[np.ndarray], np.ndarray]:
        z1 = x @ self.W1 + self.b1
        hidden = np.maximum(z1, 0.0)
        primitive = hidden @ self.Wp + self.bp
        gripper = hidden @ self.Wg + self.bg
        query = hidden @ self.Wq + self.bq
        scores = [emb @ query[index] for index, emb in enumerate(object_embs)]
        return z1, hidden, primitive, gripper, scores

    def predict(
        self, x: np.ndarray, object_embs: list[np.ndarray]
    ) -> tuple[list[Prediction], np.ndarray, np.ndarray, list[np.ndarray]]:
        _z1, _hidden, primitive, gripper, scores = self.forward(x, object_embs)
        predictions: list[Prediction] = []
        for index, row in enumerate(scores):
            predictions.append(
                Prediction(
                    primitive_id=int(np.argmax(primitive[index])),
                    object_id=int(np.argmax(row)),
                    gripper_id=int(np.argmax(gripper[index])),
                )
            )
        return predictions, primitive, gripper, scores

    def loss_grads(
        self,
        x: np.ndarray,
        object_embs: list[np.ndarray],
        primitive_y: np.ndarray,
        object_y: np.ndarray,
        gripper_y: np.ndarray,
    ) -> tuple[float, dict[str, np.ndarray]]:
        """Sum of mean cross-entropies, and its gradient."""
        count = x.shape[0]
        if count == 0:
            raise ValueError("empty batch")
        z1, hidden, primitive, gripper, scores = self.forward(x, object_embs)
        ce_p, d_primitive = _mean_ce_grad(primitive, primitive_y)
        ce_g, d_gripper = _mean_ce_grad(gripper, gripper_y)
        ce_o, d_query = _object_ce_grad(scores, object_y, object_embs)
        loss = ce_p + ce_o + ce_g

        d_hidden = d_primitive @ self.Wp.T + d_gripper @ self.Wg.T + d_query @ self.Wq.T
        d_z1 = d_hidden * (z1 > 0.0)
        grads = {
            "W1": x.T @ d_z1,
            "b1": d_z1.sum(axis=0),
            "Wp": hidden.T @ d_primitive,
            "bp": d_primitive.sum(axis=0),
            "Wg": hidden.T @ d_gripper,
            "bg": d_gripper.sum(axis=0),
            "Wq": hidden.T @ d_query,
            "bq": d_query.sum(axis=0),
        }
        return loss, grads

    def adam(self, grads: dict[str, np.ndarray], lr: float, max_norm: float = 5.0) -> None:
        _clip(grads, max_norm)
        self.updates += 1
        step = self.updates
        beta1 = 0.9
        beta2 = 0.999
        epsilon = 1e-8
        for name, param in self.params().items():
            grad = grads[name]
            state = self._adam[name]
            state["m"] = beta1 * state["m"] + (1.0 - beta1) * grad
            state["v"] = beta2 * state["v"] + (1.0 - beta2) * (grad * grad)
            m_hat = state["m"] / (1.0 - beta1**step)
            v_hat = state["v"] / (1.0 - beta2**step)
            param -= lr * m_hat / (np.sqrt(v_hat) + epsilon)


def _mean_ce_grad(logits: np.ndarray, targets: np.ndarray) -> tuple[float, np.ndarray]:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    probs = exp / exp.sum(axis=1, keepdims=True)
    rows = np.arange(len(targets))
    chosen = np.clip(probs[rows, targets], 1e-12, 1.0)
    loss = float(-np.log(chosen).mean())
    grad = probs.copy()
    grad[rows, targets] -= 1.0
    grad /= len(targets)
    return loss, grad


def _object_ce_grad(
    scores: list[np.ndarray],
    targets: np.ndarray,
    object_embs: list[np.ndarray],
) -> tuple[float, np.ndarray]:
    count = len(scores)
    total = 0.0
    d_query = np.zeros((count, object_embs[0].shape[1]), dtype=np.float64)
    for index, row in enumerate(scores):
        target = int(targets[index])
        shifted = row - row.max()
        exp = np.exp(shifted)
        probs = exp / exp.sum()
        total += float(-np.log(np.clip(probs[target], 1e-12, 1.0)))
        grad = probs.copy()
        grad[target] -= 1.0
        d_query[index] = object_embs[index].T @ (grad / count)
    return total / count, d_query


def _clip(grads: dict[str, np.ndarray], max_norm: float) -> None:
    total = 0.0
    for grad in grads.values():
        total += float(np.sum(grad * grad))
    norm = total**0.5
    if norm > max_norm:
        scale = max_norm / (norm + 1e-12)
        for name in grads:
            grads[name] *= scale
