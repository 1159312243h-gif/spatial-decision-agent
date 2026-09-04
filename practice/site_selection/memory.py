from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .domain import NonEmptyString, ProjectType


class ScenarioMemoryMode(StrEnum):
    DISABLED = "disabled"
    SUGGEST = "suggest"
    APPLY_DEFAULTS = "apply_defaults"


class ConversationContextSummary(BaseModel):
    """Structured compression used for LLM context, not business truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary_id: NonEmptyString
    summarized_through_message_id: NonEmptyString
    covered_message_count: int = Field(gt=0)
    retained_message_count: int = Field(ge=0)
    source_character_count: int = Field(gt=0)
    summary_character_count: int = Field(gt=0)
    compression_ratio: float = Field(gt=0, le=1)
    narrative: NonEmptyString
    current_constraints: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def updated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("上下文摘要时间必须包含时区")
        return value


class ScenarioPreferenceProfile(BaseModel):
    """User-approved defaults; an explicit current request always wins."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: NonEmptyString
    project_type: ProjectType
    discovery_radius_km: float = Field(gt=0, le=7)
    max_candidates: int = Field(ge=3, le=20)
    minimum_separation_m: int = Field(ge=100, le=5_000)
    fallback_mode: NonEmptyString
    source_session_id: NonEmptyString
    source_version_id: NonEmptyString
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("偏好记忆时间必须包含时区")
        return value

    @field_validator("fallback_mode")
    @classmethod
    def fallback_mode_is_supported(cls, value: str) -> str:
        supported = {"strict", "commercial_land_proxy", "market_exploration"}
        if value not in supported:
            raise ValueError("偏好记忆包含不支持的用地降级策略")
        return value


class ScenarioEpisode(BaseModel):
    """A privacy-minimized record of one confirmed scenario."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    episode_id: NonEmptyString
    actor_id: NonEmptyString
    project_type: ProjectType
    session_id: NonEmptyString
    scenario_id: NonEmptyString
    version_id: NonEmptyString
    region_text: str | None = None
    summary: NonEmptyString
    scenario: dict[str, Any]
    confirmed_at: datetime
    created_at: datetime

    @field_validator("confirmed_at", "created_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("情景记忆时间必须包含时区")
        return value


class ScenarioMemoryRecall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: NonEmptyString
    project_type: ProjectType
    mode: ScenarioMemoryMode
    preference: ScenarioPreferenceProfile | None = None
    recent_episodes: list[ScenarioEpisode] = Field(default_factory=list)
    applied_fields: list[NonEmptyString] = Field(default_factory=list)


class ScenarioMemorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: NonEmptyString
    preferences: list[ScenarioPreferenceProfile] = Field(default_factory=list)
    recent_episodes: list[ScenarioEpisode] = Field(default_factory=list)


class ScenarioMemoryDeleteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: NonEmptyString
    deleted_preferences: int = Field(ge=0)
    deleted_episodes: int = Field(ge=0)


class ScenarioInterpretationContext(BaseModel):
    """Bounded, untrusted context supplied only to a context-aware interpreter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: ConversationContextSummary | None = None
    recent_messages: list[dict[str, Any]] = Field(default_factory=list)
    memory_recall: ScenarioMemoryRecall | None = None


class ScenarioMemoryStore(Protocol):
    def get_preference(
        self,
        actor_id: str,
        project_type: ProjectType,
    ) -> ScenarioPreferenceProfile | None: ...

    def list_preferences(self, actor_id: str) -> list[ScenarioPreferenceProfile]: ...

    def save_preference(self, preference: ScenarioPreferenceProfile) -> None: ...

    def save_episode(self, episode: ScenarioEpisode) -> None: ...

    def save_confirmed_memory(
        self,
        preference: ScenarioPreferenceProfile,
        episode: ScenarioEpisode,
    ) -> None: ...

    def list_episodes(
        self,
        actor_id: str,
        *,
        project_type: ProjectType | None = None,
        limit: int = 5,
    ) -> list[ScenarioEpisode]: ...

    def delete_actor_memory(self, actor_id: str) -> ScenarioMemoryDeleteResult: ...


