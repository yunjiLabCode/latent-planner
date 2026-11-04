"""Overfit the direct MLP on local episode traces.

The six collected episodes (one smoke run and five batch01 goal runs) are not
in this checkout. When ``--traces`` is omitted and no ``decisions.jsonl`` tree
is passed, the v0.3 converter materializes ``tests/fixtures`` and that set is
the overfit set. DINOv2-S weights are not downloaded; missing cache entries
use the stub image encoder.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from models.direct_mlp.dataset import HISTORY_K, DecisionDataset, input_dim
from models.direct_mlp.encoders import TEXT_DIM, dinov2_status
from models.direct_mlp.metrics import conflicting_inputs
from models.direct_mlp.model import DirectMLP
from models.direct_mlp.train import fit

_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES = _ROOT / "tests" / "fixtures"


def materialize_fixtures(fixtures: Path, dest: Path) -> list[Path]:
    from trace.converter import convert_episode

    written: list[Path] = []
    for source in sorted(path for path in fixtures.iterdir() if path.is_dir()):
        if not (source / "states.json").is_file():
            continue
        written.append(
            convert_episode(source, dest, run_id="fixtures", episode_id=source.name)
        )
    return written


def run(
    traces: Path | None = None,
    feature_cache: Path | None = None,
    *,
    epochs: int = 800,
    lr: float = 0.02,
    hidden: int = 128,
    seed: int = 0,
) -> dict[str, object]:
    owned: tempfile.TemporaryDirectory[str] | None = None
    if traces is None:
        owned = tempfile.TemporaryDirectory(prefix="direct-mlp-")
        materialize_fixtures(_FIXTURES, Path(owned.name))
        traces = Path(owned.name)
    try:
        dataset = DecisionDataset.from_root(traces, feature_cache)
        if len(dataset) == 0:
            raise ValueError(f"no decisions under {traces}")
        model = DirectMLP(input_dim(), TEXT_DIM, hidden=hidden, seed=seed)
        trained = fit(model, dataset.examples, epochs=epochs, lr=lr)
        episodes = sorted({example.episode_id for example in dataset.examples})
        match = trained["decision_match"]
        summary: dict[str, object] = {
            "episodes": episodes,
            "n_episodes": len(episodes),
            "n_decisions": len(dataset),
            "history_k": HISTORY_K,
            "image_encoder": dataset.image_source,
            "dinov2_s": dinov2_status(),
            "label_conflicts": len(conflicting_inputs(dataset.examples)),
            "hidden": hidden,
            "seed": seed,
            "lr": lr,
            "epochs_ran": trained["epochs_ran"],
            "loss": trained["loss"],
            "decision_match": match,
            "near_100": isinstance(match, float) and match >= 0.99,
            "primitive_match": trained["primitive_match"],
            "object_match": trained["object_match"],
            "gripper_match": trained["gripper_match"],
            "by_role": trained["by_role"],
            "inference_s_per_decision": trained["inference_s_per_decision"],
        }
        return summary
    finally:
        if owned is not None:
            owned.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Overfit the direct MLP on decisions.jsonl")
    parser.add_argument("--traces", type=Path, default=None, help="directory of episode folders")
    parser.add_argument("--feature-cache", type=Path, default=None, help="DINOv2-S CLS cache")
    parser.add_argument("--epochs", type=int, default=800)
    parser.add_argument("--lr", type=float, default=0.02)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    summary = run(
        args.traces,
        args.feature_cache,
        epochs=args.epochs,
        lr=args.lr,
        hidden=args.hidden,
        seed=args.seed,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
