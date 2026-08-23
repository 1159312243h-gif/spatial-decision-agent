from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.services.site_selection_conversation import (
    ScenarioConfirmationBlockedError,
    ScenarioVersionConflictError,
    SiteSelectionConversationService,
)
from practice.site_selection import (
    ConversationTurnStatus,
    FixtureRegionResolver,
    InMemoryScenarioSessionStore,
    RegionCatalogEntry,
    RuleBasedScenarioInterpreter,
    ScenarioVersionStatus,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "data" / "fixtures"


def region_resolver() -> FixtureRegionResolver:
    payload = json.loads(
        (FIXTURE_ROOT / "regions.json").read_text(encoding="utf-8")
    )
    return FixtureRegionResolver(
        [RegionCatalogEntry.model_validate(item) for item in payload["entries"]]
    )


def service() -> SiteSelectionConversationService:
    identifiers = iter(f"id-{index}" for index in range(100))
    return SiteSelectionConversationService(
        InMemoryScenarioSessionStore(),
        RuleBasedScenarioInterpreter(),
        region_resolver(),
        clock=lambda: datetime(2026, 8, 21, tzinfo=timezone.utc),
        id_factory=lambda: next(identifiers),
    )


def test_conversation_builds_auditable_region_scenario_and_confirms_it() -> None:
    conversation = service()

    proposed = conversation.converse(
        "在上海市徐汇区开咖啡店，范围 4 公里，找出 8 个候选点，租金不超过 3"
    )

    assert proposed.status is ConversationTurnStatus.AWAITING_CONFIRMATION
    assert proposed.scenario_version.region_text == "上海市徐汇区"
    assert proposed.scenario_version.region_resolution.normalized_name == (
        "上海市徐汇区"
    )
    assert proposed.scenario_version.region_resolution.source.value == (
        "fixture_catalog"
    )
    assert proposed.discovery_request is not None
    assert proposed.discovery_request.max_candidates == 8
    constraints = {
        item.key.value: item for item in proposed.scenario_version.recorded_constraints
    }
    assert constraints["max_rent"].readiness.value == "missing_data"
    assert "不会参与候选过滤或评分" in constraints["max_rent"].reason

    confirmed = conversation.confirm(
        proposed.session_id,
        proposed.scenario_version.version_id,
        confirmed_by="planner-001",
    )

    assert confirmed.status is ConversationTurnStatus.CONFIRMED
    assert confirmed.scenario_version.status is ScenarioVersionStatus.CONFIRMED
    assert confirmed.scenario_version.confirmed_by == "planner-001"
    assert confirmed.discovery_request.bounds == (
        proposed.scenario_version.region_resolution.discovery_bounds
    )


def test_follow_up_replaces_region_and_preserves_parent_version() -> None:
    conversation = service()
    first = conversation.converse("在徐汇区开便利店，范围 3 公里")
    conversation.confirm(
        first.session_id,
        first.scenario_version.version_id,
        confirmed_by="planner-001",
    )

    second = conversation.converse(
        "区域改为长宁区，候选数量 10 个",
        session_id=first.session_id,
    )

    assert second.scenario_version.version_number == 2
    assert second.scenario_version.parent_version_id == (
        first.scenario_version.version_id
    )
    assert second.scenario_version.region_resolution.normalized_name == (
        "上海市长宁区"
    )
    assert second.discovery_request.max_candidates == 10

    confirmed = conversation.confirm(
        second.session_id,
        second.scenario_version.version_id,
        confirmed_by="planner-002",
    )
    session = conversation.get_session(second.session_id)
    assert session.active_version_id == confirmed.scenario_version.version_id
    assert session.versions[0].status is ScenarioVersionStatus.SUPERSEDED


def test_invalid_range_and_stale_confirmation_are_blocked() -> None:
    conversation = service()
    invalid = conversation.converse("在徐汇区开咖啡店，范围 9 公里")

    assert invalid.status is ConversationTurnStatus.NEEDS_CLARIFICATION
    assert invalid.scenario_version.conflicts[0].key.value == (
        "discovery_radius_km"
    )
    with pytest.raises(ScenarioConfirmationBlockedError):
        conversation.confirm(
            invalid.session_id,
            invalid.scenario_version.version_id,
            confirmed_by="planner-001",
        )

    ready = conversation.converse(
        "范围 4 公里",
        session_id=invalid.session_id,
    )
    with pytest.raises(ScenarioVersionConflictError):
        conversation.confirm(
            ready.session_id,
            invalid.scenario_version.version_id,
            confirmed_by="planner-001",
        )


def test_non_retail_scenario_keeps_manual_candidate_workflow() -> None:
    conversation = service()
    proposed = conversation.converse("建设物流园，严格用地")

    assert proposed.status is ConversationTurnStatus.AWAITING_CONFIRMATION
    assert proposed.discovery_request is None
    confirmed = conversation.confirm(
        proposed.session_id,
        proposed.scenario_version.version_id,
        confirmed_by="planner-001",
    )
    assert "人工候选录入" in confirmed.answer
