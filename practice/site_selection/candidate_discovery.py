from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from enum import StrEnum
from math import ceil, isfinite, sqrt
from time import perf_counter
from typing import TypedDict
from uuid import uuid4

import geopandas as gpd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_graph_runtime import compile_agent_plan_graph
from .agent_orchestration import (
    AgentExecutionPlan,
    AgentStepStatus,
    AgentStepTrace,
    build_candidate_discovery_execution_plan,
    order_agent_traces,
    trace_for,
)
from .domain import (
    CandidateParcel,
    DatasetEvidenceLevel,
    DatasetManifest,
    NonEmptyString,
    ProjectType,
)
from .evidence_snapshot import (
    CandidateDiscoverySnapshotStore,
    build_candidate_discovery_poi_snapshot,
)
from .poi import POIFeatureSet, POIProvider, POIQuery, POISourceMeta
from .poi_adapters import haversine_distance_m
from .online_poi_adapters import POIAvailabilityError
from .poi_scoring import POIScoringConfig, score_poi_feature_sets
from .poi_service import calculate_poi_metrics
from .online_land_use import (
    LandUseAvailabilityError,
    LandUseProvider,
    LandUseProviderError,
    LandUseQuery,
)
from .profiles import (
    ProjectProfile,
    get_project_profile,
    get_supported_poi_categories,
)
from .spatial.gateway import SpatialDatasetAccessError, SpatialDatasetNotFoundError
from .spatial.validate import SpatialValidationError, validate_spatial_dataset


RETAIL_PROJECT_TYPES = frozenset(
    {ProjectType.COFFEE_SHOP, ProjectType.CONVENIENCE_STORE}
)
LAND_USE_REQUIRED_FIELDS = frozenset(
    {"parcel_id", "land_use_class", "suitability", "area_hectares"}
)
DISCOVERY_REPAIR_GRID_SIDE = 2
DISCOVERY_REPAIR_MAX_WORKERS = 4


class CandidateDiscoveryBlockedError(RuntimeError):
    """Raised when candidate discovery lacks safe market or land-use evidence."""


class LandUseSuitability(StrEnum):
    ALLOWED = "allowed"
    REVIEW_REQUIRED = "review_required"
    EXCLUDED = "excluded"


class CandidateDiscoveryStrategy(StrEnum):
    REGISTERED_LAND = "registered_land"
    PUBLIC_LAND_OBSERVATION = "public_land_observation"
    COMMERCIAL_LAND_PROXY = "commercial_land_proxy"
    MARKET_EXPLORATION = "market_exploration"


class CandidateDiscoveryFallbackMode(StrEnum):
    STRICT = "strict"
    COMMERCIAL_LAND_PROXY = "commercial_land_proxy"
    MARKET_EXPLORATION = "market_exploration"


class CandidateDiscoveryPOIPurpose(StrEnum):
    SCORING = "scoring"
    RANGE_CONTEXT = "range_context"


class DiscoveryBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def bounds_are_ordered_and_bounded(self) -> DiscoveryBounds:
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("候选发现范围必须满足 west < east 且 south < north")
        diagonal_m = haversine_distance_m(
            self.west,
            self.south,
            self.east,
            self.north,
        )
        if diagonal_m > 20_000:
            raise ValueError("门店候选发现范围对角线不能超过 20 公里")
        return self

    @property
    def center(self) -> tuple[float, float]:
        return ((self.west + self.east) / 2, (self.south + self.north) / 2)

    def contains(self, longitude: float, latitude: float) -> bool:
        return (
            self.west <= longitude <= self.east
            and self.south <= latitude <= self.north
        )


class CandidateDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: NonEmptyString = Field(
        default_factory=lambda: f"discovery-{uuid4()}"
    )
    project_type: ProjectType
    bounds: DiscoveryBounds
    max_candidates: int = Field(default=8, ge=3, le=20)
    minimum_separation_m: int = Field(default=600, ge=100, le=5_000)
    poi_limit_per_group: int = Field(default=1_000, ge=100, le=1_000)
    range_poi_limit: int = Field(default=3_000, ge=100, le=5_000)
    fallback_mode: CandidateDiscoveryFallbackMode = (
        CandidateDiscoveryFallbackMode.MARKET_EXPLORATION
    )

    @model_validator(mode="after")
    def project_type_is_retail(self) -> CandidateDiscoveryRequest:
        if self.project_type not in RETAIL_PROJECT_TYPES:
            raise ValueError("候选自动发现当前只支持咖啡店和便利店")
        return self


class CandidateDiscoverySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_key: NonEmptyString
    purpose: CandidateDiscoveryPOIPurpose = CandidateDiscoveryPOIPurpose.SCORING
    provider: POIProvider
    dataset_id: NonEmptyString
    record_count: int = Field(ge=0)
    available_record_count: int | None = Field(default=None, ge=0)
    is_truncated: bool = False
    is_synthetic: bool = False
    fallback_from: POIProvider | None = None
    fallback_reason: NonEmptyString | None = None
    cache_hit: bool = False
    evidence_complete: bool = True
    incomplete_reasons: list[NonEmptyString] = Field(default_factory=list)
    repair_attempted: bool = False
    repair_query_count: int = Field(default=0, ge=0)
    repair_success_count: int = Field(default=0, ge=0)
    repair_added_record_count: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_evidence_quality(cls, values):
        if not isinstance(values, dict) or "evidence_complete" in values:
            return values
        copied = dict(values)
        reasons = []
        if copied.get("fallback_from") is not None:
            reasons.append("在线查询降级为 Fixture")
        elif copied.get("is_synthetic"):
            reasons.append("仅有合成 Fixture 证据")
        if copied.get("is_truncated"):
            reasons.append("返回截断或空间覆盖未完成")
        copied["evidence_complete"] = not reasons
        copied["incomplete_reasons"] = reasons
        return copied

    @model_validator(mode="after")
    def repair_counts_are_consistent(self) -> CandidateDiscoverySource:
        if self.repair_success_count > self.repair_query_count:
            raise ValueError("POI 修复成功数不能超过查询数")
        if self.repair_attempted != (self.repair_query_count > 0):
            raise ValueError("POI 修复状态必须与查询数一致")
        if self.evidence_complete and self.incomplete_reasons:
            raise ValueError("完整 POI 证据不能同时包含不完整原因")
        return self


class CandidateDiscoveryRangePOI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poi_id: NonEmptyString
    name: NonEmptyString
    category: NonEmptyString
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    provider: POIProvider
    dataset_id: NonEmptyString
    is_synthetic: bool = False
    source_group_keys: list[NonEmptyString] = Field(min_length=1)


class DiscoveredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    candidate: CandidateParcel
    market_score: float = Field(ge=0, le=100)
    land_use_class: NonEmptyString
    land_use_suitability: LandUseSuitability
    land_use_dataset_id: NonEmptyString | None = None
    land_use_dataset_version: NonEmptyString | None = None
    land_evidence_level: DatasetEvidenceLevel = (
        DatasetEvidenceLevel.UNSPECIFIED
    )
    formal_analysis_allowed: bool
    requires_human_review: bool
    evidence_counts: dict[NonEmptyString, int]
    group_scores: dict[NonEmptyString, float]
    reasons: list[NonEmptyString] = Field(min_length=1)


class CandidateDiscoveryReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: NonEmptyString
    project_type: ProjectType
    generated_at: datetime
    bounds: DiscoveryBounds
    evaluated_candidate_count: int = Field(ge=0)
    excluded_by_land_use_count: int = Field(ge=0)
    strategy: CandidateDiscoveryStrategy
    land_evidence_level: DatasetEvidenceLevel = (
        DatasetEvidenceLevel.UNSPECIFIED
    )
    land_source_uri: NonEmptyString | None = None
    land_source_license: NonEmptyString | None = None
    land_source_cache_hit: bool = False
    formal_analysis_allowed: bool
    candidates: list[DiscoveredCandidate]
    sources: list[CandidateDiscoverySource]
    range_pois: list[CandidateDiscoveryRangePOI] = Field(default_factory=list)
    range_poi_observed_count: int = Field(ge=0)
    range_poi_is_truncated: bool = False
    poi_evidence_snapshot_id: NonEmptyString | None = None
    poi_evidence_snapshot_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    poi_evidence_snapshot_record_count: int = Field(default=0, ge=0)
    poi_repair_group_count: int = Field(default=0, ge=0)
    poi_repair_query_count: int = Field(default=0, ge=0)
    poi_repair_success_count: int = Field(default=0, ge=0)
    poi_repair_added_record_count: int = Field(default=0, ge=0)
    incomplete_scoring_groups: list[NonEmptyString] = Field(default_factory=list)
    warnings: list[NonEmptyString] = Field(default_factory=list)
    confirmation_required: bool = True
    total_elapsed_ms: float = Field(ge=0)
    execution_plan: AgentExecutionPlan
    agent_trace: list[AgentStepTrace]

    @model_validator(mode="after")
    def repair_summary_is_consistent(self) -> CandidateDiscoveryReport:
        if self.poi_repair_success_count > self.poi_repair_query_count:
            raise ValueError("POI 修复成功数不能超过查询数")
        if not self.incomplete_scoring_groups:
            self.incomplete_scoring_groups = sorted(
                item.group_key
                for item in self.sources
                if item.purpose is CandidateDiscoveryPOIPurpose.SCORING
                and not item.evidence_complete
            )
        return self


class _PoolCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parcel_id: NonEmptyString
    name: NonEmptyString
    longitude: float
    latitude: float
    area_hectares: float | None = Field(default=None, gt=0)
    geometry_dataset_id: NonEmptyString | None = None
    land_use_class: NonEmptyString
    suitability: LandUseSuitability
    land_use_dataset_id: NonEmptyString | None = None
    land_use_dataset_version: NonEmptyString | None = None
    land_evidence_level: DatasetEvidenceLevel = (
        DatasetEvidenceLevel.UNSPECIFIED
    )
    formal_analysis_allowed: bool


class _LandPoolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[_PoolCandidate] = Field(min_length=1)
    excluded_count: int = Field(ge=0)
    strategy: CandidateDiscoveryStrategy
    evidence_level: DatasetEvidenceLevel
    formal_analysis_allowed: bool
    source_uri: NonEmptyString | None = None
    source_license: NonEmptyString | None = None
    cache_hit: bool = False
    warnings: list[NonEmptyString] = Field(default_factory=list)


class _GroupEvidenceRepair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_key: NonEmptyString
    trigger_reasons: list[NonEmptyString] = Field(default_factory=list)
    query_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    added_record_count: int = Field(default=0, ge=0)
    remaining_reasons: list[NonEmptyString] = Field(default_factory=list)

    @property
    def evidence_complete(self) -> bool:
        return not self.remaining_reasons


class _MarketEvidenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scoring_feature_sets: list[POIFeatureSet]
    context_feature_sets: list[POIFeatureSet]
    range_pois: list[CandidateDiscoveryRangePOI]
    range_poi_observed_count: int = Field(ge=0)
    range_poi_is_truncated: bool = False
    repair_statuses: list[_GroupEvidenceRepair] = Field(default_factory=list)
    warnings: list[NonEmptyString] = Field(default_factory=list)

    @property
    def all_feature_sets(self) -> list[POIFeatureSet]:
        return [*self.scoring_feature_sets, *self.context_feature_sets]


class CandidateDiscoveryGraphState(TypedDict, total=False):
    """One-writer state for the Plan-compiled candidate discovery graph."""

    request: CandidateDiscoveryRequest
    discovery_started_at: float
    land_result: _LandPoolResult
    market_result: _MarketEvidenceResult
    ranked: list[DiscoveredCandidate]
    report: CandidateDiscoveryReport
    intake_trace: AgentStepTrace
    land_trace: AgentStepTrace
    poi_trace: AgentStepTrace
    rank_trace: AgentStepTrace
    review_trace: AgentStepTrace


def build_candidate_discovery_graph(
    runtime_provider,
    *,
    land_use_provider: LandUseProvider | None = None,
    snapshot_store: CandidateDiscoverySnapshotStore | None = None,
    snapshot_id_factory: Callable[[], str] | None = None,
    clock: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] | None = None,
):
    """Compile the reviewed discovery Plan into its LangGraph runtime."""

    if runtime_provider is None:
        raise ValueError("候选发现图必须配置 RuntimeProvider")
    make_snapshot_id = snapshot_id_factory or (
        lambda: f"poi-snapshot-{uuid4()}"
    )
    now = clock or (lambda: datetime.now(timezone.utc))
    timer = monotonic or perf_counter
    plan = build_candidate_discovery_execution_plan()

    def discovery_intake(state: CandidateDiscoveryGraphState):
        _, step_trace = _timed_discovery_step(
            plan,
            "discovery_intake",
            timer,
            lambda: (
                runtime_provider.resolve(state["request"].project_type),
                get_project_profile(state["request"].project_type),
            ),
        )
        return {"intake_trace": step_trace}

    def land_use_gate(state: CandidateDiscoveryGraphState):
        runtime = runtime_provider.resolve(state["request"].project_type)
        result, step_trace = _timed_discovery_step(
            plan,
            "land_use_gate",
            timer,
            lambda: _load_candidate_pool(
                state["request"],
                runtime.datasets,
                runtime.dependencies.spatial_gateway,
                land_use_provider=land_use_provider,
            ),
        )
        return {"land_result": result, "land_trace": step_trace}

    def poi_market_evidence(state: CandidateDiscoveryGraphState):
        runtime = runtime_provider.resolve(state["request"].project_type)
        profile = get_project_profile(state["request"].project_type)
        result, step_trace = _timed_discovery_step(
            plan,
            "poi_market_evidence",
            timer,
            lambda: _load_market_evidence(
                state["request"],
                profile,
                runtime.dependencies.poi_gateway,
            ),
        )
        return {"market_result": result, "poi_trace": step_trace}

    def rank_diversify(state: CandidateDiscoveryGraphState):
        runtime = runtime_provider.resolve(state["request"].project_type)
        profile = get_project_profile(state["request"].project_type)
        ranked, step_trace = _timed_discovery_step(
            plan,
            "rank_diversify",
            timer,
            lambda: _rank_and_diversify(
                state["request"],
                profile,
                runtime.dependencies.poi_scoring_config,
                state["land_result"].candidates,
                state["market_result"].scoring_feature_sets,
            ),
        )
        return {"ranked": ranked, "rank_trace": step_trace}

    def discovery_review(state: CandidateDiscoveryGraphState):
        review_started_at = timer()
        generated_at = now()
        snapshot = None
        if snapshot_store is not None:
            snapshot = build_candidate_discovery_poi_snapshot(
                discovery_request_id=state["request"].request_id,
                project_type=state["request"].project_type,
                created_at=generated_at,
                candidates=[item.candidate for item in state["ranked"]],
                feature_sets=state["market_result"].scoring_feature_sets,
                snapshot_id=make_snapshot_id(),
            )
            snapshot_store.save_candidate_discovery_snapshot(snapshot)

        review_trace = trace_for(
            plan.step("discovery_review"),
            AgentStepStatus.SUCCEEDED,
            max(0.0, timer() - review_started_at) * 1_000,
        )
        report = _assemble_candidate_discovery_report(
            request=state["request"],
            land_result=state["land_result"],
            market_result=state["market_result"],
            ranked=state["ranked"],
            generated_at=generated_at,
            snapshot=snapshot,
            total_elapsed_ms=max(
                0.0,
                timer() - state["discovery_started_at"],
            )
            * 1_000,
            plan=plan,
            traces=[
                state["intake_trace"],
                state["land_trace"],
                state["poi_trace"],
                state["rank_trace"],
                review_trace,
            ],
        )
        return {"report": report, "review_trace": review_trace}

    return compile_agent_plan_graph(
        plan=plan,
        state_schema=CandidateDiscoveryGraphState,
        node_handlers={
            "discovery_intake": discovery_intake,
            "land_use_gate": land_use_gate,
            "poi_market_evidence": poi_market_evidence,
            "rank_diversify": rank_diversify,
            "discovery_review": discovery_review,
        },
    )


