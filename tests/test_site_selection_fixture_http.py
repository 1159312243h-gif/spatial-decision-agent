from datetime import date, datetime, timezone
from pathlib import Path

import geopandas as gpd
from fastapi.testclient import TestClient
from shapely.geometry import Point, Polygon

from app.main import create_app
from app.services.site_selection_service import (
    SiteSelectionRuntime,
    SiteSelectionRuntimeRegistry,
)
from practice.site_selection import (
    ConstraintLayerSpec,
    ConstraintLayerType,
    DatasetManifest,
    DatasetSource,
    FixturePOIAdapter,
    MissingMetricPolicy,
    POIGroupScoringConfig,
    POIMetric,
    POIMetricScoringRule,
    POIScoringConfig,
    PolicyReference,
    ProjectType,
    RuleDefinition,
    RuleOutcome,
    ScoreDirection,
    SiteSelectionWorkflowDependencies,
    SpatialConstraintRelation,
    get_project_profile,
)
from practice.site_selection.spatial import MockSpatialDatasetGateway


NOW = datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc)
PARCEL_DATASET_ID = "fixture-parcel-geometry"
CONSTRAINT_DATASET_ID = "fixture-review-layer"
CONSTRAINT_ID = "fixture-review-observation"
POI_FIXTURE_PATH = (
    Path(__file__).parents[1] / "data" / "fixtures" / "poi.json"
)


def parcel_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"parcel_id": ["A01"], "land_use": ["fixture-commercial"]},
        geometry=[
            Polygon(
                [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)]
            )
        ],
        crs="EPSG:32651",
    )


def constraint_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"constraint_id": ["C01"], "fixture_only": [True]},
        geometry=[Point(50, 50)],
        crs="EPSG:32651",
    )


def manifest(
    dataset_id: str,
    required_fields: list[str],
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        name=f"合成测试数据：{dataset_id}",
        source=DatasetSource.FILE,
        location=f"fixture://{dataset_id}",
        version="fixture-test-2026.08.1",
        crs="EPSG:32651",
        required_fields=required_fields,
        updated_at=NOW,
    )


def scoring_config() -> POIScoringConfig:
    profile = get_project_profile(ProjectType.SHOPPING_MALL)
    groups = []
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
                        missing_policy=MissingMetricPolicy.ZERO,
                    )
                    for metric in group.metrics
                ],
            )
        )
    return POIScoringConfig(
        project_type=ProjectType.SHOPPING_MALL,
        version="fixture-test-only-1.0",
        groups=groups,
    )


def constraint_spec() -> ConstraintLayerSpec:
    return ConstraintLayerSpec(
        constraint_id=CONSTRAINT_ID,
        display_name="合成测试复核图层",
        layer_type=ConstraintLayerType.ECOLOGICAL_PROTECTION,
        dataset_id=CONSTRAINT_DATASET_ID,
        relation=SpatialConstraintRelation.INTERSECTS,
        applicable_project_types=[ProjectType.SHOPPING_MALL],
        required_fields=["constraint_id", "fixture_only"],
    )


def fixture_rule() -> RuleDefinition:
    return RuleDefinition(
        rule_id="RULE-FIXTURE-HTTP",
        name="仅用于 HTTP 链路测试的规则",
        version="fixture-test-1.0",
        applicable_project_types=[ProjectType.SHOPPING_MALL],
        constraint_id=CONSTRAINT_ID,
        outcome=RuleOutcome.REVIEW_REQUIRED,
        message="合成条件命中，仅验证链路，不代表真实政策判断",
        policy=PolicyReference(
            policy_id="POLICY-FIXTURE-HTTP",
            title="合成测试政策引用",
            issuing_authority="测试代码",
            clause="fixture-only",
            version="fixture-test-1.0",
            jurisdiction="测试环境",
            source_uri="fixture://policy/http-chain",
        ),
        valid_from=date(2026, 1, 1),
    )


def fixture_runtime_registry() -> SiteSelectionRuntimeRegistry:
    manifests = [
        manifest(PARCEL_DATASET_ID, ["parcel_id", "land_use"]),
        manifest(
            CONSTRAINT_DATASET_ID,
            ["constraint_id", "fixture_only"],
        ),
    ]
    dependencies = SiteSelectionWorkflowDependencies(
        poi_gateway=FixturePOIAdapter.from_json(
            POI_FIXTURE_PATH,
            clock=lambda: NOW,
        ),
        poi_scoring_config=scoring_config(),
        spatial_gateway=MockSpatialDatasetGateway(
            {
                PARCEL_DATASET_ID: parcel_frame(),
                CONSTRAINT_DATASET_ID: constraint_frame(),
            }
        ),
        constraint_specs=[constraint_spec()],
        rules=[fixture_rule()],
        buffer_distance_m=200,
    )
    runtime = SiteSelectionRuntime(
        project_type=ProjectType.SHOPPING_MALL,
        datasets=manifests,
        dependencies=dependencies,
    )
    return SiteSelectionRuntimeRegistry(
        {ProjectType.SHOPPING_MALL: runtime}
    )


def analysis_payload(project_type: str = "shopping_mall") -> dict:
    return {
        "project_type": project_type,
        "candidate_parcels": [
            {
                "parcel_id": "A01",
                "name": "Fixture 候选地块",
                "longitude": 121.47,
                "latitude": 31.23,
                "area_hectares": 1,
                "geometry_dataset_id": PARCEL_DATASET_ID,
            }
        ],
    }


def test_fixture_runtime_completes_http_analysis_chain() -> None:
    client = TestClient(create_app(fixture_runtime_registry()))

    response = client.post(
        "/site-selection/analyses",
        json=analysis_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["project_type"] == "shopping_mall"
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["parcel_id"] == "A01"
    assert result["gis_evidence"]["metrics"]["area_hectares"] == 1
    assert result["poi_evidence"]["score_report"]["scoring_version"] == (
        "fixture-test-only-1.0"
    )
    feature_sets = result["poi_evidence"]["feature_sets"]
    assert len(feature_sets) == 6
    assert {
        item["source"]["dataset_version"] for item in feature_sets
    } == {"fixture-rich-v1"}
    assert {
        item["source"]["dataset_record_count"] for item in feature_sets
    } == {478}
    assert all(item["source"]["is_synthetic"] for item in feature_sets)
    findings = result["policy_evidence"]["rule_findings"]
    assert findings[0]["rule_id"] == "RULE-FIXTURE-HTTP"
    assert findings[0]["outcome"] == "review_required"
    assert body["comparison_report"]["candidates"][0]["soft_rank"] == 1


def test_fixture_registry_keeps_unconfigured_project_type_closed() -> None:
    client = TestClient(create_app(fixture_runtime_registry()))

    response = client.post(
        "/site-selection/analyses",
        json=analysis_payload("logistics_park"),
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "runtime_unavailable"
    assert "logistics_park" in detail["message"]
