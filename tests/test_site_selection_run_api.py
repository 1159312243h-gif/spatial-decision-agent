from fastapi.testclient import TestClient

from app.api.site_selection import get_site_selection_run_service
from app.main import app
from tests.test_site_selection_api import valid_payload
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
    assert fetched.status_code == 200
    assert fetched.json() == created.json()
    assert [item["event_type"] for item in events.json()["events"]] == [
        "created",
        "started",
        "completed",
    ]


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


def test_run_api_returns_not_found() -> None:
    app.dependency_overrides[get_site_selection_run_service] = (
        lambda: service()
    )

    response = client.get("/site-selection/runs/missing-run")

    assert response.status_code == 404


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
