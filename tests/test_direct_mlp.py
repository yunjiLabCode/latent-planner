"""Dataset, cache, and decision-match checks for the direct MLP."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models.direct_mlp.dataset import HISTORY_K, DecisionDataset, input_dim  # noqa: E402
from models.direct_mlp.encoders import (  # noqa: E402
    DINO_V2_S_DIM,
    DINOV2_S_DOWNLOADED,
    StubImageEncoder,
    cache_file,
)
from models.direct_mlp.metrics import matches  # noqa: E402
from models.direct_mlp.model import DirectMLP, Prediction  # noqa: E402
from models.direct_mlp.train import fit  # noqa: E402
from models.direct_mlp.vocab import GRIPPER, PRIMITIVES, gripper_index, target_object  # noqa: E402


def _decision(
    index: int,
    primitive: str,
    arguments: dict,
    paths: list[str],
    role: str = "new",
    success: bool | None = True,
) -> dict:
    return {
        "decision_index": index,
        "step_idx": index + 1,
        "primitive": primitive,
        "arguments": arguments,
        "obs_before": {"step_idx": index, "paths": paths},
        "labels": {
            "primitive_success": success,
            "relation_to_failed": None,
            "role": role,
            "type": role,
            "recovery_episode_id": None,
            "success_overridden": None,
        },
    }


def _write_episode(root: Path, episode_id: str, decisions: list[dict], task: dict) -> Path:
    episode_dir = root / episode_id
    episode_dir.mkdir(parents=True)
    (episode_dir / "episode.json").write_text(
        json.dumps(
            {
                "episode_id": episode_id,
                "task": task,
            }
        )
    )
    lines = [json.dumps(row) for row in decisions]
    (episode_dir / "decisions.jsonl").write_text("\n".join(lines) + "\n")
    return episode_dir


class LabelTests(unittest.TestCase):
    def test_coordinates_are_not_a_target(self) -> None:
        objects = ["bowl", "plate"]
        near = {"xyz": [0.1, 0.0, 0.2], "gripper": -1.0}
        far = {"xyz": [9.0, 9.0, 9.0], "gripper": -1.0}
        self.assertEqual(target_object(near, objects), "none")
        self.assertEqual(target_object(far, objects), "none")
        self.assertEqual(gripper_index(near), GRIPPER.index("open"))
        closed = {"xyz": [0.1, 0.0, 0.2], "gripper": 1.0}
        self.assertEqual(gripper_index(closed), GRIPPER.index("closed"))
        self.assertEqual(gripper_index({"prompt": "pick up the bowl"}), GRIPPER.index("absent"))
        self.assertEqual(target_object({"prompt": "pick up the bowl"}, objects), "bowl")

    def test_dataset_ignores_xyz_and_reads_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_episode(
                root,
                "ep",
                [
                    _decision(
                        0,
                        "pi0_pick",
                        {"prompt": "pick up the bowl"},
                        ["agentview.png/00.png", "wrist.png/00.png"],
                        role="new",
                        success=False,
                    ),
                    _decision(
                        1,
                        "move_to",
                        {"xyz": [0.1, 0.0, 0.2], "gripper": 1},
                        ["agentview.png/01.png", "wrist.png/01.png"],
                        role="restage",
                        success=True,
                    ),
                ],
                {"suite": "libero_object", "task": 1, "seed": 12, "objects": ["bowl", "plate"]},
            )
            twin_root = root / "twin"
            _write_episode(
                twin_root,
                "ep",
                [
                    _decision(
                        0,
                        "pi0_pick",
                        {"prompt": "pick up the bowl"},
                        ["agentview.png/00.png", "wrist.png/00.png"],
                        role="new",
                        success=False,
                    ),
                    _decision(
                        1,
                        "move_to",
                        {"xyz": [4.0, 5.0, 6.0], "gripper": 1},
                        ["agentview.png/01.png", "wrist.png/01.png"],
                        role="restage",
                        success=True,
                    ),
                ],
                {"suite": "libero_object", "task": 1, "seed": 12, "objects": ["bowl", "plate"]},
            )
            first = DecisionDataset([root / "ep"])
            second = DecisionDataset([twin_root / "ep"])
            self.assertEqual(len(first), 2)
            self.assertTrue(np.array_equal(first[1].x, second[1].x))
            self.assertEqual(first[1].primitive_id, PRIMITIVES.index("move_to"))
            self.assertEqual(first[1].object_names[first[1].object_id], "none")
            self.assertEqual(first[0].object_names[first[0].object_id], "bowl")
            self.assertEqual(first[1].x.shape, (input_dim(),))
            # Most recent history slot is the failed pick, not a pad.
            slot = history_slot_dim_slice(first[1].x)
            self.assertEqual(slot[PRIMITIVES.index("pi0_pick")], 1.0)
            self.assertEqual(first[1].role, "restage")
            self.assertEqual(HISTORY_K, 5)
            self.assertIs(DINOV2_S_DOWNLOADED, False)
            self.assertEqual(first.image_source, "stub")


def history_slot_dim_slice(feature: np.ndarray) -> np.ndarray:
    from models.direct_mlp.dataset import history_slot_dim

    slot = history_slot_dim()
    history = feature[-HISTORY_K * slot :]
    return history[-slot : -slot + len(PRIMITIVES) + 1]


class CacheTests(unittest.TestCase):
    def test_cache_replaces_stub_for_that_camera(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            episode = _write_episode(
                root,
                "ep",
                [
                    _decision(
                        0,
                        "release",
                        {},
                        ["agentview.png/00.png", "wrist.png/00.png"],
                    )
                ],
                {"language": "put the bowl on the plate", "objects": ["bowl", "plate"]},
            )
            cache = root / "cache"
            vector = np.linspace(-1.0, 1.0, DINO_V2_S_DIM, dtype=np.float32)
            path = cache_file(cache, "ep", "agentview.png/00.png")
            path.parent.mkdir(parents=True)
            np.save(path, vector)
            dataset = DecisionDataset([episode], feature_cache=cache)
            stub = StubImageEncoder().encode("ep", "agentview.png/00.png")
            self.assertFalse(np.allclose(vector, stub))
            np.testing.assert_allclose(dataset[0].x[:DINO_V2_S_DIM], vector, rtol=0, atol=0)
            self.assertEqual(dataset[0].image_sources, ("cache", "stub"))
            self.assertEqual(dataset.image_source, "mixed")
            self.assertEqual(dataset[0].object_names[dataset[0].object_id], "none")


class TrainTests(unittest.TestCase):
    def test_separable_pair_reaches_full_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_episode(
                root,
                "a",
                [
                    _decision(
                        0,
                        "pi0_pick",
                        {"prompt": "pick up the bowl"},
                        ["agentview.png/00.png", "wrist.png/00.png"],
                        role="new",
                    )
                ],
                {"language": "pick up the bowl", "objects": ["bowl"]},
            )
            _write_episode(
                root,
                "b",
                [
                    _decision(
                        0,
                        "set_gripper",
                        {"gripper": -1},
                        ["agentview.png/00.png", "wrist.png/00.png"],
                        role="retry",
                    )
                ],
                {"language": "open the drawer", "objects": ["drawer"]},
            )
            dataset = DecisionDataset([root / "a", root / "b"])
            model = DirectMLP(input_dim(), dataset[0].object_embs.shape[1], hidden=32, seed=0)
            trained = fit(model, dataset.examples, epochs=400, lr=0.05)
            self.assertEqual(trained["decision_match"], 1.0)
            self.assertEqual(trained["by_role"]["new"]["match"], 1.0)
            self.assertEqual(trained["by_role"]["retry"]["n"], 1)
            self.assertIsNone(trained["by_role"]["recovery"]["match"])
            self.assertGreater(trained["inference_s_per_decision"], 0.0)
            self.assertTrue(
                matches(
                    Prediction(
                        primitive_id=dataset[0].primitive_id,
                        object_id=dataset[0].object_id,
                        gripper_id=dataset[0].gripper_id,
                    ),
                    dataset[0].primitive_id,
                    dataset[0].object_id,
                    dataset[0].gripper_id,
                )
            )


if __name__ == "__main__":
    unittest.main()
