---
name: figure-agent
description: Use when the user asks Codex to generate, render, inspect, or repair academic paper figures, charts, diagrams, workflows, FigureRequest JSON, or FigureAgent artifacts using the local FigureAgent renderer.
---

# FigureAgent

Use FigureAgent as a deterministic figure builder. Let Codex do the reasoning; use FigureAgent to build requests, render assets, and collect manifests.

## Default Rule

Do not enable FigureAgent's internal LLM by default. Codex already has the active session model, so prefer this split:

- Codex reads the user's context, decides what figure is needed, and edits or creates `ResearchFigureContext` / `FigureRequest` JSON when useful.
- FigureAgent renders and validates the figure assets.

Only use `FIGURE_AGENT_LLM_*` if the user explicitly asks to test FigureAgent's internal model hooks.

## Commands

Use the skill wrapper from the user's current working directory:

```bash
FIGURE_AGENT_PYTHON=/opt/miniconda3/envs/codex_env/bin/python \
python /Users/zyq/.codex/skills/figure-agent/scripts/run_figure_agent.py run CONTEXT.json --output result.json
```

For a single request:

```bash
FIGURE_AGENT_PYTHON=/opt/miniconda3/envs/codex_env/bin/python \
python /Users/zyq/.codex/skills/figure-agent/scripts/run_figure_agent.py run-request REQUEST.json
```

For request generation only:

```bash
FIGURE_AGENT_PYTHON=/opt/miniconda3/envs/codex_env/bin/python \
python /Users/zyq/.codex/skills/figure-agent/scripts/run_figure_agent.py build-requests CONTEXT.json --output request_bundle.json --requests-dir requests
```

The wrapper runs in the current directory. If it cannot find the package, set:

```bash
FIGURE_AGENT_PROJECT_ROOT=/path/to/FigureAgent
```

If using the repository copy directly before installing the skill, run:

```bash
python /path/to/FigureAgent/codex_skill/figure-agent/scripts/run_figure_agent.py ...
```

## Outputs

Unless `FIGURE_AGENT_ARTIFACT_ROOT` is set, outputs go under:

```text
./figure_agent_artifacts/
```

Report these paths after a run:

- `figure_agent_artifacts/figures/`
- `figure_agent_artifacts/manifests/`
- `figure_agent_artifacts/reports/`
- `result.json` if the command wrote one

## Workflow

1. Inspect the context or request before running when the user asks for quality or correctness.
2. If the context mixes chart and diagram outputs, avoid requesting `pdf` for diagrams; diagrams currently render as `png`/`svg`.
3. Run FigureAgent through the wrapper.
4. Check manifest status and critic reports.
5. If a figure fails, use Codex reasoning to edit the request/context or spec, then rerun.
6. For visual review, inspect the final PNG/SVG plus the critic report before answering.

## Internal LLM Test Mode

Only when explicitly requested, create a session-local `.figure_agent.env` or export:

```bash
FIGURE_AGENT_LLM_ENABLED=1
FIGURE_AGENT_LLM_PROVIDER=openai
FIGURE_AGENT_LLM_BASE_URL=...
FIGURE_AGENT_LLM_MODEL=...
FIGURE_AGENT_LLM_API_KEY=...
```

Do not put real API keys in Git, examples, logs, or final answers.
