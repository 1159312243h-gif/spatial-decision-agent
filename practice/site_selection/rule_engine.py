from __future__ import annotations

from collections.abc import Iterable

from .constraints import ConstraintObservation
from .evidence import AgentState, EvidenceStatus, GISEvidence, PolicyEvidence
from .rules import PolicyFinding, RuleDefinition


class RuleConfigurationError(ValueError):
    """Raised when active rule versions are ambiguous."""


class RuleEvaluationBlockedError(RuntimeError):
    """Raised when deterministic policy evaluation is not safe to run."""


def evaluate_policy_rules(
    state: AgentState,
    rules: Iterable[RuleDefinition],
) -> AgentState:
    """Map validated spatial observations to versioned policy evidence."""

    request_date = state.request.requested_at.date()
    active_rules = [
        rule
        for rule in rules
        if rule.enabled
        and state.request.project_type in rule.applicable_project_types
        and rule.is_effective_on(request_date)
    ]
    if not active_rules:
        raise RuleEvaluationBlockedError(
            "没有适用于当前项目类型和请求日期的有效规则"
        )
    _validate_active_rules(active_rules)

    evidence_by_parcel = _index_gis_evidence(state.gis_evidence)
    updated_policy_evidence = [
        _evaluate_parcel(
            parcel_id=parcel.parcel_id,
            evidence=evidence_by_parcel.get(parcel.parcel_id),
            rules=active_rules,
        )
        for parcel in state.request.candidate_parcels
    ]

    state_data = state.model_dump()
    state_data["policy_evidence"] = updated_policy_evidence
    return AgentState.model_validate(state_data)


def _validate_active_rules(rules: list[RuleDefinition]) -> None:
    versions_by_rule_id: dict[str, list[str]] = {}
    for rule in rules:
        versions_by_rule_id.setdefault(rule.rule_id, []).append(rule.version)

    ambiguous = {
        rule_id: versions
        for rule_id, versions in versions_by_rule_id.items()
        if len(versions) > 1
    }
    if ambiguous:
        details = ", ".join(
            f"{rule_id}={sorted(versions)}"
            for rule_id, versions in sorted(ambiguous.items())
        )
        raise RuleConfigurationError(
            f"同一 rule_id 同时存在多个有效版本：{details}"
        )


def _index_gis_evidence(
    evidence_items: list[GISEvidence],
) -> dict[str, GISEvidence]:
    indexed: dict[str, GISEvidence] = {}
    for evidence in evidence_items:
        if evidence.parcel_id in indexed:
            raise RuleEvaluationBlockedError(
                f"候选地块存在重复 GIS 证据：{evidence.parcel_id}"
            )
        indexed[evidence.parcel_id] = evidence
    return indexed


def _evaluate_parcel(
    *,
    parcel_id: str,
    evidence: GISEvidence | None,
    rules: list[RuleDefinition],
) -> PolicyEvidence:
    if evidence is None or evidence.status is not EvidenceStatus.READY:
        status = "missing" if evidence is None else evidence.status.value
        raise RuleEvaluationBlockedError(
            f"地块 GIS 证据未就绪：{parcel_id}, status={status}"
        )

    observations = _index_observations(
        parcel_id,
        evidence.constraint_observations,
    )
    missing_constraint_ids = sorted(
        {
            rule.constraint_id
            for rule in rules
            if rule.constraint_id not in observations
        }
    )
    if missing_constraint_ids:
        joined = ", ".join(missing_constraint_ids)
        raise RuleEvaluationBlockedError(
            f"地块缺少规则所需空间观察：{parcel_id}, constraints={joined}"
        )

    findings = [
        _build_finding(parcel_id, rule, observations[rule.constraint_id])
        for rule in rules
        if observations[rule.constraint_id].triggered
        == rule.expected_triggered
    ]
    evaluated_rule_ids = [
        f"{rule.rule_id}@{rule.version}"
        for rule in rules
    ]
    policy_ids = list(dict.fromkeys(rule.policy.policy_id for rule in rules))
    notes = []
    if not findings:
        notes.append("适用规则已完成评估；未命中规则不等于整体合规")

    return PolicyEvidence(
        parcel_id=parcel_id,
        status=EvidenceStatus.READY,
        policy_ids=policy_ids,
        evaluated_rule_ids=evaluated_rule_ids,
        findings=[finding.message for finding in findings],
        rule_findings=findings,
        notes=notes,
    )


def _index_observations(
    parcel_id: str,
    observations: list[ConstraintObservation],
) -> dict[str, ConstraintObservation]:
    indexed: dict[str, ConstraintObservation] = {}
    for observation in observations:
        if observation.constraint_id in indexed:
            raise RuleEvaluationBlockedError(
                "地块存在重复空间约束观察："
                f"{parcel_id}, constraint={observation.constraint_id}"
            )
        indexed[observation.constraint_id] = observation
    return indexed


def _build_finding(
    parcel_id: str,
    rule: RuleDefinition,
    observation: ConstraintObservation,
) -> PolicyFinding:
    policy = rule.policy
    return PolicyFinding(
        parcel_id=parcel_id,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        constraint_id=rule.constraint_id,
        observed_triggered=observation.triggered,
        expected_triggered=rule.expected_triggered,
        outcome=rule.outcome,
        message=rule.message,
        policy_id=policy.policy_id,
        policy_title=policy.title,
        policy_version=policy.version,
        policy_clause=policy.clause,
        issuing_authority=policy.issuing_authority,
        jurisdiction=policy.jurisdiction,
        source_uri=policy.source_uri,
        observation_dataset_id=observation.dataset_id,
        observation_dataset_version=observation.dataset_version,
        observation_analysis_crs=observation.analysis_crs,
    )
