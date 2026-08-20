from __future__ import annotations

from collections.abc import Sequence
from pydantic import BaseModel, ConfigDict, model_validator

from .agent_orchestration import AgentRole
from .comparison import compare_candidate_results
from .constraints import ConstraintLayerSpec
from .evidence import AgentState, AnalysisStatus, EvidenceStatus
from .evidence_review import review_site_selection_evidence
from .preflight import (
    PreflightDecision,
    SiteSelectionDraft,
    evaluate_site_selection_draft,
)
from .results import assemble_analysis_results
from .rule_engine import evaluate_policy_rules
from .rules import RuleDefinition
from .spatial.analysis import run_gis_analysis
from .spatial.constraint_analysis import run_spatial_constraint_analysis
from .spatial.gateway import SpatialDatasetGateway, collect_gis_evidence


class SpatialAgentBlockedError(RuntimeError):
    """Raised when mandatory GIS evidence is not ready for analysis."""


class OrchestratorAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: SiteSelectionDraft


class OrchestratorAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole = AgentRole.ORCHESTRATOR
    decision: PreflightDecision

    @model_validator(mode="after")
    def role_is_orchestrator(self) -> OrchestratorAgentOutput:
        if self.role is not AgentRole.ORCHESTRATOR:
            raise ValueError("Orchestrator 输出角色不一致")
        return self


class SpatialAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: AgentState


class SpatialAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole = AgentRole.SPATIAL
    state: AgentState

    @model_validator(mode="after")
    def gis_evidence_is_ready(self) -> SpatialAgentOutput:
        parcel_ids = {
            parcel.parcel_id for parcel in self.state.request.candidate_parcels
        }
        evidence_ids = {
            evidence.parcel_id
            for evidence in self.state.gis_evidence
            if evidence.status is EvidenceStatus.READY
        }
        if self.role is not AgentRole.SPATIAL or evidence_ids != parcel_ids:
            raise ValueError("SpatialAgent 输出必须覆盖全部 READY GIS 证据")
        return self


class PolicyAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: AgentState


class PolicyAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole = AgentRole.POLICY
    state: AgentState

    @model_validator(mode="after")
    def policy_evidence_is_ready(self) -> PolicyAgentOutput:
        parcel_ids = {
            parcel.parcel_id for parcel in self.state.request.candidate_parcels
        }
        evidence_ids = {
            evidence.parcel_id
            for evidence in self.state.policy_evidence
            if evidence.status is EvidenceStatus.READY
        }
        if self.role is not AgentRole.POLICY or evidence_ids != parcel_ids:
            raise ValueError("PolicyAgent 输出必须覆盖全部 READY 政策证据")
        return self


class ReviewAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: AgentState


class ReviewAgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole = AgentRole.REVIEW
    state: AgentState

    @model_validator(mode="after")
    def completed_output_is_consistent(self) -> ReviewAgentOutput:
        candidate_count = len(self.state.request.candidate_parcels)
        if self.role is not AgentRole.REVIEW:
            raise ValueError("ReviewAgent 输出角色不一致")
        if self.state.status is not AnalysisStatus.COMPLETED:
            raise ValueError("ReviewAgent 输出必须为 completed")
        if len(self.state.results) != candidate_count:
            raise ValueError("ReviewAgent 输出必须覆盖全部地块结果")
        if self.state.comparison_report is None:
            raise ValueError("ReviewAgent 输出必须包含候选地块对比报告")
        if self.state.evidence_review_report is None:
            raise ValueError("ReviewAgent 输出必须包含证据审查报告")
        return self


class OrchestratorAgent:
    """Routes incomplete input without invoking an LLM or guessing fields."""

    def run(self, agent_input: OrchestratorAgentInput) -> OrchestratorAgentOutput:
        return OrchestratorAgentOutput(
            decision=evaluate_site_selection_draft(agent_input.draft)
        )


class SpatialAgent:
    """Runs the deterministic GIS collection and analysis pipeline."""

    def __init__(
        self,
        gateway: SpatialDatasetGateway,
        constraint_specs: Sequence[ConstraintLayerSpec],
        *,
        buffer_distance_m: float = 500,
    ) -> None:
        specs = tuple(constraint_specs)
        if gateway is None:
            raise ValueError("SpatialAgent 必须配置空间数据网关")
        if not specs:
            raise ValueError("SpatialAgent 至少需要一个空间约束配置")
        if buffer_distance_m <= 0:
            raise ValueError("SpatialAgent 缓冲距离必须大于 0")
        self._gateway = gateway
        self._constraint_specs = specs
        self._buffer_distance_m = buffer_distance_m

    def run(self, agent_input: SpatialAgentInput) -> SpatialAgentOutput:
        state = collect_gis_evidence(agent_input.state, self._gateway)
        issues = [
            (
                f"{item.parcel_id}: status={item.status.value}, "
                f"notes={'; '.join(item.notes) or 'none'}"
            )
            for item in state.gis_evidence
            if item.status is not EvidenceStatus.READY
        ]
        if issues:
            raise SpatialAgentBlockedError(
                "GIS 强制证据未就绪：" + " | ".join(issues)
            )
        state = run_gis_analysis(
            state,
            self._gateway,
            buffer_distance_m=self._buffer_distance_m,
        )
        state = run_spatial_constraint_analysis(
            state,
            self._gateway,
            self._constraint_specs,
        )
        return SpatialAgentOutput(state=state)


class PolicyAgent:
    """Maps spatial observations to versioned deterministic policy evidence."""

    def __init__(self, rules: Sequence[RuleDefinition]) -> None:
        rules = tuple(rules)
        if not rules:
            raise ValueError("PolicyAgent 至少需要一条版本化规则")
        self._rules = rules

    def run(self, agent_input: PolicyAgentInput) -> PolicyAgentOutput:
        return PolicyAgentOutput(
            state=evaluate_policy_rules(agent_input.state, self._rules)
        )


class ReviewAgent:
    """Assembles parcel results and produces the auditable comparison report."""

    def run(self, agent_input: ReviewAgentInput) -> ReviewAgentOutput:
        state = assemble_analysis_results(agent_input.state)
        state = compare_candidate_results(state)
        state = review_site_selection_evidence(state)
        return ReviewAgentOutput(state=state)
