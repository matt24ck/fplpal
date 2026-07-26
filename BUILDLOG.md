# Build Log

Short record of what was implemented at each step, in order. Companion to [PLAN.md](PLAN.md) (the "what and why") — this is the "what actually got built".

## 1. Plans

**[PLAN.md](PLAN.md)** — product and architecture plan: bottom-up modeling stack (team strength → minutes → event rates → points assembly), position-specific rating systems, MILP optimization, and a grounded chat layer where the LLM only narrates engine output. Roadmap compressed around the hard mid-August GW1 deadline. **[UI_PLAN.md](UI_PLAN.md)** — interface plan around "The Board": the pitch view as the primary analytical instrument, chips as status card + season timeline, chat that cross-highlights the data views it cites.

## 2. Project scaffold

`pyproject.toml` (Python 3.12+, httpx/pydantic/pandas/pyarrow/scipy, ruff + pytest), venv, `.gitignore` (data and build artifacts excluded), `README.md` quickstart, and the `engine/` package layout separating ingest / config / features / models.

## 3. Season rules config — `engine/config/`

All FPL game rules as versioned, pydantic-validated JSON per season (`seasons/2026-27.json`): scoring table (including 2025/26's defensive-contribution points), squad composition, formation bounds, transfer banking, chip counts. Nothing downstream hardcodes a rule. Flagged `verified_against_game: false` until it can be checked against the launched 2026/27 game.

## 4. FPL API client — `engine/ingest/fpl_api.py`

Thin httpx client for the public FPL endpoints (bootstrap-static, fixtures, element-summary, live GW, entry/picks, set-piece notes) with retry on transient failures and a dedicated `MaintenanceError` for the API's 503 "Game Updating" state. No response validation here by design — bytes get archived first, parsed later.

## 5. Snapshot archive — `engine/ingest/snapshot.py`

Every API pull saved as timestamped gzipped JSON under `data/snapshots/<endpoint>/`, so all downstream tables are rebuildable and API schema drift can never lose data. Includes a `--watch-minutes` mode that polls until the API comes back and archives the first snapshot — set up to catch the 2026/27 launch moment. Running it revealed the API is currently in summer-rollover maintenance.

## 6. Historical downloader — `engine/ingest/historical.py`

Fetches the vaastav community archive (the only per-GW source for past seasons — the official API keeps per-GW data for the current season only) over plain HTTPS, idempotently: 10 seasons (2016/17–2025/26) of `merged_gw.csv`, `players_raw.csv`, `teams.csv`, `fixtures.csv`, plus `master_team_list.csv` for early-season team names. ~45 MB total.

## 7. Canonical player-GW table — `engine/features/historical_gw.py`

Normalizes ten drifting CSV schemas into one 253,509-row parquet (one row per player per fixture). Handles: latin-1 encoding and `First_Last`/`Name_123` name formats in early seasons, positions joined from `players_raw` where absent, team identity derived from fixture opponent-pairs for seasons with no team column, assistant-manager rows dropped (2024/25), nullable xG (2022/23+) and defensive-count (2016–19, 2025/26) columns. Validated by coverage checks and by reproducing every season's real top scorer exactly (Salah 303, Haaland 272, Palmer 244, …).

## 8. Match results table — `engine/features/matches.py`

Collapses the player table into one row per match: home/away, final score, kickoff, and per-side team xG (summed player xG). 3,799 matches; every season a complete 380 except one scoreless row in the 2019/20 source data.

## 9. Team-strength model — `engine/models/team_strength.py`

First model of the stack (PLAN.md Layer 1): a Dixon-Coles Poisson model with exponential time decay, fitted by weighted MLE with analytic gradients. The response blends team xG with actual goals where xG exists; a ridge penalty stabilizes the fit; the low-score correction (rho) is fitted in a second stage on real scorelines; `as_of` fitting supports point-in-time backtests; unknown (newly promoted) teams forecast from a low-percentile prior. Outputs per fixture: expected goals both sides, full scoreline grid, clean-sheet probabilities.

**Holdout result** (fit frozen at the start of 2025/26, scored on all 380 matches): clean-sheet Brier 0.1788 vs 0.1901 constant-rate baseline; goal calibration close (2.87 predicted vs 2.75 actual per match); fitted table passes the eye test (Liverpool top attack, Arsenal top defence, home advantage ≈ +16% goals).

## 10. Minutes model — `engine/models/minutes.py`

PLAN.md Layer 2, the highest-leverage component. Three LightGBM models over strictly point-in-time features (shifted rolling and time-decayed start share/minutes, unused streak, rest days, price momentum, prev-season aggregates): a 3-class {unused, cameo, start} classifier, P(60+ | start), and E[minutes | start]; combined into `p_start` / `p_cameo` / `p_60plus` / `e_minutes` per player-fixture. GW1 cold start works by construction — in-season features are NaN and prediction leans on prev-season priors, price, and position, a shape the model also sees in training. Live injury flags (absent from historical data) overlay multiplicatively via `apply_availability`.

Two data findings along the way: the archive's 2022-23 GW1–15 have `starts` erroneously all-zero (repaired by masking any season-GW recording far fewer than 22 starters per fixture), and player names drift across seasons — so FPL's stable `code` was added to the canonical player-GW table (`historical_gw.py`) as the cross-season identity key. That fixed e.g. David Raya's GW1 forecast (name-joined prior missed → p_start 0.57; code-joined → 0.96).

**Holdout result** (trained 2022-23…2024-25, scored on all 29,747 player-fixtures of 2025-26): start Brier 0.0774 vs 0.1030 last-5-start-share baseline; minutes RMSE 21.6 vs 24.7 last-5-average baseline; decile calibration close (worst bin 0.949 predicted vs 0.930 observed); cold-start slice (GW1–5) Brier 0.0950 vs 0.1273. Deps added: lightgbm, scikit-learn.

## 11. Player event rates — `engine/models/event_rates.py`

PLAN.md Layer 3. Strictly pre-match per-90 rates per player-fixture from exponentially time-decayed career sums (grouped by the stable `code`, so rates carry across seasons), shrunk empirical-Bayes style toward position × price-quintile priors: `rate = (decayed_count + k·prior) / (decayed_90s + k)`. Covers attacking (`xg90`/`xa90` with finishing and assist multipliers), defensive-contribution counts (`cbit90`/`cbirt90` → P(threshold) via negative binomial with per-position overdispersion fitted from full-match rows, thresholds from season config), GK saves, cards, rare-event base rates, and "bonus magnetism" (`bps_res90` — per-90 residual vs a per-position BPS-from-events regression). Each stat family keeps its own decayed exposure because coverage differs by era (xG 2022-23+; DC counts 2016-19 and 2025-26 only).

Findings: the archive's `defensive_contribution` column is the raw CBIT/CBIRT count, not points (verified exactly). FPL's assist definition runs far above xA (FWD ~2.5×) — so assist rates shrink toward the position's league assists/xA ratio, which fixed a −30% under-prediction of total assists. The analogous goals/xG position ratios were tried and **reverted**: they didn't generalize on holdout (totals went from +5% to +12% over), so finishing shrinks toward 1 and xG's own scale is trusted.

**Holdout result** (priors fitted before 2025-26, scored on its 11,492 played player-fixtures): P(anytime goal) Brier 0.0663 vs 0.0678 position-prior baseline; P(anytime assist) 0.0685 vs 0.0700; DC-threshold Brier 0.0870 vs 0.1338 position base rate with clean reliability; bonus magnetism persists out-of-sample (r 0.43); rate leaders pass the eye test (Haaland top xG, Cherki/Bruno top xA, Senesi/Mavropanos top DC).

## 12. Points assembly — `engine/models/points.py`

PLAN.md Layer 4: `PointsAssembler` combines the three fitted layers into per-player-fixture expected points, decomposed into named components (appearance, goals, assists, CS, conceded, saves, DC, bonus, cards, other) with a per-row variance estimate for captaincy/ceiling advice. Every scoring value comes from season config. Attacking rates scale by fixture difficulty (λ_fixture / team baseline λ, via new `baseline_lambda`/`league_lambda` on the team model); GK saves scale by opponent attack; saves/DC condition on starting (minutes model now also exposes `e_min_given_start`). Bonus = E[BPS|plays] from the BPS-events regression applied to conditional-on-playing expectations + bonus-magnetism, allocated within each fixture by an exact Plackett-Luce top-3 (O(n²) identity), so match bonus sums to 6. `aggregate_gw` collapses double gameweeks.

Two bugs caught by the eval: feeding the BPS regression *unconditional* expectations handed its intercept to benchwarmers whose weights then exploded through the play-gating division (bonus corr −0.05 → +0.27 after conditioning), and a "normalized remainder" P(3rd) approximation gave weak players more third-place probability than strong ones (replaced with the exact formula). Also diagnosed why naive form narrowly wins all-rows Spearman (0.727 vs 0.721): never-playing players form actual-points tie groups that a hard-0 prediction matches perfectly — breaking form's ties drops it to 0.652. The decision-relevant metrics are unambiguous.

**Holdout result** (2025-26 replayed point-in-time, team strength refit before every GW, 29,747 player-fixtures): total xPts +1.3% of actual; every component total within ~6% of realized; RMSE 1.89 vs 2.13 (last-4 form) and 2.06 (season PPG); played-only rank corr 0.374 vs 0.274/0.290; top-10 overlap 0.336 vs 0.302/0.294. Season xPts leaders are the real elite (Haaland 223 projected / 239 realized); known miss: Salah projected 176 vs 123 realized — the 270-day rate half-life smooths his decline, a knob for the backtest harness.

## 13. Position ratings — `engine/models/ratings.py`

PLAN.md's position rating systems: composite 0-100 ratings from position-specific sub-scores (GKP: clean sheets · saves · bonus · value · minutes; DEF adds attacking threat and DC floor; MID/FWD: attacking · involvement · floor · explosiveness · value · minutes). Sub-scores are percentiles of Layer-4 projections summed over a horizon window (default next 6 GWs — fixture-adjusted and DGW-aware by construction), anchored on the relevant pool (≥45 projected mean minutes) so benchwarmers score near 0 instead of compressing the scale. Headline weights fitted per position by NNLS of realized window points on sub-scores — regression, not hand-tuned — normalized to keep the 0-100 scale. "Involvement" = share of team's projected goal+assist points (proxies focal-player/penalty status until live set-piece notes arrive); "explosiveness" = window projection sigma (ceiling). Also refactored the season replay out of `points.evaluate_holdout` into a reusable `replay_season()`.

**Holdout result** (2025-26 replay; weights fit on first-half windows, scored on second-half): rating-vs-realized rank corr beats raw xPts for GKP (0.45 vs 0.40), MID (0.58 vs 0.57), FWD (0.55 vs 0.53), ties DEF (0.60 vs 0.62). NNLS zeroes some collinear sub-scores (saves for GKP, explosiveness) on this small fit — refitting across seasons is harness work. The GW1 eye test is the headline: top pre-season MID pick was Semenyo (realized 202 points, the season's breakout), FWD Haaland 100, and the DEF sub-score table surfaces exactly the "why" the product promises (van Dijk 91 = CS 99 · DC floor 99 · bonus 98 · minutes 98).

## 14. Squad optimizer — `engine/optimize/squad.py`

PLAN.md §5 at GW1 scope: a MILP (HiGHS via PuLP, CBC fallback) that jointly picks the 15, starting XI, formation, captain, and vice. Objective = XI xPts + captain doubling + a small vice term (P(captain misses)) + bench xPts weighted by position-level autosub likelihood. Constraints all from season config: 2/5/5/3 shape, budget, ≤3 per club, formation bounds. Supports locked/excluded players ("build around X" / "never Y") and a fixed-squad mode — `optimize_lineup` is the "rate my draft" primitive (best XI / captain / bench order from any 15). Solves in ~0.4-1.9s at full-pool scale (~690 candidates). Transfer planner and chip advisor remain in-season deliverables per the roadmap.

**Holdout result** (2025-26 GW1 draft from pre-season projections, realized points over GWs 1-6 with fixed XI + captain, no transfers — symmetric across variants): **model draft 432 pts vs naive last-season-points draft 217 pts**, with the hindsight-optimal upper bound at 528 — the model's pre-season squad doubled the naive drafter and captured 82% of the ceiling. The drafted squad is a credible 2025-26 template (Raya; van Dijk/Gabriel/Tarkowski; Mbeumo/Bruno/Semenyo/Gakpo; Haaland (C), João Pedro), while the naive draft walks into the classic traps (declining Salah as captain, regressing Wood/Wissa). Constraint validation and lineup-mode reproduction both pass in the eval.

---

**Engine complete at GW1 scope.**

## 15. Live bridge — `engine/pipeline.py`, `engine/config/verify.py`

The 2026/27 API went live (checked July 23; GW1 deadline 2026-08-21) and the first snapshots are archived. `engine/config/verify.py` checks every API-verifiable rule against the season config — all 22 pass (budget, squad shape, formation bounds, club limit, banked-transfer cap, chip counts and half-windows); scoring point values aren't in the API and remain a manual check before flipping `verified_against_game`.

`engine/pipeline.py` is the nightly-refresh core: latest bootstrap + fixtures snapshots → future player-fixture rows in the canonical player-GW shape (the exact cold-start shape the models were trained on) → minutes/rates/team-strength → assembly → per-GW projections, position ratings (blend weights cached from a 2025-26 replay fit), and the optimal GW1 draft, written to `data/live/` with provenance columns (`data_snapshot`, `computed_at`). Details that mattered: future-GW features are computed one GW at a time so phantom future rows never pollute each other's history; live status flags overlay minutes (injured/suspended → 0, doubtful → chance-of-playing); team-name drift is aliased ("Ipswich Town" → "Ipswich"); and `strengths_for` now falls back to the promoted prior for *data-starved* teams, not just unknown ones — Hull's last PL data (2016-17) had decayed to ridge-average, which would have flattered them (promoted 2026/27: Coventry, Hull, Ipswich). Holdout evals re-run unchanged after these edits.

First live output (555 players, 84 new-to-league on pure priors, 23 zeroed by flags): the market moves are in — Mbeumo and Semenyo at their new clubs, Bruno Fernandes top projected at £12.0m — and the optimizer produces a £100.0m GW1 draft in ~0.4s.

## 16. API + grounded chat — `api/`, `backtest/grounding_evals.py`

The product backend (PLAN.md §6/§7). `api/data.py` loads the pipeline's `data/live/` parquets (read-only in the request path; on-demand MILP solves are the only compute); `api/tools.py` is the typed tool surface at GW1 scope — get_player, project_points (with component decomposition + ceilings), compare_players, rank_players, get_fixtures (model difficulty), explain_rating, build_squad, rate_my_draft, plus honest not-yet-available stubs for transfer/chip advice — every payload carrying provenance (`data_snapshot`, `computed_at`). `api/app.py` (FastAPI) serves the same functions as REST so UI tables and chat answers can never disagree, plus `POST /chat` streaming SSE. `api/chat.py` runs the Claude tool loop via the SDK's beta tool runner — `claude-sonnet-5` per PLAN §6, `@beta_tool`-typed tools, the grounding contract as a cached system prompt, and `tool_use`/`tool_result` SSE events so the UI can render provenance cards next to the prose. `backtest/grounding_evals.py` is the adversarial suite (guess-baiting, invented players, departed players, engine-vs-general-knowledge, squad requests must route to the MILP) with heuristic trace/text checks.

Findings: name resolution needed whole-token-before-substring matching ("Saka" was hitting Sakamoto), and Mohamed Salah genuinely left the league in summer 2026 — the tools' honest "not in the 2026-27 pool" is exactly the grounded behavior the evals now pin. All REST endpoints verified via TestClient (player cards, decompositions, fixture difficulty, squad solve with locks, draft rating round-trip, 404s and validation). The chat loop and evals are built but **not yet live-tested — no Anthropic credentials in this environment**; first run needs `ANTHROPIC_API_KEY` (then: `python -m backtest.grounding_evals`).

## 17. The Board — `web/` (Next.js UI at GW1 launch scope)

UI_PLAN.md §12's launch list, working end-to-end against the live API. Next.js 15 + React 19 + Tailwind v4 + TanStack Query, hand-scaffolded (no create-next-app); the FastAPI engine is reached through a same-origin rewrite (`/api/engine/*`), so CORS never enters the picture. Three UI-facing endpoints were added to `api/app.py` first — `/meta` (provenance + next deadline from the latest bootstrap snapshot + squad/chip rules from season config, so the client never hardcodes a rule or date), `/explorer` (player table with sub-scores + per-team fixture ticker), `/fixtures-matrix` — all verified via TestClient.

Screens: **My Team** (onboarding with draft/team-ID paths → the pitch board with xPts/fixtures overlays, GW/next-6 horizon toggle, This Week panel with live deadline countdown, chips status card), **Squad Builder** (edit-mode board, budget/rules bar with inline never-silently-blocked violations, position-filtered picker sorted by rating, MILP optimize-around-my-picks, rate-my-draft verdict card with gap-to-optimal and weakest starter), **Players** (position tabs with per-position sub-score columns, sortable, fixture tickers, player drawer: rating dial, sub-score bars, per-GW xPts decomposition, fixture run), **Fixtures** (team × GW matrix on model difficulty), **Planner** (honest pre-season state), **Chat** (desktop rail + mobile center tab: SSE streaming, typed tool cards incl. a mini-pitch for squad solutions with "use as my draft", provenance footers, contextual suggested prompts). Grounding surfaces per UI_PLAN §6: decimal/£ numbers in assistant prose render as **data chips** linked to the tool card they came from, and tool payload player names **cross-highlight on the board** (pulse ring, others dimmed) on hover and on reply completion.

Design system as specced ("tactics room, match day"): §7 tokens as CSS custom properties (`@theme static` — Tailwind v4 prunes vars referenced only from inline styles otherwise, which silently blanked the difficulty ramp until screenshots caught it), Archivo variable-width for hero/chip voices, IBM Plex Mono for all numerals. The dataviz skill's validator was run on every palette: the xPts decomposition palette passes all six checks in its stack-adjacency order (incl. the GK chain), and the difficulty ramp is a diverging pair (per-pole ordinal-validated) kept luminance-monotonic so it survives grayscale; number + color everywhere.

Verified by driving the real app with Playwright (system Edge): optimize → 15 chips on the board → rate verdict → My Team XI with captain/vice badges and bench flags → drawer decomposition → matrix, plus mobile viewports; screenshots eyeballed per the dataviz render-and-look step. That pass caught two real bugs beyond the ramp: 5-across chip rows overlapped enough to paint over the captain badge (chip width now derives from row density), and a missing `ANTHROPIC_API_KEY` killed the chat stream with no event because the SDK raises `TypeError`, not `APIError` (`chat_stream` now catches broadly and emits the SSE error event; the UI shows it as an honest state).

## 18. Chat goes live — grounding evals pass 7/7

`ANTHROPIC_API_KEY` arrived (now read from a gitignored repo-root `.env` via python-dotenv, loaded in `api/chat.py` so the server and the evals CLI both pick it up). **All 7 grounding evals pass** on the first live run: engine-grounded player answers, refusal to freelance numbers, invented players not hallucinated, departed players (Salah) reported honestly, general-knowledge answers explicitly de-badged from engine output, squad requests routed to the MILP, chip questions answered with the honest not-yet-available state.

The browser end-to-end (Playwright driving the real UI) confirmed the full grounded-chat loop live: "Build me a £100m squad" → build_squad tool card with mini-pitch, bench, and "Use as my draft" → ~30 data chips in the prose, each linked to its source card → 6 players cross-highlighted on the board behind the rail. Sonnet formats squads as markdown tables about half the time, which the minimal chat renderer flattened into pipe-soup — MiniMarkdown now renders pipe tables (separator-row detection tolerates the model attaching a bold heading to the table block), verified against a captured raw stream. One tooling gotcha worth remembering: Git Bash curl mangles `£` to Latin-1, causing 400s that look like an app bug — test with UTF-8 body files.

## 19. Deployment prep — Vercel + Railway ([DEPLOY.md](DEPLOY.md))

The repo side of going live, verified locally. `api/jobs.py` (APScheduler per PLAN §7) makes one Railway service own everything: on boot with `JOBS_ENABLED=1` it idempotently seeds an empty volume (historical download → feature builds → first snapshot → first pipeline) then schedules the hourly snapshot and nightly pipeline+reload in-process — which sidesteps Railway's one-volume-per-service constraint entirely. App hardening for a public URL: CORS origins from env, `/health` resilient during first-boot seeding (Railway healthcheck passes while the volume fills), and a per-IP hourly rate limit on `/chat` that 429s before any Anthropic spend. The web client's chat calls go direct to Railway via `NEXT_PUBLIC_CHAT_API_URL` (Vercel's rewrite proxy times out on 60–150s SSE streams); REST stays on the same-origin rewrite. `railway.json` + `.python-version` pin the build; the 620-byte rating-weights cache is now the one committed exception in the gitignored `data/` tree, saving a deployed first boot from refitting weights via a full 2025-26 replay. Verified: boot with jobs off and on, seed no-op on existing data, limit-0 chat 429s, `next build` clean.

## 20. Deployed — and an About page that proves the pitch

**The site is live**: engine on Railway (volume-seeded on first boot in ~6 min, hourly snapshot + nightly pipeline scheduled in-process), web on Vercel. Deploy war stories, for the record: Vercel initially deployed the repo root and its Python runtime seized our `api/` directory (its serverless-functions convention) — LightGBM then failed on a missing `libgomp` inside a Lambda; fixed by Root Directory = `web` plus flipping the stuck "FastAPI" framework preset to Next.js. Chat's CORS preflight 400'd because the Railway variable was named `CORS_ORIGIN` (singular); the parser now also tolerates spaces and trailing slashes. First live verification passed end-to-end: status bar provenance through the rewrite, tables through the proxy, chat streaming direct to Railway.

`/about` ("How it works") is the marketing surface for the grounding architecture: chatbot-vs-engine contrast cards, the four modeling layers with the assembly formula, the honesty mechanics, and the 2025/26 replay numbers (432 vs 217 vs 528 hindsight ceiling). Its centerpiece holds the page to the product's own standard — a **live** decomposition of the engine's current top-projected player, fetched with provenance on every view, with an offline state that says "this page would rather show you nothing than a made-up chart." Linked from the desktop nav, the onboarding hero, and the chat empty state (mobile path).

---

*Remaining pre-launch: manual scoring-table verification (flip `verified_against_game`). Then the user's UI fixes and TODO.md §2 in-season work. UI backlog per UI_PLAN §12: dark mode, live mode, drag-and-drop, comparison pinning, ownership overlay, chip timeline.*
