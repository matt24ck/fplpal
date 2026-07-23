# FPL AI Assistant

Fantasy Premier League assistant: a statistical engine (projections, position ratings, squad/transfer/chip optimization) fronted by a grounded natural-language chat. The LLM never invents numbers — every insight comes from the engine.

- **[PLAN.md](PLAN.md)** — product, modeling, and architecture plan
- **[UI_PLAN.md](UI_PLAN.md)** — interface plan ("The Board")

## Layout

```
engine/     the product's brain — ingest, features, models, optimization (no LLM code)
api/        FastAPI app: REST + chat endpoint + tool definitions   (later)
web/        Next.js frontend                                       (later)
backtest/   historical evaluation harness + grounding evals        (later)
data/       raw API snapshots & historical archives (gitignored)
```

## Quickstart (Windows / PowerShell)

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Pull and archive a snapshot of the live FPL API
python -m engine.ingest.snapshot
```

Snapshots land in `data/snapshots/<endpoint>/<utc-timestamp>.json.gz`. Every API pull is archived raw so all downstream work is reproducible.
