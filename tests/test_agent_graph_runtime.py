from __future__ import annotations

from typing import TypedDict

import pytest

from practice.site_selection import (
    AgentExecutionPlan,
    AgentGraphConfigurationError,
    AgentRole,
    AgentSkillManifest,
    compile_agent_plan_graph,
)


class RuntimeState(TypedDict, total=False):
    seed: int
    left: int
    right: int
    total: int


def _step(node_id: str, depends_on: list[str] | None = None):
    return AgentSkillManifest(
        node_id=node_id,
        role=AgentRole.ORCHESTRATOR,
        skill_name=f"{node_id}Skill",
        skill_version="v1",
        depends_on=depends_on or [],
        output_contract=f"{node_id}Output",
    )


def _plan() -> AgentExecutionPlan:
    return AgentExecutionPlan(
        plan_id="runtime-compiler-test",
        version="v1",
        steps=[
            _step("root"),
            _step("left", ["root"]),
            _step("right", ["root"]),
            _step("merge", ["left", "right"]),
        ],
    )


def test_compiler_uses_plan_nodes_edges_and_fan_in() -> None:
    merge_calls = []

    def merge(state: RuntimeState):
        merge_calls.append((state["left"], state["right"]))
        return {"total": state["left"] + state["right"]}

    graph = compile_agent_plan_graph(
        plan=_plan(),
        state_schema=RuntimeState,
        node_handlers={
            "root": lambda _state: {"seed": 3},
            "left": lambda state: {"left": state["seed"] + 1},
            "right": lambda state: {"right": state["seed"] + 2},
            "merge": merge,
        },
    )

    result = graph.invoke({})
    drawable = graph.get_graph()

    assert result["total"] == 9
    assert merge_calls == [(4, 5)]
    assert set(drawable.nodes) == {
        "__start__",
        "root",
        "left",
        "right",
        "merge",
        "__end__",
    }
    assert {
        (edge.source, edge.target) for edge in drawable.edges
    } >= {
        ("__start__", "root"),
        ("root", "left"),
        ("root", "right"),
        ("left", "merge"),
        ("right", "merge"),
        ("merge", "__end__"),
    }


@pytest.mark.parametrize(
    ("handlers", "message"),
    [
        ({}, "missing handlers"),
        (
            {
                "root": lambda state: state,
                "left": lambda state: state,
                "right": lambda state: state,
                "merge": lambda state: state,
                "hidden": lambda state: state,
            },
            "unplanned handlers",
        ),
    ],
)
def test_compiler_rejects_handler_drift(handlers, message) -> None:
    with pytest.raises(AgentGraphConfigurationError, match=message):
        compile_agent_plan_graph(
            plan=_plan(),
            state_schema=RuntimeState,
            node_handlers=handlers,
        )
