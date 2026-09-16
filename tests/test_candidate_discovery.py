from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import geopandas as gpd
import pytest
from pydantic import ValidationError
from shapely.geometry import shape

import practice.site_selection.candidate_discovery as candidate_discovery_module

from app.services.site_selection_service import (
    SiteSelectionRuntime,
    SiteSelectionRuntimeRegistry,
)
from app.site_selection_bootstrap import (
    build_fixture_runtime_registry,
    load_fixture_spatial_seed,
)
from practice.site_selection import (
    AnalysisStatus,
    CandidateDiscoveryBlockedError,
    CandidateDiscoveryFallbackMode,
    CandidateDiscoveryRequest,
    CandidateDiscoveryService,
    CandidateDiscoveryStrategy,
    DiscoveryBounds,
    DatasetEvidenceLevel,
    LandUseFeature,
    LandUseFeatureSet,
    LandUseQuery,
    LandUseSourceMeta,
    LandUseSuitability,
    POIFeatureSet,
    POIProvider,
    POIQuery,
    POIRecord,
    POISourceMeta,
    ProjectRequest,
    ProjectType,
    build_candidate_discovery_execution_plan,
    build_candidate_discovery_graph,
    get_project_profile,
    get_supported_poi_categories,
    run_parallel_site_selection_workflow,
)
from practice.site_selection.poi_adapters import (
    FixturePOIAdapter,
    haversine_distance_m,
)
from practice.site_selection.online_poi_adapters import (
    FallbackPOIAdapter,
    POIUpstreamError,
)
from practice.site_selection.candidate_discovery import (
    _repair_incomplete_scoring_evidence,
    _search_queries_retaining_availability_failures,
)
from practice.site_selection.spatial import MockSpatialDatasetGateway


FIXTURE_ROOT = Path(__file__).parents[1] / "data" / "fixtures"
NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


class CountingPOIAdapter:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.queries = []

    def search(self, query):
        self.queries.append(query.model_copy(deep=True))
        return self.delegate.search(query)


class CategoryBudgetPOIAdapter(CountingPOIAdapter):
    max_categories_per_query = 3


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self.snapshots = {}

    def save_candidate_discovery_snapshot(self, snapshot) -> None:
        self.snapshots[snapshot.snapshot_id] = snapshot

    def get_candidate_discovery_snapshot(self, snapshot_id):
        return self.snapshots.get(snapshot_id)


class ScriptedRepairPOIAdapter:
    max_categories_per_query = 3

    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.queries = []

    def search(self, query):
        self.queries.append(query.model_copy(deep=True))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        provider, category = outcome
        return repair_feature_set(
            query,
            provider=provider,
            category=category,
            fallback=provider is POIProvider.MOCK,
        )


def repair_feature_set(
    query: POIQuery,
    *,
    provider: POIProvider,
    category: str,
    fallback: bool = False,
) -> POIFeatureSet:
    records = [
        POIRecord(
            poi_id=f"{query.query_id}:{category}",
            name=f"补查 {category}",
            category=category,
            longitude=query.longitude,
            latitude=query.latitude,
            distance_m=0,
        )
    ]
    return POIFeatureSet(
        query=query,
        records=records,
        source=POISourceMeta(
            provider=provider,
            dataset_id=f"{provider.value}-repair-test",
            queried_at=NOW,
            record_count=1,
            available_record_count=1,
            is_synthetic=fallback,
            quality_notice=("测试 Fixture" if fallback else None),
            fallback_from=(POIProvider.OSM if fallback else None),
            fallback_reason=("POIUpstreamError" if fallback else None),
        ),
    )


