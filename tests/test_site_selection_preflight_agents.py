from datetime import datetime, timezone

import pytest

from practice.site_selection import (
    AgentRole,
    AgentState,
    CandidateParcel,
    ConstraintLayerSpec,
    ConstraintLayerType,
    DatasetManifest,
    DatasetSource,
    OrchestratorAgent,
    OrchestratorAgentInput,
    PolicyAgent,
    PreflightStatus,
    ProjectRequest,
    ProjectType,
    SiteSelectionDraft,
    SpatialAgent,
    SpatialAgentBlockedError,
    SpatialAgentInput,
    SpatialConstraintRelation,
    evaluate_site_selection_draft,
    get_project_profile,
)
from practice.site_selection.spatial import MockSpatialDatasetGateway


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
DATASET_ID = "parcel-fixture-20260818"


def parcel(
    *,
    area_hectares: float | None = 2.5,
    geometry_dataset_id: str | None = DATASET_ID,
) -> CandidateParcel:
    return CandidateParcel(
        parcel_id="A01",
        name="候选地块 A",
        longitude=121.47,
        latitude=31.23,
        area_hectares=area_hectares,
        geometry_dataset_id=geometry_dataset_id,
    )


def manifest() -> DatasetManifest:
    return DatasetManifest(
        dataset_id=DATASET_ID,
        name="候选地块几何",
        source=DatasetSource.FILE,
        location="data/fixtures/parcel.geojson",
        version="fixture-2026.08.1",
        crs="EPSG:32651",
        required_fields=["parcel_id"],
        updated_at=NOW,
    )


def ready_draft(project_type: str) -> SiteSelectionDraft:
    return SiteSelectionDraft(
        project_type=project_type,
        candidate_parcels=[parcel()],
        datasets=[manifest()],
    )


@pytest.mark.parametrize(
    "project_type",
    [ProjectType.SHOPPING_MALL, ProjectType.LOGISTICS_PARK],
)
def test_supported_project_type_routes_to_matching_profile(
    project_type: ProjectType,
) -> None:
    decision = evaluate_site_selection_draft(ready_draft(project_type.value))

    assert decision.status is PreflightStatus.READY
    assert decision.project_type is project_type
    assert decision.profile is not None
    assert decision.profile.project_type is project_type
    assert decision.missing_fields == []


def test_unknown_project_type_stops_as_unsupported() -> None:
    decision = evaluate_site_selection_draft(ready_draft("office_tower"))

    assert decision.status is PreflightStatus.UNSUPPORTED
    assert decision.unsupported_value == "office_tower"
    assert decision.profile is None


def test_missing_business_input_is_returned_without_guessing() -> None:
    draft = SiteSelectionDraft(
        candidate_parcels=[
            parcel(area_hectares=None, geometry_dataset_id=None)
        ]
    )

    decision = evaluate_site_selection_draft(draft)

    assert decision.status is PreflightStatus.NEEDS_INPUT
    assert decision.missing_fields == [
        "project_type",
        "candidate_parcels[0].area_hectares",
        "candidate_parcels[0].geometry_dataset_id",
        "datasets",
    ]


def test_missing_referenced_manifest_is_named() -> None:
    draft = ready_draft(ProjectType.SHOPPING_MALL.value)
    draft.datasets = [
        manifest().model_copy(update={"dataset_id": "other-dataset"})
    ]

    decision = evaluate_site_selection_draft(draft)

    assert decision.status is PreflightStatus.NEEDS_INPUT
    assert decision.missing_fields == [f"datasets[{DATASET_ID}]"]


def test_orchestrator_returns_structured_preflight_output() -> None:
    agent_input = OrchestratorAgentInput(
        draft=ready_draft(ProjectType.LOGISTICS_PARK.value)
    )

    output = OrchestratorAgent().run(agent_input)

    assert output.role is AgentRole.ORCHESTRATOR
    assert output.decision.status is PreflightStatus.READY
    assert output.decision.project_type is ProjectType.LOGISTICS_PARK
    assert agent_input.draft.project_type == ProjectType.LOGISTICS_PARK.value


def test_spatial_agent_stops_when_gis_dataset_is_missing() -> None:
    request = ProjectRequest(
        request_id="REQ-agent-boundary",
        project_type=ProjectType.SHOPPING_MALL,
        candidate_parcels=[parcel()],
        requested_at=NOW,
    )
    state = AgentState(
        request=request,
        profile=get_project_profile(ProjectType.SHOPPING_MALL),
        datasets=[manifest()],
    )
    spec = ConstraintLayerSpec(
        constraint_id="constraint-demo",
        display_name="测试约束",
        layer_type=ConstraintLayerType.ECOLOGICAL_PROTECTION,
        dataset_id="constraint-dataset",
        relation=SpatialConstraintRelation.INTERSECTS,
        applicable_project_types=[ProjectType.SHOPPING_MALL],
        required_fields=["constraint_id"],
    )
    agent = SpatialAgent(MockSpatialDatasetGateway(), [spec])

    with pytest.raises(SpatialAgentBlockedError, match="status=missing"):
        agent.run(SpatialAgentInput(state=state))


def test_agents_reject_missing_runtime_configuration() -> None:
    with pytest.raises(ValueError, match="空间数据网关"):
        SpatialAgent(None, [])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="空间约束"):
        SpatialAgent(MockSpatialDatasetGateway(), [])
    with pytest.raises(ValueError, match="缓冲距离"):
        SpatialAgent(MockSpatialDatasetGateway(), [object()], buffer_distance_m=0)
    with pytest.raises(ValueError, match="版本化规则"):
        PolicyAgent([])
