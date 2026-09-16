from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol, TypedDict, TypeVar
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from .agent_collaboration_contracts import (
    AgentCollaborationReport,
    AgentCollaborationStatus,
    AgentMemoryRecord,
    AgentMemoryUpdate,
    AgentMessage,
    AgentMessageKind,
    ReviewAction,
    ReviewVerdict,
    SpecialistResponse,
    SupervisorAction,
    SupervisorDecision,
)
from .agent_orchestration import AgentRole
from .evidence import AgentState, AnalysisStatus


class AgentProtocolViolationError(RuntimeError):
    """Raised when an Agent response exceeds its reviewed evidence boundary."""


class AgentMemoryConflictError(RuntimeError):
    """Raised when a stale Agent tries to overwrite newer role memory."""


class AgentMemoryStore(Protocol):
    def recall(
        self,
        role: AgentRole,
        *,
        memory_scope: str,
        limit: int,
    ) -> list[AgentMemoryRecord]: ...

    def upsert(
        self,
        role: AgentRole,
        update: AgentMemoryUpdate,
        *,
        memory_scope: str,
        updated_at: datetime,
    ) -> AgentMemoryRecord: ...


class InMemoryAgentMemoryStore:
    """Thread-safe role memory used in tests and local single-process runs."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, AgentRole, str], AgentMemoryRecord] = {}
        self._lock = RLock()

    def recall(
        self,
        role: AgentRole,
        *,
        memory_scope: str,
        limit: int,
    ) -> list[AgentMemoryRecord]:
        if limit <= 0:
            raise ValueError("Agent 记忆召回数量必须大于 0")
        with self._lock:
            records = [
                item
                for (stored_scope, stored_role, _), item in self._records.items()
                if stored_scope == memory_scope and stored_role is role
            ]
            records.sort(
                key=lambda item: (item.updated_at, item.memory_key),
                reverse=True,
            )
            return [item.model_copy(deep=True) for item in records[:limit]]

    def upsert(
        self,
        role: AgentRole,
        update: AgentMemoryUpdate,
        *,
        memory_scope: str,
        updated_at: datetime,
    ) -> AgentMemoryRecord:
        key = (memory_scope, role, update.memory_key)
        with self._lock:
            existing = self._records.get(key)
            current_revision = existing.revision if existing is not None else 0
            if (
                update.expected_revision is not None
                and update.expected_revision != current_revision
            ):
                raise AgentMemoryConflictError(
                    f"{role.value}:{update.memory_key} memory revision conflict"
                )
            record = AgentMemoryRecord(
                memory_scope=memory_scope,
                role=role,
                memory_key=update.memory_key,
                content=update.content,
                evidence_references=update.evidence_references,
                revision=current_revision + 1,
                updated_at=updated_at,
            )
            self._records[key] = record
            return record.model_copy(deep=True)


class RedisAgentMemoryStore:
    """Durable role-isolated memory backed by Redis hashes."""

    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "site-selection:agent-memory",
        ttl_seconds: int = 2_592_000,
        max_conflict_retries: int = 3,
    ) -> None:
        if client is None or not namespace.strip():
            raise ValueError("Redis Agent 记忆必须配置客户端和 namespace")
        if ttl_seconds <= 0 or max_conflict_retries <= 0:
            raise ValueError("Redis Agent 记忆 TTL 和冲突重试次数必须大于 0")
        self._client = client
        self._namespace = namespace.strip(":")
        self._ttl_seconds = ttl_seconds
        self._max_conflict_retries = max_conflict_retries

    def recall(
        self,
        role: AgentRole,
        *,
        memory_scope: str,
        limit: int,
    ) -> list[AgentMemoryRecord]:
        if limit <= 0:
            raise ValueError("Agent 记忆召回数量必须大于 0")
        raw_records = self._client.hvals(
            self._role_key(memory_scope, role)
        )
        records = [
            AgentMemoryRecord.model_validate_json(_decode_redis(item))
            for item in raw_records
        ]
        records.sort(
            key=lambda item: (item.updated_at, item.memory_key),
            reverse=True,
        )
        return records[:limit]

    def upsert(
        self,
        role: AgentRole,
        update: AgentMemoryUpdate,
        *,
        memory_scope: str,
        updated_at: datetime,
    ) -> AgentMemoryRecord:
        from redis.exceptions import WatchError

        redis_key = self._role_key(memory_scope, role)
        for _ in range(self._max_conflict_retries):
            with self._client.pipeline() as pipeline:
                try:
                    pipeline.watch(redis_key)
                    raw = pipeline.hget(redis_key, update.memory_key)
                    existing = (
                        AgentMemoryRecord.model_validate_json(
                            _decode_redis(raw)
                        )
                        if raw is not None
                        else None
                    )
                    current_revision = (
                        existing.revision if existing is not None else 0
                    )
                    if (
                        update.expected_revision is not None
                        and update.expected_revision != current_revision
                    ):
                        raise AgentMemoryConflictError(
                            f"{role.value}:{update.memory_key} memory revision conflict"
                        )
                    record = AgentMemoryRecord(
                        memory_scope=memory_scope,
                        role=role,
                        memory_key=update.memory_key,
                        content=update.content,
                        evidence_references=update.evidence_references,
                        revision=current_revision + 1,
                        updated_at=updated_at,
                    )
                    pipeline.multi()
                    pipeline.hset(
                        redis_key,
                        update.memory_key,
                        record.model_dump_json(),
                    )
                    pipeline.expire(redis_key, self._ttl_seconds)
                    pipeline.execute()
                    return record
                except WatchError:
                    continue
        raise AgentMemoryConflictError(
            f"{role.value}:{update.memory_key} memory write contention"
        )

    def _role_key(self, memory_scope: str, role: AgentRole) -> str:
        normalized = memory_scope.strip().replace(":", "_")
        if not normalized:
            raise ValueError("Agent memory_scope 不能为空")
        return f"{self._namespace}:{normalized}:{role.value}"


class AgentPromptProfile(BaseModel):
    """Independent model, prompt and context budget for one Agent role."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: AgentRole
    model: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    memory_limit: int = Field(default=6, ge=1, le=50)
    message_limit: int = Field(default=12, ge=1, le=50)