def broad_feature_sets(*, target_mode: str = "complete") -> list[POIFeatureSet]:
    profile = get_project_profile(ProjectType.COFFEE_SHOP)
    center_lon, center_lat = discovery_request().bounds.center
    feature_sets = []
    for group in profile.poi_groups:
        records = [
            POIRecord(
                poi_id=f"broad:{group.group_key}:{index}",
                name=f"宽域 {category}",
                category=category,
                longitude=center_lon,
                latitude=center_lat,
                distance_m=0,
            )
            for index, category in enumerate(group.categories, start=1)
        ]
        provider = POIProvider.OSM
        is_synthetic = False
        fallback_from = None
        fallback_reason = None
        quality_notice = None
        is_truncated = False
        if group.group_key == "transit_access" and target_mode == "fallback":
            provider = POIProvider.MOCK
            is_synthetic = True
            fallback_from = POIProvider.OSM
            fallback_reason = "POIUpstreamError"
            quality_notice = "测试 Fixture"
        elif group.group_key == "transit_access" and target_mode == "truncated":
            is_truncated = True
        query = POIQuery(
            query_id=f"broad:{group.group_key}",
            parcel_id="candidate-discovery-scope",
            group_key=group.group_key,
            longitude=center_lon,
            latitude=center_lat,
            categories=group.categories,
            radius_m=10_000,
            limit=1_000,
        )
        feature_sets.append(
            POIFeatureSet(
                query=query,
                records=records,
                source=POISourceMeta(
                    provider=provider,
                    dataset_id=f"{provider.value}-broad-test",
                    queried_at=NOW,
                    record_count=len(records),
                    available_record_count=(
                        len(records) + 1 if is_truncated else len(records)
                    ),
                    is_truncated=is_truncated,
                    is_synthetic=is_synthetic,
                    quality_notice=quality_notice,
                    fallback_from=fallback_from,
                    fallback_reason=fallback_reason,
                ),
            )
        )
    return feature_sets


def test_category_availability_failure_is_retained_without_grid_retry() -> None:
    profile = get_project_profile(ProjectType.COFFEE_SHOP)
    feature_sets = broad_feature_sets()
    target_index = next(
        index
        for index, item in enumerate(feature_sets)
        if item.query.group_key == "stay_environment"
    )
    target = feature_sets[target_index]
    partial_records = [
        item for item in target.records if item.category != "公园"
    ]
    partial_source = POISourceMeta.model_validate(
        {
            **target.source.model_dump(),
            "record_count": len(partial_records),
            "available_record_count": len(partial_records) + 1,
            "is_truncated": True,
            "unavailable_categories": ["公园"],
            "availability_warnings": ["公园：POIUpstreamError：HTTP 504"],
        }
    )
    feature_sets[target_index] = POIFeatureSet(
        query=target.query,
        records=partial_records,
        source=partial_source,
    )

    class NoRetryGateway:
        def search(self, query):
            raise AssertionError("类别级上游失败不应立即触发分区重试")

    repaired, statuses, warnings = _repair_incomplete_scoring_evidence(
        discovery_request(),
        profile,
        NoRetryGateway(),
        feature_sets,
    )

    retained = next(
        item for item in repaired if item.query.group_key == "stay_environment"
    )
    status = next(
        item for item in statuses if item.group_key == "stay_environment"
    )
    assert retained == feature_sets[target_index]
    assert status.query_count == 0
    assert any("上游查询失败类别：公园" in item for item in status.remaining_reasons)
    assert all("stay_environment 已执行 2×2" not in item for item in warnings)


def test_failed_scoring_group_does_not_discard_other_real_groups() -> None:
    queries = [item.query for item in broad_feature_sets()]

    class PartlyUnavailableGateway:
        provider = POIProvider.OSM

        def search(self, query):
            if query.group_key == "stay_environment":
                raise POIUpstreamError("Overpass HTTP 429/504")
            return next(
                item
                for item in broad_feature_sets()
                if item.query.group_key == query.group_key
            ).model_copy(deep=True, update={"query": query})

    results = _search_queries_retaining_availability_failures(
        PartlyUnavailableGateway(),
        queries,
    )

    assert len(results) == len(queries)
    assert sum(bool(item.records) for item in results) == len(queries) - 1
    failed = next(
        item for item in results if item.query.group_key == "stay_environment"
    )
    assert failed.source.provider is POIProvider.OSM
    assert failed.source.is_synthetic is False
    assert failed.source.is_truncated is True
    assert failed.source.unavailable_categories == failed.query.categories
    assert "HTTP 429/504" in failed.source.availability_warnings[0]


def fixture_frames():
    seed = load_fixture_spatial_seed(FIXTURE_ROOT / "spatial_layers.json")
    return {
        layer.layer_id: gpd.GeoDataFrame(
            [feature.properties for feature in layer.features],
            geometry=[shape(feature.geometry) for feature in layer.features],
            crs=seed.crs,
        )
        for layer in seed.layers
    }


def discovery_request(
    project_type: ProjectType = ProjectType.COFFEE_SHOP,
) -> CandidateDiscoveryRequest:
    latitude_offset = 0.17 if project_type is ProjectType.CONVENIENCE_STORE else 0
    return CandidateDiscoveryRequest(
        request_id=f"discover-{project_type.value}",
        project_type=project_type,
        bounds=DiscoveryBounds(
            west=121.29,
            south=31.14 + latitude_offset,
            east=121.37,
            north=31.19 + latitude_offset,
        ),
        max_candidates=8,
        minimum_separation_m=600,
    )


