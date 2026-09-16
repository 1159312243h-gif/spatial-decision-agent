from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from app.schemas.site_selection import (
    SiteSelectionAnalysisResponse,
    SiteSelectionRunResponse,
)
from practice.site_selection import (
    AgentCollaborationStatus,
    AgentMemoryConflictError,
    AgentMemoryUpdate,
    AgentMessageKind,
    AgentRole,
    AgentRoster,
    CollaborationBudget,
    InMemoryAgentMemoryStore,
    MultiAgentReviewRuntime,
    ReviewVerdict,
    RedisAgentMemoryStore,
    RoleAgent,
    SpecialistResponse,
    SupervisorDecision,
    default_agent_profiles,
    run_parallel_site_selection_workflow,
)
from practice.site_selection.storage import RunStatus
from tests.test_site_selection_workflow import dependencies, manifests, request
from workbench.site_selection_client import agent_collaboration_rows


OutputFactory = Callable[[dict[str, Any]], dict[str, Any]]


class ScriptedAgentModel:
    def __init__(self, *outputs: dict[str, Any] | OutputFactory) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[AgentRole, type]] = []

    def generate(self, *, profile, response_model, payload):
        self.calls.append((profile.role, response_model))
        if not self.outputs:
            raise AssertionError(f"unexpected {profile.role.value} LLM call")
        output = self.outputs.pop(0)
        data = output(payload) if callable(output) else output
        return response_model.model_validate(data)


def _reference(payload: dict[str, Any], prefix: str) -> str:
    return next(
        item
        for item in payload["evidence"]["allowed_references"]
        if item.startswith(prefix)
    )


def _runtime_for_reflection() -> tuple[
    MultiAgentReviewRuntime,
    dict[AgentRole, ScriptedAgentModel],
    dict[AgentRole, InMemoryAgentMemoryStore],
]:
    supervisor = ScriptedAgentModel(
        lambda payload: {
            "action": "delegate",
            "target_role": "poi",
            "objective": "核对 POI 证据完整度",
            "rationale": "确定性审查包含 POI 来源信息",
            "evidence_references": [_reference(payload, "poi:")],
        },
        lambda payload: {
            "action": "review",
            "objective": "交叉检查 POI 专家意见",
            "rationale": "已有第一轮专家意见",
            "evidence_references": [_reference(payload, "poi:")],
        },
        lambda payload: {
            "action": "delegate",
            "target_role": "spatial",
            "objective": "复核 Review Agent 指出的空间风险",
            "rationale": "Critic 要求补充独立空间意见",
            "evidence_references": [_reference(payload, "gis:")],
        },
        lambda payload: {
            "action": "review",
            "objective": "形成第二轮终态复核",
            "rationale": "POI 与空间意见均已返回",
            "evidence_references": [
                _reference(payload, "poi:"),
                _reference(payload, "gis:"),
            ],
        },
    )
    poi = ScriptedAgentModel(
        lambda payload: {
            "summary": "POI 证据来源可追踪",
            "stance": "support",
            "findings": ["评分组包含来源和数据集标识"],
            "evidence_references": [_reference(payload, "poi:")],
            "memory_update": {
                "memory_key": "source-quality",
                "content": "后续优先核对 POI 截断和降级来源",
                "evidence_references": [_reference(payload, "poi:")],
                "expected_revision": 0,
            },
        }
    )
    spatial = ScriptedAgentModel(
        lambda payload: {
            "summary": "空间指标与 CRS 证据一致",
            "stance": "support",
            "findings": ["空间指标可由已引用 GIS 证据复核"],
            "evidence_references": [_reference(payload, "gis:")],
        }
    )
    policy = ScriptedAgentModel()
    reviewer = ScriptedAgentModel(
        lambda payload: {
            "action": "redelegate",
            "summary": "POI 意见尚不能覆盖空间证据",
            "rationale": "需要独立 Spatial Agent 交叉核验",
            "target_role": "spatial",
            "follow_up_objective": "复核 CRS、几何和空间指标",
            "evidence_references": [_reference(payload, "gis:")],
        },
        lambda payload: {
            "action": "accept",
            "summary": "两类专家意见与确定性证据一致",
            "rationale": "交叉检查未发现无引用结论",
            "evidence_references": [
                _reference(payload, "poi:"),
                _reference(payload, "gis:"),
            ],
        },
    )
    models = {
        AgentRole.SUPERVISOR: supervisor,
        AgentRole.POI: poi,
        AgentRole.SPATIAL: spatial,
        AgentRole.POLICY: policy,
        AgentRole.REVIEW: reviewer,
    }
    profiles = default_agent_profiles("fixture-model")
    stores = {role: InMemoryAgentMemoryStore() for role in models}
    roster = {
        role: RoleAgent(
            profile=profiles[role],
            model=model,
            memory_store=stores[role],
        )
        for role, model in models.items()
    }
    runtime = MultiAgentReviewRuntime(
        AgentRoster(agents=roster),
        budget=CollaborationBudget(
            max_delegations=4,
            max_reflection_rounds=2,
            max_llm_calls=10,
        ),
        clock=lambda: datetime(2026, 9, 12, tzinfo=UTC),
    )
    return runtime, models, stores


