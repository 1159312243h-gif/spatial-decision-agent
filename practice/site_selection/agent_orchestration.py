from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import NonEmptyString


class AgentRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    POI = "poi"
    SPATIAL = "spatial"
    POLICY = "policy"
    REVIEW = "review"


class AgentStepStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentSkillManifest(BaseModel):
    """Reviewed contract for one node in the business-agent DAG."""

    model_config = ConfigDict(extra="forbid")

    node_id: NonEmptyString
    role: AgentRole
    skill_name: NonEmptyString
    skill_version: NonEmptyString
    depends_on: list[NonEmptyString] = Field(default_factory=list)
    parallel_group: NonEmptyString | None = None
    critical: bool = True
    llm_allowed: bool = False
    output_contract: NonEmptyString

    @model_validator(mode="after")
    def dependencies_are_valid(self) -> AgentSkillManifest:
        if self.node_id in self.depends_on:
            raise ValueError("Agent 节点不能依赖自身")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("Agent 节点依赖不能重复")
        return self


class AgentExecutionPlan(BaseModel):
    """Versioned, acyclic and fully whitelisted execution plan."""

    model_config = ConfigDict(extra="forbid")

    plan_id: NonEmptyString
    version: NonEmptyString
    steps: list[AgentSkillManifest] = Field(min_length=1)

    @model_validator(mode="after")
    def plan_is_acyclic_and_closed(self) -> AgentExecutionPlan:
        node_ids = [step.node_id for step in self.steps]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Agent 执行计划不能包含重复节点")
        known = set(node_ids)
        missing = {
            dependency
            for step in self.steps
            for dependency in step.depends_on
            if dependency not in known
        }
        if missing:
            raise ValueError(
                "Agent 执行计划引用未知依赖：" + ", ".join(sorted(missing))
            )

        dependencies = {
            step.node_id: set(step.depends_on) for step in self.steps
        }
        ready = [node_id for node_id, deps in dependencies.items() if not deps]
        visited: set[str] = set()
        while ready:
            node_id = ready.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            for candidate, deps in dependencies.items():
                if candidate not in visited and deps.issubset(visited):
                    ready.append(candidate)
        if visited != known:
            raise ValueError("Agent 执行计划存在循环依赖")
        return self

    def step(self, node_id: str) -> AgentSkillManifest:
        for step in self.steps:
            if step.node_id == node_id:
                return step.model_copy(deep=True)
        raise KeyError(f"Agent 执行计划不存在节点：{node_id}")


class AgentStepTrace(BaseModel):
    """Sanitized result for one planned Agent/Skill execution."""

    model_config = ConfigDict(extra="forbid")

    node_id: NonEmptyString
    role: AgentRole
    skill_name: NonEmptyString
    skill_version: NonEmptyString
    depends_on: list[NonEmptyString] = Field(default_factory=list)
    parallel_group: NonEmptyString | None = None
    critical: bool = True
    status: AgentStepStatus
    elapsed_ms: float = Field(ge=0)
    error_type: NonEmptyString | None = None

    @model_validator(mode="after")
    def failure_contains_only_sanitized_type(self) -> AgentStepTrace:
        if (self.status is AgentStepStatus.FAILED) != (
            self.error_type is not None
        ):
            raise ValueError("failed Agent trace 必须且只能包含错误类型")
        return self


def build_site_selection_execution_plan() -> AgentExecutionPlan:
    """Return the reviewed DAG used by the production parallel workflow."""

    return AgentExecutionPlan(
        plan_id="site-selection-agent-dag",
        version="2026.08-agent-v1",
        steps=[
            AgentSkillManifest(
                node_id="intake",
                role=AgentRole.ORCHESTRATOR,
                skill_name="ProjectIntakeSkill",
                skill_version="v1",
                output_contract="AgentState[data_pending]",
            ),
            AgentSkillManifest(
                node_id="poi_evidence",
                role=AgentRole.POI,
                skill_name="POIEvidenceSkill",
                skill_version="v1",
                depends_on=["intake"],
                parallel_group="evidence_collection",
                output_contract="POIEvidence[]",
            ),
            AgentSkillManifest(
                node_id="spatial_evidence",
                role=AgentRole.SPATIAL,
                skill_name="SpatialComplianceSkill",
                skill_version="v1",
                depends_on=["intake"],
                parallel_group="evidence_collection",
                output_contract="GISEvidence[]",
            ),
            AgentSkillManifest(
                node_id="policy_rules",
                role=AgentRole.POLICY,
                skill_name="PolicyRuleSkill",
                skill_version="v1",
                depends_on=["spatial_evidence"],
                output_contract="PolicyEvidence[]",
            ),
            AgentSkillManifest(
                node_id="merge_gate",
                role=AgentRole.ORCHESTRATOR,
                skill_name="EvidenceMergeGate",
                skill_version="v1",
                depends_on=["poi_evidence", "policy_rules"],
                output_contract="AgentState[analyzing]",
            ),
            AgentSkillManifest(
                node_id="review",
                role=AgentRole.REVIEW,
                skill_name="EvidenceReviewSkill",
                skill_version="v1",
                depends_on=["merge_gate"],
                output_contract="AgentState[completed]",
            ),
        ],
    )


def trace_for(
    manifest: AgentSkillManifest,
    status: AgentStepStatus,
    elapsed_ms: float,
    *,
    error_type: str | None = None,
) -> AgentStepTrace:
    return AgentStepTrace(
        node_id=manifest.node_id,
        role=manifest.role,
        skill_name=manifest.skill_name,
        skill_version=manifest.skill_version,
        depends_on=manifest.depends_on,
        parallel_group=manifest.parallel_group,
        critical=manifest.critical,
        status=status,
        elapsed_ms=elapsed_ms,
        error_type=error_type,
    )


def order_agent_traces(
    plan: AgentExecutionPlan,
    traces: list[AgentStepTrace],
) -> list[AgentStepTrace]:
    by_node: dict[str, AgentStepTrace] = {}
    for trace in traces:
        if trace.node_id in by_node:
            raise ValueError(f"Agent trace 节点重复：{trace.node_id}")
        manifest = plan.step(trace.node_id)
        expected = (
            manifest.role,
            manifest.skill_name,
            manifest.skill_version,
            manifest.depends_on,
            manifest.parallel_group,
            manifest.critical,
        )
        actual = (
            trace.role,
            trace.skill_name,
            trace.skill_version,
            trace.depends_on,
            trace.parallel_group,
            trace.critical,
        )
        if actual != expected:
            raise ValueError(f"Agent trace 与 manifest 不一致：{trace.node_id}")
        by_node[trace.node_id] = trace
    return [by_node[step.node_id] for step in plan.steps if step.node_id in by_node]
