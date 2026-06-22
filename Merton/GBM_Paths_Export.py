"""
GBM_Paths_Export — GBM Asset Path Simulation Export
=================================================================
Run with: python Merton/GBM_Paths_Export.py

  Block 0: Imports & Setup
  Block 1: Merton Calculation (all 5 tickers) — V0, sigma_V, D, DD, Rating
  Block 2: GBM Path Simulation (N_PATHS=30, T=252 trading days)
  Block 3: Excel Export -> C:\\Python\\Outputs\\Reports\\DCF_Merton_MC\\GBM_Paths_{date}.xlsx
"""

# region Block 0 - Imports & Setup
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import os
import json
import importlib
import warnings
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import norm

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TICKER_LIST    = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]
CACHE_FOLDER   = r"C:\Python\Data\FMP\FMP_Cache"
OUTPUT_DIR     = r"C:\Python\Outputs\Reports\DCF_Merton_MC"
os.makedirs(OUTPUT_DIR, exist_ok=True)

N_PATHS = 30
T       = 252
TODAY   = date.today().strftime("%Y-%m-%d")

print(f"\n{'='*60}")
print(f"GBM Paths Export — {TODAY}")
print(f"{'='*60}")
# endregion


# region Block 1 - Helper Functions & Merton Calculation
def load_json(filename):
    """Load a JSON cache file from CACHE_FOLDER."""
    with open(os.path.join(CACHE_FOLDER, filename), "r", encoding="utf-8") as f:
        return json.load(f)


def merton_model(E, D, r, T_val, sigma_e, max_iter=1000, tol=1e-6):
    """Iterative Merton (1974) model. Returns V, sigma_v, dd, pd."""
    V       = E + D
    sigma_v = sigma_e * (E / V)
    for _ in range(max_iter):
        sqrt_t = np.sqrt(T_val)
        d1     = (np.log(V / D) + (r + 0.5 * sigma_v**2) * T_val) / (sigma_v * sqrt_t)
        d2     = d1 - sigma_v * sqrt_t
        e_mod  = V * norm.cdf(d1) - D * np.exp(-r * T_val) * norm.cdf(d2)
        v_new  = V * (E / e_mod)
        sv_new = sigma_e * (E / v_new)
        if abs(v_new - V) < tol and abs(sv_new - sigma_v) < tol:
            V, sigma_v = v_new, sv_new
            break
        V, sigma_v = v_new, sv_new
    sqrt_t = np.sqrt(T_val)
    dd     = (np.log(V / D) + (r - 0.5 * sigma_v**2) * T_val) / (sigma_v * sqrt_t)
    return {"V": V, "sigma_v": sigma_v, "dd": dd, "pd": float(norm.cdf(-dd))}


_RATING_THRESHOLDS = [
    ("AAA/AA", 8.0),
    ("A",      6.0),
    ("BBB",    4.0),
    ("BB",     2.0),
    ("B",      1.0),
]


def dd_to_rating(dd):
    for label, threshold in _RATING_THRESHOLDS:
        if dd >= threshold:
            return label
    return "CCC"


print("\nMerton calculation (all 5 tickers):")
print(f"  {'Ticker':<6} {'V0 (Mrd)':>10} {'D (Mrd)':>9} {'DD':>7} {'sigma_V':>9} {'Rating':<8}")
print(f"  {'-'*6} {'-'*10} {'-'*9} {'-'*7} {'-'*9} {'-'*8}")

ticker_params = {}
for tkr in TICKER_LIST:
    cfg     = importlib.import_module(f"Config.{tkr}")
    raw     = load_json(f"{tkr}_historical-price-eod_full.json")
    df      = pd.DataFrame(raw)
    df["date"] = pd.to_datetime(df["date"])
    prices  = df.sort_values("date").set_index("date")["close"]
    log_ret = np.log(prices / prices.shift(1)).dropna()
    sigma_e = float(log_ret.std() * np.sqrt(252))
    bs      = load_json(f"{tkr}_balance-sheet-statement.json")[0]
    km      = load_json(f"{tkr}_key-metrics.json")[0]
    E       = float(km.get("marketCap", 0) or 0)
    D       = float(bs.get("totalDebt",  0) or 0)
    r       = cfg.RISK_FREE_RATE
    T_cfg   = cfg.MATURITY
    m       = merton_model(E, D, r, T_cfg, sigma_e)
    rating  = dd_to_rating(m["dd"])
    ticker_params[tkr] = {
        "V0":      m["V"],
        "sigma_V": m["sigma_v"],
        "mu":      r,
        "D":       D,
        "dd":      m["dd"],
        "rating":  rating,
    }
    print(f"  {tkr:<6} {m['V']/1e9:>10.2f} {D/1e9:>9.2f} {m['dd']:>7.3f} "
          f"{m['sigma_v']:>9.1%} {rating:<8}")

# endregion


# region Block 2 - GBM Path Simulation
# GBM closed-form incremental discretisation:
#   A_{t+1} = A_t * exp((mu - 0.5*sigma_V^2)*dt + sigma_V*sqrt(dt)*Z)
# Equivalent cumulative form:
#   A_t = V0 * exp((mu - 0.5*sigma_V^2)*(t/T) + sigma_V * W_t)
# where W_t = cumsum of sqrt(dt)*Z_i (Brownian motion, iid increments)

