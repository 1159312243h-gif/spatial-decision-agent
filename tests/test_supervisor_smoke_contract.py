from scripts.smoke_supervisor_runtime import (
    REQUIRED_EVENTS,
    resume_phase,
    start_phase,
)


def test_supervisor_smoke_supports_restart_between_phases() -> None:
    calls = []
    analysis_submitted = False
    session = {
        "session_id": "supervisor-smoke-001",
        "checkpoint_id": "checkpoint-001",
        "status": "awaiting_confirmation",
        "discovery_report": {
            "candidates": [
                {"candidate": {"parcel_id": "candidate-001"}},
                {"candidate": {"parcel_id": "candidate-002"}},
            ]
        },
    }

    def requester(method, url, payload, expected):
        nonlocal analysis_submitted
        calls.append((method, url, payload, expected))
        if url.endswith("/events"):
            return 200, {
                "events": [
                    {"event_type": event_type} for event_type in REQUIRED_EVENTS
                ]
            }
        if url.endswith("/confirm") and payload["selected_candidate_ids"] == [
            "outside-discovery"
        ]:
            return 409, {
                "detail": {"code": "supervisor_confirmation_blocked"}
            }
        if url.endswith("/confirm"):
            analysis_submitted = True
            return 202, {
                **session,
                "status": "awaiting_analysis",
                "analysis_run_id": "run-supervisor-001",
            }
        if method == "GET" and analysis_submitted:
            return 200, {
                **session,
                "status": "completed",
                "analysis_run_id": "run-supervisor-001",
                "analysis": {"results": [{"parcel_id": "candidate-001"}]},
            }
        return (201 if method == "POST" else 200), session

    state = start_phase("http://api.test", requester)
    completed = resume_phase("http://api.test", state, requester)

    assert state == {
        "session_id": "supervisor-smoke-001",
        "checkpoint_id": "checkpoint-001",
        "selected_candidate_ids": ["candidate-001", "candidate-002"],
    }
    assert completed["status"] == "completed"
    assert [call[0] for call in calls] == [
        "POST",
        "GET",
        "POST",
        "POST",
        "GET",
        "GET",
    ]
