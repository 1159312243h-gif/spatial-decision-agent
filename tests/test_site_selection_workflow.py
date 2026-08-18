from datetime import date, datetime, timezone

import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon

from practice.site_selection import (
    AgentState,
    AnalysisStatus,
    CandidateParcel,
    ConstraintLayerSpec,
    ConstraintLayerType,
    DatasetManifest,
    DatasetSource,
    EvidenceStatus,
    MissingMetricPolicy,
    MockPOIGateway,
    POIGroupScoringConfig,
    POIMetric,
    POIMetricScoringRule,
    POIRecord,
    POIScoringConfig,
    PolicyReference,
    ProjectRequest,
    ProjectType,
    ResultAssemblyBlockedError,
    RuleDefinition,
    RuleOutcome,
    ScoreDirection,
    SiteSelectionWorkflowDependencies,
    SpatialConstraintRelation,
    assemble_analysis_results,
    get_project_profile,
    run_site_selection_workflow,
)
from practice.site_selection.spatial import MockSpatialDatasetGateway


NOW = datetime(2026, 8, 18, 23, 55, tzinfo=timezone.utc)
PARCEL_DATASET_ID = "parcel-workflow-2026-08"
CONSTRAINT_DATASET_ID = "ecology-workflow-2026-08"
CONSTRAINT_ID = "ecology-observation"


def target_frame(*, crs: str | None = "EPSG:32651") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"parcel_id": ["A01"], "land_use": ["commercial"]},
        geometry=[
            Polygon(
                [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
            )
        ],
        crs=crs,
    )


def constraint_frame(
    point: Point = Point(50, 50),
) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"constraint_id": ["E1"], "level": ["demo"]},
        geometry=[point],
        crs="EPSG:32651",
    )


def manifest(
    dataset_id: str,
    required_fields: list[str],
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        name=dataset_id,
        source=DatasetSource.POSTGIS,
        location=dataset_id,
        version="2026.08",
        crs="EPSG:32651",
        required_fields=required_fields,
        updated_at=NOW,
    )


def manifests() -> list[DatasetManifest]:
    return [
        manifest(PARCEL_DATASET_ID, ["parcel_id", "land_use"]),
        manifest(CONSTRAINT_DATASET_ID, ["constraint_id", "level"]),
    ]


def request() -> ProjectRequest:
    return ProjectRequest(
        request_id="REQ-workflow",
        project_type=ProjectType.SHOPPING_MALL,
        candidate_parcels=[
            CandidateParcel(
                parcel_id="A01",
                longitude=121.47,
                latitude=31.23,
                geometry_dataset_id=PARCEL_DATASET_ID,
            )
        ],
        requested_at=NOW,
    )


def constraint_spec() -> ConstraintLayerSpec:
    return ConstraintLayerSpec(
        constraint_id=CONSTRAINT_ID,
        display_name="生态保护空间观察",
        layer_type=ConstraintLayerType.ECOLOGICAL_PROTECTION,
        dataset_id=CONSTRAINT_DATASET_ID,
        relation=SpatialConstraintRelation.INTERSECTS,
        applicable_project_types=[ProjectType.SHOPPING_MALL],
        required_fields=["constraint_id", "level"],
    )


def policy() -> PolicyReference:
    return PolicyReference(
        policy_id="POLICY-WORKFLOW-DEMO",
        title="工作流测试规则",
        issuing_authority="测试机构",
        clause="第一条",
        version="2026.1",
        jurisdiction="测试行政区",
        source_uri="policy://demo/workflow",
    )


def rule(*, constraint_id: str = CONSTRAINT_ID) -> RuleDefinition:
    return RuleDefinition(
        rule_id="RULE-WORKFLOW-DEMO",
        name="工作流测试规则",
        version="1.0",
        applicable_project_types=[ProjectType.SHOPPING_MALL],
        constraint_id=constraint_id,
        outcome=RuleOutcome.REVIEW_REQUIRED,
        message="命中测试空间条件，需要人工复核",
        policy=policy(),
        valid_from=date(2026, 1, 1),
    )


