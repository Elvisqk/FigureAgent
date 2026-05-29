from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from figure_agent.adapters import codex


class CodexAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="figure-agent-codex-adapter-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_dotenv_preserves_existing_environment(self):
        dotenv = self.tmpdir / ".figure_agent.env"
        dotenv.write_text(
            "\n".join([
                "FIGURE_AGENT_LLM_ENABLED=1",
                "FIGURE_AGENT_LLM_MODEL='test-model'",
                "EXISTING=value-from-file",
            ]),
            encoding="utf-8",
        )
        env = {"EXISTING": "already-set"}
        with patch.dict(os.environ, {"EXISTING": "already-set"}, clear=False):
            codex.load_dotenv(dotenv, env)
        self.assertEqual(env["FIGURE_AGENT_LLM_ENABLED"], "1")
        self.assertEqual(env["FIGURE_AGENT_LLM_MODEL"], "test-model")
        self.assertEqual(env["EXISTING"], "already-set")

    def test_build_env_defaults_artifacts_to_session_directory(self):
        config = codex.CodexAdapterConfig(
            session_root=self.tmpdir,
            project_root=Path("/tmp/project"),
            python="python",
            artifact_root=self.tmpdir / "figure_agent_artifacts",
        )
        env = codex.build_env(config)
        self.assertEqual(env["FIGURE_AGENT_ARTIFACT_ROOT"], str(self.tmpdir / "figure_agent_artifacts"))
        self.assertIn("/tmp/project", env["PYTHONPATH"])

