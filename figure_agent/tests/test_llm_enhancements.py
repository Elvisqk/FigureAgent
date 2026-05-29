from __future__ import annotations

import unittest
from pathlib import Path

from figure_agent.figure_request_runner.caption_writer import CaptionWriter
from figure_agent.figure_request_runner.diagram_planner import DiagramPlanner
from figure_agent.request_builder.evidence_resolver import EvidenceResolver
from figure_agent.request_builder.opportunity_detector import FigureOpportunityDetector
from figure_agent.tests.fixtures import research_context, write_builder_csvs


class FakeLLMClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def json_completion(self, system_prompt, user_payload):
        self.calls.append((system_prompt, user_payload))
        return self.payload


class LLMEnhancementTest(unittest.TestCase):
    def test_opportunity_detector_uses_llm_candidates(self):
        context = research_context()
        client = FakeLLMClient({
            "candidates": [
                {
                    "candidate_id": "cand_training_curve",
                    "source_type": "analysis_claim",
                    "source_id": "claim_apgr_selected_routers",
                    "figure_kind": "chart",
                    "target_section": "Experiments/APGR Comparison",
                    "goal": "Show APGR as a trend across selected conditions.",
                    "priority": "high",
                    "evidence_ids": ["ev_router_apgr_selected"],
                    "result_summary": "Selected routers show different APGR patterns.",
                    "method_summary": None,
                    "rationale": "A trend-oriented chart is useful for this claim.",
                    "suggested_chart_type": "line",
                    "suggested_diagram_type": None,
                }
            ]
        })
        candidates = FigureOpportunityDetector(llm_client=client).detect(context)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].suggested_chart_type, "line")
        self.assertEqual(candidates[0].source_id, "claim_apgr_selected_routers")

    def test_evidence_resolver_uses_llm_column_selection(self):
        context = research_context()
        candidate = FigureOpportunityDetector(llm_client=FakeLLMClient(None)).detect(context)[0]
        client = FakeLLMClient({
            "evidence_refs": [
                {
                    "evidence_id": "ev_router_apgr_selected",
                    "kind": "table_file",
                    "path": None,
                    "content": None,
                    "sheet": None,
                    "table_name": None,
                    "row_selector": None,
                    "column_selector": ["dataset", "method", "score_mean"],
                    "paragraph_ref": "Experiments/APGR Comparison",
                    "sha256": None,
                }
            ]
        })
        resolved, skip = EvidenceResolver(llm_client=client).resolve(context, candidate)
        self.assertIsNone(skip)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.evidence_refs[0]["column_selector"], ["dataset", "method", "score_mean"])

    def test_caption_writer_uses_llm_caption(self):
        client = FakeLLMClient({
            "request_id": "figreq_demo",
            "figure_id": "fig_demo",
            "short_caption": "Validation accuracy over epochs.",
            "full_caption": "Validation accuracy over training epochs for the baseline and proposed methods.",
            "claim_alignment": "The caption only describes the mapped epoch, method, and accuracy fields.",
        })
        caption = CaptionWriter(llm_client=client).build(
            request={"request_id": "figreq_demo", "figure_id": "fig_demo", "target_section": "Experiments"},
            intent={"claim": "The proposed method improves validation accuracy."},
            spec={
                "figure_kind": "chart",
                "chart_type": "line",
                "data_mapping": {"x": "epoch", "y": "accuracy", "series": "method"},
            },
            render_result={"attempt": 1, "status": "success", "output_files": [], "metadata": {}, "error": None},
        )
        self.assertEqual(caption["short_caption"], "Validation accuracy over epochs.")
        self.assertEqual(client.calls[0][1]["figure_spec"]["chart_type"], "line")

    def test_diagram_planner_uses_llm_plan(self):
        client = FakeLLMClient({
            "request_id": "figreq_demo",
            "figure_id": "fig_demo",
            "diagram_type": "agent_workflow",
            "layout_mode": "grid",
            "nodes": [
                {"id": "n1", "label": "Input", "role": "input", "group": None},
                {"id": "n2", "label": "Parallel branch A", "role": "process", "group": "parallel_branches"},
                {"id": "n3", "label": "Parallel branch B", "role": "process", "group": "parallel_branches"},
                {"id": "n4", "label": "Quality gate", "role": "decision", "group": None},
            ],
            "edges": [
                {"source": "n1", "target": "n2", "kind": "primary", "label": None},
                {"source": "n1", "target": "n3", "kind": "secondary", "label": "branch"},
                {"source": "n2", "target": "n4", "kind": "primary", "label": None},
                {"source": "n4", "target": "n2", "kind": "feedback", "label": "if failed"},
            ],
            "clusters": [
                {"cluster_id": "cluster_parallel", "label": "Parallel Analysis", "role": "group", "members": ["n2", "n3"]}
            ],
            "lanes": [],
            "primary_flow": ["n1", "n2", "n4"],
            "routing_hints": {"prefer_orthogonal_edges": True, "separate_primary_and_secondary_edges": True},
            "label_policy": {"max_chars_per_line": 16, "max_lines_per_node": 3},
        })
        plan = DiagramPlanner(llm_client=client).plan(
            request={
                "request_id": "figreq_demo",
                "figure_id": "fig_demo",
                "goal": "Show branch and loop workflow.",
                "target_section": "Method",
                "context": {"method_summary": "Input -> parallel branch A and branch B -> Quality gate -> loop back to branch A"},
                "evidence_refs": [{"content": "Input -> parallel branch A and branch B -> Quality gate -> loop back to branch A"}],
            },
            bound_intent={"recommended_visualization": "agent_workflow", "claim": "Show branch and loop workflow."},
        )
        self.assertEqual(plan["layout_mode"], "grid")
        self.assertTrue(any(edge["kind"] == "feedback" for edge in plan["edges"]))
        self.assertEqual(plan["clusters"][0]["label"], "Parallel Analysis")


if __name__ == "__main__":
    unittest.main()
