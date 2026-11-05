# Experiment 1: direct MLP overfit on six real episodes

Hawaii, 2026-11-04 19:23 KST. The collector in tmux `batch02` was left running. The two planner episodes were not stopped. GPU 3 was not used.

## Episodes

Five batch01 goal episodes and the smoke episode. 78 decisions, 156 camera frames (agentview and wrist for each decision).

| episode | source |
|---|---|
| `libero_spatial_task_t00_seed011` | smoke |
| `libero_goal_task_t01_seed011_attempt00` | batch01, the rc=0 run |
| `libero_goal_task_t00_seed011_attempt00` | batch01-retry2 |
| `libero_goal_task_t02_seed011_attempt00` | batch01-retry2 |
| `libero_goal_swap_t00_seed011_attempt00` | batch01-retry2 |
| `libero_goal_swap_t01_seed011_attempt00` | batch01-retry2 |

Code is `origin/main` `16973ae` (`src/models/direct_mlp/`), extracted outside the checkout to `/data/yunji/latent-planner-work/tmp/src`. The git checkout was not modified for the run.

## Device

GPU 2 before the run: 19999 MiB used, 4025 MiB free, 24576 MiB total. The 22 GiB cap is 22528 MiB, so the headroom was 2529 MiB. A DINOv2-S CUDA context on top of the collector would cross that line. Features and the MLP ran on CPU. `CUDA_VISIBLE_DEVICES` was empty for this process.

After the run, GPU 2 was again 19999 MiB used and 4025 MiB free.

## Features

DINOv2-S (`dinov2_vits14`) weights: `/data/yunji/latent-planner-work/cache/torch/hub/checkpoints/dinov2_vits14_pretrain.pth`. CLS vectors, 384-d, written to `/data/yunji/latent-planner-work/cache/dinov2_s/<episode_id>/<image path>.npy`. 156 new files. The dataset reports `image_encoder=dinov2_s`. The package flag `dinov2_s.downloaded` stays false because that constant is hardcoded in `encoders.py`; the weights used here were downloaded into the cache above.

## Overfit

Full-batch Adam, hidden 128, lr 0.02, seed 0. Stopped at decision match 1.0.

| quantity | value |
|---|---|
| epochs | 75 |
| loss | 0.008068 |
| decisions | 78 |
| label conflicts | 0 |
| train decision match | 1.0 |
| primitive / object / gripper | 1.0 / 1.0 / 1.0 |
| inference seconds per decision | 1.52e-5 |

The inference time is one batched MLP forward after the features are already on the examples. It does not include DINOv2.

Match by role, all on the train set:

| role | n | match |
|---|---:|---:|
| new | 41 | 1.0 |
| retry | 10 | 1.0 |
| restage | 20 | 1.0 |
| restage_retry | 2 | 1.0 |
| recovery | 5 | 1.0 |
