"""
merton_core — Pure calculation functions for the Merton (1974) structural credit risk model.
No I/O, no side effects — safe to import for tests or from any script.
"""

import numpy as np
from scipy.stats import norm

# region Merton Model
def merton_model(E, D, r, T, sigma_e, max_iter=1000, tol=1e-6):
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

        e_model       = V * norm.cdf(d1) - D * np.exp(-r * T) * norm.cdf(d2)
        sigma_e_model = (V / E) * norm.cdf(d1) * sigma_v

        v_new       = V * (E / e_model)
        sigma_v_new = sigma_e * (E / v_new)

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


# region Rating & Credit Spread
RATING_TABLE = [
    ("AAA/AA",  8.0,  float("inf"),  30,   50),
    ("A",       6.0,  8.0,           60,   90),
    ("BBB",     4.0,  6.0,           120,  180),
    ("BB",      2.0,  4.0,           250,  400),
    ("B",       1.0,  2.0,           400,  650),
    ("CCC",     0.0,  1.0,           800,  1200),
]


def get_rating_info(dd):
    for rating, dd_min, dd_max, bps_lo, bps_hi in RATING_TABLE:
        if dd >= dd_min and (dd < dd_max or dd_max == float("inf")):
            return rating, bps_lo, bps_hi
    return "CCC", 800, 1200


def calculate_spread(pd_val, T, lgd=0.45):
    pd_lgd = min(pd_val * lgd, 0.9999)
    if pd_lgd <= 0:
        return 0.0
    return -np.log(1 - pd_lgd) / T
# endregion
