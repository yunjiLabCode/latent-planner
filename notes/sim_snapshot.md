# Simulator snapshot

Read-only. No code change, no experiment, no commit. Sources are `/workspace/RPent`, `/workspace/AgenticRoboRL`, the packages those trees install (`rpent-liberopro` 0.2.0, `rpent-rlinf` 0.3.0, `rpent-openpi` at `RLinf/openpi` branch `rpent`, `robosuite` at `RLinf/robosuite` branch `rlinf`). This RPent checkout imports `rlinf.envs.libero.libero_env`. That module is in `rpent-rlinf` 0.3.0. Current RLinf `main` has moved it to `rlinf/envs/sim/libero/libero_env.py`.

## 1. Can the env save and restore the full simulator state?

No full-state snapshot. LIBERO-PRO can save and restore a flattened kinematic state. RPent does not expose that call. Its reset reloads the task init file, then steps.

LIBERO-PRO `OffScreenRenderEnv` subclasses `ControlEnv` in `liberopro/liberopro/envs/env_wrapper.py` (`rpent-liberopro` 0.2.0; same file on `RLinf/LIBERO-PRO` branch `rpent`).

| Function | What it does |
| --- | --- |
| `ControlEnv.get_sim_state` | `self.env.sim.get_state().flatten()` |
| `ControlEnv.set_state` | `self.env.sim.set_state_from_flattened(mujoco_state)` |
| `ControlEnv.set_init_state` | calls `regenerate_obs_from_state` |
| `ControlEnv.regenerate_obs_from_state` | `set_state`, then `sim.forward()`, success check, `_post_process`, `_update_observables(force=True)`, `_get_observations` |

The vector is robosuite `MjSimState`, not `mujoco.mj_getState` / `mj_setState`. In `robosuite/utils/binding_utils.py` (`RLinf/robosuite` branch `rlinf`):

- `MjSim.get_state` copies `data.time`, `data.qpos`, `data.qvel`.
- `MjSimState.flatten` concatenates `[time, qpos, qvel]`.
- `MjSimState.from_flattened` asserts `sim.model.na == 0`. Actuator activation state is not in the vector.
- `MjSim.set_state` and `MjSim.set_state_from_flattened` write time, qpos, and qvel only. They do not write `ctrl`, warmstart, mocap, or userdata, and they do not call `forward`. `regenerate_obs_from_state` does call `forward`.

RLinf's worker accepts those two commands. `rlinf/envs/libero/venv.py`, function `_worker`: command `get_sim_state` calls `env.get_sim_state()`; command `set_init_state` calls `env.set_init_state(data)`. `LiberoEnv` does not call `get_sim_state`.

The path RPent actually uses is init-file reset, not an arbitrary restore.

- `LiberoEnv._reconfigure` in `rlinf/envs/libero/libero_env.py` calls `self.env.reset` and then, unless the variant is `plus`, `self.env.set_init_state` with the state from `_get_reset_states`.
- `LiberoEnv.reset` then applies 15 zero actions. If `reset_gripper_open` is true, the last action component is `-1`.
- `robots/libero/env_server.py` `make_env` / `build_env_cfg` pins that file: `use_fixed_reset_state_ids=True`, `specific_reset_id = sum of earlier tasks' init counts + (seed % trials)`, `auto_reset=False`, `reset_gripper_open=True`.
- `LiberoEnvFacade.reset` only calls `self._env.reset()`. Registered RPC methods are `env.reset`, `env.step`, `env.chunk_step`, `env.raw_obs`, `env.render_camera`, `env.get_camera_meta`, `env.get_task_language`. There is no get/set state method.
- `LiberoPrimitives.reset` in `robots/libero/tools.py` calls `self.env.reset()` and caches the observation.

`/workspace/AgenticRoboRL` does not add a snapshot API. `patches/rpent/README.md` says a later RPent recorded simulator state for an unreported experiment, and that recording is not in `rpent_f70d720.patch`.

## 2. What has to be restored together

