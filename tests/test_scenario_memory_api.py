from fastapi.testclient import TestClient

from app.main import create_app


def test_memory_api_round_trip_and_delete() -> None:
    with TestClient(create_app()) as client:
        proposed = client.post(
            "/chat",
            json={
                "question": (
                    "在上海市徐汇区开便利店，范围 3 公里，"
                    "候选数量 10 个，最小间距 900 米"
                ),
                "actor_id": "api-planner-001",
                "memory_mode": "apply_defaults",
            },
        )
        assert proposed.status_code == 200
        payload = proposed.json()
        confirmed = client.post(
            f"/chat/{payload['session_id']}/confirm",
            json={
                "version_id": payload["scenario_version"]["version_id"],
                "confirmed_by": "api-planner-001",
                "remember_preferences": True,
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["memory_saved"] is True

        memory = client.get("/site-selection/memory/api-planner-001")
        assert memory.status_code == 200
        assert len(memory.json()["preferences"]) == 1
        assert len(memory.json()["recent_episodes"]) == 1

        deleted = client.delete("/site-selection/memory/api-planner-001")
        assert deleted.status_code == 200
        assert deleted.json()["deleted_preferences"] == 1
        assert deleted.json()["deleted_episodes"] == 1


def test_memory_api_rejects_unsafe_actor_id() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/site-selection/memory/not%20safe")

    assert response.status_code == 422