def poi_gateway() -> MockPOIGateway:
    return MockPOIGateway(
        {
            "A01": [
                POIRecord(
                    poi_id="P1",
                    name="测试地铁站",
                    category="地铁站",
                    longitude=121.471,
                    latitude=31.231,
                    distance_m=300,
                )
            ]
        },
        clock=lambda: NOW,
    )


def scoring_config(
    *,
    missing_policy: MissingMetricPolicy = MissingMetricPolicy.ZERO,
) -> POIScoringConfig:
    groups = []
    profile = get_project_profile(ProjectType.SHOPPING_MALL)
    for group in profile.poi_groups:
        metric_weight = 1 / len(group.metrics)
        groups.append(
            POIGroupScoringConfig(
                group_key=group.group_key,
                metric_rules=[
                    POIMetricScoringRule(
                        metric=metric,
                        direction=(
                            ScoreDirection.LOWER_IS_BETTER
                            if metric
                            in {
                                POIMetric.NEAREST_DISTANCE_M,
                                POIMetric.AVERAGE_DISTANCE_M,
                            }
                            else ScoreDirection.HIGHER_IS_BETTER
                        ),
                        lower_bound=0,
                        upper_bound=100,
                        weight=metric_weight,
                        missing_policy=missing_policy,
                    )
                    for metric in group.metrics
                ],
            )
        )
    return POIScoringConfig(
        project_type=ProjectType.SHOPPING_MALL,
        version="demo-1.0",
        groups=groups,
    )
def dependencies(
    *,
    target: gpd.GeoDataFrame | None = None,
    constraint: gpd.GeoDataFrame | None = None,
    active_rule: RuleDefinition | None = None,
    active_poi_gateway=None,
    active_scoring_config: POIScoringConfig | None = None,
) -> SiteSelectionWorkflowDependencies:
    return SiteSelectionWorkflowDependencies(
        poi_gateway=active_poi_gateway or poi_gateway(),
        poi_scoring_config=active_scoring_config or scoring_config(),
        spatial_gateway=MockSpatialDatasetGateway(
            {
                PARCEL_DATASET_ID: (
                    target if target is not None else target_frame()
                ),
                CONSTRAINT_DATASET_ID: (
                    constraint
                    if constraint is not None
                    else constraint_frame()
                ),
            }
        ),
        constraint_specs=[constraint_spec()],
        rules=[active_rule or rule()],
        buffer_distance_m=200,
    )


def test_happy_path_builds_auditable_parcel_result() -> None:
    initial_request = request()

    result = run_site_selection_workflow(
        initial_request,
        manifests(),
        dependencies(),
    )

    assert result.status is AnalysisStatus.COMPLETED
    assert result.errors == []
    assert len(result.results) == 1
    parcel_result = result.results[0]
    assert parcel_result.gis_evidence.metrics["area_hectares"] == pytest.approx(1)
    assert len(parcel_result.gis_evidence.constraint_observations) == 1
    assert len(parcel_result.policy_evidence.rule_findings) == 1
    assert parcel_result.policy_evidence.rule_findings[0].rule_version == "1.0"
    assert parcel_result.poi_evidence.status is EvidenceStatus.READY
    assert parcel_result.overall_soft_score is not None
    assert parcel_result.poi_evidence.score_report is not None
    assert parcel_result.poi_evidence.score_report.scoring_version == "demo-1.0"
    assert parcel_result.overall_soft_score == pytest.approx(
        parcel_result.poi_evidence.score_report.total_score
    )
    assert parcel_result.conclusion is None
    assert not any("未生成软评分" in item for item in parcel_result.warnings)
    assert initial_request.request_id == "REQ-workflow"


def test_unmatched_rule_does_not_become_compliance_conclusion() -> None:
    result = run_site_selection_workflow(
        request(),
        manifests(),
        dependencies(constraint=constraint_frame(Point(150, 50))),
    )

    parcel_result = result.results[0]
    assert result.status is AnalysisStatus.COMPLETED
    assert parcel_result.policy_evidence.rule_findings == []
    assert parcel_result.conclusion is None
    assert any("不等于整体合规" in item for item in parcel_result.warnings)


