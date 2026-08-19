from scripts.smoke_day24_fixture_runtime import EXPECTED_MCP_TOOLS, PAYLOADS


def test_day24_smoke_covers_both_project_types_and_four_fixture_candidates() -> None:
    assert set(PAYLOADS) == {"shopping_mall", "logistics_park"}
    assert sum(len(item["candidate_parcels"]) for item in PAYLOADS.values()) == 4
    assert EXPECTED_MCP_TOOLS == {
        "gis_feature_area",
        "gis_intersection_count",
        "gis_nearest_distance",
        "poi_nearby",
        "poi_metrics",
        "policy_search",
    }
