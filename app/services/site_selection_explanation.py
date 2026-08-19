from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from practice.site_selection import AgentState


class EvidenceExplanationStatus(StrEnum):
    GENERATED = "generated"
    NOT_CONFIGURED = "not_configured"
    FAILED = "failed"


class CandidateEvidenceNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parcel_id: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    evidence_references: list[str] = Field(min_length=1)


class SiteSelectionEvidenceExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: EvidenceExplanationStatus
    summary: str | None = Field(default=None, min_length=1)
    candidate_notes: list[CandidateEvidenceNote] = Field(default_factory=list)
    error: str | None = Field(default=None, min_length=1)
    boundary_notice: str = (
        "该解释仅复述已完成证据，不改变评分、排序、规则结果，"
        "也不构成合规结论或选址推荐。"
    )

    @model_validator(mode="after")
    def fields_match_status(self) -> SiteSelectionEvidenceExplanation:
        if self.status is EvidenceExplanationStatus.GENERATED:
            if self.summary is None or not self.candidate_notes or self.error is not None:
                raise ValueError("已生成解释必须包含摘要和候选地说明")
        elif self.summary is not None or self.candidate_notes:
            raise ValueError("未生成解释不能包含模型内容")
        if self.status is EvidenceExplanationStatus.FAILED and self.error is None:
            raise ValueError("失败解释必须包含脱敏错误")
        if self.status is not EvidenceExplanationStatus.FAILED and self.error is not None:
            raise ValueError("非失败解释不能包含错误")
        return self


class SiteSelectionEvidenceExplainer(Protocol):
    def explain(self, state: AgentState) -> SiteSelectionEvidenceExplanation: ...


class _GeneratedExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    candidate_notes: list[CandidateEvidenceNote] = Field(min_length=1)


class OpenAISiteSelectionEvidenceExplainer:
    """Generate a bounded narrative after deterministic analysis is complete."""

    def __init__(self, client: Any, model: str) -> None:
        if client is None or not model.strip():
            raise ValueError("LLM 解释器必须配置客户端和模型")
        self._client = client
        self._model = model.strip()

    def explain(self, state: AgentState) -> SiteSelectionEvidenceExplanation:
        payload, allowed_references = _explanation_payload(state)
        response = self._client.responses.create(
            model=self._model,
            instructions=(
                "你是选址证据解释器。只能复述输入 JSON 中的事实，并使用其中的 "
                "evidence_reference。不得补充外部事实，不得修改评分或排序，不得给出"
                "总体合规结论、批准意见或选址推荐。只返回 JSON："
                '{"summary":"...","candidate_notes":[{"parcel_id":"...",'
                '"explanation":"...","evidence_references":["..."]}]}。'
            ),
            input=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
        raw = getattr(response, "output_text", "").strip()
        if not raw:
            raise RuntimeError("LLM returned empty explanation")
        generated = _GeneratedExplanation.model_validate_json(raw)
        _validate_generated_explanation(
            generated,
            expected_parcel_ids={result.parcel_id for result in state.results},
            allowed_references=allowed_references,
        )
        return SiteSelectionEvidenceExplanation(
            status=EvidenceExplanationStatus.GENERATED,
            summary=generated.summary,
            candidate_notes=generated.candidate_notes,
        )


def unconfigured_explanation() -> SiteSelectionEvidenceExplanation:
    return SiteSelectionEvidenceExplanation(
        status=EvidenceExplanationStatus.NOT_CONFIGURED
    )


def failed_explanation(exc: Exception) -> SiteSelectionEvidenceExplanation:
    return SiteSelectionEvidenceExplanation(
        status=EvidenceExplanationStatus.FAILED,
        error=f"LLM 证据解释不可用：{type(exc).__name__}",
    )


def _explanation_payload(state: AgentState) -> tuple[dict[str, Any], set[str]]:
    if state.status.value != "completed" or not state.results:
        raise ValueError("LLM 解释只能处理已完成且包含结果的分析")
    allowed: set[str] = set()
    candidates = []
    for result in state.results:
        gis = []
        for metric, value in sorted(result.gis_evidence.metrics.items()):
            reference = f"gis:{result.parcel_id}:{metric}"
            allowed.add(reference)
            gis.append(
                {
                    "evidence_reference": reference,
                    "metric": metric,
                    "value": value,
                }
            )
        poi = []
        for feature_set in result.poi_evidence.feature_sets:
            reference = (
                f"poi:{result.parcel_id}:{feature_set.query.group_key}:"
                f"{feature_set.source.dataset_id}"
            )
            allowed.add(reference)
            poi.append(
                {
                    "evidence_reference": reference,
                    "group_key": feature_set.query.group_key,
                    "metrics": {
                        key.value: value
                        for key, value in feature_set.metrics.items()
                    },
                    "source": feature_set.source.model_dump(mode="json"),
                }
            )
        rules = []
        for finding in result.policy_evidence.rule_findings:
            reference = f"rule:{finding.rule_id}@{finding.rule_version}"
            allowed.add(reference)
            rules.append(
                {
                    "evidence_reference": reference,
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
                "gis_evidence": gis,
                "poi_evidence": poi,
                "rule_findings": rules,
            }
        )
    comparison = (
        state.comparison_report.model_dump(mode="json")
        if state.comparison_report is not None
        else None
    )
    return {
        "project_type": state.request.project_type.value,
        "candidates": candidates,
        "comparison": comparison,
        "constraints": {
            "external_facts_forbidden": True,
            "compliance_conclusion_forbidden": True,
            "site_recommendation_forbidden": True,
        },
    }, allowed


def _validate_generated_explanation(
    generated: _GeneratedExplanation,
    *,
    expected_parcel_ids: set[str],
    allowed_references: set[str],
) -> None:
    actual_parcel_ids = {note.parcel_id for note in generated.candidate_notes}
    if actual_parcel_ids != expected_parcel_ids:
        raise ValueError("LLM 解释必须完整覆盖候选地块")
    references = {
        reference
        for note in generated.candidate_notes
        for reference in note.evidence_references
    }
    unknown = references - allowed_references
    if unknown:
        raise ValueError("LLM 解释引用了未知证据")
    forbidden = ("建议选择", "推荐地块", "总体合规", "合规通过", "批准建设")
    content = "\n".join(
        [generated.summary, *(note.explanation for note in generated.candidate_notes)]
    )
    if any(term in content for term in forbidden):
        raise ValueError("LLM 解释越过了证据说明边界")
