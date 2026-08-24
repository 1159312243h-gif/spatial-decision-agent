from pathlib import Path

from practice.site_selection.performance import measure_fixture_performance


PROJECT_ROOT = Path(__file__).parents[1]


def test_performance_report_is_versioned_and_covers_gis_poi_rag_and_suite() -> None:
    report = measure_fixture_performance(
        PROJECT_ROOT,
        samples=3,
        warmup_runs=0,
    )

    assert report.fixture_versions == {
        "poi": "fixture-rich-v1",
        "policy": "fixture-2026.08.1",
        "spatial": "fixture-rich-v1",
    }
    assert {item.metric for item in report.measurements} == {
        "gis_geopandas_area_intersection_distance",
        "poi_fixture_search",
        "rag_hybrid_retrieval",
        "frozen_evaluation_suite",
    }
    assert all(item.samples == 3 for item in report.measurements)
    assert "not a production benchmark" in report.disclaimer
