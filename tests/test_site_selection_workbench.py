from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import httpx
import pytest

from app.schemas.site_selection import (
    SiteSelectionAnalysisResponse,
    SiteSelectionRunResponse,
    SiteSelectionSupervisorEventsResponse,
    SiteSelectionSupervisorResponse,
)
from practice.site_selection.storage import RunStatus
from practice.site_selection import (
    CandidateDiscoveryReport,
    CandidateSelection,
    SupervisorAnalysisCompletion,
    SupervisorAnalysisStatus,
)
from tests.test_site_selection_reporting import completed_state
from tests.test_site_selection_supervisor import _request, _supervisor
from workbench.site_selection_client import (
    SiteSelectionAPIClient,
    SiteSelectionAPIError,
    agent_plan_rows,
    agent_trace_rows,
    available_discovery_poi_categories,
    available_poi_categories,
    candidate_radius_rows,
    candidate_comparison_rows,
    discovery_candidate_rows,
    discovery_map_rows,
    evidence_review_rows,
    map_rows,
    map_view_state,
    poi_metric_rows,
    poi_candidate_coverage_rows,
    poi_group_comparability_rows,
    poi_record_rows,
    poi_source_rows,
    supervisor_completed_run,
    unique_analysis_poi_map_rows,
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
    coverage = poi_candidate_coverage_rows(run)
    comparability = poi_group_comparability_rows(run)
    points = map_rows(payload, run, categories=["地铁站"])
    radius_rows = candidate_radius_rows(payload, run, "A01")
    view = map_view_state(points)

    assert comparison[0]["parcel_id"] == "A01"
    assert comparison[0]["poi_groups_with_hits"] == 1
    assert comparison[0]["poi_groups_total"] == 6
    assert comparison[0]["poi_records_matched"] == 1
    assert comparison[0]["review_required"] is True
    assert categories == ["地铁站"]
    assert records[0]["provider"] == "mock"
    assert records[0]["evidence_reused"] is False
    assert records[0]["evidence_supplemented"] is False
    assert any(row["metric"] == "count" for row in metrics)
    assert sources[0]["matched_records"] == 1
    assert "available_record_count" in sources[0]
    assert "query_limit" in sources[0]
    assert "is_truncated" in sources[0]
    assert sources[0]["evidence_supplemented"] is False
    assert sources[0]["evidence_supplement_reason"] is None
    assert sources[0]["evidence_supplement_error"] is None
    assert sources[0]["is_synthetic"] is False
    assert plan[0]["node_id"] == "intake"
    assert trace[0]["status"] == "succeeded"
    assert review
    assert coverage[0]["evidence_status"] == "完整可比"
    assert coverage[0]["complete_groups"] == 6
    assert all(row["comparability"] == "可横向比较" for row in comparability)
    assert [row["kind"] for row in points] == ["candidate", "poi"]
    assert radius_rows
    assert all(row["kind"] == "coverage" for row in radius_rows)
    assert points[0]["radius_m"] > points[1]["radius_m"]
    assert points[0]["color"] == [220, 38, 38, 235]
    assert points[1]["provider"] == "mock"
    assert 7 <= view["zoom"] <= 14


def test_analysis_poi_map_deduplicates_and_preserves_lineage() -> None:
    shared = {
        "group_key": "transit_access",
        "poi_id": "poi-shared-001",
        "name": "共享地铁站",
        "category": "地铁站",
        "longitude": 121.47,
        "latitude": 31.23,
        "provider": "overpass",
        "dataset_id": "osm-poi",
        "evidence_reused": True,
        "evidence_supplemented": False,
    }
    rows = unique_analysis_poi_map_rows(
        [
            {**shared, "parcel_id": "A01", "distance_m": 250.0},
            {**shared, "parcel_id": "A02", "distance_m": 180.0},
            {
                **shared,
                "parcel_id": "A03",
                "distance_m": 320.0,
                "evidence_reused": False,
                "evidence_supplemented": True,
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["candidate_link_count"] == 3
    assert rows[0]["candidate_ids"] == "A01, A02, A03"
    assert rows[0]["distance_m"] == 180.0
    assert rows[0]["evidence_origin"] == "候选点补查、发现快照裁剪"
    assert rows[0]["line_color"] == [8, 145, 178, 190]


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


def test_api_client_converses_confirms_and_recovers_scenario() -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app

    api = TestClient(create_app())

    def handler(request: httpx.Request) -> httpx.Response:
        response = api.request(
            request.method,
            request.url.path,
            content=request.content,
            headers={"content-type": "application/json"},
        )
        return httpx.Response(response.status_code, json=response.json())

    client = SiteSelectionAPIClient(
        "http://api.test",
        transport=httpx.MockTransport(handler),
    )
    proposed = client.chat(
        "在上海市徐汇区开咖啡店，范围 4 公里",
        project_type="coffee_shop",
    )

    assert proposed.status.value == "awaiting_confirmation"
    confirmed = client.confirm_chat_scenario(
        proposed.session_id,
        version_id=proposed.scenario_version.version_id,
        confirmed_by="workbench-user",
    )
    recovered = client.get_chat(proposed.session_id)

    assert confirmed.status.value == "confirmed"
    assert confirmed.discovery_request is not None
    assert recovered.active_version_id == confirmed.scenario_version.version_id


def test_api_client_discovers_candidates_and_flattens_review_evidence() -> None:
    from tests.test_candidate_discovery import discovery_request, fixture_frames
    from app.site_selection_bootstrap import build_fixture_runtime_registry
    from practice.site_selection import CandidateDiscoveryService
    from practice.site_selection.spatial import MockSpatialDatasetGateway

    registry = build_fixture_runtime_registry(
        object(),
        fixture_root=Path(__file__).parents[1] / "data" / "fixtures",
        spatial_gateway=MockSpatialDatasetGateway(fixture_frames()),
    )
    expected = CandidateDiscoveryService(registry).discover(discovery_request())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/site-selection/candidates/discover"
        return httpx.Response(200, json=expected.model_dump(mode="json"))

    client = SiteSelectionAPIClient(
        "http://api.test", transport=httpx.MockTransport(handler)
    )
    report = client.discover_candidates({"project_type": "coffee_shop"})
    rows = discovery_candidate_rows(report)
    categories = available_discovery_poi_categories(report)
    map_points = discovery_map_rows(report, categories=categories[:1])

    assert isinstance(report, CandidateDiscoveryReport)
    assert rows[0]["rank"] == 1
    assert rows[0]["geometry_dataset_id"] == "demo-coffee-discovery-pool"
    assert "land_use_suitability" in rows[0]
    assert rows[0]["formal_analysis_allowed"] is True
    assert categories
    assert any(item["kind"] == "poi" for item in map_points)
    assert map_points[0]["map_label"] == "#1"
    assert all(
        item["kind"] == "candidate" or item["category"] == categories[0]
        for item in map_points
    )


def test_api_client_starts_recovers_and_confirms_supervisor_session() -> None:
    supervisor, _, analysis = _supervisor()
    paused_run = supervisor.start("workbench-supervisor-001", _request())
    selected = paused_run.confirmation_request.candidate_ids[:2]
    awaiting_run = supervisor.confirm(
        paused_run.session_id,
        CandidateSelection(
            selected_candidate_ids=selected,
            reviewer_id="planner-001",
            confirmed_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        ),
        expected_checkpoint_id=paused_run.checkpoint_id,
    )
    completed_run = supervisor.complete_analysis(
        paused_run.session_id,
        SupervisorAnalysisCompletion(
            run_id=analysis.run_id,
            status=SupervisorAnalysisStatus.COMPLETED,
            analysis_state=analysis.completed_state(),
        ),
    )
    paused = SiteSelectionSupervisorResponse.from_run(
        paused_run,
        session_ttl_seconds=7_200,
    )
    completed = SiteSelectionSupervisorResponse.from_run(
        completed_run,
        session_ttl_seconds=7_200,
    )
    awaiting = SiteSelectionSupervisorResponse.from_run(
        awaiting_run,
        session_ttl_seconds=7_200,
    )
    empty_events = SiteSelectionSupervisorEventsResponse(
        session_id=paused.session_id,
        events=[],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=empty_events.model_dump(mode="json"))
        if request.url.path.endswith("/confirm"):
            payload = json.loads(request.content)
            assert payload["expected_checkpoint_id"] == paused.checkpoint_id
            assert payload["selected_candidate_ids"] == selected
            assert payload["reviewer_id"] == "planner-001"
            return httpx.Response(202, json=awaiting.model_dump(mode="json"))
        if request.method == "GET":
            return httpx.Response(200, json=paused.model_dump(mode="json"))
        return httpx.Response(201, json=paused.model_dump(mode="json"))

    client = SiteSelectionAPIClient(
        "http://api.test",
        transport=httpx.MockTransport(handler),
    )

    assert client.start_supervisor({}).session_id == paused.session_id
    assert client.get_supervisor(paused.session_id).checkpoint_id == (
        paused.checkpoint_id
    )
    confirmed = client.confirm_supervisor(
        paused.session_id,
        checkpoint_id=paused.checkpoint_id,
        selected_candidate_ids=selected,
        reviewer_id="planner-001",
    )
    assert confirmed.status.value == "awaiting_analysis"
    assert confirmed.analysis_run_id == analysis.run_id
    assert client.get_supervisor_events(paused.session_id).events == []
    adapted = supervisor_completed_run(completed)
    assert adapted.status is RunStatus.COMPLETED
    assert adapted.analysis is not None
    assert adapted.poi_evidence_snapshot_reused is True


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


def test_api_client_gives_supervisor_start_a_bounded_timeout_allowance() -> None:
    supervisor, _, _ = _supervisor()
    paused_run = supervisor.start("workbench-supervisor-timeout", _request())
    paused = SiteSelectionSupervisorResponse.from_run(
        paused_run,
        session_ttl_seconds=7_200,
    )
    observed_timeout = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed_timeout.update(request.extensions["timeout"])
        return httpx.Response(201, json=paused.model_dump(mode="json"))

    client = SiteSelectionAPIClient(
        "http://api.test",
        transport=httpx.MockTransport(handler),
    )

    client.start_supervisor({})

    assert observed_timeout["connect"] == 150
    assert observed_timeout["read"] == 150
    assert client.timeout_seconds == 90


def test_api_client_explains_supervisor_candidate_discovery_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fixture timeout", request=request)

    client = SiteSelectionAPIClient(
        "http://api.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SiteSelectionAPIError) as captured:
        client.start_supervisor({})

    assert captured.value.status_code == 504
    assert captured.value.code == "api_timeout"
    assert "在线 POI 分区补查仍未完成" in str(captured.value)
    assert "缓存可供下一次复用" in str(captured.value)


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
    assert "use_container_width" not in source
    assert 'width="stretch"' in source
    assert '"Agent 运行"' in source
    assert 'st.subheader("执行计划")' in source
    assert 'st.subheader("节点轨迹")' in source
    assert 'st.subheader("质量门禁")' in source
    assert "POI 查询达到返回上限" in source
    assert '"coffee_shop": "门店选址 · 咖啡店"' in source
    assert '"convenience_store": "门店选址 · 便利店"' in source
    assert 'st.session_state[candidate_mode_key] = "discovery"' in source
    assert 'default="discovery"' not in source
    assert '"fixture": "演示候选"' in source
    assert '"discovery": "自动发现"' in source
    assert "default_bounds" not in source
    assert "确认并发现候选" in source
    assert "scenario_discovery_pending" in source
    assert "discovery-bounds-ready" in source
    assert "候选尚未生成" in source
    assert 'if candidate_mode != "discovery":' in source
    assert '"awaiting_confirmation": "待确认候选"' in source
    assert "确认候选并运行商业选址分析" in source
    assert "用地、规划与政策合规状态标记为待核验" in source
    assert "disabled=not analysis_allowed" in source
    assert "恢复历史任务" in source
    assert "Supervisor Session" not in source
    assert "start_supervisor" in source
    assert "get_supervisor" in source
    assert "confirm_supervisor" in source
    assert "render_supervisor_analysis_status" in source
    assert 'f"取消{analysis_label}"' in source
    assert "client.cancel_run(current.analysis_run_id)" in source
    assert 'st.query_params["supervisor_session"]' in source
    assert "expected_checkpoint_id" not in source
    assert "checkpoint_id=current_supervisor.checkpoint_id" in source
    assert '"selected": st.column_config.CheckboxColumn' in source
    assert "确认候选并运行完整分析" in source
    assert "用地降级策略" in source
    assert "当前范围未取得可核验用地依据" in source
    assert "使用演示用地并发现候选" in source
    assert "使用演示用地重新发现" in source
    assert "使用演示用地启动完整流程" in source
    assert '"fallback_mode": "strict"' in source
    assert "不会把市场网格冒充为合法地块" in source
    assert "本次用地依据来自版本化合成演示数据" in source
    assert "disabled=not formal_analysis_allowed" not in source
    assert "范围 POI 类别" in source
    assert "范围 POI 数据与来源" in source
    assert "边界内真实 POI" in source
    assert "评分缓冲区 POI" in source
    assert "分区补查评分组" in source
    assert "补查成功分区" in source
    assert "补查新增真实 POI" in source
    assert "仍不完整评分组" in source
    assert "首次在线分区补查可能需要几十秒，请勿重复点击" in source
    assert "成功的真实记录已合并去重并重新用于候选评分" in source
    assert 'item.repair_success_count' in source
    assert 'item.incomplete_reasons' in source
    assert "数据质量与降级说明" in source
    assert 'get_text="map_label"' in source
    assert source.index("        render_scenario_primary_action(conversation)") < (
        source.index("if version.region_resolution is not None")
    )
    assert source.index("    render_analysis_action()") < source.index(
        'st.subheader("POI 分布与证据来源")'
    )
    assert "discovery_map_rows" in source
    assert 'payload["poi_evidence_snapshot_id"]' in source
    assert "评分证据快照覆盖候选点" in source
    assert "点击页面左上角的 » 展开设置侧栏" in source
    assert "仅补查对应候选点附近范围" in source
    assert "截断、缺组或缺类别时才按候选点补查" in source
    assert 'row["evidence_supplemented"]' in source
    assert 'row["evidence_supplement_error"]' in source
    assert "run.poi_evidence_snapshot_reused" in source
    assert 'if candidate_mode == "discovery" and supervisor_status == "completed":' in source
    assert "商业选址分析已完成，无需再次确认候选" in source
    assert "软评分第 1 名（待复核）" in source
    assert 'st.subheader("4. 分析结果")' in source
    assert "请保留至少一个候选，并确认当前任务仍处于待确认状态" not in source
    assert 'st.segmented_control(' in source
    assert "评分证据（候选局部）" in source
    assert "发现背景（完整范围）" in source
    assert "类别口径差异" in source
    assert "候选-POI 关联" in source
    assert "地图聚焦候选" in source
    assert "候选 POI 覆盖与可比性" in source
    assert "这些差异不能直接解释为真实商业密度差异" in source
    assert "聚焦单个候选时显示 Profile 服务半径" in source
    assert "青色细环：在线补查成功" in source
    assert "橙色细环：合成数据" in source
    assert 'get_line_color="line_color"' in source
    assert 'key=f"{key_prefix}-poi-map"' in source
    assert "显示真实 POI" in source
