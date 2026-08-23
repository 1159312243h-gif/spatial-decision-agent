from fastapi.testclient import TestClient

from app.api.site_selection import get_site_selection_run_service
from app.main import app
from app.services.site_selection_artifacts import FileSystemSiteSelectionReportStore
from app.services.site_selection_queue import QueuedSiteSelectionRunService
from practice.site_selection import CandidateDiscoverySnapshotNotFoundError
from tests.test_site_selection_api import valid_payload
from tests.test_site_selection_async_queue import FakeJobQueue
from tests.test_site_selection_run_service import command, preview_command, service


client = TestClient(app)


def run_payload() -> dict:
    return command().model_dump(mode="json")


def setup_function() -> None:
    app.dependency_overrides.clear()


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_run_api_creates_reads_and_lists_events() -> None:
    run_service = service(run_ids=["run-api-001"])
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: run_service
    )

    created = client.post(
        "/site-selection/runs",
        json=run_payload(),
        headers={"Idempotency-Key": "api-request-001"},
    )
    fetched = client.get("/site-selection/runs/run-api-001")
    events = client.get("/site-selection/runs/run-api-001/events")

    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    assert created.json()["analysis"]["status"] == "completed"
    assert created.json()["explanation"]["status"] == "not_configured"
    assert created.json()["human_review"]["status"] == "pending"
    assert created.json()["trace"][-1]["stage"] == "total"
    assert fetched.status_code == 200
    assert fetched.json() == created.json()
    assert [item["event_type"] for item in events.json()["events"]] == [
        "created",
        "started",
        "completed",
    ]


def test_run_api_acknowledges_human_review_without_approval() -> None:
    run_service = service(run_ids=["run-review-001"])
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: run_service
    )
    client.post("/site-selection/runs", json=run_payload())

    response = client.post(
        "/site-selection/runs/run-review-001/human-review/acknowledge",
        json={"note": "Reviewed evidence only."},
    )
    events = client.get("/site-selection/runs/run-review-001/events")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["human_review"]["status"] == "acknowledged"
    assert events.json()["events"][-1]["event_type"] == (
        "human_review_acknowledged"
    )
    assert events.json()["events"][-1]["details"]["boundary"] == (
        "acknowledgement_not_compliance_approval"
    )


def test_run_api_returns_and_downloads_report(tmp_path) -> None:
    run_service = service(
        run_ids=["run-report-001"],
        report_store=FileSystemSiteSelectionReportStore(tmp_path),
    )
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: run_service
    )

    created = client.post("/site-selection/runs", json=run_payload())
    report = client.get(created.json()["report_url"])

    assert created.status_code == 201
    assert created.json()["report_sha256"] is not None
    assert report.status_code == 200
    assert report.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    assert report.content.startswith(b"PK")


def test_run_api_reuses_idempotency_key() -> None:
    run_service = service(run_ids=["run-api-001", "run-api-002"])
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: run_service
    )
    headers = {"Idempotency-Key": "api-request-002"}

    first = client.post("/site-selection/runs", json=run_payload(), headers=headers)
    second = client.post("/site-selection/runs", json=run_payload(), headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.json()["run_id"] == second.json()["run_id"] == "run-api-001"


def test_run_api_rejects_idempotency_key_reuse_for_different_request() -> None:
    run_service = service(run_ids=["run-api-001", "run-api-002"])
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: run_service
    )
    headers = {"Idempotency-Key": "api-request-conflict"}
    changed = run_payload()
    changed["candidate_parcels"][0]["longitude"] = 121.48

    first = client.post("/site-selection/runs", json=run_payload(), headers=headers)
    second = client.post("/site-selection/runs", json=changed, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "idempotency_conflict"


def test_run_api_returns_conflict_for_expired_discovery_snapshot() -> None:
    class ExpiredSnapshotService:
        def create_run(self, command, *, idempotency_key=None):
            del command, idempotency_key
            raise CandidateDiscoverySnapshotNotFoundError(
                "候选发现证据快照不存在或已过期：expired-snapshot"
            )

    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: ExpiredSnapshotService()
    )
    payload = run_payload()
    payload["poi_evidence_snapshot_id"] = "expired-snapshot"

    response = client.post("/site-selection/runs", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "analysis_blocked"
    assert "不存在或已过期" in response.json()["detail"]["message"]


def test_run_api_returns_not_found() -> None:
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: service()
    )

    response = client.get("/site-selection/runs/missing-run")

    assert response.status_code == 404


def test_async_run_api_returns_202_and_supports_cancellation() -> None:
    run_service = QueuedSiteSelectionRunService(
        service(run_ids=["run-async-api-001"]),
        FakeJobQueue(),
    )
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: run_service
    )

    created = client.post("/site-selection/runs", json=run_payload())
    cancelled = client.post(
        "/site-selection/runs/run-async-api-001/cancel"
    )

    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    assert created.json()["analysis"] is None
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_cancel_api_rejects_completed_run_and_returns_not_found() -> None:
    run_service = service(run_ids=["run-completed-api-001"])
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: run_service
    )
    client.post("/site-selection/runs", json=run_payload())

    conflict = client.post(
        "/site-selection/runs/run-completed-api-001/cancel"
    )
    missing = client.post("/site-selection/runs/missing-run/cancel")

    assert conflict.status_code == 409
    assert missing.status_code == 404


def test_poi_preview_reports_cache_hit() -> None:
    run_service = service()
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: run_service
    )
    payload = preview_command().model_dump(mode="json")

    first = client.post("/site-selection/poi/preview", json=payload)
    second = client.post("/site-selection/poi/preview", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["feature_set"] == first.json()["feature_set"]

    payload["refresh"] = True
    refreshed = client.post("/site-selection/poi/preview", json=payload)

    assert refreshed.status_code == 200
    assert refreshed.json()["cached"] is False


def test_default_run_and_preview_endpoints_fail_closed() -> None:
    run_response = client.post("/site-selection/runs", json=valid_payload())
    preview_response = client.post(
        "/site-selection/poi/preview",
        json=preview_command().model_dump(mode="json"),
    )

    assert run_response.status_code == 503
    assert preview_response.status_code == 503


def test_default_report_endpoint_fails_closed() -> None:
    response = client.get("/site-selection/runs/run-001/report")

    assert response.status_code == 503


def test_run_api_rejects_unsafe_run_id_and_blank_idempotency_key() -> None:
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: service()
    )

    unsafe_run = client.get("/site-selection/runs/bad$run")
    blank_key = client.post(
        "/site-selection/runs",
        json=run_payload(),
        headers={"Idempotency-Key": " "},
    )

    assert unsafe_run.status_code == 422
    assert blank_key.status_code == 422
