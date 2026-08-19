from math import pi

import pytest

from practice.site_selection import POIQuery, POIRecord, build_poi_metrics_report


def query() -> POIQuery:
    return POIQuery(
        query_id="metric-query",
        parcel_id="A01",
        group_key="transit",
        longitude=121.47,
        latitude=31.23,
        categories=["公交站"],
        radius_m=1_500,
    )


def record(poi_id: str, distance_m: float | None) -> POIRecord:
    return POIRecord(
        poi_id=poi_id,
        name=poi_id,
        category="公交站",
        longitude=121.47,
        latitude=31.23,
        distance_m=distance_m,
    )


def test_report_contains_reproducible_density_and_cumulative_bands() -> None:
    result = build_poi_metrics_report(
        query(),
        [record("P1", 100), record("P2", 600), record("P3", 1_100)],
        distance_bands_m=[500, 1_000, 1_500],
    )

    assert result.count == 3
    assert result.density_per_sq_km == pytest.approx(3 / (pi * 1.5**2))
    assert result.nearest_distance_m == 100
    assert result.average_distance_m == 600
    assert [band.count for band in result.distance_bands] == [1, 2, 3]


def test_empty_records_keep_distance_metrics_explicitly_missing() -> None:
    result = build_poi_metrics_report(
        query(),
        [],
        distance_bands_m=[500, 1_500],
    )

    assert result.count == 0
    assert result.nearest_distance_m is None
    assert result.average_distance_m is None
    assert [band.count for band in result.distance_bands] == [0, 0]


@pytest.mark.parametrize(
    "bands",
    [[], [500, 500], [1_000, 500], [0, 500], [500, 2_000]],
)
def test_invalid_distance_bands_are_rejected(bands: list[int]) -> None:
    with pytest.raises(ValueError, match="距离分级"):
        build_poi_metrics_report(
            query(),
            [record("P1", 100)],
            distance_bands_m=bands,
        )
