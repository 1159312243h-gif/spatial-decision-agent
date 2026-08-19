from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from practice.site_selection.poi_normalizer import (
    POINormalizer,
    RawPOI,
    UnsupportedPOICRSError,
)


NOW = datetime(2026, 8, 19, 14, 30, tzinfo=timezone.utc)


def raw_poi(**updates: object) -> RawPOI:
    payload = {
        "source": "Fixture",
        "source_id": "poi-001",
        "name": "测试公交站",
        "category": "bus_stop",
        "longitude": 121.47,
        "latitude": 31.23,
        "source_crs": "WGS84",
        "address": " 测试路 1 号 ",
        "fetched_at": NOW,
        "raw_payload": {"provider_type": "150700"},
    }
    payload.update(updates)
    return RawPOI.model_validate(payload)


def test_normalizer_standardizes_source_category_and_address() -> None:
    normalized = POINormalizer(
        {"bus_stop": "公交站"}
    ).normalize(raw_poi())

    assert normalized.source == "fixture"
    assert normalized.category == "公交站"
    assert normalized.address == "测试路 1 号"
    assert normalized.source_crs == "WGS84"
    assert normalized.normalized_crs == "EPSG:4326"
    assert normalized.identity_key == ("fixture", "poi-001")


def test_gcj02_is_not_mislabeled_as_epsg4326() -> None:
    with pytest.raises(UnsupportedPOICRSError, match="不能直接标记"):
        POINormalizer().normalize(raw_poi(source_crs="GCJ-02"))


def test_unknown_source_crs_is_rejected() -> None:
    with pytest.raises(UnsupportedPOICRSError, match="尚不支持"):
        POINormalizer().normalize(raw_poi(source_crs="BD-09"))


def test_raw_poi_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="必须包含时区"):
        raw_poi(fetched_at=datetime(2026, 8, 19, 14, 30))


def test_normalize_many_returns_independent_payloads() -> None:
    raw = raw_poi()
    results = POINormalizer().normalize_many([raw])

    results[0].raw_payload["changed"] = True
    assert "changed" not in raw.raw_payload
