from pathlib import Path

import pytest

from app.services.site_selection_poi_provider import OVERPASS_CATEGORY_FILTERS
from app.site_selection_bootstrap import build_fixture_runtime_registry
from practice.site_selection import (
    POIMetric,
    ProjectType,
    ScoreDirection,
    get_project_profile,
    load_policy_corpus,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "data" / "fixtures"


@pytest.mark.parametrize(
    ("project_type", "competition_group", "competition_categories"),
    [
        (ProjectType.COFFEE_SHOP, "coffee_competition", ["咖啡馆"]),
        (
            ProjectType.CONVENIENCE_STORE,
            "convenience_competition",
            ["便利店", "超市"],
        ),
    ],
)
def test_retail_profiles_have_store_specific_competition_evidence(
    project_type,
    competition_group,
    competition_categories,
) -> None:
    profile = get_project_profile(project_type)
    group = next(
        item for item in profile.poi_groups if item.group_key == competition_group
    )

    assert group.categories == competition_categories
    assert "竞争" in group.display_name
    assert sum(item.soft_score_weight for item in profile.poi_groups) == pytest.approx(1)


def test_retail_profiles_use_different_demand_and_access_models() -> None:
    coffee = get_project_profile(ProjectType.COFFEE_SHOP)
    convenience = get_project_profile(ProjectType.CONVENIENCE_STORE)

    assert {item.group_key for item in coffee.poi_groups} != {
        item.group_key for item in convenience.poi_groups
    }
    assert all(
        "客流" not in item.display_name
        for profile in (coffee, convenience)
        for item in profile.poi_groups
    )
    assert any("需求代理指标" in item.display_name for item in coffee.poi_groups)
    assert any(
        "需求代理指标" in item.display_name for item in convenience.poi_groups
    )


def test_all_profile_categories_have_controlled_overpass_mapping() -> None:
    categories = {
        category
        for project_type in ProjectType
        for group in get_project_profile(project_type).poi_groups
        for category in group.categories
    }

    assert categories <= OVERPASS_CATEGORY_FILTERS.keys()


@pytest.mark.parametrize(
    ("project_type", "competition_group"),
    [
        (ProjectType.COFFEE_SHOP, "coffee_competition"),
        (ProjectType.CONVENIENCE_STORE, "convenience_competition"),
    ],
)
def test_competition_scoring_rewards_fewer_and_more_distant_competitors(
    project_type,
    competition_group,
) -> None:
    runtime = build_fixture_runtime_registry(
        object(), fixture_root=FIXTURE_ROOT
    ).resolve(project_type)
    config = next(
        item
        for item in runtime.dependencies.poi_scoring_config.groups
        if item.group_key == competition_group
    )
    directions = {item.metric: item.direction for item in config.metric_rules}

    assert directions[POIMetric.COUNT] is ScoreDirection.LOWER_IS_BETTER
    assert (
        directions[POIMetric.NEAREST_DISTANCE_M]
        is ScoreDirection.HIGHER_IS_BETTER
    )


def test_retail_rules_are_fixture_evidence_and_require_human_review() -> None:
    registry = build_fixture_runtime_registry(object(), fixture_root=FIXTURE_ROOT)

    for project_type in (
        ProjectType.COFFEE_SHOP,
        ProjectType.CONVENIENCE_STORE,
    ):
        rules = registry.resolve(project_type).dependencies.rules
        assert len(rules) == 1
        assert rules[0].outcome.value == "review_required"
        assert rules[0].policy.source_uri.startswith("fixture://")


def test_retail_policy_corpus_matches_rule_pack_sources() -> None:
    corpus = load_policy_corpus(FIXTURE_ROOT / "policies.json")
    by_type = {
        project_type: {
            document.source_uri
            for document in corpus.documents
            if project_type in document.applicable_project_types
        }
        for project_type in (
            ProjectType.COFFEE_SHOP,
            ProjectType.CONVENIENCE_STORE,
        )
    }

    assert by_type[ProjectType.COFFEE_SHOP] == {
        "fixture://policies/retail-suitability"
    }
    assert by_type[ProjectType.CONVENIENCE_STORE] == {
        "fixture://policies/convenience-retail-suitability"
    }
