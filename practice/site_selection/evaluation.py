from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

import geopandas as gpd
from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import Point, Polygon

from .domain import (
    CandidateParcel,
    DatasetManifest,
    DatasetSource,
    ProjectRequest,
    ProjectType,
)
from .constraints import (
    ConstraintLayerSpec,
    ConstraintLayerType,
    SpatialConstraintRelation,
)
from .online_poi_adapters import (
    AmapPOIAdapter,
    FallbackPOIAdapter,
    POICircuitOpenError,
    POIResponseError,
    RetryingCircuitBreakerPOIAdapter,
)
from .poi import POIMetric, POIQuery, POIRecord
from .poi_adapters import FixturePOIAdapter
from .poi_scoring import (
    MissingMetricPolicy,
    POIGroupScoringConfig,
    POIMetricScoringRule,
    POIScoringConfig,
    ScoreDirection,
)
from .poi_service import MockPOIGateway
from .policy_rag import (
    PolicyHybridRetriever,
    chunk_policy_documents,
    load_policy_corpus,
)
from .preflight import SiteSelectionDraft, evaluate_site_selection_draft
from .profiles import get_project_profile
from .rules import PolicyReference, RuleDefinition, RuleOutcome
from .spatial import (
    MockSpatialDatasetGateway,
    SpatialValidationError,
    validate_spatial_dataset,
)
from .parallel_workflow import run_parallel_site_selection_workflow
from .workflow import SiteSelectionWorkflowDependencies


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)


class EvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    frozen_at: datetime
    fixture_versions: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    cases: list[EvaluationCase] = Field(min_length=18, max_length=24)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> EvaluationSuite:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation case IDs must be unique")
        return self


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: str
    scenario: str
    passed: bool
    elapsed_ms: float = Field(ge=0)
    expected: dict[str, Any]
    actual: dict[str, Any]
    error_type: str | None = None


class EvaluationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: str
    version: str
    generated_at: datetime
    environment: dict[str, str]
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    results: list[EvaluationResult]


CaseHandler = Callable[[EvaluationCase], dict[str, Any]]


