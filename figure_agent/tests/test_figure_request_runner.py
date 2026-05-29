from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from figure_agent.figure_request_runner import FigureRequestRunner
from figure_agent.tests.fixtures import chart_request, diagram_request, write_chart_csv


class FigureRequestRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="figure-agent-runner-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_chart_request_completes(self):
        request = chart_request(write_chart_csv(self.tmpdir))
        manifest = FigureRequestRunner().run(request)
        self.assertEqual(manifest["status"], "completed")
        self.assertGreaterEqual(len(manifest["attempt_history"]), 1)
        for output in manifest["render_outputs"]:
            self.assertTrue(Path(output).exists(), output)

    def test_diagram_request_completes(self):
        manifest = FigureRequestRunner().run(diagram_request())
        self.assertEqual(manifest["status"], "completed")
        self.assertTrue(any(output.endswith(".svg") for output in manifest["render_outputs"]))


if __name__ == "__main__":
    unittest.main()
