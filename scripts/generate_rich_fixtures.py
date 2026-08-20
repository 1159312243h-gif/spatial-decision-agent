from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from pyproj import Transformer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "data" / "fixtures"
FIXTURE_VERSION = "fixture-rich-v1"
UPDATED_AT = "2026-08-20T00:00:00Z"
QUALITY_NOTICE = (
    "确定性合成数据，仅用于验证多候选比较、空间查询和证据链；"
    "不代表真实城市覆盖率、商业活力或设施现状。"
)


CANDIDATES: dict[str, list[dict[str, Any]]] = {
    "shopping_mall": [
        {
            "parcel_id": "MALL-A01",
            "name": "商场候选 A｜轨交餐饮核心",
            "scenario_profile": "transit_catering_core",
            "longitude": 121.4700,
            "latitude": 31.2300,
            "area_hectares": 0.9,
            "geometry_dataset_id": "demo-mall-candidates",
        },
        {
            "parcel_id": "MALL-A02",
            "name": "商场候选 B｜办公商务门户",
            "scenario_profile": "office_gateway",
            "longitude": 121.5050,
            "latitude": 31.2300,
            "area_hectares": 1.2,
            "geometry_dataset_id": "demo-mall-candidates",
        },
        {
            "parcel_id": "MALL-A03",
            "name": "商场候选 C｜成熟居住片区",
            "scenario_profile": "residential_mature",
            "longitude": 121.4350,
            "latitude": 31.2300,
            "area_hectares": 1.5,
            "geometry_dataset_id": "demo-mall-candidates",
        },
        {
            "parcel_id": "MALL-A04",
            "name": "商场候选 D｜综合服务中心",
            "scenario_profile": "mixed_service_center",
            "longitude": 121.4700,
            "latitude": 31.2700,
            "area_hectares": 1.8,
            "geometry_dataset_id": "demo-mall-candidates",
        },
        {
            "parcel_id": "MALL-A05",
            "name": "商场候选 E｜商业竞争饱和区",
            "scenario_profile": "competition_saturated",
            "longitude": 121.5050,
            "latitude": 31.2700,
            "area_hectares": 1.3,
            "geometry_dataset_id": "demo-mall-candidates",
        },
        {
            "parcel_id": "MALL-A06",
            "name": "商场候选 F｜外围成长片区",
            "scenario_profile": "emerging_fringe",
            "longitude": 121.4350,
            "latitude": 31.2700,
            "area_hectares": 1.6,
            "geometry_dataset_id": "demo-mall-candidates",
        },
    ],
    "logistics_park": [
        {
            "parcel_id": "LOG-A01",
            "name": "物流园候选 A｜高速服务门户",
            "scenario_profile": "highway_service_gateway",
            "longitude": 121.5600,
            "latitude": 31.1800,
            "area_hectares": 2.0,
            "geometry_dataset_id": "demo-logistics-candidates",
        },
        {
            "parcel_id": "LOG-A02",
            "name": "物流园候选 B｜铁路产业集群",
            "scenario_profile": "rail_industrial_cluster",
            "longitude": 121.6200,
            "latitude": 31.1800,
            "area_hectares": 3.2,
            "geometry_dataset_id": "demo-logistics-candidates",
        },
        {
            "parcel_id": "LOG-A03",
            "name": "物流园候选 C｜港口仓储走廊",
            "scenario_profile": "port_warehouse_corridor",
            "longitude": 121.6800,
            "latitude": 31.1800,
            "area_hectares": 4.5,
            "geometry_dataset_id": "demo-logistics-candidates",
        },
        {
            "parcel_id": "LOG-A04",
            "name": "物流园候选 D｜城市配送边缘",
            "scenario_profile": "urban_delivery_sensitive",
            "longitude": 121.5600,
            "latitude": 31.2800,
            "area_hectares": 1.8,
            "geometry_dataset_id": "demo-logistics-candidates",
        },
        {
            "parcel_id": "LOG-A05",
            "name": "物流园候选 E｜综合物流节点",
            "scenario_profile": "balanced_logistics_node",
            "longitude": 121.6200,
            "latitude": 31.2800,
            "area_hectares": 3.8,
            "geometry_dataset_id": "demo-logistics-candidates",
        },
        {
            "parcel_id": "LOG-A06",
            "name": "物流园候选 F｜航空联运节点",
            "scenario_profile": "air_cargo_intermodal",
            "longitude": 121.6800,
            "latitude": 31.2800,
            "area_hectares": 2.7,
            "geometry_dataset_id": "demo-logistics-candidates",
        },
    ],
}