def test_discovery_is_land_use_gated_diversified_and_auditable() -> None:
    poi_adapter = CountingPOIAdapter(
        FixturePOIAdapter.from_json(FIXTURE_ROOT / "poi.json")
    )
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(fixture_frames()),
        poi_adapter=poi_adapter,
    )

    report = CandidateDiscoveryService(registry).discover(discovery_request())

    assert report.confirmation_required is True
    assert report.strategy is CandidateDiscoveryStrategy.REGISTERED_LAND
    assert report.formal_analysis_allowed is True
    assert report.evaluated_candidate_count == 20
    assert report.excluded_by_land_use_count == 5
    assert len(report.candidates) == 8
    assert all(
        item.land_use_suitability is not LandUseSuitability.EXCLUDED
        for item in report.candidates
    )
    assert all(
        item.candidate.geometry_dataset_id == "demo-coffee-discovery-pool"
        for item in report.candidates
    )
    assert all(
        haversine_distance_m(
            left.candidate.longitude,
            left.candidate.latitude,
            right.candidate.longitude,
            right.candidate.latitude,
        )
        >= 600
        for index, left in enumerate(report.candidates)
        for right in report.candidates[index + 1 :]
    )
    assert all(
        item.requires_human_review
        is (item.land_use_suitability is LandUseSuitability.REVIEW_REQUIRED)
        for item in report.candidates
    )
    profile = get_project_profile(ProjectType.COFFEE_SHOP)
    scoring_categories = {
        category
        for group in profile.poi_groups
        for category in group.categories
    }
    assert len(poi_adapter.queries) == 2
    assert set(poi_adapter.queries[0].categories) == scoring_categories
    assert set(poi_adapter.queries[1].categories) == (
        set(get_supported_poi_categories()) - scoring_categories
    )
    assert {
        category
        for query in poi_adapter.queries
        for category in query.categories
    } == set(get_supported_poi_categories())
    assert report.range_poi_observed_count == len(report.range_pois)
    assert report.range_pois
    assert len(
        {(item.provider, item.poi_id) for item in report.range_pois}
    ) == len(report.range_pois)
    assert all(
        report.bounds.contains(item.longitude, item.latitude)
        for item in report.range_pois
    )
    assert {item.purpose.value for item in report.sources} == {
        "scoring",
        "range_context",
    }
    assert {trace.node_id for trace in report.agent_trace} == {
        step.node_id for step in report.execution_plan.steps
    }
    assert any("合成 Fixture" in warning for warning in report.warnings)
    assert report.total_elapsed_ms >= 0


def test_discovery_returns_fixture_promptly_when_online_provider_is_unavailable() -> None:
    class UnavailablePOIAdapter:
        max_categories_per_query = 3
        provider = POIProvider.OSM

        def __init__(self) -> None:
            self.calls = 0

        def search(self, query):
            self.calls += 1
            raise POIUpstreamError("测试 Provider 不可用")

    primary = UnavailablePOIAdapter()
    fixture = FixturePOIAdapter.from_json(FIXTURE_ROOT / "poi.json")
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(fixture_frames()),
        poi_adapter=FallbackPOIAdapter(primary, fixture),
    )

    report = CandidateDiscoveryService(registry).discover(discovery_request())

    assert report.candidates
    assert primary.calls == 2
    assert any("跳过分区补查" in warning for warning in report.warnings)
    assert all(
        item.fallback_from is POIProvider.OSM
        for item in report.sources
        if item.purpose.value in {"scoring", "range_context"}
    )


def test_discovery_runtime_graph_nodes_are_the_reviewed_plan_nodes() -> None:
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(fixture_frames()),
    )
    graph = build_candidate_discovery_graph(registry).get_graph()
    plan = build_candidate_discovery_execution_plan()

    assert set(graph.nodes) - {"__start__", "__end__"} == {
        step.node_id for step in plan.steps
    }


