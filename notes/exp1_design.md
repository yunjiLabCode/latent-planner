# Experiment 1: direct MLP

A small MLP predicts the teacher’s next execution decision from frozen features. Later experiments should reuse `DecisionDataset` and `evaluate` in `src/models/direct_mlp/`. Coordinates are not a target.

## Input

One example is one line of `decisions.jsonl` (schema v0.3), joined with the sibling `episode.json`.

- **Images.** `obs_before.paths` supplies one agentview frame and one wrist frame (depth paths are skipped). Each frame is a frozen DINOv2-S CLS vector: `dinov2_vits14`, 384-d. The dataset does not run the encoder. It reads a pre-extracted cache at `<cache>/<episode_id>/<relative path>.npy` (shape `(384,)` or `(tokens, 384)` with the CLS token on row 0). A `.npz` with an array named `cls` is also accepted. If the file is missing, `StubImageEncoder` fills the same 384-d shape from a hash of the episode id and path. A missing camera is the zero vector.
- **History.** The previous `K=5` decisions, oldest first, left-padded. Each slot is the primitive, the target object, and the result (`labels.primitive_success`: success, failure, or unknown). The current decision’s own result is not an input.
- **Task text.** A frozen text encoder. The stored task sentence is used when `episode.json` has `task.language`, `task.text`, `task.task_language`, or `task.instruction`. Otherwise the text is `suite`, `task`, and `seed`. This run uses a hashed character-trigram encoder (128-d) because no text-encoder weights were loaded.

`move_to` / `move_pose` fields `xyz` are not copied into the input.

## Output

Three classification heads. The loss is their sum (mean cross-entropy each).

| Head | Classes |
| --- | --- |
| Primitive | `move_to`, `move_pose`, `pi0_pick`, `pi0_doubled`, `release`, `set_gripper`, `rotate_wrist`, `rotate_pitch`, `reset`, `other` |
| Target object | The task object list, plus `none` |
| Gripper | `absent` (key not logged), `open` (`gripper < 0`), `closed` (`gripper >= 0`) |

The object list is `task.objects` when present, otherwise the nouns of the task sentence, otherwise nouns of the episode’s `prompt` arguments. The head scores each name with a dot product against its frozen text embedding and softmaxes over that list only. A command whose arguments do not name one of those objects, including a coordinate `move_to`, is `none`. There is no regression head and no `xyz` prediction.

LIBERO’s logged convention is `gripper = +1` closed and `gripper = -1` open. An omitted key stays `absent` rather than being filled with the runtime default.

## Metrics

`evaluate` in `src/models/direct_mlp/metrics.py`.

- **Decision match.** Primitive, target object, and gripper are all correct.
- **Match by role.** The same match rate inside `new`, `retry`, `restage`, `restage_retry`, and `recovery`. A role with no decisions has match `null`.
- **Inference time per decision.** Wall time of one batched MLP forward, after one warmup, divided by the number of decisions. Cache loads and the stub encoder are not included; features are already on the example.

## Overfit

DINOv2-S was not downloaded. There is no feature cache and no episode images in this checkout, and PyTorch is not installed, so the run used the stub image encoder. The cache loader is in `src/models/direct_mlp/encoders.py` for a later drop-in of real CLS files.

The six collected episodes (smoke `libero_spatial_task` task 0 seed 11, plus batch01 goal task 0, task 1, task 2, swap 0, and swap 1) are not in this tree as `decisions.jsonl`. Hawaii was not read. The overfit converted the eight episode fixtures under `tests/fixtures` with the v0.3 converter: `batch01_goal_swap_0`, `batch01_goal_swap_1`, `batch01_goal_task_0`, `batch01_goal_task_1`, `batch01_goal_task_2`, `first_success`, `restage_retry`, `truncated_failure`. That is 16 decisions. No two decisions share an input and disagree on the label.

Train decision match is **1.0** (primitive 1.0, object 1.0, gripper 1.0) after 25 epochs, hidden size 128, Adam learning rate 0.02, seed 0. Loss at that step was about `5.6e-6`. Train accuracy on this fixture set is near 100%. This is not a measurement on the six collected episodes.

| Role | n | match |
| --- | ---: | ---: |
| new | 10 | 1.0 |
| retry | 1 | 1.0 |
| restage | 3 | 1.0 |
| restage_retry | 2 | 1.0 |
| recovery | 0 | — |

Inference time was about `9.4e-5` seconds per decision (`0.094` ms) on this machine.

```
PYTHONPATH=src python3 -m models.direct_mlp.overfit
PYTHONPATH=src python3 -m models.direct_mlp.overfit --traces <episode-root> --feature-cache <cache>
```
