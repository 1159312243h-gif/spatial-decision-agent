from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.site_selection import get_site_selection_analysis_service
from app.main import app, create_app
from app.schemas.site_selection import SiteSelectionAnalysisCreate
from app.services.site_selection_service import (
    SiteSelectionRuntimeUnavailableError,
)
from practice.site_selection import (
    AgentState,
    AnalysisResult,
    AnalysisStatus,
    CandidateComparisonItem,
    CandidateComparisonReport,
    EvidenceStatus,
    GISEvidence,
    MissingMetricPolicy,
    POIEvidence,
    POIGroupScore,
    POIMetric,
    POIMetricScore,
    POIScoreReport,
    PolicyEvidence,
    ProjectIntakeSkill,
    ProjectRequest,
    ScoreDirection,
)


NOW = datetime(2026, 8, 18, 23, 59, tzinfo=timezone.utc)
client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def valid_payload() -> dict:
    return {
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


def valid_preflight_payload(project_type: str = "shopping_mall") -> dict:
    payload = valid_payload()
    payload["project_type"] = project_type
    payload["datasets"] = [
        {
            "dataset_id": "parcel-demo",
            "name": "测试地块数据",
            "source": "file",
            "location": "data/fixtures/parcel.geojson",
            "version": "fixture-2026.08.1",
            "crs": "EPSG:32651",
            "required_fields": ["parcel_id"],
            "updated_at": "2026-08-18T12:00:00Z",
        }
    ]
    return payload


def state_for(
    command: SiteSelectionAnalysisCreate,
    status: AnalysisStatus,
    *,
    errors: list[str] | None = None,
) -> AgentState:
    request = ProjectRequest(
        request_id="analysis-api-001",
        project_type=command.project_type,
        candidate_parcels=[
            parcel.to_domain() for parcel in command.candidate_parcels
        ],
        requested_at=NOW,
    )
    state = ProjectIntakeSkill().run(request)
    data = state.model_dump()
    data["status"] = status
    data["errors"] = errors or []
    if status is AnalysisStatus.COMPLETED:
        _add_completed_result(data, request)
    return AgentState.model_validate(data)


def _add_completed_result(data: dict, request: ProjectRequest) -> None:
    parcel_id = request.candidate_parcels[0].parcel_id
    score = 75.0
    metric_score = POIMetricScore(
        metric=POIMetric.COUNT,
        direction=ScoreDirection.HIGHER_IS_BETTER,
        raw_value=score,
        normalized_score=score,
        metric_weight=1,
        weighted_score=score,
        missing_policy=MissingMetricPolicy.BLOCK,
    )
    group_score = POIGroupScore(
        group_key="api_demo",
        query_id=f"query-{parcel_id}",
        source_dataset_id="poi-api-demo",
        metric_scores=[metric_score],
        group_score=score,
        profile_weight=1,
        weighted_score=score,
    )
    score_report = POIScoreReport(
        parcel_id=parcel_id,
        project_type=request.project_type,
        scoring_version="api-test-1.0",
        group_scores=[group_score],
        total_score=score,
    )
    gis = GISEvidence(parcel_id=parcel_id, status=EvidenceStatus.READY)
    poi = POIEvidence(
        parcel_id=parcel_id,
        status=EvidenceStatus.READY,
        soft_score=score,
        score_report=score_report,
    )
    policy = PolicyEvidence(
        parcel_id=parcel_id,
        status=EvidenceStatus.READY,
    )
    result = AnalysisResult(
        request_id=request.request_id,
        parcel_id=parcel_id,
        project_type=request.project_type,
        gis_evidence=gis,
        poi_evidence=poi,
        policy_evidence=policy,
        overall_soft_score=score,
    )
    comparison = CandidateComparisonReport(
        request_id=request.request_id,
        project_type=request.project_type,
        scoring_version="api-test-1.0",
        candidates=[
            CandidateComparisonItem(
                parcel_id=parcel_id,
                soft_rank=1,
                soft_score=score,
            )
        ],
    )
    data["gis_evidence"] = [gis.model_dump()]
    data["poi_evidence"] = [poi.model_dump()]
    data["policy_evidence"] = [policy.model_dump()]
    data["results"] = [result.model_dump()]
    data["comparison_report"] = comparison.model_dump()


class StaticService:
    def __init__(self, status: AnalysisStatus, errors: list[str] | None = None):
        self.status = status
        self.errors = errors
        self.commands: list[SiteSelectionAnalysisCreate] = []

    def analyze(self, command: SiteSelectionAnalysisCreate) -> AgentState:
        self.commands.append(command)
        return state_for(command, self.status, errors=self.errors)


class ExplodingService:
    def analyze(self, command: SiteSelectionAnalysisCreate) -> AgentState:
        raise RuntimeError("secret-token=must-not-leak")


class IncompleteCompletedService:
    def analyze(self, command: SiteSelectionAnalysisCreate) -> AgentState:
        state = ProjectIntakeSkill().run(
            ProjectRequest(
                request_id="analysis-api-incomplete",
                project_type=command.project_type,
                candidate_parcels=[
                    parcel.to_domain() for parcel in command.candidate_parcels
                ],
                requested_at=NOW,
            )
        )
        data = state.model_dump()
        data["status"] = AnalysisStatus.COMPLETED
        return AgentState.model_validate(data)


def override_service(service) -> None:
    app.dependency_overrides[get_site_selection_analysis_service] = (
        lambda: service
    )


def test_analysis_endpoint_returns_completed_response() -> None:
    service = StaticService(AnalysisStatus.COMPLETED)
    override_service(service)

    response = client.post("/site-selection/analyses", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "analysis-api-001"
    assert body["requested_at"] == "2026-08-18T23:59:00Z"
    assert body["project_type"] == "shopping_mall"
    assert body["status"] == "completed"
    assert len(body["results"]) == 1
    assert body["results"][0]["overall_soft_score"] == 75
    assert body["comparison_report"]["scoring_version"] == "api-test-1.0"
    assert body["errors"] == []
    assert service.commands[0].candidate_parcels[0].parcel_id == "A01"


def test_default_endpoint_reports_unconfigured_runtime() -> None:
    response = client.post("/site-selection/analyses", json=valid_payload())

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "runtime_unavailable"
    assert "shopping_mall" in detail["message"]
    assert detail["errors"] == []


def test_app_factory_uses_explicit_runtime_provider() -> None:
    class MaintenanceProvider:
        def resolve(self, project_type):
            raise SiteSelectionRuntimeUnavailableError(
                f"审核中的运行时：{project_type.value}"
            )

    isolated_client = TestClient(create_app(MaintenanceProvider()))

    response = isolated_client.post(
        "/site-selection/analyses",
        json=valid_payload(),
    )

    assert response.status_code == 503
    assert response.json()["detail"]["message"] == (
        "审核中的运行时：shopping_mall"
    )


def test_failed_workflow_maps_to_conflict_with_business_errors() -> None:
    service = StaticService(
        AnalysisStatus.FAILED,
        errors=["poi_scoring 失败：POI 评分缺少指标"],
    )
    override_service(service)

    response = client.post("/site-selection/analyses", json=valid_payload())

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "analysis_blocked"
    assert detail["request_id"] == "analysis-api-001"
    assert detail["errors"] == ["poi_scoring 失败：POI 评分缺少指标"]


def test_unknown_exception_is_sanitized() -> None:
    override_service(ExplodingService())

    response = client.post("/site-selection/analyses", json=valid_payload())

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "analysis_internal_error"
    assert detail["errors"] == ["RuntimeError"]
    assert "secret-token" not in response.text


def test_nonterminal_service_state_is_rejected() -> None:
    override_service(StaticService(AnalysisStatus.ANALYZING))

    response = client.post("/site-selection/analyses", json=valid_payload())

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "analysis_internal_error"
    assert detail["errors"] == ["unexpected_status=analyzing"]


def test_incomplete_completed_state_is_rejected() -> None:
    override_service(IncompleteCompletedService())

    response = client.post("/site-selection/analyses", json=valid_payload())

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "analysis_internal_error"
    assert detail["errors"] == ["incomplete_completed_state"]


def test_request_rejects_invalid_longitude() -> None:
    payload = valid_payload()
    payload["candidate_parcels"][0]["longitude"] = 181

    response = client.post("/site-selection/analyses", json=payload)

    assert response.status_code == 422


def test_request_rejects_duplicate_parcel_ids() -> None:
    payload = valid_payload()
    payload["candidate_parcels"].append(
        payload["candidate_parcels"][0].copy()
    )

    response = client.post("/site-selection/analyses", json=payload)

    assert response.status_code == 422


def test_request_rejects_unknown_fields() -> None:
    payload = valid_payload()
    payload["unreviewed_mode"] = True

    response = client.post("/site-selection/analyses", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "project_type",
    ["shopping_mall", "logistics_park"],
)
def test_preflight_routes_supported_project_types(project_type: str) -> None:
    response = client.post(
        "/site-selection/preflight",
        json=valid_preflight_payload(project_type),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["project_type"] == project_type
    assert body["profile"]["project_type"] == project_type
    assert body["missing_fields"] == []


def test_preflight_reports_all_top_level_missing_input() -> None:
    response = client.post("/site-selection/preflight", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_input"
    assert body["missing_fields"] == [
        "project_type",
        "candidate_parcels",
        "datasets",
    ]


def test_preflight_stops_unsupported_project_type() -> None:
    response = client.post(
        "/site-selection/preflight",
        json=valid_preflight_payload("office_tower"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unsupported"
    assert body["unsupported_value"] == "office_tower"
    assert body["profile"] is None


def test_preflight_names_missing_referenced_dataset() -> None:
    payload = valid_preflight_payload()
    payload["datasets"][0]["dataset_id"] = "another-dataset"

    response = client.post("/site-selection/preflight", json=payload)

    assert response.status_code == 200
    assert response.json()["missing_fields"] == ["datasets[parcel-demo]"]


def test_preflight_rejects_duplicate_dataset_ids() -> None:
    payload = valid_preflight_payload()
    payload["datasets"].append(payload["datasets"][0].copy())

    response = client.post("/site-selection/preflight", json=payload)

    assert response.status_code == 422
