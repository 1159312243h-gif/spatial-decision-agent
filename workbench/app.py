from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pydeck as pdk
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT_STR = str(PROJECT_ROOT)
if not sys.path or sys.path[0] != PROJECT_ROOT_STR:
    try:
        sys.path.remove(PROJECT_ROOT_STR)
    except ValueError:
        pass
    sys.path.insert(0, PROJECT_ROOT_STR)

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
)
from practice.site_selection import ProjectType, load_fixture_candidate_catalog


st.set_page_config(
    page_title="选址决策工作台",
    page_icon=":material/map:",
    layout="wide",
)

st.title("选址决策工作台")
st.caption("需求设置 → 场景确认 → 候选发现 → 证据分析")
st.info(
    "需要调整项目类型、候选来源或发现范围？"
    "点击页面左上角的 » 展开设置侧栏。"
)

with st.sidebar.expander("连接设置"):
    api_url = st.text_input(
        "API 地址",
        value=os.getenv("SITE_SELECTION_API_URL", "http://localhost:8000"),
    )
public_api_url = (
    os.getenv("SITE_SELECTION_PUBLIC_API_URL", "").strip() or api_url
)
project_type = st.sidebar.radio(
    "项目类型",
    options=[
        "coffee_shop",
        "convenience_store",
        "shopping_mall",
        "logistics_park",
    ],
    format_func=lambda value: {
        "coffee_shop": "门店选址 · 咖啡店",
        "convenience_store": "门店选址 · 便利店",
        "shopping_mall": "商场",
        "logistics_park": "物流园",
    }[value],
)

candidate_catalog = load_fixture_candidate_catalog(
    PROJECT_ROOT / "data" / "fixtures" / "candidates.json"
)
defaults = {
    item.value: candidate_catalog.payload_for(item)["candidate_parcels"]
    for item in ProjectType
}

is_retail = project_type in {"coffee_shop", "convenience_store"}
candidate_mode = "fixture"
if is_retail:
    candidate_mode_key = f"candidate-mode-{project_type}"
    if candidate_mode_key not in st.session_state:
        st.session_state[candidate_mode_key] = "discovery"
    candidate_mode = st.sidebar.segmented_control(
        "候选来源",
        options=["fixture", "discovery"],
        format_func=lambda value: {
            "fixture": "演示候选",
            "discovery": "自动发现",
        }[value],
        key=candidate_mode_key,
    )

if "candidate_editor_revisions" not in st.session_state:
    st.session_state.candidate_editor_revisions = {}
if "discovered_candidates" not in st.session_state:
    st.session_state.discovered_candidates = {}
if "site_selection_supervisor" not in st.session_state:
    st.session_state.site_selection_supervisor = None
if "site_selection_conversation" not in st.session_state:
    st.session_state.site_selection_conversation = None


def apply_confirmed_scenario() -> None:
    reply = st.session_state.site_selection_conversation
    request = reply.discovery_request if reply is not None else None
    if request is None:
        st.session_state.scenario_apply_error = "该场景没有可执行的候选发现范围"
        return
    request_project_type = request.project_type.value
    if request_project_type != project_type:
        st.session_state.scenario_apply_error = (
            f"场景项目类型为 {request_project_type}，请先切换左侧项目类型"
        )
        return
    bounds = request.bounds
    st.session_state[f"candidate-mode-{project_type}"] = "discovery"
    st.session_state[f"discovery-west-{project_type}"] = bounds.west
    st.session_state[f"discovery-south-{project_type}"] = bounds.south
    st.session_state[f"discovery-east-{project_type}"] = bounds.east
    st.session_state[f"discovery-north-{project_type}"] = bounds.north
    st.session_state[f"discovery-count-{project_type}"] = request.max_candidates
    st.session_state[f"discovery-separation-{project_type}"] = (
        request.minimum_separation_m
    )
    st.session_state[f"discovery-fallback-{project_type}"] = (
        request.fallback_mode.value
    )
    st.session_state[f"discovery-bounds-ready-{project_type}"] = True
    st.session_state.scenario_apply_error = None
    st.session_state.scenario_apply_notice = (
        f"已应用场景版本 {reply.scenario_version.version_id}"
    )


def queue_fixture_land_demo_discovery() -> None:
    bounds = candidate_catalog.demo_discovery_bounds_for(
        ProjectType(project_type)
    )
    request = {
        "project_type": project_type,
        "bounds": bounds,
        "max_candidates": 8,
        "minimum_separation_m": 600,
        "fallback_mode": "strict",
    }
    st.session_state[f"candidate-mode-{project_type}"] = "discovery"
    for edge, value in bounds.items():
        st.session_state[f"discovery-{edge}-{project_type}"] = value
    st.session_state[f"discovery-count-{project_type}"] = 8
    st.session_state[f"discovery-separation-{project_type}"] = 600
    st.session_state[f"discovery-fallback-{project_type}"] = "strict"
    st.session_state[f"discovery-bounds-ready-{project_type}"] = True
    st.session_state.scenario_discovery_pending = request
    st.session_state.scenario_apply_error = None
    st.session_state.scenario_apply_notice = (
        "已主动切换到版本化合成用地演示范围；"
        "该范围只用于验证完整 Agent 工作流"
    )


def queue_confirmed_scenario_discovery() -> None:
    conversation = st.session_state.site_selection_conversation
    if conversation is None or conversation.discovery_request is None:
        st.session_state.scenario_apply_error = "当前场景没有可执行的候选发现范围"
        return
    st.session_state.scenario_apply_error = None
    st.session_state.scenario_discovery_pending = (
        conversation.discovery_request.model_dump(mode="json")
    )
    apply_confirmed_scenario()


def confirm_and_queue_scenario_discovery() -> None:
    conversation = st.session_state.site_selection_conversation
    if conversation is None:
        return
    try:
        confirmed = SiteSelectionAPIClient(api_url).confirm_chat_scenario(
            conversation.session_id,
            version_id=conversation.scenario_version.version_id,
            confirmed_by="workbench-user",
        )
        st.session_state.site_selection_conversation = confirmed
        queue_confirmed_scenario_discovery()
    except SiteSelectionAPIError as exc:
        st.session_state.scenario_apply_error = str(exc)


def render_scenario_primary_action(conversation) -> None:
    if conversation.status.value == "awaiting_confirmation":
        st.button(
            "确认并发现候选",
            icon=":material/check_circle:",
            type="primary",
            width="stretch",
            on_click=confirm_and_queue_scenario_discovery,
        )
    elif (
        conversation.status.value == "confirmed"
        and conversation.discovery_request is not None
        and st.session_state.get(
            f"candidate_discovery_report_{project_type}"
        )
        is None
        and st.session_state.get("scenario_discovery_pending") is None
    ):
        st.button(
            "发现候选",
            icon=":material/travel_explore:",
            type="primary",
            width="stretch",
            on_click=queue_confirmed_scenario_discovery,
        )