class FrozenEvaluationRunner:
    """Run frozen deterministic evaluations without calling live providers."""

    def __init__(self, fixture_root: str | Path) -> None:
        self._fixture_root = Path(fixture_root)
        self._handlers: dict[str, CaseHandler] = {
            "preflight": self._run_preflight,
            "spatial": self._run_spatial,
            "poi": self._run_poi,
            "poi_failure": self._run_poi_failure,
            "rag": self._run_rag,
            "runtime": self._run_runtime,
        }

    def run_case(self, case: EvaluationCase) -> EvaluationResult:
        started_at = perf_counter()
        actual: dict[str, Any] = {}
        error_type = None
        try:
            handler = self._handlers[case.category]
            actual = handler(case)
            passed = _contains(case.expected, actual)
        except Exception as exc:
            error_type = type(exc).__name__
            actual = {"exception": error_type}
            passed = _contains(case.expected, actual)
        return EvaluationResult(
            case_id=case.case_id,
            category=case.category,
            scenario=case.scenario,
            passed=passed,
            elapsed_ms=round((perf_counter() - started_at) * 1_000, 3),
            expected=case.expected,
            actual=actual,
            error_type=error_type,
        )

    def run_suite(self, suite: EvaluationSuite) -> EvaluationSummary:
        results = [self.run_case(case) for case in suite.cases]
        passed = sum(result.passed for result in results)
        return EvaluationSummary(
            suite_id=suite.suite_id,
            version=suite.version,
            generated_at=datetime.now(timezone.utc),
            environment={
                "runtime": "local deterministic fixtures",
                "network": "disabled by evaluation design",
                "benchmark_scope": "functional regression, not production benchmark",
            },
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            results=results,
        )

    def _run_preflight(self, case: EvaluationCase) -> dict[str, Any]:
        payload = dict(case.input)
        payload["candidate_parcels"] = [
            CandidateParcel.model_validate(item)
            for item in payload.get("candidate_parcels", [])
        ]
        payload["datasets"] = [
            DatasetManifest.model_validate(item)
            for item in payload.get("datasets", [])
        ]
        decision = evaluate_site_selection_draft(
            SiteSelectionDraft.model_validate(payload)
        )
        return decision.model_dump(mode="json")

    def _run_spatial(self, case: EvaluationCase) -> dict[str, Any]:
        scenario = case.scenario
        crs = None if scenario == "missing_crs" else case.input.get("crs", "EPSG:32651")
        fields = {"parcel_id": ["EVAL-A01"], "land_use": ["fixture"]}
        if scenario == "missing_field":
            fields.pop("land_use")
        geometry = Polygon(
            [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
        )
        if scenario == "empty_geometry":
            geometry = Polygon()
        elif scenario == "invalid_geometry":
            geometry = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
        frame = gpd.GeoDataFrame(fields, geometry=[geometry], crs=crs)
        try:
            result = validate_spatial_dataset(
                frame,
                required_fields=["parcel_id", "land_use"],
            )
        except SpatialValidationError as exc:
            return {"status": "blocked", "code": exc.code.value}
        return {
            "status": "ready",
            "crs": result.crs,
            "feature_count": result.feature_count,
        }

    def _run_poi(self, case: EvaluationCase) -> dict[str, Any]:
        adapter = FixturePOIAdapter.from_json(self._fixture_root / "poi.json")
        result = adapter.search(_poi_query(case.input))
        return {
            "provider": result.source.provider.value,
            "record_count": len(result.records),
            "categories": sorted({record.category for record in result.records}),
            "poi_ids": [record.poi_id for record in result.records],
        }

    def _run_poi_failure(self, case: EvaluationCase) -> dict[str, Any]:
        fixture = FixturePOIAdapter.from_json(self._fixture_root / "poi.json")
        query = _poi_query(case.input)
        if case.scenario == "retry_429_then_success":
            client = _FakeHTTPClient(
                [
                    _FakeResponse(429, {}),
                    _FakeResponse(200, _amap_payload()),
                ]
            )
            adapter = RetryingCircuitBreakerPOIAdapter(
                AmapPOIAdapter("fixture-key", client, _IdentityTransformer()),
                max_attempts=2,
                base_backoff_seconds=0,
            )
            result = adapter.search(query)
            return {
                "provider": result.source.provider.value,
                "http_calls": client.calls,
                "circuit_open": adapter.circuit_open,
            }
        if case.scenario == "open_circuit_fixture_fallback":
            client = _FakeHTTPClient([_FakeResponse(429, {})])
            reliable = RetryingCircuitBreakerPOIAdapter(
                AmapPOIAdapter("fixture-key", client, _IdentityTransformer()),
                max_attempts=1,
                failure_threshold=1,
                recovery_timeout_seconds=60,
            )
            adapter = FallbackPOIAdapter(reliable, fixture)
            first = adapter.search(query)
            second = adapter.search(query)
            return {
                "providers": [first.source.provider.value, second.source.provider.value],
                "fallback_reasons": [
                    first.source.fallback_reason,
                    second.source.fallback_reason,
                ],
                "http_calls": client.calls,
                "circuit_open": reliable.circuit_open,
            }
        if case.scenario == "malformed_response_not_retried":
            client = _FakeHTTPClient(
                [
                    _FakeResponse(200, {"status": "1"}),
                    _FakeResponse(200, _amap_payload()),
                ]
            )
            reliable = RetryingCircuitBreakerPOIAdapter(
                AmapPOIAdapter("fixture-key", client, _IdentityTransformer()),
                max_attempts=2,
                failure_threshold=1,
            )
            try:
                reliable.search(query)
            except POIResponseError as exc:
                return {
                    "error": type(exc).__name__,
                    "http_calls": client.calls,
                    "circuit_open": reliable.circuit_open,
                }
        if case.scenario == "circuit_blocks_extra_http":
            client = _FakeHTTPClient([_FakeResponse(429, {})])
            reliable = RetryingCircuitBreakerPOIAdapter(
                AmapPOIAdapter("fixture-key", client, _IdentityTransformer()),
                max_attempts=1,
                failure_threshold=1,
                recovery_timeout_seconds=60,
            )
            try:
                reliable.search(query)
            except Exception:
                pass
            try:
                reliable.search(query)
            except POICircuitOpenError as exc:
                return {
                    "error": type(exc).__name__,
                    "http_calls": client.calls,
                    "circuit_open": reliable.circuit_open,
                }
        raise ValueError(f"unsupported POI failure scenario: {case.scenario}")

    def _run_rag(self, case: EvaluationCase) -> dict[str, Any]:
        corpus = load_policy_corpus(self._fixture_root / "policies.json")
        retriever = PolicyHybridRetriever(
            chunk_policy_documents(corpus.documents),
            _KeywordEmbeddingProvider(),
        )
        results = retriever.search(
            str(case.input["query"]),
            project_type=ProjectType(case.input["project_type"]),
            jurisdiction=case.input.get("jurisdiction"),
            top_k=int(case.input.get("top_k", 3)),
        )
        return {
            "result_count": len(results),
            "policy_ids": [item.citation.policy_id for item in results],
            "source_uris": [item.citation.source_uri for item in results],
        }

    def _run_runtime(self, case: EvaluationCase) -> dict[str, Any]:
        project_type = ProjectType(case.input["project_type"])
        parcel_id = "MALL-EVAL-01" if project_type is ProjectType.SHOPPING_MALL else "LOG-EVAL-01"
        candidate_dataset_id = f"{project_type.value}-candidate-eval"
        constraint_dataset_id = f"{project_type.value}-constraint-eval"
        constraint_point = (
            Point(10_000, 10_000)
            if case.scenario == "no_rule_match"
            else Point(50, 50)
        )
        datasets: dict[str, gpd.GeoDataFrame] = {
            candidate_dataset_id: _candidate_frame(parcel_id),
            constraint_dataset_id: _constraint_frame(constraint_point),
        }
        if case.scenario == "missing_spatial_dataset":
            datasets.pop(candidate_dataset_id)
        manifests = [
            _manifest(candidate_dataset_id, ["parcel_id", "land_use"]),
            _manifest(constraint_dataset_id, ["constraint_id", "level"]),
        ]
        request = ProjectRequest(
            request_id=f"evaluation-{case.case_id.lower()}",
            project_type=project_type,
            candidate_parcels=[
                CandidateParcel(
                    parcel_id=parcel_id,
                    longitude=121.47,
                    latitude=31.23,
                    geometry_dataset_id=candidate_dataset_id,
                )
            ],
            requested_at=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc),
        )
        result = run_parallel_site_selection_workflow(
            request,
            manifests,
            _workflow_dependencies(
                project_type,
                parcel_id=parcel_id,
                candidate_dataset_id=candidate_dataset_id,
                constraint_dataset_id=constraint_dataset_id,
                datasets=datasets,
            ),
        )
        review = result.evidence_review_report
        return {
            "status": result.status.value,
            "result_count": len(result.results),
            "requires_human_review": (
                review.requires_human_review if review is not None else None
            ),
            "rule_finding_count": sum(
                len(item.policy_evidence.rule_findings) for item in result.results
            ),
            "error_count": len(result.errors),
        }


