from pathlib import Path

from practice.site_selection.evaluation import (
    FrozenEvaluationRunner,
    EvaluationSuite,
    load_evaluation_suite,
    write_evaluation_summary,
)
from practice.site_selection.poi_adapters import haversine_distance_m


PROJECT_ROOT = Path(__file__).parents[1]
SUITE_PATH = PROJECT_ROOT / "evals" / "cases.json"


def test_frozen_suite_has_24_unique_cases_and_four_poi_failures() -> None:
    suite = load_evaluation_suite(SUITE_PATH)

    assert isinstance(suite, EvaluationSuite)
    assert len(suite.cases) == 24
    assert len({case.case_id for case in suite.cases}) == 24
    assert sum(case.category == "poi_failure" for case in suite.cases) == 4


def test_poi_category_fixture_expectation_matches_two_kilometre_radius() -> None:
    suite = load_evaluation_suite(SUITE_PATH)
    case = next(case for case in suite.cases if case.case_id == "POI-001")

    assert haversine_distance_m(121.47, 31.23, 121.471, 31.23) < 2_000
    assert haversine_distance_m(121.47, 31.23, 121.49, 31.23) < 2_000
    assert case.expected["poi_ids"] == ["F0001", "F0002"]


def test_all_frozen_cases_pass_without_live_network() -> None:
    suite = load_evaluation_suite(SUITE_PATH)

    summary = FrozenEvaluationRunner(
        PROJECT_ROOT / "data" / "fixtures"
    ).run_suite(suite)

    assert summary.total == 24
    assert summary.passed == 24
    assert summary.failed == 0
    assert all(result.elapsed_ms >= 0 for result in summary.results)


def test_summary_is_machine_readable_and_preserves_provenance(tmp_path) -> None:
    suite = load_evaluation_suite(SUITE_PATH)
    summary = FrozenEvaluationRunner(
        PROJECT_ROOT / "data" / "fixtures"
    ).run_suite(suite)
    output = tmp_path / "summary.json"

    write_evaluation_summary(summary, output)
    reloaded = output.read_text(encoding="utf-8")

    assert '"suite_id": "site-selection"' in reloaded
    assert '"network": "disabled by evaluation design"' in reloaded
    assert '"failed": 0' in reloaded
