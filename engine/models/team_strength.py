"""Team strength: a time-decayed Dixon-Coles model blended with team xG.

Produces per-fixture goal expectations and scoreline distributions — the
foundation for clean-sheet probabilities, goals-conceded penalties, save
volume, and fixture difficulty (PLAN.md §4, Layer 1).

Model:
- log lambda_home = mu + home_adv + attack[home] - defence[away]
- log lambda_away = mu + attack[away] - defence[home]
- Weighted MLE where each match's weight decays exponentially with age
  relative to ``as_of`` (so backtests fit "as of" any historical date).
- The Poisson response is a blend of actual goals and team xG where xG exists
  (2022-23+); xG is a less noisy signal of team quality than goals. The
  y*log(lam) - lam quasi-likelihood is valid for the continuous blend.
- A small ridge penalty on attack/defence makes the translation direction
  identifiable and mildly shrinks low-data teams toward league average.
- The Dixon-Coles low-score correction (rho) is fitted in a second stage on
  actual integer scorelines with strengths held fixed — it matters for
  clean-sheet probabilities via P(0-0)/P(1-0)/P(0-1)/P(1-1).
- Teams with no PL history (newly promoted) forecast from a "promoted prior":
  a low percentile of currently-established teams' attack/defence.

Defaults (decay, xg_weight, ridge) are starting points to be tuned by the
backtest harness, not settled choices.

Run a 2025-26 holdout evaluation: ``python -m engine.models.team_strength``
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

MAX_GOALS = 10  # scoreline grid truncation; P(>10 goals) is negligible


@dataclass
class FixtureForecast:
    home: str
    away: str
    lambda_home: float
    lambda_away: float
    p_cs_home: float  # P(away scores 0)
    p_cs_away: float  # P(home scores 0)
    score_grid: np.ndarray = field(repr=False)  # P(home=i, away=j), (MAX_GOALS+1)^2


class TeamStrengthModel:
    def __init__(
        self,
        decay_per_day: float = 0.0025,  # half-life ~277 days
        xg_weight: float = 0.7,  # blend weight on xG where available
        ridge: float = 1.0,
        promoted_percentile: float = 0.15,
        min_weighted_n: float = 5.0,  # below this decayed weight, use the promoted prior
    ) -> None:
        self.decay_per_day = decay_per_day
        self.xg_weight = xg_weight
        self.ridge = ridge
        self.promoted_percentile = promoted_percentile
        self.min_weighted_n = min_weighted_n

        self.teams_: list[str] = []
        self.mu_: float = 0.0
        self.home_adv_: float = 0.0
        self.attack_: dict[str, float] = {}
        self.defence_: dict[str, float] = {}
        self.rho_: float = 0.0
        self.weighted_n_: dict[str, float] = {}
        self.as_of_: pd.Timestamp | None = None

    # -- fitting -----------------------------------------------------------

    def fit(self, matches: pd.DataFrame, as_of: pd.Timestamp | None = None) -> TeamStrengthModel:
        """Fit on matches with kickoff strictly before ``as_of`` (default: all)."""
        m = matches.dropna(subset=["home_goals", "away_goals"]).copy()
        as_of = as_of if as_of is not None else m["kickoff_time"].max() + pd.Timedelta(days=1)
        m = m[m["kickoff_time"] < as_of]
        if m.empty:
            raise ValueError("no matches before as_of")
        self.as_of_ = as_of

        age_days = (as_of - m["kickoff_time"]).dt.total_seconds().to_numpy() / 86400.0
        w = np.exp(-self.decay_per_day * age_days)

        self.teams_ = sorted(set(m["home"]) | set(m["away"]))
        idx = {t: k for k, t in enumerate(self.teams_)}
        T = len(self.teams_)
        hi = m["home"].map(idx).to_numpy()
        ai = m["away"].map(idx).to_numpy()

        hg = m["home_goals"].to_numpy(dtype=float)
        ag = m["away_goals"].to_numpy(dtype=float)
        hxg = m["home_xg"].astype("float64").to_numpy()
        axg = m["away_xg"].astype("float64").to_numpy()
        y_h = np.where(np.isnan(hxg), hg, self.xg_weight * hxg + (1 - self.xg_weight) * hg)
        y_a = np.where(np.isnan(axg), ag, self.xg_weight * axg + (1 - self.xg_weight) * ag)

        def nll_grad(params: np.ndarray) -> tuple[float, np.ndarray]:
            mu, ha = params[0], params[1]
            att = params[2 : 2 + T]
            dfn = params[2 + T :]
            log_lh = mu + ha + att[hi] - dfn[ai]
            log_la = mu + att[ai] - dfn[hi]
            lh, la = np.exp(log_lh), np.exp(log_la)

            nll = float(
                np.sum(w * (lh - y_h * log_lh))
                + np.sum(w * (la - y_a * log_la))
                + self.ridge * (att @ att + dfn @ dfn)
            )
            r_h = w * (lh - y_h)
            r_a = w * (la - y_a)
            g = np.zeros_like(params)
            g[0] = r_h.sum() + r_a.sum()
            g[1] = r_h.sum()
            g_att = np.zeros(T)
            np.add.at(g_att, hi, r_h)
            np.add.at(g_att, ai, r_a)
            g_dfn = np.zeros(T)
            np.add.at(g_dfn, ai, -r_h)
            np.add.at(g_dfn, hi, -r_a)
            g[2 : 2 + T] = g_att + 2 * self.ridge * att
            g[2 + T :] = g_dfn + 2 * self.ridge * dfn
            return nll, g

        x0 = np.zeros(2 + 2 * T)
        x0[0] = np.log(max(y_h.mean(), 0.1))
        res = minimize(nll_grad, x0, jac=True, method="L-BFGS-B")
        if not res.success:
            raise RuntimeError(f"team-strength fit did not converge: {res.message}")

        self.mu_ = float(res.x[0])
        self.home_adv_ = float(res.x[1])
        self.attack_ = dict(zip(self.teams_, res.x[2 : 2 + T]))
        self.defence_ = dict(zip(self.teams_, res.x[2 + T :]))

        wn = np.zeros(T)
        np.add.at(wn, hi, w)
        np.add.at(wn, ai, w)
        self.weighted_n_ = dict(zip(self.teams_, wn))

        self._fit_rho(hi, ai, hg, ag, w, res.x, T)
        return self

    def _fit_rho(self, hi, ai, hg, ag, w, params, T) -> None:
        """Stage 2: Dixon-Coles low-score correction on actual integer scores."""
        att = params[2 : 2 + T]
        dfn = params[2 + T :]
        lh = np.exp(self.mu_ + self.home_adv_ + att[hi] - dfn[ai])
        la = np.exp(self.mu_ + att[ai] - dfn[hi])
        low = (hg <= 1) & (ag <= 1)
        lh, la, x, y, wl = lh[low], la[low], hg[low], ag[low], w[low]

        def neg_ll(rho: float) -> float:
            tau = _dc_tau(x, y, lh, la, rho)
            if np.any(tau <= 0):
                return np.inf
            return -float(np.sum(wl * np.log(tau)))

        res = minimize_scalar(neg_ll, bounds=(-0.3, 0.3), method="bounded")
        self.rho_ = float(res.x)

    # -- prediction --------------------------------------------------------

    def strengths_for(self, team: str) -> tuple[float, float]:
        """(attack, defence) — promoted prior for unknown or data-starved teams.

        A club last seen in the league many years ago has decayed to nearly
        zero data weight, so its fitted strengths are ridge-dominated (i.e.,
        league average) — the promoted prior is the honest forecast there too.
        """
        if self.weighted_n_.get(team, 0.0) >= self.min_weighted_n:
            return self.attack_[team], self.defence_[team]
        return self.promoted_prior()

    def baseline_lambda(self, team: str) -> float:
        """Expected goals vs a league-average opponent, venue-averaged.

        The normalizer for fixture scaling: player attacking rates were earned
        over a home/away mix of typical opponents, so a fixture's difficulty
        multiplier is lambda_fixture / baseline_lambda(team).
        """
        att, _ = self.strengths_for(team)
        return float(np.exp(self.mu_ + self.home_adv_ / 2.0 + att - self._mean_defence()))

    def league_lambda(self) -> float:
        """League-average per-team goal expectation (venue-averaged)."""
        return float(
            np.exp(self.mu_ + self.home_adv_ / 2.0 + self._mean_attack() - self._mean_defence())
        )

    def _mean_attack(self) -> float:
        w = np.array([self.weighted_n_[t] for t in self.teams_])
        return float(np.average([self.attack_[t] for t in self.teams_], weights=w))

    def _mean_defence(self) -> float:
        w = np.array([self.weighted_n_[t] for t in self.teams_])
        return float(np.average([self.defence_[t] for t in self.teams_], weights=w))

    def promoted_prior(self) -> tuple[float, float]:
        """Low-percentile strength of established teams — the newly-promoted default."""
        pool = [t for t, n in self.weighted_n_.items() if n >= 20]
        att = np.quantile([self.attack_[t] for t in pool], self.promoted_percentile)
        dfn = np.quantile([self.defence_[t] for t in pool], self.promoted_percentile)
        return float(att), float(dfn)

    def forecast(self, home: str, away: str) -> FixtureForecast:
        att_h, def_h = self.strengths_for(home)
        att_a, def_a = self.strengths_for(away)
        lam_h = float(np.exp(self.mu_ + self.home_adv_ + att_h - def_a))
        lam_a = float(np.exp(self.mu_ + att_a - def_h))

        goals = np.arange(MAX_GOALS + 1)
        grid = np.outer(poisson.pmf(goals, lam_h), poisson.pmf(goals, lam_a))
        for i in (0, 1):
            for j in (0, 1):
                grid[i, j] *= _dc_tau(
                    np.array([i]), np.array([j]), np.array([lam_h]), np.array([lam_a]), self.rho_
                )[0]
        grid /= grid.sum()

        return FixtureForecast(
            home=home,
            away=away,
            lambda_home=lam_h,
            lambda_away=lam_a,
            p_cs_home=float(grid[:, 0].sum()),
            p_cs_away=float(grid[0, :].sum()),
            score_grid=grid,
        )

    def team_table(self) -> pd.DataFrame:
        return (
            pd.DataFrame(
                {
                    "team": self.teams_,
                    "attack": [self.attack_[t] for t in self.teams_],
                    "defence": [self.defence_[t] for t in self.teams_],
                    "weighted_n": [self.weighted_n_[t] for t in self.teams_],
                }
            )
            .sort_values("attack", ascending=False)
            .reset_index(drop=True)
        )


def _dc_tau(
    x: np.ndarray, y: np.ndarray, lam: np.ndarray, mu: np.ndarray, rho: float
) -> np.ndarray:
    """Dixon-Coles adjustment for the four low-score cells; 1.0 elsewhere."""
    tau = np.ones_like(lam)
    tau = np.where((x == 0) & (y == 0), 1 - lam * mu * rho, tau)
    tau = np.where((x == 0) & (y == 1), 1 + lam * rho, tau)
    tau = np.where((x == 1) & (y == 0), 1 + mu * rho, tau)
    tau = np.where((x == 1) & (y == 1), 1 - rho, tau)
    return tau


# -- holdout evaluation ----------------------------------------------------


def evaluate_holdout(holdout_season: str = "2025-26") -> None:
    """Fit before ``holdout_season``, score CS probabilities and goal calibration on it."""
    from engine.features.matches import load_matches

    matches = load_matches()
    test = matches[matches["season"] == holdout_season]
    if test.empty:
        raise SystemExit(f"no matches for holdout season {holdout_season}")
    cutoff = test["kickoff_time"].min()

    model = TeamStrengthModel().fit(matches, as_of=cutoff)
    print(
        f"fitted on {(matches['kickoff_time'] < cutoff).sum():,} matches before "
        f"{cutoff.date()} | home_adv={model.home_adv_:+.3f} rho={model.rho_:+.3f}"
    )

    fx = [model.forecast(r.home, r.away) for r in test.itertuples()]
    lam_h = np.array([f.lambda_home for f in fx])
    lam_a = np.array([f.lambda_away for f in fx])
    p_cs_h = np.array([f.p_cs_home for f in fx])
    p_cs_a = np.array([f.p_cs_away for f in fx])
    hg = test["home_goals"].to_numpy()
    ag = test["away_goals"].to_numpy()

    cs_h, cs_a = (ag == 0).astype(float), (hg == 0).astype(float)
    brier = float(np.mean(np.concatenate([(p_cs_h - cs_h) ** 2, (p_cs_a - cs_a) ** 2])))
    base_rate = float(np.mean(np.concatenate([cs_h, cs_a])))
    brier_base = float(np.mean(np.concatenate([(base_rate - cs_h) ** 2, (base_rate - cs_a) ** 2])))

    print(f"\nholdout {holdout_season} ({len(test)} matches, params frozen at season start):")
    print(f"  clean-sheet Brier: model {brier:.4f} vs constant-rate baseline {brier_base:.4f}")
    print(
        f"  mean goals/match: predicted {float(np.mean(lam_h + lam_a)):.2f} vs actual {float(np.mean(hg + ag)):.2f}"
    )
    print(f"  home goals: predicted {float(lam_h.mean()):.2f} vs actual {float(hg.mean()):.2f}")
    print(f"  away goals: predicted {float(lam_a.mean()):.2f} vs actual {float(ag.mean()):.2f}")

    promoted = sorted(set(test["home"]) - set(model.attack_))
    if promoted:
        pa, pdf = model.promoted_prior()
        print(
            f"  promoted (prior-forecast) teams: {promoted} -> attack {pa:+.2f} defence {pdf:+.2f}"
        )

    print("\ntop of the fitted table (attack):")
    print(model.team_table().head(8).to_string(index=False, float_format=lambda v: f"{v:+.3f}"))


if __name__ == "__main__":
    evaluate_holdout()