def test_discovery_land_and_poi_nodes_start_concurrently() -> None:
    barrier = Barrier(2, timeout=2)

    class BarrierPOIAdapter:
        max_categories_per_query = None

        def __init__(self, delegate) -> None:
            self.delegate = delegate
            self.first_search = True

        def search(self, query):
            if self.first_search:
                self.first_search = False
                barrier.wait()
            return self.delegate.search(query)

    class BarrierSpatialGateway:
        def __init__(self, delegate) -> None:
            self.delegate = delegate
            self.first_load = True

        def load(self, manifest):
            if self.first_load:
                self.first_load = False
                barrier.wait()
            return self.delegate.load(manifest)

    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=BarrierSpatialGateway(
            MockSpatialDatasetGateway(fixture_frames())
        ),
        poi_adapter=BarrierPOIAdapter(
            FixturePOIAdapter.from_json(FIXTURE_ROOT / "poi.json")
        ),
    )

    report = CandidateDiscoveryService(registry).discover(discovery_request())

    assert report.candidates
    assert {trace.status.value for trace in report.agent_trace} == {
        "succeeded"
    }


def test_discovery_persists_scoring_evidence_snapshot_for_formal_analysis() -> None:
    store = InMemorySnapshotStore()
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(fixture_frames()),
    )
    service = CandidateDiscoveryService(
        registry,
        snapshot_store=store,
        snapshot_id_factory=lambda: "poi-snapshot-discovery-001",
    )

    report = service.discover(discovery_request())
    frozen = store.snapshots[report.poi_evidence_snapshot_id]

    assert report.poi_evidence_snapshot_id == "poi-snapshot-discovery-001"
    assert report.poi_evidence_snapshot_sha256 == frozen.content_sha256
    assert report.poi_evidence_snapshot_record_count == frozen.unique_record_count
    assert frozen.project_type is ProjectType.COFFEE_SHOP
    assert [item.parcel_id for item in frozen.candidates] == [
        item.candidate.parcel_id for item in report.candidates
    ]
    assert {item.query.group_key for item in frozen.feature_sets} == {
        group.group_key
        for group in get_project_profile(ProjectType.COFFEE_SHOP).poi_groups
    }


@pytest.mark.parametrize(
    "project_type",
    [ProjectType.COFFEE_SHOP, ProjectType.CONVENIENCE_STORE],
)
def test_retail_discovery_balances_categories_for_limited_online_provider(
    project_type,
) -> None:
    poi_adapter = CategoryBudgetPOIAdapter(
        FixturePOIAdapter.from_json(FIXTURE_ROOT / "poi.json")
    )
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(fixture_frames()),
        poi_adapter=poi_adapter,
    )

    report = CandidateDiscoveryService(registry).discover(
        discovery_request(project_type)
    )
    profile = get_project_profile(project_type)
    scoring_keys = {group.group_key for group in profile.poi_groups}
    scoring_sources = [
        source for source in report.sources if source.purpose.value == "scoring"
    ]

    assert len(scoring_sources) == len(profile.poi_groups)
    assert {source.group_key for source in scoring_sources} == scoring_keys
    assert all(len(query.categories) <= 3 for query in poi_adapter.queries)
    assert {
        category
        for query in poi_adapter.queries
        for category in query.categories
    } == set(get_supported_poi_categories())
    assert report.range_pois
    assert report.total_elapsed_ms >= 0


def test_discovered_candidates_complete_existing_formal_workflow() -> None:
    gateway = MockSpatialDatasetGateway(fixture_frames())
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=gateway,
    )
    report = CandidateDiscoveryService(registry).discover(discovery_request())
    runtime = registry.resolve(ProjectType.COFFEE_SHOP)

    state = run_parallel_site_selection_workflow(
        ProjectRequest(
            request_id="discovery-formal-analysis",
            project_type=ProjectType.COFFEE_SHOP,
            candidate_parcels=[item.candidate for item in report.candidates[:3]],
            requested_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        ),
        runtime.datasets,
        runtime.dependencies,
    )

    assert state.status is AnalysisStatus.COMPLETED
    assert len(state.results) == 3
    assert all(item.gis_evidence.metrics for item in state.results)


def test_discovery_fails_closed_without_land_use_opportunity_layer() -> None:
    frames = fixture_frames()
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(frames),
    )
    configured = registry.resolve(ProjectType.COFFEE_SHOP)
    incomplete = SiteSelectionRuntime(
        project_type=ProjectType.COFFEE_SHOP,
        datasets=configured.datasets[:2],
        dependencies=configured.dependencies,
    )
    service = CandidateDiscoveryService(
        SiteSelectionRuntimeRegistry({ProjectType.COFFEE_SHOP: incomplete})
    )

    strict_request = discovery_request().model_copy(
        update={"fallback_mode": CandidateDiscoveryFallbackMode.STRICT}
    )
    with pytest.raises(CandidateDiscoveryBlockedError, match="机会单元"):
        service.discover(strict_request)