class InMemoryScenarioMemoryStore:
    def __init__(self) -> None:
        self._preferences: dict[tuple[str, ProjectType], ScenarioPreferenceProfile] = {}
        self._episodes: dict[str, ScenarioEpisode] = {}

    def get_preference(
        self,
        actor_id: str,
        project_type: ProjectType,
    ) -> ScenarioPreferenceProfile | None:
        value = self._preferences.get((actor_id, project_type))
        return value.model_copy(deep=True) if value is not None else None

    def list_preferences(self, actor_id: str) -> list[ScenarioPreferenceProfile]:
        return [
            item.model_copy(deep=True)
            for (stored_actor, _), item in sorted(
                self._preferences.items(),
                key=lambda pair: pair[0][1].value,
            )
            if stored_actor == actor_id
        ]

    def save_preference(self, preference: ScenarioPreferenceProfile) -> None:
        key = (preference.actor_id, preference.project_type)
        existing = self._preferences.get(key)
        value = preference
        if existing is not None:
            value = preference.model_copy(update={"created_at": existing.created_at})
        self._preferences[key] = value.model_copy(deep=True)

    def save_episode(self, episode: ScenarioEpisode) -> None:
        self._episodes[episode.episode_id] = episode.model_copy(deep=True)

    def save_confirmed_memory(
        self,
        preference: ScenarioPreferenceProfile,
        episode: ScenarioEpisode,
    ) -> None:
        self.save_preference(preference)
        self.save_episode(episode)

    def list_episodes(
        self,
        actor_id: str,
        *,
        project_type: ProjectType | None = None,
        limit: int = 5,
    ) -> list[ScenarioEpisode]:
        if limit <= 0:
            raise ValueError("情景记忆返回数量必须大于 0")
        values = [
            value
            for value in self._episodes.values()
            if value.actor_id == actor_id
            and (project_type is None or value.project_type is project_type)
        ]
        values.sort(key=lambda item: item.confirmed_at, reverse=True)
        return [item.model_copy(deep=True) for item in values[:limit]]

    def delete_actor_memory(self, actor_id: str) -> ScenarioMemoryDeleteResult:
        preference_keys = [key for key in self._preferences if key[0] == actor_id]
        episode_keys = [
            key for key, value in self._episodes.items() if value.actor_id == actor_id
        ]
        for key in preference_keys:
            del self._preferences[key]
        for key in episode_keys:
            del self._episodes[key]
        return ScenarioMemoryDeleteResult(
            actor_id=actor_id,
            deleted_preferences=len(preference_keys),
            deleted_episodes=len(episode_keys),
        )


class StructuredScenarioContextCompactor:
    """Compresses old dialogue into version-derived structured context."""

    def __init__(self, *, max_recent_messages: int = 6) -> None:
        if max_recent_messages < 2:
            raise ValueError("工作记忆至少保留 2 条最近消息")
        self.max_recent_messages = max_recent_messages

    def interpretation_context(
        self,
        messages: Sequence[Any],
        *,
        summary: ConversationContextSummary | None,
        memory_recall: ScenarioMemoryRecall | None,
    ) -> ScenarioInterpretationContext:
        recent = list(messages)[-self.max_recent_messages :]
        return ScenarioInterpretationContext(
            summary=summary,
            recent_messages=[
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else dict(item)
                for item in recent
            ],
            memory_recall=memory_recall,
        )

    def compact(
        self,
        messages: Sequence[Any],
        current: Any,
        *,
        updated_at: datetime,
    ) -> ConversationContextSummary | None:
        values = list(messages)
        covered = values[: -self.max_recent_messages]
        if not covered:
            return None
        source_characters = sum(len(str(item.content)) for item in covered)
        constraints = _current_constraints(current)
        narrative = _summary_narrative(current, len(covered), constraints)
        summary_characters = len(narrative)
        return ConversationContextSummary(
            summary_id=f"context-{current.version_id}",
            summarized_through_message_id=covered[-1].message_id,
            covered_message_count=len(covered),
            retained_message_count=min(len(values), self.max_recent_messages),
            source_character_count=max(1, source_characters),
            summary_character_count=max(1, summary_characters),
            compression_ratio=min(1.0, summary_characters / max(1, source_characters)),
            narrative=narrative,
            current_constraints=constraints,
            updated_at=updated_at,
        )


def _current_constraints(current: Any) -> dict[str, Any]:
    return {
        "project_type": (
            current.project_type.value if current.project_type is not None else None
        ),
        "region_text": current.region_text,
        "discovery_radius_km": current.discovery_radius_km,
        "max_candidates": current.max_candidates,
        "minimum_separation_m": current.minimum_separation_m,
        "fallback_mode": current.fallback_mode.value,
        "recorded_constraints": {
            item.key.value: item.value for item in current.recorded_constraints
        },
    }


def _summary_narrative(
    current: Any,
    covered_message_count: int,
    constraints: dict[str, Any],
) -> str:
    project_type = constraints["project_type"] or "未设置"
    region = constraints["region_text"] or "未设置"
    return (
        f"已压缩 {covered_message_count} 条较早消息；当前场景版本 "
        f"v{current.version_number}（{current.status.value}）；"
        f"项目类型={project_type}；区域={region}；"
        f"发现半径={current.discovery_radius_km:g}公里；"
        f"候选数量={current.max_candidates}；"
        f"最小间距={current.minimum_separation_m}米；"
        f"降级策略={current.fallback_mode.value}。"
    )
