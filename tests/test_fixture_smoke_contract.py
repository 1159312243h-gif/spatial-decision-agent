from scripts.smoke_fixture_runtime import (
    EXPECTED_CANDIDATE_COUNT,
    EXPECTED_MCP_TOOLS,
    PAYLOADS,
    FixtureSmokeError,
)


def test_fixture_smoke_covers_all_project_types_and_rich_fixture_candidates() -> None:
    assert set(PAYLOADS) == {
        "shopping_mall",
        "logistics_park",
        "coffee_shop",
        "convenience_store",
    }
    assert EXPECTED_CANDIDATE_COUNT == 24
    assert all(len(item["candidate_parcels"]) == 6 for item in PAYLOADS.values())
    assert EXPECTED_MCP_TOOLS == {
        "gis_feature_area",
        "gis_intersection_count",
        "gis_nearest_distance",
        "poi_nearby",
        "poi_metrics",
        "policy_search",
    }


def test_fixture_safe_error_can_preserve_terminal_run_diagnostics() -> None:
    error = FixtureSmokeError(
        "stage=worker; project_type=shopping_mall; run_id=run-001; "
        "status=failed; run_error=选址任务入队失败：TypeError"
    )

    assert "run_id=run-001" in str(error)
    assert "status=failed" in str(error)
    assert "run_error=选址任务入队失败：TypeError" in str(error)
