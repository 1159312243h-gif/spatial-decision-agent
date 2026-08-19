from pathlib import Path

import pytest
from pydantic import ValidationError

from practice.site_selection import ProjectType
from practice.site_selection.rule_pack import (
    RulePack,
    dump_rule_pack_json,
    load_rule_pack,
)


FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "data"
    / "fixtures"
    / "rules.shopping_mall.yaml"
)


def test_yaml_rule_pack_loads_with_policy_lineage() -> None:
    rule_pack = load_rule_pack(FIXTURE_PATH)

    assert rule_pack.is_fixture is True
    assert rule_pack.applicable_project_types == [ProjectType.SHOPPING_MALL]
    assert rule_pack.rules[0].rule_id == "FIXTURE-RULE-ECOLOGY-001"
    assert rule_pack.rules[0].policy.source_uri.startswith("fixture://")


def test_rule_pack_json_round_trip_is_stable(tmp_path: Path) -> None:
    rule_pack = load_rule_pack(FIXTURE_PATH)
    json_path = tmp_path / "rules.json"
    json_path.write_text(dump_rule_pack_json(rule_pack), encoding="utf-8")

    reloaded = load_rule_pack(json_path)

    assert reloaded == rule_pack


def test_rule_pack_rejects_project_type_outside_pack() -> None:
    payload = load_rule_pack(FIXTURE_PATH).model_dump()
    payload["rules"][0]["applicable_project_types"] = ["logistics_park"]

    with pytest.raises(ValidationError, match="未声明"):
        RulePack.model_validate(payload)


def test_fixture_rule_pack_requires_fixture_policy_uri() -> None:
    payload = load_rule_pack(FIXTURE_PATH).model_dump()
    payload["rules"][0]["policy"]["source_uri"] = "https://example.com/policy"

    with pytest.raises(ValidationError, match="fixture://"):
        RulePack.model_validate(payload)


def test_rule_pack_rejects_unknown_file_type(tmp_path: Path) -> None:
    path = tmp_path / "rules.txt"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="仅支持"):
        load_rule_pack(path)