print(f"\nSimulating {N_PATHS} paths x {T+1} days x {len(TICKER_LIST)} tickers ...")

np.random.seed(42)
dt = 1.0 / T
all_dfs = []

for tkr in TICKER_LIST:
    p  = ticker_params[tkr]
    V0 = p["V0"]
    mu = p["mu"]
    sv = p["sigma_V"]
    D  = p["D"]
    dd = round(p["dd"], 4)
    rt = p["rating"]

    # Z: (N_PATHS, T) iid N(0,1) increments
    Z = np.random.standard_normal((N_PATHS, T))

    # Log-return increments per step (drift + diffusion)
    log_inc = (mu - 0.5 * sv**2) * dt + sv * np.sqrt(dt) * Z  # (N_PATHS, T)

    # Cumulative log-path; prepend zero for day 0
    log_cum = np.hstack([np.zeros((N_PATHS, 1)), np.cumsum(log_inc, axis=1)])  # (N_PATHS, T+1)

    # Asset value paths in Bn USD
    asset_paths_bn = (V0 * np.exp(log_cum)) / 1e9  # (N_PATHS, T+1)

    # Vectorised DataFrame build
    path_ids = np.repeat(np.arange(1, N_PATHS + 1)[:, None], T + 1, axis=1)
    days     = np.tile(np.arange(T + 1), (N_PATHS, 1))

    df_tkr = pd.DataFrame({
        "ticker":        tkr,
        "path_id":       path_ids.ravel(),
        "day":           days.ravel(),
        "asset_value":   np.round(asset_paths_bn.ravel(), 6),
        "default_point": round(D / 1e9, 6),
        "dd":            dd,
        "rating":        rt,
    })
    all_dfs.append(df_tkr)
    print(f"  {tkr}: {len(df_tkr):,} rows generated")

df_gbm = pd.concat(all_dfs, ignore_index=True)
print(f"\nTotal shape: {df_gbm.shape}")
# endregion


# region Block 3 - Excel Export
xlsx_path = os.path.join(OUTPUT_DIR, f"GBM_Paths_{TODAY}.xlsx")
with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
    df_gbm.to_excel(writer, sheet_name="GBM_Paths", index=False)

print(f"\n=== Excel Export ===")
print(f"File:   {xlsx_path}")
print(f"Rows:   {len(df_gbm):,}   Columns: {df_gbm.shape[1]}")
print(f"        ({len(TICKER_LIST)} tickers x {N_PATHS} paths x {T+1} days)")
print(f"\nFirst 10 rows:")
print(df_gbm.head(10).to_string(index=False))
# endregion


# region Interpretation
print("\n=== Interpretation ===")
for tkr in TICKER_LIST:
    p = ticker_params[tkr]
    print(f">>> {tkr}: DD={p['dd']:.3f}  Rating={p['rating']}  "
          f"V0={p['V0']/1e9:.1f} Bn  D={p['D']/1e9:.2f} Bn  "
          f"sigma_V={p['sigma_V']:.1%}")

riskiest = min(ticker_params, key=lambda t: ticker_params[t]["dd"])
safest   = max(ticker_params, key=lambda t: ticker_params[t]["dd"])
print(f"\n>>> Highest risk:    {riskiest} (DD={ticker_params[riskiest]['dd']:.3f}) — "
      f"paths close to the default point")
print(f">>> Lowest risk:     {safest} (DD={ticker_params[safest]['dd']:.3f}) — "
      f"wide safety buffer")
print(f">>> Excel file ready: {len(df_gbm):,} rows, columns: "
      f"{list(df_gbm.columns)}")
# endregion


# region Legende
print("\n=== Legende ===")
print("V0            = Merton asset value at the valuation date (in Bn USD)")
print("D             = Default point = Total Debt (in Bn USD)")
print("sigma_V       = Asset volatility, iterated from equity volatility sigma_E")
print("mu            = Drift = risk-free rate (risk-neutral GBM drift)")
print("dt            = 1/252 (one trading day as a fraction of a year)")
print("Z             = Standard normal random variable (N(0,1), iid per step)")
print("log_inc       = (mu - 0.5*sigma_V^2)*dt + sigma_V*sqrt(dt)*Z  (log increment)")
print("asset_value   = GBM-simulated asset value on day t (in Bn USD)")
print("default_point = Constant threshold = D of the respective ticker (Bn USD)")
print("dd            = Distance to Default from the Merton calculation (constant per ticker)")
print("rating        = Credit rating from the DD mapping (AAA/AA>=8, A>=6, BBB>=4, BB>=2)")
print("path_id       = Path index (1 to 30)")
print("day           = Trading day within the simulation horizon (0 to 252)")
print("N_PATHS       = 30  (number of simulated GBM paths per ticker)")
print("T             = 252 (trading days = 1-year time horizon)")
print("Seed          = 42  (numpy.random.seed for reproducibility)")
# endregion
