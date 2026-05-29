from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from figure_agent import FigureAgent
from figure_agent.tests.fixtures import research_context, write_builder_csvs


class FigureAgentTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="figure-agent-test-"))
        write_builder_csvs(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_runs_context_to_figures(self):
        result = FigureAgent().build(research_context(self.tmpdir), max_figures=1)
        self.assertIn(result["status"], {"completed", "partial_completed"})
        self.assertEqual(len(result["request_bundle"]["requests"]), 1)
        self.assertEqual(len(result["manifests"]), 1)
        self.assertEqual(result["manifests"][0]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