MALL_COUNTS = [
    {"地铁站": 2, "公交站": 7, "住宅小区": 4, "公寓": 3, "写字楼": 5, "产业园": 1, "餐厅": 9, "咖啡馆": 5, "医院": 1, "学校": 2, "文化场馆": 2, "购物中心": 2, "百货商场": 1},
    {"地铁站": 1, "公交站": 5, "住宅小区": 3, "公寓": 5, "写字楼": 10, "产业园": 3, "餐厅": 7, "咖啡馆": 6, "医院": 1, "学校": 1, "文化场馆": 1, "购物中心": 2, "百货商场": 1},
    {"地铁站": 1, "公交站": 5, "住宅小区": 9, "公寓": 6, "写字楼": 2, "产业园": 1, "餐厅": 6, "咖啡馆": 3, "医院": 2, "学校": 4, "文化场馆": 1, "购物中心": 1, "百货商场": 1},
    {"地铁站": 1, "公交站": 6, "住宅小区": 5, "公寓": 4, "写字楼": 5, "产业园": 3, "餐厅": 8, "咖啡馆": 4, "医院": 1, "学校": 3, "文化场馆": 2, "购物中心": 2, "百货商场": 1},
    {"地铁站": 1, "公交站": 4, "住宅小区": 4, "公寓": 3, "写字楼": 4, "产业园": 2, "餐厅": 10, "咖啡馆": 5, "医院": 1, "学校": 2, "文化场馆": 2, "购物中心": 6, "百货商场": 4},
    {"地铁站": 0, "公交站": 3, "住宅小区": 4, "公寓": 2, "写字楼": 2, "产业园": 4, "餐厅": 3, "咖啡馆": 1, "医院": 1, "学校": 1, "文化场馆": 1, "购物中心": 0, "百货商场": 1},
]


LOGISTICS_COUNTS = [
    {"高速收费站": 2, "高速出入口": 3, "铁路货运站": 1, "港口": 0, "货运机场": 0, "物流公司": 8, "快递网点": 5, "工业园": 3, "仓储基地": 3, "加油站": 4, "充电站": 2, "货车维修": 3, "住宅小区": 2, "学校": 1, "医院": 1},
    {"高速收费站": 1, "高速出入口": 2, "铁路货运站": 3, "港口": 0, "货运机场": 0, "物流公司": 6, "快递网点": 3, "工业园": 8, "仓储基地": 7, "加油站": 3, "充电站": 2, "货车维修": 4, "住宅小区": 1, "学校": 0, "医院": 1},
    {"高速收费站": 1, "高速出入口": 2, "铁路货运站": 1, "港口": 2, "货运机场": 0, "物流公司": 4, "快递网点": 2, "工业园": 7, "仓储基地": 8, "加油站": 2, "充电站": 2, "货车维修": 3, "住宅小区": 0, "学校": 0, "医院": 0},
    {"高速收费站": 1, "高速出入口": 1, "铁路货运站": 1, "港口": 0, "货运机场": 0, "物流公司": 5, "快递网点": 5, "工业园": 3, "仓储基地": 2, "加油站": 3, "充电站": 4, "货车维修": 2, "住宅小区": 10, "学校": 3, "医院": 2},
    {"高速收费站": 2, "高速出入口": 2, "铁路货运站": 2, "港口": 1, "货运机场": 0, "物流公司": 7, "快递网点": 4, "工业园": 6, "仓储基地": 6, "加油站": 4, "充电站": 3, "货车维修": 4, "住宅小区": 2, "学校": 1, "医院": 1},
    {"高速收费站": 1, "高速出入口": 2, "铁路货运站": 0, "港口": 1, "货运机场": 2, "物流公司": 3, "快递网点": 2, "工业园": 4, "仓储基地": 5, "加油站": 2, "充电站": 3, "货车维修": 3, "住宅小区": 1, "学校": 0, "医院": 1},
]