def load_evaluation_suite(path: str | Path) -> EvaluationSuite:
    return EvaluationSuite.model_validate_json(Path(path).read_text(encoding="utf-8"))


def write_evaluation_summary(summary: EvaluationSummary, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        summary.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _contains(expected: Any, actual: Any) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(
            key in actual and _contains(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and expected == actual
    return expected == actual


def _poi_query(payload: Mapping[str, Any]) -> POIQuery:
    return POIQuery(
        query_id="frozen-evaluation",
        parcel_id="EVAL-A01",
        group_key="evaluation",
        longitude=float(payload.get("longitude", 121.47)),
        latitude=float(payload.get("latitude", 31.23)),
        categories=list(payload.get("categories", ["地铁站"])),
        radius_m=int(payload.get("radius_m", 2_000)),
        limit=int(payload.get("limit", 20)),
    )


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeHTTPClient:
    def __init__(self, responses: Sequence[_FakeResponse]) -> None:
        self._responses = deque(responses)
        self.calls = 0

    def get(self, url: str, *, params: Mapping[str, Any], timeout: float) -> _FakeResponse:
        self.calls += 1
        return self._responses.popleft()


class _IdentityTransformer:
    def wgs84_to_gcj02(self, longitude: float, latitude: float) -> tuple[float, float]:
        return longitude, latitude

    def gcj02_to_wgs84(self, longitude: float, latitude: float) -> tuple[float, float]:
        return longitude, latitude


class _KeywordEmbeddingProvider:
    _terms = ("生态", "轨道", "物流", "高速", "货运")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [1.0, *(float(text.count(term)) for term in self._terms)]
            for text in texts
        ]


def _amap_payload() -> dict[str, Any]:
    return {
        "status": "1",
        "infocode": "10000",
        "pois": [
            {
                "id": "EVAL-AMAP-01",
                "name": "评测用测试地铁站",
                "location": "121.471000,31.230000",
                "type": "交通设施服务;地铁站",
                "typecode": "150500",
                "address": "合成测试地址",
            }
        ],
    }


def _candidate_frame(parcel_id: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"parcel_id": [parcel_id], "land_use": ["fixture"]},
        geometry=[Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])],
        crs="EPSG:32651",
    )