def test_discovery_uses_commercial_land_as_review_only_proxy() -> None:
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(fixture_frames()),
    )
    configured = registry.resolve(ProjectType.COFFEE_SHOP)
    proxy_runtime = SiteSelectionRuntime(
        project_type=ProjectType.COFFEE_SHOP,
        datasets=configured.datasets[:2],
        dependencies=configured.dependencies,
    )
    service = CandidateDiscoveryService(
        SiteSelectionRuntimeRegistry(
            {ProjectType.COFFEE_SHOP: proxy_runtime}
        )
    )

    report = service.discover(discovery_request())

    assert report.strategy is CandidateDiscoveryStrategy.COMMERCIAL_LAND_PROXY
    assert report.formal_analysis_allowed is False
    assert len(report.candidates) == 6
    assert all(item.requires_human_review for item in report.candidates)
    assert all(
        item.formal_analysis_allowed is False for item in report.candidates
    )
    assert {
        item.candidate.geometry_dataset_id for item in report.candidates
    } == {"demo-coffee-candidates"}
    assert any("商业用地代理" in warning for warning in report.warnings)


def test_discovery_builds_non_runnable_market_grid_without_land_data() -> None:
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(fixture_frames()),
    )
    configured = registry.resolve(ProjectType.COFFEE_SHOP)
    market_runtime = SiteSelectionRuntime(
        project_type=ProjectType.COFFEE_SHOP,
        datasets=[configured.datasets[1]],
        dependencies=configured.dependencies,
    )
    service = CandidateDiscoveryService(
        SiteSelectionRuntimeRegistry(
            {ProjectType.COFFEE_SHOP: market_runtime}
        )
    )

    report = service.discover(discovery_request())

    assert report.strategy is CandidateDiscoveryStrategy.MARKET_EXPLORATION
    assert report.formal_analysis_allowed is False
    assert len(report.candidates) == 8
    assert all(
        item.candidate.geometry_dataset_id is None
        and item.candidate.area_hectares is None
        and item.requires_human_review
        for item in report.candidates
    )
    assert any("市场机会热区" in warning for warning in report.warnings)


def test_discovery_prefers_public_land_polygons_before_fixture_proxy() -> None:
    class PublicLandProvider:
        def search(self, query: LandUseQuery) -> LandUseFeatureSet:
            return LandUseFeatureSet(
                query=query,
                features=[
                    LandUseFeature(
                        source_feature_id=f"osm:way:{index}",
                        name=f"真实商业单元 {index}",
                        land_use_class="OSM 商业用地",
                        longitude=121.30 + index * 0.015,
                        latitude=31.15 + index * 0.008,
                        area_hectares=1.5 + index,
                    )
                    for index in range(1, 4)
                ],
                source=LandUseSourceMeta(
                    dataset_id="openstreetmap-overpass-land-use",
                    dataset_version="osm-land-test-v1",
                    evidence_level=DatasetEvidenceLevel.PUBLIC_OBSERVATION,
                    queried_at=NOW,
                    source_uri="https://overpass-api.de/api/interpreter",
                    license="OpenStreetMap ODbL 1.0",
                    record_count=3,
                    available_record_count=3,
                ),
            )

    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(fixture_frames()),
    )
    configured = registry.resolve(ProjectType.COFFEE_SHOP)
    runtime_without_registered_land = SiteSelectionRuntime(
        project_type=ProjectType.COFFEE_SHOP,
        datasets=configured.datasets[:2],
        dependencies=configured.dependencies,
    )
    service = CandidateDiscoveryService(
        SiteSelectionRuntimeRegistry(
            {ProjectType.COFFEE_SHOP: runtime_without_registered_land}
        ),
        land_use_provider=PublicLandProvider(),
    )

    report = service.discover(discovery_request())

    assert report.strategy is CandidateDiscoveryStrategy.PUBLIC_LAND_OBSERVATION
    assert report.land_evidence_level is DatasetEvidenceLevel.PUBLIC_OBSERVATION
    assert report.formal_analysis_allowed is False
    assert report.land_source_license == "OpenStreetMap ODbL 1.0"
    assert all(
        item.candidate.parcel_id.startswith("osm:way:")
        for item in report.candidates
    )
    assert all(
        item.land_evidence_level is DatasetEvidenceLevel.PUBLIC_OBSERVATION
        for item in report.candidates
    )
    assert any("法定规划" in warning for warning in report.warnings)