CATEGORY_RADIUS_M = {
    "地铁站": (250, 1_200),
    "公交站": (120, 1_300),
    "餐厅": (100, 1_250),
    "咖啡馆": (100, 1_150),
    "住宅小区": (350, 2_600),
    "公寓": (250, 2_400),
    "写字楼": (250, 2_500),
    "产业园": (500, 2_700),
    "医院": (500, 2_800),
    "学校": (400, 2_700),
    "文化场馆": (300, 2_600),
    "购物中心": (600, 4_500),
    "百货商场": (600, 4_500),
    "高速收费站": (1_000, 12_000),
    "高速出入口": (800, 12_000),
    "铁路货运站": (2_000, 35_000),
    "港口": (5_000, 45_000),
    "货运机场": (8_000, 45_000),
    "物流公司": (300, 8_000),
    "快递网点": (250, 7_500),
    "工业园": (700, 15_000),
    "仓储基地": (600, 15_000),
    "加油站": (300, 6_000),
    "充电站": (250, 6_000),
    "货车维修": (350, 6_500),
}


def build_candidate_catalog() -> dict[str, Any]:
    return {
        "is_fixture": True,
        "version": FIXTURE_VERSION,
        "updated_at": UPDATED_AT,
        "quality_notice": QUALITY_NOTICE,
        "project_candidates": CANDIDATES,
    }


def build_poi_dataset() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for project_type, counts_by_candidate in (
        ("shopping_mall", MALL_COUNTS),
        ("logistics_park", LOGISTICS_COUNTS),
    ):
        for candidate, category_counts in zip(
            CANDIDATES[project_type],
            counts_by_candidate,
            strict=True,
        ):
            records.extend(
                _cluster_records(
                    project_type,
                    candidate,
                    category_counts,
                    starting_index=len(records) + 1,
                )
            )
    return {
        "dataset_id": "poi-fixture-synthetic-multicandidate",
        "version": FIXTURE_VERSION,
        "provider": "mock",
        "crs": "EPSG:4326",
        "updated_at": UPDATED_AT,
        "is_synthetic": True,
        "coverage_scope": "12 个合成候选地、25 个 POI 类别的场景化局部覆盖",
        "generation_method": "deterministic-radial-v1",
        "quality_notice": QUALITY_NOTICE,
        "records": records,
    }


def build_spatial_seed() -> dict[str, Any]:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32651", always_xy=True)
    mall_features = [
        _candidate_feature(item, "fixture-commercial", transformer)
        for item in CANDIDATES["shopping_mall"]
    ]
    logistics_features = [
        _candidate_feature(item, "fixture-logistics", transformer)
        for item in CANDIDATES["logistics_park"]
    ]
    mall_constraints = [
        _constraint_feature("MALL-ECO-01", CANDIDATES["shopping_mall"][0], transformer),
        _constraint_feature("MALL-ECO-02", CANDIDATES["shopping_mall"][4], transformer),
    ]
    logistics_constraints = [
        _constraint_feature("LOG-SENSITIVE-01", CANDIDATES["logistics_park"][3], transformer),
        _constraint_feature("LOG-SENSITIVE-02", CANDIDATES["logistics_park"][5], transformer),
    ]
    return {
        "is_fixture": True,
        "version": FIXTURE_VERSION,
        "updated_at": UPDATED_AT,
        "crs": "EPSG:32651",
        "projects": [
            {"project_id": "fixture-shopping-mall", "project_type": "shopping_mall", "name": "合成商场多候选评估"},
            {"project_id": "fixture-logistics-park", "project_type": "logistics_park", "name": "合成物流园多候选评估"},
        ],
        "layers": [
            _layer("demo-mall-candidates", "fixture-shopping-mall", "合成商场候选地", "candidate_parcel", "parcel_id", ["parcel_id", "land_use", "scenario_profile"], mall_features),
            _layer("demo-mall-constraints", "fixture-shopping-mall", "合成生态观察图层", "ecological_protection", "constraint_id", ["constraint_id", "level"], mall_constraints),
            _layer("demo-logistics-candidates", "fixture-logistics-park", "合成物流园候选地", "candidate_parcel", "parcel_id", ["parcel_id", "land_use", "scenario_profile"], logistics_features),
            _layer("demo-logistics-constraints", "fixture-logistics-park", "合成敏感目标观察图层", "sensitive_receptor", "constraint_id", ["constraint_id", "level"], logistics_constraints),
        ],
    }