def _constraint_frame(point: Point) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"constraint_id": ["EVAL-C01"], "level": ["fixture-review"]},
        geometry=[point],
        crs="EPSG:32651",
    )


def _manifest(dataset_id: str, required_fields: list[str]) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        name=dataset_id,
        source=DatasetSource.POSTGIS,
        location=dataset_id,
        version="evaluation-fixture-v1",
        crs="EPSG:32651",
        required_fields=required_fields,
        updated_at=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc),
    )


def _workflow_dependencies(
    project_type: ProjectType,
    *,
    parcel_id: str,
    candidate_dataset_id: str,
    constraint_dataset_id: str,
    datasets: Mapping[str, gpd.GeoDataFrame],
) -> SiteSelectionWorkflowDependencies:
    profile = get_project_profile(project_type)
    scoring_groups = []
    for group in profile.poi_groups:
        scoring_groups.append(
            POIGroupScoringConfig(
                group_key=group.group_key,
                metric_rules=[
                    POIMetricScoringRule(
                        metric=metric,
                        direction=(
                            ScoreDirection.LOWER_IS_BETTER
                            if metric in {
                                POIMetric.NEAREST_DISTANCE_M,
                                POIMetric.AVERAGE_DISTANCE_M,
                            }
                            else ScoreDirection.HIGHER_IS_BETTER
                        ),
                        lower_bound=0,
                        upper_bound=100,
                        weight=1 / len(group.metrics),
                        missing_policy=MissingMetricPolicy.ZERO,
                    )
                    for metric in group.metrics
                ],
            )
        )
    policy = PolicyReference(
        policy_id=f"EVAL-{project_type.value}-POLICY",
        title="合成评测规则",
        issuing_authority="测试机构",
        clause="第一条（合成测试）",
        version="1.0",
        jurisdiction="测试行政区",
        source_uri="fixture://evaluation/policy",
    )
    constraint_id = f"{project_type.value}-constraint"
    return SiteSelectionWorkflowDependencies(
        poi_gateway=MockPOIGateway(
            {
                parcel_id: [
                    POIRecord(
                        poi_id="EVAL-POI-01",
                        name="合成评测 POI",
                        category=profile.poi_groups[0].categories[0],
                        longitude=121.471,
                        latitude=31.231,
                        distance_m=150,
                    )
                ]
            },
            clock=lambda: datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc),
        ),
        poi_scoring_config=POIScoringConfig(
            project_type=project_type,
            version="evaluation-v1",
            groups=scoring_groups,
        ),
        spatial_gateway=MockSpatialDatasetGateway(datasets),
        constraint_specs=[
            ConstraintLayerSpec(
                constraint_id=constraint_id,
                display_name="合成评测约束",
                layer_type=(
                    ConstraintLayerType.ECOLOGICAL_PROTECTION
                    if project_type is ProjectType.SHOPPING_MALL
                    else ConstraintLayerType.SENSITIVE_RECEPTOR
                ),
                dataset_id=constraint_dataset_id,
                relation=SpatialConstraintRelation.INTERSECTS,
                applicable_project_types=[project_type],
                required_fields=["constraint_id", "level"],
            )
        ],
        rules=[
            RuleDefinition(
                rule_id=f"EVAL-{project_type.value}-RULE",
                name="合成评测规则",
                version="1.0",
                applicable_project_types=[project_type],
                constraint_id=constraint_id,
                outcome=RuleOutcome.REVIEW_REQUIRED,
                message="命中合成空间条件，需要人工复核",
                policy=policy,
                valid_from=date(2026, 1, 1),
            )
        ],
        buffer_distance_m=200,
    )