def test_discovery_request_rejects_non_retail_and_oversized_bounds() -> None:
    with pytest.raises(ValidationError, match="只支持咖啡店和便利店"):
        CandidateDiscoveryRequest(
            project_type=ProjectType.SHOPPING_MALL,
            bounds=DiscoveryBounds(
                west=121.29, south=31.14, east=121.37, north=31.19
            ),
        )

    with pytest.raises(ValidationError, match="20 公里"):
        DiscoveryBounds(west=121.0, south=31.0, east=121.4, north=31.4)


def test_range_poi_layer_reports_response_limit_without_changing_candidates() -> None:
    gateway = MockSpatialDatasetGateway(fixture_frames())
    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=gateway,
    )
    service = CandidateDiscoveryService(registry)
    full = service.discover(discovery_request())
    limited = service.discover(
        discovery_request().model_copy(update={"range_poi_limit": 100})
    )

    assert limited.range_poi_observed_count == full.range_poi_observed_count
    assert len(limited.range_pois) == 100
    assert limited.range_poi_is_truncated is True
    assert [item.candidate.parcel_id for item in limited.candidates] == [
        item.candidate.parcel_id for item in full.candidates
    ]
    assert any("返回上限" in warning for warning in limited.warnings)


def test_discovery_report_exposes_repair_metrics_and_uses_repaired_ranking_input() -> None:
    class IntegrationRepairAdapter:
        max_categories_per_query = 3

        def __init__(self) -> None:
            self.delegate = FixturePOIAdapter.from_json(FIXTURE_ROOT / "poi.json")
            self.repair_count = 0

        def search(self, query):
            if ":repair:transit_access:" in query.query_id:
                category = query.categories[self.repair_count % len(query.categories)]
                self.repair_count += 1
                return repair_feature_set(
                    query,
                    provider=POIProvider.OSM,
                    category=category,
                )
            result = self.delegate.search(query)
            if query.group_key != "transit_access":
                return result
            return result.model_copy(
                deep=True,
                update={
                    "source": result.source.model_copy(
                        update={
                            "fallback_from": POIProvider.OSM,
                            "fallback_reason": "POIUpstreamError",
                        }
                    )
                },
            )

    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=FIXTURE_ROOT,
        spatial_gateway=MockSpatialDatasetGateway(fixture_frames()),
        poi_adapter=IntegrationRepairAdapter(),
    )

    report = CandidateDiscoveryService(registry).discover(discovery_request())

    transit = next(
        item for item in report.sources if item.group_key == "transit_access"
    )
    assert report.poi_repair_group_count == 1
    assert report.poi_repair_query_count == 4
    assert report.poi_repair_success_count == 4
    assert report.poi_repair_added_record_count == 4
    assert transit.provider is POIProvider.OSM
    assert transit.evidence_complete is True
    assert transit.repair_success_count == 4
    assert all(
        item.evidence_counts["transit_access"] >= 0
        for item in report.candidates
    )
    assert report.formal_analysis_allowed is True


def test_complete_online_scoring_evidence_skips_discovery_repair() -> None:
    gateway = ScriptedRepairPOIAdapter([])

    repaired, statuses, warnings = _repair_incomplete_scoring_evidence(
        discovery_request(),
        get_project_profile(ProjectType.COFFEE_SHOP),
        gateway,
        broad_feature_sets(),
    )

    assert not gateway.queries
    assert all(item.query_count == 0 for item in statuses)
    assert all(item.evidence_complete for item in statuses)
    assert all(item.source.provider is POIProvider.OSM for item in repaired)
    assert warnings == []


def test_saturated_category_complete_online_result_skips_discovery_repair() -> None:
    feature_sets = broad_feature_sets()
    transit = next(
        item
        for item in feature_sets
        if item.query.group_key == "transit_access"
    )
    records = [
        POIRecord(
            poi_id=f"saturated:{index}",
            name=f"上限记录 {index}",
            category=transit.query.categories[index % len(transit.query.categories)],
            longitude=transit.query.longitude,
            latitude=transit.query.latitude,
            distance_m=0,
        )
        for index in range(transit.query.limit)
    ]
    saturated = POIFeatureSet(
        query=transit.query.model_copy(deep=True),
        records=records,
        source=transit.source.model_copy(
            deep=True,
            update={
                "record_count": transit.query.limit,
                "available_record_count": transit.query.limit + 1_542,
                "is_truncated": True,
            },
        ),
    )
    feature_sets[feature_sets.index(transit)] = saturated
    gateway = ScriptedRepairPOIAdapter([])

    repaired, statuses, warnings = _repair_incomplete_scoring_evidence(
        discovery_request(),
        get_project_profile(ProjectType.COFFEE_SHOP),
        gateway,
        feature_sets,
    )

    repaired_transit = next(
        item for item in repaired if item.query.group_key == "transit_access"
    )
    transit_status = next(
        item for item in statuses if item.group_key == "transit_access"
    )
    assert not gateway.queries
    assert repaired_transit.source.is_truncated is True
    assert transit_status.query_count == 0
    assert transit_status.evidence_complete is False
    assert "返回截断或空间覆盖未完成" in transit_status.remaining_reasons
    assert any("跳过同步分区补查" in warning for warning in warnings)


