from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from practice.site_selection.performance import measure_fixture_performance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure the local fixture baseline")
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--warmup-runs", type=int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "evals" / "results" / "performance.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = measure_fixture_performance(
        PROJECT_ROOT,
        samples=args.samples,
        warmup_runs=args.warmup_runs,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print("Local fixture performance (not a production benchmark):")
    for item in report.measurements:
        print(
            f"- {item.metric}: median={item.median_ms:.3f}ms "
            f"min={item.min_ms:.3f}ms max={item.max_ms:.3f}ms "
            f"samples={item.samples}"
        )
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
