# FPL AI Assistant — UI Plan

Companion to [PLAN.md](PLAN.md). Defines the interface: information architecture, key screens, the pitch view and chips surfaces, the chat experience, and the visual language. Design goals, in the user's words: **professional, analytical, intuitive** — with a field view of the team and chips as first-class surfaces.

**Audience reality check:** engaged FPL managers are data-literate hobbyists who make decisions in short bursts (lunch break, the hour before deadline) and are **predominantly on mobile** near deadlines. The UI must be dense enough to respect their literacy and fast enough for the deadline crunch.

**Anti-goals:** gamey/cartoonish styling, gradient-heavy "AI product" look, decoration that isn't information, and any number on screen that didn't come from the engine.

---

## 1. Design concept: "The Board"

The organizing metaphor is the **analyst's tactics board**. The pitch view is not an illustration of the team — it *is* the primary analytical instrument: an interactive top-down board where projections, flags, and advice are rendered in place, with overlay modes like a broadcast telestrator.

The **signature interaction**: the assistant points at the board. When chat output references players, chips, or fixtures, the corresponding elements highlight on the canvas — ask "who should I captain?" and the recommended player pulses on the pitch while the reply streams. This makes the grounding architecture *visible*: the AI is demonstrably reading the same instruments the user sees, not inventing answers.

---

## 2. Information architecture

### Desktop — three-zone layout

```
┌────┬──────────────────────────────────────────────┬───────────────────┐
│    │                                              │  CHAT RAIL        │
│ N  │   MAIN CANVAS                                │  (persistent,     │
│ A  │   My Team · Planner · Players · Fixtures     │   collapsible)    │
│ V  │                                              │                   │
│    │   pitch view / tables / tickers live here    │  streaming reply  │
│    │                                              │  + tool cards     │
├────┴──────────────────────────────────────────────┴───────────────────┤
│  status bar: “Model v0.4 · data through GW7 · updated 14:02”          │
└───────────────────────────────────────────────────────────────────────┘
```