with st.expander("1. 描述需求与确认场景", expanded=True):
    conversation = st.session_state.site_selection_conversation
    if conversation is None:
        st.subheader("创建选址场景")
        st.info(
            "从区域、业态和搜索范围开始。Agent 会先整理为可确认的场景，"
            "确认后自动发现候选。"
        )
    if conversation is not None:
        for message in conversation.messages[-8:]:
            role = "user" if message.role.value == "user" else "assistant"
            with st.chat_message(role):
                st.write(message.content)
        version = conversation.scenario_version
        status_a, status_b, status_c = st.columns(3)
        status_a.metric("场景版本", f"v{version.version_number}")
        status_b.metric(
            "状态",
            {
                "needs_clarification": "待补充",
                "awaiting_confirmation": "待确认",
                "confirmed": "已确认",
            }[conversation.status.value],
        )
        status_c.metric(
            "解析方式",
            {
                "rule_based": "规则解析",
                "llm": "LLM 解析",
                "confirmation": "人工确认",
            }.get(
                conversation.interpretation_source,
                conversation.interpretation_source,
            ),
        )
        render_scenario_primary_action(conversation)
        if version.region_resolution is not None:
            resolution = version.region_resolution
            st.dataframe(
                [
                    {
                        "区域": resolution.normalized_name,
                        "层级": resolution.administrative_level,
                        "来源": resolution.source.value,
                        "Provider": resolution.provider,
                        "置信度": resolution.confidence,
                        "搜索半径_km": resolution.discovery_radius_km,
                        "west": resolution.discovery_bounds.west,
                        "south": resolution.discovery_bounds.south,
                        "east": resolution.discovery_bounds.east,
                        "north": resolution.discovery_bounds.north,
                    }
                ],
                hide_index=True,
                width="stretch",
            )
            for warning in resolution.warnings:
                st.warning(warning)
        if version.data_readiness:
            st.dataframe(
                [
                    {
                        "约束": item.key.value,
                        "数据状态": {
                            "executable": "可执行",
                            "advisory": "仅提示",
                            "missing_data": "缺少数据",
                        }[item.readiness.value],
                        "说明": item.reason,
                    }
                    for item in version.data_readiness
                ],
                hide_index=True,
                width="stretch",
            )
        for conflict in version.conflicts:
            st.error(conflict.message)
        for clarification in version.clarifications:
            st.info(clarification)

    with st.form("site-selection-conversation-form", clear_on_submit=True):
        agent_message = st.text_area(
            "需求或约束变更",
            placeholder="例如：在上海市徐汇区开咖啡店，范围 4 公里，找 8 个候选点",
            height=80,
        )
        send_message = st.form_submit_button(
            "发送",
            icon=":material/send:",
            type="primary",
        )
    if send_message and agent_message.strip():
        try:
            session_id = (
                conversation.session_id if conversation is not None else None
            )
            st.session_state.site_selection_conversation = (
                SiteSelectionAPIClient(api_url).chat(
                    agent_message,
                    project_type=project_type,
                    session_id=session_id,
                )
            )
            st.rerun()
        except SiteSelectionAPIError as exc:
            st.error(str(exc))

    if st.session_state.get("scenario_apply_error"):
        st.error(st.session_state.scenario_apply_error)
    if st.session_state.get("scenario_apply_notice"):
        st.success(st.session_state.scenario_apply_notice)


def store_supervisor_state(session, *, client=None) -> None:
    previous = st.session_state.site_selection_supervisor
    st.session_state.site_selection_supervisor = session
    st.query_params["supervisor_session"] = session.session_id
    report = session.discovery_report
    if report is None:
        return
    report_project_type = report.project_type.value
    st.session_state[f"discovery-bounds-ready-{report_project_type}"] = True
    recovered_bounds = {
        "west": report.bounds.west,
        "south": report.bounds.south,
        "east": report.bounds.east,
        "north": report.bounds.north,
    }
    for edge, value in recovered_bounds.items():
        key = f"discovery-{edge}-{report_project_type}"
        if key not in st.session_state:
            st.session_state[key] = value
    report_changed = (
        previous is None
        or previous.session_id != session.session_id
        or previous.discovery_report != report
    )
    if report_changed:
        st.session_state[
            f"candidate_discovery_report_{report_project_type}"
        ] = report
        st.session_state.discovered_candidates[report_project_type] = [
            item.candidate.model_dump(mode="json") for item in report.candidates
        ]
        st.session_state.candidate_editor_revisions[report_project_type] = (
            st.session_state.candidate_editor_revisions.get(
                report_project_type, 0
            )
            + 1
        )
    if session.status.value != "completed" or session.analysis is None:
        return
    selected_ids = set(session.confirmation.selected_candidate_ids)
    selected_candidates = [
        item.candidate.model_dump(mode="json")
        for item in report.candidates
        if item.candidate.parcel_id in selected_ids
    ]
    st.session_state.site_selection_payload = {
        "project_type": report_project_type,
        "candidate_parcels": selected_candidates,
        "poi_evidence_snapshot_id": report.poi_evidence_snapshot_id,
    }
    st.session_state.site_selection_run = (
        client.get_run(session.analysis_run_id)
        if client is not None and session.analysis_run_id is not None
        else supervisor_completed_run(session)
    )


@st.fragment(run_every=2)
def render_supervisor_analysis_status(api_url: str) -> None:
    current = st.session_state.site_selection_supervisor
    if current is None:
        return
    was_waiting = current.status.value == "awaiting_analysis"
    if was_waiting:
        try:
            client = SiteSelectionAPIClient(api_url)
            current = client.get_supervisor(current.session_id)
            store_supervisor_state(current, client=client)
        except SiteSelectionAPIError as exc:
            st.warning(f"Supervisor 状态自动更新暂时失败：{exc}")
    status_a, status_b, status_c = st.columns([2, 2, 1])
    status_a.metric("任务会话", current.session_id)
    status_b.metric(
        "分析运行",
        current.analysis_run_id or "尚未提交",
    )
    status_c.metric(
        "Agent 状态",
        {
            "discovering": "发现中",
            "awaiting_confirmation": "待确认候选",
            "awaiting_analysis": "分析中",
            "completed": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
            "timed_out": "已超时",
        }.get(current.status.value, current.status.value),
    )
    if current.status.value == "awaiting_analysis":
        analysis_label = (
            "完整合规分析"
            if current.discovery_report is not None
            and current.discovery_report.formal_analysis_allowed
            else "商业选址分析"
        )
        st.caption(f"{analysis_label}已提交，状态每 2 秒自动更新")
        if current.analysis_run_id is not None and st.button(
            f"取消{analysis_label}",
            icon=":material/cancel:",
            key=f"cancel-supervisor-analysis-{current.session_id}",
        ):
            try:
                client = SiteSelectionAPIClient(api_url)
                client.cancel_run(current.analysis_run_id)
                current = client.get_supervisor(current.session_id)
                store_supervisor_state(current, client=client)
                st.rerun()
            except SiteSelectionAPIError as exc:
                st.error(str(exc))
    elif current.status.value in {"failed", "cancelled", "timed_out"}:
        message = current.analysis_error_type or current.status.value
        if current.status.value == "cancelled":
            st.warning(f"分析已取消：{message}")
        else:
            st.error(f"分析未完成：{message}")
    if was_waiting and current.status.value != "awaiting_analysis":
        st.rerun()


