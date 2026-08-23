from datetime import datetime, timezone
from typing import cast

import pytest

from app.schemas.site_selection import SiteSelectionAnalysisCreate
from app.services.site_selection_service import (
    SiteSelectionAnalysisService,
    SiteSelectionRuntime,
    SiteSelectionRuntimeConfigurationError,
    SiteSelectionRuntimeRegistry,
    SiteSelectionRuntimeUnavailableError,
    UnconfiguredSiteSelectionRuntimeProvider,
)
from practice.site_selection import (
    CandidateDiscoverySnapshotNotFoundError,
    DatasetManifest,
    DatasetSource,
    POIQuery,
    ProjectIntakeSkill,
    ProjectType,
    SiteSelectionWorkflowDependencies,
    build_candidate_discovery_poi_snapshot,
)
from tests.test_evidence_snapshot import broad_feature_set
from tests.test_site_selection_workflow import dependencies


NOW = datetime(2026, 8, 18, 23, 59, tzinfo=timezone.utc)


def command() -> SiteSelectionAnalysisCreate:
    return SiteSelectionAnalysisCreate.model_validate(
        {
            "project_type": "shopping_mall",
            "candidate_parcels": [
                {
                    "parcel_id": "A01",
                    "name": "测试地块",
                    "longitude": 121.47,
                    "latitude": 31.23,
                    "area_hectares": 3.5,
                    "geometry_dataset_id": "parcel-demo",
                }
            ],
        }
    )


def manifest() -> DatasetManifest:
    return DatasetManifest(
        dataset_id="parcel-demo",
        name="合成测试地块",
        source=DatasetSource.POSTGIS,
        location="parcel_demo",
        version="2026.08",
        crs="EPSG:32651",
        required_fields=["parcel_id"],
        updated_at=NOW,
    )


def runtime() -> SiteSelectionRuntime:
    dependencies = cast(SiteSelectionWorkflowDependencies, object())
    return SiteSelectionRuntime(
        project_type=ProjectType.SHOPPING_MALL,
        datasets=[manifest()],
        dependencies=dependencies,
    )


class RecordingProvider:
    def __init__(self, configured_runtime: SiteSelectionRuntime) -> None:
        self.configured_runtime = configured_runtime
        self.project_types: list[ProjectType] = []

    def resolve(self, project_type: ProjectType) -> SiteSelectionRuntime:
        self.project_types.append(project_type)
        return self.configured_runtime


def test_service_builds_domain_request_and_invokes_workflow() -> None:
    configured_runtime = runtime()
    provider = RecordingProvider(configured_runtime)
    calls = []

    def runner(request, datasets, dependencies):
        calls.append((request, tuple(datasets), dependencies))
        return ProjectIntakeSkill().run(request)

    service = SiteSelectionAnalysisService(
        provider,
        workflow_runner=runner,
        clock=lambda: NOW,
        request_id_factory=lambda: "analysis-fixed-001",
    )

    state = service.analyze(command())

    assert provider.project_types == [ProjectType.SHOPPING_MALL]
    assert len(calls) == 1
    request, datasets, dependencies = calls[0]
    assert request.request_id == "analysis-fixed-001"
    assert request.requested_at == NOW
    assert request.project_type is ProjectType.SHOPPING_MALL
    assert request.candidate_parcels[0].parcel_id == "A01"
    assert request.candidate_parcels[0].area_hectares == 3.5
    assert datasets == tuple(configured_runtime.datasets)
    assert dependencies is configured_runtime.dependencies
    assert state.request.request_id == "analysis-fixed-001"


def test_service_reuses_discovery_snapshot_without_calling_live_gateway() -> None:
    class RaisingGateway:
        def search(self, query):
            raise AssertionError(f"unexpected live POI query: {query.group_key}")

    class SnapshotStore:
        def __init__(self, frozen):
            self.frozen = frozen

        def get_candidate_discovery_snapshot(self, snapshot_id):
            return self.frozen if snapshot_id == self.frozen.snapshot_id else None

    analysis_command = command().model_copy(
        update={"poi_evidence_snapshot_id": "poi-snapshot-analysis-001"}
    )
    parcel = analysis_command.candidate_parcels[0].to_domain()
    broad = broad_feature_set().model_copy(
        update={
            "query": broad_feature_set().query.model_copy(
                update={"group_key": "public_transit"}
            )
        }
    )
    frozen = build_candidate_discovery_poi_snapshot(
        discovery_request_id="discover-analysis-001",
        project_type=ProjectType.SHOPPING_MALL,
        created_at=NOW,
        candidates=[parcel],
        feature_sets=[broad],
        snapshot_id="poi-snapshot-analysis-001",
    )
    configured_dependencies = dependencies(active_poi_gateway=RaisingGateway())
    configured_runtime = SiteSelectionRuntime(
        project_type=ProjectType.SHOPPING_MALL,
        datasets=[manifest()],
        dependencies=configured_dependencies,
    )
    captured = []

    def runner(request, datasets, workflow_dependencies):
        del datasets
        captured.append(
            workflow_dependencies.poi_gateway.search(
                POIQuery(
                    query_id="formal-public-transit",
                    parcel_id=parcel.parcel_id,
                    group_key="public_transit",
                    longitude=parcel.longitude,
                    latitude=parcel.latitude,
                    categories=["公交站"],
                    radius_m=200,
                    limit=100,
                )
            )
        )
        return ProjectIntakeSkill().run(request)

    service = SiteSelectionAnalysisService(
        SiteSelectionRuntimeRegistry(
            {ProjectType.SHOPPING_MALL: configured_runtime}
        ),
        snapshot_store=SnapshotStore(frozen),
        workflow_runner=runner,
        clock=lambda: NOW,
        request_id_factory=lambda: "analysis-fixed-snapshot",
    )

    service.analyze(analysis_command)

    assert captured[0].source.evidence_snapshot_id == frozen.snapshot_id
    assert captured[0].source.evidence_reused is True


