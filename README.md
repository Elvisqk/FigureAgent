# FigureAgent

FigureAgent builds paper-ready figures from research context.

The package is in `figure_agent/`. See `figure_agent/README.md` for CLI and Python API usage.

The Codex skill source is in `codex_skill/figure-agent/`. It keeps the preferred usage mode simple:
Codex handles reasoning, planning, and repair; FigureAgent handles deterministic rendering and
artifact management.

Quick checks:

```bash
python -m unittest discover figure_agent/tests
python -m figure_agent --help
```
