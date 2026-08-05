import json
from pathlib import Path

from .layer_stats.io import load_layers
from .layer_stats.service import summarize_layers


DEFAULT_DATA_FILE = Path(__file__).parent / "data" / "layers.json"


def main(file_path: str | Path = DEFAULT_DATA_FILE) -> int:
    """读取图层文件、执行统计并打印结果。"""
    try:
        layers = load_layers(file_path)
        summary = summarize_layers(layers)
    except (FileNotFoundError, TypeError, ValueError) as error:
        print(f"运行失败：{error}")
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())