query_supervisor_id = str(
    st.query_params.get("supervisor_session", "")
).strip()
if (
    candidate_mode == "discovery"
    and query_supervisor_id
    and st.session_state.site_selection_supervisor is None
):
    try:
        recovery_client = SiteSelectionAPIClient(api_url)
        recovered_supervisor = recovery_client.get_supervisor(query_supervisor_id)
        if (
            recovered_supervisor.discovery_report is not None
            and recovered_supervisor.discovery_report.project_type.value
            == project_type
        ):
            store_supervisor_state(recovered_supervisor, client=recovery_client)
    except SiteSelectionAPIError as exc:
        st.sidebar.warning(f"历史任务恢复失败：{exc}")

discovery_report = st.session_state.get(
    f"candidate_discovery_report_{project_type}"
)
current_supervisor = st.session_state.site_selection_supervisor
if (
    current_supervisor is not None
    and (
        current_supervisor.discovery_report is None
        or current_supervisor.discovery_report.project_type.value
        != project_type
    )
):
    current_supervisor = None
if is_retail and candidate_mode == "discovery":
    bounds_ready = bool(
        st.session_state.get(f"discovery-bounds-ready-{project_type}")
        or discovery_report is not None
    )
    if bounds_ready:
        with st.sidebar.expander("发现范围", expanded=False):
            west = st.number_input(
                "西界经度",
                format="%.6f",
                key=f"discovery-west-{project_type}",
            )
            south = st.number_input(
                "南界纬度",
                format="%.6f",
                key=f"discovery-south-{project_type}",
            )
            east = st.number_input(
                "东界经度",
                format="%.6f",
                key=f"discovery-east-{project_type}",
            )
            north = st.number_input(
                "北界纬度",
                format="%.6f",
                key=f"discovery-north-{project_type}",
            )
            candidate_count_key = f"discovery-count-{project_type}"
            if candidate_count_key not in st.session_state:
                st.session_state[candidate_count_key] = 8
            maximum_candidates = st.slider(
                "候选数量",
                min_value=3,
                max_value=20,
                key=candidate_count_key,
            )
            separation_key = f"discovery-separation-{project_type}"
            if separation_key not in st.session_state:
                st.session_state[separation_key] = 600
            minimum_separation_m = st.slider(
                "最小间距（米）",
                min_value=100,
                max_value=3000,
                step=100,
                key=separation_key,
            )
            fallback_mode = st.selectbox(
                "用地降级策略",
                options=[
                    "market_exploration",
                    "commercial_land_proxy",
                    "strict",
                ],
                format_func=lambda value: {
                    "market_exploration": "自动：用地 → 商业代理 → 市场网格",
                    "commercial_land_proxy": "最多降级到商业用地代理",
                    "strict": "仅使用完整用地机会单元",
                }[value],
                key=f"discovery-fallback-{project_type}",
            )
            st.caption(
                "任意区域可以自动加载真实 POI 并进行市场探索；"
                "正式分析还需要覆盖该范围的可核验用地数据。"
            )
            st.button(
                "使用演示用地并发现候选",
                icon=":material/science:",
                width="stretch",
                key=f"fixture-land-demo-{project_type}",
                on_click=queue_fixture_land_demo_discovery,
                help=(
                    "主动切换到版本化合成用地覆盖范围，并使用 strict 模式"
                    "验证候选发现、人工确认和正式分析完整链路"
                ),
            )
            reviewer_id = st.text_input(
                "确认人标识",
                value="workbench-user",
                key=f"supervisor-reviewer-{project_type}",
            )
            confirmation_note = st.text_input(
                "确认备注",
                value="",
                key=f"supervisor-note-{project_type}",
            )
    else:
        reviewer_id = "workbench-user"
        confirmation_note = ""
        st.sidebar.info("请先在右侧描述需求，确认区域后会自动设置发现范围")
    with st.sidebar.expander("恢复历史任务"):
        resume_session_id = st.text_input(
            "任务会话 ID",
            value=query_supervisor_id,
            key=f"supervisor-resume-{project_type}",
        )
        if st.button(
            "恢复",
            icon=":material/restore:",
            width="stretch",
            key=f"supervisor-resume-button-{project_type}",
        ):
            try:
                recovered_supervisor = SiteSelectionAPIClient(
                    api_url
                ).get_supervisor(resume_session_id)
                if (
                    recovered_supervisor.discovery_report is None
                    or recovered_supervisor.discovery_report.project_type.value
                    != project_type
                ):
                    raise ValueError("历史任务与当前项目类型不一致")
                store_supervisor_state(
                    recovered_supervisor,
                    client=SiteSelectionAPIClient(api_url),
                )
                st.rerun()
            except (SiteSelectionAPIError, ValueError) as exc:
                st.error(str(exc))
    pending_discovery = st.session_state.get("scenario_discovery_pending")
    manual_discovery = (
        st.sidebar.button(
            "重新发现候选",
            icon=":material/refresh:",
            width="stretch",
        )
        if bounds_ready
        else False
    )
    if pending_discovery is not None or manual_discovery:
        try:
            discovery_command = pending_discovery or {
                "project_type": project_type,
                "bounds": {
                    "west": west,
                    "south": south,
                    "east": east,
                    "north": north,
                },
                "max_candidates": maximum_candidates,
                "minimum_separation_m": minimum_separation_m,
                "fallback_mode": fallback_mode,
            }
            with st.spinner(
                "正在并行核验用地和 POI 市场证据；"
                "首次在线分区补查可能需要几十秒，请勿重复点击..."
            ):
                supervisor_session = SiteSelectionAPIClient(
                    api_url
                ).start_supervisor(discovery_command)
            st.session_state.pop("scenario_discovery_pending", None)
            st.session_state.scenario_apply_notice = None
            store_supervisor_state(supervisor_session)
            discovery_report = supervisor_session.discovery_report
            st.rerun()
        except (SiteSelectionAPIError, ValueError) as exc:
            st.session_state.pop("scenario_discovery_pending", None)
            st.session_state.scenario_apply_error = str(exc)
            st.error(str(exc))

candidate_defaults = defaults[project_type]
if candidate_mode == "discovery":
    candidate_defaults = [
        {"selected": True, **item}
        for item in st.session_state.discovered_candidates.get(project_type, [])
    ]
st.subheader(
    "2. 候选发现与选择"
    if candidate_mode == "discovery"
    else "2. 演示候选编辑"
)
editor_revision = st.session_state.candidate_editor_revisions.get(
    project_type, 0
)
editor_key = f"candidate-editor-{project_type}-{candidate_mode}-{editor_revision}"
if candidate_mode == "discovery" and not candidate_defaults:
    st.info(
        "候选尚未生成。请先在上方提交需求并确认场景；区域解析完成后，"
        "系统会自动启动候选发现。"
    )
    if is_retail:
        st.button(
            "使用演示用地启动完整流程",
            icon=":material/science:",
            key=f"fixture-land-demo-empty-{project_type}",
            on_click=queue_fixture_land_demo_discovery,
        )
    candidates = pd.DataFrame()
