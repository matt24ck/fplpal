# FPL AI Assistant — Project Plan

An AI-focused Fantasy Premier League assistant. Users converse in natural language; every insight the site returns is computed by a statistical/ML engine — the LLM is an orchestrator and translator, never the source of numbers.

**Timing note:** it is July 2026; the 2026/27 FPL game launches shortly (season kicks off mid-August). Building the data pipeline and models now against historical data means the site can go live with projections at Gameweek 1.

---

## 1. Product summary

| Capability | What the user gets |
|---|---|
| **Player ratings** | Position-specific 0–100 ratings (separate systems for GK / DEF / MID / FWD) with sub-scores explaining *why* |
| **Points projections** | Expected points (xPts) per player for the next 1–8 gameweeks, decomposed by source (goals, assists, clean sheets, bonus, …) |
| **Squad & transfer advice** | Given the user's actual team, budget, and free transfers: optimal transfers this week and over a multi-GW horizon, including whether a points hit is worth it |
| **Chip advice** | When to play Wildcard / Free Hit / Bench Boost / Triple Captain, quantified as expected points gained vs. holding |
| **Captaincy & lineup** | Best XI, formation, captain/vice, bench order for the user's squad |
| **Chat interface** | All of the above through natural conversation ("Should I sell Saka for Palmer or save for Haaland?"), with numbers grounded in the engine |

### The core design principle: grounded AI

The LLM (Claude) never computes or invents a statistic. It:

1. Interprets the user's question,
2. Calls typed tools exposed by the stats/optimization engine,
3. Explains the tool results in natural language, citing them.

Every numeric claim in a response must be traceable to a tool result. This is enforced by system-prompt rules, structured tool outputs with provenance metadata, and automated grounding evals (§8).

---

## 2. FPL domain model (rules the engine must encode)

Scoring and squad rules are **season configuration**, stored in a versioned config file and re-verified against the official game at each season launch (rules change most summers — e.g. defensive contribution points were added in 2025/26). Baseline (2025/26 ruleset):

**Squad rules:** 15 players (2 GK, 5 DEF, 5 MID, 3 FWD), £100.0m initial budget, max 3 per club. Starting XI: 1 GK, ≥3 DEF, ≥2 MID, ≥1 FWD. Captain doubles points (vice as fallback). Auto-subs by bench order. 1 free transfer per GW, bankable up to 5; extra transfers cost −4 each.

**Scoring (points per event):**

| Event | GK | DEF | MID | FWD |
|---|---|---|---|---|
| Appearance (<60 / ≥60 min) | 1 / 2 | 1 / 2 | 1 / 2 | 1 / 2 |
| Goal | 6 | 6 | 5 | 4 |
| Assist | 3 | 3 | 3 | 3 |
| Clean sheet (≥60 min) | 4 | 4 | 1 | — |
| Every 2 goals conceded | −1 | −1 | — | — |
| Every 3 saves | 1 | — | — | — |
| Penalty save / miss | +5 / −2 | — / −2 | — / −2 | — / −2 |
| Defensive contribution (threshold per match) | — | +2 (10+ CBIT) | +2 (12+ CBIRT) | +2 (12+ CBIRT) |
| Yellow / red card | −1 / −3 | −1 / −3 | −1 / −3 | −1 / −3 |
| Own goal | −2 | −2 | −2 | −2 |
| Bonus (top 3 BPS in match) | 1–3 | 1–3 | 1–3 | 1–3 |

CBIT = clearances, blocks, interceptions, tackles; CBIRT adds ball recoveries.

**Chips (config-driven; 2025/26 had two of each, one per half-season):** Wildcard, Free Hit, Bench Boost, Triple Captain.

---

## 3. Data sources & pipeline

### Sources

