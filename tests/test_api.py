from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app, create_app


client = TestClient(app)


def valid_chat_payload() -> dict:
    return {
        "question": "请比较两个候选地块的交通和生态条件",
        "project_type": "logistics_park",
        "candidate_parcels": [
            {
                "parcel_id": "P001",
                "name": "城北地块",
            },
            {
                "parcel_id": "P002",
                "name": "临港地块",
            },
        ],
    }


def test_health_success() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
    }


def test_application_closes_configured_runtime_resource() -> None:
    calls = []
    application = create_app(resource_closer=lambda: calls.append("closed"))

    with TestClient(application) as runtime_client:
        assert runtime_client.get("/health").status_code == 200
        assert calls == []

    assert calls == ["closed"]


def test_create_document_success() -> None:
    payload = {
        "filename": "land_policy.pdf",
        "source": "自然资源部门",
        "document_type": "planning_policy",
    }

    response = client.post("/documents", json=payload)

    assert response.status_code == 201

    body = response.json()
    UUID(body["document_id"])
    assert body["status"] == "accepted"
    assert body["metadata"] == payload


def test_create_document_missing_field() -> None:
    response = client.post(
        "/documents",
        json={
            "filename": "land_policy.pdf",
            "document_type": "planning_policy",
        },
    )

    assert response.status_code == 422


def test_chat_success() -> None:
    response = client.post("/chat", json=valid_chat_payload())

    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["received_candidates"] == 2
    assert body["scenario_version"]["project_type"] == "logistics_park"
    assert "请确认该版本" in body["answer"]


def test_chat_confirms_region_scenario_and_returns_discovery_request() -> None:
    proposed = client.post(
        "/chat",
        json={
            "question": "在上海市徐汇区开咖啡店，范围 4 公里，找 8 个候选点",
        },
    )
    assert proposed.status_code == 200
    pending = proposed.json()

    confirmed = client.post(
        f"/chat/{pending['session_id']}/confirm",
        json={
            "version_id": pending["scenario_version"]["version_id"],
            "confirmed_by": "api-test-user",
        },
    )

    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "confirmed"
    assert body["discovery_request"]["project_type"] == "coffee_shop"
    assert body["scenario_version"]["confirmed_by"] == "api-test-user"
    recovered = client.get(f"/chat/{pending['session_id']}")
    assert recovered.status_code == 200
    assert recovered.json()["active_version_id"] == (
        pending["scenario_version"]["version_id"]
    )


def test_chat_rejects_blank_question() -> None:
    payload = valid_chat_payload()
    payload["question"] = "   "

    response = client.post("/chat", json=payload)

    assert response.status_code == 422


def test_chat_rejects_invalid_project_type() -> None:
    payload = valid_chat_payload()
    payload["project_type"] = "residential"

    response = client.post("/chat", json=payload)

    assert response.status_code == 422
