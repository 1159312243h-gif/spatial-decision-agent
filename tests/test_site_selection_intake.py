from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from practice.site_selection import (
    AnalysisStatus,
    CandidateParcel,
    ProfileRegistry,
    ProjectIntakeSkill,
    ProjectRequest,
    ProjectType,
    ProjectTypeRouter,
    UnsupportedProjectTypeError,
    build_poi_queries,
    get_project_profile,
)


NOW = datetime(2026, 8, 18, 20, 45, tzinfo=timezone.utc)


def parcel(parcel_id: str = "A01") -> CandidateParcel:
    return CandidateParcel(
        parcel_id=parcel_id,
        name=f"候选地块 {parcel_id}",
        longitude=121.47,
        latitude=31.23,
        area_hectares=30,
    )


def request_for(
    project_type: ProjectType,
    parcels: list[CandidateParcel] | None = None,
) -> ProjectRequest:
    return ProjectRequest(
        request_id=f"REQ-{project_type.value}",
        project_type=project_type,
        candidate_parcels=parcels or [parcel()],
        requested_at=NOW,
    )


@pytest.mark.parametrize(
    "project_type",
    list(ProjectType),
)
def test_router_selects_the_matching_profile(project_type: ProjectType) -> None:
    profile = ProjectTypeRouter().route(request_for(project_type))

    assert profile.project_type is project_type


def test_registry_rejects_unknown_project_type() -> None:
    with pytest.raises(UnsupportedProjectTypeError, match="factory"):
        ProfileRegistry().get("factory")


def test_registry_returns_a_defensive_copy() -> None:
    registry = ProfileRegistry()
    first = registry.get(ProjectType.SHOPPING_MALL)
    first.poi_groups[0].categories.append("测试类别")

    second = registry.get(ProjectType.SHOPPING_MALL)

    assert "测试类别" not in second.poi_groups[0].categories


def test_registry_rejects_mismatched_registration_key() -> None:
    shopping_profile = get_project_profile(ProjectType.SHOPPING_MALL)

    with pytest.raises(ValueError, match="注册键"):
        ProfileRegistry({ProjectType.LOGISTICS_PARK: shopping_profile})


def test_queries_follow_shopping_mall_profile() -> None:
    request = request_for(ProjectType.SHOPPING_MALL)
    profile = get_project_profile(ProjectType.SHOPPING_MALL)

    queries = build_poi_queries(request, profile)

    assert len(queries) == len(profile.poi_groups)
    assert [query.group_key for query in queries] == [
        group.group_key for group in profile.poi_groups
    ]
    assert queries[0].categories == ["地铁站", "公交站"]
    assert queries[0].radius_m == 1_500


def test_queries_follow_logistics_park_profile() -> None:
    request = request_for(ProjectType.LOGISTICS_PARK)
    profile = get_project_profile(ProjectType.LOGISTICS_PARK)

    queries = build_poi_queries(request, profile)

    assert len(queries) == len(profile.poi_groups)
    assert [query.group_key for query in queries] == [
        group.group_key for group in profile.poi_groups
    ]
    assert queries[0].categories == ["高速收费站", "高速出入口"]
    assert queries[0].radius_m == 15_000


def test_retail_queries_follow_store_specific_profiles() -> None:
    coffee = get_project_profile(ProjectType.COFFEE_SHOP)
    convenience = get_project_profile(ProjectType.CONVENIENCE_STORE)

    coffee_queries = build_poi_queries(
        request_for(ProjectType.COFFEE_SHOP), coffee
    )
    convenience_queries = build_poi_queries(
        request_for(ProjectType.CONVENIENCE_STORE), convenience
    )

    assert {query.group_key for query in coffee_queries} != {
        query.group_key for query in convenience_queries
    }
    assert next(
        query for query in coffee_queries if query.group_key == "coffee_competition"
    ).categories == ["咖啡馆"]
    assert next(
        query
        for query in convenience_queries
        if query.group_key == "convenience_competition"
    ).categories == ["便利店", "超市"]
    assert {query.limit for query in coffee_queries} == {1_000}
    assert {query.limit for query in convenience_queries} == {1_000}


def test_each_parcel_gets_every_profile_query_group() -> None:
    request = request_for(
        ProjectType.SHOPPING_MALL,
        [parcel("A01"), parcel("B01")],
    )
    profile = get_project_profile(ProjectType.SHOPPING_MALL)

    queries = build_poi_queries(request, profile)

    assert len(queries) == 2 * len(profile.poi_groups)
    assert len({query.query_id for query in queries}) == len(queries)
    assert {query.parcel_id for query in queries} == {"A01", "B01"}
    assert {
        (query.parcel_id, query.group_key)
        for query in queries
    } == {
        (parcel_id, group.group_key)
        for parcel_id in ("A01", "B01")
        for group in profile.poi_groups
    }


def test_query_builder_rejects_a_mismatched_profile() -> None:
    request = request_for(ProjectType.SHOPPING_MALL)
    logistics_profile = get_project_profile(ProjectType.LOGISTICS_PARK)

    with pytest.raises(ValueError, match="ProjectProfile"):
        build_poi_queries(request, logistics_profile)


def test_intake_skill_creates_data_pending_state() -> None:
    request = request_for(ProjectType.LOGISTICS_PARK)

    state = ProjectIntakeSkill().run(request)

    assert state.status is AnalysisStatus.DATA_PENDING
    assert state.profile.project_type is ProjectType.LOGISTICS_PARK
    assert len(state.poi_queries) == len(state.profile.poi_groups)
    assert state.poi_feature_sets == []


def test_unknown_type_is_rejected_before_business_routing() -> None:
    with pytest.raises(ValidationError, match="project_type"):
        ProjectRequest.model_validate(
            {
                "request_id": "REQ-unknown",
                "project_type": "factory",
                "candidate_parcels": [parcel().model_dump()],
                "requested_at": NOW,
            }
        )


def test_empty_candidate_parcels_are_rejected_before_business_routing() -> None:
    with pytest.raises(ValidationError, match="candidate_parcels"):
        ProjectRequest(
            request_id="REQ-empty",
            project_type=ProjectType.SHOPPING_MALL,
            candidate_parcels=[],
            requested_at=NOW,
        )
