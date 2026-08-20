from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from practice.site_selection import (
    AgentState,
    CandidateParcel,
    DatasetManifest,
    POIFeatureSet,
    POIProvider,
    POIQuery,
    POIRecord,
    POISourceMeta,
    ProjectRequest,
    ProjectType,
    get_project_profile,
)


NOW = datetime(2026, 8, 17, 20, 45, tzinfo=timezone.utc)


def parcel(parcel_id: str = "A01") -> CandidateParcel:
    return CandidateParcel(
        parcel_id=parcel_id,
        name=f"候选地块 {parcel_id}",
        longitude=121.47,
        latitude=31.23,
        area_hectares=30,
        geometry_dataset_id="parcel-2026-08",
    )


def project_request(project_type: ProjectType) -> ProjectRequest:
    return ProjectRequest(
        request_id=f"REQ-{project_type.value}",
        project_type=project_type,
        candidate_parcels=[parcel()],
        requested_at=NOW,
    )


@pytest.mark.parametrize(
    "project_type",
    [ProjectType.SHOPPING_MALL, ProjectType.LOGISTICS_PARK],
)
def test_two_supported_project_requests_are_valid(
    project_type: ProjectType,
) -> None:
    request = project_request(project_type)

    assert request.project_type is project_type
    assert request.candidate_parcels[0].parcel_id == "A01"


def test_unknown_project_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="project_type"):
        ProjectRequest.model_validate(
            {
                "request_id": "REQ-unknown",
                "project_type": "factory",
                "candidate_parcels": [parcel().model_dump()],
                "requested_at": NOW,
            }
        )


def test_missing_candidate_field_is_rejected() -> None:
    invalid_parcel = parcel().model_dump()
    invalid_parcel.pop("latitude")

    with pytest.raises(ValidationError, match="latitude"):
        ProjectRequest.model_validate(
            {
                "request_id": "REQ-missing-field",
                "project_type": "shopping_mall",
                "candidate_parcels": [invalid_parcel],
                "requested_at": NOW,
            }
        )


def test_candidate_parcel_ids_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="候选地块编号不能重复"):
        ProjectRequest(
            request_id="REQ-duplicate",
            project_type=ProjectType.LOGISTICS_PARK,
            candidate_parcels=[parcel("A01"), parcel("A01")],
            requested_at=NOW,
        )


def test_request_time_must_include_timezone() -> None:
    with pytest.raises(ValidationError, match="时区"):
        ProjectRequest(
            request_id="REQ-naive-time",
            project_type=ProjectType.SHOPPING_MALL,
            candidate_parcels=[parcel()],
            requested_at=datetime(2026, 8, 17, 20, 45),
        )


def test_illegal_poi_radius_is_rejected() -> None:
    with pytest.raises(ValidationError, match="radius_m"):
        POIQuery(
            query_id="Q-001",
            parcel_id="A01",
            group_key="public_transit",
            longitude=121.47,
            latitude=31.23,
            categories=["地铁站"],
            radius_m=99,
        )


def test_empty_poi_categories_are_rejected() -> None:
    with pytest.raises(ValidationError, match="categories"):
        POIQuery(
            query_id="Q-002",
            parcel_id="A01",
            group_key="public_transit",
            longitude=121.47,
            latitude=31.23,
            categories=[],
            radius_m=1_000,
        )


def test_missing_poi_group_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="group_key"):
        POIQuery(
            query_id="Q-missing-group",
            parcel_id="A01",
            longitude=121.47,
            latitude=31.23,
            categories=["地铁站"],
            radius_m=1_000,
        )


def test_unknown_dataset_source_is_rejected() -> None:
    with pytest.raises(ValidationError, match="source"):
        DatasetManifest.model_validate(
            {
                "dataset_id": "poi-2026-08",
                "name": "POI 数据",
                "source": "unknown-cloud",
                "location": "poi_table",
                "version": "2026.08",
                "crs": "EPSG:4326",
                "required_fields": ["poi_id", "category"],
                "updated_at": NOW,
            }
        )


def test_unknown_poi_provider_is_rejected() -> None:
    with pytest.raises(ValidationError, match="provider"):
        POISourceMeta.model_validate(
            {
                "provider": "untrusted-provider",
                "dataset_id": "poi-2026-08",
                "queried_at": NOW,
                "record_count": 0,
            }
        )


def test_two_profiles_have_distinct_poi_rules() -> None:
    shopping = get_project_profile(ProjectType.SHOPPING_MALL)
    logistics = get_project_profile(ProjectType.LOGISTICS_PARK)

    assert len(shopping.poi_groups) >= 5
    assert len(logistics.poi_groups) >= 5
    assert {group.group_key for group in shopping.poi_groups} != {
        group.group_key for group in logistics.poi_groups
    }
    assert sum(group.soft_score_weight for group in shopping.poi_groups) == pytest.approx(1)
    assert sum(group.soft_score_weight for group in logistics.poi_groups) == pytest.approx(1)


def test_poi_feature_count_must_match_source_metadata() -> None:
    query = POIQuery(
        query_id="Q-003",
        parcel_id="A01",
        group_key="public_transit",
        longitude=121.47,
        latitude=31.23,
        categories=["地铁站"],
        radius_m=1_500,
    )
    record = POIRecord(
        poi_id="P-001",
        name="人民广场站",
        category="地铁站",
        longitude=121.475,
        latitude=31.232,
        distance_m=420,
    )
    source = POISourceMeta(
        provider=POIProvider.MOCK,
        dataset_id="poi-mock",
        queried_at=NOW,
        record_count=0,
    )

    with pytest.raises(ValidationError, match="记录数"):
        POIFeatureSet(query=query, records=[record], source=source)


@pytest.mark.parametrize(
    ("available_record_count", "is_truncated"),
    [(2, False), (1, True)],
)
def test_poi_source_truncation_must_match_available_count(
    available_record_count: int,
    is_truncated: bool,
) -> None:
    with pytest.raises(ValidationError, match="截断标记"):
        POISourceMeta(
            provider=POIProvider.OSM,
            dataset_id="osm-test",
            queried_at=NOW,
            record_count=1,
            available_record_count=available_record_count,
            is_truncated=is_truncated,
        )


def test_agent_state_requires_matching_profile_type() -> None:
    request = project_request(ProjectType.SHOPPING_MALL)
    wrong_profile = get_project_profile(ProjectType.LOGISTICS_PARK)

    with pytest.raises(ValidationError, match="ProjectProfile"):
        AgentState(request=request, profile=wrong_profile)


def test_agent_state_rejects_unknown_parcel_reference() -> None:
    request = project_request(ProjectType.SHOPPING_MALL)
    profile = get_project_profile(ProjectType.SHOPPING_MALL)
    unknown_query = POIQuery(
        query_id="Q-unknown-parcel",
        parcel_id="B99",
        group_key="public_transit",
        longitude=121.47,
        latitude=31.23,
        categories=["地铁站"],
        radius_m=1_500,
    )

    with pytest.raises(ValidationError, match="不存在的候选地块"):
        AgentState(
            request=request,
            profile=profile,
            poi_queries=[unknown_query],
        )
