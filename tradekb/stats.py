"""Performance statistics over a list of R multiples. Pure functions.

Expectancy is reported as mean R. With breakeven trades counted at their actual
R this equals (win rate x avg win) - (loss rate x |avg loss|) + (BE rate x avg BE),
i.e. the textbook formula plus the small contribution breakevens actually make.

Confidence intervals are percentile bootstraps with a FIXED seed so the same
data always produces the same report. They quantify sampling noise only; they
cannot account for regime change, selection bias, or look-ahead in the records.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import fmean, median

WIN, LOSS, BE = "win", "loss", "breakeven"


@dataclass
class Summary:
    n: int
    wins: int
    losses: int
    breakevens: int
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    payoff: float | None
    expectancy: float | None
    median: float | None
    total: float
    profit_factor: float | None
    max_win_streak: int
    max_loss_streak: int
    max_drawdown: float
    ci: tuple[float, float] | None
    evidence: str


@dataclass
class Comparison:
    a: Summary
    b: Summary
    diff: float | None
    ci: tuple[float, float] | None
    verdict: str


def classify(r: float, band: float) -> str:
    return WIN if r > band else LOSS if r < -band else BE


def streaks(kinds: list[str]) -> tuple[int, int]:
    """Longest win and loss runs. A breakeven ends both runs."""
    best = {WIN: 0, LOSS: 0}
    run_kind, run = None, 0
    for kind in kinds:
        run = run + 1 if kind == run_kind else 1
        run_kind = kind
        if kind in best:
            best[kind] = max(best[kind], run)
    return best[WIN], best[LOSS]


def max_drawdown(rs: list[float]) -> float:
    """Largest peak-to-trough decline of cumulative R, starting from 0. Order matters: pass chronologically."""
    cum = peak = worst = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    return worst


def _interval(samples: list[float], confidence: float) -> tuple[float, float]:
    samples.sort()
    alpha = (1 - confidence) / 2
    lo = samples[int(alpha * len(samples))]
    hi = samples[min(len(samples) - 1, int((1 - alpha) * len(samples)))]
    return lo, hi


def bootstrap_mean_ci(rs: list[float], cfg: dict) -> tuple[float, float]:
    b = cfg["bootstrap"]
    rng = random.Random(b["seed"])
    n = len(rs)
    means = [fmean(rng.choices(rs, k=n)) for _ in range(b["resamples"])]
    return _interval(means, b["confidence"])


def bootstrap_diff_ci(a: list[float], b_: list[float], cfg: dict) -> tuple[float, float]:
    b = cfg["bootstrap"]
    rng = random.Random(b["seed"])
    na, nb = len(a), len(b_)
    diffs = [fmean(rng.choices(a, k=na)) - fmean(rng.choices(b_, k=nb)) for _ in range(b["resamples"])]
    return _interval(diffs, b["confidence"])


def evidence_tier(n: int, conditions: int, cfg: dict) -> str:
    t = cfg["evidence_tiers"]
    if n >= t["higher_min_n"] and conditions >= t["higher_min_conditions"]:
        return "HIGHER"
    if n >= t["moderate_min_n"]:
        return "MODERATE"
    return "LOW"


def summarize(rs: list[float], cfg: dict, conditions: int = 0) -> Summary:
    n = len(rs)
    tier = evidence_tier(n, conditions, cfg)
    if n == 0:
        return Summary(0, 0, 0, 0, None, None, None, None, None, None, 0.0, None, 0, 0, 0.0, None, tier)

    band = cfg["breakeven_band_r"]
    kinds = [classify(r, band) for r in rs]
    win_rs = [r for r, k in zip(rs, kinds) if k == WIN]
    loss_rs = [r for r, k in zip(rs, kinds) if k == LOSS]
    avg_win = fmean(win_rs) if win_rs else None
    avg_loss = fmean(loss_rs) if loss_rs else None

    enough = n >= cfg["min_n_for_ratios"]
    gross_profit = sum(r for r in rs if r > 0)
    gross_loss = -sum(r for r in rs if r < 0)
    profit_factor = gross_profit / gross_loss if enough and gross_loss > 0 else None
    payoff = avg_win / abs(avg_loss) if enough and avg_win is not None and avg_loss else None

    win_streak, loss_streak = streaks(kinds)
    ci = bootstrap_mean_ci(list(rs), cfg) if n >= cfg["min_n_for_ci"] else None

    return Summary(
        n=n, wins=len(win_rs), losses=len(loss_rs), breakevens=n - len(win_rs) - len(loss_rs),
        win_rate=len(win_rs) / n, avg_win=avg_win, avg_loss=avg_loss, payoff=payoff,
        expectancy=fmean(rs), median=median(rs), total=sum(rs), profit_factor=profit_factor,
        max_win_streak=win_streak, max_loss_streak=loss_streak, max_drawdown=max_drawdown(rs),
        ci=ci, evidence=tier,
    )


def compare(a: list[float], b: list[float], cfg: dict, cond_a: int = 0, cond_b: int = 0) -> Comparison:
    sa, sb = summarize(a, cfg, cond_a), summarize(b, cfg, cond_b)
    floor = cfg["min_n_for_ci"]
    if min(sa.n, sb.n) < floor:
        return Comparison(sa, sb, None, None,
                          f"INSUFFICIENT DATA: need at least {floor} trades on each side for any interval "
                          f"(have {sa.n} vs {sb.n}). Do not declare a winner.")
    diff = sa.expectancy - sb.expectancy
    ci = bootstrap_diff_ci(a, b, cfg)
    moderate = cfg["evidence_tiers"]["moderate_min_n"]
    if ci[0] > 0 or ci[1] < 0:
        leader = "A" if diff > 0 else "B"
        if min(sa.n, sb.n) >= moderate:
            verdict = (f"{leader} shows higher expectancy and the interval excludes zero. "
                       f"Evidence, not proof: confirm on trades recorded after this comparison.")
        else:
            verdict = (f"Interval excludes zero in favour of {leader}, but each side has fewer than "
                       f"{moderate} trades. Treat as a hypothesis to keep testing, not a result.")
    else:
        verdict = "NO DETECTABLE DIFFERENCE: the interval includes zero. Do not declare a winner."
    return Comparison(sa, sb, diff, ci, verdict)


def histogram(rs: list[float], band: float) -> list[tuple[str, int]]:
    """R distribution. The first bin isolates losses beyond -1.1R: slippage, gaps or a violated stop."""
    bins = [
        ("< -1.1R (loss exceeded 1R)", lambda r: r < -1.1),
        ("-1.1R to BE", lambda r: -1.1 <= r < -band),
        ("breakeven", lambda r: -band <= r <= band),
        ("BE to +1R", lambda r: band < r < 1),
        ("+1R to +2R", lambda r: 1 <= r < 2),
        ("+2R to +3R", lambda r: 2 <= r < 3),
        (">= +3R", lambda r: r >= 3),
    ]
    return [(label, sum(1 for r in rs if test(r))) for label, test in bins]
