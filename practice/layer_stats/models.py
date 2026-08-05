class Layer:
    """表示一个空间图层。"""

    def __init__(
        self,
        name: str,
        layer_type: str,
        crs: str | None,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("图层名称必须是非空字符串")

        if not isinstance(layer_type, str) or not layer_type.strip():
            raise ValueError("图层类型必须是非空字符串")

        if crs is not None:
            if not isinstance(crs, str) or not crs.strip():
                raise ValueError("CRS 必须是非空字符串或 None")
            crs = crs.strip()

        self.name = name.strip()
        self.layer_type = layer_type.strip()
        self.crs = crs

    def __repr__(self) -> str:
        return (
            f"Layer(name={self.name!r}, "
            f"layer_type={self.layer_type!r}, "
            f"crs={self.crs!r})"
        )