def test_all_fallback_scoring_evidence_skips_expensive_repair() -> None:
    original = broad_feature_sets()
    fallback = [
        item.model_copy(
            deep=True,
            update={
                "source": item.source.model_copy(
                    deep=True,
                    update={
                        "provider": POIProvider.MOCK,
                        "dataset_id": "mock-fallback-test",
                        "is_synthetic": True,
                        "quality_notice": "测试 Fixture",
                        "fallback_from": POIProvider.OSM,
                        "fallback_reason": "POIUpstreamError",
                    },
                )
            },
        )
        for item in original
    ]
    gateway = ScriptedRepairPOIAdapter([])

    repaired, statuses, warnings = _repair_incomplete_scoring_evidence(
        discovery_request(),
        get_project_profile(ProjectType.COFFEE_SHOP),
        gateway,
        fallback,
    )

    assert not gateway.queries
    assert repaired == fallback
    assert all(item.query_count == 0 for item in statuses)
    assert all(not item.evidence_complete for item in statuses)
    assert any("全部不可用" in warning for warning in warnings)


def test_multiple_incomplete_groups_share_one_interleaved_repair_batch(
    monkeypatch,
) -> None:
    feature_sets = broad_feature_sets(target_mode="fallback")
    office = next(
        item
        for item in feature_sets
        if item.query.group_key == "office_demand_proxy"
    )
    office_index = feature_sets.index(office)
    feature_sets[office_index] = office.model_copy(
        deep=True,
        update={
            "source": office.source.model_copy(
                update={
                    "provider": POIProvider.MOCK,
                    "dataset_id": "mock-office-test",
                    "is_synthetic": True,
                    "quality_notice": "测试 Fixture",
                    "fallback_from": POIProvider.OSM,
                    "fallback_reason": "POIUpstreamError",
                }
            )
        },
    )
    batches = []

    def search_batch(gateway, queries):
        del gateway
        batches.append([item.model_copy(deep=True) for item in queries])
        group_counts = {}
        outcomes = []
        for query in queries:
            index = group_counts.get(query.group_key, 0)
            group_counts[query.group_key] = index + 1
            outcomes.append(
                (
                    repair_feature_set(
                        query,
                        provider=POIProvider.OSM,
                        category=query.categories[index % len(query.categories)],
                    ),
                    None,
                )
            )
        return outcomes

    monkeypatch.setattr(
        candidate_discovery_module,
        "_search_repair_queries",
        search_batch,
    )

    _, statuses, _ = _repair_incomplete_scoring_evidence(
        discovery_request(),
        get_project_profile(ProjectType.COFFEE_SHOP),
        object(),
        feature_sets,
    )

    assert len(batches) == 1
    assert len(batches[0]) == 8
    assert [item.group_key for item in batches[0][:4]] == [
        "transit_access",
        "office_demand_proxy",
        "transit_access",
        "office_demand_proxy",
    ]
    repaired = [item for item in statuses if item.query_count]
    assert len(repaired) == 2
    assert all(item.success_count == 4 for item in repaired)
    assert all(item.evidence_complete for item in repaired)


