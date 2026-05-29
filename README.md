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

Manual black-box test cases live under `test/`. Inputs are in `test/requests/`, evidence CSVs are in
`test/data/`, and all generated outputs are written to `test/artifacts/`:

```bash
bash test/run_all_requests.sh
bash test/run_request.sh test/requests/chart_line_training_curve.json
```
