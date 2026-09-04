from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.services.site_selection_conversation import (
    ScenarioActorConflictError,
    ScenarioMemoryConsentRequiredError,
    SiteSelectionConversationService,
)
from practice.site_selection import (
    FixtureRegionResolver,
    InMemoryScenarioMemoryStore,
    InMemoryScenarioSessionStore,
    RegionCatalogEntry,
    RuleBasedScenarioInterpreter,
    ScenarioMemoryMode,
    StructuredScenarioContextCompactor,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "data" / "fixtures"
NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def region_resolver() -> FixtureRegionResolver:
    payload = json.loads(
        (FIXTURE_ROOT / "regions.json").read_text(encoding="utf-8")
    )
    return FixtureRegionResolver(
        [RegionCatalogEntry.model_validate(item) for item in payload["entries"]]
    )


def build_service(
    *,
    memory_store: InMemoryScenarioMemoryStore | None = None,
    interpreter=None,
    recent_messages: int = 6,
) -> SiteSelectionConversationService:
    identifiers = iter(f"memory-id-{index}" for index in range(500))
    return SiteSelectionConversationService(
        InMemoryScenarioSessionStore(),
        interpreter or RuleBasedScenarioInterpreter(),
        region_resolver(),
        memory_store=memory_store or InMemoryScenarioMemoryStore(),
        context_compactor=StructuredScenarioContextCompactor(
            max_recent_messages=recent_messages
        ),
        clock=lambda: NOW,
        id_factory=lambda: next(identifiers),
    )


def remember_convenience_store_defaults(
    service: SiteSelectionConversationService,
    actor_id: str,
) -> None:
    proposed = service.converse(
        "在徐汇区开便利店，范围 3 公里，候选数量 10 个，最小间距 900 米",
        actor_id=actor_id,
        memory_mode=ScenarioMemoryMode.APPLY_DEFAULTS,
    )
    confirmed = service.confirm(
        proposed.session_id,
        proposed.scenario_version.version_id,
        confirmed_by=actor_id,
        remember_preferences=True,
    )
    assert confirmed.memory_saved is True


def test_confirmed_preferences_fill_only_missing_fields_in_new_session() -> None:
    memory_store = InMemoryScenarioMemoryStore()
    service = build_service(memory_store=memory_store)
    remember_convenience_store_defaults(service, "planner-001")

    recalled = service.converse(
        "在长宁区开便利店",
        actor_id="planner-001",
        memory_mode=ScenarioMemoryMode.APPLY_DEFAULTS,
    )

    assert recalled.scenario_version.discovery_radius_km == 3
    assert recalled.scenario_version.max_candidates == 10
    assert recalled.scenario_version.minimum_separation_m == 900
    assert recalled.memory_recall is not None
    assert set(recalled.memory_recall.applied_fields) == {
        "discovery_radius_km",
        "max_candidates",
        "minimum_separation_m",
        "fallback_mode",
    }
    assert "已应用跨会话偏好" in recalled.answer


def test_current_message_overrides_recalled_preferences() -> None:
    memory_store = InMemoryScenarioMemoryStore()
    service = build_service(memory_store=memory_store)
    remember_convenience_store_defaults(service, "planner-002")

    recalled = service.converse(
        "在长宁区开便利店，范围 5 公里，找出 6 个候选点",
        actor_id="planner-002",
        memory_mode=ScenarioMemoryMode.APPLY_DEFAULTS,
    )

    assert recalled.scenario_version.discovery_radius_km == 5
    assert recalled.scenario_version.max_candidates == 6
    assert recalled.scenario_version.minimum_separation_m == 900
    assert set(recalled.memory_recall.applied_fields) == {
        "minimum_separation_m",
        "fallback_mode",
    }


def test_suggest_mode_does_not_mutate_scenario_defaults() -> None:
    memory_store = InMemoryScenarioMemoryStore()
    service = build_service(memory_store=memory_store)
    remember_convenience_store_defaults(service, "planner-003")

    proposed = service.converse(
        "在长宁区开便利店",
        actor_id="planner-003",
        memory_mode=ScenarioMemoryMode.SUGGEST,
    )

    assert proposed.scenario_version.discovery_radius_km == 4
    assert proposed.scenario_version.max_candidates == 8
    assert proposed.scenario_version.minimum_separation_m == 600
    assert proposed.memory_recall.preference is not None
    assert proposed.memory_recall.applied_fields == []
    assert "仅作为建议" in proposed.answer


def test_memory_is_actor_scoped_and_can_be_deleted() -> None:
    memory_store = InMemoryScenarioMemoryStore()
    service = build_service(memory_store=memory_store)
    remember_convenience_store_defaults(service, "planner-owner")

    isolated = service.converse(
        "在长宁区开便利店",
        actor_id="planner-other",
        memory_mode=ScenarioMemoryMode.APPLY_DEFAULTS,
    )
    assert isolated.scenario_version.discovery_radius_km == 4
    assert isolated.memory_recall.preference is None

    before = service.get_memory("planner-owner")
    assert len(before.preferences) == 1
    assert len(before.recent_episodes) == 1
    deleted = service.delete_memory("planner-owner")
    assert deleted.deleted_preferences == 1
    assert deleted.deleted_episodes == 1
    assert service.get_memory("planner-owner").preferences == []


def test_memory_write_requires_actor_and_session_actor_cannot_change() -> None:
    service = build_service()
    anonymous = service.converse("在徐汇区开便利店")
    with pytest.raises(ScenarioMemoryConsentRequiredError):
        service.confirm(
            anonymous.session_id,
            anonymous.scenario_version.version_id,
            confirmed_by="planner",
            remember_preferences=True,
        )

    owned = service.converse(
        "在徐汇区开便利店",
        actor_id="planner-owner",
    )
    with pytest.raises(ScenarioActorConflictError):
        service.converse(
            "范围 3 公里",
            session_id=owned.session_id,
            actor_id="planner-other",
        )


class CapturingInterpreter(RuleBasedScenarioInterpreter):
    def __init__(self) -> None:
        self.contexts = []

    def interpret_with_context(self, message, current, context):
        self.contexts.append(context)
        return super().interpret_with_context(message, current, context)


def test_old_messages_are_compressed_but_full_audit_history_is_retained() -> None:
    interpreter = CapturingInterpreter()
    service = build_service(interpreter=interpreter, recent_messages=4)
    first = service.converse("在徐汇区开便利店")
    service.converse("范围 3 公里", session_id=first.session_id)
    service.converse("候选数量 10 个", session_id=first.session_id)
    fourth = service.converse("最小间距 900 米", session_id=first.session_id)

    assert interpreter.contexts[-1].summary is not None
    assert len(interpreter.contexts[-1].recent_messages) == 4
    assert fourth.context_summary is not None
    assert fourth.context_summary.covered_message_count == 4
    assert fourth.context_summary.retained_message_count == 4
    assert fourth.context_summary.compression_ratio <= 1
    assert len(service.get_session(first.session_id).messages) == 8


class FailingMemoryStore:
    def get_preference(self, actor_id, project_type):
        raise RuntimeError("memory unavailable")

    def list_preferences(self, actor_id):
        raise RuntimeError("memory unavailable")

    def save_preference(self, preference):
        raise RuntimeError("memory unavailable")

    def save_episode(self, episode):
        raise RuntimeError("memory unavailable")

    def save_confirmed_memory(self, preference, episode):
        raise RuntimeError("memory unavailable")

    def list_episodes(self, actor_id, *, project_type=None, limit=5):
        raise RuntimeError("memory unavailable")

    def delete_actor_memory(self, actor_id):
        raise RuntimeError("memory unavailable")


def test_unavailable_long_term_memory_does_not_block_current_session() -> None:
    service = build_service(memory_store=FailingMemoryStore())

    proposed = service.converse(
        "在徐汇区开便利店",
        actor_id="planner-degraded",
        memory_mode=ScenarioMemoryMode.APPLY_DEFAULTS,
    )
    assert proposed.scenario_version.discovery_radius_km == 4
    assert proposed.memory_recall is None
    assert "已降级为当前会话" in proposed.memory_warnings[0]

    confirmed = service.confirm(
        proposed.session_id,
        proposed.scenario_version.version_id,
        confirmed_by="planner-degraded",
        remember_preferences=True,
    )
    assert confirmed.status.value == "confirmed"
    assert confirmed.memory_saved is False
    assert "保存失败" in confirmed.memory_warnings[0]
    assert service.get_session(proposed.session_id).active_version_id == (
        proposed.scenario_version.version_id
    )
