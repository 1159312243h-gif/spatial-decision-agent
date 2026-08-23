from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .candidate_discovery import (
    CandidateDiscoveryFallbackMode,
    CandidateDiscoveryRequest,
    DiscoveryBounds,
    RETAIL_PROJECT_TYPES,
)
from .domain import NonEmptyString, ProjectType


class ScenarioConstraintOperation(StrEnum):
    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"


class ScenarioConstraintKey(StrEnum):
    PROJECT_TYPE = "project_type"
    REGION = "region"
    DISCOVERY_RADIUS_KM = "discovery_radius_km"
    MAX_CANDIDATES = "max_candidates"
    MINIMUM_SEPARATION_M = "minimum_separation_m"
    FALLBACK_MODE = "fallback_mode"
    MAX_RENT = "max_rent"
    MIN_FOOTFALL = "min_footfall"
    COMPETITOR_DISTANCE_M = "competitor_distance_m"


class ConstraintReadiness(StrEnum):
    EXECUTABLE = "executable"
    ADVISORY = "advisory"
    MISSING_DATA = "missing_data"


class ScenarioVersionStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class RegionResolutionSource(StrEnum):
    AMAP = "amap"
    FIXTURE_CATALOG = "fixture_catalog"


class ConversationTurnStatus(StrEnum):
    NEEDS_CLARIFICATION = "needs_clarification"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"


class ConversationMessageRole(StrEnum):
    USER = "user"
    AGENT = "agent"


class ScenarioConstraintAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: ScenarioConstraintOperation
    key: ScenarioConstraintKey
    value: Any | None = None
    source_text: str | None = None


class ConstraintDataReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: ScenarioConstraintKey
    readiness: ConstraintReadiness
    reason: NonEmptyString


class ScenarioConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: ScenarioConstraintKey
    value: Any
    readiness: ConstraintReadiness
    reason: NonEmptyString


class ConstraintConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: ScenarioConstraintKey
    message: NonEmptyString


class RegionResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: NonEmptyString
    normalized_name: NonEmptyString
    administrative_level: NonEmptyString
    center_longitude: float = Field(ge=-180, le=180)
    center_latitude: float = Field(ge=-90, le=90)
    discovery_bounds: DiscoveryBounds
    discovery_radius_km: float = Field(gt=0, le=7)
    source: RegionResolutionSource
    provider: NonEmptyString
    confidence: float = Field(ge=0, le=1)
    warnings: list[NonEmptyString] = Field(default_factory=list)


class ScenarioVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: NonEmptyString
    version_id: NonEmptyString
    version_number: int = Field(ge=1)
    parent_version_id: NonEmptyString | None = None
    status: ScenarioVersionStatus
    created_at: datetime
    confirmed_at: datetime | None = None
    confirmed_by: NonEmptyString | None = None
    project_type: ProjectType | None = None
    region_text: str | None = None
    region_resolution: RegionResolution | None = None
    discovery_radius_km: float = Field(default=4.0, gt=0, le=7)
    max_candidates: int = Field(default=8, ge=3, le=20)
    minimum_separation_m: int = Field(default=600, ge=100, le=5_000)
    fallback_mode: CandidateDiscoveryFallbackMode = (
        CandidateDiscoveryFallbackMode.MARKET_EXPLORATION
    )
    actions: list[ScenarioConstraintAction] = Field(default_factory=list)
    recorded_constraints: list[ScenarioConstraint] = Field(default_factory=list)
    data_readiness: list[ConstraintDataReadiness] = Field(default_factory=list)
    conflicts: list[ConstraintConflict] = Field(default_factory=list)
    clarifications: list[NonEmptyString] = Field(default_factory=list)

    @field_validator("created_at", "confirmed_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("场景版本时间必须包含时区")
        return value

    @property
    def ready_for_confirmation(self) -> bool:
        return not self.conflicts and not self.clarifications

    @property
    def discovery_ready(self) -> bool:
        return (
            self.ready_for_confirmation
            and self.project_type in RETAIL_PROJECT_TYPES
            and self.region_resolution is not None
        )

    def to_discovery_request(self) -> CandidateDiscoveryRequest | None:
        if not self.discovery_ready:
            return None
        assert self.project_type is not None
        assert self.region_resolution is not None
        return CandidateDiscoveryRequest(
            request_id=f"scenario-{self.version_id}",
            project_type=self.project_type,
            bounds=self.region_resolution.discovery_bounds,
            max_candidates=self.max_candidates,
            minimum_separation_m=self.minimum_separation_m,
            fallback_mode=self.fallback_mode,
        )


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: NonEmptyString
    role: ConversationMessageRole
    content: NonEmptyString
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("对话消息时间必须包含时区")
        return value


class ScenarioConversationSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: NonEmptyString
    scenario_id: NonEmptyString
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessage] = Field(default_factory=list)
    versions: list[ScenarioVersion] = Field(default_factory=list)
    active_version_id: NonEmptyString | None = None
    pending_version_id: NonEmptyString | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def session_times_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("对话会话时间必须包含时区")
        return value

    def version(self, version_id: str | None) -> ScenarioVersion | None:
        if version_id is None:
            return None
        return next(
            (item for item in self.versions if item.version_id == version_id),
            None,
        )

    @property
    def active_version(self) -> ScenarioVersion | None:
        return self.version(self.active_version_id)

    @property
    def pending_version(self) -> ScenarioVersion | None:
        return self.version(self.pending_version_id)


class ScenarioInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actions: list[ScenarioConstraintAction] = Field(default_factory=list)
    source: NonEmptyString
    warnings: list[NonEmptyString] = Field(default_factory=list)


class ScenarioInterpreter(Protocol):
    def interpret(
        self,
        message: str,
        current: ScenarioVersion | None,
    ) -> ScenarioInterpretation: ...


class ScenarioSessionStore(Protocol):
    def save_scenario_session(self, session: ScenarioConversationSession) -> None: ...

    def get_scenario_session(
        self,
        session_id: str,
    ) -> ScenarioConversationSession | None: ...

    def scenario_session_ttl(self, session_id: str) -> int: ...


class InMemoryScenarioSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ScenarioConversationSession] = {}

    def save_scenario_session(self, session: ScenarioConversationSession) -> None:
        self._sessions[session.session_id] = session

    def get_scenario_session(
        self,
        session_id: str,
    ) -> ScenarioConversationSession | None:
        return self._sessions.get(session_id)

    def scenario_session_ttl(self, session_id: str) -> int:
        return -1 if session_id in self._sessions else -2


class RegionResolver(Protocol):
    def resolve(
        self,
        region_text: str,
        *,
        radius_km: float,
    ) -> RegionResolution | None: ...


class ScenarioConversationReply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: NonEmptyString
    status: ConversationTurnStatus
    answer: NonEmptyString
    interpretation_source: NonEmptyString
    scenario_version: ScenarioVersion
    discovery_request: CandidateDiscoveryRequest | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)
    session_ttl_seconds: int | None = None
