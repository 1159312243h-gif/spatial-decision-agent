from collections.abc import Callable
from typing import TypedDict


class LayerSummary(TypedDict):
    total: int
    types: set[str]
    missing_crs: list[str]
    counts_by_type: dict[str, int]


REQUIRED_FIELDS = ("name", "type", "crs")


def summarize_layers(layers: object) -> LayerSummary:
    """Validate layer records and return summary statistics."""
    if not isinstance(layers, list):
        raise TypeError("layers 必须是列表。")

    layer_types: set[str] = set()
    missing_crs: list[str] = []
    counts_by_type: dict[str, int] = {}
    seen_names: set[str] = set()

    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            raise TypeError(f"索引 {index} 处的元素必须是字典。")

        missing_fields = [
            field for field in REQUIRED_FIELDS if field not in layer
        ]
        if missing_fields:
            fields = ", ".join(missing_fields)
            raise ValueError(f"索引 {index} 处缺少字段: {fields}")

        name = layer["name"]
        layer_type = layer["type"]
        crs = layer["crs"]

        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"索引 {index} 处的 name 必须是非空字符串。")
        if not isinstance(layer_type, str) or not layer_type.strip():
            raise ValueError(f"索引 {index} 处的 type 必须是非空字符串。")
        if name in seen_names:
            raise ValueError(f"图层名称重复: {name}")

        seen_names.add(name)
        layer_types.add(layer_type)
        counts_by_type[layer_type] = counts_by_type.get(layer_type, 0) + 1

        if crs is None or (isinstance(crs, str) and not crs.strip()):
            missing_crs.append(name)

    return {
        "total": len(layers),
        "types": layer_types,
        "missing_crs": missing_crs,
        "counts_by_type": counts_by_type,
    }


def expect_error(
    exception_type: type[Exception],
    message_part: str,
    action: Callable[[], object],
) -> None:
    """Assert that an action raises the expected error with useful context."""
    try:
        action()
    except exception_type as error:
        assert message_part in str(error)
    else:
        raise AssertionError(f"预期抛出 {exception_type.__name__}")


if __name__ == "__main__":
    layers = [
        {"name": "生态保护红线", "type": "polygon", "crs": "EPSG:4490"},
        {"name": "永久基本农田", "type": "polygon", "crs": "EPSG:4490"},
        {"name": "道路", "type": "line", "crs": None},
    ]

    summary = summarize_layers(layers)
    print("样例统计结果:", summary)

    assert summary["total"] == 3
    assert summary["types"] == {"polygon", "line"}
    assert summary["missing_crs"] == ["道路"]
    assert summary["counts_by_type"] == {"polygon": 2, "line": 1}
    assert summarize_layers([]) == {
        "total": 0,
        "types": set(),
        "missing_crs": [],
        "counts_by_type": {},
    }
    assert summarize_layers(
        [{"name": "空坐标系", "type": "point", "crs": ""}]
    )["missing_crs"] == ["空坐标系"]

    expect_error(TypeError, "必须是列表", lambda: summarize_layers("not a list"))
    expect_error(TypeError, "索引 0", lambda: summarize_layers(["not a dict"]))
    expect_error(
        ValueError,
        "crs",
        lambda: summarize_layers([{"name": "道路", "type": "line"}]),
    )
    expect_error(
        ValueError,
        "重复",
        lambda: summarize_layers(
            [
                {"name": "道路", "type": "line", "crs": None},
                {"name": "道路", "type": "line", "crs": "EPSG:4490"},
            ]
        ),
    )
    expect_error(
        ValueError,
        "name 必须是非空字符串",
        lambda: summarize_layers([{"name": " ", "type": "line", "crs": None}]),
    )
    expect_error(
        ValueError,
        "type 必须是非空字符串",
        lambda: summarize_layers([{"name": "道路", "type": "", "crs": None}]),
    )

    print("All checks passed.")
