"""Frozen image and text features.

Image input is a DINOv2-S CLS vector (384-d, ``dinov2_vits14``) loaded from a
pre-extracted cache. This module does not download weights. When a cache entry
is missing, :class:`StubImageEncoder` fills the same shape so training can run.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

DINO_V2_S_NAME = "dinov2_vits14"
DINO_V2_S_DIM = 384
TEXT_DIM = 128

# Weights were not fetched. Episode images are not in this checkout, and the
# cache is the only image path the dataset reads.
DINOV2_S_DOWNLOADED = False


def dinov2_status() -> dict[str, object]:
    return {
        "model": DINO_V2_S_NAME,
        "dim": DINO_V2_S_DIM,
        "downloaded": DINOV2_S_DOWNLOADED,
    }


def cache_file(cache_root: Path, episode_id: str, relpath: str) -> Path:
    """``<cache>/<episode_id>/<relpath>.npy`` for one CLS vector."""
    relative = Path(relpath)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"observation path escapes the episode: {relpath}")
    return cache_root / episode_id / Path(str(relative) + ".npy")


def load_cached_cls(path: Path, dim: int = DINO_V2_S_DIM) -> np.ndarray:
    """Load a cached CLS vector.

    Accepts shape ``(dim,)`` or a token matrix ``(tokens, dim)`` whose first
    row is the CLS token, which is how DINOv2 lays out ``x_norm_clstoken``
    beside patch tokens. ``.npz`` files use the array named ``cls``.
    """
    if path.suffix == ".npz":
        with np.load(path) as bundle:
            if "cls" not in bundle:
                raise ValueError(f"{path} has no cls array")
            array = np.asarray(bundle["cls"])
    else:
        array = np.asarray(np.load(path))
    array = np.asarray(array, dtype=np.float32)
    if array.ndim == 2 and array.shape[1] == dim:
        array = array[0]
    if array.shape != (dim,):
        raise ValueError(f"{path} has shape {array.shape}, expected {(dim,)}")
    return array


class FeatureCache:
    """Read-only DINOv2-S cache. Missing keys return ``None``."""

    def __init__(self, root: Path | None, dim: int = DINO_V2_S_DIM):
        self.root = None if root is None else Path(root)
        self.dim = dim

    def get(self, episode_id: str, relpath: str) -> np.ndarray | None:
        if self.root is None:
            return None
        path = cache_file(self.root, episode_id, relpath)
        npz = path.with_suffix(".npz")
        if path.is_file():
            return load_cached_cls(path, self.dim)
        if npz.is_file():
            return load_cached_cls(npz, self.dim)
        return None


class StubImageEncoder:
    """Deterministic 384-d stand-in with no learned weights and no download.

    The same ``(episode_id, relpath)`` always maps to the same vector. A
    missing camera is the zero vector, not a hashed path.
    """

    name = "stub"
    dim = DINO_V2_S_DIM

    def encode(self, episode_id: str, relpath: str | None) -> np.ndarray:
        if relpath is None:
            return np.zeros(self.dim, dtype=np.float32)
        digest = hashlib.sha256(f"{episode_id}\0{relpath}".encode()).digest()
        seed = int.from_bytes(digest[:8], "little")
        vector = np.random.default_rng(seed).standard_normal(self.dim).astype(np.float32)
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector


class StubTextEncoder:
    """Frozen hashed character trigrams. Same text, same unit vector."""

    name = "stub"
    dim = TEXT_DIM

    def encode(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float64)
        padded = f" {text.lower()} "
        if not text.strip():
            return vector.astype(np.float32)
        for index in range(len(padded) - 2):
            digest = hashlib.sha256(padded[index : index + 3].encode()).digest()
            bucket = int.from_bytes(digest[:2], "little") % self.dim
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector.astype(np.float32)
