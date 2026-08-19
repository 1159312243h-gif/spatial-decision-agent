import json
from types import SimpleNamespace

import pytest

from app.services.site_selection_explanation import (
    EvidenceExplanationStatus,
    OpenAISiteSelectionEvidenceExplainer,
    failed_explanation,
    unconfigured_explanation,
)
from practice.site_selection import run_parallel_site_selection_workflow
from tests.test_site_selection_workflow import dependencies, manifests, request


def completed_state():
    return run_parallel_site_selection_workflow(
        request(),
        manifests(),
        dependencies(),
    )


class RecordingResponses:
    def __init__(self, output: dict) -> None:
        self.output = output
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(self.output, ensure_ascii=False)
        )


def valid_output() -> dict:
    return {
        "summary": "证据显示候选地块完成了 GIS、POI 和规则检查。",
        "candidate_notes": [
            {
                "parcel_id": "A01",
                "explanation": "记录面积指标和公共交通 POI 来源。",
                "evidence_references": [
                    "gis:A01:area_hectares",
                    "poi:A01:public_transit:poi-mock",
                ],
            }
        ],
    }


def test_explainer_sends_only_structured_evidence_and_validates_references() -> None:
    responses = RecordingResponses(valid_output())
    explainer = OpenAISiteSelectionEvidenceExplainer(
        SimpleNamespace(responses=responses),
        "fixture-model",
    )

    result = explainer.explain(completed_state())

    assert result.status is EvidenceExplanationStatus.GENERATED
    assert result.candidate_notes[0].parcel_id == "A01"
    assert "不得修改评分" in responses.calls[0]["instructions"]
    payload = json.loads(responses.calls[0]["input"])
    assert payload["constraints"]["site_recommendation_forbidden"] is True


def test_explainer_rejects_unknown_reference_or_recommendation() -> None:
    unknown = valid_output()
    unknown["candidate_notes"][0]["evidence_references"] = ["made-up"]
    explainer = OpenAISiteSelectionEvidenceExplainer(
        SimpleNamespace(responses=RecordingResponses(unknown)),
        "fixture-model",
    )
    with pytest.raises(ValueError, match="未知证据"):
        explainer.explain(completed_state())

    recommendation = valid_output()
    recommendation["summary"] = "建议选择 A01"
    explainer = OpenAISiteSelectionEvidenceExplainer(
        SimpleNamespace(responses=RecordingResponses(recommendation)),
        "fixture-model",
    )
    with pytest.raises(ValueError, match="边界"):
        explainer.explain(completed_state())


def test_unavailable_states_are_explicit_and_sanitized() -> None:
    assert unconfigured_explanation().status is EvidenceExplanationStatus.NOT_CONFIGURED
    failed = failed_explanation(RuntimeError("secret-token"))
    assert failed.status is EvidenceExplanationStatus.FAILED
    assert failed.error == "LLM 证据解释不可用：RuntimeError"
    assert "secret" not in failed.model_dump_json()
