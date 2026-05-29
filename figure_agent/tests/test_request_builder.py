from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from figure_agent.common.validators import validate_payload
from figure_agent.request_builder import FigureRequestBuilder
from figure_agent.tests.fixtures import research_context, write_builder_csvs


ROOT = Path(__file__).resolve().parents[2]


class FigureRequestBuilderTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="figure-agent-builder-test-"))
        write_builder_csvs(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_builds_schema_valid_bundle(self):
        bundle = FigureRequestBuilder().build(research_context(self.tmpdir))
        validate_payload(bundle, "figure_request_bundle.schema.json")
        self.assertEqual(bundle["status"], "ready")
        self.assertEqual(len(bundle["requests"]), 3)
        for request in bundle["requests"]:
            validate_payload(request, "figure_request.schema.json")

    def test_cli_writes_bundle_and_split_requests(self):
        import subprocess
        import sys

        context = self.tmpdir / "research_context.json"
        context.write_text(json.dumps(research_context(self.tmpdir), indent=2), encoding="utf-8")
        output = self.tmpdir / "bundle.json"
        requests_dir = self.tmpdir / "requests"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "figure_agent.request_builder",
                str(context),
                "--output",
                str(output),
                "--requests-dir",
                str(requests_dir),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.exists())
        self.assertEqual(len(list(requests_dir.glob("*.json"))), 3)


if __name__ == "__main__":
    unittest.main()
