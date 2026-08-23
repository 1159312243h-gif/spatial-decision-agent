from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_STATE_FILE = Path("artifacts/supervisor-smoke-state.json")
REQUIRED_EVENTS = [
    "started",
    "awaiting_confirmation",
    "confirmation_rejected",
    "confirmed",
    "analysis_submitted",
    "analysis_completed",
    "completed",
]


class SupervisorSmokeError(RuntimeError):
    pass


Requester = Callable[[str, str, dict[str, Any] | None, set[int]], tuple[int, dict]]


def start_phase(api_url: str, requester: Requester) -> dict:
    status, body = requester(
        "POST",
        f"{api_url}/site-selection/supervisor/sessions",
        {
            "request_id": "supervisor-smoke-discovery-001",
            "project_type": "coffee_shop",
            "bounds": {
                "west": 121.29,
                "south": 31.14,
                "east": 121.37,
                "north": 31.19,
            },
            "max_candidates": 6,
            "minimum_separation_m": 600,
        },
        {201},
    )
    del status
    if body.get("status") != "awaiting_confirmation":
        raise SupervisorSmokeError("Supervisor 未停在候选确认节点")
    candidates = body.get("discovery_report", {}).get("candidates", [])
    if len(candidates) < 2:
        raise SupervisorSmokeError("Supervisor Smoke 至少需要两个候选")
    return {
        "session_id": body["session_id"],
        "checkpoint_id": body["checkpoint_id"],
        "selected_candidate_ids": [
            item["candidate"]["parcel_id"] for item in candidates[:2]
        ],
    }


def resume_phase(api_url: str, state: dict, requester: Requester) -> dict:
    session_id = state["session_id"]
    _, recovered = requester(
        "GET",
        f"{api_url}/site-selection/supervisor/sessions/{session_id}",
        None,
        {200},
    )
    if recovered.get("checkpoint_id") != state["checkpoint_id"]:
        raise SupervisorSmokeError("API 重启后恢复的 checkpoint_id 不一致")

    rejected_status, rejected = requester(
        "POST",
        f"{api_url}/site-selection/supervisor/sessions/{session_id}/confirm",
        {
            "expected_checkpoint_id": state["checkpoint_id"],
            "selected_candidate_ids": ["outside-discovery"],
            "reviewer_id": "supervisor-smoke",
        },
        {409},
    )
    del rejected_status
    if rejected.get("detail", {}).get("code") != (
        "supervisor_confirmation_blocked"
    ):
        raise SupervisorSmokeError("非法候选未按业务阻断返回")

    _, submitted = requester(
        "POST",
        f"{api_url}/site-selection/supervisor/sessions/{session_id}/confirm",
        {
            "expected_checkpoint_id": state["checkpoint_id"],
            "selected_candidate_ids": state["selected_candidate_ids"],
            "reviewer_id": "supervisor-smoke",
            "note": "durable checkpoint smoke",
        },
        {200, 202},
    )
    completed = submitted
    for _ in range(90):
        if completed.get("status") != "awaiting_analysis":
            break
        _, completed = requester(
            "GET",
            f"{api_url}/site-selection/supervisor/sessions/{session_id}",
            None,
            {200},
        )
        if completed.get("status") == "awaiting_analysis":
            time.sleep(2)
    if completed.get("status") != "completed" or not completed.get("analysis"):
        raise SupervisorSmokeError("Supervisor 恢复后未完成正式分析")

    _, events = requester(
        "GET",
        f"{api_url}/site-selection/supervisor/sessions/{session_id}/events",
        None,
        {200},
    )
    event_types = [item["event_type"] for item in events.get("events", [])]
    if event_types != REQUIRED_EVENTS:
        raise SupervisorSmokeError(
            f"Supervisor 审计事件链不完整：{event_types}"
        )
    return completed


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    expected_statuses: set[int],
) -> tuple[int, dict]:
    data = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=180) as response:
            status = response.status
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        status = exc.code
        body = json.loads(exc.read().decode("utf-8"))
    if status not in expected_statuses:
        raise SupervisorSmokeError(
            f"{method} {url} 返回 {status}，期望 {sorted(expected_statuses)}"
        )
    return status, body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument(
        "--phase",
        choices=("all", "start", "resume"),
        default="all",
    )
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    args = parser.parse_args()
    api_url = args.api_url.rstrip("/")

    if args.phase in {"all", "start"}:
        state = start_phase(api_url, request_json)
        args.state_file.parent.mkdir(parents=True, exist_ok=True)
        args.state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            "Supervisor start OK: "
            f"session_id={state['session_id']}, state={args.state_file.resolve()}"
        )
        if args.phase == "start":
            return
    else:
        state = json.loads(args.state_file.read_text(encoding="utf-8"))

    completed = resume_phase(api_url, state, request_json)
    print(
        "Supervisor resume OK: "
        f"session_id={completed['session_id']}, "
        f"results={len(completed['analysis']['results'])}, "
        f"events={len(REQUIRED_EVENTS)}"
    )


if __name__ == "__main__":
    main()
