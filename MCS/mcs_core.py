"""
mcs_core — Pure calculation for the Monte Carlo risk model.

Extracted from Monte_Carlo_Sim.py, which runs its whole analysis at import time
and therefore cannot be unit tested at all. Everything here takes numbers and
returns numbers: no file access, no configuration, no plotting.

The module exists for one reason above the others. The conversion from a
simulated value per share to a loss appeared inline at five places in the script,
each with its own copy of the same three lines. When the floor was corrected from
-2.0 to 0.0 — a stock cannot lose more than everything, so a loss above 100% is
impossible — one of the five was missed, and the tornado analysis kept reporting
a base case that disagreed with the headline figure by ten percentage points.
Nothing caught it; the two numbers simply sat in different blocks of output.

One function, called five times, cannot drift apart from itself.
"""

from typing import NamedTuple, Optional, TypedDict

import numpy as np
from scipy.stats import norm

# Bounds on the ratio of simulated value per share to market price.
#
# The floor is the economically binding one: shareholders have limited liability,
# so the value of a share cannot fall below zero and a loss cannot exceed 100%.
# The cap is a modelling convention — a simulation that produces a six-fold value
# is telling you the input distribution has a fat tail, not that the company is
# worth that much, and letting it through would dominate the portfolio average.
REL_FLOOR = 0.0
REL_CAP = 5.0


class RiskMeasures(NamedTuple):
    """Loss quantiles of one simulated distribution, in percent."""
    var_95: float
    var_99: float
    cvar_99: float


class DistributionSpec(TypedDict, total=False):
    """
    Parameters of one input distribution.

    Which keys are present depends on "type" — a normal has "std", a uniform has
    "min"/"max". total=False keeps that flexible while still typing every value as
    a number, instead of the dict[str, object] mypy would infer from the literal.
    """
    type: str
    std: float
    min: float
    max: float
    sigma: float
    alpha: float
    beta_param: float


DISTRIBUTIONS: dict[str, DistributionSpec] = {
    "WACC": {"type": "normal",     "std": 0.015},
    "g1":   {"type": "triangular", "min": 0.00, "max": 0.12},
    "FCF":  {"type": "lognormal",  "sigma": 0.25},
    "g2":   {"type": "uniform",    "min": 0.015, "max": 0.035},
    "LGD":  {"type": "beta",       "alpha": 2,   "beta_param": 3},
    "rho":  {"type": "uniform",    "min": 0.10,  "max": 0.40},
}


# ----------------------------------------------------------------------------
# region VALUE, LOSS AND RISK MEASURES
# ----------------------------------------------------------------------------
def relative_value(
    value_per_share: np.ndarray,
    price: float,
    floor: float = REL_FLOOR,
    cap: float = REL_CAP,
) -> np.ndarray:
    """
    Simulated value per share as a multiple of the market price, bounded.

    A simulation that produced no usable value (NaN, or a price of zero) is set
    to 1.0 rather than dropped: it means the model could not say anything about
    that scenario, and treating "no information" as "total loss" would invent a
    default that the model never predicted.
    """
    unusable = np.isnan(value_per_share) | (price == 0)
    # np.where evaluates both branches, so dividing by the raw price would still
    # raise a divide-by-zero warning even though the result is thrown away. The
    # calling script silences all warnings globally, which would hide it — and a
    # warning nobody can see is worse than one that never fires.
    divisor = price if price != 0 else 1.0
    ratio = np.where(unusable, 1.0, value_per_share / divisor)
    return np.clip(ratio, floor, cap)


def loss_percent(relative: np.ndarray) -> np.ndarray:
    """
    Loss in percent of the starting value, from a bounded relative value.

    With `relative` floored at zero this can never exceed 100. That is not a
    coincidence to be rediscovered later but the reason the floor exists, so the
    tests assert it directly.
    """
    return 100.0 - relative * 100.0


def risk_measures(losses: np.ndarray) -> RiskMeasures:
    """
    VaR at 95% and 99%, and the conditional VaR beyond the 99% point.

    CVaR is the mean of the losses at or above VaR 99 and is therefore always at
    least as large as VaR 99 — a useful invariant, because a CVaR below its VaR
    means the tail was taken from the wrong side of the distribution.
    """
    var_95 = float(np.percentile(losses, 95))
    var_99 = float(np.percentile(losses, 99))
    tail = losses[losses >= var_99]
    cvar_99 = float(np.mean(tail)) if tail.size else var_99
    return RiskMeasures(var_95=var_95, var_99=var_99, cvar_99=cvar_99)


def diversification_benefit(portfolio_std: float, average_single_std: float) -> float:
    """
    How much of the average single-name volatility the portfolio removes.

    Zero when the names move together, approaching one as they offset. Returns
    0.0 for an average of zero rather than dividing — a portfolio of constants
    has no benefit to measure.
    """
    if average_single_std <= 0:
        return 0.0
    return 1.0 - portfolio_std / average_single_std
# endregion


# ----------------------------------------------------------------------------
# region VASICEK CREDIT MODEL
# ----------------------------------------------------------------------------
def vasicek_conditional_pd(
    unconditional_pd: float,
    rho: float,
    systematic: np.ndarray,
) -> np.ndarray:
    """
    Default probability conditional on the systematic factor.

    Single-factor model: a borrower's asset value is sqrt(rho)*Z + sqrt(1-rho)*e,
    and default occurs below the threshold implied by the unconditional PD. Under
    a bad draw of Z every borrower becomes more likely to default at once, which
    is what makes the portfolio loss distribution skewed rather than binomial.
    """
    threshold = norm.ppf(unconditional_pd)
    conditional: np.ndarray = norm.cdf(
        (threshold - np.sqrt(rho) * systematic) / np.sqrt(1 - rho))
    return conditional