def test_service_fails_closed_when_discovery_snapshot_is_missing() -> None:
    class EmptySnapshotStore:
        def get_candidate_discovery_snapshot(self, snapshot_id):
            return None

    service = SiteSelectionAnalysisService(
        RecordingProvider(runtime()),
        snapshot_store=EmptySnapshotStore(),
    )
    analysis_command = command().model_copy(
        update={"poi_evidence_snapshot_id": "expired-snapshot"}
    )

    with pytest.raises(
        CandidateDiscoverySnapshotNotFoundError,
        match="不存在或已过期",
    ):
        service.analyze(analysis_command)


def test_runtime_copies_dataset_sequence_to_immutable_tuple() -> None:
    source_manifest = manifest()
    datasets = [source_manifest]

    configured_runtime = SiteSelectionRuntime(
        project_type=ProjectType.SHOPPING_MALL,
        datasets=datasets,
        dependencies=cast(SiteSelectionWorkflowDependencies, object()),
    )
    datasets.clear()
    source_manifest.version = "changed-after-runtime-created"

    assert isinstance(configured_runtime.datasets, tuple)
    assert len(configured_runtime.datasets) == 1
    assert configured_runtime.datasets[0].version == "2026.08"


def test_runtime_requires_at_least_one_dataset() -> None:
    with pytest.raises(ValueError, match="至少需要一个数据清单"):
        SiteSelectionRuntime(
            project_type=ProjectType.SHOPPING_MALL,
            datasets=[],
            dependencies=cast(SiteSelectionWorkflowDependencies, object()),
        )


def test_unconfigured_provider_fails_without_demo_business_values() -> None:
    provider = UnconfiguredSiteSelectionRuntimeProvider()

    with pytest.raises(
        SiteSelectionRuntimeUnavailableError,
        match="shopping_mall",
    ):
        provider.resolve(ProjectType.SHOPPING_MALL)


def test_runtime_registry_resolves_only_configured_project_types() -> None:
    configured_runtime = runtime()
    registry = SiteSelectionRuntimeRegistry(
        {ProjectType.SHOPPING_MALL: configured_runtime}
    )

    resolved = registry.resolve(ProjectType.SHOPPING_MALL)

    assert registry.configured_types == (ProjectType.SHOPPING_MALL,)
    assert resolved.project_type is ProjectType.SHOPPING_MALL
    assert resolved is not configured_runtime
    with pytest.raises(SiteSelectionRuntimeUnavailableError, match="logistics"):
        registry.resolve(ProjectType.LOGISTICS_PARK)


def test_runtime_registry_rejects_mismatched_registration_key() -> None:
    with pytest.raises(ValueError, match="注册键"):
        SiteSelectionRuntimeRegistry(
            {ProjectType.LOGISTICS_PARK: runtime()}
        )


def test_runtime_registry_returns_defensive_manifest_copies() -> None:
    registry = SiteSelectionRuntimeRegistry(
        {ProjectType.SHOPPING_MALL: runtime()}
    )

    first = registry.resolve(ProjectType.SHOPPING_MALL)
    first.datasets[0].version = "changed-by-caller"
    second = registry.resolve(ProjectType.SHOPPING_MALL)

    assert second.datasets[0].version == "2026.08"


def test_service_rejects_provider_runtime_for_another_project_type() -> None:
    wrong_runtime = SiteSelectionRuntime(
        project_type=ProjectType.LOGISTICS_PARK,
        datasets=[manifest()],
        dependencies=cast(SiteSelectionWorkflowDependencies, object()),
    )
    service = SiteSelectionAnalysisService(
        RecordingProvider(wrong_runtime),
        workflow_runner=lambda *args: pytest.fail("workflow must not run"),
    )

    with pytest.raises(SiteSelectionRuntimeConfigurationError, match="不一致"):
        service.analyze(command())