def test_invalid_gis_routes_to_failed_state() -> None:
    result = run_site_selection_workflow(
        request(),
        manifests(),
        dependencies(target=target_frame(crs=None)),
    )

    assert result.status is AnalysisStatus.FAILED
    assert result.results == []
    assert "gis_collection" in result.errors[0]
    assert "missing_crs" in result.errors[0]
    assert result.policy_evidence == []


def test_missing_poi_metric_routes_to_failed_state_before_gis() -> None:
    result = run_site_selection_workflow(
        request(),
        manifests(),
        dependencies(
            active_scoring_config=scoring_config(
                missing_policy=MissingMetricPolicy.BLOCK,
            )
        ),
    )

    assert result.status is AnalysisStatus.FAILED
    assert result.results == []
    assert "poi_scoring" in result.errors[0]
    assert "缺少指标" in result.errors[0]
    assert result.gis_evidence == []
    assert result.policy_evidence == []


def test_missing_rule_observation_routes_to_failed_state() -> None:
    result = run_site_selection_workflow(
        request(),
        manifests(),
        dependencies(active_rule=rule(constraint_id="missing-observation")),
    )

    assert result.status is AnalysisStatus.FAILED
    assert result.results == []
    assert "policy_rules" in result.errors[0]
    assert "缺少规则所需空间观察" in result.errors[0]


def test_unknown_gateway_error_is_sanitized() -> None:
    class ExplodingPOIGateway:
        def search(self, query):
            raise RuntimeError("secret-token=do-not-copy")

    result = run_site_selection_workflow(
        request(),
        manifests(),
        dependencies(active_poi_gateway=ExplodingPOIGateway()),
    )

    assert result.status is AnalysisStatus.FAILED
    assert "RuntimeError" in result.errors[0]
    assert "secret-token" not in result.errors[0]


def test_dependencies_require_constraints() -> None:
    with pytest.raises(ValueError, match="空间约束"):
        SiteSelectionWorkflowDependencies(
            poi_gateway=poi_gateway(),
            poi_scoring_config=scoring_config(),
            spatial_gateway=MockSpatialDatasetGateway(),
            constraint_specs=[],
            rules=[rule()],
        )


def test_dependencies_require_rules() -> None:
    with pytest.raises(ValueError, match="版本化规则"):
        SiteSelectionWorkflowDependencies(
            poi_gateway=poi_gateway(),
            poi_scoring_config=scoring_config(),
            spatial_gateway=MockSpatialDatasetGateway(),
            constraint_specs=[constraint_spec()],
            rules=[],
        )


def test_dependencies_require_positive_buffer() -> None:
    with pytest.raises(ValueError, match="缓冲距离"):
        SiteSelectionWorkflowDependencies(
            poi_gateway=poi_gateway(),
            poi_scoring_config=scoring_config(),
            spatial_gateway=MockSpatialDatasetGateway(),
            constraint_specs=[constraint_spec()],
            rules=[rule()],
            buffer_distance_m=0,
        )


def test_result_assembly_requires_all_three_evidence_types() -> None:
    completed = run_site_selection_workflow(
        request(),
        manifests(),
        dependencies(),
    )
    incomplete_data = completed.model_dump()
    incomplete_data["policy_evidence"] = []
    incomplete_data["results"] = []
    incomplete_data["status"] = AnalysisStatus.ANALYZING
    incomplete = AgentState.model_validate(incomplete_data)

    with pytest.raises(ResultAssemblyBlockedError, match="policy"):
        assemble_analysis_results(incomplete)


def test_result_assembly_preserves_explicit_poi_soft_score() -> None:
    completed = run_site_selection_workflow(
        request(),
        manifests(),
        dependencies(),
    )
    scored_data = completed.model_dump()
    scored_data["poi_evidence"][0]["score_report"] = None
    scored_data["poi_evidence"][0]["soft_score"] = 82.5
    scored_data["results"] = []
    scored_data["status"] = AnalysisStatus.ANALYZING
    scored = AgentState.model_validate(scored_data)

    result = assemble_analysis_results(scored)

    assert result.results[0].overall_soft_score == 82.5
    assert not any(
        "未生成软评分" in item
        for item in result.results[0].warnings
    )
