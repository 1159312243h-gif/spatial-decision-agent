from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from mcp import Client


EXPECTED_MCP_TOOLS = {
    "gis_feature_area",
    "gis_intersection_count",
    "gis_nearest_distance",
    "poi_nearby",
    "poi_metrics",
    "policy_search",
}


PAYLOADS = {
    "shopping_mall": {
        "project_type": "shopping_mall",
        "candidate_parcels": [
            {
                "parcel_id": "MALL-A01",
                "name": "商场候选 A",
                "longitude": 121.4700,
                "latitude": 31.2300,
                "geometry_dataset_id": "demo-mall-candidates",
            },
            {
                "parcel_id": "MALL-A02",
                "name": "商场候选 B",
                "longitude": 121.4850,
                "latitude": 31.2350,
                "geometry_dataset_id": "demo-mall-candidates",
            },
        ],
    },
    "logistics_park": {
        "project_type": "logistics_park",
        "candidate_parcels": [
            {
                "parcel_id": "LOG-A01",
                "name": "物流园候选 A",
                "longitude": 121.5200,
                "latitude": 31.2400,
                "geometry_dataset_id": "demo-logistics-candidates",
            },
            {
                "parcel_id": "LOG-A02",
                "name": "物流园候选 B",
                "longitude": 121.5600,
                "latitude": 31.2550,
                "geometry_dataset_id": "demo-logistics-candidates",
            },
        ],
    },
}


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
            run = response.json()
            if run["status"] != "completed":
                raise RuntimeError(f"{project_type} run did not complete")
            analysis = run["analysis"]
            if len(analysis["results"]) != 2:
                raise RuntimeError(f"{project_type} result count mismatch")
            comparison = analysis["comparison_report"]
            if not comparison or len(comparison["candidates"]) != 2:
                raise RuntimeError(f"{project_type} comparison is incomplete")
            for result in analysis["results"]:
                if not result["gis_evidence"]["metrics"]:
                    raise RuntimeError("GIS evidence is missing")
                if not result["poi_evidence"]["feature_sets"]:
                    raise RuntimeError("POI evidence is missing")
                if not result["policy_evidence"]["evaluated_rule_ids"]:
                    raise RuntimeError("rule IDs are missing")
                sources = [
                    item["source"]
                    for item in result["poi_evidence"]["feature_sets"]
                ]
                if any(not source.get("queried_at") for source in sources):
                    raise RuntimeError("POI queried_at is missing")
            explanation_statuses.append(run["explanation"]["status"])
            report = client.get(run["report_url"])
            report.raise_for_status()
            if not report.content.startswith(b"PK"):
                raise RuntimeError("report is not a DOCX artifact")
    return explanation_statuses


async def smoke_mcp(mcp_url: str) -> None:
    async with Client(mcp_url) as client:
        listed = await client.list_tools()
    actual = {tool.name for tool in listed.tools}
    if actual != EXPECTED_MCP_TOOLS:
        raise RuntimeError(
            f"MCP tool mismatch: missing={sorted(EXPECTED_MCP_TOOLS - actual)}, "
            f"unexpected={sorted(actual - EXPECTED_MCP_TOOLS)}"
        )


def main() -> int:
    api_url = os.getenv("SITE_SELECTION_API_URL", "http://127.0.0.1:8000")
    mcp_url = os.getenv("SITE_SELECTION_MCP_URL", "http://127.0.0.1:8001/mcp")
    try:
        statuses = smoke_api(api_url)
        asyncio.run(smoke_mcp(mcp_url))
    except Exception as exc:
        print(f"Day24 fixture smoke FAILED: error_type={type(exc).__name__}")
        return 1
    print(
        "Day24 fixture smoke OK: project_types=2, candidates=4, "
        "reports=2, mcp_tools=6, explanation_statuses="
        + ",".join(statuses)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
