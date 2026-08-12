"""
merton_core — Pure calculation functions for the Merton (1974) structural credit risk model.
No I/O, no side effects — safe to import for tests or from any script.
"""

import numpy as np
from scipy.stats import norm

# ----------------------------------------------------------------------------
# region MERTON MODEL
# ----------------------------------------------------------------------------
def merton_model(
    E: float, D: float, r: float, T: float, sigma_e: float,
    max_iter: int = 1000, tol: float = 1e-6,
) -> dict[str, float]:
    """
    Iterative Merton (1974) model.
    Returns dict: V, sigma_v, dd, pd, el.
    """
    V       = E + D
    sigma_v = sigma_e * (E / V)

    for _ in range(max_iter):
        sqrt_t = np.sqrt(T)
        d1     = (np.log(V / D) + (r + 0.5 * sigma_v ** 2) * T) / (sigma_v * sqrt_t)
        d2     = d1 - sigma_v * sqrt_t

        n_d1    = norm.cdf(d1)
        e_model = V * n_d1 - D * np.exp(-r * T) * norm.cdf(d2)

        # Both defining equations of the model are used, not just the first:
        #   E     = V*N(d1) - D*e^(-rT)*N(d2)      -> update of V
        #   sigma_E = (V/E) * N(d1) * sigma_V      -> update of sigma_V
        # Solving the second for sigma_V gives the N(d1) term below. Dropping it
        # would be the "naive" approximation of Bharath/Shumway (2008), a different
        # method from the iterative KMV procedure this module documents. For firms
        # far from the default boundary N(d1) is ~1 and both coincide; close to the
        # boundary they do not.
        v_new       = V * (E / e_model)
        sigma_v_new = sigma_e * E / (v_new * n_d1)

        converged = abs(v_new - V) < tol and abs(sigma_v_new - sigma_v) < tol
        V, sigma_v = v_new, sigma_v_new
        if converged:
            break

    sqrt_t = np.sqrt(T)
    dd     = (np.log(V / D) + (r - 0.5 * sigma_v ** 2) * T) / (sigma_v * sqrt_t)
    pd_val = float(norm.cdf(-dd))
    el     = pd_val * D * 0.45   # LGD assumption 45%

    return {"V": V, "sigma_v": sigma_v, "dd": dd, "pd": pd_val, "el": el}
# endregion


# ----------------------------------------------------------------------------
# region DD BANDS & CREDIT SPREAD
# ----------------------------------------------------------------------------
# Buckets for reporting DD, nothing more. They used to carry rating letters -
# AAA/AA, BBB, CCC - which made a bucket boundary look like a credit opinion and
# invited a comparison against agency ratings that the model cannot support.
#
# The edges are still chosen rather than derived, but as bands that is no longer
# a claim: any histogram picks its own. Estimating where default risk actually
# changes needs observed defaults across many firms, which is a different project
# (credit-risk-validation), not a better set of cut-offs here.
DD_BANDS: list[tuple[str, float, float]] = [
    ("DD > 8",  8.0,  float("inf")),
    ("DD 6-8",  6.0,  8.0),
    ("DD 4-6",  4.0,  6.0),
    ("DD 2-4",  2.0,  4.0),
    ("DD 1-2",  1.0,  2.0),
    ("DD < 1",  0.0,  1.0),
]

BAND_LABELS: list[str] = [label for label, _lo, _hi in DD_BANDS]


def dd_band(dd: float) -> str:
    """The reporting band a Distance to Default falls in."""
    for label, dd_min, dd_max in DD_BANDS:
        if dd >= dd_min and (dd < dd_max or dd_max == float("inf")):
            return label
    return DD_BANDS[-1][0]


def calculate_spread(pd_val: float, T: float, lgd: float = 0.45) -> float:
    pd_lgd = min(pd_val * lgd, 0.9999)
    if pd_lgd <= 0:
        return 0.0
    return -np.log(1 - pd_lgd) / T
# endregion
