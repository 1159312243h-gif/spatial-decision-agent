import json
from json import JSONDecodeError
from pathlib import Path

from .models import Layer


def load_layers(file_path: str | Path) -> list[Layer]:
    """从 JSON 文件读取并校验图层数据。"""
    path = Path(file_path)

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"图层数据文件不存在：{path}"
        ) from error
    except JSONDecodeError as error:
        raise ValueError(
            f"JSON 格式错误：第 {error.lineno} 行，第 {error.colno} 列"
        ) from error

    if not isinstance(data, list):
        raise TypeError("JSON 最外层必须是列表")

    layers: list[Layer] = []
    required_fields = {"name", "type", "crs"}

    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise TypeError(f"第 {index} 项必须是对象")

        missing_fields = required_fields - item.keys()
        if missing_fields:
            fields = ", ".join(sorted(missing_fields))
            raise ValueError(f"第 {index} 项缺少字段：{fields}")

        try:
            layer = Layer(
                name=item["name"],
                layer_type=item["type"],
                crs=item["crs"],
            )
        except ValueError as error:
            raise ValueError(
                f"第 {index} 项图层数据无效：{error}"
            ) from error

        layers.append(layer)

    return layers