else:
    candidates = st.data_editor(
        pd.DataFrame(candidate_defaults),
        key=editor_key,
        hide_index=True,
        num_rows=("fixed" if candidate_mode == "discovery" else "dynamic"),
        disabled=(
            [
                "parcel_id",
                "name",
                "longitude",
                "latitude",
                "area_hectares",
                "geometry_dataset_id",
            ]
            if candidate_mode == "discovery"
            else False
        ),
        width="stretch",
        column_config={
            "selected": st.column_config.CheckboxColumn("选择"),
            "parcel_id": st.column_config.TextColumn("地块编号", required=True),
            "name": st.column_config.TextColumn("名称"),
            "longitude": st.column_config.NumberColumn(
                "经度", min_value=-180.0, max_value=180.0, format="%.6f"
            ),
            "latitude": st.column_config.NumberColumn(
                "纬度", min_value=-90.0, max_value=90.0, format="%.6f"
            ),
            "area_hectares": st.column_config.NumberColumn(
                "面积（公顷）", min_value=0.01, format="%.2f"
            ),
            "geometry_dataset_id": st.column_config.TextColumn(
                "空间数据集", required=True
            ),
        },
    )

candidate_records = candidates.where(pd.notnull(candidates), None).to_dict(
    orient="records"
)
if candidate_mode == "discovery":
    candidate_records = [
        {key: value for key, value in item.items() if key != "selected"}
        for item in candidate_records
        if item.get("selected") is True
    ]
payload = {
    "project_type": project_type,
    "candidate_parcels": candidate_records,
}
if candidate_mode == "discovery" and discovery_report is not None:
    supervisor_session = current_supervisor
    if supervisor_session is not None:
        render_supervisor_analysis_status(api_url)
    payload["poi_evidence_snapshot_id"] = (
        discovery_report.poi_evidence_snapshot_id
    )


def render_analysis_action() -> None:
    supervisor_status = (
        current_supervisor.status.value
        if current_supervisor is not None
        else None
    )
    is_market_selection = (
        candidate_mode == "discovery"
        and discovery_report is not None
        and not discovery_report.formal_analysis_allowed
    )
    run_button_label = (
        "确认候选并运行商业选址分析"
        if is_market_selection
        else (
            "确认候选并运行完整分析"
            if candidate_mode == "discovery"
            else "运行分析"
        )
    )
    analysis_allowed = candidate_mode != "discovery" or (
        discovery_report is not None
        and current_supervisor is not None
        and current_supervisor.status.value == "awaiting_confirmation"
        and bool(candidate_records)
    )
    st.subheader("3. 确认候选并分析")
    if candidate_mode == "discovery":
        st.caption(
            "分析会按每个候选点及 Profile 服务半径复核 POI："
            "完整证据从发现快照本地裁剪；快照被截断、缺组或缺类别时，"
            "仅补查对应候选点附近范围，并优先复用查询缓存。"
        )
    if candidate_mode == "discovery" and supervisor_status == "completed":
        completed_run = st.session_state.get("site_selection_run")
        completed_payload = st.session_state.get("site_selection_payload")
        comparison = []
        if (
            completed_run is not None
            and completed_run.status.value == "completed"
            and completed_run.analysis is not None
        ):
            comparison = candidate_comparison_rows(
                completed_run,
                payload=completed_payload,
            )
        st.success(
            "商业选址分析已完成，无需再次确认候选。"
            "本区显示结果摘要，完整结果见下方“4. 分析结果”。"
        )
        if comparison:
            ranked_rows = [
                row for row in comparison if row.get("soft_rank") is not None
            ]
            soft_score_leader = min(
                ranked_rows or comparison,
                key=lambda row: row.get("soft_rank") or float("inf"),
            )
            leader_name = (
                soft_score_leader.get("candidate_name")
                or soft_score_leader["parcel_id"]
            )
            soft_score = soft_score_leader.get("soft_score")
            summary_a, summary_b, summary_c = st.columns([1, 2, 1])
            summary_a.metric("已分析候选", len(comparison))
            summary_b.metric("软评分第 1 名（待复核）", leader_name)
            summary_c.metric(
                "软评分",
                "--" if soft_score is None else f"{float(soft_score):.2f}",
            )
            st.caption(
                "软评分只表示当前 POI、交通、需求代理、竞品证据和版本化权重下的排序，"
                "不构成经营承诺、规划许可或最终选址推荐。"
            )
        return
    if candidate_mode == "discovery" and supervisor_status == "awaiting_analysis":
        st.info("候选已经确认，分析任务正在执行；状态会自动刷新，无需重复提交。")
        return
    if candidate_mode == "discovery" and supervisor_status in {
        "failed",
        "cancelled",
        "timed_out",
    }:
        st.warning("本轮分析未完成。请先查看上方任务状态，再决定是否重新发现候选。")
        return
    if is_market_selection:
        st.info(
            "当前将运行商业选址分析：继续完成 POI、交通、需求代理、"
            "竞品评分和候选对比；用地、规划与政策合规状态标记为待核验。"
        )
    if candidate_mode == "discovery" and not analysis_allowed:
        if supervisor_status != "awaiting_confirmation":
            st.caption("请先完成候选发现，待任务进入候选确认状态后再运行分析。")
        elif not candidate_records:
            st.caption("请在上方候选表中至少保留一个候选。")
    if not st.button(
        run_button_label,
        type="primary",
        icon=":material/play_arrow:",
        disabled=not analysis_allowed,
        width="stretch",
    ):
        return
    try:
        client = SiteSelectionAPIClient(api_url)
        if candidate_mode == "discovery":
            selected_candidate_ids = [
                str(item.get("parcel_id", "")).strip()
                for item in payload["candidate_parcels"]
                if str(item.get("parcel_id", "")).strip()
            ]
            with st.spinner("正在恢复任务并提交候选分析..."):
                completed_supervisor = client.confirm_supervisor(
                    current_supervisor.session_id,
                    checkpoint_id=current_supervisor.checkpoint_id,
                    selected_candidate_ids=selected_candidate_ids,
                    reviewer_id=reviewer_id,
                    note=confirmation_note or None,
                )
            store_supervisor_state(completed_supervisor, client=client)
            st.rerun()
        else:
            with st.spinner("正在提交选址任务..."):
                st.session_state.site_selection_run = client.create_run(
                    payload,
                    idempotency_key=f"workbench-{uuid4()}",
                )
            st.session_state.site_selection_payload = payload
    except (SiteSelectionAPIError, ValueError) as exc:
        st.error(str(exc))


