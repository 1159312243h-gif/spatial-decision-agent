from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from math import cos, log2, radians
from typing import Any
from urllib.parse import urljoin

import httpx

from app.schemas.site_selection import SiteSelectionRunResponse


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

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise SiteSelectionAPIError(
                504,
                "api_timeout",
                "选址 API 调用超时",
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
) -> list[dict]:
    analysis = _require_analysis(run)
    selected = set(categories or [])
    rows = []
    for result in analysis.results:
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
                    }
                )
    return rows


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
                    "dataset_version": source.dataset_version,
                    "is_synthetic": source.is_synthetic,
                    "quality_notice": source.quality_notice,
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


def map_rows(
    payload: dict[str, Any],
    run: SiteSelectionRunResponse,
    *,
    categories: Iterable[str] | None = None,
) -> list[dict]:
    comparison = {
        row["parcel_id"]: row
        for row in candidate_comparison_rows(run, payload=payload)
    }
    rows = []
    for parcel in payload.get("candidate_parcels", []):
        parcel_id = parcel["parcel_id"]
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
        {
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "label": item["name"],
            "name": item["name"],
            "kind": "poi",
            "category": item["category"],
            "provider": item["provider"],
            "distance_m": item["distance_m"],
            "soft_rank": None,
            "soft_score": None,
            "color": _category_color(item["category"]),
            "radius_m": 55,
        }
        for item in poi_record_rows(run, categories=categories)
    )
    return rows


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
