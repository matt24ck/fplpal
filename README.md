# FPL Pal

Fantasy Premier League assistant — your pal who does the maths: a statistical engine (projections, position ratings, squad/transfer/chip optimization) fronted by a grounded natural-language chat. The LLM never invents numbers — every insight comes from the engine. The pitch view at the heart of the UI is "The Board".

- **[PLAN.md](PLAN.md)** — product, modeling, and architecture plan
- **[UI_PLAN.md](UI_PLAN.md)** — interface plan ("The Board")
- **[BUILDLOG.md](BUILDLOG.md)** — what has been built, step by step
- **[TODO.md](TODO.md)** — remaining development, in priority order

## Layout

```
engine/     the product's brain — ingest, features, models, optimization (no LLM code)
api/        FastAPI app: REST + chat endpoint + tool definitions
web/        Next.js frontend ("The Board")
backtest/   historical evaluation harness + grounding evals
data/       raw API snapshots & historical archives (gitignored)
```

## Quickstart (Windows / PowerShell)

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Pull and archive a snapshot of the live FPL API
python -m engine.ingest.snapshot

# Verify season config against the live game (squad/chips/transfers rules)
python -m engine.config.verify

# Refresh live projections, ratings, and the optimal draft from snapshots
python -m engine.pipeline

# Serve the API (REST + grounded chat at POST /chat; chat needs ANTHROPIC_API_KEY)
# Gated endpoints (/chat, /squad/optimize) verify Clerk sessions — set CLERK_ISSUER
# in .env (Clerk dashboard → Frontend API URL), or AUTH_DISABLED=1 to skip auth locally
uvicorn api.app:app --reload

# Grounding evals for the chat layer (needs ANTHROPIC_API_KEY)
python -m backtest.grounding_evals
```

## Frontend (web/)

```powershell
cd web
npm install
copy .env.local.example .env.local   # then paste your Clerk dev keys into it
npm run dev        # http://localhost:3000 — expects the API on 127.0.0.1:8000
```

The Next.js app proxies `/api/engine/*` to the FastAPI server (override with
`ENGINE_API_URL`), so the browser talks to one origin. Production: `npm run
build` then `npm run start`.

Accounts are Clerk (Google one-tap). Signed-out visitors get the builder,
rate-my-draft, Players, Fixtures, and About; chatting with Pal, the Planner,
and optimizer runs require sign-in — enforced by the API, not just the UI.

Snapshots land in `data/snapshots/<endpoint>/<utc-timestamp>.json.gz`. Every API pull is archived raw so all downstream work is reproducible. Pipeline output (per-fixture and per-GW projections, ratings) lands in `data/live/` with provenance columns.

For the hourly snapshot cadence the plan calls for, register a scheduled task (adjust the repo path):

```powershell
schtasks /Create /SC HOURLY /TN "FPL Snapshot" /TR "C:\Users\mcalk\Work\fpl_ai_site\.venv\Scripts\python.exe -m engine.ingest.snapshot" /ST 00:05
```

Each model layer is self-evaluating against a 2025-26 holdout — run any of `python -m engine.models.team_strength`, `...minutes`, `...event_rates`, `...points`, `...ratings`, or `python -m engine.optimize.squad`.