| Source | What | Access | Notes |
|---|---|---|---|
| **Official FPL API** | Players, prices, ownership, fixtures, per-GW stats, **official xG/xA/xGI/xGC**, BPS, defensive-contribution stats, injury flags | Free, no auth, JSON | Primary source. Key endpoints: `bootstrap-static/`, `fixtures/`, `element-summary/{id}/`, `event/{gw}/live/`, `entry/{id}/event/{gw}/picks/`, `team/set-piece-notes/` |
| **User team import** | User's squad, bank, chips used, transfers | Public via team ID (`entry/` endpoints) | No login needed for MVP — user just pastes their team ID |
| **vaastav/Fantasy-Premier-League** (GitHub) | Per-player per-GW history back to 2016/17 | Free CSV | Backtesting + model training corpus |
| **Understat** | Shot-level xG, player match xG/xA | Scrapeable JSON | Optional enrichment; check ToS. FPL's own xG fields may be sufficient for MVP |
| **FBref** | Detailed per-90s (touches, progressive actions, GK advanced) | Scrape / paid API | Phase 2+; licensing caveats |

### Historical depth & the GW1 cold start

What the official API does and doesn't provide historically:

- `element-summary/{id}/` → `history`: per-GW rows for the **current season only**. At GW1 these are empty and every player's `bootstrap-static` season stats are zero.
- `element-summary/{id}/` → `history_past`: one row per **previous season** with season totals (points, minutes, goals, assists, xG/xA, …) — useful for priors, but season-level only.
- **Per-GW data for past seasons is not served by the API at all.** The vaastav archive (per-GW back to 2016/17) is the training corpus; it is not optional.

The engine is designed so GW1 needs no current-season stats — everything at launch runs on priors:

