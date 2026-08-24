from __future__ import annotations

import platform
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

import geopandas as gpd
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Point, Polygon

from .domain import ProjectType
from .evaluation import FrozenEvaluationRunner, load_evaluation_suite
from .poi import POIQuery
from .poi_adapters import FixturePOIAdapter
from .policy_rag import PolicyHybridRetriever, chunk_policy_documents, load_policy_corpus


class PerformanceMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    samples: int = Field(ge=1)
    warmup_runs: int = Field(ge=0)
    median_ms: float = Field(ge=0)
    min_ms: float = Field(ge=0)
    max_ms: float = Field(ge=0)
    state: str
    input_summary: dict[str, Any]


class FixturePerformanceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    generated_at: datetime
    environment: dict[str, str]
    fixture_versions: dict[str, str]
    disclaimer: str
    measurements: list[PerformanceMeasurement]


def measure_fixture_performance(
    project_root: str | Path,
    *,
    samples: int = 7,
    warmup_runs: int = 2,
) -> FixturePerformanceReport:
    if samples < 3:
        raise ValueError("performance samples must be at least 3")
    if warmup_runs < 0:
        raise ValueError("warmup runs cannot be negative")
    root = Path(project_root)
    fixture_root = root / "data" / "fixtures"
    suite = load_evaluation_suite(root / "evals" / "cases.json")

    candidate = gpd.GeoDataFrame(
        {"parcel_id": ["PERF-A01"]},
        geometry=[Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])],
        crs="EPSG:32651",
    )
    constraints = gpd.GeoDataFrame(
        {"constraint_id": ["PERF-C01"]},
        geometry=[Point(50, 50)],
        crs="EPSG:32651",
    )

    def gis_operation() -> None:
        geometry = candidate.geometry.iloc[0]
        _ = geometry.area / 10_000
        _ = int(constraints.intersects(geometry).sum())
        _ = float(constraints.distance(geometry.centroid).min())

    poi_adapter = FixturePOIAdapter.from_json(fixture_root / "poi.json")
    poi_query = POIQuery(
        query_id="fixture-performance-poi",
        parcel_id="PERF-A01",
        group_key="public_transit",
        longitude=121.47,
        latitude=31.23,
        categories=["地铁站", "公交站"],
        radius_m=3_000,
        limit=100,
    )

    corpus = load_policy_corpus(fixture_root / "policies.json")
    retriever = PolicyHybridRetriever(
        chunk_policy_documents(corpus.documents),
        _KeywordEmbeddingProvider(),
    )

    measurements = [
        _measure(
            "gis_geopandas_area_intersection_distance",
            gis_operation,
            samples=samples,
            warmup_runs=warmup_runs,
            state="in-memory projected fixture",
            input_summary={"candidate_features": 1, "constraint_features": 1, "crs": "EPSG:32651"},
        ),
        _measure(
            "poi_fixture_search",
            lambda: poi_adapter.search(poi_query),
            samples=samples,
            warmup_runs=warmup_runs,
            state="local JSON fixture; no Redis; no network",
            input_summary={
                "fixture_records": len(poi_adapter.dataset.records),
                "radius_m": 3000,
                "categories": 2,
            },
        ),
        _measure(
            "rag_hybrid_retrieval",
            lambda: retriever.search(
                "商业设施轨道交通站点距离",
                project_type=ProjectType.SHOPPING_MALL,
                jurisdiction="测试行政区",
                top_k=3,
            ),
            samples=samples,
            warmup_runs=warmup_runs,
            state="in-memory fixture corpus; deterministic embeddings",
            input_summary={
                "policy_documents": len(corpus.documents),
                "top_k": 3,
            },
        ),
        _measure(
            "frozen_evaluation_suite",
            lambda: FrozenEvaluationRunner(fixture_root).run_suite(suite),
            samples=samples,
            warmup_runs=warmup_runs,
            state="24 deterministic cases; no live providers",
            input_summary={"cases": len(suite.cases), "poi_failure_cases": 4},
        ),
    ]
    return FixturePerformanceReport(
        report_id="site-selection-local-fixture",
        generated_at=datetime.now(timezone.utc),
        environment={
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "not reported",
        },
        fixture_versions=suite.fixture_versions,
        disclaimer=(
            "Local deterministic fixture measurements only. They are not a "
            "production benchmark, capacity claim, or online POI SLA."
        ),
        measurements=measurements,
    )


def _measure(
    metric: str,
    operation: Callable[[], object],
    *,
    samples: int,
    warmup_runs: int,
    state: str,
    input_summary: dict[str, Any],
) -> PerformanceMeasurement:
    for _ in range(warmup_runs):
        operation()
    timings = []
    for _ in range(samples):
        started_at = perf_counter()
        operation()
        timings.append((perf_counter() - started_at) * 1_000)
    return PerformanceMeasurement(
        metric=metric,
        samples=samples,
        warmup_runs=warmup_runs,
        median_ms=round(median(timings), 3),
        min_ms=round(min(timings), 3),
        max_ms=round(max(timings), 3),
        state=state,
        input_summary=input_summary,
    )


class _KeywordEmbeddingProvider:
    _terms = ("生态", "轨道", "物流", "高速", "货运")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [1.0, *(float(text.count(term)) for term in self._terms)]
            for text in texts
        ]
