#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from figure_agent.common.validators import validate_payload
from figure_agent.request_builder import FigureRequestBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description="Build FigureAgent eval contexts from local CCF-A paper assets.")
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / "ccfa_papers", help="Directory containing paper PDFs, extracted text, context_data, and research_contexts.")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "ccfa_papers" / "figure_agent_eval", help="Directory for generated eval contexts and request bundles.")
    parser.add_argument("--path-base", type=Path, default=PROJECT_ROOT, help="Base directory for relative paths embedded in generated contexts and manifests.")
    parser.add_argument("--use-llm", action="store_true", help="Allow FigureAgent's internal LLM hooks while building request bundles.")
    parser.add_argument("--render-smoke", action="store_true", help="Run FigureAgent on every generated context and write a smoke report.")
    args = parser.parse_args()

    if not args.use_llm:
        os.environ["FIGURE_AGENT_LLM_ENABLED"] = "0"

    source_root = args.source.resolve()
    output_root = args.output.resolve()
    path_base = args.path_base.resolve()
    path_base.mkdir(parents=True, exist_ok=True)
    os.chdir(path_base)

    manifest = read_json(source_root / "manifest.json")
    context_manifest = read_json(source_root / "research_contexts" / "manifest.json")
    context_paths = {
        item["paper_id"]: resolve_project_path(item["context_path"])
        for item in context_manifest.get("contexts", [])
    }

    contexts_dir = output_root / "contexts"
    data_dir = output_root / "data"
    bundles_dir = output_root / "request_bundles"
    requests_dir = output_root / "requests"
    for directory in [contexts_dir, data_dir, bundles_dir, requests_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    eval_entries: list[dict[str, Any]] = []
    chart_entries: list[dict[str, Any]] = []
    builder = FigureRequestBuilder()

    for paper in manifest.get("papers", []):
        paper_id = paper_id_from_file(paper["file"])
        context_path = context_paths.get(paper_id)
        if context_path is None or not context_path.exists():
            raise FileNotFoundError(f"missing research context for {paper_id}")

        context = normalize_context(read_json(context_path), paper, source_root, output_root, data_dir, path_base, chart_entries)
        validate_payload(context, "research_figure_context.schema.json")

        generated_context_path = contexts_dir / f"{context['paper_id']}_context.json"
        write_json(generated_context_path, context)

        bundle = builder.build(context)
        bundle_path = bundles_dir / f"{context['paper_id']}_request_bundle.json"
        write_json(bundle_path, bundle)

        paper_requests_dir = requests_dir / context["paper_id"]
        paper_requests_dir.mkdir(parents=True, exist_ok=True)
        for request in bundle["requests"]:
            write_json(paper_requests_dir / f"{request['request_id']}.json", request)

        eval_entries.append({
            "paper_id": context["paper_id"],
            "paper_title": context["paper_title"],
            "venue": paper.get("venue"),
            "ccf_area": paper.get("ccf_area"),
            "source_pdf": context.get("source_pdf"),
            "context_path": relative_to_base(generated_context_path, path_base),
            "request_bundle_path": relative_to_base(bundle_path, path_base),
            "requests_dir": relative_to_base(paper_requests_dir, path_base),
            "chart_data": [
                {
                    "evidence_id": evidence["evidence_id"],
                    "path": evidence.get("path"),
                    "columns": evidence.get("columns"),
                    "row_count": evidence.get("row_count"),
                    "paragraph_ref": evidence.get("paragraph_ref"),
                }
                for evidence in context["evidence_catalog"]
                if evidence["kind"] == "table_file"
            ],
            "expected_requests": [
                {
                    "request_id": request["request_id"],
                    "figure_id": request["figure_id"],
                    "figure_kind": request["figure_kind"],
                    "target_section": request["target_section"],
                }
                for request in bundle["requests"]
            ],
            "builder_status": bundle["status"],
            "builder_warnings": bundle["warnings"],
        })

    eval_manifest = {
        "created_by": "scripts/build_ccfa_eval_dataset.py",
        "source_manifest": relative_to_base(source_root / "manifest.json", path_base),
        "purpose": "Deterministic FigureAgent evaluation contexts and chart data extracted from local CCF-A paper assets.",
        "notes": [
            "Contexts use png/svg outputs so chart and diagram requests can run together.",
            "Chart CSV files are local numeric table slices curated from the source papers and copied into this eval dataset.",
            "Run commands from the path base used to generate this dataset because FigureAgent resolves relative evidence paths from cwd.",
        ],
        "path_base": str(path_base),
        "paper_count": len(eval_entries),
        "papers": eval_entries,
    }
    write_json(output_root / "manifest.json", eval_manifest)
    write_json(output_root / "chart_data_manifest.json", {"chart_data": chart_entries})

    smoke_report = None
    if args.render_smoke:
        smoke_report = run_smoke(output_root, contexts_dir, path_base)
        write_json(output_root / "smoke_report.json", smoke_report)

    print(json.dumps({
        "output_root": relative_to_base(output_root, path_base),
        "path_base": str(path_base),
        "paper_count": len(eval_entries),
        "contexts": len(list(contexts_dir.glob("*_context.json"))),
        "request_bundles": len(list(bundles_dir.glob("*_request_bundle.json"))),
        "chart_data_files": len(list(data_dir.glob("*.csv"))),
        "smoke_status": smoke_report["status"] if smoke_report else "not_run",
    }, indent=2))
    return 0


def normalize_context(
    context: dict[str, Any],
    paper: dict[str, Any],
    source_root: Path,
    output_root: Path,
    data_dir: Path,
    path_base: Path,
    chart_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = deepcopy(context)
    normalized["target_stage"] = "figure_agent_evaluation"
    normalized["output_formats"] = ["png", "svg"]
    normalized["source_pdf"] = relative_to_base(source_root / paper["file"], path_base)
    normalized["source_metadata"] = {
        "venue": paper.get("venue"),
        "ccf_area": paper.get("ccf_area"),
        "source_url": paper.get("source_url"),
        "source_sha256": paper.get("sha256"),
        "notes": paper.get("notes"),
    }

    for evidence in normalized.get("evidence_catalog", []):
        if evidence["kind"] == "table_file" and evidence.get("path"):
            source_path = resolve_project_path(evidence["path"])
            target_path = data_dir / source_path.name
            shutil.copyfile(source_path, target_path)
            columns, row_count = inspect_csv(target_path)
            evidence["path"] = relative_to_base(target_path, path_base)
            evidence["columns"] = columns
            evidence["row_count"] = row_count
            evidence["sha256"] = sha256(target_path)
            evidence["extraction_note"] = f"Copied from {relative_to_base(source_path, path_base)} for FigureAgent evaluation."
            chart_entries.append({
                "paper_id": normalized["paper_id"],
                "paper_title": normalized["paper_title"],
                "evidence_id": evidence["evidence_id"],
                "source_csv": relative_to_base(source_path, path_base),
                "eval_csv": evidence["path"],
                "columns": columns,
                "row_count": row_count,
                "paragraph_ref": evidence.get("paragraph_ref"),
                "description": evidence.get("description"),
                "sha256": evidence["sha256"],
            })
        elif evidence.get("path"):
            evidence["path"] = relative_to_base(resolve_project_path(evidence["path"]), path_base)
            evidence.setdefault("sha256", sha256(resolve_project_path(evidence["path"])))

    return normalized


def run_smoke(output_root: Path, contexts_dir: Path, path_base: Path) -> dict[str, Any]:
    smoke_root = output_root / "smoke_artifacts"
    smoke_root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for context_path in sorted(contexts_dir.glob("*_context.json")):
        paper_id = context_path.name.removesuffix("_context.json")
        artifact_root = smoke_root / paper_id
        result_path = smoke_root / f"{paper_id}_result.json"
        env = os.environ.copy()
        env["FIGURE_AGENT_ARTIFACT_ROOT"] = str(artifact_root)
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(PROJECT_ROOT) if not existing_pythonpath else f"{PROJECT_ROOT}{os.pathsep}{existing_pythonpath}"
        command = [sys.executable, "-m", "figure_agent", "run", relative_to_base(context_path, path_base), "--output", str(result_path)]
        completed = subprocess.run(command, cwd=path_base, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        result = read_json(result_path) if result_path.exists() else None
        entries.append({
            "paper_id": paper_id,
            "context_path": relative_to_base(context_path, path_base),
            "artifact_root": str(artifact_root),
            "result_path": str(result_path),
            "returncode": completed.returncode,
            "status": result.get("status") if isinstance(result, dict) else "failed",
            "stderr_tail": completed.stderr[-1200:],
        })
    return {
        "status": "passed" if all(item["returncode"] == 0 and item["status"] == "completed" for item in entries) else "failed",
        "runs": entries,
    }


def paper_id_from_file(filename: str) -> str:
    stem = Path(filename).stem
    aliases = {
        "neurips2017_attention_is_all_you_need": "neurips2017_transformer",
    }
    return aliases.get(stem, stem)


def inspect_csv(path: Path) -> tuple[list[str], int]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), sum(1 for _ in reader)


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_project_path(path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def project_relative(path: Path) -> str:
    return relative_to_base(path, PROJECT_ROOT)


def relative_to_base(path: Path, base: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(base.resolve()))
    except ValueError:
        return str(resolved)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
