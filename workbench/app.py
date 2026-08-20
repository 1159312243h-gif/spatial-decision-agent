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
    available_poi_categories,
    candidate_comparison_rows,
    evidence_review_rows,
    map_rows,
    map_view_state,
    poi_metric_rows,
    poi_record_rows,
    poi_source_rows,
)
from practice.site_selection import ProjectType, load_fixture_candidate_catalog


st.set_page_config(
    page_title="选址证据工作台",
    page_icon=":material/map:",
    layout="wide",
)

st.title("选址证据工作台")

api_url = st.sidebar.text_input(
    "API 地址",
    value=os.getenv("SITE_SELECTION_API_URL", "http://localhost:8000"),
)
public_api_url = (
    os.getenv("SITE_SELECTION_PUBLIC_API_URL", "").strip() or api_url
)
project_type = st.sidebar.radio(
    "项目类型",
    options=["shopping_mall", "logistics_park"],
    format_func=lambda value: {
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

editor_key = f"candidate-editor-{project_type}"
candidates = st.data_editor(
    pd.DataFrame(defaults[project_type]),
    key=editor_key,
    hide_index=True,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
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

payload = {
    "project_type": project_type,
    "candidate_parcels": candidates.where(pd.notnull(candidates), None).to_dict(
        orient="records"
    ),
}


def render_evidence_map(
    active_payload: dict,
    active_run,
    *,
    categories: list[str] | None = None,
) -> None:
    rows = map_rows(active_payload, active_run, categories=categories)
    if not rows:
        st.info("当前没有可展示的空间点位。")
        return
    candidates_on_map = [row for row in rows if row["kind"] == "candidate"]
    pois_on_map = [row for row in rows if row["kind"] == "poi"]
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
                get_line_color=[255, 255, 255, 180],
                line_width_min_pixels=1,
                pickable=True,
            ),
        )
    st.caption("候选地：红色大标记　POI：按类别着色的小标记")
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
                    "软评分：{soft_score}"
                ),
                "style": {
                    "backgroundColor": "#111827",
                    "color": "#f9fafb",
                },
            },
        ),
        use_container_width=True,
        height=520,
    )


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
            use_container_width=True,
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
            use_container_width=True,
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

if st.button("运行分析", type="primary", icon=":material/play_arrow:"):
    try:
        client = SiteSelectionAPIClient(api_url)
        with st.spinner("正在提交选址任务..."):
            st.session_state.site_selection_run = client.create_run(
                payload,
                idempotency_key=f"workbench-{uuid4()}",
            )
        st.session_state.site_selection_payload = payload
    except (SiteSelectionAPIError, ValueError) as exc:
        st.error(str(exc))

run = st.session_state.get("site_selection_run")
run_payload = st.session_state.get("site_selection_payload")
if run is not None and run_payload is not None:
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
        st.dataframe(comparison, hide_index=True, use_container_width=True)
        render_evidence_map(run_payload, run)

    with poi_tab:
        source_rows = poi_source_rows(run)
        if any(row["is_synthetic"] for row in source_rows):
            st.warning(candidate_catalog.quality_notice)
        if any(row["is_truncated"] for row in source_rows):
            st.warning(
                "部分 POI 查询达到返回上限，数量和密度仅表示下界，"
                "已进入人工复核。"
            )
        st.dataframe(source_rows, hide_index=True, use_container_width=True)
        categories = available_poi_categories(run)
        selected = st.multiselect(
            "POI 类别",
            options=categories,
            default=categories,
        )
        poi_rows = poi_record_rows(run, categories=selected)
        render_evidence_map(run_payload, run, categories=selected)
        st.dataframe(poi_rows, hide_index=True, use_container_width=True)
        st.dataframe(
            poi_metric_rows(run),
            hide_index=True,
            use_container_width=True,
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
        st.dataframe(plan_rows, hide_index=True, use_container_width=True)
        st.subheader("节点轨迹")
        st.dataframe(trace_rows, hide_index=True, use_container_width=True)
        st.subheader("质量门禁")
        st.dataframe(review_rows, hide_index=True, use_container_width=True)

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
                use_container_width=True,
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
                use_container_width=True,
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