ResponseT = TypeVar("ResponseT", bound=BaseModel)


class StructuredAgentModel(Protocol):
    def generate(
        self,
        *,
        profile: AgentPromptProfile,
        response_model: type[ResponseT],
        payload: dict[str, Any],
    ) -> ResponseT: ...


class OpenAIStructuredAgentModel:
    """Strict JSON adapter for OpenAI-compatible Responses clients."""

    def __init__(self, client: Any) -> None:
        if client is None:
            raise ValueError("Agent LLM 必须配置客户端")
        self._client = client

    def generate(
        self,
        *,
        profile: AgentPromptProfile,
        response_model: type[ResponseT],
        payload: dict[str, Any],
    ) -> ResponseT:
        schema = response_model.model_json_schema()
        response = self._client.responses.create(
            model=profile.model,
            instructions=(
                profile.system_prompt
                + "\n只能依据输入证据工作，不得修改评分、排序或规则结果。"
                + "memory_update 只能保存可复用的审查方法，不得保存姓名、精确位置"
                + "或其他用户特定信息。"
                + "只返回符合以下 JSON Schema 的 JSON："
                + json.dumps(schema, ensure_ascii=False, sort_keys=True)
            ),
            input=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
        raw = getattr(response, "output_text", "").strip()
        if not raw:
            raise RuntimeError(f"{profile.role.value} Agent returned empty output")
        return response_model.model_validate_json(raw)


@dataclass(frozen=True)
class RoleAgent:
    profile: AgentPromptProfile
    model: StructuredAgentModel
    memory_store: AgentMemoryStore

    def generate(
        self,
        response_model: type[ResponseT],
        *,
        memory_scope: str,
        evidence: dict[str, Any],
        messages: Sequence[AgentMessage],
    ) -> ResponseT:
        memories = self.memory_store.recall(
            self.profile.role,
            memory_scope=memory_scope,
            limit=self.profile.memory_limit,
        )
        return self.model.generate(
            profile=self.profile,
            response_model=response_model,
            payload={
                "role": self.profile.role.value,
                "evidence": evidence,
                "recent_messages": [
                    item.model_dump(mode="json")
                    for item in messages[-self.profile.message_limit :]
                ],
                "role_memory": [
                    item.model_dump(mode="json") for item in memories
                ],
            },
        )


@dataclass(frozen=True)
class AgentRoster:
    agents: Mapping[AgentRole, RoleAgent]

    def __post_init__(self) -> None:
        object.__setattr__(self, "agents", dict(self.agents))
        required = {
            AgentRole.SUPERVISOR,
            AgentRole.POI,
            AgentRole.SPATIAL,
            AgentRole.POLICY,
            AgentRole.REVIEW,
        }
        configured = set(self.agents)
        if configured != required:
            missing = sorted(role.value for role in required - configured)
            extra = sorted(role.value for role in configured - required)
            details = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if extra:
                details.append("extra=" + ",".join(extra))
            raise ValueError("Agent roster 不完整：" + "; ".join(details))
        for role, agent in self.agents.items():
            if agent.profile.role is not role:
                raise ValueError(f"Agent profile role mismatch: {role.value}")

    def get(self, role: AgentRole) -> RoleAgent:
        return self.agents[role]


class CollaborationBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_delegations: int = Field(default=6, ge=1, le=30)
    max_reflection_rounds: int = Field(default=2, ge=0, le=10)
    max_llm_calls: int = Field(default=12, ge=2, le=60)


class CollaborationGraphState(TypedDict, total=False):
    analysis: AgentState
    conversation_id: str
    memory_scope: str
    evidence: dict[str, Any]
    allowed_references: list[str]
    messages: list[AgentMessage]
    supervisor_decision: SupervisorDecision
    review_verdict: ReviewVerdict
    delegation_count: int
    reflection_rounds: int
    llm_calls: int
    terminal_status: AgentCollaborationStatus
    final_summary: str
    human_review_reason: str
    collaboration_report: AgentCollaborationReport


class MultiAgentReviewRuntime:
    """Bounded LangGraph runtime for delegated review and self-reflection.

    The collaboration layer can challenge or escalate deterministic results,
    but it cannot mutate evidence, scores, rankings or policy outcomes.
    """

    def __init__(
        self,
        roster: AgentRoster,
        *,
        budget: CollaborationBudget | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._roster = roster
        self._budget = budget or CollaborationBudget()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._graph = self._build_graph()

    def review(
        self,
        state: AgentState,
        *,
        conversation_id: str | None = None,
        prepared_evidence: tuple[dict[str, Any], set[str]] | None = None,
    ) -> AgentState:
        if state.status is not AnalysisStatus.COMPLETED:
            raise ValueError("多 Agent 复核只能处理已完成的确定性分析")
        if state.evidence_review_report is None:
            raise ValueError("多 Agent 复核要求先完成确定性证据审查")
        evidence, references = prepared_evidence or build_collaboration_evidence(
            state
        )
        resolved_id = conversation_id or (
            f"collab-{state.request.request_id}-{uuid4().hex[:12]}"
        )
        output = self._graph.invoke(
            {
                "analysis": state,
                "conversation_id": resolved_id,
                "memory_scope": f"project:{state.request.project_type.value}",
                "evidence": evidence,
                "allowed_references": sorted(references),
                "messages": [],
                "delegation_count": 0,
                "reflection_rounds": 0,
                "llm_calls": 0,
            }
        )
        report = AgentCollaborationReport.model_validate(
            output["collaboration_report"]
        )
        data = state.model_dump()
        data["collaboration_report"] = report.model_dump(mode="json")
        return AgentState.model_validate(data)

    @property
    def budget(self) -> CollaborationBudget:
        return self._budget.model_copy(deep=True)

    @property
    def roster(self) -> AgentRoster:
        return self._roster

    def _build_graph(self):
        builder = StateGraph(CollaborationGraphState)
        builder.add_node("supervisor", self._supervisor_node)
        builder.add_node("poi_agent", self._specialist_node(AgentRole.POI))
        builder.add_node(
            "spatial_agent",
            self._specialist_node(AgentRole.SPATIAL),
        )
        builder.add_node(
            "policy_agent",
            self._specialist_node(AgentRole.POLICY),
        )
        builder.add_node("review_agent", self._review_node)
        builder.add_node("finalize", self._finalize_node)
        builder.add_edge(START, "supervisor")
        builder.add_conditional_edges(
            "supervisor",
            self._route_after_supervisor,
            {
                "poi_agent": "poi_agent",
                "spatial_agent": "spatial_agent",
                "policy_agent": "policy_agent",
                "review_agent": "review_agent",
                "finalize": "finalize",
            },
        )
        for node_id in ("poi_agent", "spatial_agent", "policy_agent"):
            builder.add_conditional_edges(
                node_id,
                self._route_after_specialist,
                {"supervisor": "supervisor", "finalize": "finalize"},
            )
        builder.add_conditional_edges(
            "review_agent",
            self._route_after_review,
            {"supervisor": "supervisor", "finalize": "finalize"},
        )
        builder.add_edge("finalize", END)
        return builder.compile()

    def _supervisor_node(
        self,
        state: CollaborationGraphState,
    ) -> dict[str, Any]:
        if state["llm_calls"] >= self._budget.max_llm_calls:
            return self._budget_failure("LLM 调用预算已耗尽")
        if state["delegation_count"] >= self._budget.max_delegations:
            return {
                "supervisor_decision": SupervisorDecision(
                    action=SupervisorAction.REVIEW,
                    objective="在现有专家意见上执行终态复核",
                    rationale="动态委派预算已用完，禁止继续扩张任务",
                )
            }
        agent = self._roster.get(AgentRole.SUPERVISOR)
        try:
            decision = agent.generate(
                SupervisorDecision,
                memory_scope=state["memory_scope"],
                evidence=state["evidence"],
                messages=state["messages"],
            )
            self._validate_output(decision, state["allowed_references"])
            self._remember(agent, decision.memory_update, state)
        except Exception as exc:
            return self._agent_failure(
                AgentRole.SUPERVISOR,
                exc,
                llm_calls=state["llm_calls"] + 1,
            )

        messages = list(state["messages"])
        if decision.action is SupervisorAction.DELEGATE:
            messages.append(
                self._message(
                    state,
                    sender=AgentRole.SUPERVISOR,
                    recipient=decision.target_role,
                    kind=AgentMessageKind.DELEGATION,
                    content=f"{decision.objective}；委派理由：{decision.rationale}",
                    evidence_references=decision.evidence_references,
                )
            )
        elif decision.action is SupervisorAction.REVIEW:
            messages.append(
                self._message(
                    state,
                    sender=AgentRole.SUPERVISOR,
                    recipient=AgentRole.REVIEW,
                    kind=AgentMessageKind.DELEGATION,
                    content=f"{decision.objective}；复核理由：{decision.rationale}",
                    evidence_references=decision.evidence_references,
                )
            )
        elif decision.action is SupervisorAction.HUMAN_REVIEW:
            messages.append(
                self._message(
                    state,
                    sender=AgentRole.SUPERVISOR,
                    recipient=AgentRole.REVIEW,
                    kind=AgentMessageKind.DECISION,
                    content=decision.rationale,
                    evidence_references=decision.evidence_references,
                )
            )
        return {
            "supervisor_decision": decision,
            "messages": messages,
            "delegation_count": state["delegation_count"]
            + int(decision.action is SupervisorAction.DELEGATE),
            "llm_calls": state["llm_calls"] + 1,
            **(
                {
                    "terminal_status": AgentCollaborationStatus.HUMAN_REVIEW,
                    "final_summary": decision.rationale,
                    "human_review_reason": decision.rationale,
                }
                if decision.action is SupervisorAction.HUMAN_REVIEW
                else {}
            ),
        }

    def _specialist_node(
        self,
        role: AgentRole,
    ) -> Callable[[CollaborationGraphState], dict[str, Any]]:
        def node(state: CollaborationGraphState) -> dict[str, Any]:
            if state["llm_calls"] >= self._budget.max_llm_calls:
                return self._budget_failure("LLM 调用预算已耗尽")
            agent = self._roster.get(role)
            try:
                response = agent.generate(
                    SpecialistResponse,
                    memory_scope=state["memory_scope"],
                    evidence=state["evidence"],
                    messages=state["messages"],
                )
                self._validate_output(response, state["allowed_references"])
                self._remember(agent, response.memory_update, state)
            except Exception as exc:
                return self._agent_failure(
                    role,
                    exc,
                    llm_calls=state["llm_calls"] + 1,
                )
            suggestion = (
                f"；建议后续委派 {response.suggested_next_role.value}"
                if response.suggested_next_role is not None
                else ""
            )
            content = (
                f"立场={response.stance.value}；{response.summary}；"
                + "；".join(response.findings)
                + suggestion
            )
            return {
                "messages": [
                    *state["messages"],
                    self._message(
                        state,
                        sender=role,
                        recipient=AgentRole.SUPERVISOR,
                        kind=AgentMessageKind.FINDING,
                        content=content,
                        evidence_references=response.evidence_references,
                    ),
                ],
                "llm_calls": state["llm_calls"] + 1,
            }

        return node

    def _review_node(
        self,
        state: CollaborationGraphState,
    ) -> dict[str, Any]:
        if state["llm_calls"] >= self._budget.max_llm_calls:
            return self._budget_failure("LLM 调用预算已耗尽")
        agent = self._roster.get(AgentRole.REVIEW)
        try:
            verdict = agent.generate(
                ReviewVerdict,
                memory_scope=state["memory_scope"],
                evidence=state["evidence"],
                messages=state["messages"],
            )
            self._validate_output(verdict, state["allowed_references"])
            self._remember(agent, verdict.memory_update, state)
        except Exception as exc:
            return self._agent_failure(
                AgentRole.REVIEW,
                exc,
                llm_calls=state["llm_calls"] + 1,
            )

        messages = [
            *state["messages"],
            self._message(
                state,
                sender=AgentRole.REVIEW,
                recipient=AgentRole.SUPERVISOR,
                kind=(
                    AgentMessageKind.CRITIQUE
                    if verdict.action is ReviewAction.REDELEGATE
                    else AgentMessageKind.DECISION
                ),
                content=(
                    verdict.summary
                    + "；"
                    + verdict.rationale
                    + (
                        f"；建议重新委派 {verdict.target_role.value}："
                        f"{verdict.follow_up_objective}"
                        if verdict.action is ReviewAction.REDELEGATE
                        else ""
                    )
                ),
                evidence_references=verdict.evidence_references,
            ),
        ]
        calls = state["llm_calls"] + 1
        if verdict.action is ReviewAction.ACCEPT:
            return {
                "review_verdict": verdict,
                "messages": messages,
                "llm_calls": calls,
                "terminal_status": AgentCollaborationStatus.ACCEPTED,
                "final_summary": verdict.summary,
            }
        if verdict.action is ReviewAction.HUMAN_REVIEW:
            return {
                "review_verdict": verdict,
                "messages": messages,
                "llm_calls": calls,
                "terminal_status": AgentCollaborationStatus.HUMAN_REVIEW,
                "final_summary": verdict.summary,
                "human_review_reason": verdict.rationale,
            }
        next_round = state["reflection_rounds"] + 1
        if next_round > self._budget.max_reflection_rounds:
            return {
                "review_verdict": verdict,
                "messages": messages,
                "llm_calls": calls,
                **self._budget_failure("自反思轮数预算已耗尽"),
            }
        return {
            "review_verdict": verdict,
            "messages": messages,
            "llm_calls": calls,
            "reflection_rounds": next_round,
        }

    def _route_after_supervisor(self, state: CollaborationGraphState) -> str:
        if "terminal_status" in state:
            return "finalize"
        decision = state["supervisor_decision"]
        if decision.action is SupervisorAction.REVIEW:
            return "review_agent"
        return {
            AgentRole.POI: "poi_agent",
            AgentRole.SPATIAL: "spatial_agent",
            AgentRole.POLICY: "policy_agent",
        }[decision.target_role]

    @staticmethod
    def _route_after_specialist(state: CollaborationGraphState) -> str:
        return "finalize" if "terminal_status" in state else "supervisor"

    @staticmethod
    def _route_after_review(state: CollaborationGraphState) -> str:
        return "finalize" if "terminal_status" in state else "supervisor"

    def _finalize_node(
        self,
        state: CollaborationGraphState,
    ) -> dict[str, AgentCollaborationReport]:
        status = state.get("terminal_status", AgentCollaborationStatus.FAILED)
        reason = state.get("human_review_reason")
        if status is AgentCollaborationStatus.FAILED and reason is None:
            reason = "协作图未生成有效终态"
        revisions = {}
        memory_failure = None
        for role in self._roster.agents:
            try:
                records = self._roster.get(role).memory_store.recall(
                    role,
                    memory_scope=state["memory_scope"],
                    limit=50,
                )
            except Exception as exc:
                records = []
                memory_failure = (
                    "Agent 记忆终态读取失败：" + type(exc).__name__
                )
            revisions[role] = max(
                (record.revision for record in records),
                default=0,
            )
        if memory_failure is not None:
            status = AgentCollaborationStatus.FAILED
            reason = memory_failure
        report = AgentCollaborationReport(
            request_id=state["analysis"].request.request_id,
            conversation_id=state["conversation_id"],
            status=status,
            messages=state["messages"],
            delegation_count=state["delegation_count"],
            reflection_rounds=state["reflection_rounds"],
            llm_calls=state["llm_calls"],
            final_summary=(
                reason
                if memory_failure is not None
                else state.get("final_summary", reason or "协作失败")
            ),
            human_review_reason=reason,
            role_memory_revisions=revisions,
        )
        return {"collaboration_report": report}

    def _message(
        self,
        state: CollaborationGraphState,
        *,
        sender: AgentRole,
        recipient: AgentRole | None,
        kind: AgentMessageKind,
        content: str,
        evidence_references: Sequence[str],
    ) -> AgentMessage:
        if recipient is None:
            raise AgentProtocolViolationError("Agent message recipient is required")
        return AgentMessage(
            message_id=(
                f"{state['conversation_id']}:{len(state['messages']) + 1:03d}"
            ),
            conversation_id=state["conversation_id"],
            sender=sender,
            recipient=recipient,
            kind=kind,
            round_index=state["reflection_rounds"],
            content=content,
            evidence_references=list(evidence_references),
            created_at=self._clock(),
        )

    def _remember(
        self,
        agent: RoleAgent,
        update: AgentMemoryUpdate | None,
        state: CollaborationGraphState,
    ) -> None:
        if update is None:
            return
        self._validate_references(
            update.evidence_references,
            state["allowed_references"],
        )
        agent.memory_store.upsert(
            agent.profile.role,
            update,
            memory_scope=state["memory_scope"],
            updated_at=self._clock(),
        )

    def _validate_output(
        self,
        output: BaseModel,
        allowed_references: Sequence[str],
    ) -> None:
        references = getattr(output, "evidence_references", [])
        self._validate_references(references, allowed_references)

    @staticmethod
    def _validate_references(
        references: Sequence[str],
        allowed_references: Sequence[str],
    ) -> None:
        unknown = set(references) - set(allowed_references)
        if unknown:
            raise AgentProtocolViolationError(
                "Agent 引用了未知证据：" + ", ".join(sorted(unknown))
            )

    @staticmethod
    def _agent_failure(
        role: AgentRole,
        exc: Exception,
        *,
        llm_calls: int,
    ) -> dict[str, Any]:
        reason = f"{role.value} Agent 失败：{type(exc).__name__}"
        return {
            "terminal_status": AgentCollaborationStatus.FAILED,
            "final_summary": reason,
            "human_review_reason": reason,
            "llm_calls": llm_calls,
        }

    @staticmethod
    def _budget_failure(reason: str) -> dict[str, Any]:
        return {
            "terminal_status": AgentCollaborationStatus.BUDGET_EXHAUSTED,
            "final_summary": reason,
            "human_review_reason": reason,
        }


def default_agent_profiles(
    default_model: str,
    *,
    model_overrides: Mapping[AgentRole, str] | None = None,
) -> dict[AgentRole, AgentPromptProfile]:
    """Create distinct prompts while allowing a different model per role."""

    overrides = dict(model_overrides or {})
    prompts = {
        AgentRole.SUPERVISOR: (
            "你是选址多智能体 Supervisor。根据证据缺口和既有消息动态委派 "
            "POI、Spatial、Policy Agent，信息充分后交给 Review Agent。不得臆造证据。"
        ),
        AgentRole.POI: (
            "你是 POI 证据专家。检查来源、完整度、评分组可比性和截断/降级风险，"
            "以自然语言向 Supervisor 报告并逐条引用证据。"
        ),
        AgentRole.SPATIAL: (
            "你是空间证据专家。检查 CRS、几何、用地门禁和空间指标，仅解释已提供"
            "的 GIS 证据，并指出需要人工核验的边界。"
        ),
        AgentRole.POLICY: (
            "你是政策证据专家。核对规则版本、条款引用和命中结果；未命中规则不得"
            "表述为整体合规。"
        ),
        AgentRole.REVIEW: (
            "你是独立 Critic/Review Agent。交叉检查专家意见与确定性证据；可接受、"
            "提出有证据引用的反驳并要求重新委派，或转人工复核。"
        ),
    }
    return {
        role: AgentPromptProfile(
            role=role,
            model=overrides.get(role, default_model),
            system_prompt=prompt,
        )
        for role, prompt in prompts.items()
    }


def build_agent_roster(
    *,
    models: Mapping[AgentRole, StructuredAgentModel],
    profiles: Mapping[AgentRole, AgentPromptProfile],
    memory_stores: Mapping[AgentRole, AgentMemoryStore],
) -> AgentRoster:
    """Bind independent model, prompt and memory instances to every role."""

    roles = set(profiles)
    if set(models) != roles or set(memory_stores) != roles:
        raise ValueError("models、profiles 和 memory_stores 的角色集合必须一致")
    return AgentRoster(
        agents={
            role: RoleAgent(
                profile=profiles[role],
                model=models[role],
                memory_store=memory_stores[role],
            )
            for role in roles
        }
    )


def build_collaboration_evidence(
    state: AgentState,
) -> tuple[dict[str, Any], set[str]]:
    allowed: set[str] = set()
    candidates = []
    for result in state.results:
        gis = []
        for metric, value in sorted(result.gis_evidence.metrics.items()):
            reference = f"gis:{result.parcel_id}:{metric}"
            allowed.add(reference)
            gis.append({"reference": reference, "metric": metric, "value": value})
        poi = []
        for feature_set in result.poi_evidence.feature_sets:
            reference = (
                f"poi:{result.parcel_id}:{feature_set.query.group_key}:"
                f"{feature_set.source.dataset_id}"
            )
            allowed.add(reference)
            poi.append(
                {
                    "reference": reference,
                    "group_key": feature_set.query.group_key,
                    "metrics": {
                        key.value: value
                        for key, value in feature_set.metrics.items()
                    },
                    "source": feature_set.source.model_dump(mode="json"),
                }
            )
        policy = []
        for finding in result.policy_evidence.rule_findings:
            reference = f"rule:{finding.rule_id}@{finding.rule_version}"
            allowed.add(reference)
            policy.append(
                {
                    "reference": reference,
                    "outcome": finding.outcome.value,
                    "policy_id": finding.policy_id,
                    "policy_clause": finding.policy_clause,
                    "source_uri": finding.source_uri,
                }
            )
        candidates.append(
            {
                "parcel_id": result.parcel_id,
                "soft_score": result.overall_soft_score,
                "gis_status": result.gis_evidence.status.value,
                "poi_status": result.poi_evidence.status.value,
                "policy_status": result.policy_evidence.status.value,
                "gis": gis,
                "poi": poi,
                "policy": policy,
            }
        )
    review_issues = []
    report = state.evidence_review_report
    if report is not None:
        for index, issue in enumerate(report.issues):
            reference = f"review:{index}:{issue.issue_code}"
            allowed.add(reference)
            review_issues.append(
                {
                    "reference": reference,
                    **issue.model_dump(mode="json"),
                }
            )
    return (
        {
            "request": {
                "request_id": state.request.request_id,
                "project_type": state.request.project_type.value,
                "analysis_scope": state.request.analysis_scope.value,
            },
            "candidates": candidates,
            "comparison": (
                state.comparison_report.model_dump(mode="json")
                if state.comparison_report is not None
                else None
            ),
            "review_issues": review_issues,
            "allowed_references": sorted(allowed),
            "safety_boundary": {
                "may_mutate_business_state": False,
                "may_invent_external_facts": False,
                "may_issue_compliance_approval": False,
            },
        },
        allowed,
    )


def _decode_redis(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise TypeError("Redis Agent memory must be bytes or str")
