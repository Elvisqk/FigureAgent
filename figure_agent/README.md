# FigureAgent

FigureAgent separates the pipeline into two explicit stages:

- `request_builder`: builds `FigureRequest` objects from a `ResearchFigureContext`.
- `figure_request_runner`: turns one `FigureRequest` into rendered figure assets and a manifest.

The package-level `FigureAgent` composes both stages and runs the full context-to-figure workflow.

## CLI

Build requests only:

```bash
python -m figure_agent build-requests /path/to/research_figure_context.json --output /path/to/bundle.json
```

Run one request:

```bash
python -m figure_agent run-request /path/to/figure_request.json
```

Run the full workflow:

```bash
python -m figure_agent run /path/to/research_figure_context.json --output /path/to/result.json
```

Artifacts are written under `figure_agent/artifacts` by default. Override this with:

```bash
FIGURE_AGENT_ARTIFACT_ROOT=/path/to/artifacts python -m figure_agent run /path/to/research_figure_context.json
```

## Python API

```python
from figure_agent import FigureAgent
from figure_agent.figure_request_runner import FigureRequestRunner
from figure_agent.request_builder import FigureRequestBuilder

bundle = FigureRequestBuilder().build(research_context)
manifest = FigureRequestRunner().run(bundle["requests"][0])
result = FigureAgent().build(research_context)
```
