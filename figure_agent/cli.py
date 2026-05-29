from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from figure_agent.agent import FigureAgent
from figure_agent.common.persistence import write_json
from figure_agent.figure_request_runner import FigureRequestRunner
from figure_agent.request_builder import FigureRequestBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FigureAgent.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_requests = subparsers.add_parser("build-requests", help="Build FigureRequest JSON files from a ResearchFigureContext.")
    build_requests.add_argument("context", type=Path, help="Path to ResearchFigureContext JSON")
    build_requests.add_argument("--output", type=Path, default=None, help="Path to write FigureRequestBundle JSON")
    build_requests.add_argument("--requests-dir", type=Path, default=None, help="Directory to write split FigureRequest JSON files")
    build_requests.add_argument("--max-figures", type=int, default=None, help="Maximum number of FigureRequests to generate")
    build_requests.add_argument("--include-low-priority", action="store_true", help="Keep low-priority candidates")

    run_request = subparsers.add_parser("run-request", help="Render one FigureRequest into figure assets.")
    run_request.add_argument("request", type=Path, help="Path to FigureRequest JSON")
    run_request.add_argument("--output", type=Path, default=None, help="Path to write the FigureAssetManifest JSON")

    run_all = subparsers.add_parser("run", help="Run context -> requests -> figure assets.")
    run_all.add_argument("context", type=Path, help="Path to ResearchFigureContext JSON")
    run_all.add_argument("--output", type=Path, default=None, help="Path to write the end-to-end result JSON")
    run_all.add_argument("--max-figures", type=int, default=None, help="Maximum number of FigureRequests to generate")
    run_all.add_argument("--include-low-priority", action="store_true", help="Keep low-priority candidates")

    args = parser.parse_args()
    if args.command == "build-requests":
        result = FigureRequestBuilder().build(
            _read_json(args.context),
            max_figures=args.max_figures,
            include_low_priority=args.include_low_priority,
        )
        if args.output:
            write_json(args.output, result)
        if args.requests_dir:
            args.requests_dir.mkdir(parents=True, exist_ok=True)
            for request in result["requests"]:
                write_json(args.requests_dir / f"{request['request_id']}.json", request)
    elif args.command == "run-request":
        result = FigureRequestRunner().run(_read_json(args.request))
        if args.output:
            write_json(args.output, result)
    else:
        result = FigureAgent().build(
            _read_json(args.context),
            max_figures=args.max_figures,
            include_low_priority=args.include_low_priority,
        )
        if args.output:
            write_json(args.output, result)

    print(json.dumps(result, indent=2, ensure_ascii=False))


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