def render_discovery_map(
    report,
    *,
    categories: list[str],
    chart_key: str | None = None,
) -> None:
    rows = discovery_map_rows(report, categories=categories)
    if not rows:
        return
    candidates_on_map = [row for row in rows if row["kind"] == "candidate"]
    coverage_on_map = [row for row in rows if row["kind"] == "coverage"]
    pois_on_map = [row for row in rows if row["kind"] == "poi"]
    view = map_view_state(rows)
    layers = []
    if pois_on_map:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=pois_on_map,
                get_position="[longitude, latitude]",
                get_fill_color="color",
                get_radius="radius_m",
                radius_min_pixels=3,
                radius_max_pixels=10,
                stroked=True,
                get_line_color=[255, 255, 255, 180],
                line_width_min_pixels=1,
                pickable=True,
            )
        )
    layers.extend(
        [
            pdk.Layer(
                "ScatterplotLayer",
                data=candidates_on_map,
                get_position="[longitude, latitude]",
                get_fill_color="color",
                get_radius="radius_m",
                radius_min_pixels=10,
                radius_max_pixels=24,
                stroked=True,
                get_line_color=[255, 255, 255, 255],
                line_width_min_pixels=3,
                pickable=True,
            ),
            pdk.Layer(
                "TextLayer",
                data=candidates_on_map,
                get_position="[longitude, latitude]",
                get_text="map_label",
                get_color=[17, 24, 39, 255],
                get_size=14,
                get_pixel_offset=[0, -22],
                billboard=True,
            ),
        ]
    )
    st.caption("候选地：红色大标记　范围 POI：按类别着色的小标记")
    st.pydeck_chart(
        pdk.Deck(
            map_style="light",
            initial_view_state=pdk.ViewState(**view, pitch=0),
            layers=layers,
            tooltip={
                "html": (
                    "<b>{name}</b><br/>类型：{kind}<br/>"
                    "类别：{category}<br/>来源：{provider}<br/>"
                    "市场评分：{market_score}<br/>用地：{land_use_class}"
                )
            },
        ),
        width="stretch",
        height=460,
        key=chart_key,
    )


if candidate_mode == "discovery" and discovery_report is not None:
    summary_a, summary_b, summary_c, summary_d, summary_e = st.columns(5)
    summary_a.metric("发现候选", len(discovery_report.candidates))
    summary_b.metric("用地排除", discovery_report.excluded_by_land_use_count)
    summary_c.metric("已评估单元", discovery_report.evaluated_candidate_count)
    summary_d.metric(
        "结果层级",
        {
            "registered_land": "登记用地",
            "public_land_observation": "公开实况",
            "commercial_land_proxy": "商业代理",
            "market_exploration": "市场探索",
        }[discovery_report.strategy.value],
    )
    summary_e.metric("边界内 POI", discovery_report.range_poi_observed_count)
    evidence_labels = {
        "authoritative": "权威数据",
        "public_observation": "公开观察",
        "synthetic": "合成演示",
        "unspecified": "暂无依据",
    }
    st.caption(
        "用地证据等级："
        + evidence_labels[discovery_report.land_evidence_level.value]
        + (
            " · 已命中缓存"
            if discovery_report.land_source_cache_hit
            else " · 本次查询"
        )
    )
    if discovery_report.land_source_uri is not None:
        st.caption(
            "用地来源："
            f"{discovery_report.land_source_uri} · "
            f"许可：{discovery_report.land_source_license or '未声明'}"
        )
    online_range_poi_count = sum(
        not item.is_synthetic for item in discovery_report.range_pois
    )
    synthetic_range_poi_count = sum(
        item.is_synthetic for item in discovery_report.range_pois
    )
    fallback_source_count = sum(
        source.fallback_from is not None for source in discovery_report.sources
    )
    quality_a, quality_b, quality_c = st.columns(3)
    quality_a.metric(
        "评分缓冲区 POI",
        discovery_report.poi_evidence_snapshot_record_count,
    )
    quality_b.metric("边界内真实 POI", online_range_poi_count)
    quality_c.metric(
        "Fixture 降级批次",
        f"{fallback_source_count}/{len(discovery_report.sources)}",
    )
    repair_a, repair_b, repair_c, repair_d = st.columns(4)
    repair_a.metric("分区补查评分组", discovery_report.poi_repair_group_count)
    repair_b.metric(
        "补查成功分区",
        (
            f"{discovery_report.poi_repair_success_count}/"
            f"{discovery_report.poi_repair_query_count}"
        ),
    )
    repair_c.metric(
        "补查新增真实 POI",
        discovery_report.poi_repair_added_record_count,
    )
    repair_d.metric(
        "仍不完整评分组",
        len(discovery_report.incomplete_scoring_groups),
    )
    poi_trace = next(
        (
            trace
            for trace in discovery_report.agent_trace
            if trace.node_id == "poi_market_evidence"
        ),
        None,
    )
    timing_a, timing_b, timing_c = st.columns(3)
    timing_a.metric(
        "发现总耗时",
        f"{discovery_report.total_elapsed_ms / 1_000:.2f}s",
    )
    timing_b.metric(
        "POI 证据耗时",
        f"{(poi_trace.elapsed_ms if poi_trace else 0) / 1_000:.2f}s",
    )
    cache_hit_count = sum(
        source.cache_hit for source in discovery_report.sources
    )
    timing_c.metric(
        "缓存命中批次",
        f"{cache_hit_count}/{len(discovery_report.sources)}",
    )
    if discovery_report.poi_evidence_snapshot_id is not None:
        st.info(
            "评分证据快照覆盖候选点的服务半径，可能包含搜索边界外的缓冲区 POI；"
            "地图只显示原始搜索边界内的记录。本次已冻结 "
            f"{discovery_report.poi_evidence_snapshot_record_count} 条去重 POI。"
            "正式分析会按候选点和 Profile 半径重新裁剪；"
            "完整组直接复用，截断、缺组或缺类别时才按候选点补查。"
        )
    if fallback_source_count:
        st.warning(
            f"本次边界内真实在线 POI 为 {online_range_poi_count} 条，"
            f"Fixture 为 {synthetic_range_poi_count} 条；"
            f"{fallback_source_count} 个查询批次发生在线降级。"
            "该结果适合流程演示，不代表完整城市覆盖。"
        )
    if discovery_report.poi_repair_group_count:
        st.info(
            "发现阶段已对降级、截断或缺类别的评分组执行 2×2 分区补查，"
            "成功的真实记录已合并去重并重新用于候选评分和地图展示。"
        )
    if discovery_report.incomplete_scoring_groups:
        st.warning(
            "以下评分组补查后仍不完整，当前排名需要结合数据质量复核："
            + "、".join(discovery_report.incomplete_scoring_groups)
        )
    demo_land_dataset_ids = sorted(
        {
            item.land_use_dataset_id
            for item in discovery_report.candidates
            if item.land_use_dataset_id is not None
            and item.land_use_dataset_id.startswith("demo-")
        }
    )
    if demo_land_dataset_ids:
        st.warning(
            "本次用地依据来自版本化合成演示数据（"
            + "、".join(demo_land_dataset_ids)
            + "），仅用于验证候选发现、人工确认、GIS/规则分析和报告链路，"
            "不代表真实规划许可。"
        )
    if discovery_report.strategy.value == "public_land_observation":
        st.info(
            "已加载范围内的 OSM 商业/零售用地或商业建筑多边形，"
            "候选点不再来自规则网格。该数据属于公开实况观察，"
            "可用于商业初筛，但不是自然资源部门的法定用途或权属证明。"
        )
    if not discovery_report.formal_analysis_allowed:
        st.warning(
            "当前范围未取得可核验用地依据。你仍可根据已输入的需求运行"
            "商业选址分析；系统会将用地、规划与政策合规状态标记为待核验，"
            "不会把市场网格冒充为合法地块。"
        )
        with st.expander("演示与开发选项"):
            st.caption("仅在需要演示完整 GIS/规则链路时使用版本化合成用地。")
            st.button(
                "使用演示用地重新发现",
                icon=":material/science:",
                key=f"fixture-land-demo-main-{project_type}",
                on_click=queue_fixture_land_demo_discovery,
            )
    if discovery_report.warnings:
        with st.expander(
            f"数据质量与降级说明（{len(discovery_report.warnings)} 条）"
        ):
            for warning in discovery_report.warnings:
                st.warning(warning)
    st.dataframe(
        discovery_candidate_rows(discovery_report),
        hide_index=True,
        width="stretch",
    )
    render_analysis_action()
    st.subheader("POI 分布与证据来源")
    discovery_categories = available_discovery_poi_categories(discovery_report)
    selected_discovery_categories = st.multiselect(
        "范围 POI 类别",
        options=discovery_categories,
        default=discovery_categories,
        key=f"discovery-poi-categories-{project_type}",
    )
    render_discovery_map(
        discovery_report,
        categories=selected_discovery_categories,
    )
    with st.expander("范围 POI 数据与来源"):
        st.dataframe(
            [item.model_dump(mode="json") for item in discovery_report.range_pois],
            hide_index=True,
            width="stretch",
        )
        st.dataframe(
            [
                {
                    "证据组": item.group_key,
                    "用途": item.purpose.value,
                    "来源": item.provider.value,
                    "记录数": item.record_count,
                    "可用记录": item.available_record_count,
                    "合成数据": item.is_synthetic,
                    "降级自": (
                        item.fallback_from.value
                        if item.fallback_from is not None
                        else None
                    ),
                    "降级原因": item.fallback_reason,
                    "缓存命中": item.cache_hit,
                    "证据完整": item.evidence_complete,
                    "不完整原因": "；".join(item.incomplete_reasons),
                    "已分区补查": item.repair_attempted,
                    "补查成功/查询": (
                        f"{item.repair_success_count}/{item.repair_query_count}"
                    ),
                    "补查新增记录": item.repair_added_record_count,
                }
                for item in discovery_report.sources
            ],
            hide_index=True,
            width="stretch",
        )
    with st.expander("候选发现阶段耗时"):
        st.dataframe(
            [
                {
                    "node_id": trace.node_id,
                    "role": trace.role.value,
                    "skill_name": trace.skill_name,
                    "status": trace.status.value,
                    "elapsed_ms": round(trace.elapsed_ms, 3),
                }
                for trace in discovery_report.agent_trace
            ],
            hide_index=True,
            width="stretch",
        )


