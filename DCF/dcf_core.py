"""
dcf_core — Pure calculation functions for the two-phase DCF valuation model.
No I/O, no side effects — safe to import for tests or from any script.

Deliberately free of any data-provider field names: callers hand in plain floats,
so the same functions work regardless of where the figures came from.
"""

from collections.abc import Sequence
from typing import TypedDict, cast

import numpy as np
import pandas as pd

# Equity Risk Premium (Damodaran estimate) — default for the CAPM cost of equity.
MARKET_PREMIUM: float = 0.055

# Fallback effective tax rate when no profitable year is available (U.S. federal rate).
DEFAULT_TAX_RATE: float = 0.21


# region DCF Core
class DcfParams(TypedDict):
    """Everything the two-phase DCF needs. All amounts in absolute USD."""
    fcf_start: float     # normalized FCF at t=0
    g1: float            # phase 1 growth (explicit forecast years)
    g2: float            # phase 2 growth (perpetual)
    wacc: float          # discount rate
    years: int           # number of explicit forecast years
    net_debt: float      # total debt minus cash
    shares: float        # shares outstanding


class DcfResult(TypedDict):
    ev: float
    equity: float
    value_per_share: float
    pv_terminal_value: float


def with_params(p: DcfParams, **overrides: float) -> DcfParams:
    """Copy of p with individual fields replaced — for sensitivity and simulation runs."""
    merged = dict(p)
    merged.update(overrides)
    return cast(DcfParams, merged)


def dcf_full(p: DcfParams) -> DcfResult:
    """
    Two-phase DCF: explicit forecast at g1, Gordon terminal value at g2.
    Returns all-nan when wacc <= g2 (terminal value undefined).
    """
    if p["wacc"] <= p["g2"]:
        nan = float("nan")
        return {"ev": nan, "equity": nan, "value_per_share": nan, "pv_terminal_value": nan}

    fcf_t  = p["fcf_start"]
    pv_sum = 0.0
    for t in range(1, p["years"] + 1):
        fcf_t   = fcf_t * (1 + p["g1"])
        pv_sum += fcf_t / (1 + p["wacc"]) ** t

    tv    = fcf_t * (1 + p["g2"]) / (p["wacc"] - p["g2"])
    pv_tv = tv / (1 + p["wacc"]) ** p["years"]
    ev    = pv_sum + pv_tv
    eq    = ev - p["net_debt"]
    vps   = eq / p["shares"] if p["shares"] > 0 else float("nan")

    return {"ev": ev, "equity": eq, "value_per_share": vps, "pv_terminal_value": pv_tv}


def dcf_schedule(p: DcfParams) -> tuple[list[dict[str, float]], DcfResult]:
    """
    Same model as dcf_full(), but also returns the year-by-year forecast table
    (Year, FCF, PV_FCF) for the base case output.
    """
    schedule: list[dict[str, float]] = []
    fcf_t = p["fcf_start"]
    for t in range(1, p["years"] + 1):
        fcf_t = fcf_t * (1 + p["g1"])
        schedule.append({
            "Year":   float(t),
            "FCF":    fcf_t,
            "PV_FCF": fcf_t / (1 + p["wacc"]) ** t,
        })
    return schedule, dcf_full(p)
# endregion


# region CAPM / WACC
def _log_returns(prices: pd.Series) -> pd.Series:
    """
    Log returns of a price series.
    The cast is needed because pandas-stubs types np.log() on a Series as ndarray,
    while it actually returns a Series.
    """
    return cast(pd.Series, np.log(prices / prices.shift(1))).dropna()


def calculate_beta(stock: pd.Series, market: pd.Series, window: int = 252) -> float:
    """Beta from log returns over the last `window` overlapping trading days."""
    ret_stk = _log_returns(stock)
    ret_mkt = _log_returns(market)

    common  = ret_stk.index.intersection(ret_mkt.index)[-window:]
    cov_mat = np.cov(np.asarray(ret_stk.loc[common], dtype=float),
                     np.asarray(ret_mkt.loc[common], dtype=float))
    return float(cov_mat[0, 1] / cov_mat[1, 1])


def cost_of_debt(interest_expense: float, total_debt: float) -> float:
    """Kd = interest expense / total debt."""
    if interest_expense <= 0 or total_debt <= 0:
        return 0.0
    return interest_expense / total_debt


def effective_tax_rate(
    tax_and_ebt: Sequence[tuple[float, float]],
    default: float = DEFAULT_TAX_RATE,
) -> float:
    """
    Average effective tax rate over the profitable years.
    Each element is (income tax expense, income before tax); loss years are ignored.
    """
    rates = [tax / ebt for tax, ebt in tax_and_ebt if ebt > 0 and tax > 0]
    return float(np.mean(rates)) if rates else default


