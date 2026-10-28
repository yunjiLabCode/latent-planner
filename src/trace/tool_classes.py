"""LIBERO tool classes for RPent commit f70d720.

``Toolkit.execute_tool`` writes a ``states.json`` step unless the handler is
marked ``@readonly`` (``rpent/tools/toolkit.py``). The patch
``AgenticRoboRL/patches/rpent/rpent_f70d720.patch`` does not add or remove
tools. It only confines ``read_text_file`` and ``list_dir`` under the
``proven`` knowledge profile.

Execution tools are the LIBERO handlers that are not ``@readonly``:

- primitive methods on ``LiberoPrimitives`` (``robots/libero/tools.py``)
- ``reset``, registered in exploration mode as ``LiberoToolkit._reset_episode``
  (``robots/libero/toolkit.py``), which is not ``@readonly``

Query tools are ``@readonly`` and do not create a step:

- ``view_env_state``, ``view_camera_meta``, ``back_project``, ``segment``
- common tools ``read_text_file``, ``write_text_file``, ``list_dir``, ``finish``
  (``rpent/tools/common.py``)
"""

from __future__ import annotations

from pathlib import Path

# Handlers that call get_env_state and therefore append a states.json step.
EXECUTION_TOOLS: frozenset[str] = frozenset(
    {
        "reset",
        "move_to",
        "pi0_pick",
        "pi0_doubled",
        "release",
        "set_gripper",
        "rotate_wrist",
        "rotate_pitch",
        "move_pose",
    }
)

# @readonly handlers. They attach to the next execution record.
QUERY_TOOLS: frozenset[str] = frozenset(
    {
        "view_env_state",
        "view_camera_meta",
        "back_project",
        "segment",
        "read_text_file",
        "write_text_file",
        "list_dir",
        "finish",
    }
)

# File tools whose path can count as a memory read.
MEMORY_READ_TOOLS: frozenset[str] = frozenset({"read_text_file", "list_dir"})


def is_memory_path(path: str) -> bool:
    """Return whether ``path`` is an f70d720 memory-corpus path.

    ``get_memory_dir`` is ``<repo>/resources/<robot>/memory``
    (``rpent/utils/config.py``). The local-eval prompt reads ``MEMORY.md``
    and ``global/``, ``suite/``, and ``task/`` under that directory.
    """
    if not path or not str(path).strip():
        return False
    parsed = Path(path)
    return "memory" in parsed.parts or parsed.name == "MEMORY.md"
