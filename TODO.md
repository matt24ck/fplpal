# Remaining Development

What's left to build, in priority order. Companion to [PLAN.md](PLAN.md) (the design), [UI_PLAN.md](UI_PLAN.md) (the interface spec), and [BUILDLOG.md](BUILDLOG.md) (what exists). Status as of 23 July 2026 — engine, API, grounded chat, and the full GW1-scope UI are built and verified; the GW1 deadline is **Fri 21 Aug 2026, 18:30 UTC**.

## 1. Before GW1 launch (blocking)

- [ ] **Verify the scoring table against the live game** — compare `engine/config/seasons/2026-27.json` `"scoring"` block against the official 2026/27 rules page, correct any changes, flip `verified_against_game: true`, rerun `python -m engine.pipeline` if values changed. (Owner: manual check — Matthew.)
- [ ] **Deploy** — everything currently runs on localhost. Vercel (web) + Railway (FastAPI + jobs; existing Railway account). Needs: separate Railway service with a Volume mounted at `data/` (~1 GB/month growth), one-time historical seed on the volume, hourly snapshot + nightly pipeline as Railway cron (decision: no local scheduled tasks — jobs start at deployment), `ANTHROPIC_API_KEY` as a Railway env var, `ENGINE_API_URL` on the Vercel build, CORS origins from env (currently hardcoded localhost), and browser→Railway direct for `/chat` SSE (Vercel rewrite timeouts). Until then: run `python -m engine.ingest.snapshot` manually now and then, and before any `engine.pipeline` refresh. **Deployed 26 Jul 2026** — engine on Railway, web at fplpal-eight.vercel.app; remaining: buy **fplpal.com** (product name: FPL Pal; the pitch view stays "The Board"; Twitter @TheBoardFPL), add it as the Vercel custom domain, and append `https://fplpal.com,https://www.fplpal.com` to Railway's `CORS_ORIGINS`.
- [ ] **Cost & abuse controls on `/chat`** — per-IP rate limiting and a daily spend cap before the endpoint is public (PLAN §10). Prompt caching is already in place.
- [ ] **CI** — run the grounding evals on every system-prompt/tool change, plus `next build` + ruff as the minimum gate (PLAN §8 calls for evals in CI; today they're manual).

## 2. In-season, first weeks (time-triggered)

- [ ] **Played-GW ingest** (needed by GW2) — post-match job: `event/{gw}/live` + `element-summary` snapshots appended to the canonical player-GW table so the models retrain on current-season data. The pipeline currently builds only *future* rows; model history ends at 2025/26.
- [ ] **Real team import** (works only after the GW1 deadline — picks are public then) — `entry/{id}/picks` ingest → squad, bank, free transfers, chips used; replace the My Team draft-only path; the UI's team-ID onboarding field already stores the ID.
- [ ] **Multi-GW transfer planner** (by GW2, PLAN §5) — multi-period MILP over 5–8 GWs: FT banking (the `min(5, ft−used+1)` state needs linearizing), −4 hits, sell-price rules, later-week discounting. **Unblocked now** — inputs (multi-GW projections) and solver exist; only the *product wiring* waits on post-GW1 team import. Validation harness exists: the bot-manager sim (26 Jul, gitignored `test/bot_sim.py`) replayed 2025/26 with a myopic greedy policy for **2,020 pts** (real average 1,895; no chips, news-blind) — acceptance test: the planner must beat it. New engine module + `optimize_transfers` tool + REST endpoint + Planner UI transfer cards ("−4 now, +6.2 expected over 4 GWs", alternatives with deltas). Backtest detail: needs a `replay_season` variant with projections frozen at the decision date.
- [ ] **Chip advisor** (~GW4, PLAN §5) — per-chip EV across remaining GWs, DGW/BGW-aware. Engine module + `chip_advice` tool (replace the honest stub) + chip timeline UI (UI_PLAN §5) + one-line recommendations on the My Team chips card.
- [ ] **Full multi-season backtest harness** — replay ≥3 seasons (train-before-evaluate), the metric suite from PLAN §8, refit rating weights across seasons (NNLS currently fit on half of 2025/26), and tune the rate-decay half-life (the Salah-decline miss). The compressed one-season pre-launch gate was the accepted quality debt.
- [ ] **Live accuracy monitoring** — projections vs. realized per GW, published on the site (credibility surface).

## 3. Engine improvements (opportunistic)

- [ ] **Prior-vs-observed provenance badge** — expose each player's decayed exposure so tools/UI can say "this projection is mostly a price-tier prior" for new signings (deadline-day arrivals, January window). Cheap; very much in the grounding spirit.
- [ ] **Price-change prediction model** — transfer-momentum based; improves transfer-timing advice and enables price-alert features.
- [ ] **Understat/FBref enrichment** (phase 2, check ToS) — shot-level xG blend and, most valuably, European-league priors for new-to-FPL signings (today they start from position × price tier only).
- [ ] **Manual override table for late team news** — press-conference knowledge isn't in any API (PLAN §10 mitigation); a simple overrides file the pipeline reads.
- [ ] **Bot-manager simulation** — a season-long simulated manager following the optimizer + chip advisor; compare vs. average manager and top-10k (PLAN §8).

## 4. UI backlog (UI_PLAN §12 — cut from launch)

- [ ] **Live mode** on the pitch — live points count-up during matches, provisional bonus, played/playing/yet-to-play states. (Depends on played-GW ingest.)
- [ ] **Dark mode** ("evening kickoff") + the CVD-safe alternate difficulty ramp as a setting — tokens are already CSS custom properties, so both are config not rework; re-run the palette validator against the dark surface.
- [ ] **Comparison pinning** — pin up to 3 players side-by-side in the explorer (the chat compare tool exists; the UI surface doesn't).
- [ ] **Ownership overlay** on the pitch + ownership/price-trend charts in the player drawer (data already snapshotted).
- [ ] **Explorer mobile card view** — the spec calls for ranked cards with top-3 sub-scores on phones; currently it's a horizontally scrolling table.
- [ ] **Manual lineup editing** — tap-to-swap XI/bench/captain overrides (drag-and-drop later); today the XI is always the optimizer's.
- [ ] **Richer cross-highlighting** — fixtures matrix and chip timeline as highlight targets; data chips for integer values (currently only decimals/£ to avoid false matches).
- [ ] **Alerts** — injury-flag changes, price changes, deadline reminders (needs accounts or push/email plumbing).
- [ ] **Mini-league views**, player-news integration — later.

## 5. Platform & quality (as it scales)

- [ ] **Accounts / persistence** — accounts shipped 27 Jul 2026 (BUILDLOG §22): Clerk with Google one-tap; chat/planner/optimize are signed-in-only, enforced by FastAPI verifying session JWTs. Postgres persistence shipped same day (BUILDLOG §23): draft + team ID sync per user via `/me/state` (Railway Postgres, `DATABASE_URL`). Remaining: **pricing/billing** (Clerk Billing — the reason Clerk was chosen).
- [ ] **Haiku router for chat** — A/B `claude-haiku-4-5` on single-tool lookups behind the grounding evals; keep Sonnet for multi-step advice (PLAN §6 cost path).
- [ ] **Unit tests** — the engine's module-level holdout evals are strong but there's no fast pytest suite for pure functions (config, shrinkage math, points assembly identities, API tools' name resolution).
- [ ] **Error tracking / uptime monitoring** on API + web once deployed.
