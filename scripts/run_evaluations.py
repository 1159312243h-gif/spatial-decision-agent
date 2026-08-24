from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from practice.site_selection.evaluation import (
    Day26EvaluationRunner,
    load_evaluation_suite,
    write_evaluation_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen Day 26 evaluations")
    parser.add_argument(
        "--suite",
        type=Path,
        default=PROJECT_ROOT / "evals" / "day26_cases.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "evals" / "results" / "day26-summary.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    suite = load_evaluation_suite(args.suite)
    summary = EvaluationRunner(PROJECT_ROOT / "data" / "fixtures").run_suite(
        suite
    )
    write_evaluation_summary(summary, args.output)
    print(
        f"Evaluations: passed={summary.passed}/{summary.total}, "
        f"failed={summary.failed}, output={args.output}"
    )
    for result in summary.results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"[{marker}] {result.case_id} {result.scenario} {result.elapsed_ms:.3f}ms")
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
