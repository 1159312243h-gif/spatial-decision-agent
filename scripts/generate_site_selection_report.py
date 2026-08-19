from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from practice.site_selection import AgentState
from practice.site_selection.reporting import generate_site_selection_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an auditable site-selection Word report.",
    )
    parser.add_argument("state_json", type=Path)
    parser.add_argument("output_docx", type=Path)
    arguments = parser.parse_args()

    state = AgentState.model_validate_json(
        arguments.state_json.read_text(encoding="utf-8")
    )
    output = generate_site_selection_report(state, arguments.output_docx)
    print(f"Site-selection report OK: {output}")


if __name__ == "__main__":
    main()
