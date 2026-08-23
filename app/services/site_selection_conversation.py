from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from practice.site_selection.candidate_discovery import (
    CandidateDiscoveryFallbackMode,
    RETAIL_PROJECT_TYPES,
)
from practice.site_selection.domain import ProjectType
from practice.site_selection.scenario import (
    ConstraintConflict,
    ConstraintDataReadiness,
    ConstraintReadiness,
    ConversationMessage,
    ConversationMessageRole,
    ConversationTurnStatus,
    RegionResolver,
    ScenarioConstraintAction,
    ScenarioConstraint,
    ScenarioConstraintKey,
    ScenarioConstraintOperation,
    ScenarioConversationReply,
    ScenarioConversationSession,
    ScenarioInterpreter,
    ScenarioSessionStore,
    ScenarioVersion,
    ScenarioVersionStatus,
)


class ScenarioConversationNotFoundError(LookupError):
    pass


class ScenarioVersionConflictError(RuntimeError):
    pass


class ScenarioConfirmationBlockedError(RuntimeError):
    pass


class SiteSelectionConversationService:
    def __init__(
        self,
        store: ScenarioSessionStore,
        interpreter: ScenarioInterpreter,
        region_resolver: RegionResolver,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._interpreter = interpreter
        self._region_resolver = region_resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: str(uuid4()))

    def converse(
        self,
        message: str,
        *,
        session_id: str | None = None,
        project_type: ProjectType | None = None,
    ) -> ScenarioConversationReply:
        now = self._clock()
        session = (
            self.get_session(session_id)
            if session_id is not None
            else ScenarioConversationSession(
                session_id=f"conversation-{self._id_factory()}",
                scenario_id=f"scenario-{self._id_factory()}",
                created_at=now,
                updated_at=now,
            )
        )
        base = session.pending_version or session.active_version
        interpretation = self._interpreter.interpret(message, base)
        actions = list(interpretation.actions)
        if project_type is not None and not any(
            action.key is ScenarioConstraintKey.PROJECT_TYPE for action in actions
        ):
            actions.insert(
                0,
                ScenarioConstraintAction(
                    operation=(
                        ScenarioConstraintOperation.REPLACE
                        if base is not None and base.project_type is not None
                        else ScenarioConstraintOperation.ADD
                    ),
                    key=ScenarioConstraintKey.PROJECT_TYPE,
                    value=project_type.value,
                    source_text="structured_project_type",
                ),
            )
        version = self._build_version(session, base, actions, now)
        answer = _proposal_answer(version, interpretation.warnings)
        messages = [
            *session.messages,
            ConversationMessage(
                message_id=f"message-{self._id_factory()}",
                role=ConversationMessageRole.USER,
                content=message,
                created_at=now,
            ),
            ConversationMessage(
                message_id=f"message-{self._id_factory()}",
                role=ConversationMessageRole.AGENT,
                content=answer,
                created_at=now,
            ),
        ]
        prior_versions = [
            version.model_copy(
                update={"status": ScenarioVersionStatus.SUPERSEDED}
            )
            if version.version_id == session.pending_version_id
            else version
            for version in session.versions
        ]
        updated = session.model_copy(
            update={
                "updated_at": now,
                "messages": messages,
                "versions": [*prior_versions, version],
                "pending_version_id": version.version_id,
            }
        )
        self._store.save_scenario_session(updated)
        turn_status = (
            ConversationTurnStatus.AWAITING_CONFIRMATION
            if version.ready_for_confirmation
            else ConversationTurnStatus.NEEDS_CLARIFICATION
        )
        return ScenarioConversationReply(
            session_id=updated.session_id,
            status=turn_status,
            answer=answer,
            interpretation_source=interpretation.source,
            scenario_version=version,
            discovery_request=version.to_discovery_request(),
            messages=updated.messages,
            session_ttl_seconds=_normalized_ttl(
                self._store.scenario_session_ttl(updated.session_id)
            ),
        )

    def confirm(
        self,
        session_id: str,
        version_id: str,
        *,
        confirmed_by: str,
    ) -> ScenarioConversationReply:
        session = self.get_session(session_id)
        pending = session.pending_version
        if pending is None or pending.version_id != version_id:
            raise ScenarioVersionConflictError("待确认场景版本已变化，请读取最新版本")
        if not pending.ready_for_confirmation:
            raise ScenarioConfirmationBlockedError(
                "场景仍有冲突或待澄清字段，不能确认"
            )
        now = self._clock()
        versions = []
        for version in session.versions:
            if version.version_id == pending.version_id:
                versions.append(
                    version.model_copy(
                        update={
                            "status": ScenarioVersionStatus.CONFIRMED,
                            "confirmed_at": now,
                            "confirmed_by": confirmed_by,
                        }
                    )
                )
            elif version.version_id == session.active_version_id:
                versions.append(
                    version.model_copy(
                        update={"status": ScenarioVersionStatus.SUPERSEDED}
                    )
                )
            else:
                versions.append(version)
        confirmed = next(
            version for version in versions if version.version_id == version_id
        )
        answer = _confirmation_answer(confirmed)
        messages = [
            *session.messages,
            ConversationMessage(
                message_id=f"message-{self._id_factory()}",
                role=ConversationMessageRole.AGENT,
                content=answer,
                created_at=now,
            ),
        ]
        updated = session.model_copy(
            update={
                "updated_at": now,
                "messages": messages,
                "versions": versions,
                "active_version_id": version_id,
                "pending_version_id": None,
            }
        )
        self._store.save_scenario_session(updated)
        return ScenarioConversationReply(
            session_id=session_id,
            status=ConversationTurnStatus.CONFIRMED,
            answer=answer,
            interpretation_source="confirmation",
            scenario_version=confirmed,
            discovery_request=confirmed.to_discovery_request(),
            messages=updated.messages,
            session_ttl_seconds=_normalized_ttl(
                self._store.scenario_session_ttl(session_id)
            ),
        )

    def get_session(self, session_id: str) -> ScenarioConversationSession:
        session = self._store.get_scenario_session(session_id)
        if session is None:
            raise ScenarioConversationNotFoundError(
                "对话会话不存在或已过期"
            )
        return session

    def _build_version(
        self,
        session: ScenarioConversationSession,
        base: ScenarioVersion | None,
        actions: list[ScenarioConstraintAction],
        now: datetime,
    ) -> ScenarioVersion:
        defaults: dict[str, Any] = {
            "project_type": None,
            "region_text": None,
            "discovery_radius_km": 4.0,
            "max_candidates": 8,
            "minimum_separation_m": 600,
            "fallback_mode": CandidateDiscoveryFallbackMode.MARKET_EXPLORATION,
        }
        values: dict[str, Any] = {
            "project_type": base.project_type if base else None,
            "region_text": base.region_text if base else None,
            "discovery_radius_km": base.discovery_radius_km if base else 4.0,
            "max_candidates": base.max_candidates if base else 8,
            "minimum_separation_m": base.minimum_separation_m if base else 600,
            "fallback_mode": (
                base.fallback_mode
                if base
                else CandidateDiscoveryFallbackMode.MARKET_EXPLORATION
            ),
        }
        conflicts = _duplicate_action_conflicts(actions)
        recorded = {
            item.key: item for item in (base.recorded_constraints if base else [])
        }
        for action in actions:
            if action.operation is ScenarioConstraintOperation.REMOVE:
                recorded.pop(action.key, None)
                field_name = {
                    ScenarioConstraintKey.REGION: "region_text",
                    ScenarioConstraintKey.PROJECT_TYPE: "project_type",
                }.get(action.key, action.key.value)
                if field_name in values:
                    values[field_name] = defaults[field_name]
                continue
            if action.key in {
                ScenarioConstraintKey.MAX_RENT,
                ScenarioConstraintKey.MIN_FOOTFALL,
                ScenarioConstraintKey.COMPETITOR_DISTANCE_M,
            }:
                recorded[action.key] = ScenarioConstraint(
                        key=action.key,
                        value=action.value,
                        readiness=ConstraintReadiness.MISSING_DATA,
                        reason=(
                            "当前运行时没有经过审核的租金、真实客流或经营级竞品距离数据；"
                            "该约束已记录，但不会参与候选过滤或评分。"
                        ),
                    )
                continue
            field_name = {
                ScenarioConstraintKey.REGION: "region_text",
                ScenarioConstraintKey.PROJECT_TYPE: "project_type",
            }.get(action.key, action.key.value)
            values[field_name] = action.value
            recorded[action.key] = ScenarioConstraint(
                    key=action.key,
                    value=action.value,
                    readiness=ConstraintReadiness.EXECUTABLE,
                    reason="该约束有确定性字段和执行消费者。",
                )
        validation_conflicts: list[ConstraintConflict] = []
        project_type = _validate_project_type(values["project_type"], validation_conflicts)
        radius = _validate_number(
            ScenarioConstraintKey.DISCOVERY_RADIUS_KM,
            values["discovery_radius_km"],
            0.01,
            7,
            validation_conflicts,
            float,
        )
        max_candidates = _validate_number(
            ScenarioConstraintKey.MAX_CANDIDATES,
            values["max_candidates"],
            3,
            20,
            validation_conflicts,
            int,
        )
        separation = _validate_number(
            ScenarioConstraintKey.MINIMUM_SEPARATION_M,
            values["minimum_separation_m"],
            100,
            5_000,
            validation_conflicts,
            int,
        )
        fallback_mode = _validate_fallback(
            values["fallback_mode"], validation_conflicts
        )
        region_text = str(values["region_text"] or "").strip() or None
        resolution = None
        if region_text is not None and radius is not None:
            resolution = self._region_resolver.resolve(
                region_text,
                radius_km=radius,
            )
            if resolution is None:
                validation_conflicts.append(
                    ConstraintConflict(
                        key=ScenarioConstraintKey.REGION,
                        message=(
                            f"无法解析区域“{region_text}”。请补充城市和区县，"
                            "或配置在线区域解析 Provider。"
                        ),
                    )
                )
        clarifications = []
        if project_type is None:
            clarifications.append("请说明项目类型：咖啡店、便利店、商场或物流园。")
        if project_type in RETAIL_PROJECT_TYPES and region_text is None:
            clarifications.append("门店候选发现需要一个区域名称，例如“上海市徐汇区”。")
        return ScenarioVersion(
            scenario_id=session.scenario_id,
            version_id=f"scenario-version-{self._id_factory()}",
            version_number=len(session.versions) + 1,
            parent_version_id=base.version_id if base else None,
            status=ScenarioVersionStatus.PROPOSED,
            created_at=now,
            project_type=project_type,
            region_text=region_text,
            region_resolution=resolution,
            discovery_radius_km=radius or 4.0,
            max_candidates=max_candidates or 8,
            minimum_separation_m=separation or 600,
            fallback_mode=fallback_mode,
            actions=actions,
            recorded_constraints=list(recorded.values()),
            data_readiness=[
                ConstraintDataReadiness(
                    key=item.key,
                    readiness=item.readiness,
                    reason=item.reason,
                )
                for item in recorded.values()
            ],
            conflicts=[*conflicts, *validation_conflicts],
            clarifications=clarifications,
        )


