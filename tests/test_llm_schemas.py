import json

import pytest
from pydantic import ValidationError

from practice.llm_api.schemas import SiteSelectionRequirement


VALID_REQUIREMENT = {
    "project_type": "logistics_park",
    "land_area_hectares": 30,
    "candidate_sites": ["A01", "B01"],
    "review_items": ["交通条件", "生态保护红线"],
}


def error_types(error: ValidationError) -> set[str]:
    return {item["type"] for item in error.errors()}


def test_valid_json_is_parsed() -> None:
    requirement = SiteSelectionRequirement.model_validate_json(
        json.dumps(VALID_REQUIREMENT, ensure_ascii=False)
    )

    assert requirement.project_type == "logistics_park"
    assert requirement.land_area_hectares == 30
    assert requirement.candidate_sites == ["A01", "B01"]
    assert requirement.review_items == ["交通条件", "生态保护红线"]


def test_invalid_json_is_rejected() -> None:
    invalid_json = '{"project_type":"logistics_park",}'

    with pytest.raises(ValidationError) as exc_info:
        SiteSelectionRequirement.model_validate_json(invalid_json)

    assert "json_invalid" in error_types(exc_info.value)


def test_missing_required_field_is_rejected() -> None:
    data = VALID_REQUIREMENT.copy()
    data.pop("candidate_sites")

    with pytest.raises(ValidationError) as exc_info:
        SiteSelectionRequirement.model_validate(data)

    assert any(
        item["type"] == "missing" and item["loc"] == ("candidate_sites",)
        for item in exc_info.value.errors()
    )


def test_wrong_field_type_is_rejected() -> None:
    data = VALID_REQUIREMENT | {"candidate_sites": "A01"}

    with pytest.raises(ValidationError) as exc_info:
        SiteSelectionRequirement.model_validate(data)

    assert "list_type" in error_types(exc_info.value)


def test_extra_field_is_rejected() -> None:
    data = VALID_REQUIREMENT | {"final_decision": "approved"}

    with pytest.raises(ValidationError) as exc_info:
        SiteSelectionRequirement.model_validate(data)

    assert "extra_forbidden" in error_types(exc_info.value)