@pytest.mark.parametrize("target_mode", ["fallback", "truncated"])
def test_discovery_repair_tiles_incomplete_group_and_merges_real_records(
    target_mode,
) -> None:
    categories = ["地铁站", "公交站", "地铁站", "公交站"]
    gateway = ScriptedRepairPOIAdapter(
        [(POIProvider.OSM, category) for category in categories]
    )

    repaired, statuses, warnings = _repair_incomplete_scoring_evidence(
        discovery_request(),
        get_project_profile(ProjectType.COFFEE_SHOP),
        gateway,
        broad_feature_sets(target_mode=target_mode),
    )

    transit = next(
        item for item in repaired if item.query.group_key == "transit_access"
    )
    status = next(
        item for item in statuses if item.group_key == "transit_access"
    )
    assert len(gateway.queries) == 4
    assert len({(item.longitude, item.latitude) for item in gateway.queries}) == 4
    assert {item.parcel_id for item in gateway.queries} == {
        "candidate-discovery-repair"
    }
    assert status.query_count == 4
    assert status.success_count == 4
    assert status.added_record_count == 4
    assert status.evidence_complete is True
    assert transit.source.provider is POIProvider.OSM
    assert transit.source.is_synthetic is False
    assert transit.source.is_truncated is False
    assert any("2×2 分区补查" in warning for warning in warnings)


def test_partial_discovery_repair_keeps_group_explicitly_incomplete() -> None:
    gateway = ScriptedRepairPOIAdapter(
        [
            (POIProvider.OSM, "地铁站"),
            (POIProvider.OSM, "公交站"),
            (POIProvider.MOCK, "地铁站"),
            RuntimeError("upstream unavailable"),
        ]
    )

    repaired, statuses, warnings = _repair_incomplete_scoring_evidence(
        discovery_request(),
        get_project_profile(ProjectType.COFFEE_SHOP),
        gateway,
        broad_feature_sets(target_mode="fallback"),
    )

    transit = next(
        item for item in repaired if item.query.group_key == "transit_access"
    )
    status = next(
        item for item in statuses if item.group_key == "transit_access"
    )
    assert status.success_count == 2
    assert status.evidence_complete is False
    assert transit.source.provider is POIProvider.OSM
    assert transit.source.is_truncated is True
    assert any("仍不完整" in warning for warning in warnings)
    assert any("POIUpstreamError" in warning for warning in warnings)


def test_failed_discovery_repair_retains_original_fallback_and_audit_warning() -> None:
    gateway = ScriptedRepairPOIAdapter(
        [RuntimeError("offline") for _ in range(4)]
    )
    original = broad_feature_sets(target_mode="fallback")

    repaired, statuses, warnings = _repair_incomplete_scoring_evidence(
        discovery_request(),
        get_project_profile(ProjectType.COFFEE_SHOP),
        gateway,
        original,
    )

    transit = next(
        item for item in repaired if item.query.group_key == "transit_access"
    )
    status = next(
        item for item in statuses if item.group_key == "transit_access"
    )
    assert status.success_count == 0
    assert status.evidence_complete is False
    assert transit.source.provider is POIProvider.MOCK
    assert transit.source.fallback_from is POIProvider.OSM
    assert any("未恢复真实在线数据" in item for item in status.remaining_reasons)
    assert any("RuntimeError" in warning for warning in warnings)


class FallbackAwarePOIGateway:
    max_categories_per_query = 3

    def __init__(self) -> None:
        self.primary_queries = []
        self.fallback_queries = []

    def search(self, query):
        self.primary_queries.append(query.model_copy(deep=True))
        return repair_feature_set(
            query,
            provider=POIProvider.MOCK,
            category=query.categories[0],
            fallback=True,
        )

    def search_fallback(self, query, *, source_template=None):
        self.fallback_queries.append(query.model_copy(deep=True))
        return repair_feature_set(
            query,
            provider=POIProvider.MOCK,
            category=query.categories[0],
            fallback=True,
        )


def fallback_probe_queries() -> list[POIQuery]:
    return [
        POIQuery(
            query_id=f"probe:{index}",
            parcel_id="candidate-discovery-scope",
            group_key=f"probe_{index}",
            longitude=121.33,
            latitude=31.16,
            categories=["地铁站"],
            radius_m=1_000,
            limit=20,
        )
        for index in range(1, 4)
    ]


def test_search_queries_reuses_fallback_after_first_provider_probe() -> None:
    gateway = FallbackAwarePOIGateway()

    results = candidate_discovery_module._search_queries(
        gateway,
        fallback_probe_queries(),
    )

    assert len(results) == 3
    assert len(gateway.primary_queries) == 1
    assert len(gateway.fallback_queries) == 2


def test_optional_search_queries_reuses_fallback_after_first_provider_probe() -> None:
    gateway = FallbackAwarePOIGateway()

    results, warnings = candidate_discovery_module._search_optional_queries(
        gateway,
        fallback_probe_queries(),
    )

    assert len(results) == 3
    assert warnings == []
    assert len(gateway.primary_queries) == 1
    assert len(gateway.fallback_queries) == 2
