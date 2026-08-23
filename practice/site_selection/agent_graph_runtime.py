from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.graph import END, START, StateGraph

from .agent_orchestration import AgentExecutionPlan


class AgentGraphConfigurationError(ValueError):
    """Raised when runtime handlers drift from the reviewed Agent plan."""


def compile_agent_plan_graph(
    *,
    plan: AgentExecutionPlan,
    state_schema: type,
    node_handlers: Mapping[str, Callable[..., Any]],
    checkpointer=None,
):
    """Compile a LangGraph whose nodes and edges come only from the plan.

    A reviewed plan is the structural source of truth. Runtime code supplies
    behavior for every planned node, but it cannot silently add, omit or
    reconnect nodes.
    """

    _validate_handlers(plan, node_handlers)
    builder = StateGraph(state_schema)
    for step in plan.steps:
        builder.add_node(step.node_id, node_handlers[step.node_id])

    for step in plan.steps:
        dependencies = list(step.depends_on)
        if not dependencies:
            builder.add_edge(START, step.node_id)
        elif len(dependencies) == 1:
            builder.add_edge(dependencies[0], step.node_id)
        else:
            # LangGraph's list form is an explicit fan-in barrier: the node is
            # invoked once only after every dependency has completed.
            builder.add_edge(dependencies, step.node_id)

    depended_on = {
        dependency
        for step in plan.steps
        for dependency in step.depends_on
    }
    for step in plan.steps:
        if step.node_id not in depended_on:
            builder.add_edge(step.node_id, END)
    return builder.compile(checkpointer=checkpointer)


def _validate_handlers(
    plan: AgentExecutionPlan,
    node_handlers: Mapping[str, Callable[..., Any]],
) -> None:
    planned = {step.node_id for step in plan.steps}
    configured = set(node_handlers)
    missing = sorted(planned - configured)
    extra = sorted(configured - planned)
    if not missing and not extra:
        return

    issues = []
    if missing:
        issues.append("missing handlers: " + ", ".join(missing))
    if extra:
        issues.append("unplanned handlers: " + ", ".join(extra))
    raise AgentGraphConfigurationError("; ".join(issues))
