#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ARTIFACT_DIRNAME = "figure_agent_artifacts"


def find_project_root() -> Path | None:
    configured = os.environ.get("FIGURE_AGENT_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()

    search_roots = [Path.cwd(), *Path(__file__).resolve().parents]
    for root in search_roots:
        for candidate in [root, *root.parents]:
            if (candidate / "figure_agent" / "__main__.py").exists():
                return candidate.resolve()
    return None


def main() -> int:
    session_root = Path.cwd().resolve()
    project_root = find_project_root()
    if project_root and not (project_root / "figure_agent").exists():
        print(f"FigureAgent project not found: {project_root}", file=sys.stderr)
        return 2

    python = os.environ.get("FIGURE_AGENT_PYTHON", sys.executable)
    cmd = [python, "-m", "figure_agent", *sys.argv[1:]]
    env = os.environ.copy()
    if project_root:
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(project_root) if not existing else f"{project_root}{os.pathsep}{existing}"
    elif not package_available(python, env):
        print(
            "FigureAgent package is not importable. Install it in the selected Python environment "
            "or set FIGURE_AGENT_PROJECT_ROOT=/path/to/FigureAgent.",
            file=sys.stderr,
        )
        return 2

    env.setdefault("FIGURE_AGENT_ARTIFACT_ROOT", str(session_root / ARTIFACT_DIRNAME))
    return subprocess.call(cmd, cwd=str(session_root), env=env)


def package_available(python: str, env: dict[str, str]) -> bool:
    probe = [
        python,
        "-c",
        "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('figure_agent') else 1)",
    ]
    return subprocess.call(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env) == 0


if __name__ == "__main__":
    raise SystemExit(main())