| Component | GW1 initialization |
|---|---|
| Team strength | Seeded from 2025/26 results with time decay; promoted teams get league-adjusted priors |
| Player event rates | Prior-season per-90s carried over with shrinkage; `history_past` totals as a cross-check |
| New-to-league signings | Position × price-tier priors (FPL's pricing itself encodes expected output) |
| Minutes | Hardest at GW1: status flags, price tier, historical GW1 start patterns, preseason signals; expect this to be the biggest early-season error source and let it sharpen quickly as real minutes arrive |

Shrinkage weights then shift from prior → current-season observed data as GWs accumulate, so the same code path serves GW1 and GW30.

One practical implication: the 2026/27 game and its API typically go live in mid-July — **check now and start hourly snapshots immediately**, so launch prices, new player IDs, and early ownership trends are archived from day one.

Unofficial-API risk: no SLA, occasional schema changes, gameweek-rollover downtime. Mitigate with a raw-snapshot archive (store every API pull), schema validation on ingest, and graceful "data as of" staleness handling.

### Pipeline

```
Scheduled jobs (cron / APScheduler):
  hourly:      bootstrap-static snapshot  → prices, ownership, injury flags
  post-match:  event/{gw}/live + element-summary → per-match player stats
  nightly:     model retrain/refresh → projections table rebuild
  deadline-1h: final refresh + projection freeze for the GW

Raw JSON snapshots (object storage / disk)
  → staging tables (Postgres)
  → feature tables (per-player per-GW)
  → model outputs (projections, ratings) — versioned, timestamped
```

Every model output row carries `(model_version, data_through_gw, computed_at)` — this is the provenance the chat layer cites.

---

## 4. Statistical modeling architecture

Expected points are built **bottom-up from event probabilities**, not predicted as a single opaque number. This makes projections decomposable (the chat layer can explain *why*), position-aware by construction, and independently testable per component.

```
Layer 1  Team strength      →  per-fixture goal expectations (attack/defence)
Layer 2  Minutes model      →  P(start), E[minutes], P(60+)
Layer 3  Player event rates →  per-90 rates for goals, assists, saves, DC, cards
Layer 4  Points assembly    →  E[pts] = Σ P(event) × points(event, position)
```

### Layer 1 — Team strength (Dixon-Coles)

A bivariate Poisson / Dixon-Coles model over match results with exponential time-decay, blended with team-level xG (which is less noisy than goals). Outputs per fixture: λ_home, λ_away (expected goals for each side). Derived quantities:

- **P(clean sheet)** for team T = P(opponent scores 0) = Poisson(0; λ_opp)
- **Goals-conceded distribution** → expected −1/2-goals penalty for GK/DEF
- **Expected opponent shots on target** (scaled from λ_opp) → GK save points
- A continuous **fixture difficulty** measure per team per GW (replaces FPL's crude 1–5 FDR), including double/blank gameweek awareness.

### Layer 2 — Minutes model (the highest-leverage component)

Most projection error in public FPL models comes from minutes, not per-90 quality. A gradient-boosted classifier (LightGBM) predicting `{start, sub-appearance, unused}` and, conditional on starting, P(plays 60+). Features: recent start share, minutes trend, days between fixtures (rotation risk), FPL injury/status flags (`chance_of_playing`), new-signing flag, cup congestion, blowout-substitution patterns, price-change momentum (market signal of expected minutes).

Output: `p_start`, `p_cameo`, `e_minutes`, `p_60plus` per player per fixture.

### Layer 3 — Player event rates (per-90, shrunken)

For each player, per-90 rates estimated with **empirical-Bayes shrinkage** toward position/price-tier priors (so a two-match hot streak doesn't dominate, and new signings get sensible priors):

- **npxG/90** and **xA/90** (official FPL xG/xA, optionally blended with Understat), plus penalty-taker status from `set-piece-notes`
- **Finishing adjustment**: career goals-minus-xG, heavily shrunk (finishing skill is mostly noise season-to-season)
- **Defensive contribution**: CBIT/CBIRT per 90 → P(hit threshold) via a Poisson/negative-binomial count model — this is a *floor* stat that matters a lot for DEF/MID ratings since 2025/26
- **Saves/90** for GKs, driven by opponent shot volume from Layer 1
- **Cards/90**, own-goal and penalty-miss base rates
- **Bonus model**: expected BPS from the event projections + historical "bonus magnetism" residual (some players systematically over/under-earn BPS per point-scoring event) → E[bonus] via rank simulation within the match

Player attacking output is scaled by team context: E[goals] = (npxG/90 shrunk) × (e_minutes/90) × (team λ for that fixture / team baseline λ) + penalty share.

### Layer 4 — Points assembly (position-aware by construction)

```
E[pts] = p_appear × appearance_pts(e_minutes)
       + E[goals]   × goal_value(position)
       + E[assists] × 3
       + p_60plus × P(CS) × cs_value(position)          (GK/DEF/MID)
       − E[goals_conceded_pairs]                         (GK/DEF)
       + E[save_points] + p_pen_save × 5                 (GK)
       + P(DC threshold) × 2                             (DEF/MID/FWD)
       + E[bonus] − E[card_pts] − minor_negatives
```

Computed per fixture (summing across fixtures in a double gameweek) for horizons GW+1 … GW+8. Also produce a **variance/ceiling estimate** per player (needed for captaincy and differential advice — captain picks maximize upside, not just mean).

### Position rating systems

Each position gets its own composite 0–100 rating built from *different* components with *different* weights, plus named sub-scores the UI and chat can surface:

| Position | Sub-scores (each 0–100) |
|---|---|
| **GK** | Clean-sheet potential · Save-point volume · Bonus/pen-save upside · Value (xPts/£m) · Minutes security |
| **DEF** | Clean-sheet potential · Attacking threat (xG+xA from set pieces/overlaps) · Defensive-contribution floor · Bonus magnetism · Value · Minutes security |
| **MID** | Attacking output (npxG+xA) · Involvement (penalties, set pieces) · DC/appearance floor · Explosiveness (ceiling) · Value · Minutes security |
| **FWD** | Attacking output · Penalty status · Floor (DC + appearance) · Explosiveness · Value · Minutes security |

The headline rating is a fixture-adjusted weighted blend over the chosen horizon (default next 6 GWs). Weights are fit by regressing sub-scores against realized points in backtests — not hand-tuned vibes.

---

## 5. Optimization engine

Deterministic operations-research layer on top of the projections. All advice is *solved*, not heuristic.

### Squad optimizer (MILP)

Mixed-integer linear program (HiGHS via PuLP or OR-Tools): maximize Σ xPts over the horizon subject to budget, 2/5/5/3 squad shape, ≤3 per club, valid formation for the XI, captain doubling, and bench-weighted xPts (bench players weighted by autosub probability). Solves "best squad for £X" and "best XI from my 15" in well under a second at FPL scale (~700 players).

### Transfer planner (multi-period MILP)

Plans transfers over a 5–8 GW horizon: free-transfer banking (max 5), −4 hit costs, sell-price rules (50% of profit). Outputs: this week's recommended move(s), the plan's expected gain vs. doing nothing, and sensitivity ("if Haaland's flagged, plan B is…"). Price-change prediction (transfer-momentum model) is a Phase-3 nicety that improves timing advice.

### Chip advisor

For each unused chip, simulate expected value across every remaining GW and recommend the best window with a quantified gain:

- **Bench Boost**: E[bench points] per GW with the optimizer allowed to build toward a strong bench; peaks in double gameweeks
- **Triple Captain**: max E[captain pts] GW, using the ceiling estimate (variance matters), DGW-aware
- **Free Hit**: (optimal one-week squad xPts − current squad xPts) per GW; peaks in blank/double GWs
- **Wildcard**: (optimal squad from scratch − current squad, over horizon) minus what the normal transfer plan would achieve anyway

The advisor reports "play TC in GW34 (Haaland, DGW): +4.1 expected points vs. best single-GW alternative" — a number the chat layer can quote directly.

---

## 6. AI conversational layer

### Architecture: LLM as orchestrator over typed tools

Claude API with **tool use** (the SDK Tool Runner drives the loop). The backend exposes the engine as tools; Claude interprets the question, calls tools, and narrates results.

Core tool surface (all return structured JSON with provenance):

```
get_player(name | id)                  → profile, price, ownership, status, rating + sub-scores
project_points(player_ids, horizon)    → xPts decomposition per GW per player
compare_players(ids, horizon)          → side-by-side projections + ratings
rank_players(position, filters, horizon) → top-N by rating or xPts (e.g. "best DEF under £5.5m")
get_user_team(team_id)                 → squad, bank, free transfers, chips remaining
optimize_transfers(team_id, horizon, max_hits) → recommended moves + expected gain
optimize_lineup(team_id)               → best XI, formation, captain/vice, bench order
chip_advice(team_id)                   → per-chip best window + expected gain
get_fixtures(team | player, horizon)   → fixture list with model difficulty
explain_rating(player_id)              → sub-score breakdown + top contributing factors
```

### Grounding guarantees (the "not from the AI model" requirement)

1. **System prompt contract**: "Every statistic, projection, ranking, or recommendation you state must come from a tool result in this conversation. If a tool doesn't cover the question, say so — never estimate from your own knowledge. Football knowledge may be used only for context and phrasing, never for numbers or recommendations."
2. **Structured provenance**: every tool response includes `model_version` and `data_through_gw`; responses in the UI carry a "computed from data through GW N" badge, and the raw tool results are rendered as expandable cards (tables/charts) alongside the prose — so the numbers the user sees come from the engine payload directly, not from tokens the LLM generated.
3. **Strict tool schemas** (`strict: true`) so tool inputs always validate.
4. **Grounding evals**: an automated test suite of adversarial prompts ("just give me a rough guess", "who won the league in 2019?", questions about players who don't exist) asserting the assistant refuses to freelance numbers and correctly distinguishes engine output from general knowledge.
5. **Out-of-scope honesty**: knowledge cutoffs don't matter because current data always comes from tools; the assistant is instructed to treat its own priors about current-season football as stale.

### Model choice & cost

Because the grounded design pushes all difficult reasoning into the engine, the LLM only needs to parse intent, sequence tool calls, and narrate results faithfully — a mid-tier model handles that well. Default **`claude-sonnet-5`** ($3/$15 per MTok; intro $2/$10 through Aug 2026). With a cached system prompt (~3k tokens, `cache_control` breakpoint) a typical query runs roughly 3–6k input / 400–800 output tokens ≈ **$0.01–0.02 per query**. **`claude-haiku-4-5`** ($1/$5) is a further step-down worth A/B-testing once the grounding evals exist — likely fine for single-tool lookups ("how's Saka rated?"), with a simple router keeping multi-step advice queries ("sell X for Y or bank?") on Sonnet if Haiku's tool sequencing proves less reliable. Streaming responses via SSE for a responsive chat feel; prompt caching on the system prompt + tool definitions keeps per-turn cost down.

---

## 7. Tech stack & system architecture

| Layer | Choice | Rationale |
|---|---|---|
| Language (engine) | **Python 3.12** | The entire modeling/optimization ecosystem lives here |
| Data | **PostgreSQL** + raw JSON snapshot archive | Relational fits the domain; snapshots make everything reproducible |
| Modeling | pandas/polars, **statsmodels/scipy** (Dixon-Coles), **LightGBM** (minutes, bonus), custom shrinkage | Right tool per component; all interpretable enough to explain |
| Optimization | **PuLP + HiGHS** (or OR-Tools) | Free, fast at FPL problem sizes |
| API backend | **FastAPI** | Async, typed, SSE streaming, serves both the chat loop and REST endpoints |
| LLM | **Claude API** — Python SDK tool runner (`@beta_tool` + `client.beta.messages.tool_runner`), prompt caching, streaming | Tool-use loop handled by SDK; per-turn hooks for logging/guardrails |
| Frontend | **Next.js + TypeScript**, Tailwind | Chat UI (streaming), player tables, fixture ticker, rating cards |
| Jobs | APScheduler (MVP) → dedicated scheduler if needed | Simple first |
| Hosting | Vercel (frontend) + a single VPS or Railway/Fly (API + Postgres + jobs) | Cheap to start; nothing here needs to scale early |

```
┌──────────────┐   SSE/REST   ┌────────────────────────────────────────┐
│  Next.js UI  │ ───────────► │  FastAPI                               │
│  chat + data │              │  ├─ /chat  → Claude tool-runner loop   │
│  views       │              │  │           └─ tools → engine services │
└──────────────┘              │  ├─ /players /projections /fixtures    │
                              │  └─ /team/{id}/advice                  │
                              └───────┬────────────────────────────────┘
                                      │ reads
                    ┌─────────────────▼───────────────┐     ┌──────────────┐
                    │ Postgres: features, projections, │ ◄── │ Nightly jobs │
                    │ ratings, optimizer cache         │     │ ingest+train │
                    └──────────────────────────────────┘     └──────┬───────┘
                                                                    │
                                                     FPL API · vaastav · Understat
```

Chat is read-only over precomputed projections plus on-demand optimizer runs — LLM latency dominates, so no heavy compute sits in the request path except MILP solves (sub-second).

### Suggested repo layout

```
fpl_ai_site/
├── engine/            # the product's brain — no LLM code here
│   ├── ingest/        # FPL API clients, snapshot archive, schema validation
│   ├── features/      # feature building (per-player per-GW tables)
│   ├── models/        # team_strength/, minutes/, event_rates/, points/, ratings/
│   ├── optimize/      # squad MILP, transfer planner, chip advisor
│   └── config/        # season rules (scoring, chips) as versioned config
├── api/               # FastAPI app: REST + chat endpoint + tool definitions
├── web/               # Next.js frontend
├── backtest/          # historical evaluation harness + grounding evals
└── PLAN.md
```

---

## 8. Evaluation & backtesting

Built in Phase 1, not bolted on — the ratings-weight fitting and all "is this model good?" claims depend on it.

- **Replay framework**: run the full pipeline against vaastav historical data as if live, per GW, for ≥3 past seasons (train on seasons before the evaluation season).
- **Projection metrics**: RMSE of xPts vs actual per player-GW; **Spearman rank correlation within position** (rank quality matters more than absolute error); top-K overlap (model top-10 vs actual top-10 per position).
- **Calibration**: clean-sheet probabilities, minutes probabilities, DC-threshold probabilities vs observed frequencies (reliability curves).
- **Baselines to beat**: FPL's own `ep_next` field, naive "last-4-GW form", and season points-per-game. If the engine can't beat these, the AI layer has nothing worth saying.
- **Bot manager simulation**: a simulated manager following the optimizer + chip advisor for a full season; compare total to the season's average manager and top-10k cutoff (public numbers).
- **Grounding evals** for the chat layer (§6) run in CI on every system-prompt or tool change.

---

## 9. Roadmap

**Hard deadline: live before the GW1 deadline (mid-August 2026, ~3–4 weeks away).** Pre-season is peak engagement — the launch must catch it. The scope cut that makes this feasible: the killer pre-season feature is **initial squad drafting**, which needs projections, ratings, and the squad MILP but *not* the transfer planner (changes are unlimited before GW1) and *not* the chip advisor (chips matter from ~GW4 at the earliest). Those ship in-season, when they first become relevant.

### GW1-critical path

**Week 1 — Foundations + data (start snapshotting day 1):** repo + git init, Postgres, FPL API client with snapshot archive against the live 2026/27 game, vaastav historical load, 2026/27 season-rules config verified against the launched game.

**Weeks 2–3 — Engine at GW1 scope:** team strength seeded from 2025/26 (+ promoted-team priors); minutes model v1; shrunken event rates with new-signing priors; points assembly; position ratings v1; **squad MILP + lineup/captain optimizer** ("build my £100m GW1 squad" / "rate my draft"). Backtest gate abbreviated for the deadline: replay 2025/26 only and beat `ep_next` on within-position rank correlation — the full multi-season suite moves in-season.

**Weeks 3–4 — Product + launch:** FastAPI endpoints; minimal Next.js UI (chat, player table with ratings/projections, squad builder / draft-rating view, team import); Claude tool loop with streaming + provenance cards; core grounding evals. **Launch before the GW1 deadline.**

### In-season (first priority after launch)

- **By GW2:** multi-GW transfer planner (the moment it's first needed)
- **By ~GW4:** chip advisor (ahead of the first realistic wildcard window)
- **Ongoing:** full multi-season backtest suite + live accuracy monitoring, price-change model, alerts (injury flags, deadlines), accounts/persistence, mini-league comparisons

### Explicitly cut from launch

Understat/FBref enrichment, accounts, alerts, price-change model, bot-manager simulation — all post-GW1. Nothing on this list blocks the pre-season value proposition.

The compressed pre-launch backtest is the main quality risk of this schedule: the engine goes live validated against one season instead of three. Acceptable because early-season projections are prior-dominated anyway (§3), and the full evaluation harness lands within the first few gameweeks.

---

## 10. Risks & open questions

| Risk | Mitigation |
|---|---|
| FPL API is unofficial (schema drift, no SLA) | Snapshot archive, schema validation on ingest, "data as of" surfacing, quick-patch ownership of the ingest layer |
| Rule changes at season launch (scoring, chips) | All rules in versioned season config; verify against the game in July/August before GW1 |
| Minutes model is hard (press-conference news isn't in any API) | Accept it's the error ceiling; use status flags + market signals; consider a manual override table for late team news |
| Understat/FBref scraping ToS | MVP runs on official FPL xG only; enrichment is optional and isolated |
| LLM cost at scale | Prompt caching + streaming from day one; per-user rate limits; Haiku step-down/router path documented |
| Grounding regressions as prompts evolve | Grounding evals in CI; provenance rendered from engine payloads, not LLM text |

**Open decisions (defaults chosen, easy to revisit):** user accounts vs. team-ID-only (default: team-ID-only for MVP); Understat enrichment in Phase 1 or later (default: later); hosting target (default: VPS/Railway + Vercel); whether chip simulation uses full Monte Carlo over season paths or per-GW expectation (default: per-GW expectation first).
