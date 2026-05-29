---
name: figure-agent
description: Use when the user asks Codex to create, render, critique, repair, or manage academic paper figures from research context, FigureRequest JSON, tables, experiment data, charts, diagrams, workflows, or paper-ready visual assets using the local FigureAgent Python package.
---

# FigureAgent

Use the local FigureAgent package to turn research context or FigureRequest JSON into paper-ready figures.

## When To Use

Use this skill when the user asks to:

- generate a paper figure, chart, diagram, workflow, or figure asset;
- convert research context into figure requests;
- render a `FigureRequest` into PNG/PDF/SVG outputs;
- inspect, critique, repair, or locate FigureAgent artifacts;
- run FigureAgent with an OpenAI-compatible model.

## Local Package

The Python package is `figure_agent`. Prefer the `codex_env` environment when available.

Main commands:

```bash
conda run -n codex_env python -m figure_agent build-requests CONTEXT.json --output BUNDLE.json --requests-dir REQUESTS_DIR
conda run -n codex_env python -m figure_agent run-request REQUEST.json
conda run -n codex_env python -m figure_agent run CONTEXT.json --output RESULT.json
```

When using the plugin helper script, the wrapper locates the package from `FIGURE_AGENT_PROJECT_ROOT`, the current working directory, the script path, or an installed `figure_agent` package.

If the user has not set `FIGURE_AGENT_ARTIFACT_ROOT`, plugin runs write all outputs under the current session directory:

```text
./figure_agent_artifacts/
```

Important subdirectories:

- `figures/`: final rendered images such as PNG, PDF, SVG.
- `specs/`: intermediate chart or diagram specs.
- `reports/`: render, caption, critic, repair, and LLM trace reports.
- `manifests/`: final figure manifests.
- `requests/`: copied or generated FigureRequest files.

## Helper Script

Use `scripts/run_figure_agent.py` from this skill when a stable wrapper is easier than spelling out the module command:

```bash
python /Users/zyq/plugins/figure-agent/skills/figure-agent/scripts/run_figure_agent.py run-request REQUEST.json
python /Users/zyq/plugins/figure-agent/skills/figure-agent/scripts/run_figure_agent.py run CONTEXT.json --output RESULT.json
python /Users/zyq/plugins/figure-agent/skills/figure-agent/scripts/run_figure_agent.py build-requests CONTEXT.json --output BUNDLE.json --requests-dir REQUESTS_DIR
```

The helper runs from the current working directory, so relative context, request, and data paths are resolved relative to the user's active Codex session folder.

If the package is not installed and the current directory is not the FigureAgent repository, set:

```bash
FIGURE_AGENT_PROJECT_ROOT=/path/to/FigureAgent
```

## Model Configuration

FigureAgent reads model settings from environment variables:

```bash
FIGURE_AGENT_LLM_ENABLED=1
FIGURE_AGENT_LLM_PROVIDER=openai
FIGURE_AGENT_LLM_BASE_URL=https://api.deepseek.com
FIGURE_AGENT_LLM_MODEL=deepseek-v4-flash
FIGURE_AGENT_LLM_API_KEY=...
```

The helper script also loads a session-local `.figure_agent.env` file before running FigureAgent. Use `.figure_agent.env.example` as the template, then create `.figure_agent.env` in the active session directory for real credentials.

Do not write API keys into repository files, generated requests, manifests, logs, shell history, or `.figure_agent.env.example`. If a network call is needed and sandbox DNS/network fails, request elevated execution rather than silently falling back.

## Workflow

1. Determine whether the user has a full research context or an existing FigureRequest.
2. If they provide context, run `build-requests` or full `run`.
3. If they provide a FigureRequest, run `run-request`.
4. Keep generated artifacts in `./figure_agent_artifacts/` unless the user explicitly sets `FIGURE_AGENT_ARTIFACT_ROOT`.
5. After rendering, report the manifest path, final figure paths, critic result, and relevant trace path.
6. For visual quality questions, inspect the PNG/SVG and the critic report before answering.

## Quality Checks

Before calling work complete, run at least one relevant check:

```bash
conda run -n codex_env python -m unittest discover figure_agent/tests
conda run -n codex_env python -m figure_agent --help
```

For a generated figure, prefer checking the final manifest plus the newest files in `figure_agent_artifacts/figures`.
