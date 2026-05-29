from __future__ import annotations

import argparse
import json
from pathlib import Path

from figure_agent.common.persistence import write_json
from figure_agent.request_builder.builder import FigureRequestBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FigureRequest JSON files from a ResearchFigureContext.")
    parser.add_argument("context", type=Path, help="Path to ResearchFigureContext JSON")
    parser.add_argument("--output", type=Path, default=None, help="Path to write FigureRequestBundle JSON")
    parser.add_argument("--requests-dir", type=Path, default=None, help="Directory to write split FigureRequest JSON files")
    parser.add_argument("--max-figures", type=int, default=None, help="Maximum number of FigureRequests to generate")
    parser.add_argument("--include-low-priority", action="store_true", help="Keep low-priority candidates")
    parser.add_argument("--fail-on-warning", action="store_true", help="Exit non-zero when warnings are present")
    args = parser.parse_args()

    with args.context.open("r", encoding="utf-8") as handle:
        context = json.load(handle)

    bundle = FigureRequestBuilder().build(
        context,
        max_figures=args.max_figures,
        include_low_priority=args.include_low_priority,
    )

    if args.output:
        write_json(args.output, bundle)
    if args.requests_dir:
        args.requests_dir.mkdir(parents=True, exist_ok=True)
        for request in bundle["requests"]:
            write_json(args.requests_dir / f"{request['request_id']}.json", request)

    print(json.dumps(bundle, indent=2, ensure_ascii=False))
    if args.fail_on_warning and bundle["warnings"]:
        raise SystemExit(1)
