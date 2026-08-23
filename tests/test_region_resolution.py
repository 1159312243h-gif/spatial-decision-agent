from practice.site_selection import (
    AMapRegionResolver,
    FixtureRegionResolver,
    RegionCatalogEntry,
    bounds_around_center,
)


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "status": "1",
            "districts": [
                {
                    "name": "杭州市西湖区",
                    "level": "district",
                    "center": "120.1302,30.2596",
                }
            ],
        }


class FakeClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def get(self, endpoint: str, *, params: dict) -> FakeResponse:
        assert params["keywords"] == "杭州西湖区"
        assert params["key"] == "secret"
        return FakeResponse()


def test_bounds_window_remains_inside_discovery_safety_limit() -> None:
    bounds = bounds_around_center(121.4365, 31.1885, 7)

    assert bounds.center == (121.4365, 31.1885)


def test_fixture_resolver_discloses_non_authoritative_source() -> None:
    resolver = FixtureRegionResolver(
        [
            RegionCatalogEntry(
                name="上海市徐汇区",
                aliases=["徐汇", "徐汇区"],
                administrative_level="district",
                center_longitude=121.4365,
                center_latitude=31.1885,
            )
        ]
    )

    result = resolver.resolve("上海市徐汇区", radius_km=4)

    assert result is not None
    assert result.source.value == "fixture_catalog"
    assert any("不是权威" in warning for warning in result.warnings)
    assert resolver.resolve("杭州市西湖区", radius_km=4) is None


def test_amap_resolver_converts_region_center_to_validated_bounds() -> None:
    resolver = AMapRegionResolver(
        "secret",
        client_factory=FakeClient,
    )

    result = resolver.resolve("杭州西湖区", radius_km=5)

    assert result.normalized_name == "杭州市西湖区"
    assert result.source.value == "amap"
    assert result.discovery_bounds.contains(120.1302, 30.2596)
