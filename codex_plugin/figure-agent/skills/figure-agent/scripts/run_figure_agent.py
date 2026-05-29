#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ARTIFACT_DIRNAME = "figure_agent_artifacts"
ENV_FILENAME = ".figure_agent.env"


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
    dotenv_path = session_root / ENV_FILENAME
    project_root = find_project_root()
    if project_root and not (project_root / "figure_agent").exists():
        print(f"FigureAgent project not found: {project_root}", file=sys.stderr)
        return 2

    python = os.environ.get("FIGURE_AGENT_PYTHON", sys.executable)
    cmd = [python, "-m", "figure_agent", *sys.argv[1:]]
    env = os.environ.copy()
    load_dotenv(dotenv_path, env)
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


def load_dotenv(path: Path, env: dict[str, str]) -> None:
    if not path.exists():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            print(f"Ignoring malformed {path.name} line {line_number}: missing '='", file=sys.stderr)
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            print(f"Ignoring malformed {path.name} line {line_number}: empty key", file=sys.stderr)
            continue
        if key in os.environ:
            continue
        env[key] = strip_quotes(value.strip())


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def package_available(python: str, env: dict[str, str]) -> bool:
    probe = [
        python,
        "-c",
        "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('figure_agent') else 1)",
    ]
    return subprocess.call(probe, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env) == 0


if __name__ == "__main__":
    raise SystemExit(main())