def render_result_map_rows(
    rows: list[dict],
    *,
    caption: str,
    chart_key: str | None = None,
) -> None:
    if not rows:
        st.info("当前没有可展示的空间点位。")
        return
    candidates_on_map = [row for row in rows if row["kind"] == "candidate"]
    coverage_on_map = [row for row in rows if row["kind"] == "coverage"]
    pois_on_map = [
        {
            "line_color": [255, 255, 255, 180],
            "evidence_origin": "范围背景",
            "candidate_ids": "",
            "group_keys": row.get("source_group_keys", ""),
            "distance_m": None,
            "soft_score": None,
            **row,
        }
        for row in rows
        if row["kind"] == "poi"
    ]
    view = map_view_state(rows)
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            data=candidates_on_map,
            get_position="[longitude, latitude]",
            get_fill_color="color",
            get_radius="radius_m",
            radius_min_pixels=11,
            radius_max_pixels=26,
            stroked=True,
            get_line_color=[255, 255, 255, 255],
            line_width_min_pixels=3,
            pickable=True,
        ),
        pdk.Layer(
            "TextLayer",
            data=candidates_on_map,
            get_position="[longitude, latitude]",
            get_text="label",
            get_color=[17, 24, 39, 255],
            get_size=15,
            get_pixel_offset=[0, -24],
            get_text_anchor="middle",
            get_alignment_baseline="bottom",
            billboard=True,
            pickable=True,
        ),
    ]
    if coverage_on_map:
        layers.insert(
            0,
            pdk.Layer(
                "ScatterplotLayer",
                data=coverage_on_map,
                get_position="[longitude, latitude]",
                get_radius="radius_m",
                filled=False,
                stroked=True,
                get_line_color="line_color",
                line_width_min_pixels=1,
                pickable=True,
            ),
        )
    if pois_on_map:
        layers.insert(
            0,
            pdk.Layer(
                "ScatterplotLayer",
                data=pois_on_map,
                get_position="[longitude, latitude]",
                get_fill_color="color",
                get_radius="radius_m",
                radius_min_pixels=3,
                radius_max_pixels=11,
                stroked=True,
                get_line_color="line_color",
                line_width_min_pixels=1,
                pickable=True,
            ),
        )
    st.caption(caption)
    st.pydeck_chart(
        pdk.Deck(
            map_style="light",
            initial_view_state=pdk.ViewState(
                latitude=view["latitude"],
                longitude=view["longitude"],
                zoom=view["zoom"],
                pitch=0,
            ),
            layers=layers,
            tooltip={
                "html": (
                    "<b>{name}</b><br/>"
                    "类型：{kind}<br/>"
                    "类别：{category}<br/>"
                    "来源：{provider}<br/>"
                    "距离：{distance_m}<br/>"
                    "证据路径：{evidence_origin}<br/>"
                    "关联候选：{candidate_ids}<br/>"
                    "评分组：{group_keys}<br/>"
                    "软评分：{soft_score}"
                ),
                "style": {
                    "backgroundColor": "#111827",
                    "color": "#f9fafb",
                },
            },
        ),
        width="stretch",
        height=520,
        key=chart_key,
    )


def render_evidence_map(
    active_payload: dict,
    active_run,
    *,
    categories: list[str] | None = None,
    candidate_ids: list[str] | None = None,
    chart_key: str | None = None,
) -> None:
    rows = map_rows(
        active_payload,
        active_run,
        categories=categories,
        candidate_ids=candidate_ids,
    )
    if candidate_ids is not None and len(candidate_ids) == 1:
        rows = [
            *candidate_radius_rows(
                active_payload,
                active_run,
                candidate_ids[0],
            ),
            *rows,
        ]
    render_result_map_rows(
        rows,
        caption=(
            "候选地：红色大标记　POI：按类别着色的小标记　"
            "青色细环：在线补查成功　橙色细环：合成数据　"
            "聚焦单个候选时显示 Profile 服务半径"
        ),
        chart_key=chart_key,
    )


ANALYSIS_POI_MAP_MODE = "评分证据（候选局部）"
BACKGROUND_POI_MAP_MODE = "发现背景（完整范围）"


