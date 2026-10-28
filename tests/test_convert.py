"""Conversion checks for the three v0.1 fixtures."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trace.converter import convert_episode  # noqa: E402
from trace.relabel import relabel  # noqa: E402
from trace.rules import (  # noqa: E402
    MOVE_TO_TOL_M,
    decision_type,
    primitive_success,
    relation_to_failed,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(episode_dir: Path) -> tuple[dict, list[dict]]:
    episode = json.loads((episode_dir / "episode.json").read_text())
    lines = (episode_dir / "decisions.jsonl").read_text().splitlines()
    decisions = [json.loads(line) for line in lines if line.strip()]
    return episode, decisions


class FixtureTests(unittest.TestCase):
    def test_first_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = convert_episode(
                FIXTURES / "first_success",
                tmp,
                run_id="run-a",
                episode_id="ep-first",
            )
            self.assertEqual(out, Path(tmp) / "run-a" / "ep-first")
            episode, decisions = _load(out)
            self.assertEqual(len(decisions), 1)
            self.assertEqual(decisions[0]["labels"]["role"], "new")
            self.assertEqual(decisions[0]["labels"]["type"], "new")
            self.assertIsNone(decisions[0]["labels"]["recovery_episode_id"])
            self.assertEqual(episode["recovery_episodes"], [])
            self.assertIs(decisions[0]["labels"]["primitive_success"], True)
            self.assertIs(episode["outcome"]["success"], True)
            self.assertIs(episode["conversion"]["matched"], True)
            self.assertEqual(episode["conversion"]["warnings"], [])
            self.assertEqual(
                decisions[0]["obs_before"]["paths"],
                ["agentview.png/00.png", "wrist.png/00.png"],
            )
            self.assertEqual(
                [call["name"] for call in decisions[0]["context_calls"]],
                ["list_dir", "view_env_state", "read_text_file"],
            )
            self.assertIs(decisions[0]["teacher_text"]["cites_memory"], True)
            self.assertEqual(episode["stats"]["n_memory_reads"], 1)
            self.assertEqual(episode["trailing_context_calls"][0]["name"], "finish")
            self.assertEqual(list(out.rglob("*.png")), [])

    def test_restage_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = convert_episode(FIXTURES / "restage_retry", tmp, run_id="run-b", episode_id="ep-restage")
            episode, decisions = _load(out)
            self.assertEqual(
                [row["labels"]["type"] for row in decisions],
                ["new", "restage", "restage_retry"],
            )
            self.assertEqual(
                [row["labels"]["role"] for row in decisions],
                ["new", "restage", "restage_retry"],
            )
            self.assertEqual(
                [row["labels"]["recovery_episode_id"] for row in decisions],
                [1, 1, 1],
            )
            self.assertEqual(
                episode["recovery_episodes"],
                [
                    {
                        "id": 1,
                        "failed_primitive": "pi0_pick",
                        "start_decision": 0,
                        "end_decision": 2,
                        "n_attempts": 2,
                        "resolved": True,
                    }
                ],
            )
            self.assertIs(decisions[0]["labels"]["primitive_success"], False)
            self.assertIs(decisions[1]["labels"]["primitive_success"], True)
            self.assertEqual(decisions[1]["labels"]["relation_to_failed"], None)
            self.assertEqual(decisions[2]["labels"]["relation_to_failed"], "restage_retry")
            self.assertIs(episode["outcome"]["success"], True)
            self.assertIs(episode["conversion"]["matched"], True)
            self.assertEqual(decisions[0]["obs_before"]["paths"], ["agentview.png/00.png"])
            self.assertEqual(decisions[1]["obs_before"]["paths"], ["wrist.png/01.png"])
            self.assertEqual(decisions[1]["context_calls"][0]["name"], "segment")
            self.assertEqual(decisions[2]["teacher_text"]["text"], "Pick again.")

    def test_truncated_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = convert_episode(
                FIXTURES / "truncated_failure",
                tmp,
                run_id="run-c",
                episode_id="ep-fail",
            )
            episode, decisions = _load(out)
            self.assertEqual(decisions[0]["labels"]["role"], "new")
            self.assertEqual(decisions[0]["labels"]["type"], "new")
            self.assertIs(decisions[0]["labels"]["primitive_success"], False)
            self.assertEqual(
                episode["recovery_episodes"],
                [
                    {
                        "id": 1,
                        "failed_primitive": "pi0_pick",
                        "start_decision": 0,
                        "end_decision": 0,
                        "n_attempts": 1,
                        "resolved": False,
                    }
                ],
            )
            self.assertIs(episode["outcome"]["success"], False)
            self.assertIs(episode["outcome"]["terminated"], False)
            self.assertIs(episode["outcome"]["truncated"], True)
            self.assertIs(episode["conversion"]["matched"], True)
            self.assertEqual((out / "episode.json").is_file(), True)
            self.assertEqual((out / "decisions.jsonl").is_file(), True)

    def test_name_mismatch_clears_matched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "src"
            shutil.copytree(FIXTURES / "first_success", copied)
            transcript = copied / "transcript_object_t0_s11.json"
            payload = json.loads(transcript.read_text())
            for block in payload["messages"][1]["content"]:
                if isinstance(block, dict) and block.get("name") == "pi0_pick":
                    block["name"] = "move_to"
            transcript.write_text(json.dumps(payload))
            out = convert_episode(copied, Path(tmp) / "traces", run_id="run-d", episode_id="ep-mismatch")
            episode, decisions = _load(out)
            self.assertIs(episode["conversion"]["matched"], False)
            self.assertTrue(
                any("transcript tool" in warning for warning in episode["conversion"]["warnings"])
            )
            self.assertEqual(decisions[0]["primitive"], "pi0_pick")
            self.assertEqual(decisions[0]["context_calls"], [])

    def test_relabel_rewrites_only_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = convert_episode(
                FIXTURES / "restage_retry", tmp, run_id="run-e", episode_id="ep-relabel"
            )
            path = out / "decisions.jsonl"
            episode_before = (out / "episode.json").read_text()
            records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            records[0]["labels"]["primitive_success"] = True
            records[2]["labels"]["type"] = "unlabeled"
            records[2]["labels"]["role"] = "new"
            records[2]["labels"]["recovery_episode_id"] = None
            records[2]["labels"]["relation_to_failed"] = None
            path.write_text("".join(json.dumps(row) + "\n" for row in records))
            relabel(path)
            rewritten = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            self.assertIs(rewritten[0]["labels"]["primitive_success"], True)
            self.assertEqual(rewritten[2]["labels"]["relation_to_failed"], None)
            self.assertEqual(rewritten[2]["labels"]["role"], "restage_retry")
            self.assertEqual(rewritten[2]["labels"]["type"], "restage_retry")
            self.assertEqual(rewritten[2]["labels"]["recovery_episode_id"], 1)
            self.assertEqual(rewritten[2]["result"], records[2]["result"])
            self.assertEqual((out / "episode.json").read_text(), episode_before)

    def test_default_ids_follow_directory_and_transcript_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = convert_episode(FIXTURES / "truncated_failure", tmp)
            self.assertEqual(out, Path(tmp) / "truncated_failure" / "goal_t2_s13")


class RuleTests(unittest.TestCase):
    def test_move_to_tol_default(self) -> None:
        self.assertEqual(MOVE_TO_TOL_M, 0.012)
        self.assertIs(primitive_success("move_to", {"final_dist_m": 0.011}, {}), True)
        self.assertIs(primitive_success("move_to", {"final_dist_m": 0.012}, {}), False)
        self.assertIs(
            primitive_success("move_to", {"final_dist_m": 0.02}, {"tol": 0.03, "target_yaw": 1.0}),
            True,
        )
        self.assertIs(primitive_success("move_to", {}, {}), None)

    def test_pick_and_doubled(self) -> None:
        self.assertIs(primitive_success("pi0_pick", {"success": False}, {}), False)
        self.assertIs(primitive_success("pi0_pick", {"success": True}, {}), True)
        self.assertIs(primitive_success("pi0_doubled", {"success": False}, {}), None)
        self.assertIs(primitive_success("pi0_doubled", {"success": True}, {}), True)
        self.assertIs(primitive_success("release", {"terminated": True}, {}), None)

    def test_restage_window(self) -> None:
        def row(name: str, success: bool | None) -> dict:
            if name == "pi0_pick":
                result = {"success": success is True}
            elif name == "move_to":
                result = {"final_dist_m": 0.0 if success else 1.0}
            else:
                result = {}
            return {"primitive": name, "result": result, "arguments": {}}

        pattern = [row("pi0_pick", False), row("move_to", False), row("move_to", True), row("pi0_pick", True)]
        self.assertEqual(relation_to_failed(pattern, 3), "restage_retry")
        self.assertEqual(decision_type(pattern, 0), "new")
        self.assertEqual(decision_type(pattern, 1), "restage")
        self.assertEqual(decision_type(pattern, 2), "restage")
        self.assertEqual(decision_type(pattern, 3), "restage_retry")
        broken = [row("pi0_pick", False), row("release", None), row("pi0_pick", True)]
        self.assertIsNone(relation_to_failed(broken, 2))
        doubled = [row("pi0_doubled", False), row("move_to", True), row("pi0_pick", True)]
        self.assertIsNone(relation_to_failed(doubled, 2))


def _convert_commands(root: Path, commands: list[tuple[str, dict, dict]]) -> tuple[dict, list[dict]]:
    steps: list[dict] = [
        {
            "step_idx": 0,
            "state": {},
            "terminated": False,
            "truncated": False,
            "artifacts": ["agentview.png"],
        }
    ]
    content: list[dict] = [{"type": "text", "text": "act"}]
    for index, (name, arguments, result) in enumerate(commands, start=1):
        steps.append(
            {
                "step_idx": index,
                "state": {},
                "terminated": False,
                "truncated": False,
                "artifacts": ["agentview.png"],
                "command": {"action": name, **arguments},
                "result": result,
                "elapsed_s": 0.1,
            }
        )
        content.append(
            {"type": "tool_use", "id": f"c{index}", "name": name, "input": arguments}
        )
    source = root / "src"
    source.mkdir()
    (source / "states.json").write_text(json.dumps({"run_artifacts": [], "steps": steps}))
    (source / "transcript_case.json").write_text(
        json.dumps(
            {
                "suite": "libero_object",
                "task": 0,
                "seed": 1,
                "model": "test",
                "messages": [{"role": "assistant", "content": content}],
            }
        )
    )
    out = convert_episode(source, root / "traces", run_id="run", episode_id="ep")
    return _load(out)


def _pick(success: bool) -> tuple[str, dict, dict]:
    return ("pi0_pick", {"prompt": "bowl"}, {"name": "pick", "success": success})


def _move() -> tuple[str, dict, dict]:
    return ("move_to", {"xyz": [0, 0, 1]}, {"name": "move_to", "final_dist_m": 0.001})


class RoleTests(unittest.TestCase):
    def _run(self, commands: list[tuple[str, dict, dict]]) -> tuple[dict, list[dict]]:
        with tempfile.TemporaryDirectory() as tmp:
            return _convert_commands(Path(tmp), commands)

    def test_retry_after_failed_pick(self) -> None:
        episode, decisions = self._run([_pick(False), _pick(True)])
        self.assertEqual([row["labels"]["role"] for row in decisions], ["new", "retry"])
        self.assertEqual([row["labels"]["type"] for row in decisions], ["new", "retry"])
        self.assertEqual(episode["recovery_episodes"][0]["n_attempts"], 2)
        self.assertIs(episode["recovery_episodes"][0]["resolved"], True)
        self.assertEqual(
            [row["labels"]["recovery_episode_id"] for row in decisions],
            [1, 1],
        )

    def test_repeated_restage_is_one_episode(self) -> None:
        episode, decisions = self._run(
            [_pick(False), _move(), _pick(False), _move(), _pick(True)]
        )
        self.assertEqual(
            [row["labels"]["role"] for row in decisions],
            ["new", "restage", "restage_retry", "restage", "restage_retry"],
        )
        self.assertEqual(len(episode["recovery_episodes"]), 1)
        episode_row = episode["recovery_episodes"][0]
        self.assertEqual(episode_row["n_attempts"], 3)
        self.assertIs(episode_row["resolved"], True)
        self.assertEqual(episode_row["failed_primitive"], "pi0_pick")
        self.assertEqual(episode_row["start_decision"], 0)
        self.assertEqual(episode_row["end_decision"], 4)
        self.assertEqual(
            {row["labels"]["recovery_episode_id"] for row in decisions},
            {1},
        )

    def test_release_then_move_is_restage(self) -> None:
        _episode, decisions = self._run(
            [
                _pick(False),
                ("release", {}, {"name": "release"}),
                _move(),
                _pick(True),
            ]
        )
        self.assertEqual(
            [row["labels"]["role"] for row in decisions],
            ["new", "restage", "restage", "restage_retry"],
        )

    def test_other_primitive_is_recovery(self) -> None:
        episode, decisions = self._run(
            [
                _pick(False),
                (
                    "pi0_doubled",
                    {"prompt": "push"},
                    {"name": "pi0_doubled", "success": False, "terminated": False},
                ),
            ]
        )
        self.assertEqual([row["labels"]["role"] for row in decisions], ["new", "recovery"])
        self.assertIs(decisions[1]["labels"]["primitive_success"], None)
        self.assertEqual(len(episode["recovery_episodes"]), 1)
        self.assertIs(episode["recovery_episodes"][0]["resolved"], True)
        self.assertEqual(episode["recovery_episodes"][0]["n_attempts"], 1)
        self.assertEqual(episode["recovery_episodes"][0]["end_decision"], 1)

    def test_open_failure_is_unresolved(self) -> None:
        episode, decisions = self._run([_pick(False)])
        self.assertEqual(decisions[0]["labels"]["role"], "new")
        self.assertEqual(decisions[0]["labels"]["type"], "new")
        self.assertEqual(
            episode["recovery_episodes"],
            [
                {
                    "id": 1,
                    "failed_primitive": "pi0_pick",
                    "start_decision": 0,
                    "end_decision": 0,
                    "n_attempts": 1,
                    "resolved": False,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