def test_multi_agent_review_redelegates_and_preserves_business_truth() -> None:
    deterministic = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        dependencies(),
    )
    runtime, models, stores = _runtime_for_reflection()
    reviewed = runtime.review(deterministic, conversation_id="collab-test-001")

    report = reviewed.collaboration_report
    assert report is not None
    assert report.status is AgentCollaborationStatus.ACCEPTED
    assert report.delegation_count == 2
    assert report.reflection_rounds == 1
    assert report.llm_calls == 8
    assert [message.kind for message in report.messages] == [
        AgentMessageKind.DELEGATION,
        AgentMessageKind.FINDING,
        AgentMessageKind.DELEGATION,
        AgentMessageKind.CRITIQUE,
        AgentMessageKind.DELEGATION,
        AgentMessageKind.FINDING,
        AgentMessageKind.DELEGATION,
        AgentMessageKind.DECISION,
    ]
    assert len(models[AgentRole.POI].calls) == 1
    assert len(models[AgentRole.SPATIAL].calls) == 1
    assert len(models[AgentRole.POLICY].calls) == 0
    assert stores[AgentRole.POI].recall(
        AgentRole.POI,
        memory_scope="project:shopping_mall",
        limit=5,
    )[0].revision == 1
    assert stores[AgentRole.SUPERVISOR].recall(
        AgentRole.SUPERVISOR,
        memory_scope="project:shopping_mall",
        limit=5,
    ) == []

    api_analysis = SiteSelectionAnalysisResponse.from_state(reviewed)
    run_response = SiteSelectionRunResponse(
        run_id="run-collab-001",
        status=RunStatus.COMPLETED,
        updated_at=datetime(2026, 9, 12, tzinfo=UTC),
        request_id=reviewed.request.request_id,
        analysis=api_analysis,
    )
    assert api_analysis.collaboration_report == report
    assert agent_collaboration_rows(run_response)[3]["kind"] == "critique"

    before = deterministic.model_dump()
    after = reviewed.model_dump()
    before["collaboration_report"] = after["collaboration_report"]
    assert after == before


def test_parallel_workflow_runs_opt_in_multi_agent_review() -> None:
    runtime, _, _ = _runtime_for_reflection()
    configured = replace(dependencies(), multi_agent_runtime=runtime)

    result = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        configured,
    )

    assert result.collaboration_report is not None
    assert result.collaboration_report.status is AgentCollaborationStatus.ACCEPTED
    assert [trace.node_id for trace in result.agent_trace] == [
        "intake",
        "poi_evidence",
        "spatial_evidence",
        "policy_rules",
        "merge_gate",
        "review",
    ]


def test_unknown_evidence_reference_fails_closed() -> None:
    deterministic = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        dependencies(),
    )
    profiles = default_agent_profiles("fixture-model")
    stores = {
        role: InMemoryAgentMemoryStore()
        for role in profiles
    }
    models = {
        role: ScriptedAgentModel(
            {
                "action": "review",
                "objective": "尝试引用未知证据",
                "rationale": "协议违规测试",
                "evidence_references": ["external:invented-fact"],
            }
        )
        for role in profiles
    }
    runtime = MultiAgentReviewRuntime(
        AgentRoster(
            agents={
                role: RoleAgent(profiles[role], models[role], stores[role])
                for role in profiles
            }
        )
    )

    result = runtime.review(deterministic, conversation_id="collab-invalid-ref")

    report = result.collaboration_report
    assert report is not None
    assert report.status is AgentCollaborationStatus.FAILED
    assert report.llm_calls == 1
    assert report.human_review_reason == (
        "supervisor Agent 失败：AgentProtocolViolationError"
    )


