from __future__ import annotations

from pathlib import Path
from typing import Any


def write_chart_csv(directory: Path) -> Path:
    path = directory / "main_results.csv"
    path.write_text(
        "\n".join([
            "dataset,method,score_mean,score_std",
            "Dataset-1,Method A,0.91,0.02",
            "Dataset-1,Method B,0.86,0.03",
            "Dataset-2,Method A,0.88,0.02",
            "Dataset-2,Method B,0.81,0.04",
            "Dataset-3,Method A,0.84,0.03",
            "Dataset-3,Method B,0.79,0.05",
        ]),
        encoding="utf-8",
    )
    return path


def chart_request(csv_path: Path) -> dict[str, Any]:
    return {
        "request_id": "figreq_chart_test",
        "paper_id": "paper_test",
        "figure_id": "fig_chart_test",
        "figure_kind": "chart",
        "goal": "Compare methods across datasets with standard deviation.",
        "target_section": "Experiments/Overall Performance",
        "context": {
            "result_summary": "Method A performs best across all datasets.",
            "method_summary": None,
            "style_profile": "academic_default",
            "output_formats": ["png", "pdf"],
            "max_revision_rounds": 2,
            "chart_type": "grouped_bar",
        },
        "evidence_refs": [
            {
                "evidence_id": "ev_results_table",
                "kind": "table_file",
                "path": str(csv_path),
                "sheet": None,
                "table_name": None,
                "row_selector": None,
                "column_selector": None,
                "paragraph_ref": None,
                "sha256": None,
            }
        ],
    }


def diagram_request(method_summary: str | None = None, *, figure_id: str = "fig_diagram_test") -> dict[str, Any]:
    summary = method_summary or "FigureRequest -> Planner -> EvidenceBinder -> SpecGenerator -> Render MCP -> Critic -> Repairer -> Integrator"
    return {
        "request_id": f"req_{figure_id}",
        "paper_id": "paper_test",
        "figure_id": figure_id,
        "figure_kind": "diagram",
        "goal": "Summarize the FigureAgent pipeline from user request to final paper asset.",
        "target_section": "Method/FigureAgent",
        "context": {
            "result_summary": None,
            "method_summary": summary,
            "style_profile": "academic_default",
            "output_formats": ["svg", "png"],
            "max_revision_rounds": 2,
            "diagram_type": "pipeline",
        },
        "evidence_refs": [
            {
                "evidence_id": "ev_method_summary",
                "kind": "text_block",
                "path": None,
                "content": summary,
                "sheet": None,
                "table_name": None,
                "row_selector": None,
                "column_selector": None,
                "paragraph_ref": None,
                "sha256": None,
            }
        ],
    }


def research_context(data_dir: Path | None = None) -> dict[str, Any]:
    apgr_path = str(data_dir / "router_apgr_selected.csv") if data_dir else None
    tradeoff_path = str(data_dir / "router_tradeoff_scatter.csv") if data_dir else None
    return {
        "paper_id": "test_router_demo",
        "paper_title": "Heterogeneous Model Routing Test Context",
        "target_stage": "experiment_analysis",
        "section_plan": [
            {
                "section_id": "method_framework",
                "title": "Method/Router Framework",
                "expected_figures": ["router_framework_diagram"],
            },
            {
                "section_id": "experiments_apgr",
                "title": "Experiments/APGR Comparison",
                "expected_figures": ["apgr_grouped_bar", "tradeoff_scatter"],
            },
        ],
        "analysis_claims": [
            {
                "claim_id": "claim_apgr_selected_routers",
                "text": "Selected routers show different APGR patterns across datasets and methods.",
                "target_section": "Experiments/APGR Comparison",
                "importance": "high",
                "suggested_figure_kind": "chart",
                "suggested_chart_type": "grouped_bar",
                "evidence_ids": ["ev_router_apgr_selected"],
            },
            {
                "claim_id": "claim_cost_apgr_tradeoff",
                "text": "The router results reveal a trade-off between cost proxy CPT and APGR score.",
                "target_section": "Experiments/Cost-Performance Trade-off",
                "importance": "high",
                "suggested_figure_kind": "chart",
                "suggested_chart_type": "scatter",
                "evidence_ids": ["ev_router_tradeoff"],
            },
            {
                "claim_id": "claim_minor_unbacked_observation",
                "text": "A minor observation may be worth mentioning in prose but has no resolved evidence file.",
                "target_section": "Discussion",
                "importance": "low",
                "suggested_figure_kind": "chart",
                "suggested_chart_type": "bar",
                "evidence_ids": [],
            },
        ],
        "method_summaries": [
            {
                "summary_id": "method_router_pipeline",
                "text": "Preference data construction -> Unified preference labels -> Router training -> Threshold-based routing -> Strong or weak model response",
                "target_section": "Method/Router Framework",
                "importance": "high",
                "suggested_diagram_type": "pipeline",
                "evidence_ids": ["ev_method_summary"],
            }
        ],
        "evidence_catalog": [
            {
                "evidence_id": "ev_router_apgr_selected",
                "kind": "table_file",
                "path": apgr_path,
                "description": "Selected router APGR, CPT, and improvement results across benchmarks.",
                "columns": ["dataset", "method", "score_mean", "cpt50_percent", "cpt80_percent"],
                "row_count": 4,
            },
            {
                "evidence_id": "ev_router_tradeoff",
                "kind": "table_file",
                "path": tradeoff_path,
                "description": "Scatter-ready cost and APGR trade-off table.",
                "columns": ["x", "score_mean", "method", "dataset", "cpt80_percent"],
                "row_count": 4,
            },
            {
                "evidence_id": "ev_method_summary",
                "kind": "text_block",
                "path": None,
                "content": "Preference data construction -> Unified preference labels -> Router training -> Threshold-based routing -> Strong or weak model response",
                "paragraph_ref": "Method/Router Framework",
            },
        ],
        "style_profile": "academic_default",
        "output_formats": ["png", "pdf"],
        "max_revision_rounds": 2,
    }


def write_builder_csvs(directory: Path) -> None:
    (directory / "router_apgr_selected.csv").write_text(
        "\n".join([
            "dataset,method,score_mean,cpt50_percent,cpt80_percent",
            "GSM8K,Router A,0.71,40,70",
            "GSM8K,Router B,0.69,35,65",
            "MMLU,Router A,0.64,45,75",
            "MMLU,Router B,0.61,38,68",
        ]),
        encoding="utf-8",
    )
    (directory / "router_tradeoff_scatter.csv").write_text(
        "\n".join([
            "x,score_mean,method,dataset,cpt80_percent",
            "40,0.71,Router A,GSM8K,70",
            "35,0.69,Router B,GSM8K,65",
            "45,0.64,Router A,MMLU,75",
            "38,0.61,Router B,MMLU,68",
        ]),
        encoding="utf-8",
    )