def render_result_poi_map(
    active_payload: dict,
    active_run,
    active_discovery_report,
    *,
    key_prefix: str,
    show_filters: bool,
) -> tuple[str, list[str]]:
    mode_options = [ANALYSIS_POI_MAP_MODE]
    if active_discovery_report is not None:
        mode_options.append(BACKGROUND_POI_MAP_MODE)
    map_mode = st.segmented_control(
        "地图口径",
        options=mode_options,
        default=ANALYSIS_POI_MAP_MODE,
        key=f"{key_prefix}-{active_run.run_id}-poi-map-mode",
    ) or ANALYSIS_POI_MAP_MODE

    if map_mode == BACKGROUND_POI_MAP_MODE:
        categories = available_discovery_poi_categories(
            active_discovery_report
        )
        selected = (
            st.multiselect(
                "范围背景 POI 类别",
                options=categories,
                default=categories,
                key=(
                    f"{key_prefix}-{active_run.run_id}-"
                    "background-poi-categories"
                ),
            )
            if show_filters
            else categories
        )
        background_rows = discovery_map_rows(
            active_discovery_report,
            categories=selected,
        )
        visible_pois = [
            row for row in background_rows if row["kind"] == "poi"
        ]
        visible_real_pois = sum(
            not row.get("is_synthetic", False) for row in visible_pois
        )
        metric_a, metric_b, metric_c, metric_d = st.columns(4)
        metric_a.metric("边界内背景 POI", len(visible_pois))
        metric_b.metric("显示类别", len(selected))
        metric_c.metric(
            "冻结评分缓冲 POI",
            active_discovery_report.poi_evidence_snapshot_record_count,
        )
        metric_d.metric("显示真实 POI", visible_real_pois)
        st.info(
            "当前显示候选发现阶段的完整范围背景，数据直接来自上方同一个 "
            "range_pois；它用于理解区域环境，并不表示每条记录都进入了候选评分。"
        )
        st.caption("类别口径｜显示候选发现阶段的范围背景类别")
        render_result_map_rows(
            background_rows,
            caption="候选地：红色大标记　范围 POI：按类别着色的小标记",
            chart_key=f"{key_prefix}-poi-map",
        )
        return map_mode, selected

    categories = available_poi_categories(active_run)
    selected = (
        st.multiselect(
            "评分 POI 类别",
            options=categories,
            default=categories,
            key=(
                f"{key_prefix}-{active_run.run_id}-"
                "analysis-poi-categories"
            ),
        )
        if show_filters
        else categories
    )
    candidate_options = [
        item["parcel_id"]
        for item in active_payload.get("candidate_parcels", [])
    ]
    focused_candidate = "全部候选"
    if show_filters and candidate_options:
        focused_candidate = st.selectbox(
            "地图聚焦候选",
            options=["全部候选", *candidate_options],
            key=f"{key_prefix}-{active_run.run_id}-focused-candidate",
            help="选择单个候选后，地图只显示该点的评分 POI 与服务半径。",
        )
    selected_candidate_ids = (
        None if focused_candidate == "全部候选" else [focused_candidate]
    )
    association_rows = poi_record_rows(
        active_run,
        categories=selected,
        candidate_ids=selected_candidate_ids,
    )
    analysis_rows = map_rows(
        active_payload,
        active_run,
        categories=selected,
        candidate_ids=selected_candidate_ids,
    )
    unique_pois = [row for row in analysis_rows if row["kind"] == "poi"]
    reused_pois = sum(
        "发现快照裁剪" in row.get("evidence_origin", "")
        for row in unique_pois
    )
    supplemented_pois = sum(
        "候选点补查" in row.get("evidence_origin", "")
        for row in unique_pois
    )
    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("分析唯一 POI", len(unique_pois))
    metric_b.metric("候选-POI 关联", len(association_rows))
    metric_c.metric("快照裁剪 POI", reused_pois)
    metric_d.metric("局部补查 POI", supplemented_pois)
    st.info(
        "当前只显示真正进入评分的局部证据：先从候选发现快照按 Profile "
        "服务半径裁剪，快照截断、缺组或缺类别时才补查候选点附近 POI。"
    )
    coverage_rows = poi_candidate_coverage_rows(active_run)
    comparability_rows = poi_group_comparability_rows(active_run)
    incomplete_candidates = sum(
        row["evidence_status"] != "完整可比" for row in coverage_rows
    )
    incomparable_groups = [
        row["group_key"]
        for row in comparability_rows
        if row["comparability"] != "可横向比较"
    ]
    if incomplete_candidates:
        st.warning(
            f"{incomplete_candidates} 个候选存在合成、截断或补查失败证据；"
            "这些差异不能直接解释为真实商业密度差异。"
        )
    if incomparable_groups:
        st.caption(
            "不可直接横向比较的评分组｜" + "、".join(incomparable_groups)
        )
    if show_filters:
        with st.expander("候选 POI 覆盖与可比性", expanded=incomplete_candidates > 0):
            st.dataframe(
                coverage_rows,
                hide_index=True,
                width="stretch",
            )
            st.dataframe(
                comparability_rows,
                hide_index=True,
                width="stretch",
            )
    if active_discovery_report is not None:
        background_categories = set(
            available_discovery_poi_categories(active_discovery_report)
        )
        analysis_categories = set(categories)
        background_only = sorted(background_categories - analysis_categories)
        analysis_only = sorted(analysis_categories - background_categories)
        differences = []
        if background_only:
            differences.append("仅范围背景：" + "、".join(background_only))
        if analysis_only:
            differences.append("仅评分证据：" + "、".join(analysis_only))
        st.caption(
            "类别口径差异｜" + (
                "；".join(differences) if differences else "与范围背景一致"
            )
        )
    render_evidence_map(
        active_payload,
        active_run,
        categories=selected,
        candidate_ids=selected_candidate_ids,
        chart_key=f"{key_prefix}-poi-map",
    )
    return map_mode, selected


ACTIVE_RUN_STATUSES = {"queued", "running"}


@st.fragment(run_every=2)
def render_live_run_status(active_api_url: str) -> None:
    current = st.session_state.get("site_selection_run")
    if current is None:
        return
    was_active = current.status.value in ACTIVE_RUN_STATUSES
    if was_active:
        try:
            current = SiteSelectionAPIClient(active_api_url).get_run(
                current.run_id
            )
            st.session_state.site_selection_run = current
        except SiteSelectionAPIError as exc:
            st.warning(f"自动更新暂时失败：{exc}")

    status_col, updated_col, report_col = st.columns([1, 1, 2])
    status_col.metric("运行状态", current.status.value)
    updated_col.metric("更新时间", current.updated_at.strftime("%H:%M:%S"))
    report_col.metric("运行编号", current.run_id)

    if current.status.value in ACTIVE_RUN_STATUSES:
        st.caption("状态每 2 秒自动更新")
        refresh_col, cancel_col = st.columns(2)
        if refresh_col.button(
            "立即刷新",
            icon=":material/refresh:",
            width="stretch",
        ):
            try:
                st.session_state.site_selection_run = (
                    SiteSelectionAPIClient(active_api_url).get_run(
                        current.run_id
                    )
                )
                st.rerun()
            except SiteSelectionAPIError as exc:
                st.error(str(exc))
        if cancel_col.button(
            "取消任务",
            icon=":material/cancel:",
            width="stretch",
        ):
            try:
                st.session_state.site_selection_run = (
                    SiteSelectionAPIClient(active_api_url).cancel_run(
                        current.run_id
                    )
                )
                st.rerun()
            except SiteSelectionAPIError as exc:
                st.error(str(exc))
    if was_active and current.status.value not in ACTIVE_RUN_STATUSES:
        st.rerun()

if candidate_mode != "discovery":
    render_analysis_action()

