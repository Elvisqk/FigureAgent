#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def bootstrap_project_path() -> None:
    configured = os.environ.get("FIGURE_AGENT_PROJECT_ROOT")
    roots = [Path(configured).expanduser()] if configured else []
    roots.extend([Path.cwd(), *Path(__file__).resolve().parents])
    for root in roots:
        for candidate in [root, *root.parents]:
            if (candidate / "figure_agent" / "adapters" / "codex.py").exists():
                sys.path.insert(0, str(candidate.resolve()))
                return


bootstrap_project_path()

from figure_agent.adapters.codex import main


if __name__ == "__main__":
    raise SystemExit(main())