def wacc_capm(
    beta: float,
    risk_free: float,
    kd: float,
    tax_rate: float,
    market_cap: float,
    total_debt: float,
    market_premium: float = MARKET_PREMIUM,
) -> dict[str, float]:
    """
    CAPM cost of equity plus after-tax cost of debt, weighted at market values.
    With no capital base (V <= 0) the WACC collapses to the cost of equity.
    """
    ke           = risk_free + beta * market_premium
    kd_after_tax = kd * (1 - tax_rate)

    v = market_cap + total_debt
    if v > 0:
        ev_ratio = market_cap / v
        dv_ratio = total_debt / v
        wacc     = ke * ev_ratio + kd_after_tax * dv_ratio
    else:
        ev_ratio = 1.0
        dv_ratio = 0.0
        wacc     = ke

    return {
        "beta":         beta,
        "ke":           ke,
        "kd":           kd,
        "tax_rate":     tax_rate,
        "kd_after_tax": kd_after_tax,
        "ev_ratio":     ev_ratio,
        "dv_ratio":     dv_ratio,
        "wacc_calc":    wacc,
    }
# endregion


# region Sensitivity
def sensitivity_matrix(
    p: DcfParams,
    wacc_range: Sequence[float],
    g1_range: Sequence[float],
) -> list[list[float]]:
    """Value per share for every (WACC, g1) combination — rows = WACC, columns = g1."""
    return [
        [dcf_full(with_params(p, wacc=w, g1=g))["value_per_share"] for g in g1_range]
        for w in wacc_range
    ]


def g2_sensitivity(
    p: DcfParams,
    g2_range: Sequence[float],
    g2_base: float,
) -> list[dict[str, float]]:
    """
    Value per share across terminal growth rates, plus the deviation from the
    g2_base run in percent. Returns one dict per g2 value: g2, value_per_share, delta_pct.
    """
    values = {g2: dcf_full(with_params(p, g2=g2))["value_per_share"] for g2 in g2_range}
    base   = values.get(g2_base, float("nan"))

    rows: list[dict[str, float]] = []
    for g2 in g2_range:
        value = values[g2]
        if base and not np.isnan(base) and not np.isnan(value):
            delta = (value / base - 1) * 100
        else:
            delta = float("nan")
        rows.append({"g2": g2, "value_per_share": value, "delta_pct": delta})
    return rows
# endregion


# region Monte Carlo
def simulate_dcf(
    p: DcfParams,
    n: int,
    wacc_std: float,
    growth_std: float,
    fcf_std_factor: float,
    seed: int = 42,
) -> np.ndarray:
    """
    Monte Carlo over WACC, phase-1 growth and starting FCF (all normal).
    WACC is clipped at 4% and growth at 0%; runs with wacc <= g2 are dropped.
    Returns the cleaned array of value-per-share outcomes.

    Uses the legacy np.random.seed API on purpose: it keeps results identical to
    the figures published in the README.
    """
    np.random.seed(seed)
    wacc_sim = np.random.normal(p["wacc"], wacc_std, n)
    g1_sim   = np.random.normal(p["g1"], growth_std, n)
    fcf0_sim = np.random.normal(p["fcf_start"], abs(p["fcf_start"]) * fcf_std_factor, n)

    wacc_sim = np.clip(wacc_sim, 0.04, None)
    g1_sim   = np.clip(g1_sim, 0.00, None)

    raw = np.array([
        dcf_full(with_params(p, wacc=w, g1=g, fcf_start=f))["value_per_share"]
        for w, g, f in zip(wacc_sim, g1_sim, fcf0_sim)
    ])
    return raw[~np.isnan(raw)]
# endregion


# region Classification & Multiples
def cagr(newest: float, oldest: float, periods: int) -> float:
    """Compound annual growth rate; nan when the ratio is not positive."""
    if oldest == 0 or periods <= 0 or (newest / oldest) <= 0:
        return float("nan")
    return (newest / oldest) ** (1 / periods) - 1


def classify_valuation(upside_pct: float, threshold: float = 10.0) -> str:
    """UNDERVALUED / OVERVALUED / FAIR based on the upside in percent."""
    if upside_pct > threshold:
        return "UNDERVALUED"
    if upside_pct < -threshold:
        return "OVERVALUED"
    return "FAIR"


def rate_multiple(value: float, lo: float, hi: float) -> str:
    """CHEAP / FAIR / EXPENSIVE against a benchmark band."""
    if np.isnan(value):
        return "N/A"
    if value < lo:
        return "CHEAP"
    if value <= hi:
        return "FAIR"
    return "EXPENSIVE"


def compute_multiples(
    ev: float,
    ebitda: float,
    revenue: float,
    price: float,
    net_income: float,
    shares: float,
) -> dict[str, float]:
    """EV/EBITDA, P/E and EV/Sales; nan where the denominator is not positive."""
    return {
        "EV/EBITDA": ev / ebitda if ebitda > 0 else float("nan"),
        "P/E":       price / (net_income / shares) if net_income > 0 and shares > 0 else float("nan"),
        "EV/Sales":  ev / revenue if revenue > 0 else float("nan"),
    }
# endregion