def _cluster_records(
    project_type: str,
    candidate: dict[str, Any],
    category_counts: dict[str, int],
    *,
    starting_index: int,
) -> list[dict[str, Any]]:
    records = []
    record_index = starting_index
    for category, count in category_counts.items():
        minimum, maximum = CATEGORY_RADIUS_M[category]
        for ordinal in range(1, count + 1):
            if record_index == 1:
                longitude, latitude = 121.4710, 31.2300
            else:
                longitude, latitude = _offset_point(
                    candidate["longitude"],
                    candidate["latitude"],
                    minimum,
                    maximum,
                    token=f"{candidate['parcel_id']}:{category}:{ordinal}",
                )
            records.append(
                {
                    "poi_id": f"F{record_index:04d}",
                    "name": f"合成{candidate['parcel_id']}{category}{ordinal:02d}",
                    "category": category,
                    "longitude": longitude,
                    "latitude": latitude,
                    "attributes": {
                        "synthetic": True,
                        "project_type": project_type,
                        "candidate_id": candidate["parcel_id"],
                        "scenario_profile": candidate["scenario_profile"],
                        "generation_method": "deterministic-radial-v1",
                    },
                }
            )
            record_index += 1
    return records


def _offset_point(
    longitude: float,
    latitude: float,
    minimum_radius_m: int,
    maximum_radius_m: int,
    *,
    token: str,
) -> tuple[float, float]:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    span = maximum_radius_m - minimum_radius_m
    radius = minimum_radius_m + int.from_bytes(digest[:4], "big") % (span + 1)
    angle = int.from_bytes(digest[4:8], "big") / (2**32) * 2 * math.pi
    east_m = math.cos(angle) * radius
    north_m = math.sin(angle) * radius
    longitude_delta = east_m / (111_320 * math.cos(math.radians(latitude)))
    latitude_delta = north_m / 110_540
    return round(longitude + longitude_delta, 6), round(latitude + latitude_delta, 6)


def _candidate_feature(candidate, land_use, transformer) -> dict[str, Any]:
    center_x, center_y = transformer.transform(
        candidate["longitude"], candidate["latitude"]
    )
    area_square_m = candidate["area_hectares"] * 10_000
    width = math.sqrt(area_square_m * 1.25)
    height = area_square_m / width
    x0, x1 = center_x - width / 2, center_x + width / 2
    y0, y1 = center_y - height / 2, center_y + height / 2
    coordinates = [
        [round(x0, 3), round(y0, 3)],
        [round(x1, 3), round(y0, 3)],
        [round(x1, 3), round(y1, 3)],
        [round(x0, 3), round(y1, 3)],
        [round(x0, 3), round(y0, 3)],
    ]
    return {
        "source_feature_id": candidate["parcel_id"],
        "properties": {
            "parcel_id": candidate["parcel_id"],
            "land_use": land_use,
            "scenario_profile": candidate["scenario_profile"],
            "area_hectares": candidate["area_hectares"],
        },
        "geometry": {"type": "Polygon", "coordinates": [coordinates]},
    }


def _constraint_feature(feature_id, candidate, transformer) -> dict[str, Any]:
    x, y = transformer.transform(candidate["longitude"], candidate["latitude"])
    return {
        "source_feature_id": feature_id,
        "properties": {"constraint_id": feature_id, "level": "fixture-review"},
        "geometry": {"type": "Point", "coordinates": [round(x, 3), round(y, 3)]},
    }


def _layer(layer_id, project_id, name, layer_type, source_id_field, required_fields, features):
    return {
        "layer_id": layer_id,
        "project_id": project_id,
        "name": name,
        "layer_type": layer_type,
        "source_id_field": source_id_field,
        "required_fields": required_fields,
        "features": features,
    }


def write_fixtures(root: Path = FIXTURE_ROOT) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payloads = {
        "candidates.json": build_candidate_catalog(),
        "poi.json": build_poi_dataset(),
        "spatial_layers.json": build_spatial_seed(),
    }
    for filename, payload in payloads.items():
        (root / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=FIXTURE_ROOT)
    args = parser.parse_args()
    write_fixtures(args.output_root)
    payload = build_poi_dataset()
    print(
        "Rich fixtures generated: "
        f"candidates={sum(len(items) for items in CANDIDATES.values())}, "
        f"pois={len(payload['records'])}, version={FIXTURE_VERSION}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
