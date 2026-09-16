from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from practice.site_selection.agent_collaboration import default_agent_profiles
from practice.site_selection.agent_evaluation import (
    FrozenAgentEvaluationRunner,
    load_agent_evaluation_suite,
    write_agent_evaluation_report,
)
from practice.site_selection.agent_harness import PromptBundle
from practice.site_selection.evaluation import FrozenEvaluationRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run frozen multi-Agent Harness evaluations"
    )
    parser.add_argument(
        "--suite",
        type=Path,
        default=PROJECT_ROOT / "evals" / "agent-cases.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "evals" / "results" / "agent-summary.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_state = FrozenEvaluationRunner(
        PROJECT_ROOT / "data" / "fixtures"
    ).build_runtime_state()
    bundle = PromptBundle(
        version="multi-agent-prompts-v1",
        change_summary="Initial reviewed role prompts",
        created_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
        profiles=default_agent_profiles("scripted-evaluation-model"),
    )
    report = FrozenAgentEvaluationRunner(base_state, bundle).run_suite(
        load_agent_evaluation_suite(args.suite)
    )
    write_agent_evaluation_report(report, args.output)
    print(
        f"Agent evaluations: passed={report.passed}/{report.total}, "
        f"failed={report.failed}, output={args.output}"
    )
    metrics = report.metrics
    print(
        "Metrics: "
        f"task_success={metrics.task_success_rate:.3f}, "
        f"evidence_refs={metrics.evidence_reference_valid_rate:.3f}, "
        f"reflection_recovery={metrics.reflection_recovery_rate:.3f}, "
        f"budget_convergence={metrics.budget_convergence_rate:.3f}"
    )
    for result in report.results:
        marker = "PASS" if result.passed else "FAIL"
        print(
            f"[{marker}] {result.case_id} {result.scenario} "
            f"{result.elapsed_ms:.3f}ms"
        )
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
