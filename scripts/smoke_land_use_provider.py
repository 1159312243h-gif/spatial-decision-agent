from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from app.services.site_selection_land_use_provider import (
    build_configured_land_use_provider,
)
from practice.site_selection import LandUseQuery, ProjectType


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only smoke check for the configured land-use provider.",
    )
    parser.add_argument("--west", type=float, required=True)
    parser.add_argument("--south", type=float, required=True)
    parser.add_argument("--east", type=float, required=True)
    parser.add_argument("--north", type=float, required=True)
    parser.add_argument(
        "--project-type",
        choices=["coffee_shop", "convenience_store"],
        default="coffee_shop",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(os.getenv("ENV_FILE", PROJECT_ROOT / ".env"))
    configured = build_configured_land_use_provider(os.environ)
    try:
        if configured.provider is None:
            raise RuntimeError("SITE_SELECTION_LAND_USE_PROVIDER 已禁用")
        result = configured.provider.search(
            LandUseQuery(
                project_type=ProjectType(args.project_type),
                west=args.west,
                south=args.south,
                east=args.east,
                north=args.north,
            )
        )
        print(
            f"dataset={result.source.dataset_id} "
            f"evidence={result.source.evidence_level.value} "
            f"records={result.source.record_count} "
            f"available={result.source.available_record_count} "
            f"cache_hit={str(result.source.cache_hit).lower()}"
        )
        print(f"source={result.source.source_uri}")
        print(f"license={result.source.license}")
        for item in result.features[:10]:
            print(
                f"{item.source_feature_id}\t{item.land_use_class}\t"
                f"{item.area_hectares:.4f}ha\t{item.name}"
            )
        return 0 if result.features else 2
    finally:
        configured.close()


if __name__ == "__main__":
    raise SystemExit(main())
