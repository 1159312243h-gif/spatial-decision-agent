from .models import Layer


def summarize_layers(layers: list[Layer]) -> dict[str, object]:
    """统计空间图层的数量、类型和 CRS 完整性。"""
    if not isinstance(layers, list):
        raise TypeError("layers 必须是列表")

    layer_names: set[str] = set()
    layer_types: set[str] = set()
    missing_crs: list[str] = []
    counts_by_type: dict[str, int] = {}

    for index, layer in enumerate(layers, start=1):
        if not isinstance(layer, Layer):
            raise TypeError(f"第 {index} 项必须是 Layer 对象")

        if layer.name in layer_names:
            raise ValueError(f"发现重复图层：{layer.name}")

        layer_names.add(layer.name)
        layer_types.add(layer.layer_type)

        if layer.crs is None:
            missing_crs.append(layer.name)

        counts_by_type[layer.layer_type] = (
            counts_by_type.get(layer.layer_type, 0) + 1
        )

    return {
        "total": len(layers),
        "types": sorted(layer_types),
        "missing_crs": missing_crs,
        "counts_by_type": counts_by_type,
    }