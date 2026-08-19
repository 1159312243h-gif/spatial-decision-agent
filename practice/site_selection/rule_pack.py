from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import NonEmptyString, ProjectType
from .rules import RuleDefinition


class RulePack(BaseModel):
    """Versioned and auditable collection of deterministic policy rules."""

    model_config = ConfigDict(extra="forbid")

    pack_id: NonEmptyString
    version: NonEmptyString
    is_fixture: bool = False
    applicable_project_types: list[ProjectType] = Field(min_length=1)
    rules: list[RuleDefinition] = Field(min_length=1)

    @field_validator("applicable_project_types")
    @classmethod
    def project_types_are_unique(
        cls,
        values: list[ProjectType],
    ) -> list[ProjectType]:
        if len(values) != len(set(values)):
            raise ValueError("RulePack 适用项目类型不能重复")
        return values

    @model_validator(mode="after")
    def rules_are_consistent(self) -> RulePack:
        identities = [(rule.rule_id, rule.version) for rule in self.rules]
        if len(identities) != len(set(identities)):
            raise ValueError("RulePack 不能包含重复规则版本")
        allowed = set(self.applicable_project_types)
        outside = sorted(
            {
                project_type.value
                for rule in self.rules
                for project_type in rule.applicable_project_types
                if project_type not in allowed
            }
        )
        if outside:
            raise ValueError(
                "RulePack 规则包含未声明的项目类型：" + ", ".join(outside)
            )
        if self.is_fixture and any(
            not rule.policy.source_uri.startswith("fixture://")
            for rule in self.rules
        ):
            raise ValueError("Fixture RulePack 必须使用 fixture:// 政策来源")
        return self


def load_rule_pack(path: str | Path) -> RulePack:
    source = Path(path)
    suffix = source.suffix.lower()
    text = source.read_text(encoding="utf-8")
    if suffix == ".json":
        payload = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        raise ValueError("RulePack 仅支持 .json、.yaml 或 .yml")
    if not isinstance(payload, dict):
        raise ValueError("RulePack 文件顶层必须是对象")
    return RulePack.model_validate(payload)


def dump_rule_pack_json(rule_pack: RulePack) -> str:
    payload: dict[str, Any] = rule_pack.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
