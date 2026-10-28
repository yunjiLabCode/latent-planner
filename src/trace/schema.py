"""Pydantic models for trace schema v0.2.

Matching, outcome, and observation paths are unchanged from v0.1.
Label rules are documented in ``notes/trace_schema_v0.2.md``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Literal["0.2"] = "0.2"


class ObsBefore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_idx: int | None
    paths: list[str]


class ContextCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any]
    tool_call_id: str | None = None


class TeacherText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    thinking: str = ""
    cites_memory: bool = False


class Labels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primitive_success: bool | None
    relation_to_failed: str | None
    role: str
    type: str
    recovery_episode_id: int | None = None


class RecoveryEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    failed_primitive: str
    start_decision: int
    end_decision: int
    n_attempts: int
    resolved: bool


class Decision(BaseModel):
    """One executed primitive that created a states.json step."""

    model_config = ConfigDict(extra="forbid")

    decision_index: int
    step_idx: int
    primitive: str
    arguments: dict[str, Any]
    tool_call_id: str | None = None
    obs_before: ObsBefore
    context_calls: list[ContextCall]
    teacher_text: TeacherText
    result: dict[str, Any]
    terminated: bool
    truncated: bool
    elapsed_s: float | None = None
    labels: Labels


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    terminated: bool
    truncated: bool


class Conversion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched: bool
    warnings: list[str]


class EpisodeStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_memory_reads: int
    n_decisions: int
    n_context_calls: int


class Episode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.2"] = SCHEMA_VERSION
    run_id: str
    episode_id: str
    source: dict[str, Any]
    task: dict[str, Any]
    outcome: Outcome
    conversion: Conversion
    stats: EpisodeStats
    recovery_episodes: list[RecoveryEpisode] = Field(default_factory=list)
    trailing_context_calls: list[ContextCall] = Field(default_factory=list)
    trailing_teacher_text: TeacherText = Field(default_factory=TeacherText)