def _duplicate_action_conflicts(
    actions: list[ScenarioConstraintAction],
) -> list[ConstraintConflict]:
    values: dict[ScenarioConstraintKey, set[str]] = {}
    for action in actions:
        values.setdefault(action.key, set()).add(repr(action.value))
    return [
        ConstraintConflict(key=key, message=f"同一条消息对 {key.value} 给出了冲突值")
        for key, candidates in values.items()
        if len(candidates) > 1
    ]


def _validate_project_type(
    value: Any,
    conflicts: list[ConstraintConflict],
) -> ProjectType | None:
    if value is None:
        return None
    try:
        return ProjectType(value)
    except ValueError:
        conflicts.append(
            ConstraintConflict(
                key=ScenarioConstraintKey.PROJECT_TYPE,
                message=f"不支持的项目类型：{value}",
            )
        )
        return None


def _validate_number(
    key: ScenarioConstraintKey,
    value: Any,
    lower: float,
    upper: float,
    conflicts: list[ConstraintConflict],
    caster: Callable[[Any], Any],
) -> Any | None:
    try:
        result = caster(value)
    except (TypeError, ValueError):
        result = None
    if result is None or not lower <= result <= upper:
        conflicts.append(
            ConstraintConflict(
                key=key,
                message=f"{key.value} 必须在 {lower} 到 {upper} 之间",
            )
        )
        return None
    return result


