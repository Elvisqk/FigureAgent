from __future__ import annotations

import unittest
from unittest.mock import patch

from figure_agent.request_builder import FigureRequestBuilder


class RequestBuilderEnhancementTest(unittest.TestCase):
    def test_infers_chart_mappings_diagram_structure_and_figure_text(self) -> None:
        with patch.dict("os.environ", {"FIGURE_AGENT_LLM_ENABLED": "0"}):
            bundle = FigureRequestBuilder().build({
                "paper_id": "builder_enhancement_demo",
                "paper_title": "Builder Enhancement Demo",
                "target_stage": "experiment_analysis",
                "section_plan": [],
                "style_profile": "academic_default",
                "output_formats": ["png", "pdf"],
                "max_revision_rounds": 2,
                "figure_title": "Automatically Built Figure Requests",
                "figure_subtitle": "RequestBuilder should infer chart mappings and structured diagrams.",
                "figure_notes": ["Generated from a ResearchFigureContext fixture."],
                "figure_footer": "Builder regression fixture.",
                "analysis_claims": [
                    {
                        "claim_id": "method_dataset_claim",
                        "text": "The heatmap ranking pattern differs across datasets and methods.",
                        "target_section": "Experiments/Cross-Dataset Comparison",
                        "importance": "high",
                        "evidence_ids": ["ev_method_dataset_heatmap"],
                    },
                    {
                        "claim_id": "training_curve_claim",
                        "text": "FigureAgent shows a faster score trajectory over optimization steps than the baseline.",
                        "target_section": "Experiments/Training Dynamics",
                        "importance": "medium",
                        "evidence_ids": ["ev_training_curves"],
                    },
                    {
                        "claim_id": "component_scaling_claim",
                        "text": "Compare seven component contributions in a compact chart.",
                        "target_section": "Experiments/Component Scaling",
                        "importance": "medium",
                        "evidence_ids": ["ev_component_scaling"],
                    },
                ],
                "method_summaries": [
                    {
                        "summary_id": "parallel_workflow_summary",
                        "text": "Research question -> Context intake -> parallel retrieval branch -> profiling branch -> analysis branch -> Evidence fusion -> Critic gate -> Final package -> feedback revise if failed",
                        "target_section": "Method/Parallel Workflow",
                        "importance": "high",
                        "suggested_diagram_type": "agent_workflow",
                        "evidence_ids": ["ev_parallel_workflow_text"],
                    }
                ],
                "evidence_catalog": [
                    {
                        "evidence_id": "ev_method_dataset_heatmap",
                        "kind": "table_file",
                        "path": "test/data/method_dataset_heatmap.csv",
                    },
                    {
                        "evidence_id": "ev_training_curves",
                        "kind": "table_file",
                        "path": "test/data/training_curves.csv",
                    },
                    {
                        "evidence_id": "ev_component_scaling",
                        "kind": "table_file",
                        "path": "test/data/component_scaling_7bar.csv",
                    },
                    {
                        "evidence_id": "ev_parallel_workflow_text",
                        "kind": "text_block",
                        "content": "Research question -> Context intake -> parallel retrieval branch -> profiling branch -> analysis branch -> Evidence fusion -> Critic gate -> Final package -> feedback revise if failed",
                    },
                ],
            })

        self.assertEqual(bundle["status"], "ready")
        requests = {request["figure_id"]: request for request in bundle["requests"]}

        heatmap = requests["fig_experiments_cross_dataset_comparison_method_dataset_claim"]
        self.assertEqual(heatmap["context"]["chart_type"], "heatmap")
        self.assertEqual(
            heatmap["context"]["data_mapping"],
            {"x": "dataset", "y": "method", "value": "score_mean"},
        )
        self.assertEqual(heatmap["evidence_refs"][0]["column_selector"], ["dataset", "method", "score_mean"])

        line = requests["fig_experiments_training_dynamics_training_curve_claim"]
        self.assertEqual(line["context"]["chart_type"], "line")
        self.assertEqual(
            line["context"]["data_mapping"],
            {"x": "step", "y": "score_mean", "series": "method", "error_y": "score_std"},
        )

        bar = requests["fig_experiments_component_scaling_component_scaling_claim"]
        self.assertEqual(bar["context"]["chart_type"], "bar")
        self.assertEqual(bar["context"]["data_mapping"], {"x": "category", "y": "value"})
        self.assertEqual(bar["evidence_refs"][0]["column_selector"], ["category", "value"])

        diagram = requests["fig_method_parallel_workflow_parallel_workflow_summary"]
        structure = diagram["context"]["diagram_structure"]
        self.assertEqual(structure["layout_mode"], "branch_merge")
        self.assertEqual(structure["primary_flow"], ["n1", "n2", "n3", "n6", "n7", "n8"])
        self.assertEqual(structure["clusters"][0]["members"], ["n3", "n4", "n5"])
        self.assertIn({"source": "n7", "target": "n2", "kind": "feedback", "label": "revise"}, structure["edges"])

        for request in bundle["requests"]:
            context = request["context"]
            self.assertEqual(context["figure_title"], "Automatically Built Figure Requests")
            self.assertEqual(context["figure_subtitle"], "RequestBuilder should infer chart mappings and structured diagrams.")
            self.assertEqual(context["figure_notes"], ["Generated from a ResearchFigureContext fixture."])
            self.assertEqual(context["figure_footer"], "Builder regression fixture.")


if __name__ == "__main__":
    unittest.main()
