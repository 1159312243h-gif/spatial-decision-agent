from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.site_selection_supervisor import (
    SiteSelectionSupervisorApplicationService,
)
from practice.site_selection import SupervisorSessionNotFoundError
from practice.site_selection.storage import RunState, RunStatus, SupervisorSessionEvent
from tests.test_site_selection_supervisor import _request, _supervisor


NOW = datetime(2026, 8, 21, 6, 30, tzinfo=timezone.utc)


class MemorySupervisorCoordinator:
    def __init__(self) -> None:
        self.active: dict[str, str] = {}
        self.events: dict[str, list[SupervisorSessionEvent]] = {}
        self.locked: set[str] = set()

    def activate(self, session_id: str, checkpoint_id: str) -> None:
        self.active[session_id] = checkpoint_id

    def is_active(self, session_id: str) -> bool:
        return session_id in self.active

    def ttl(self, session_id: str) -> int:
        return 7_200 if session_id in self.active else -2

    def acquire_transition(self, session_id: str) -> str | None:
        if session_id in self.locked:
            return None
        self.locked.add(session_id)
        return "lock-token"

    def release_transition(self, session_id: str, token: str) -> None:
        assert token == "lock-token"
        self.locked.discard(session_id)

    def append_event(self, event: SupervisorSessionEvent) -> None:
        self.events.setdefault(event.session_id, []).append(event)

    def list_events(self, session_id: str) -> list[SupervisorSessionEvent]:
        return list(self.events.get(session_id, []))

    def deactivate(self, session_id: str) -> None:
        self.active.pop(session_id, None)
        self.locked.discard(session_id)


class FailingSecondEventCoordinator(MemorySupervisorCoordinator):
    def append_event(self, event: SupervisorSessionEvent) -> None:
        if self.events.get(event.session_id):
            raise RuntimeError("audit unavailable")
        super().append_event(event)


class MutableRunService:
    def __init__(self, run_id: str, session_id: str) -> None:
        self.state = RunState(
            run_id=run_id,
            status=RunStatus.QUEUED,
            updated_at=NOW,
            details={"supervisor_session_id": session_id},
        )

    def get_run(self, run_id: str) -> RunState:
        assert run_id == self.state.run_id
        return self.state

    def complete(self, analysis) -> None:
        self.state = RunState(
            run_id=self.state.run_id,
            status=RunStatus.COMPLETED,
            updated_at=NOW,
            details={
                "supervisor_session_id": "supervisor-api-001",
                "analysis": analysis.model_dump(mode="json"),
            },
        )

    def terminate(self, status: RunStatus) -> None:
        self.state = RunState(
            run_id=self.state.run_id,
            status=status,
            updated_at=NOW,
            error=(
                "选址 Worker 终态"
                if status in {RunStatus.FAILED, RunStatus.TIMED_OUT}
                else None
            ),
            details={
                "supervisor_session_id": "supervisor-api-001",
                "worker_error_type": "WorkerTerminalError",
            },
        )


def configured_client():
    supervisor, _, analysis = _supervisor()
    run_service = MutableRunService(
        analysis.run_id,
        "supervisor-api-001",
    )
    service = SiteSelectionSupervisorApplicationService(
        supervisor,
        MemorySupervisorCoordinator(),
        run_service,
        clock=lambda: NOW,
        session_id_factory=lambda: "supervisor-api-001",
    )
    return TestClient(create_app(supervisor_service=service)), run_service, analysis


