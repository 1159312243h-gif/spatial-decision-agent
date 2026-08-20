from __future__ import annotations

from collections.abc import Iterable
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


def candidate_comparison_rows(run: SiteSelectionRunResponse) -> list[dict]:
    analysis = _require_analysis(run)
    report = analysis.comparison_report
    if report is None:
        return []
    results = {result.parcel_id: result for result in analysis.results}
    rows = []
    for item in report.candidates:
        result = results[item.parcel_id]
        rows.append(
            {
                "parcel_id": item.parcel_id,
                "soft_rank": item.soft_rank,
                "soft_score": item.soft_score,
                "policy_outcomes": ", ".join(
                    outcome.value for outcome in item.policy_outcomes
                )
                or "none",
                "gis_crs": result.gis_evidence.crs,
                "review_required": bool(item.policy_outcomes),
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
                        "name": record.name,
                        "category": record.category,
                        "distance_m": record.distance_m,
                        "longitude": record.longitude,
                        "latitude": record.latitude,
                        "provider": source.provider.value,
                        "dataset_id": source.dataset_id,
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
                        "queried_at": feature_set.source.queried_at.isoformat(),
                    }
                )
    return rows


def map_rows(
    payload: dict[str, Any],
    run: SiteSelectionRunResponse,
    *,
    categories: Iterable[str] | None = None,
) -> list[dict]:
    rows = [
        {
            "latitude": parcel["latitude"],
            "longitude": parcel["longitude"],
            "label": parcel["parcel_id"],
            "kind": "candidate",
        }
        for parcel in payload.get("candidate_parcels", [])
    ]
    rows.extend(
        {
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "label": item["name"],
            "kind": "poi",
        }
        for item in poi_record_rows(run, categories=categories)
    )
    return rows


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
