import json
import tempfile
import unittest
from pathlib import Path

from practice.layer_stats.io import load_layers
from practice.layer_stats.models import Layer
from practice.layer_stats.service import summarize_layers


class LayerStatsTests(unittest.TestCase):
    def write_json(self, directory: str, data: object) -> Path:
        path = Path(directory) / "layers.json"
        path.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_normal_data(self) -> None:
        data = [
            {"name": "生态保护红线", "type": "polygon", "crs": "EPSG:4490"},
            {"name": "永久基本农田", "type": "polygon", "crs": "EPSG:4490"},
            {"name": "道路", "type": "line", "crs": None},
        ]

        with tempfile.TemporaryDirectory() as directory:
            layers = load_layers(self.write_json(directory, data))

        self.assertEqual(
            summarize_layers(layers),
            {
                "total": 3,
                "types": ["line", "polygon"],
                "missing_crs": ["道路"],
                "counts_by_type": {"polygon": 2, "line": 1},
            },
        )

    def test_empty_list(self) -> None:
        self.assertEqual(
            summarize_layers([]),
            {
                "total": 0,
                "types": [],
                "missing_crs": [],
                "counts_by_type": {},
            },
        )

    def test_missing_field(self) -> None:
        data = [{"name": "生态保护红线", "type": "polygon"}]

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, data)
            with self.assertRaisesRegex(ValueError, "缺少字段：crs"):
                load_layers(path)

    def test_duplicate_layer(self) -> None:
        layers = [
            Layer("道路", "line", "EPSG:4490"),
            Layer("道路", "line", "EPSG:4490"),
        ]

        with self.assertRaisesRegex(ValueError, "发现重复图层：道路"):
            summarize_layers(layers)

    def test_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text('[{"name": }]', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "JSON 格式错误"):
                load_layers(path)

    def test_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"

            with self.assertRaisesRegex(FileNotFoundError, "文件不存在"):
                load_layers(path)


if __name__ == "__main__":
    unittest.main()