- **Nav (slim left rail):** My Team · Planner · Players · Fixtures. Chips live inside My Team and Planner (they're decisions about *your* team, not a separate library).
- **Chat rail (right):** always available next to any view — this is what "AI-focused" means spatially. Collapsible to a floating button when the user wants full canvas width.
- **Status bar:** global provenance. Every screen answers "how fresh is this?" without being asked.

### Mobile — bottom tabs, chat at center

```
┌─────────────────────────────┐
│         (view content)      │
│                             │
├─────────────────────────────┤
│ Team │ Plan │ ⬤Chat │ Play │ Fix │
└─────────────────────────────┘
```

Chat is the center tab (full-screen thread). Tool result cards are the same components as desktop; cross-highlighting becomes "tap a card → jump to that view with the element highlighted."

### Onboarding

Two entry paths, matching the season calendar:

1. **Pre-GW1 / no team yet:** "Draft your squad" → straight into the Squad Builder (pitch in edit mode) with an optimizer-seeded starting point.
2. **Team exists:** paste FPL team ID → import squad, bank, transfers, chips → land on My Team. No account, no login (per PLAN.md); team ID stored locally, changeable anytime.

---

## 3. Key screens

### 3.1 My Team (home)

```
┌ MY TEAM ─────────────────────────────┐ ┌ THIS WEEK ───────────────┐
│  overlay: [xPts] [Form] [Fixtures]   │ │ GW8 deadline: Sat 11:00  │
│  ┌────────────────────────────────┐  │ │ Projected: 58.3 pts      │
│  │            ▓ GK ▓              │  │ │ Captain: Haaland (C)     │
│  │      ▓DEF▓ ▓DEF▓ ▓DEF▓ ▓DEF▓   │  │ │ ⚠ 1 flagged player       │
│  │    ▓MID▓ ▓MID▓ ▓MID▓ ▓MID▓     │  │ ├──────────────────────────┤
│  │         ▓FWD▓  ▓FWD▓           │  │ │ CHIPS                    │
│  │  ······· pitch (SVG) ········  │  │ │ WC ●avail  FH ●avail     │
│  └────────────────────────────────┘  │ │ BB ○used   TC ●avail     │
│  BENCH:  ▓GK▓ ▓1▓ ▓2▓ ▓3▓            │ │ → best window: see Plan  │
└──────────────────────────────────────┘ └──────────────────────────┘
```

- Pitch view (spec in §4) with overlay toggles.
- **This Week panel:** deadline countdown, projected XI total, captain, flags — the "do I need to act?" summary. Each line deep-links (flagged player → player drawer; captain → captaincy comparison in chat).
- **Chips panel:** compact status card (per-chip: available / used in GWx / active). Links to the chip timeline in Planner.
- In-season, a **Live mode** replaces projections with live points during matches (§4, modes).

### 3.2 Squad Builder (pre-season centerpiece)

Same pitch component in **edit mode**: budget bar and rule validation live at the top (£ spent, per-club count, formation legality), tap an empty slot → filterable player picker sorted by rating, "Optimize" fills or repairs the draft via the MILP, "Rate my draft" scores the user's own squad against the optimal (total xPts delta + weakest-link callouts). This screen is the launch's killer feature and doubles as the Wildcard/Free Hit drafting surface in-season.

### 3.3 Planner (in-season)

- **Transfer plan:** recommended moves this GW and over the horizon, expected gain vs. doing nothing, hit math shown explicitly ("−4 now, +6.2 expected over 4 GWs"). Alternatives listed with deltas, not just a single verdict.
- **Chip timeline** (spec in §5).
- Before the planner ships (GW2 per PLAN.md), this tab shows the chip status card and a "planning unlocks after GW1" state that explains why (transfers are unlimited pre-season).

### 3.4 Players explorer

Dense, sortable table — the analyst's spreadsheet, done properly: position tabs (GK/DEF/MID/FWD each showing **their own** sub-score columns), filters (price, team, ownership, minutes security), fixture-run mini-ticker per row, rating + xPts columns with tabular numerals. Row click → **player drawer**: rating dial with sub-score bars, xPts decomposition (stacked by source: goals/assists/CS/DC/bonus) per GW, fixture run, price & ownership trend. "Compare" pins up to 3 players side-by-side.

### 3.5 Fixtures

Team × GW matrix colored by **model** difficulty (not FPL's FDR), every cell carrying its numeric value; DGW cells show two fixtures stacked, blanks are hatched. Click a team → its players filtered in the explorer.

---

## 4. Pitch view specification

The most important component in the product. Custom responsive SVG (not canvas — needs DOM semantics for a11y and hit targets).

### Layout

Vertical pitch, formation-aware slot positions (all 8 legal formations), bench strip below in autosub order. Two-tone mow stripes in the surface; chalk lines. Max width ~520px on desktop (taller than wide, like a real tactics board); full-bleed width on mobile.

### Player chip anatomy

```
┌───────────┐
│ HAALAND   │  ← condensed caps, like shirt printing
│   14.2    │  ← primary stat for active overlay (mono, tabular)
│ MCI · £14.3│ ← club + price, small
└───────────┘
   ⓒ  ⚠  ▲      ← badges: captain/vice, flag, price-change
```

- **Badges:** Ⓒ captain (armband gold), Ⓥ vice, availability flag (yellow-card amber = doubt, red-card red = out/suspended), price arrows.
- **States:** default · selected (drawer open) · highlighted (chat cross-highlight — chalk-white pulse ring) · dimmed (when chat highlights others) · edit-mode (draggable/tappable).

### Overlay modes (segmented control above the pitch)

| Overlay | Primary stat on chip | Extra rendering |
|---|---|---|
| **xPts** (default) | next-GW expected points | XI total shown above pitch |
| **Form** | last-4 points per game | — |
| **Fixtures** | next-3 difficulty numbers | chip underlined with a 3-cell difficulty strip |
| **Ownership** | ownership % + trend arrow | — |

### Modes

- **Projection** (default): all overlays available; toggling horizon (next GW / next 6) re-renders numbers.
- **Live** (in-season, during matches): chips show live points counting up; played/playing/yet-to-play encoded in chip opacity + a small clock glyph; bonus shown provisionally with a "BPS est." tag.
- **Edit** (Squad Builder, Wildcard/Free Hit drafts): slots become drop targets, budget/rules bar appears, illegal states explained inline ("4th City player — remove one first"), never silently blocked.

### Interactions

Click/tap chip → player drawer. Long-press (mobile) / hover (desktop) → mini-tooltip with the decomposition sparkline. In edit mode: drag between XI and bench, tap-to-swap on mobile. Empty slots (draft) show a ghost chip with "+".

---

## 5. Chips UI specification

Two levels, matching how managers actually think about chips:

### Status card (My Team — always visible)

One row per chip: name, state dot (● available / ○ used in GWx / ◉ active this GW), and — once the advisor ships — a one-line recommendation ("TC: best window GW34, +4.1 xPts"). Pre-advisor, state only. No advice is ever shown that the engine didn't compute.

### Chip timeline (Planner — the analytical view)

```
      GW: 8  9  10 11 12 13 14 ... 33 34 35 36 37 38
          ─┬──┬──┬──┬──┬──┬──┬─ ── ─┬──┬──┬──┬──┬──┬─
  events:  │  │  │  │ BGW │  │      │DGW│  │  │  │  │
  WC  ████████████░░░░░░░░  ← recommended window shading + gain label
  TC                              ▲ GW34 +4.1
  BB                              ▲ GW34 +6.8
  FH              ▲ GW11 (BGW) +9.2
```

- Horizontal GW strip (current GW → 38) with DGW/BGW event badges from the fixture model.
- Per chip: recommended window shaded, best single GW marked with expected gain — the exact number the chip advisor computed, tappable to open the reasoning as a tool card in chat ("why GW34?").
- Deadline-half rules (chips expiring at GW19 under the two-sets rule) rendered as a hard boundary line with a countdown when a use-it-or-lose-it chip nears expiry.

---

## 6. Chat experience & grounding surfaces

### Message anatomy (assistant)

```
┌────────────────────────────────────────────┐
│ Palmer projects [6.1 xPts]* vs. Saka's     │  ← prose; numbers are
│ [5.4]* over the next 4 — the fixture swing │    tappable data chips
│ favors Chelsea from GW9.                   │
│ ┌────────────────────────────────────────┐ │
│ │ ▦ COMPARISON — Palmer vs Saka, GW8–11  │ │  ← tool result card,
│ │   (table rendered from engine payload) │ │    expandable
│ └────────────────────────────────────────┘ │
│ Model v0.4 · data through GW7              │  ← provenance line
└────────────────────────────────────────────┘
```

- **Data chips in prose:** every number the assistant states is rendered as a subtle tappable chip linked to its source tool card — tap → card expands and (desktop) the relevant element highlights on the canvas. This is the UI half of the grounding guarantee: the payload numbers are on screen, the prose merely narrates them.
- **Tool cards:** typed renderers per tool — comparison table, projection sparkline card, transfer-plan card (moves + gain), chip-advice card, mini-pitch (for lineup answers). Never raw JSON.
- **Cross-highlighting:** the signature (§1). Card ↔ canvas highlights in both directions.
- **Suggested prompts** contextual to the current view ("Rate my draft", "Who should I captain?", "Is a −4 worth it this week?") — teaches the tool surface without a manual.
- Streaming via SSE with the reply appearing token-by-token; tool-call activity shown as a quiet inline status ("checking your team → running optimizer") so waits feel purposeful.

### Refusal & honesty states

When the engine can't answer (unknown player, question outside tool coverage), the assistant's "I can't compute that" reply is styled as a normal, confident state — not an error. Out-of-scope honesty is a feature; the UI shouldn't make it feel like a failure.

---

## 7. Visual language

### Direction

**"Tactics room, match day."** Professional-analytical, light-first, with football's own vernacular as the source of every expressive choice — the pitch, chalk lines, shirt printing, referee cards, the captain's armband. Not the cream-serif editorial look, not the black-with-acid-green terminal look; restraint everywhere except the board itself.

### Palette (tokens)

| Token | Hex | Use |
|---|---|---|
| `paper` | `#F6F8F6` | App background (cool off-white, faint green cast) |
| `ink` | `#17211B` | Text (green-tinted near-black) |
| `pitch` | `#1E6B3C` / `#25794A` | Pitch surface (two-tone stripes) — **reserved for the board**; deep `pitch-700` doubles as the interactive accent (links, buttons) |
| `chalk` | `#FFFFFF` | Pitch lines, highlight pulse ring |
| `armband` | `#D9A62B` | Captaincy only |
| `card-yellow` | `#E8B93B` | Warnings: doubt flags, price-fall risk (subject-native semantics) |
| `card-red` | `#C0392B` | Danger: out/suspended, hard errors |
| `slate` | `#5C6B63` | Secondary text, borders, dividers |

Dark mode = **"evening kickoff"**: deep floodlit navy-green (`#0E1613`) surface, pitch slightly luminous, chalk brighter, same semantics. Light is default; dark ships when the token system makes it cheap (post-launch acceptable).

### Typography

| Role | Face | Notes |
|---|---|---|
| Display / hero numbers | **Archivo** (Expanded, Black) | Athletic, scoreboard DNA; used sparingly — section heads, big xPts totals |
| Player chips / labels | **Archivo Condensed**, caps | Shirt-printing vernacular on the pitch and in compact labels |
| Body / UI | **Instrument Sans** | Clean, neutral, not the default-stack look |
| Data / numerals | **IBM Plex Mono** (tabular) | Every table, every stat, every delta — columns must align |

### Data-viz rules (full guidance applied at build time via the dataviz skill)

- **Difficulty ramp:** always number + color, luminance-monotonic so it survives grayscale; CVD-safe alternate ramp (blue→orange) in settings. Never color-only.
- **Deltas:** arrow/sign + color, never color alone (red-green colorblindness is common; green/red is also semantically loaded here by the card colors).
- Decomposition charts use one consistent source-category palette app-wide (goals/assists/CS/DC/bonus each keep their color everywhere).

### Motion

One orchestrated moment: on team load, chips slot into formation with a ~300ms stagger. Otherwise: cross-highlight pulse, live-points count-up, drawer slides. Nothing ambient, nothing looping. `prefers-reduced-motion` respected throughout.

### Copy voice

Plain verbs, sentence case, decisions phrased as the manager thinks ("Worth a −4?" not "Execute transfer analysis"). Buttons say what happens: "Import team", "Optimize draft", "Show why". Empty states are invitations ("No team yet — draft one or paste your team ID"), errors say what to do next. The assistant never hedges numbers it computed and never states numbers it didn't.

---

## 8. Component inventory

| Component | Used in | Notes |
|---|---|---|
| `PitchView` | My Team, Builder, chat mini-pitch | SVG; modes: projection/live/edit; overlay prop |
| `PlayerChip` | PitchView | badge/state system per §4 |
| `PlayerDrawer` | everywhere | rating dial, sub-score bars, decomposition chart, fixture run |
| `RatingDial` + `SubScoreBars` | drawer, explorer | position-specific sub-scores |
| `DecompositionChart` | drawer, tool cards | stacked xPts by source |
| `FixtureTickerCell` | explorer rows, fixtures matrix | number + ramp color |
| `ChipStatusCard` / `ChipTimeline` | My Team / Planner | §5 |
| `BudgetRulesBar` | Builder | live validation |
| `ChatThread`, `DataChip`, `ToolCard` (typed variants) | chat | §6 |
| `ProvenanceBadge` | status bar, tool cards | model version + data-through |
| `ComparisonView` | explorer, tool cards | up to 3 players |

---

## 9. Responsive strategy

Mobile is not an afterthought — deadline-hour traffic is mostly phones.

- Pitch view designed mobile-first (it's naturally portrait); overlay control becomes a horizontal scroll segment.
- Explorer table collapses to ranked cards with the position's top-3 sub-scores; full table behind a "columns" toggle in landscape/desktop.
- Chip timeline scrolls horizontally with the current GW pinned.
- Chat is a full-screen tab; tool cards full-width; cross-highlight becomes tap-to-navigate.
- Touch targets ≥44px including pitch chips (chip size floors the pitch's minimum width; bench wraps if needed).

---

## 10. Accessibility & quality floor

WCAG AA contrast in both themes; visible keyboard focus everywhere including pitch chips (SVG elements are real focusable buttons in DOM order: GK → DEF → MID → FWD → bench); difficulty and deltas never color-only; chat stream announced via `aria-live="polite"` with tool-activity status readable; drawer/dialog focus trapping; `prefers-reduced-motion`; all tables real `<table>` semantics with sortable-header ARIA.

---

## 11. Build notes

- **Stack (per PLAN.md):** Next.js + TypeScript, Tailwind + shadcn/ui primitives themed to §7 tokens, TanStack Query for engine data, SSE for chat streaming.
- **Pitch view:** hand-built SVG component; formation slot coordinates as data; no chart library involved.
- **Charts:** Recharts or visx, styled by the token system; consult the dataviz skill when building each chart.
- **Theming:** all §7 values as CSS custom properties from day one — dark mode and the CVD ramp become config, not rework.
- **Tool cards:** a typed registry mapping tool name → card component; unknown tools fall back to a generic table card (never raw JSON, never dropped).

---

## 12. Phasing (aligned to PLAN.md's GW1 deadline)

### GW1 launch (must ship)

- Onboarding (draft path + team-ID import)
- **PitchView** — projection mode, xPts + fixtures overlays, player drawer
- **Squad Builder** — edit mode, budget/rules bar, optimize + rate-my-draft
- Chips **status card** (state only)
- Players explorer (table + drawer + position sub-scores)
- Fixtures matrix (basic)
- **Chat** — rail/tab, streaming, tool cards for the launch tool surface, data chips + provenance; cross-highlight v1 (pitch highlight on player mentions)
- Status bar provenance; light theme; mobile layouts for all of the above

### In-season, first weeks

- Planner view: transfer-plan cards (GW2), **chip timeline with advice** (~GW4)
- Live mode on the pitch
- ComparisonView, ownership overlay, suggested-prompt polish
- Dark mode ("evening kickoff"), CVD ramp setting

### Later

- Drag-and-drop lineup editing (tap-to-swap ships first), mini-league views, alerts surfaces, richer cross-highlighting (fixtures/chips), player news integration.

### Explicitly cut from launch

Dark mode, live mode, drag-and-drop, comparison pinning, ownership overlay — none block the pre-season job of drafting a squad and interrogating it through chat.