def test_reflection_budget_exhaustion_routes_to_human_review() -> None:
    deterministic = run_parallel_site_selection_workflow(
        request(),
        manifests(),
        dependencies(),
    )
    supervisor = ScriptedAgentModel(
        lambda payload: {
            "action": "delegate",
            "target_role": "poi",
            "objective": "核对 POI",
            "rationale": "执行第一轮专家复核",
            "evidence_references": [_reference(payload, "poi:")],
        }
    )
    poi = ScriptedAgentModel(
        lambda payload: {
            "summary": "POI 专家意见",
            "stance": "challenge",
            "findings": ["需要空间专家交叉检查"],
            "evidence_references": [_reference(payload, "poi:")],
            "suggested_next_role": "spatial",
        }
    )
    reviewer = ScriptedAgentModel(
        lambda payload: {
            "action": "redelegate",
            "summary": "当前意见不足",
            "rationale": "仍需补充空间核验",
            "target_role": "spatial",
            "follow_up_objective": "核对空间证据",
            "evidence_references": [_reference(payload, "gis:")],
        }
    )
    models = {
        AgentRole.SUPERVISOR: supervisor,
        AgentRole.POI: poi,
        AgentRole.SPATIAL: ScriptedAgentModel(),
        AgentRole.POLICY: ScriptedAgentModel(),
        AgentRole.REVIEW: reviewer,
    }
    profiles = default_agent_profiles("fixture-model")
    runtime = MultiAgentReviewRuntime(
        AgentRoster(
            agents={
                role: RoleAgent(
                    profiles[role],
                    model,
                    InMemoryAgentMemoryStore(),
                )
                for role, model in models.items()
            }
        ),
        budget=CollaborationBudget(
            max_delegations=1,
            max_reflection_rounds=0,
            max_llm_calls=5,
        ),
    )

    result = runtime.review(deterministic, conversation_id="collab-budget")

    report = result.collaboration_report
    assert report is not None
    assert report.status is AgentCollaborationStatus.BUDGET_EXHAUSTED
    assert report.human_review_reason == "自反思轮数预算已耗尽"
    assert report.delegation_count == 1
    assert report.llm_calls == 3


def test_agent_memory_is_role_scoped_and_detects_stale_update() -> None:
    store = InMemoryAgentMemoryStore()
    now = datetime(2026, 9, 12, tzinfo=UTC)
    update = AgentMemoryUpdate(
        memory_key="quality-gate",
        content="核对来源版本",
        expected_revision=0,
    )
    first = store.upsert(
        AgentRole.POI,
        update,
        memory_scope="project:shopping_mall",
        updated_at=now,
    )

    assert first.revision == 1
    assert store.recall(
        AgentRole.POLICY,
        memory_scope="project:shopping_mall",
        limit=5,
    ) == []
    assert store.recall(
        AgentRole.POI,
        memory_scope="project:logistics_park",
        limit=5,
    ) == []
    with pytest.raises(AgentMemoryConflictError, match="revision conflict"):
        store.upsert(
            AgentRole.POI,
            update,
            memory_scope="project:shopping_mall",
            updated_at=now,
        )


def test_redis_agent_memory_survives_store_recreation() -> None:
    class FakePipeline:
        def __init__(self, client) -> None:
            self.client = client

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def watch(self, key):
            self.key = key

        def hget(self, key, field):
            return self.client.hashes.get(key, {}).get(field)

        def multi(self):
            return None

        def hset(self, key, field, value):
            self.client.hashes.setdefault(key, {})[field] = value

        def expire(self, key, ttl):
            self.client.expirations[key] = ttl

        def execute(self):
            return [1, True]

    class FakeRedisMemory:
        def __init__(self) -> None:
            self.hashes = {}
            self.expirations = {}

        def pipeline(self):
            return FakePipeline(self)

        def hvals(self, key):
            return list(self.hashes.get(key, {}).values())

    redis = FakeRedisMemory()
    first_store = RedisAgentMemoryStore(redis, ttl_seconds=60)
    first_store.upsert(
        AgentRole.POLICY,
        AgentMemoryUpdate(
            memory_key="rule-version",
            content="未命中规则不等于整体合规",
            expected_revision=0,
        ),
        memory_scope="project:shopping_mall",
        updated_at=datetime(2026, 9, 12, tzinfo=UTC),
    )

    second_store = RedisAgentMemoryStore(redis, ttl_seconds=60)
    records = second_store.recall(
        AgentRole.POLICY,
        memory_scope="project:shopping_mall",
        limit=5,
    )

    assert [(record.memory_key, record.revision) for record in records] == [
        ("rule-version", 1)
    ]
    assert second_store.recall(
        AgentRole.POI,
        memory_scope="project:shopping_mall",
        limit=5,
    ) == []


def test_contracts_reject_invalid_role_transitions() -> None:
    with pytest.raises(ValueError, match="delegate"):
        SupervisorDecision(
            action="delegate",
            target_role="review",
            objective="错误委派",
            rationale="测试",
        )
    with pytest.raises(ValueError, match="redelegate"):
        ReviewVerdict(
            action="redelegate",
            summary="需要复核",
            rationale="缺少目标",
        )
    with pytest.raises(ValueError, match="evidence_references"):
        SpecialistResponse(
            summary="缺少引用",
            stance="insufficient",
            findings=["没有证据"],
            evidence_references=[],
        )