def _validate_fallback(
    value: Any,
    conflicts: list[ConstraintConflict],
) -> CandidateDiscoveryFallbackMode:
    try:
        return CandidateDiscoveryFallbackMode(value)
    except ValueError:
        conflicts.append(
            ConstraintConflict(
                key=ScenarioConstraintKey.FALLBACK_MODE,
                message=f"不支持的用地降级策略：{value}",
            )
        )
        return CandidateDiscoveryFallbackMode.MARKET_EXPLORATION


def _proposal_answer(
    version: ScenarioVersion,
    warnings: list[str],
) -> str:
    if version.conflicts:
        return "我已记录需求，但还不能确认：" + "；".join(
            conflict.message for conflict in version.conflicts
        )
    if version.clarifications:
        return "我还需要补充信息：" + "；".join(version.clarifications)
    parts = [
        f"已生成场景版本 v{version.version_number}",
        f"项目类型={version.project_type.value if version.project_type else '未设置'}",
    ]
    if version.region_resolution is not None:
        parts.append(
            f"区域={version.region_resolution.normalized_name}"
            f"（中心半径 {version.discovery_radius_km:g} 公里）"
        )
    missing = [
        item.key.value
        for item in version.data_readiness
        if item.readiness is ConstraintReadiness.MISSING_DATA
    ]
    if missing:
        parts.append("未进入执行的缺数约束=" + ", ".join(missing))
    if warnings:
        parts.append("解析提示=" + "；".join(warnings))
    parts.append("请确认该版本；确认前不会启动候选发现。")
    return "；".join(parts)


def _confirmation_answer(version: ScenarioVersion) -> str:
    if version.discovery_ready:
        return (
            f"场景版本 v{version.version_number} 已确认。"
            "区域边界和约束已冻结，可以据此启动候选发现。"
        )
    return (
        f"场景版本 v{version.version_number} 已确认。"
        "当前项目类型沿用人工候选录入和正式分析流程。"
    )


def _normalized_ttl(value: int) -> int | None:
    return value if value >= 0 else None
