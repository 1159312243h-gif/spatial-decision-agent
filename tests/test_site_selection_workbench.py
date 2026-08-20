from datetime import datetime, timezone
from pathlib import Path
import sys

import httpx
import pytest

from app.schemas.site_selection import (
    SiteSelectionAnalysisResponse,
    SiteSelectionRunResponse,
)
from practice.site_selection.storage import RunStatus
from tests.test_site_selection_reporting import completed_state
from workbench.site_selection_client import (
    SiteSelectionAPIClient,
    SiteSelectionAPIError,
    agent_plan_rows,
    agent_trace_rows,
    available_poi_categories,
    candidate_comparison_rows,
    evidence_review_rows,
    map_rows,
    map_view_state,
    poi_metric_rows,
    poi_record_rows,
    poi_source_rows,
)


def completed_run() -> SiteSelectionRunResponse:
    state = completed_state()
    return SiteSelectionRunResponse(
        run_id="run-workbench-001",
        status=RunStatus.COMPLETED,
        updated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        request_id=state.request.request_id,
        analysis=SiteSelectionAnalysisResponse.from_state(state),
        report_url="/site-selection/runs/run-workbench-001/report",
        report_sha256="a" * 64,
    )


def test_workbench_builds_comparison_poi_metrics_and_map_rows() -> None:
    run = completed_run()
    payload = {
        "candidate_parcels": [
            {
                "parcel_id": "A01",
                "longitude": 121.47,
                "latitude": 31.23,
            }
        ]
    }

    comparison = candidate_comparison_rows(run, payload=payload)
    categories = available_poi_categories(run)
    records = poi_record_rows(run, categories=["地铁站"])
    metrics = poi_metric_rows(run)
    sources = poi_source_rows(run)
    plan = agent_plan_rows(run)
    trace = agent_trace_rows(run)
    review = evidence_review_rows(run)
    points = map_rows(payload, run, categories=["地铁站"])
    view = map_view_state(points)

    assert comparison[0]["parcel_id"] == "A01"
    assert comparison[0]["poi_groups_with_hits"] == 1
    assert comparison[0]["poi_groups_total"] == 6
    assert comparison[0]["poi_records_matched"] == 1
    assert comparison[0]["review_required"] is True
    assert categories == ["地铁站"]
    assert records[0]["provider"] == "mock"
    assert any(row["metric"] == "count" for row in metrics)
    assert sources[0]["matched_records"] == 1
    assert "available_record_count" in sources[0]
    assert "query_limit" in sources[0]
    assert "is_truncated" in sources[0]
    assert sources[0]["is_synthetic"] is False
    assert plan[0]["node_id"] == "intake"
    assert trace[0]["status"] == "succeeded"
    assert review
    assert [row["kind"] for row in points] == ["candidate", "poi"]
    assert points[0]["radius_m"] > points[1]["radius_m"]
    assert points[0]["color"] == [220, 38, 38, 235]
    assert points[1]["provider"] == "mock"
    assert 7 <= view["zoom"] <= 14


def test_api_client_creates_run_and_downloads_report() -> None:
    run = completed_run()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/site-selection/runs":
            assert request.headers["Idempotency-Key"] == "fixture-key"
            return httpx.Response(201, json=run.model_dump(mode="json"))
        if request.url.path.endswith("/report"):
            return httpx.Response(
                200,
                content=b"PK-fixture",
                headers={
                    "content-type": (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    )
                },
            )
        raise AssertionError(request.url)

    client = SiteSelectionAPIClient(
        "http://api.test",
        transport=httpx.MockTransport(handler),
    )

    created = client.create_run({}, idempotency_key="fixture-key")
    report = client.download_report(created.report_url)

    assert created.run_id == "run-workbench-001"
    assert report == b"PK-fixture"


def test_api_client_refreshes_and_cancels_queued_run() -> None:
    queued = SiteSelectionRunResponse(
        run_id="run-queued-001",
        status=RunStatus.QUEUED,
        updated_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )
    cancelled = queued.model_copy(update={"status": RunStatus.CANCELLED})

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/site-selection/runs/run-queued-001" + (
            "/cancel" if request.method == "POST" else ""
        )
        return httpx.Response(
            200,
            json=(
                cancelled.model_dump(mode="json")
                if request.method == "POST"
                else queued.model_dump(mode="json")
            ),
        )

    client = SiteSelectionAPIClient(
        "http://api.test",
        transport=httpx.MockTransport(handler),
    )

    assert client.get_run(queued.run_id).status is RunStatus.QUEUED
    assert client.cancel_run(queued.run_id).status is RunStatus.CANCELLED


def test_api_client_default_timeout_covers_fixture_llm_budget() -> None:
    client = SiteSelectionAPIClient("http://api.test")

    assert client.timeout_seconds == 90


def test_api_client_builds_browser_accessible_report_url() -> None:
    client = SiteSelectionAPIClient("http://localhost:8000")

    assert client.absolute_url("/site-selection/runs/run-001/report") == (
        "http://localhost:8000/site-selection/runs/run-001/report"
    )


def test_api_client_maps_structured_error_without_leaking_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={
                "detail": {
                    "code": "runtime_unavailable",
                    "message": "运行时尚未配置",
                    "internal": "secret-token",
                }
            },
        )

    client = SiteSelectionAPIClient(
        "http://api.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SiteSelectionAPIError) as captured:
        client.create_run({}, idempotency_key="fixture-key")

    assert captured.value.status_code == 503
    assert captured.value.code == "runtime_unavailable"
    assert str(captured.value) == "运行时尚未配置"
    assert "secret-token" not in str(captured.value)


def test_workbench_entrypoint_bootstraps_project_root_before_package_import() -> None:
    project_root = Path(__file__).parents[1]
    entrypoint = project_root / "workbench" / "app.py"
    source = entrypoint.read_text(encoding="utf-8")

    assert source.index("sys.path.insert") < source.index(
        "from workbench.site_selection_client"
    )

    bootstrap_source = source.split(
        "from workbench.site_selection_client", maxsplit=1
    )[0]
    original_path = sys.path.copy()
    try:
        sys.path[:] = [str(entrypoint.parent), str(project_root), *sys.path]
        exec(
            compile(bootstrap_source, str(entrypoint), "exec"),
            {"__file__": str(entrypoint)},
        )
        assert sys.path[0] == str(project_root)
    finally:
        sys.path[:] = original_path


def test_workbench_auto_polls_and_uses_distinct_map_layers() -> None:
    source = (
        Path(__file__).parents[1] / "workbench" / "app.py"
    ).read_text(encoding="utf-8")

    assert "@st.fragment(run_every=2)" in source
    assert "状态每 2 秒自动更新" in source
    assert '"TextLayer"' in source
    assert source.count('"ScatterplotLayer"') >= 2
    assert "st.pydeck_chart" in source
    assert "st.map(" not in source
    assert '"Agent 运行"' in source
    assert 'st.subheader("执行计划")' in source
    assert 'st.subheader("节点轨迹")' in source
    assert 'st.subheader("质量门禁")' in source
    assert "POI 查询达到返回上限" in source
