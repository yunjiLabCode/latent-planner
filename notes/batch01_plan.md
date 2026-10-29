# batch01 episodes

10 episodes, init 11 only. Script: `scripts/collect_batch.sh`. Not launched.

`tasks.jsonl` has 8 suites: `libero_spatial_task`, `libero_spatial_swap`, `libero_object_task`, `libero_object_swap`, `libero_goal_task`, `libero_goal_swap`, `libero_10_task`, `libero_10_swap`.

Spatial is out. The smoke episode was `libero_spatial_task` task 0 init 11. The other three families are goal, object, and long (`libero_10`). The four suites are the `*_task` suite of each of those, plus `libero_goal_swap` so goal is collected in both layouts. Tasks are the first rows of each suite. Init 11 is the first training init. Eval inits 1–10 are unused.

| suite | tasks | init |
| --- | --- | --- |
| libero_goal_task | 0, 1, 2 | 11 |
| libero_object_task | 0, 1 | 11 |
| libero_10_task | 0, 1, 2 | 11 |
| libero_goal_swap | 0, 1 | 11 |

Output: `$ROOT/outputs/batch01/{suite}/task_{task:02d}/seed_011/attempt_00/`. `ROOT` defaults to `/data/yunji/latent-planner-work`.