run = st.session_state.get("site_selection_run")
run_payload = st.session_state.get("site_selection_payload")
if run is not None and run_payload is not None:
    st.divider()
    st.subheader("4. 分析结果")
    render_live_run_status(api_url)
    run = st.session_state.site_selection_run

    if run.status.value in ACTIVE_RUN_STATUSES:
        if run.status.value == "queued":
            st.info("任务已进入队列，等待 Worker 执行。")
        else:
            st.info("Worker 正在执行空间分析、证据解释和报告生成。")
        st.stop()

    if run.status.value in {"failed", "timed_out", "cancelled"}:
        message = run.error or {
            "cancelled": "任务已取消。",
            "timed_out": "任务执行超时。",
            "failed": "任务执行失败。",
        }[run.status.value]
        if run.status.value == "cancelled":
            st.warning(message)
        else:
            st.error(message)
        st.stop()

    if run.analysis is None:
        st.error("运行已结束，但未返回分析结果。")
        st.stop()

    if run.human_review is not None:
        if run.human_review.status.value == "pending":
            st.warning(
                "该结果需要人工复核："
                + ", ".join(run.human_review.reason_codes)
            )
            if st.button(
                "确认已阅",
                icon=":material/fact_check:",
                help="仅确认已查看风险证据，不代表合规批准或选址推荐。",
            ):
                try:
                    client = SiteSelectionAPIClient(api_url)
                    st.session_state.site_selection_run = (
                        client.acknowledge_human_review(run.run_id)
                    )
                    st.rerun()
                except SiteSelectionAPIError as exc:
                    st.error(str(exc))
        elif run.human_review.status.value == "acknowledged":
            st.info("人工复核风险项已确认查看；该操作不代表合规批准。")

    if run.trace:
        with st.expander("运行耗时"):
            st.dataframe(
                [trace.model_dump(mode="json") for trace in run.trace],
                hide_index=True,
                width="stretch",
            )

    comparison_tab, poi_tab, agent_tab, evidence_tab, report_tab = st.tabs(
        ["候选对比", "POI", "Agent 运行", "证据", "报告"]
    )
    with comparison_tab:
        comparison = candidate_comparison_rows(run, payload=run_payload)
        st.dataframe(comparison, hide_index=True, width="stretch")
        render_result_poi_map(
            run_payload,
            run,
            discovery_report,
            key_prefix="comparison",
            show_filters=False,
        )

    with poi_tab:
        source_rows = poi_source_rows(run)
        supplemented_rows = [
            row for row in source_rows if row["evidence_supplemented"]
        ]
        supplement_failed_rows = [
            row for row in source_rows if row["evidence_supplement_error"]
        ]
        if run.poi_evidence_snapshot_reused:
            st.info(
                "本次正式分析复用了候选发现 POI 证据快照："
                f"{run.poi_evidence_snapshot_id}。"
                "地图只展示项目评分类别及各候选局部半径内的证据，"
                "不会展示上方仅用于背景理解的全部范围类别。"
            )
        if supplemented_rows:
            st.info(
                f"{len(supplemented_rows)} 个候选点评分查询因快照截断或缺失，"
                "已按实际服务半径补充查询附近 POI；来源明细保留补采原因、"
                "Provider 与缓存命中状态。"
            )
        if supplement_failed_rows:
            st.warning(
                f"{len(supplement_failed_rows)} 个候选点 POI 补查失败，"
                "当前保留已有快照局部证据并标记为不完整，请查看补采失败原因。"
            )
        if any(row["is_synthetic"] for row in source_rows):
            st.warning(candidate_catalog.quality_notice)
        if any(row["is_truncated"] for row in source_rows):
            st.warning(
                "部分 POI 查询达到返回上限，数量和密度仅表示下界，"
                "已进入人工复核。"
            )
        st.dataframe(source_rows, hide_index=True, width="stretch")
        map_mode, selected = render_result_poi_map(
            run_payload,
            run,
            discovery_report,
            key_prefix="evidence",
            show_filters=True,
        )
        if map_mode == BACKGROUND_POI_MAP_MODE:
            st.subheader("范围背景 POI 明细")
            st.dataframe(
                [
                    item.model_dump(mode="json")
                    for item in discovery_report.range_pois
                    if not selected or item.category in selected
                ],
                hide_index=True,
                width="stretch",
            )
        else:
            st.subheader("候选局部评分证据明细")
            poi_rows = poi_record_rows(run, categories=selected)
            st.dataframe(poi_rows, hide_index=True, width="stretch")
            st.dataframe(
                poi_metric_rows(run),
                hide_index=True,
                width="stretch",
            )

    with agent_tab:
        plan_rows = agent_plan_rows(run)
        trace_rows = agent_trace_rows(run)
        review_rows = evidence_review_rows(run)
        if run.analysis.execution_plan is not None:
            st.caption(
                "执行计划："
                f"{run.analysis.execution_plan.plan_id}@"
                f"{run.analysis.execution_plan.version}"
            )
        st.subheader("执行计划")
        st.dataframe(plan_rows, hide_index=True, width="stretch")
        st.subheader("节点轨迹")
        st.dataframe(trace_rows, hide_index=True, width="stretch")
        st.subheader("质量门禁")
        st.dataframe(review_rows, hide_index=True, width="stretch")

    with evidence_tab:
        if run.explanation is not None:
            st.subheader("LLM 证据解释")
            st.caption(run.explanation.boundary_notice)
            if run.explanation.status.value == "generated":
                st.write(run.explanation.summary)
                for note in run.explanation.candidate_notes:
                    st.markdown(f"**{note.parcel_id}**")
                    st.write(note.explanation)
                    st.caption("证据引用：" + ", ".join(note.evidence_references))
            elif run.explanation.status.value == "failed":
                st.warning(run.explanation.error)
            else:
                st.info("当前运行未配置 LLM 证据解释。")
        for result in run.analysis.results:
            st.subheader(result.parcel_id)
            gis_col, policy_col = st.columns(2)
            gis_col.dataframe(
                [
                    {"metric": key, "value": value}
                    for key, value in result.gis_evidence.metrics.items()
                ],
                hide_index=True,
                width="stretch",
            )
            policy_col.dataframe(
                [
                    {
                        "rule_id": finding.rule_id,
                        "outcome": finding.outcome.value,
                        "clause": finding.policy_clause,
                        "source": finding.source_uri,
                    }
                    for finding in result.policy_evidence.rule_findings
                ],
                hide_index=True,
                width="stretch",
            )

    with report_tab:
        if run.report_url:
            client = SiteSelectionAPIClient(api_url)
            st.link_button(
                "打开报告",
                SiteSelectionAPIClient(public_api_url).absolute_url(
                    run.report_url
                ),
                icon=":material/open_in_new:",
            )
            try:
                report_bytes = client.download_report(run.report_url)
                st.download_button(
                    "下载 Word 报告",
                    data=report_bytes,
                    file_name=f"site-selection-{run.run_id}.docx",
                    mime=(
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    icon=":material/download:",
                )
            except SiteSelectionAPIError as exc:
                st.error(str(exc))
        else:
            st.warning("当前运行未生成报告产物")

    st.caption(
        "软评分、政策结果和人工复核状态分开展示；页面不生成总体合规结论或选址推荐。"
    )
