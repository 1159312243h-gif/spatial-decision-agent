from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx

from scripts.smoke_fixture_runtime import PAYLOADS, wait_for_run


REQUIRED_EVENTS = {"created", "enqueued", "started", "completed"}


class AsyncSmokeError(RuntimeError):
    def __init__(
        self,
        stage: str,
        message: str,
        *,
        http_status: int | None = None,
        run_id: str | None = None,
        status: str | None = None,
        run_error: str | None = None,
        event_types: set[str] | None = None,
    ) -> None:
        fields = [f"stage={stage}", f"message={message}"]
        if http_status is not None:
            fields.append(f"http_status={http_status}")
        if run_id is not None:
            fields.append(f"run_id={run_id}")
        if status is not None:
            fields.append(f"status={status}")
        if run_error is not None:
            fields.append(f"run_error={run_error}")
        if event_types is not None:
            fields.append(f"events={','.join(sorted(event_types)) or 'none'}")
        super().__init__("; ".join(fields))


def smoke_async_runtime(api_url: str) -> tuple[str, int]:
    with httpx.Client(base_url=api_url, timeout=90) as client:
        response = client.post(
            "/site-selection/runs",
            json=PAYLOADS["shopping_mall"],
            headers={"Idempotency-Key": f"async-smoke-{uuid4()}"},
        )
        if response.status_code != 202:
            raise AsyncSmokeError(
                "create",
                "async run creation did not return HTTP 202",
                http_status=response.status_code,
            )
        initial = response.json()
        if initial["status"] not in {"queued", "running"}:
            raise AsyncSmokeError(
                "create",
                "async run did not enter queued or running state",
                run_id=initial.get("run_id"),
                status=initial.get("status"),
                run_error=initial.get("error"),
            )

        try:
            run = wait_for_run(client, initial)
        except TimeoutError as exc:
            raise AsyncSmokeError(
                "poll",
                "async run did not reach a terminal state",
                run_id=initial.get("run_id"),
                status=initial.get("status"),
            ) from exc

        events_response = client.get(
            f"/site-selection/runs/{run['run_id']}/events"
        )
        if events_response.status_code != 200:
            raise AsyncSmokeError(
                "events",
                "event endpoint did not return HTTP 200",
                http_status=events_response.status_code,
                run_id=run.get("run_id"),
                status=run.get("status"),
                run_error=run.get("error"),
            )
        event_types = {
            event["event_type"]
            for event in events_response.json()["events"]
        }
        if run["status"] != "completed" or run.get("analysis") is None:
            raise AsyncSmokeError(
                "worker",
                "async worker did not complete the analysis",
                run_id=run.get("run_id"),
                status=run.get("status"),
                run_error=run.get("error"),
                event_types=event_types,
            )
        missing = REQUIRED_EVENTS - event_types
        if missing:
            raise AsyncSmokeError(
                "events",
                "async run event chain is incomplete; missing="
                + ",".join(sorted(missing)),
                run_id=run.get("run_id"),
                status=run.get("status"),
                event_types=event_types,
            )

        report_response = client.get(run["report_url"])
        if report_response.status_code != 200:
            raise AsyncSmokeError(
                "report",
                "report endpoint did not return HTTP 200",
                http_status=report_response.status_code,
                run_id=run.get("run_id"),
                status=run.get("status"),
                event_types=event_types,
            )
        if not report_response.content.startswith(b"PK"):
            raise AsyncSmokeError(
                "report",
                "async report is not a DOCX artifact",
                run_id=run.get("run_id"),
                status=run.get("status"),
                event_types=event_types,
            )
        return run["run_id"], len(event_types)


def main() -> int:
    api_url = os.getenv(
        "SITE_SELECTION_API_URL",
        "http://127.0.0.1:8000",
    )
    try:
        run_id, event_count = smoke_async_runtime(api_url)
    except AsyncSmokeError as exc:
        print(f"Async smoke FAILED: {exc}")
        return 1
    except Exception as exc:
        print(
            "Async smoke FAILED: "
            f"stage=unexpected; error_type={type(exc).__name__}"
        )
        return 1
    print(
        "Async smoke OK: "
        f"run_id={run_id}, events={event_count}, report=docx"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