def correlation_matrix(size: int, rho: float) -> np.ndarray:
    """Equicorrelation matrix: 1 on the diagonal, `rho` everywhere else."""
    matrix = np.full((size, size), float(rho))
    np.fill_diagonal(matrix, 1.0)
    return matrix
# endregion


# ----------------------------------------------------------------------------
# region INPUT DISTRIBUTIONS
# ----------------------------------------------------------------------------
def sample_distribution(
    name: str,
    mu: float,
    n: int,
    seed: Optional[int] = None,
) -> np.ndarray:
    """
    Draw n independent samples from the configured distribution for `name`.

    Uses the legacy global np.random seed rather than a Generator: the published
    figures were produced with it, and switching would change every number in the
    README without changing the model.
    """
    if seed is not None:
        np.random.seed(seed)
    dist = DISTRIBUTIONS[name]
    dtype = dist["type"]
    if dtype == "normal":
        return np.random.normal(mu, dist["std"], n)
    elif dtype == "triangular":
        return np.random.triangular(
            dist["min"],
            np.clip(mu, dist["min"] + 1e-9, dist["max"] - 1e-9),
            dist["max"], n)
    elif dtype == "lognormal":
        # A lognormal cannot represent a negative mean. INTC's normalised free
        # cash flow is negative, so the fallback keeps the simulation running and
        # the calling script reports the model as inapplicable for that ticker.
        if mu <= 0:
            return np.random.normal(mu, abs(mu) * dist["sigma"], n)
        return np.random.lognormal(np.log(mu) - 0.5 * dist["sigma"] ** 2, dist["sigma"], n)
    elif dtype == "uniform":
        return np.random.uniform(dist["min"], dist["max"], n)
    elif dtype == "beta":
        a, b = dist["alpha"], dist["beta_param"]
        raw = np.random.beta(a, b, n)
        expected = a / (a + b)
        return np.clip(raw * mu / expected, 0.0, 1.0) if expected > 0 else raw
    else:
        return np.full(n, mu)


def apply_distribution(name: str, mu: float, z_arr: np.ndarray) -> np.ndarray:
    """
    Map standard normal draws onto the target distribution, keeping their ranks.

    This is the Gaussian copula step: correlation is generated once among normal
    variables, then each margin is transformed separately. Drawing each parameter
    from its own distribution directly would lose the correlation between them.
    """
    dist = DISTRIBUTIONS[name]
    dtype = dist["type"]
    if dtype == "normal":
        return mu + z_arr * dist["std"]
    elif dtype == "lognormal":
        if mu <= 0:
            return mu + abs(mu) * dist["sigma"] * z_arr
        return mu * np.exp(dist["sigma"] * z_arr - 0.5 * dist["sigma"] ** 2)
    elif dtype == "triangular":
        u = norm.cdf(z_arr)
        a = dist["min"]
        b = dist["max"]
        c = np.clip(float(mu), a + 1e-9, b - 1e-9)
        fc = (c - a) / (b - a)
        return np.where(u < fc,
                        a + np.sqrt(np.maximum(u * (b - a) * (c - a), 0.0)),
                        b - np.sqrt(np.maximum((1 - u) * (b - a) * (b - c), 0.0)))
    elif dtype == "uniform":
        return dist["min"] + norm.cdf(z_arr) * (dist["max"] - dist["min"])
    elif dtype == "beta":
        from scipy.stats import beta as _beta
        a, b = dist["alpha"], dist["beta_param"]
        u = np.clip(norm.cdf(z_arr), 1e-6, 1 - 1e-6)
        raw = _beta.ppf(u, a, b)
        expected = a / (a + b)
        return np.clip(raw * mu / expected, 0.0, 1.0) if expected > 0 else raw
    else:
        return np.full(len(z_arr), float(mu))
# endregion


# ----------------------------------------------------------------------------
# region VECTORISED DCF
# ----------------------------------------------------------------------------
def dcf_array(
    wacc_arr: np.ndarray,
    g1_arr: np.ndarray,
    fcf_start_arr: np.ndarray,
    g2_arr: np.ndarray,
    prog: float,
    nd: float,
    shares: float,
) -> np.ndarray:
    """
    Two-phase DCF over whole simulation arrays; equity value per share.

    Scenarios where the discount rate does not exceed the terminal growth rate
    return NaN. The Gordon formula divides by (wacc - g2) and would otherwise
    produce a negative or explosive terminal value that looks like a result.
    """
    valid = wacc_arr > g2_arr
    fcf_t = np.where(fcf_start_arr > -1e13, fcf_start_arr, 0.0)
    pv_sum = np.zeros(len(wacc_arr))
    for t in range(1, int(prog) + 1):
        fcf_t = fcf_t * (1 + g1_arr)
        pv_sum += fcf_t / (1 + wacc_arr) ** t
    tv = np.where(valid, fcf_t * (1 + g2_arr) / (wacc_arr - g2_arr), 0.0)
    pv_tv = np.where(valid, tv / (1 + wacc_arr) ** prog, 0.0)
    equity = pv_sum + pv_tv - nd
    divisor = shares if shares > 0 else 1.0     # see relative_value on np.where
    per_share = np.where(shares > 0, equity / divisor, np.nan)
    return np.where(valid, per_share, np.nan)
# endregion
