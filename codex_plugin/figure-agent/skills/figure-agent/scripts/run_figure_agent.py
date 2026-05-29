#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("FIGURE_AGENT_PROJECT_ROOT", "/Users/zyq/Documents/projects/agent"))


def main() -> int:
    if not (PROJECT_ROOT / "figure_agent").exists():
        print(f"FigureAgent project not found: {PROJECT_ROOT}", file=sys.stderr)
        return 2

    python = os.environ.get("FIGURE_AGENT_PYTHON", sys.executable)
    cmd = [python, "-m", "figure_agent", *sys.argv[1:]]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(PROJECT_ROOT) if not existing else f"{PROJECT_ROOT}{os.pathsep}{existing}"
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