def test_supervisor_api_returns_202_then_reconciles_completed_run() -> None:
    client, run_service, analysis = configured_client()
    started_response = client.post(
        "/site-selection/supervisor/sessions",
        json=_request().model_dump(mode="json"),
    )

    assert started_response.status_code == 201
    started = started_response.json()
    assert started["status"] == "awaiting_confirmation"
    assert started["session_ttl_seconds"] == 7_200

    rejected = client.post(
        "/site-selection/supervisor/sessions/supervisor-api-001/confirm",
        json={
            "expected_checkpoint_id": started["checkpoint_id"],
            "selected_candidate_ids": ["outside-discovery"],
            "reviewer_id": "planner-001",
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "supervisor_confirmation_blocked"

    selected = [
        item["candidate"]["parcel_id"]
        for item in started["discovery_report"]["candidates"][:2]
    ]
    submitted_response = client.post(
        "/site-selection/supervisor/sessions/supervisor-api-001/confirm",
        json={
            "expected_checkpoint_id": started["checkpoint_id"],
            "selected_candidate_ids": selected,
            "reviewer_id": "planner-001",
            "note": "保留两个差异化候选",
        },
    )

    assert submitted_response.status_code == 202
    submitted = submitted_response.json()
    assert submitted["status"] == "awaiting_analysis"
    assert submitted["analysis_run_id"] == analysis.run_id
    assert submitted["analysis_run_status"] == "queued"
    assert submitted["analysis"] is None

    run_service.complete(analysis.completed_state())
    completed_response = client.get(
        "/site-selection/supervisor/sessions/supervisor-api-001"
    )
    assert completed_response.status_code == 200
    completed = completed_response.json()
    assert completed["status"] == "completed"
    assert completed["analysis_run_status"] == "completed"
    assert completed["analysis"]["status"] == "completed"
    assert [item["parcel_id"] for item in completed["analysis"]["results"]] == selected
    assert completed["confirmation"]["confirmed_at"] == "2026-08-21T06:30:00Z"

    events = client.get(
        "/site-selection/supervisor/sessions/supervisor-api-001/events"
    ).json()["events"]
    assert [item["event_type"] for item in events] == [
        "started",
        "awaiting_confirmation",
        "confirmation_rejected",
        "confirmed",
        "analysis_submitted",
        "analysis_completed",
        "completed",
    ]
    assert events[-2]["analysis_run_id"] == analysis.run_id


def test_supervisor_api_rejects_stale_checkpoint_and_unconfigured_runtime() -> None:
    client, _, _ = configured_client()
    started = client.post(
        "/site-selection/supervisor/sessions",
        json=_request().model_dump(mode="json"),
    ).json()

    stale = client.post(
        "/site-selection/supervisor/sessions/supervisor-api-001/confirm",
        json={
            "expected_checkpoint_id": "stale-checkpoint",
            "selected_candidate_ids": [
                started["discovery_report"]["candidates"][0]["candidate"]["parcel_id"]
            ],
            "reviewer_id": "planner-001",
        },
    )
    unavailable = TestClient(create_app()).post(
        "/site-selection/supervisor/sessions",
        json=_request().model_dump(mode="json"),
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "supervisor_conflict"
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "supervisor_unavailable"


@pytest.mark.parametrize(
    ("run_status", "event_type"),
    [
        (RunStatus.FAILED, "analysis_failed"),
        (RunStatus.CANCELLED, "analysis_cancelled"),
        (RunStatus.TIMED_OUT, "analysis_timed_out"),
    ],
)
def test_supervisor_api_reconciles_non_success_terminal_state_once(
    run_status,
    event_type,
) -> None:
    client, run_service, _ = configured_client()
    started = client.post(
        "/site-selection/supervisor/sessions",
        json=_request().model_dump(mode="json"),
    ).json()
    selected = [
        started["discovery_report"]["candidates"][0]["candidate"]["parcel_id"]
    ]
    submitted = client.post(
        "/site-selection/supervisor/sessions/supervisor-api-001/confirm",
        json={
            "expected_checkpoint_id": started["checkpoint_id"],
            "selected_candidate_ids": selected,
            "reviewer_id": "planner-001",
        },
    )
    assert submitted.status_code == 202
    run_service.terminate(run_status)

    first = client.get(
        "/site-selection/supervisor/sessions/supervisor-api-001"
    ).json()
    second = client.get(
        "/site-selection/supervisor/sessions/supervisor-api-001"
    ).json()

    assert first == second
    assert first["status"] == run_status.value
    assert first["analysis_run_status"] == run_status.value
    assert first["analysis_error_type"] == "WorkerTerminalError"
    event_types = [
        item["event_type"]
        for item in client.get(
            "/site-selection/supervisor/sessions/supervisor-api-001/events"
        ).json()["events"]
    ]
    assert event_types.count(event_type) == 1
    assert "completed" not in event_types


def test_supervisor_start_compensates_checkpoint_and_lease_on_audit_failure() -> None:
    supervisor, _, _ = _supervisor()
    coordinator = FailingSecondEventCoordinator()
    service = SiteSelectionSupervisorApplicationService(
        supervisor,
        coordinator,
        session_id_factory=lambda: "supervisor-cleanup-001",
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.start(_request())

    assert coordinator.is_active("supervisor-cleanup-001") is False
    with pytest.raises(SupervisorSessionNotFoundError):
        supervisor.get("supervisor-cleanup-001")
