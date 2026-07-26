# Deployment — Vercel (web) + Railway (engine)

The split: **Railway** runs the FastAPI engine with a persistent volume and the
scheduled jobs (hourly snapshot, nightly pipeline) in-process via APScheduler.
**Vercel** serves the Next.js app; REST goes through its same-origin rewrite to
Railway, chat SSE goes browser→Railway directly (Vercel's rewrite proxy times
out on long streams).

Everything repo-side is already in place: `railway.json` (start command +
`/health` healthcheck), `.python-version`, the jobs module (`api/jobs.py`,
enabled by `JOBS_ENABLED=1`), env-driven CORS, a per-IP chat rate limit, and
the committed rating-weights cache (`data/models/ratings_weights.json`) that
saves the first boot from a very slow refit.

## 0. Push the repo to GitHub

Both platforms deploy from the repo. `.env`, `data/` (except the weights
cache), and `web/node_modules` are gitignored — nothing secret or heavy ships.

## 1. Railway — the engine service

1. **New Project → Deploy from GitHub repo**, pick this repo. Root directory:
   repo root (default). `railway.json` supplies the start command:
   `uvicorn api.app:app --host 0.0.0.0 --port $PORT`.
2. **Attach a Volume** to the service, mount path **`/app/data`**. (Nixpacks
   builds run the app from `/app`, so this is the repo's `data/` dir. ~1 GB
   headroom is plenty for a season of hourly snapshots.)
3. **Variables**:
   | Variable | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | your key |
   | `JOBS_ENABLED` | `1` |
   | `CORS_ORIGINS` | `https://<your-app>.vercel.app,http://localhost:3000` |
   | `CHAT_RATE_LIMIT_PER_HOUR` | optional, default `30` per IP |
4. **Settings → Networking → Generate Domain** — note the public URL.
5. Deploy. **First boot seeds the empty volume** (one-time, ~10–20 min):
   historical download (~45 MB) → feature builds → first snapshot → first
   pipeline. `/health` returns `{"ok": false, "status": "…seeding…"}` while
   this runs and flips to `ok: true` with provenance when done — watch the
   deploy logs (`jobs:` lines). Subsequent boots skip all of it.
6. From then on the schedule runs in-process: snapshot hourly at :05 UTC,
   pipeline nightly at 02:30 UTC followed by a live-store reload. (Times are
   constants at the top of `api/jobs.py`.)

Service sizing: the API idles tiny, but give it ~2 GB RAM headroom for the
nightly model refit. Keep it at **one replica / one uvicorn worker** — the
in-memory store, rate limiter, and scheduler all assume a single process.

## 2. Vercel — the web app

1. **Import the repo**; set **Root Directory = `web`**. Framework auto-detects
   Next.js; default build command is fine.
2. **Environment variables** (both build-time):
   | Variable | Value |
   |---|---|
   | `ENGINE_API_URL` | `https://<railway-domain>` (REST via rewrite) |
   | `NEXT_PUBLIC_CHAT_API_URL` | `https://<railway-domain>` (chat SSE, direct) |
3. Deploy. If the Vercel domain wasn't known when you set `CORS_ORIGINS` on
   Railway, update it now — chat is the only path that needs CORS.

## 3. Verify (in order)

1. `https://<railway-domain>/health` → `ok: true` + provenance timestamps.
2. Vercel site loads; status bar shows the season/GW window (proves the
   rewrite works).
3. Players / Fixtures pages populate (proves live parquets serve).
4. Ask the chat something ("How is Haaland rated?") — streams, tool cards
   render (proves direct SSE + CORS + key).
5. Next day: status bar's "computed" timestamp has advanced (proves the
   nightly pipeline + reload ran).

## Notes & gotchas

- **The volume is the system of record** — snapshots can't be backfilled. If
  the service is ever recreated, re-attach the same volume (or accept a
  re-seed with a gap in the archive).
- **Redeploys don't touch the volume**; seeding is skipped when data exists.
- **Local dev is unchanged**: `JOBS_ENABLED` unset means no jobs; run
  snapshot/pipeline manually as before.
- Rating weights: to refresh the committed cache, run
  `python -m engine.pipeline --refit-ratings` locally and commit the updated
  `data/models/ratings_weights.json`.
- The chat rate limit is per-IP per-hour in one process's memory — enough to
  cap abuse at MVP scale; revisit (shared store) if the service ever scales
  beyond one replica.
