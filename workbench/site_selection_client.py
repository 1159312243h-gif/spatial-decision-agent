from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from hashlib import sha256
from math import cos, log2, radians
from typing import Any
from urllib.parse import urljoin

import httpx

from app.schemas.site_selection import (
    SiteSelectionRunResponse,
    SiteSelectionSupervisorEventsResponse,
    SiteSelectionSupervisorResponse,
)
from app.schemas.chat import ChatResponse, ChatSessionResponse
from practice.site_selection import CandidateDiscoveryReport
from practice.site_selection.storage import RunStatus


SUPERVISOR_START_TIMEOUT_SECONDS = 150


class SiteSelectionAPIError(RuntimeError):
    """A sanitized HTTP error returned by the site-selection API."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class SiteSelectionAPIClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 90,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("API 地址不能为空")
        if timeout_seconds <= 0:
            raise ValueError("API 超时必须大于 0")
        self._base_url = normalized
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    def create_run(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> SiteSelectionRunResponse:
        response = self._request(
            "POST",
            "/site-selection/runs",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        return SiteSelectionRunResponse.model_validate(response.json())

    def chat(
        self,
        question: str,
        *,
        project_type: str,
        session_id: str | None = None,
    ) -> ChatResponse:
        response = self._request(
            "POST",
            "/chat",
            json={
                "question": question,
                "project_type": project_type,
                "session_id": session_id,
            },
        )
        return ChatResponse.model_validate(response.json())

    def get_chat(self, session_id: str) -> ChatSessionResponse:
        response = self._request("GET", f"/chat/{session_id}")
        return ChatSessionResponse.model_validate(response.json())

    def confirm_chat_scenario(
        self,
        session_id: str,
        *,
        version_id: str,
        confirmed_by: str,
    ) -> ChatResponse:
        response = self._request(
            "POST",
            f"/chat/{session_id}/confirm",
            json={
                "version_id": version_id,
                "confirmed_by": confirmed_by,
            },
        )
        return ChatResponse.model_validate(response.json())

    def discover_candidates(
        self,
        payload: dict[str, Any],
    ) -> CandidateDiscoveryReport:
        response = self._request(
            "POST",
            "/site-selection/candidates/discover",
            json=payload,
        )
        return CandidateDiscoveryReport.model_validate(response.json())

    def start_supervisor(
        self,
        payload: dict[str, Any],
    ) -> SiteSelectionSupervisorResponse:
        response = self._request(
            "POST",
            "/site-selection/supervisor/sessions",
            json=payload,
            request_timeout_seconds=max(
                self._timeout_seconds,
                SUPERVISOR_START_TIMEOUT_SECONDS,
            ),
            timeout_message=(
                "候选发现超时：在线 POI 分区补查仍未完成，请稍后重试；"
                "已完成的在线查询缓存可供下一次复用"
            ),
        )
        return SiteSelectionSupervisorResponse.model_validate(response.json())

    def get_supervisor(
        self,
        session_id: str,
    ) -> SiteSelectionSupervisorResponse:
        response = self._request(
            "GET",
            f"/site-selection/supervisor/sessions/{session_id}",
        )
        return SiteSelectionSupervisorResponse.model_validate(response.json())

    def confirm_supervisor(
        self,
        session_id: str,
        *,
        checkpoint_id: str,
        selected_candidate_ids: list[str],
        reviewer_id: str,
        note: str | None = None,
    ) -> SiteSelectionSupervisorResponse:
        response = self._request(
            "POST",
            f"/site-selection/supervisor/sessions/{session_id}/confirm",
            json={
                "expected_checkpoint_id": checkpoint_id,
                "selected_candidate_ids": selected_candidate_ids,
                "reviewer_id": reviewer_id,
                "note": note,
            },
        )
        return SiteSelectionSupervisorResponse.model_validate(response.json())

    def get_supervisor_events(
        self,
        session_id: str,
    ) -> SiteSelectionSupervisorEventsResponse:
        response = self._request(
            "GET",
            f"/site-selection/supervisor/sessions/{session_id}/events",
        )
        return SiteSelectionSupervisorEventsResponse.model_validate(
            response.json()
        )

    def get_run(self, run_id: str) -> SiteSelectionRunResponse:
        response = self._request("GET", f"/site-selection/runs/{run_id}")
        return SiteSelectionRunResponse.model_validate(response.json())

    def cancel_run(self, run_id: str) -> SiteSelectionRunResponse:
        response = self._request(
            "POST",
            f"/site-selection/runs/{run_id}/cancel",
        )
        return SiteSelectionRunResponse.model_validate(response.json())

    def acknowledge_human_review(
        self,
        run_id: str,
        *,
        note: str | None = None,
    ) -> SiteSelectionRunResponse:
        response = self._request(
            "POST",
            f"/site-selection/runs/{run_id}/human-review/acknowledge",
            json={"note": note},
        )
        return SiteSelectionRunResponse.model_validate(response.json())

    def download_report(self, report_url: str) -> bytes:
        response = self._request("GET", report_url)
        expected = (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
        if not response.headers.get("content-type", "").startswith(expected):
            raise SiteSelectionAPIError(
                response.status_code,
                "invalid_report_content_type",
                "报告下载接口未返回 Word 文档",
            )
        return response.content

    def absolute_url(self, path: str) -> str:
        return urljoin(self._base_url + "/", path.lstrip("/"))

    def _request(
        self,
        method: str,
        path: str,
        *,
        request_timeout_seconds: float | None = None,
        timeout_message: str | None = None,
        **kwargs,
    ) -> httpx.Response:
        request_timeout = request_timeout_seconds or self._timeout_seconds
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=request_timeout,
                transport=self._transport,
            ) as client:
                response = client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise SiteSelectionAPIError(
                504,
                "api_timeout",
                timeout_message or "选址 API 调用超时",
            ) from exc
        except httpx.HTTPError as exc:
            raise SiteSelectionAPIError(
                503,
                "api_unavailable",
                "无法连接选址 API",
            ) from exc
        if response.is_error:
            code, message = _error_detail(response)
            raise SiteSelectionAPIError(response.status_code, code, message)
        return response


def supervisor_completed_run(
    session: SiteSelectionSupervisorResponse,
) -> SiteSelectionRunResponse:
    if session.status.value != "completed" or session.analysis is None:
        raise ValueError("Supervisor session 尚未完成正式分析")
    updated_at = (
        session.confirmation.confirmed_at
        if session.confirmation is not None
        else None
    ) or datetime.now(timezone.utc)
    return SiteSelectionRunResponse(
        run_id=f"supervisor-{session.session_id}",
        status=RunStatus.COMPLETED,
        updated_at=updated_at,
        request_id=session.analysis.request_id,
        analysis=session.analysis,
        poi_evidence_snapshot_id=(
            session.discovery_report.poi_evidence_snapshot_id
            if session.discovery_report is not None
            else None
        ),
        poi_evidence_snapshot_reused=True,
    )


def candidate_comparison_rows(
    run: SiteSelectionRunResponse,
    *,
    payload: dict[str, Any] | None = None,
) -> list[dict]:
    analysis = _require_analysis(run)
    report = analysis.comparison_report
    if report is None:
        return []
    results = {result.parcel_id: result for result in analysis.results}
    names = {
        item["parcel_id"]: item.get("name")
        for item in (payload or {}).get("candidate_parcels", [])
    }
    rows = []
    for item in report.candidates:
        result = results[item.parcel_id]
        feature_sets = result.poi_evidence.feature_sets
        rows.append(
            {
                "parcel_id": item.parcel_id,
                "candidate_name": names.get(item.parcel_id),
                "soft_rank": item.soft_rank,
                "soft_score": item.soft_score,
                "policy_outcomes": ", ".join(
                    outcome.value for outcome in item.policy_outcomes
                )
                or "none",
                "gis_crs": result.gis_evidence.crs,
                "review_required": bool(item.policy_outcomes),
                "poi_groups_with_hits": sum(
                    bool(feature_set.records) for feature_set in feature_sets
                ),
                "poi_groups_total": len(feature_sets),
                "poi_records_matched": sum(
                    len(feature_set.records) for feature_set in feature_sets
                ),
                "synthetic_poi": any(
                    feature_set.source.is_synthetic
                    for feature_set in feature_sets
                ),
                "truncated_poi_groups": sum(
                    feature_set.source.is_truncated
                    for feature_set in feature_sets
                ),
            }
        )
    return rows


def discovery_candidate_rows(
    report: CandidateDiscoveryReport,
) -> list[dict[str, Any]]:
    return [
        {
            "rank": item.rank,
            "parcel_id": item.candidate.parcel_id,
            "name": item.candidate.name,
            "longitude": item.candidate.longitude,
            "latitude": item.candidate.latitude,
            "area_hectares": item.candidate.area_hectares,
            "geometry_dataset_id": item.candidate.geometry_dataset_id,
            "market_score": round(item.market_score, 2),
            "land_use_class": item.land_use_class,
            "land_use_suitability": item.land_use_suitability.value,
            "formal_analysis_allowed": item.formal_analysis_allowed,
            "requires_human_review": item.requires_human_review,
            "reasons": "；".join(item.reasons),
        }
        for item in report.candidates
    ]


def available_discovery_poi_categories(
    report: CandidateDiscoveryReport,
) -> list[str]:
    return sorted({item.category for item in report.range_pois})


def discovery_map_rows(
    report: CandidateDiscoveryReport,
    *,
    categories: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    selected = set(categories or [])
    candidates = [
        {
            **item,
            "kind": "candidate",
            "label": item["parcel_id"],
            "map_label": f"#{item['rank']}",
            "category": "候选地",
            "provider": "land",
            "color": [220, 38, 38, 235],
            "radius_m": 90,
        }
        for item in discovery_candidate_rows(report)
    ]
    pois = [
        {
            "kind": "poi",
            "poi_id": item.poi_id,
            "name": item.name,
            "label": item.name,
            "category": item.category,
            "longitude": item.longitude,
            "latitude": item.latitude,
            "provider": item.provider.value,
            "dataset_id": item.dataset_id,
            "is_synthetic": item.is_synthetic,
            "source_group_keys": ", ".join(item.source_group_keys),
            "color": _category_color(item.category),
            "radius_m": 36,
        }
        for item in report.range_pois
        if not selected or item.category in selected
    ]
    return [*candidates, *pois]


def available_poi_categories(run: SiteSelectionRunResponse) -> list[str]:
    analysis = _require_analysis(run)
    return sorted(
        {
            record.category
            for result in analysis.results
            for feature_set in result.poi_evidence.feature_sets
            for record in feature_set.records
        }
    )


def poi_record_rows(
    run: SiteSelectionRunResponse,
    *,
    categories: Iterable[str] | None = None,
    candidate_ids: Iterable[str] | None = None,
) -> list[dict]:
    analysis = _require_analysis(run)
    selected = set(categories or [])
    selected_candidates = set(candidate_ids or [])
    rows = []
    for result in analysis.results:
        if selected_candidates and result.parcel_id not in selected_candidates:
            continue
        for feature_set in result.poi_evidence.feature_sets:
            source = feature_set.source
            for record in feature_set.records:
                if selected and record.category not in selected:
                    continue
                rows.append(
                    {
                        "parcel_id": result.parcel_id,
                        "group_key": feature_set.query.group_key,
                        "poi_id": record.poi_id,
                        "name": record.name,
                        "category": record.category,
                        "distance_m": record.distance_m,
                        "longitude": record.longitude,
                        "latitude": record.latitude,
                        "provider": source.provider.value,
                        "dataset_id": source.dataset_id,
                        "dataset_record_count": source.dataset_record_count,
                        "available_record_count": source.available_record_count,
                        "is_truncated": source.is_truncated,
                        "is_synthetic": source.is_synthetic,
                        "queried_at": source.queried_at.isoformat(),
                        "evidence_snapshot_id": source.evidence_snapshot_id,
                        "evidence_reused": source.evidence_reused,
                        "evidence_supplemented": source.evidence_supplemented,
                        "evidence_supplement_reason": (
                            source.evidence_supplement_reason
                        ),
                        "evidence_supplement_error": (
                            source.evidence_supplement_error
                        ),
                    }
                )
    return rows


def unique_analysis_poi_map_rows(rows: Iterable[dict]) -> list[dict]:
    """Deduplicate map markers while preserving candidate/evidence lineage."""
    unique: dict[tuple, dict[str, Any]] = {}
    for item in rows:
        poi_id = str(item.get("poi_id") or "").strip()
        stable_key = (
            "id",
            item.get("provider"),
            item.get("dataset_id"),
            poi_id,
        ) if poi_id else (
            "location",
            item.get("category"),
            item.get("name"),
            round(float(item["longitude"]), 7),
            round(float(item["latitude"]), 7),
        )
        evidence_origin = (
            "补查失败，保留快照"
            if item.get("evidence_supplement_error")
            else (
                "候选点补查"
                if item.get("evidence_supplemented")
                else (
                    "发现快照裁剪"
                    if item.get("evidence_reused")
                    else "运行时查询"
                )
            )
        )
        is_synthetic = bool(item.get("is_synthetic"))
        supplemented = bool(item.get("evidence_supplemented"))
        line_color = (
            [234, 88, 12, 210]
            if is_synthetic
            else (
                [8, 145, 178, 190]
                if supplemented
                else [255, 255, 255, 180]
            )
        )
        existing = unique.get(stable_key)
        if existing is None:
            unique[stable_key] = {
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "label": item["name"],
                "name": item["name"],
                "kind": "poi",
                "poi_id": item.get("poi_id"),
                "category": item["category"],
                "provider": item["provider"],
                "dataset_id": item.get("dataset_id"),
                "is_synthetic": is_synthetic,
                "distance_m": item.get("distance_m"),
                "soft_rank": None,
                "soft_score": None,
                "color": _category_color(item["category"]),
                "line_color": line_color,
                "radius_m": 58 if supplemented else 55,
                "candidate_ids": {str(item["parcel_id"])},
                "group_keys": {str(item["group_key"])},
                "evidence_origins": {evidence_origin},
            }
            continue
        existing["candidate_ids"].add(str(item["parcel_id"]))
        existing["group_keys"].add(str(item["group_key"]))
        existing["evidence_origins"].add(evidence_origin)
        distance_m = item.get("distance_m")
        if distance_m is not None and (
            existing["distance_m"] is None
            or distance_m < existing["distance_m"]
        ):
            existing["distance_m"] = distance_m
        if is_synthetic:
            existing["is_synthetic"] = True
            existing["line_color"] = [234, 88, 12, 210]
        elif supplemented and not existing["is_synthetic"]:
            existing["line_color"] = [8, 145, 178, 190]
            existing["radius_m"] = 58

    result = []
    for item in unique.values():
        candidate_ids = sorted(item.pop("candidate_ids"))
        group_keys = sorted(item.pop("group_keys"))
        evidence_origins = sorted(item.pop("evidence_origins"))
        item["candidate_ids"] = ", ".join(candidate_ids)
        item["candidate_link_count"] = len(candidate_ids)
        item["group_keys"] = ", ".join(group_keys)
        item["evidence_origin"] = "、".join(evidence_origins)
        result.append(item)
    return result


def poi_metric_rows(run: SiteSelectionRunResponse) -> list[dict]:
    analysis = _require_analysis(run)
    rows = []
    for result in analysis.results:
        for feature_set in result.poi_evidence.feature_sets:
            for metric, value in feature_set.metrics.items():
                rows.append(
                    {
                        "parcel_id": result.parcel_id,
                        "group_key": feature_set.query.group_key,
                        "metric": metric.value,
                        "value": value,
                        "provider": feature_set.source.provider.value,
                        "matched_records": feature_set.source.record_count,
                        "dataset_record_count": (
                            feature_set.source.dataset_record_count
                        ),
                        "available_record_count": (
                            feature_set.source.available_record_count
                        ),
                        "is_truncated": feature_set.source.is_truncated,
                        "queried_at": feature_set.source.queried_at.isoformat(),
                    }
                )
    return rows


def poi_source_rows(run: SiteSelectionRunResponse) -> list[dict]:
    analysis = _require_analysis(run)
    rows = []
    for result in analysis.results:
        for feature_set in result.poi_evidence.feature_sets:
            source = feature_set.source
            rows.append(
                {
                    "parcel_id": result.parcel_id,
                    "group_key": feature_set.query.group_key,
                    "matched_records": source.record_count,
                    "dataset_record_count": source.dataset_record_count,
                    "available_record_count": source.available_record_count,
                    "query_limit": feature_set.query.limit,
                    "is_truncated": source.is_truncated,
                    "provider": source.provider.value,
                    "evidence_snapshot_id": source.evidence_snapshot_id,
                    "evidence_reused": source.evidence_reused,
                    "evidence_supplemented": source.evidence_supplemented,
                    "evidence_supplement_reason": (
                        source.evidence_supplement_reason
                    ),
                    "evidence_supplement_error": (
                        source.evidence_supplement_error
                    ),
                    "cache_hit": source.cache_hit,
                    "dataset_version": source.dataset_version,
                    "is_synthetic": source.is_synthetic,
                    "quality_notice": source.quality_notice,
                }
            )
    return rows


def poi_candidate_coverage_rows(run: SiteSelectionRunResponse) -> list[dict]:
    """Summarize whether each candidate has comparable POI evidence."""
    analysis = _require_analysis(run)
    rows = []
    for result in analysis.results:
        feature_sets = result.poi_evidence.feature_sets
        complete = sum(_poi_feature_set_is_complete(item) for item in feature_sets)
        synthetic = sum(item.source.is_synthetic for item in feature_sets)
        truncated = sum(item.source.is_truncated for item in feature_sets)
        supplement_failed = sum(
            item.source.evidence_supplement_error is not None
            for item in feature_sets
        )
        rows.append(
            {
                "parcel_id": result.parcel_id,
                "evidence_status": (
                    "完整可比"
                    if complete == len(feature_sets)
                    else "证据不完整，排名待复核"
                ),
                "matched_records": sum(len(item.records) for item in feature_sets),
                "complete_groups": complete,
                "total_groups": len(feature_sets),
                "synthetic_groups": synthetic,
                "truncated_groups": truncated,
                "supplement_success_groups": sum(
                    item.source.evidence_supplemented for item in feature_sets
                ),
                "supplement_failed_groups": supplement_failed,
            }
        )
    return rows


def poi_group_comparability_rows(run: SiteSelectionRunResponse) -> list[dict]:
    """Expose group-level cohort consistency instead of hiding mixed sources."""
    analysis = _require_analysis(run)
    grouped: dict[str, list] = {}
    for result in analysis.results:
        for feature_set in result.poi_evidence.feature_sets:
            grouped.setdefault(feature_set.query.group_key, []).append(feature_set)

    rows = []
    candidate_count = len(analysis.results)
    for group_key, feature_sets in sorted(grouped.items()):
        counts = [len(item.records) for item in feature_sets]
        complete = sum(_poi_feature_set_is_complete(item) for item in feature_sets)
        rows.append(
            {
                "group_key": group_key,
                "comparability": (
                    "可横向比较"
                    if len(feature_sets) == candidate_count
                    and complete == candidate_count
                    else "不可直接比较"
                ),
                "complete_candidates": complete,
                "candidate_count": candidate_count,
                "min_records": min(counts, default=0),
                "max_records": max(counts, default=0),
                "synthetic_candidates": sum(
                    item.source.is_synthetic for item in feature_sets
                ),
                "truncated_candidates": sum(
                    item.source.is_truncated for item in feature_sets
                ),
                "supplement_failed_candidates": sum(
                    item.source.evidence_supplement_error is not None
                    for item in feature_sets
                ),
            }
        )
    return rows


def agent_plan_rows(run: SiteSelectionRunResponse) -> list[dict]:
    analysis = _require_analysis(run)
    if analysis.execution_plan is None:
        return []
    return [
        {
            "node_id": step.node_id,
            "role": step.role.value,
            "skill": step.skill_name,
            "version": step.skill_version,
            "depends_on": ", ".join(step.depends_on) or "START",
            "parallel_group": step.parallel_group,
            "critical": step.critical,
            "llm_allowed": step.llm_allowed,
            "output_contract": step.output_contract,
        }
        for step in analysis.execution_plan.steps
    ]


def agent_trace_rows(run: SiteSelectionRunResponse) -> list[dict]:
    analysis = _require_analysis(run)
    return [
        {
            "node_id": trace.node_id,
            "role": trace.role.value,
            "skill": trace.skill_name,
            "status": trace.status.value,
            "elapsed_ms": round(trace.elapsed_ms, 3),
            "parallel_group": trace.parallel_group,
            "critical": trace.critical,
            "error_type": trace.error_type,
        }
        for trace in analysis.agent_trace
    ]


def evidence_review_rows(run: SiteSelectionRunResponse) -> list[dict]:
    analysis = _require_analysis(run)
    report = analysis.evidence_review_report
    if report is None:
        return []
    return [
        {
            "severity": issue.severity.value,
            "issue_code": issue.issue_code,
            "parcel_id": issue.parcel_id,
            "message": issue.message,
            "evidence_refs": ", ".join(issue.evidence_refs),
        }
        for issue in report.issues
    ]


def agent_collaboration_rows(run: SiteSelectionRunResponse) -> list[dict]:
    analysis = _require_analysis(run)
    report = analysis.collaboration_report
    if report is None:
        return []
    return [
        {
            "round": message.round_index,
            "kind": message.kind.value,
            "sender": message.sender.value,
            "recipient": message.recipient.value,
            "content": message.content,
            "evidence_references": ", ".join(message.evidence_references),
        }
        for message in report.messages
    ]


def map_rows(
    payload: dict[str, Any],
    run: SiteSelectionRunResponse,
    *,
    categories: Iterable[str] | None = None,
    candidate_ids: Iterable[str] | None = None,
) -> list[dict]:
    selected_candidates = set(candidate_ids or [])
    comparison = {
        row["parcel_id"]: row
        for row in candidate_comparison_rows(run, payload=payload)
    }
    rows = []
    for parcel in payload.get("candidate_parcels", []):
        parcel_id = parcel["parcel_id"]
        if selected_candidates and parcel_id not in selected_candidates:
            continue
        candidate_name = parcel.get("name") or parcel_id
        comparison_row = comparison.get(parcel_id, {})
        rows.append(
            {
                "latitude": parcel["latitude"],
                "longitude": parcel["longitude"],
                "label": parcel_id,
                "name": candidate_name,
                "kind": "candidate",
                "category": "候选地",
                "provider": "candidate",
                "distance_m": None,
                "soft_rank": comparison_row.get("soft_rank"),
                "soft_score": comparison_row.get("soft_score"),
                "color": [220, 38, 38, 235],
                "radius_m": 180,
            }
        )
    rows.extend(
        unique_analysis_poi_map_rows(
            poi_record_rows(
                run,
                categories=categories,
                candidate_ids=selected_candidates,
            )
        )
    )
    return rows


def candidate_radius_rows(
    payload: dict[str, Any],
    run: SiteSelectionRunResponse,
    candidate_id: str,
) -> list[dict]:
    """Build read-only service-radius rings for one focused candidate."""
    analysis = _require_analysis(run)
    parcel = next(
        (
            item
            for item in payload.get("candidate_parcels", [])
            if item["parcel_id"] == candidate_id
        ),
        None,
    )
    result = next(
        (item for item in analysis.results if item.parcel_id == candidate_id),
        None,
    )
    if parcel is None or result is None:
        return []
    radii = sorted(
        {feature_set.query.radius_m for feature_set in result.poi_evidence.feature_sets},
        reverse=True,
    )
    return [
        {
            "kind": "coverage",
            "name": f"{candidate_id} 服务半径 {radius}m",
            "category": "Profile 服务半径",
            "provider": "profile",
            "longitude": parcel["longitude"],
            "latitude": parcel["latitude"],
            "radius_m": radius,
            "line_color": [220, 38, 38, max(45, 105 - index * 20)],
            "distance_m": radius,
            "evidence_origin": "Profile 配置",
            "candidate_ids": candidate_id,
            "group_keys": ", ".join(
                feature_set.query.group_key
                for feature_set in result.poi_evidence.feature_sets
                if feature_set.query.radius_m == radius
            ),
            "soft_score": None,
        }
        for index, radius in enumerate(radii)
    ]


def map_view_state(rows: list[dict]) -> dict[str, float]:
    if not rows:
        return {"latitude": 31.23, "longitude": 121.47, "zoom": 10.0}
    latitudes = [float(row["latitude"]) for row in rows]
    longitudes = [float(row["longitude"]) for row in rows]
    latitude = (min(latitudes) + max(latitudes)) / 2
    longitude = (min(longitudes) + max(longitudes)) / 2
    latitude_span = max(latitudes) - min(latitudes)
    longitude_span = (max(longitudes) - min(longitudes)) * max(
        cos(radians(latitude)),
        0.2,
    )
    span = max(latitude_span, longitude_span, 0.001)
    zoom = max(7.0, min(14.0, 11.5 - log2(span / 0.03)))
    return {
        "latitude": latitude,
        "longitude": longitude,
        "zoom": zoom,
    }


_MAP_CATEGORY_PALETTE = (
    (37, 99, 235, 190),
    (5, 150, 105, 190),
    (124, 58, 237, 190),
    (217, 119, 6, 190),
    (8, 145, 178, 190),
    (190, 24, 93, 190),
    (77, 124, 15, 190),
    (79, 70, 229, 190),
)


def _category_color(category: str) -> list[int]:
    digest = sha256(category.encode("utf-8")).digest()
    return list(_MAP_CATEGORY_PALETTE[digest[0] % len(_MAP_CATEGORY_PALETTE)])


def _poi_feature_set_is_complete(feature_set) -> bool:
    source = feature_set.source
    return bool(
        not source.is_synthetic
        and source.fallback_from is None
        and not source.is_truncated
        and source.evidence_supplement_error is None
    )


def _require_analysis(run: SiteSelectionRunResponse):
    if run.analysis is None:
        raise ValueError("运行尚未返回分析结果")
    return run.analysis


def _error_detail(response: httpx.Response) -> tuple[str, str]:
    try:
        payload = response.json()
    except ValueError:
        return "http_error", f"选址 API 返回 HTTP {response.status_code}"
    detail = payload.get("detail", payload) if isinstance(payload, dict) else {}
    if isinstance(detail, dict):
        code = str(detail.get("code", "http_error"))
        message = str(detail.get("message", f"HTTP {response.status_code}"))
        return code, message
    if isinstance(detail, str) and detail.strip():
        return "http_error", detail
    return "http_error", f"选址 API 返回 HTTP {response.status_code}"