`qpos` / `qvel` already hold object free joints, arm joints, and gripper finger joints. Time is the first scalar. That is the whole saved vector. These other pieces change the next step and are not in it.

**Controller, outside MuJoCo data.** `Robot.reset` in `robosuite/robots/robot.py` writes the robot init qpos and calls `_load_controller()`, which rebuilds the composite controller. `CompositeController.reset` in `robosuite/controllers/composite/composite_controller.py` calls each part's `reset_goal`. `OperationalSpaceController.reset_goal` in `robosuite/controllers/parts/arm/osc.py` sets `goal_pos`, `goal_ori`, and the position/orientation interpolators from the current pose. Gripper `current_action` and the robot `recent_qpos` / `recent_actions` / `recent_torques` buffers are also set in `Robot.reset`. `set_init_state` does not call `Robot.reset`. After a mid-episode `set_state`, the OSC goal is still the goal from before the restore. `LiberoEnv.reset` covers this only because it `reset()`s first and then takes 15 zero steps after `set_init_state`. `data.ctrl` is also left as it was.

**Robosuite episode counters.** `RobotEnv._reset_internal` in `robosuite/environments/base.py` sets `cur_time = 0`, `timestep = 0`, `done = False`. `set_state` does not. LIBERO `BDDLBaseDomain.step` in `liberopro/liberopro/envs/bddl_base_domain.py` replaces `done` with `_check_success()` on every step, so the success bit is recomputed. The step counter is not.

**RLinf counters.** `LiberoEnv._reset_metrics` zeros `_elapsed_steps`, `success_once`, `returns`, and the other episode metrics. Truncation is `_elapsed_steps >= max_episode_steps` inside `LiberoEnv.step`. Restoring qpos without `_elapsed_steps` changes when the episode truncates. `auto_reset` is false in `build_env_cfg`.

**RPent harness flags, on the client, not in the sim.**

- `LiberoEnvClient.terminated` and `truncated` in `robots/libero/env_client.py`. `check_done` ORs them. `reset` clears them. `step` and `chunk_step` assert if either is already set, so a restored non-terminal sim still refuses actions while the flag stays true.
- `LiberoPrimitives` caches `_last_obs`, `_last_obs_eef_pos`, `_last_obs_eef_z`, `_last_obs_gripper` in `set_obs`. `reset` refreshes them. A later primitive reads those caches.
- `LiberoToolkit._solved` in `robots/libero/toolkit.py` is OR-accumulated from `record.terminated` in `get_env_state`. Episode `reset` does not clear it. Eval mode does not register the `reset` tool.

A mid-episode restore that should continue the same way needs the flattened state, a controller reset (`reset_goal` or a fresh `_load_controller`) after the qpos write, gripper `current_action`, and the harness flags above. RPent's `reset` does not do that partial restore. It reloads the init file and settles for 15 steps.

## 3. Where π0.5 sampling noise could take a seed

`PI0Pytorch.sample_noise(self, shape, device)` in `src/openpi/models_pytorch/pi0_pytorch.py` (`RLinf/openpi` branch `rpent`). It calls `torch.normal(mean=0.0, std=1.0, size=shape, dtype=torch.float32, device=device)` and takes no seed and no generator.

Caller: `OpenPi0ForRLActionPrediction.sample_actions` in `rlinf/models/embodiment/openpi/openpi_action_model.py` (`rpent-rlinf` 0.3.0). It calls `self.sample_noise` for the initial noise when `noise is None`, and again each denoise step as `x_t_mean + sample_noise(...) * x_t_std`. `Pi05VLAFacade.predict` in `rpent/robots/components/pi05_vla_server.py` calls `predict_action_batch(..., mode="eval")` and rejects every option except `mode`. `LiberoPrimitives._vlm_chunk` passes `mode="eval"`. In eval, `sample_actions` sets `denoise_inds` to `-1`, so `sample_mean_var_val` uses `flow_ode` and `x_t_std` is zeros. The initial `sample_noise` is the draw that changes the action. Not modified.
