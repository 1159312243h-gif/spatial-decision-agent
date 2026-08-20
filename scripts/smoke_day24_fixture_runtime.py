from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from mcp import Client
from practice.site_selection import ProjectType, load_fixture_candidate_catalog


EXPECTED_MCP_TOOLS = {
    "gis_feature_area",
    "gis_intersection_count",
    "gis_nearest_distance",
    "poi_nearby",
    "poi_metrics",
    "policy_search",
}


_CATALOG = load_fixture_candidate_catalog(
    PROJECT_ROOT / "data" / "fixtures" / "candidates.json"
)
PAYLOADS = {
    project_type.value: _CATALOG.payload_for(project_type)
    for project_type in ProjectType
}
EXPECTED_CANDIDATE_COUNT = sum(
    len(payload["candidate_parcels"])
    for payload in PAYLOADS.values()
)


class FixtureSmokeError(RuntimeError):
    """A deliberately safe error whose message may be printed by the smoke."""


def wait_for_run(
    client: httpx.Client,
    run: dict,
    *,
    timeout_seconds: float = 240,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while run["status"] in {"queued", "running"}:
        if time.monotonic() >= deadline:
            raise TimeoutError("site-selection run did not reach a terminal state")
        time.sleep(0.25)
        response = client.get(f"/site-selection/runs/{run['run_id']}")
        response.raise_for_status()
        run = response.json()
    return run


def smoke_api(api_url: str) -> list[str]:
    explanation_statuses = []
    with httpx.Client(base_url=api_url, timeout=90) as client:
        health = client.get("/health")
        health.raise_for_status()
        for project_type, payload in PAYLOADS.items():
            response = client.post(
                "/site-selection/runs",
                json=payload,
                headers={"Idempotency-Key": f"day24-smoke-{uuid4()}"},
            )
            response.raise_for_status()
            run = wait_for_run(client, response.json())
            if run["status"] != "completed":
                raise FixtureSmokeError(
                    f"stage=worker; project_type={project_type}; "
                    f"run_id={run.get('run_id')}; status={run.get('status')}; "
                    f"run_error={run.get('error') or 'none'}"
                )
            analysis = run["analysis"]
            expected_results = len(payload["candidate_parcels"])
            if len(analysis["results"]) != expected_results:
                raise FixtureSmokeError(
                    f"stage=analysis; project_type={project_type}; "
                    "result count mismatch"
                )
            comparison = analysis["comparison_report"]
            if (
                not comparison
                or len(comparison["candidates"]) != expected_results
            ):
                raise FixtureSmokeError(
                    f"stage=analysis; project_type={project_type}; "
                    "comparison is incomplete"
                )
            for result in analysis["results"]:
                if not result["gis_evidence"]["metrics"]:
                    raise FixtureSmokeError("stage=analysis; GIS evidence is missing")
                if not result["poi_evidence"]["feature_sets"]:
                    raise FixtureSmokeError("stage=analysis; POI evidence is missing")
                if not result["policy_evidence"]["evaluated_rule_ids"]:
                    raise FixtureSmokeError("stage=analysis; rule IDs are missing")
                sources = [
                    item["source"]
                    for item in result["poi_evidence"]["feature_sets"]
                ]
                if any(not source.get("queried_at") for source in sources):
                    raise FixtureSmokeError(
                        "stage=analysis; POI queried_at is missing"
                    )
            explanation_statuses.append(run["explanation"]["status"])
            report = client.get(run["report_url"])
            report.raise_for_status()
            if not report.content.startswith(b"PK"):
                raise FixtureSmokeError(
                    f"stage=report; project_type={project_type}; "
                    "artifact is not DOCX"
                )
    return explanation_statuses


async def smoke_mcp(mcp_url: str) -> None:
    async with Client(mcp_url) as client:
        listed = await client.list_tools()
    actual = {tool.name for tool in listed.tools}
    if actual != EXPECTED_MCP_TOOLS:
        raise FixtureSmokeError(
            f"MCP tool mismatch: missing={sorted(EXPECTED_MCP_TOOLS - actual)}, "
            f"unexpected={sorted(actual - EXPECTED_MCP_TOOLS)}"
        )


def main() -> int:
    api_url = os.getenv("SITE_SELECTION_API_URL", "http://127.0.0.1:8000")
    mcp_url = os.getenv("SITE_SELECTION_MCP_URL", "http://127.0.0.1:8001/mcp")
    try:
        statuses = smoke_api(api_url)
        asyncio.run(smoke_mcp(mcp_url))
    except FixtureSmokeError as exc:
        print(f"Day24 fixture smoke FAILED: {exc}")
        return 1
    except Exception as exc:
        print(
            "Day24 fixture smoke FAILED: "
            f"stage=unexpected; error_type={type(exc).__name__}"
        )
        return 1
    print(
        f"Day24 fixture smoke OK: project_types={len(PAYLOADS)}, "
        f"candidates={EXPECTED_CANDIDATE_COUNT}, reports={len(statuses)}, "
        "mcp_tools=6, "
        "explanation_statuses="
        + ",".join(statuses)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
