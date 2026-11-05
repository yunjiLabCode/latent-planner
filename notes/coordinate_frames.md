# Coordinate frames

Read-only check. No pose JSON is in this repo. Stage-1 numbers below are the measured reset poses given with this check. The rounded record is in `/workspace/notes/run_log_20261103.md`. `scripts/verify_env_suites.sh` writes pose files outside the repo, under `$ROOT/outputs/env_verify/<suite>_t00.json`, from `robot0_base_pos` (MuJoCo body xpos of the robot root) and `robot0_eef_pos`.

## 1. eef z minus base z

| suite | base z (m) | eef z (m) | eef z − base z (m) |
| --- | --- | --- | --- |
| object | 0 | 0.26127947572964 | 0.26127947572964 |
| libero_10 | 0.42 | 0.6812794757296399 | 0.2612794757296399 |
| goal | 0.912 | 1.17327947572964 | 0.26127947572964 |

The three differences are the same offset. The libero_10 remainder differs from the other two by 1e-16, which is the last digit of the supplied eef z. The common value is 0.26127947572964 m. That is 0.261 m after rounding to three decimals, which is how the stage-1 log prints eef z (0.261, 0.681, 1.173) and how those rounded heights sit above the bases (0, 0.42, 0.912). It is not exactly 0.261 m.

Both quantities are world-frame heights. The fixed-base home pose is the same relative to the robot root, and the three suites place that root at different world z.

## 2. Position primitives

They take world coordinates.

`LiberoPrimitives.move_to` in `/workspace/RPent/robots/libero/tools.py` servos to a world-frame `xyz`. The error is `target - robot0_eef_pos` (`obs["states"][:3]`, the same vector `dump_state` stores as `robot0_eef_pos`). The tool schema in that file says `World-frame target [x, y, z] in meters`. `move_pose` uses the same subtraction. There is no subtraction of `robot0_base_pos`. The absolute z values in `RPent/robots/libero/guides/env_calibration.md` (about 0.26, 0.68, 1.17) are these world heights, not heights above the base.

The other two robots match that:

- `RoboCasaPrimitives.move_to` in `/workspace/RPent/robots/robocasa/primitives.py` servos to a world `xyz` against `robot0_eef_pos`. `navigate_to` takes world xy. `move_base` is a robot-local velocity, not a position target.
- `RoboTwinPrimitives.move_to` in `/workspace/RPent/robots/robotwin/primitives.py` plans to `[xyz | quat]` in the same pose `get_left_ee_pose` / `get_right_ee_pose` returns. `RPent/robots/robotwin/prompts/system.py` states those coordinates are world-frame metres. `rotate_wrist` turns about world z.

## 3. SAM3 and perception

SAM3 itself returns an image mask, a box, and a score. `Sam3Client.segment` in `/workspace/RPent/rpent/robots/components/sam3_client.py` takes a point as `[row, col]`. It does not return a 3D position.

Object positions from the perception tools are in the world frame. `LiberoPrimitives.segment` in `/workspace/RPent/robots/libero/tools.py` looks the mask up in the camera world map and returns `world_xyz`. That map is built by `_world_from_depth` with `extrinsic_cam2world`. `back_project` in the same file reads the same maps and returns `world_xyz` in metres. Agentview and wrist share that world frame.

RoboCasa `back_project` in `/workspace/RPent/robots/robocasa/tools.py` returns `world_xyz` from a map whose extrinsic is cam-to-world (`RPent/robots/robocasa/env_server.py`, `get_camera_meta`). RoboTwin `_world_from_depth` in `/workspace/RPent/robots/robotwin/toolkit.py` back-projects into the world frame and labels the observation `world_frame: "world"`.

## 4. Trace converter

`/workspace/src/trace/converter.py` (`convert_episode`) stores positions in that same world frame. It copies each `states.json` command, except `action`, into `arguments`, and copies the step `result` dict through unchanged. `move_to` therefore keeps world-frame `xyz` and result fields such as `target_xyz` and `final_eef_pos`. Nothing subtracts the robot base, and the schema has no frame field.

The file on disk is schema 0.3. `src/trace/schema.py` says the v0.2.1 matching, outcome, observation paths, and primitive success are unchanged, and this copy of arguments and results is that path. `obs_before` stores artifact paths, not coordinates. `segment` and `back_project` are query tools (`src/trace/tool_classes.py`); their `world_xyz` results are not copied, only their call arguments.
