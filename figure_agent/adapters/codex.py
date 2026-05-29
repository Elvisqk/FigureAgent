from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ARTIFACT_DIRNAME = "figure_agent_artifacts"
ENV_FILENAME = ".figure_agent.env"


@dataclass(frozen=True)
class CodexAdapterConfig:
    session_root: Path
    project_root: Path | None
    python: str
    artifact_root: Path


def main(argv: list[str] | None = None) -> int:
    return run_cli(sys.argv[1:] if argv is None else argv)


def run_cli(argv: list[str]) -> int:
    session_root = Path.cwd().resolve()
    config = build_config(session_root)
    env = build_env(config)
    cmd = [config.python, "-m", "figure_agent", *argv]
    return subprocess.call(cmd, cwd=str(config.session_root), env=env)


def build_config(session_root: Path) -> CodexAdapterConfig:
    project_root = find_project_root(session_root)
    if project_root and not (project_root / "figure_agent").exists():
        raise SystemExit(f"FigureAgent project not found: {project_root}")

    python = os.environ.get("FIGURE_AGENT_PYTHON", sys.executable)
    base_env = os.environ.copy()
    load_dotenv(session_root / ENV_FILENAME, base_env)
    if not project_root and not package_available(python, base_env):
        raise SystemExit(
            "FigureAgent package is not importable. Install it in the selected Python environment "
            "or set FIGURE_AGENT_PROJECT_ROOT=/path/to/FigureAgent."
        )

    artifact_root = Path(base_env.get("FIGURE_AGENT_ARTIFACT_ROOT", str(session_root / ARTIFACT_DIRNAME)))
    return CodexAdapterConfig(
        session_root=session_root,
        project_root=project_root,
        python=python,
        artifact_root=artifact_root,
    )


def build_env(config: CodexAdapterConfig) -> dict[str, str]:
    env = os.environ.copy()
    load_dotenv(config.session_root / ENV_FILENAME, env)
    if config.project_root:
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(config.project_root) if not existing else f"{config.project_root}{os.pathsep}{existing}"
    env.setdefault("FIGURE_AGENT_ARTIFACT_ROOT", str(config.artifact_root))
    return env


def find_project_root(session_root: Path | None = None) -> Path | None:
    configured = os.environ.get("FIGURE_AGENT_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()

    roots = [session_root or Path.cwd(), Path(__file__).resolve()]
    for root in roots:
        start = root if root.is_dir() else root.parent
        for candidate in [start, *start.parents]:
            if (candidate / "figure_agent" / "__main__.py").exists():
                return candidate.resolve()
    return None


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