class CandidateDiscoveryService:
    """Discover analysis-ready retail candidates from reviewed opportunity cells."""

    def __init__(
        self,
        runtime_provider,
        *,
        land_use_provider: LandUseProvider | None = None,
        snapshot_store: CandidateDiscoverySnapshotStore | None = None,
        snapshot_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if runtime_provider is None:
            raise ValueError("候选发现服务必须配置 RuntimeProvider")
        self._runtime_provider = runtime_provider
        self._land_use_provider = land_use_provider
        self._snapshot_store = snapshot_store
        self._snapshot_id_factory = snapshot_id_factory or (
            lambda: f"poi-snapshot-{uuid4()}"
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or perf_counter

    def discover(self, request: CandidateDiscoveryRequest) -> CandidateDiscoveryReport:
        discovery_started_at = self._monotonic()
        graph = build_candidate_discovery_graph(
            self._runtime_provider,
            land_use_provider=self._land_use_provider,
            snapshot_store=self._snapshot_store,
            snapshot_id_factory=self._snapshot_id_factory,
            clock=self._clock,
            monotonic=self._monotonic,
        )
        output = graph.invoke(
            {
                "request": request,
                "discovery_started_at": discovery_started_at,
            },
            config={"max_concurrency": 2},
        )
        return CandidateDiscoveryReport.model_validate(output["report"])


def _timed_discovery_step(plan, node_id, monotonic, operation):
    started_at = monotonic()
    result = operation()
    return result, trace_for(
        plan.step(node_id),
        AgentStepStatus.SUCCEEDED,
        max(0.0, monotonic() - started_at) * 1_000,
    )


def _assemble_candidate_discovery_report(
    *,
    request,
    land_result,
    market_result,
    ranked,
    generated_at,
    snapshot,
    total_elapsed_ms,
    plan,
    traces,
):
    repair_by_group = {
        item.group_key: item for item in market_result.repair_statuses
    }
    repaired = [
        item for item in market_result.repair_statuses if item.query_count > 0
    ]
    return CandidateDiscoveryReport(
        request_id=request.request_id,
        project_type=request.project_type,
        generated_at=generated_at,
        bounds=request.bounds,
        evaluated_candidate_count=len(land_result.candidates),
        excluded_by_land_use_count=land_result.excluded_count,
        strategy=land_result.strategy,
        land_evidence_level=land_result.evidence_level,
        land_source_uri=land_result.source_uri,
        land_source_license=land_result.source_license,
        land_source_cache_hit=land_result.cache_hit,
        formal_analysis_allowed=land_result.formal_analysis_allowed,
        candidates=ranked,
        sources=[
            _candidate_discovery_source(
                item,
                repair_status=repair_by_group.get(item.query.group_key),
            )
            for item in market_result.scoring_feature_sets
        ]
        + [
            _candidate_discovery_source(
                item,
                purpose=CandidateDiscoveryPOIPurpose.RANGE_CONTEXT,
            )
            for item in market_result.context_feature_sets
        ],
        range_pois=market_result.range_pois,
        range_poi_observed_count=market_result.range_poi_observed_count,
        range_poi_is_truncated=market_result.range_poi_is_truncated,
        poi_evidence_snapshot_id=(
            snapshot.snapshot_id if snapshot is not None else None
        ),
        poi_evidence_snapshot_sha256=(
            snapshot.content_sha256 if snapshot is not None else None
        ),
        poi_evidence_snapshot_record_count=(
            snapshot.unique_record_count if snapshot is not None else 0
        ),
        poi_repair_group_count=len(repaired),
        poi_repair_query_count=sum(item.query_count for item in repaired),
        poi_repair_success_count=sum(item.success_count for item in repaired),
        poi_repair_added_record_count=sum(
            item.added_record_count for item in repaired
        ),
        incomplete_scoring_groups=sorted(
            item.group_key
            for item in market_result.repair_statuses
            if not item.evidence_complete
        ),
        warnings=_discovery_warnings(land_result, market_result),
        total_elapsed_ms=round(total_elapsed_ms, 3),
        execution_plan=plan,
        agent_trace=order_agent_traces(plan, traces),
    )


def _candidate_discovery_source(
    feature_set: POIFeatureSet,
    *,
    purpose: CandidateDiscoveryPOIPurpose = CandidateDiscoveryPOIPurpose.SCORING,
    repair_status: _GroupEvidenceRepair | None = None,
) -> CandidateDiscoverySource:
    if repair_status is None:
        incomplete_reasons = _feature_set_incomplete_reasons(
            feature_set,
            feature_set.query.categories,
        )
        repair_status = _GroupEvidenceRepair(
            group_key=feature_set.query.group_key,
            remaining_reasons=incomplete_reasons,
        )
    return CandidateDiscoverySource(
        group_key=feature_set.query.group_key,
        purpose=purpose,
        provider=feature_set.source.provider,
        dataset_id=feature_set.source.dataset_id,
        record_count=feature_set.source.record_count,
        available_record_count=feature_set.source.available_record_count,
        is_truncated=feature_set.source.is_truncated,
        is_synthetic=feature_set.source.is_synthetic,
        fallback_from=feature_set.source.fallback_from,
        fallback_reason=feature_set.source.fallback_reason,
        cache_hit=feature_set.source.cache_hit,
        evidence_complete=repair_status.evidence_complete,
        incomplete_reasons=repair_status.remaining_reasons,
        repair_attempted=repair_status.query_count > 0,
        repair_query_count=repair_status.query_count,
        repair_success_count=repair_status.success_count,
        repair_added_record_count=repair_status.added_record_count,
    )


def _find_registered_land_manifest(
    datasets: Sequence[DatasetManifest],
) -> DatasetManifest | None:
    matches = [
        item
        for item in datasets
        if LAND_USE_REQUIRED_FIELDS.issubset(item.required_fields)
    ]
    if len(matches) > 1:
        raise CandidateDiscoveryBlockedError(
            "候选发现需要且只能配置一个带用地适配属性的机会单元图层"
        )
    return matches[0].model_copy(deep=True) if matches else None


def _find_proxy_land_manifests(
    datasets: Sequence[DatasetManifest],
) -> list[DatasetManifest]:
    return [
        item.model_copy(deep=True)
        for item in datasets
        if {"parcel_id", "land_use"}.issubset(item.required_fields)
        and not LAND_USE_REQUIRED_FIELDS.issubset(item.required_fields)
    ]


def _load_candidate_pool(
    request,
    datasets,
    gateway,
    *,
    land_use_provider: LandUseProvider | None = None,
) -> _LandPoolResult:
    registered = _find_registered_land_manifest(datasets)
    warnings = []
    if registered is not None:
        try:
            candidates, excluded_count = _load_registered_pool(
                request, registered, gateway
            )
            return _LandPoolResult(
                candidates=candidates,
                excluded_count=excluded_count,
                strategy=CandidateDiscoveryStrategy.REGISTERED_LAND,
                evidence_level=registered.evidence_level,
                formal_analysis_allowed=True,
                source_uri=registered.source_uri,
                source_license=registered.license,
            )
        except CandidateDiscoveryBlockedError as exc:
            if request.fallback_mode is CandidateDiscoveryFallbackMode.STRICT:
                raise
            warnings.append(f"登记用地不可用：{exc}")
    elif request.fallback_mode is CandidateDiscoveryFallbackMode.STRICT:
        raise CandidateDiscoveryBlockedError(
            "候选发现缺少带用地适配属性的机会单元图层"
        )

    if land_use_provider is not None:
        try:
            observed = land_use_provider.search(
                LandUseQuery(
                    project_type=request.project_type,
                    west=request.bounds.west,
                    south=request.bounds.south,
                    east=request.bounds.east,
                    north=request.bounds.north,
                )
            )
            in_scope_features = [
                item
                for item in observed.features
                if request.bounds.contains(item.longitude, item.latitude)
            ]
            if in_scope_features:
                return _LandPoolResult(
                    candidates=[
                        _PoolCandidate(
                            parcel_id=item.source_feature_id,
                            name=item.name,
                            longitude=item.longitude,
                            latitude=item.latitude,
                            area_hectares=item.area_hectares,
                            land_use_class=item.land_use_class,
                            suitability=LandUseSuitability.REVIEW_REQUIRED,
                            land_use_dataset_id=observed.source.dataset_id,
                            land_use_dataset_version=(
                                observed.source.dataset_version
                            ),
                            land_evidence_level=(
                                observed.source.evidence_level
                            ),
                            formal_analysis_allowed=False,
                        )
                        for item in in_scope_features
                    ],
                    excluded_count=0,
                    strategy=(
                        CandidateDiscoveryStrategy.PUBLIC_LAND_OBSERVATION
                    ),
                    evidence_level=observed.source.evidence_level,
                    formal_analysis_allowed=False,
                    source_uri=observed.source.source_uri,
                    source_license=observed.source.license,
                    cache_hit=observed.source.cache_hit,
                    warnings=[
                        "候选来自 OSM 公开用地观察，只能支持商业初筛，"
                        "不能替代法定用地或权属核验"
                    ],
                )
            warnings.append(
                "公开用地查询成功，但范围内没有质心落入边界的商业用地多边形"
            )
        except LandUseAvailabilityError as exc:
            warnings.append(f"公开用地服务暂不可用：{type(exc).__name__}")
        except LandUseProviderError as exc:
            warnings.append(f"公开用地响应不可用：{type(exc).__name__}")

    proxy_manifests = _find_proxy_land_manifests(datasets)
    if proxy_manifests:
        candidates, excluded_count, proxy_warnings = _load_proxy_pool(
            request,
            proxy_manifests,
            gateway,
        )
        warnings.extend(proxy_warnings)
        if candidates:
            return _LandPoolResult(
                candidates=candidates,
                excluded_count=excluded_count,
                strategy=CandidateDiscoveryStrategy.COMMERCIAL_LAND_PROXY,
                evidence_level=DatasetEvidenceLevel.SYNTHETIC,
                formal_analysis_allowed=False,
                warnings=warnings,
            )

    if (
        request.fallback_mode
        is CandidateDiscoveryFallbackMode.MARKET_EXPLORATION
    ):
        warnings.append("缺少可核验用地，仅生成市场机会网格")
        return _LandPoolResult(
            candidates=_build_market_grid(request),
            excluded_count=0,
            strategy=CandidateDiscoveryStrategy.MARKET_EXPLORATION,
            evidence_level=DatasetEvidenceLevel.UNSPECIFIED,
            formal_analysis_allowed=False,
            warnings=warnings,
        )
    raise CandidateDiscoveryBlockedError(
        "给定范围内没有可用于候选发现的商业用地代理单元"
    )


def _load_registered_pool(request, manifest, gateway):
    try:
        frame = gateway.load(manifest)
        validate_spatial_dataset(
            frame,
            required_fields=sorted(LAND_USE_REQUIRED_FIELDS | {"name"}),
            require_projected=True,
            expected_crs=manifest.crs,
        )
    except (
        SpatialDatasetAccessError,
        SpatialDatasetNotFoundError,
        SpatialValidationError,
    ) as exc:
        raise CandidateDiscoveryBlockedError(
            f"候选发现用地数据不可用：{manifest.dataset_id}"
        ) from exc

    centers = gpd.GeoSeries(frame.geometry.centroid, crs=frame.crs).to_crs(
        "EPSG:4326"
    )
    eligible: list[_PoolCandidate] = []
    excluded_count = 0
    in_scope_count = 0
    for (_, row), center in zip(frame.iterrows(), centers, strict=True):
        if not request.bounds.contains(center.x, center.y):
            continue
        in_scope_count += 1
        try:
            suitability = LandUseSuitability(str(row["suitability"]))
        except ValueError as exc:
            raise CandidateDiscoveryBlockedError(
                f"用地适配状态无效：{row['parcel_id']}"
            ) from exc
        if suitability is LandUseSuitability.EXCLUDED:
            excluded_count += 1
            continue
        eligible.append(
            _PoolCandidate(
                parcel_id=str(row["parcel_id"]),
                name=str(row["name"]),
                longitude=float(center.x),
                latitude=float(center.y),
                area_hectares=float(row["area_hectares"]),
                geometry_dataset_id=manifest.dataset_id,
                land_use_class=str(row["land_use_class"]),
                suitability=suitability,
                land_use_dataset_id=manifest.dataset_id,
                land_use_dataset_version=manifest.version,
                land_evidence_level=manifest.evidence_level,
                formal_analysis_allowed=True,
            )
        )
    if in_scope_count == 0:
        raise CandidateDiscoveryBlockedError("给定范围内没有已登记的用地机会单元")
    if not eligible:
        raise CandidateDiscoveryBlockedError("给定范围内的机会单元均被用地门禁排除")
    return eligible, excluded_count


def _load_proxy_pool(request, manifests, gateway):
    candidates = []
    excluded_count = 0
    warnings = []
    seen_ids = set()
    for manifest in manifests:
        try:
            frame = gateway.load(manifest)
            validate_spatial_dataset(
                frame,
                required_fields=["parcel_id", "land_use"],
                require_projected=True,
                expected_crs=manifest.crs,
            )
        except (
            SpatialDatasetAccessError,
            SpatialDatasetNotFoundError,
            SpatialValidationError,
        ) as exc:
            warnings.append(f"商业用地代理图层不可用：{manifest.dataset_id}")
            continue
        centers = gpd.GeoSeries(frame.geometry.centroid, crs=frame.crs).to_crs(
            "EPSG:4326"
        )
        for (_, row), center in zip(frame.iterrows(), centers, strict=True):
            if not request.bounds.contains(center.x, center.y):
                continue
            land_use = str(row["land_use"]).strip()
            if not _is_commercial_land_use(land_use):
                excluded_count += 1
                continue
            parcel_id = str(row["parcel_id"]).strip()
            if not parcel_id or parcel_id in seen_ids:
                continue
            seen_ids.add(parcel_id)
            area_hectares = _proxy_area_hectares(
                row.get("area_hectares"), row.geometry.area
            )
            raw_name = row.get("name")
            name = str(raw_name).strip() if raw_name is not None else ""
            if not name or name.casefold() == "nan":
                name = f"商业用地代理单元 {parcel_id}"
            candidates.append(
                _PoolCandidate(
                    parcel_id=parcel_id,
                    name=name,
                    longitude=float(center.x),
                    latitude=float(center.y),
                    area_hectares=float(area_hectares),
                    geometry_dataset_id=manifest.dataset_id,
                    land_use_class=land_use,
                    suitability=LandUseSuitability.REVIEW_REQUIRED,
                    land_use_dataset_id=manifest.dataset_id,
                    land_use_dataset_version=manifest.version,
                    land_evidence_level=manifest.evidence_level,
                    formal_analysis_allowed=False,
                )
            )
    return candidates, excluded_count, warnings


def _proxy_area_hectares(value, geometry_area: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0
    if not isfinite(parsed) or parsed <= 0:
        parsed = geometry_area / 10_000
    if not isfinite(parsed) or parsed <= 0:
        raise CandidateDiscoveryBlockedError("商业用地代理单元面积无效")
    return parsed


def _is_commercial_land_use(value: str) -> bool:
    normalized = value.casefold().replace("_", "-")
    return any(
        token in normalized
        for token in (
            "commercial",
            "retail",
            "mixed-use",
            "business",
            "商业",
            "商住",
            "商务",
        )
    )


def _build_market_grid(request: CandidateDiscoveryRequest) -> list[_PoolCandidate]:
    side = max(5, ceil(sqrt(request.max_candidates * 4)))
    longitude_step = (request.bounds.east - request.bounds.west) / side
    latitude_step = (request.bounds.north - request.bounds.south) / side
    return [
        _PoolCandidate(
            parcel_id=f"MARKET-{row + 1:02d}-{column + 1:02d}",
            name=f"市场机会网格 {row + 1:02d}-{column + 1:02d}",
            longitude=(
                request.bounds.west + (column + 0.5) * longitude_step
            ),
            latitude=(
                request.bounds.south + (row + 0.5) * latitude_step
            ),
            land_use_class="未知（仅市场探索）",
            suitability=LandUseSuitability.REVIEW_REQUIRED,
            land_evidence_level=DatasetEvidenceLevel.UNSPECIFIED,
            formal_analysis_allowed=False,
        )
        for row in range(side)
        for column in range(side)
    ]


def _load_market_evidence(request, profile, gateway):
    center_lon, center_lat = request.bounds.center
    corner_distance = max(
        haversine_distance_m(center_lon, center_lat, lon, lat)
        for lon, lat in (
            (request.bounds.west, request.bounds.south),
            (request.bounds.west, request.bounds.north),
            (request.bounds.east, request.bounds.south),
            (request.bounds.east, request.bounds.north),
        )
    )
    maximum_scoring_radius = ceil(
        corner_distance + max(group.query_radius_m for group in profile.poi_groups)
    )
    if maximum_scoring_radius > 50_000:
        raise CandidateDiscoveryBlockedError("候选发现 POI 查询半径超过安全上限")
    scoring_categories = sorted(
        {
            category
            for group in profile.poi_groups
            for category in group.categories
        }
    )
    category_budget = getattr(gateway, "max_categories_per_query", None)
    if category_budget is None:
        scoring_feature_sets = _load_bulk_scoring_evidence(
            request,
            profile,
            gateway,
            center_lon=center_lon,
            center_lat=center_lat,
            maximum_scoring_radius=maximum_scoring_radius,
            corner_distance=corner_distance,
            scoring_categories=scoring_categories,
        )
    else:
        scoring_feature_sets = _load_balanced_scoring_evidence(
            request,
            profile,
            gateway,
            category_budget=category_budget,
            center_lon=center_lon,
            center_lat=center_lat,
            corner_distance=corner_distance,
        )
    if not any(item.records for item in scoring_feature_sets):
        diagnostics = "；".join(
            f"{item.query.group_key}={len(item.records)}条"
            + (
                "（"
                + "、".join(item.source.unavailable_categories)
                + "不可用）"
                if item.source.unavailable_categories
                else ""
            )
            for item in scoring_feature_sets
        )
        raise CandidateDiscoveryBlockedError(
            "给定范围内没有可用于候选排序的 POI 市场证据；"
            f"评分组明细：{diagnostics}"
        )
    (
        scoring_feature_sets,
        repair_statuses,
        repair_warnings,
    ) = _repair_incomplete_scoring_evidence(
        request,
        profile,
        gateway,
        scoring_feature_sets,
    )

    context_categories = [
        category
        for category in get_supported_poi_categories()
        if category not in scoring_categories
    ]
    context_feature_sets = []
    warnings = [*repair_warnings]
    context_radius_m = max(100, ceil(corner_distance))
    if context_categories:
        batches = (
            [context_categories]
            if category_budget is None
            else list(_chunks(context_categories, category_budget))
        )
        context_queries = [
            POIQuery(
                query_id=f"{request.request_id}:range-context:{index:02d}",
                parcel_id="candidate-discovery-range",
                group_key=f"range_context_{index:02d}",
                longitude=center_lon,
                latitude=center_lat,
                categories=categories,
                radius_m=context_radius_m,
                limit=request.poi_limit_per_group,
            )
            for index, categories in enumerate(batches, start=1)
        ]
        context_feature_sets, context_warnings = _search_optional_queries(
            gateway,
            context_queries,
        )
        warnings.extend(context_warnings)

    range_pois, observed_count, is_truncated = _build_range_poi_layer(
        request,
        [*scoring_feature_sets, *context_feature_sets],
    )
    return _MarketEvidenceResult(
        scoring_feature_sets=scoring_feature_sets,
        context_feature_sets=context_feature_sets,
        range_pois=range_pois,
        range_poi_observed_count=observed_count,
        range_poi_is_truncated=is_truncated,
        repair_statuses=repair_statuses,
        warnings=warnings,
    )


def _load_bulk_scoring_evidence(
    request,
    profile,
    gateway,
    *,
    center_lon,
    center_lat,
    maximum_scoring_radius,
    corner_distance,
    scoring_categories,
):
    try:
        scoring_bulk = gateway.search(
            POIQuery(
                query_id=f"{request.request_id}:scope:scoring-bulk",
                parcel_id="candidate-discovery-scope",
                group_key="candidate_discovery_scoring_bulk",
                longitude=center_lon,
                latitude=center_lat,
                categories=scoring_categories,
                radius_m=maximum_scoring_radius,
                limit=request.poi_limit_per_group,
            )
        )
    except Exception as exc:
        reason = str(exc).strip() or type(exc).__name__
        raise CandidateDiscoveryBlockedError(
            "POI 市场证据不可用：" + reason
        ) from exc
    return [
        _slice_bulk_feature_set(
            scoring_bulk,
            POIQuery(
                query_id=f"{request.request_id}:scope:{group.group_key}",
                parcel_id="candidate-discovery-scope",
                group_key=group.group_key,
                longitude=center_lon,
                latitude=center_lat,
                categories=group.categories,
                radius_m=ceil(corner_distance + group.query_radius_m),
                limit=request.poi_limit_per_group,
            ),
        )
        for group in profile.poi_groups
    ]


def _load_balanced_scoring_evidence(
    request,
    profile,
    gateway,
    *,
    category_budget,
    center_lon,
    center_lat,
    corner_distance,
):
    oversized = [
        group.group_key
        for group in profile.poi_groups
        if len(group.categories) > category_budget
    ]
    if oversized:
        raise CandidateDiscoveryBlockedError(
            "POI 类别预算小于评分分组需求：" + ", ".join(oversized)
        )
    queries = [
        POIQuery(
            query_id=f"{request.request_id}:scope:{group.group_key}",
            parcel_id="candidate-discovery-scope",
            group_key=group.group_key,
            longitude=center_lon,
            latitude=center_lat,
            categories=group.categories,
            radius_m=ceil(corner_distance + group.query_radius_m),
            limit=request.poi_limit_per_group,
        )
        for group in profile.poi_groups
    ]
    try:
        return _search_queries_retaining_availability_failures(gateway, queries)
    except Exception as exc:
        reason = str(exc).strip() or type(exc).__name__
        raise CandidateDiscoveryBlockedError(
            "POI 市场证据不可用：" + reason
        ) from exc


def _search_queries_retaining_availability_failures(gateway, queries):
    if not queries:
        return []
    first_query = queries[0]
    try:
        first = gateway.search(first_query)
    except POIAvailabilityError as exc:
        first = _unavailable_scoring_feature_set(gateway, first_query, exc)
    remaining = queries[1:]
    fallback_search = getattr(gateway, "search_fallback", None)
    if (
        remaining
        and first.source.fallback_from is not None
        and callable(fallback_search)
    ):
        return [
            first,
            *[
                fallback_search(query, source_template=first.source)
                for query in remaining
            ],
        ]
    if not remaining:
        return [first]

    with ThreadPoolExecutor(max_workers=min(4, len(remaining))) as executor:
        futures = [executor.submit(gateway.search, query) for query in remaining]
        results = [first]
        for query, future in zip(remaining, futures, strict=True):
            try:
                results.append(future.result())
            except POIAvailabilityError as exc:
                results.append(
                    _unavailable_scoring_feature_set(gateway, query, exc)
                )
        return results


def _unavailable_scoring_feature_set(gateway, query, error):
    provider = getattr(gateway, "provider", None)
    if not isinstance(provider, POIProvider):
        raise error
    message = str(error).strip() or type(error).__name__
    source = POISourceMeta(
        provider=provider,
        dataset_id=f"{provider.value}-availability-failure",
        queried_at=datetime.now(timezone.utc),
        record_count=0,
        available_record_count=None,
        is_truncated=True,
        unavailable_categories=list(query.categories),
        availability_warnings=[f"{type(error).__name__}：{message}"],
    )
    return POIFeatureSet(
        query=query.model_copy(deep=True),
        records=[],
        source=source,
        metrics=calculate_poi_metrics(query, []),
    )


def _search_queries(gateway, queries):
    if not queries:
        return []

    # Probe one request first.  When the configured online provider is already
    # known to be unavailable, the fallback adapter can answer the rest of the
    # batch without re-running the same network timeout for every tile/group.
    first = gateway.search(queries[0])
    remaining = queries[1:]
    fallback_search = getattr(gateway, "search_fallback", None)
    if (
        remaining
        and first.source.fallback_from is not None
        and callable(fallback_search)
    ):
        return [
            first,
            *[
                fallback_search(
                    query,
                    source_template=first.source,
                )
                for query in remaining
            ],
        ]
    if not remaining:
        return [first]
    with ThreadPoolExecutor(max_workers=min(4, len(remaining))) as executor:
        futures = [executor.submit(gateway.search, query) for query in remaining]
        return [first, *[future.result() for future in futures]]


def _repair_incomplete_scoring_evidence(
    request: CandidateDiscoveryRequest,
    profile: ProjectProfile,
    gateway,
    broad_feature_sets: list[POIFeatureSet],
) -> tuple[
    list[POIFeatureSet],
    list[_GroupEvidenceRepair],
    list[str],
]:
    broad_by_group = {
        item.query.group_key: item for item in broad_feature_sets
    }
    trigger_reasons_by_group = {}
    repair_queries_by_group = {}
    saturated_groups = []
    for group in profile.poi_groups:
        broad = broad_by_group[group.group_key]
        missing_categories = _missing_categories(broad, group.categories)
        trigger_reasons = _feature_set_incomplete_reasons(
            broad,
            group.categories,
        )
        trigger_reasons_by_group[group.group_key] = trigger_reasons
        query_limit_saturated = bool(
            not broad.source.is_synthetic
            and broad.source.fallback_from is None
            and broad.source.is_truncated
            and broad.source.record_count == broad.query.limit
            and not missing_categories
        )
        if query_limit_saturated:
            saturated_groups.append(group.group_key)
        repairable = bool(
            not broad.source.unavailable_categories
            and (
                broad.source.fallback_from is not None
            or (
                broad.source.is_truncated
                and not query_limit_saturated
            )
            or (
                not broad.source.is_synthetic
                and missing_categories
            )
            )
        )
        if trigger_reasons and repairable:
            repair_queries_by_group[group.group_key] = (
                _build_scoring_repair_queries(request, group)
            )

    # If every scoring query already fell back from an unavailable
    # online provider, retrying four tiles per group only amplifies the
    # outage: with a global provider limiter it can outlive the HTTP request
    # timeout. Keep the explicit Fixture evidence and audit warning, while
    # allowing the discovery response to return promptly. Partial outages
    # still use the normal repair path below.
    if repair_queries_by_group and all(
        item.source.fallback_from is not None
        for item in broad_feature_sets
    ):
        repaired_feature_sets = list(broad_feature_sets)
        statuses = [
            _GroupEvidenceRepair(
                group_key=group.group_key,
                trigger_reasons=trigger_reasons_by_group[group.group_key],
                remaining_reasons=[
                    *trigger_reasons_by_group[group.group_key],
                    "在线 Provider 全部不可用，已跳过分区补查",
                ],
            )
            for group in profile.poi_groups
        ]
        return (
            repaired_feature_sets,
            statuses,
            [
                "在线 POI Provider 全部不可用，已跳过分区补查并保留 Fixture 降级结果"
            ],
        )

    # Interleave tiles across groups so one slow category cannot monopolize
    # the executor. A single executor also prevents six groups from each
    # paying a separate two-worker wait cycle.
    repair_queries = [
        queries[tile_index]
        for tile_index in range(DISCOVERY_REPAIR_GRID_SIDE**2)
        for group in profile.poi_groups
        if (queries := repair_queries_by_group.get(group.group_key)) is not None
    ]
    repair_outcomes_by_group = {
        group_key: [] for group_key in repair_queries_by_group
    }
    for query, outcome in zip(
        repair_queries,
        _search_repair_queries(gateway, repair_queries),
        strict=True,
    ):
        repair_outcomes_by_group[query.group_key].append(outcome)

    repaired_feature_sets = []
    statuses = []
    warnings = [
        f"POI 评分组 {group_key} 已达到查询上限且类别齐全，"
        "保留截断标记并跳过同步分区补查"
        for group_key in saturated_groups
    ]
    for group in profile.poi_groups:
        broad = broad_by_group[group.group_key]
        trigger_reasons = trigger_reasons_by_group[group.group_key]
        queries = repair_queries_by_group.get(group.group_key)
        if queries is None:
            repaired_feature_sets.append(broad)
            statuses.append(
                _GroupEvidenceRepair(
                    group_key=group.group_key,
                    trigger_reasons=trigger_reasons,
                    remaining_reasons=trigger_reasons,
                )
            )
            continue

        outcomes = repair_outcomes_by_group[group.group_key]
        real_results = [
            result
            for result, _ in outcomes
            if result is not None and not result.source.is_synthetic
        ]
        issues = sorted(
            {
                issue
                for _, issue in outcomes
                if issue is not None
            }
        )
        if not real_results:
            remaining_reasons = [
                *trigger_reasons,
                "分区补查未恢复真实在线数据",
            ]
            repaired_feature_sets.append(broad)
            status = _GroupEvidenceRepair(
                group_key=group.group_key,
                trigger_reasons=trigger_reasons,
                query_count=len(queries),
                success_count=0,
                remaining_reasons=_unique_strings(remaining_reasons),
            )
        else:
            coverage_complete = (
                len(real_results) == len(queries)
                and all(not item.source.is_truncated for item in real_results)
            )
            merged, added_record_count = _merge_repaired_scoring_group(
                broad,
                real_results,
                group.categories,
                coverage_complete=coverage_complete,
            )
            remaining_reasons = _feature_set_incomplete_reasons(
                merged,
                group.categories,
            )
            if issues:
                remaining_reasons.append(
                    "部分分区补查失败或仍发生在线降级"
                )
            repaired_feature_sets.append(merged)
            status = _GroupEvidenceRepair(
                group_key=group.group_key,
                trigger_reasons=trigger_reasons,
                query_count=len(queries),
                success_count=len(real_results),
                added_record_count=added_record_count,
                remaining_reasons=_unique_strings(remaining_reasons),
            )
        statuses.append(status)
        warnings.append(
            f"POI 评分组 {group.group_key} 已执行 2×2 分区补查："
            f"{status.success_count}/{status.query_count} 个分区返回真实数据，"
            f"新增 {status.added_record_count} 条去重记录"
        )
        if issues:
            warnings.append(
                f"POI 评分组 {group.group_key} 分区补查异常："
                + "、".join(issues)
            )
        if status.remaining_reasons:
            warnings.append(
                f"POI 评分组 {group.group_key} 补查后仍不完整："
                + "、".join(status.remaining_reasons)
            )
    return repaired_feature_sets, statuses, warnings


def _build_scoring_repair_queries(request, group) -> list[POIQuery]:
    longitude_step = (
        request.bounds.east - request.bounds.west
    ) / DISCOVERY_REPAIR_GRID_SIDE
    latitude_step = (
        request.bounds.north - request.bounds.south
    ) / DISCOVERY_REPAIR_GRID_SIDE
    queries = []
    for row in range(DISCOVERY_REPAIR_GRID_SIDE):
        for column in range(DISCOVERY_REPAIR_GRID_SIDE):
            west = request.bounds.west + column * longitude_step
            east = west + longitude_step
            south = request.bounds.south + row * latitude_step
            north = south + latitude_step
            longitude = (west + east) / 2
            latitude = (south + north) / 2
            tile_corner_distance = max(
                haversine_distance_m(longitude, latitude, lon, lat)
                for lon, lat in (
                    (west, south),
                    (west, north),
                    (east, south),
                    (east, north),
                )
            )
            queries.append(
                POIQuery(
                    query_id=(
                        f"{request.request_id}:repair:{group.group_key}:"
                        f"{row + 1:02d}-{column + 1:02d}"
                    ),
                    parcel_id="candidate-discovery-repair",
                    group_key=group.group_key,
                    longitude=longitude,
                    latitude=latitude,
                    categories=group.categories,
                    radius_m=ceil(tile_corner_distance + group.query_radius_m),
                    limit=request.poi_limit_per_group,
                )
            )
    return queries


def _search_repair_queries(gateway, queries):
    if not queries:
        return []
    outcomes = []
    with ThreadPoolExecutor(
        max_workers=min(DISCOVERY_REPAIR_MAX_WORKERS, len(queries))
    ) as executor:
        futures = [executor.submit(gateway.search, query) for query in queries]
        for future in futures:
            try:
                result = future.result()
            except Exception as exc:
                outcomes.append((None, type(exc).__name__))
                continue
            issue = None
            if result.source.is_synthetic:
                issue = (
                    result.source.fallback_reason
                    or "synthetic_fixture"
                )
            elif result.source.is_truncated:
                issue = "response_truncated"
            outcomes.append((result, issue))
    return outcomes


def _merge_repaired_scoring_group(
    broad: POIFeatureSet,
    repair_results: list[POIFeatureSet],
    expected_categories,
    *,
    coverage_complete: bool,
) -> tuple[POIFeatureSet, int]:
    provider = repair_results[0].source.provider
    contributors = [
        item
        for item in repair_results
        if item.source.provider is provider and not item.source.is_synthetic
    ]
    if broad.source.provider is provider and not broad.source.is_synthetic:
        contributors.insert(0, broad)

    category_set = set(expected_categories)
    records_by_id = {}
    for feature_set in contributors:
        for record in feature_set.records:
            if record.category not in category_set:
                continue
            distance_m = haversine_distance_m(
                broad.query.longitude,
                broad.query.latitude,
                record.longitude,
                record.latitude,
            )
            if distance_m > broad.query.radius_m:
                continue
            existing = records_by_id.get(record.poi_id)
            updated = record.model_copy(update={"distance_m": distance_m})
            if existing is None or distance_m < (existing.distance_m or 0):
                records_by_id[record.poi_id] = updated

    records = sorted(
        records_by_id.values(),
        key=lambda item: (item.distance_m or 0, item.poi_id),
    )
    original_ids = {
        item.poi_id
        for item in broad.records
        if broad.source.provider is provider and not broad.source.is_synthetic
    }
    missing_categories = set(expected_categories) - {
        item.category for item in records
    }
    incomplete = not coverage_complete or bool(missing_categories)
    available_record_count = len(records) + (1 if incomplete else 0)
    source = repair_results[0].source.model_copy(
        deep=True,
        update={
            "record_count": len(records),
            "available_record_count": available_record_count,
            "is_truncated": incomplete,
            "dataset_record_count": None,
            "is_synthetic": False,
            "quality_notice": None,
            "fallback_from": None,
            "fallback_reason": None,
            "unavailable_categories": [],
            "availability_warnings": [],
            "cache_hit": all(item.source.cache_hit for item in contributors),
            "evidence_snapshot_id": None,
            "evidence_reused": False,
            "evidence_supplemented": False,
            "evidence_supplement_reason": None,
            "evidence_supplement_error": None,
        },
    )
    return (
        POIFeatureSet(
            query=broad.query.model_copy(deep=True),
            records=records,
            source=source,
            metrics=calculate_poi_metrics(broad.query, records),
        ),
        len(set(records_by_id) - original_ids),
    )


def _feature_set_incomplete_reasons(feature_set, expected_categories) -> list[str]:
    reasons = []
    if feature_set.source.fallback_from is not None:
        reasons.append("在线查询降级为 Fixture")
    elif feature_set.source.is_synthetic:
        reasons.append("仅有合成 Fixture 证据")
    if feature_set.source.is_truncated:
        reasons.append("返回截断或空间覆盖未完成")
    if feature_set.source.unavailable_categories:
        reasons.append(
            "上游查询失败类别："
            + "、".join(feature_set.source.unavailable_categories)
        )
    missing = _missing_categories(feature_set, expected_categories)
    if missing:
        reasons.append("缺少类别：" + "、".join(missing))
    return _unique_strings(reasons)


def _missing_categories(feature_set, expected_categories) -> list[str]:
    observed = {item.category for item in feature_set.records}
    return sorted(set(expected_categories) - observed)


def _unique_strings(values) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _search_optional_queries(gateway, queries):
    if not queries:
        return [], []
    results = []
    warnings = []

    # The first request doubles as an availability probe.  A known fallback
    # result lets optional context batches finish locally instead of queuing
    # more doomed upstream calls behind the global provider limiter.
    first = queries[0]
    try:
        first_result = gateway.search(first)
    except Exception as exc:
        warnings.append(
            "范围背景 POI 批次加载失败："
            f"{first.group_key} ({type(exc).__name__})"
        )
        first_result = None
    if first_result is not None:
        results.append(first_result)
        remaining = queries[1:]
        fallback_search = getattr(gateway, "search_fallback", None)
        if (
            remaining
            and first_result.source.fallback_from is not None
            and callable(fallback_search)
        ):
            for query in remaining:
                try:
                    results.append(
                        fallback_search(
                            query,
                            source_template=first_result.source,
                        )
                    )
                except Exception as exc:
                    warnings.append(
                        "范围背景 POI 批次加载失败："
                        f"{query.group_key} ({type(exc).__name__})"
                    )
            return results, warnings
    else:
        remaining = queries[1:]

    if not remaining:
        return results, warnings
    with ThreadPoolExecutor(max_workers=min(4, len(remaining))) as executor:
        futures = [executor.submit(gateway.search, query) for query in remaining]
        for query, future in zip(queries[1:], futures, strict=True):
            try:
                results.append(future.result())
            except Exception as exc:
                warnings.append(
                    "范围背景 POI 批次加载失败："
                    f"{query.group_key} ({type(exc).__name__})"
                )
    return results, warnings


def _chunks(values, size):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _slice_bulk_feature_set(
    bulk: POIFeatureSet,
    query: POIQuery,
) -> POIFeatureSet:
    categories = set(query.categories)
    records = [
        record.model_copy(deep=True)
        for record in bulk.records
        if record.category in categories
        and (record.distance_m is None or record.distance_m <= query.radius_m)
    ][: query.limit]
    available_record_count = len(records)
    if bulk.source.is_truncated:
        # The bulk response cannot prove completeness for any derived group.
        available_record_count += 1
    source = bulk.source.model_copy(
        deep=True,
        update={
            "record_count": len(records),
            "available_record_count": available_record_count,
            "is_truncated": bulk.source.is_truncated,
        },
    )
    return POIFeatureSet(
        query=query,
        records=records,
        source=source,
        metrics=calculate_poi_metrics(query, records),
    )


def _build_range_poi_layer(
    request: CandidateDiscoveryRequest,
    feature_sets: list[POIFeatureSet],
) -> tuple[list[CandidateDiscoveryRangePOI], int, bool]:
    records_by_key: dict[tuple[POIProvider, str], dict] = {}
    for feature_set in feature_sets:
        for record in feature_set.records:
            if not request.bounds.contains(record.longitude, record.latitude):
                continue
            key = (feature_set.source.provider, record.poi_id)
            existing = records_by_key.get(key)
            if existing is not None:
                existing["source_group_keys"].add(feature_set.query.group_key)
                continue
            records_by_key[key] = {
                "poi_id": record.poi_id,
                "name": record.name,
                "category": record.category,
                "longitude": record.longitude,
                "latitude": record.latitude,
                "provider": feature_set.source.provider,
                "dataset_id": feature_set.source.dataset_id,
                "is_synthetic": feature_set.source.is_synthetic,
                "source_group_keys": {feature_set.query.group_key},
            }

    observed_count = len(records_by_key)
    ordered = sorted(
        records_by_key.values(),
        key=lambda item: (item["category"], item["name"], item["poi_id"]),
    )
    records = [
        CandidateDiscoveryRangePOI(
            **{
                **item,
                "source_group_keys": sorted(item["source_group_keys"]),
            }
        )
        for item in ordered[: request.range_poi_limit]
    ]
    is_truncated = observed_count > len(records) or any(
        item.source.is_truncated for item in feature_sets
    )
    return records, observed_count, is_truncated


def _rank_and_diversify(
    request: CandidateDiscoveryRequest,
    profile: ProjectProfile,
    scoring_config: POIScoringConfig,
    pool: list[_PoolCandidate],
    broad_feature_sets: list[POIFeatureSet],
) -> list[DiscoveredCandidate]:
    scored = [
        _score_pool_candidate(
            item,
            profile,
            scoring_config,
            broad_feature_sets,
        )
        for item in pool
    ]
    scored.sort(key=lambda item: (-item.market_score, item.candidate.parcel_id))
    selected: list[DiscoveredCandidate] = []
    for candidate in scored:
        if any(
            haversine_distance_m(
                candidate.candidate.longitude,
                candidate.candidate.latitude,
                chosen.candidate.longitude,
                chosen.candidate.latitude,
            )
            < request.minimum_separation_m
            for chosen in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= request.max_candidates:
            break
    if not selected:
        raise CandidateDiscoveryBlockedError("候选间距约束过滤后没有可用位置")
    return [
        item.model_copy(update={"rank": rank})
        for rank, item in enumerate(selected, start=1)
    ]


def _score_pool_candidate(
    pool: _PoolCandidate,
    profile: ProjectProfile,
    scoring_config: POIScoringConfig,
    broad_feature_sets: list[POIFeatureSet],
) -> DiscoveredCandidate:
    local_sets = []
    for group in profile.poi_groups:
        broad = next(
            item for item in broad_feature_sets if item.query.group_key == group.group_key
        )
        query = POIQuery(
            query_id=f"discovery:{pool.parcel_id}:{group.group_key}",
            parcel_id=pool.parcel_id,
            group_key=group.group_key,
            longitude=pool.longitude,
            latitude=pool.latitude,
            categories=group.categories,
            radius_m=group.query_radius_m,
            limit=1_000,
        )
        records = []
        for record in broad.records:
            distance_m = haversine_distance_m(
                pool.longitude,
                pool.latitude,
                record.longitude,
                record.latitude,
            )
            if distance_m <= group.query_radius_m:
                records.append(
                    record.model_copy(update={"distance_m": distance_m})
                )
        records.sort(key=lambda item: (item.distance_m or 0, item.poi_id))
        category_query_failed = bool(broad.source.unavailable_categories)
        source = broad.source.model_copy(
            update={
                "record_count": len(records),
                "available_record_count": len(records),
                "is_truncated": category_query_failed,
            }
        )
        local_sets.append(
            POIFeatureSet(
                query=query,
                records=records,
                source=source,
                metrics=calculate_poi_metrics(query, records),
            )
        )
    score_report = score_poi_feature_sets(profile, scoring_config, local_sets)
    display_names = {item.group_key: item.display_name for item in profile.poi_groups}
    strongest = sorted(
        score_report.group_scores,
        key=lambda item: (-item.weighted_score, item.group_key),
    )[:2]
    reasons = [
        f"{display_names[item.group_key]}：{item.group_score:.1f} 分"
        for item in strongest
    ]
    reasons.append(f"用地观察：{pool.land_use_class}")
    return DiscoveredCandidate(
        rank=1,
        candidate=CandidateParcel(
            parcel_id=pool.parcel_id,
            name=pool.name,
            longitude=pool.longitude,
            latitude=pool.latitude,
            area_hectares=pool.area_hectares,
            geometry_dataset_id=pool.geometry_dataset_id,
        ),
        market_score=score_report.total_score,
        land_use_class=pool.land_use_class,
        land_use_suitability=pool.suitability,
        land_use_dataset_id=pool.land_use_dataset_id,
        land_use_dataset_version=pool.land_use_dataset_version,
        land_evidence_level=pool.land_evidence_level,
        formal_analysis_allowed=pool.formal_analysis_allowed,
        requires_human_review=(
            pool.suitability is LandUseSuitability.REVIEW_REQUIRED
            or any(
                item.source.unavailable_categories
                for item in broad_feature_sets
            )
        ),
        evidence_counts={
            item.query.group_key: len(item.records) for item in local_sets
        },
        group_scores={
            item.group_key: item.group_score for item in score_report.group_scores
        },
        reasons=reasons,
    )


def _discovery_warnings(land_result, market_result):
    warnings = [*land_result.warnings, *market_result.warnings]
    feature_sets = market_result.all_feature_sets
    versions = {
        item.land_use_dataset_version
        for item in land_result.candidates
        if item.land_use_dataset_version is not None
    }
    if any(version.startswith("fixture-") for version in versions):
        warnings.append("用地机会单元为合成 Fixture，不代表真实规划许可")
    if land_result.strategy is CandidateDiscoveryStrategy.COMMERCIAL_LAND_PROXY:
        warnings.append("候选仅基于现有商业用地代理生成，必须补充权威用地核验")
    if (
        land_result.strategy
        is CandidateDiscoveryStrategy.PUBLIC_LAND_OBSERVATION
    ):
        warnings.append("OSM 公开用地并非法定规划或权属数据，完整合规分析仍被阻断")
    if land_result.strategy is CandidateDiscoveryStrategy.MARKET_EXPLORATION:
        warnings.append("当前结果仅为市场机会热区，不能作为正式候选地块")
    if any(item.source.is_synthetic for item in feature_sets):
        warnings.append("POI 来源包含合成 Fixture，不代表真实客流或城市覆盖率")
    truncated = [
        item.query.group_key for item in feature_sets if item.source.is_truncated
    ]
    if truncated:
        warnings.append("POI 查询存在截断：" + ", ".join(sorted(truncated)))
    fallback_reasons = sorted(
        {
            _fallback_reason_label(item.source.fallback_reason)
            for item in feature_sets
            if item.source.fallback_from is not None
            and item.source.fallback_reason is not None
        }
    )
    if fallback_reasons:
        warnings.append(
            "在线 POI 不可用，部分证据已显式降级到 Fixture（"
            + "、".join(fallback_reasons)
            + "）"
        )
    empty_groups = [
        item.query.group_key
        for item in market_result.scoring_feature_sets
        if not item.records
    ]
    if empty_groups:
        warnings.append(
            "以下 POI 证据组在范围内无记录："
            + ", ".join(sorted(empty_groups))
        )
    incomplete_groups = sorted(
        item.group_key
        for item in market_result.repair_statuses
        if not item.evidence_complete
    )
    if incomplete_groups:
        warnings.append(
            "候选排序仍包含不完整 POI 评分组："
            + ", ".join(incomplete_groups)
        )
    if market_result.range_poi_is_truncated:
        warnings.append("范围 POI 图层存在返回上限，界面未展示全部可用记录")
    review_count = sum(
        item.suitability is LandUseSuitability.REVIEW_REQUIRED
        for item in land_result.candidates
    )
    if review_count:
        warnings.append(f"{review_count} 个机会单元的用地状态需要人工核验")
    return warnings


def _fallback_reason_label(reason: str) -> str:
    return {
        "POIUpstreamError": "网络或上游服务不可用",
        "POIRateLimitError": "上游限流",
        "POICircuitOpenError": "熔断保护中",
    }.get(reason, reason)
