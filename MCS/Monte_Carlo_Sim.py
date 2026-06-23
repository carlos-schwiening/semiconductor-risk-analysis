"""
Monte_Carlo_Sim — Quantitative Portfolio Risk Model (DCF + Merton)
======================================================================
Run with: python MCS/Monte_Carlo_Sim.py

  Block 0:  Imports & Setup
  Block 1:  Portfolio Setup (PD via Merton, Vasicek parameters)
  Block 2:  Vasicek Simulation (10,000 scenarios, vectorized)
  Block 3:  Risk Measures (EL, UL, VaR, CVaR, Risk Capital)
  Block 4:  Visualization + HTML Report (Vasicek)
  Block 5:  Configurable Distributions (DISTRIBUTIONS + sample_distribution)
  Block 6:  Correlated Simulation with Cholesky (5 tickers, Gaussian Copula)
  Block 7:  Macro Scenario Overlay (Recession / Base / Boom)
  Block 8:  Portfolio VaR DCF (VaR95, VaR99, CVaR, diversification effect, per-ticker risk)
  Block 8b: QCOM Dashboard Chart (distribution + parameter histograms)
  Block 9:  Convergence Test (VaR99 at N=100…10,000)
  Block 10: Tornado Chart of Uncertainty (parameter sensitivity)
  Block 11: Excel Export (MCS_Results_{TICKER}_{date}.xlsx)
"""

# ─────────────────────────────────────────────────────────────
ACTIVE_CONFIG = "MCHP"  # Change ticker: MCHP | INTC | ON | QCOM | MPWR
# ─────────────────────────────────────────────────────────────


# region Block 0 - Imports & Setup
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import os
import glob
import json
import importlib
import warnings
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.stats import norm

warnings.filterwarnings("ignore")

debug = False

# Project root = semiconductor-risk-analysis/ (1 level up from MCS/)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

config            = importlib.import_module(f"Config.{ACTIVE_CONFIG}")
TICKER            = config.TICKER
COMPANY       = config.COMPANY
RISK_FREE_RATE = config.RISK_FREE_RATE
MATURITY          = config.MATURITY

CACHE_FOLDER  = r"C:\Python\Data\FMP\FMP_Cache"
OUTPUT_DIR = r"C:\Python\Outputs\Visualisierung"
os.makedirs(OUTPUT_DIR, exist_ok=True)

from plot_style import LAYOUT, BLUE_1, BLUE_2, BLUE_3, ORANGE_1, ORANGE_2, ORANGE_3, GRAY_1
BG     = "#FFFFFF"; TEXT = "#1A1A1A"; BORDER = "#E5E5E5"; TEXT_MUTED = "#9CA3AF"

# endregion


# region Block 1 - Portfolio Setup


def _load_json(filename):
    with open(os.path.join(CACHE_FOLDER, filename), "r", encoding="utf-8") as f:
        return json.load(f)


def merton_model(E, D, r, T, sigma_e, max_iter=1000, tol=1e-6):
    """Iterative Merton (1974) model. Returns dict: V, sigma_v, dd, pd, el."""
    V       = E + D
    sigma_v = sigma_e * (E / V)
    for _ in range(max_iter):
        sqrt_t = np.sqrt(T)
        d1     = (np.log(V / D) + (r + 0.5 * sigma_v ** 2) * T) / (sigma_v * sqrt_t)
        d2     = d1 - sigma_v * sqrt_t
        e_mod  = V * norm.cdf(d1) - D * np.exp(-r * T) * norm.cdf(d2)
        sv_mod = (V / E) * norm.cdf(d1) * sigma_v
        v_new  = V * (E / e_mod)
        sv_new = sigma_e * (E / v_new)
        if abs(v_new - V) < tol and abs(sv_new - sigma_v) < tol:
            V, sigma_v = v_new, sv_new
            break
        V, sigma_v = v_new, sv_new
    sqrt_t = np.sqrt(T)
    dd     = (np.log(V / D) + (r - 0.5 * sigma_v ** 2) * T) / (sigma_v * sqrt_t)
    pd_val = float(norm.cdf(-dd))
    return {"V": V, "sigma_v": sigma_v, "dd": dd, "pd": pd_val,
            "el": pd_val * D * 0.45}


# ── Load Merton PD for the active company ────────────────
_prices_raw = _load_json(f"{TICKER}_historical-price-eod_full.json")
_df         = pd.DataFrame(_prices_raw)
_df["date"] = pd.to_datetime(_df["date"])
_df         = _df.sort_values("date").set_index("date")
_prices     = _df["close"]
_log_ret    = np.log(_prices / _prices.shift(1)).dropna()
_sigma_e    = float(_log_ret.std() * np.sqrt(252))

_bs         = _load_json(f"{TICKER}_balance-sheet-statement.json")[0]
_km         = _load_json(f"{TICKER}_key-metrics.json")[0]
_total_debt = float(_bs.get("totalDebt",  0) or 0)
_market_cap = float(_km.get("marketCap",  0) or 0)

_merton   = merton_model(_market_cap, _total_debt,
                         RISK_FREE_RATE, MATURITY, _sigma_e)
pd_merton = _merton["pd"]
pd_floor_applied = pd_merton < 1e-6
if pd_floor_applied:
    pd_merton = 0.001  # Minimum PD: DD very high → hypothetical portfolio

# ── Portfolio parameters ───────────────────────────────────────
N_LOANS      = 100
EXPOSURE     = 1.0 / N_LOANS   # equally weighted portfolio, normalized to 1
LGD          = 0.45
SIMULATIONS = 10000
RHO          = 0.20               # asset correlation (Basel II standard)
pd_portfolio = pd_merton

print(f"\n{'='*60}")
print(f"=== Vasicek Portfolio Model — {TICKER} ({COMPANY}) ===")
print(f"{'='*60}")
print(f"Merton DD:       {_merton['dd']:.4f}")
print(f"PD (Merton):     {_merton['pd']:.6%}"
      + (" → floor 0.1% applied (DD very high, hypothetical portfolio)"
         if pd_floor_applied else ""))
print(f"PD (Portfolio):  {pd_merton:.4%}")
print(f"Asset Corr. ρ:   {RHO:.0%}")
print(f"N Loans:         {N_LOANS}  (equally weighted, Exposure = {EXPOSURE:.1%})")
print(f"LGD:             {LGD:.0%}")
print(f"Simulations:     {SIMULATIONS:,}")

# endregion


# region Block 2 - Vasicek Simulation
# ─────────────────────────────────────────────────────────────
# Single-factor Vasicek model:
#   Borrower i: X_i = sqrt(ρ)·Z + sqrt(1-ρ)·ε_i
#   Default when X_i < N_inv(PD)
#   Conditional PD: P(default | Z) = N( (N_inv(PD) - sqrt(ρ)·Z) / sqrt(1-ρ) )
# ─────────────────────────────────────────────────────────────

np.random.seed(42)

# Systematic factor: Z ~ N(0,1), one value per simulation
Z_sys = np.random.normal(0, 1, SIMULATIONS)

# Conditional PD for each simulation
_pd_inv  = norm.ppf(pd_portfolio)
_sqrt_rho = np.sqrt(RHO)
_sqrt_1rho = np.sqrt(1 - RHO)
pd_cond  = norm.cdf((_pd_inv - _sqrt_rho * Z_sys) / _sqrt_1rho)  # shape (SIMULATIONS,)

# Bernoulli draws: U ~ Uniform(0,1), default when U < pd_cond
# U shape: (SIMULATIONS, N_LOANS) — vectorized, no Python loop
U        = np.random.uniform(0, 1, size=(SIMULATIONS, N_LOANS))
defaults = (U < pd_cond[:, np.newaxis]).astype(np.float32)  # shape (SIMULATIONS, N_LOANS)

portfolio_losses = defaults.sum(axis=1) * EXPOSURE * LGD  # shape (SIMULATIONS,), [0, LGD]

print(f"\nSimulation complete. "
      f"Number of scenarios with at least 1 default: "
      f"{int(np.sum(portfolio_losses > 0)):,} / {SIMULATIONS:,}")

# endregion


# region Block 3 - Calculate Risk Measures

EL       = float(np.mean(portfolio_losses))
UL       = float(np.std(portfolio_losses))
VaR_99   = float(np.percentile(portfolio_losses, 99))
VaR_999  = float(np.percentile(portfolio_losses, 99.9))
CVaR_99  = float(np.mean(portfolio_losses[portfolio_losses >= VaR_99]))
RC       = VaR_999 - EL

print(f"\n{'─'*40}")
print(f"EL:              {EL:.4%}")
print(f"UL (Std Dev):    {UL:.4%}")
print(f"VaR 99%:         {VaR_99:.4%}")
print(f"VaR 99.9%:       {VaR_999:.4%}")
print(f"CVaR 99%:        {CVaR_99:.4%}")
print(f"Risk Capital:    {RC:.4%}")
rc_el = RC / EL if EL > 0 else float("nan")
print(f"RC / EL Ratio:   {rc_el:.1f}x" if not np.isnan(rc_el) else "RC / EL Ratio:   n/a (EL=0)")

# endregion


# region Block 4 - Risk Measure Scaling
# ────────────────────────────────────────────────────────────
# The Vasicek loss-distribution chart (PNG) and the standalone HTML
# report were removed. Only ul_pct is retained below because the
# Interpretation block references it (UL_portfolio).
# ────────────────────────────────────────────────────────────

ul_pct = UL * 100

# endregion


# region Block 5 - Configurable Distributions

N_SIM = 10_000

DISTRIBUTIONS = {
    "WACC": {"type": "normal",     "std": 0.015},
    "g1":   {"type": "triangular", "min": 0.00, "max": 0.12},
    "FCF":  {"type": "lognormal",  "sigma": 0.25},
    "g2":   {"type": "uniform",    "min": 0.015, "max": 0.035},
    "LGD":  {"type": "beta",       "alpha": 2,   "beta_param": 3},
    "rho":  {"type": "uniform",    "min": 0.10,  "max": 0.40},
}


def sample_distribution(name, mu, n, seed=None):
    """Draw n samples from the configured distribution for parameter `name`."""
    if seed is not None:
        np.random.seed(seed)
    dist  = DISTRIBUTIONS[name]
    dtype = dist["type"]
    if dtype == "normal":
        return np.random.normal(mu, dist["std"], n)
    elif dtype == "triangular":
        return np.random.triangular(dist["min"], np.clip(mu, dist["min"] + 1e-9, dist["max"] - 1e-9), dist["max"], n)
    elif dtype == "lognormal":
        if mu <= 0:
            return np.random.normal(mu, abs(mu) * dist["sigma"], n)
        return np.random.lognormal(np.log(mu) - 0.5 * dist["sigma"] ** 2, dist["sigma"], n)
    elif dtype == "uniform":
        return np.random.uniform(dist["min"], dist["max"], n)
    elif dtype == "beta":
        a, b = dist["alpha"], dist["beta_param"]
        raw      = np.random.beta(a, b, n)
        expected = a / (a + b)
        return np.clip(raw * mu / expected, 0.0, 1.0) if expected > 0 else raw
    else:
        return np.full(n, mu)


def apply_distribution(name, mu, z_arr):
    """Transform standard-normal z_arr to target distribution via Gaussian copula."""
    dist  = DISTRIBUTIONS[name]
    dtype = dist["type"]
    if dtype == "normal":
        return mu + z_arr * dist["std"]
    elif dtype == "lognormal":
        if mu <= 0:
            return mu + abs(mu) * dist["sigma"] * z_arr
        return mu * np.exp(dist["sigma"] * z_arr - 0.5 * dist["sigma"] ** 2)
    elif dtype == "triangular":
        u  = norm.cdf(z_arr)
        a  = dist["min"]
        b  = dist["max"]
        c  = np.clip(float(mu), a + 1e-9, b - 1e-9)
        fc = (c - a) / (b - a)
        return np.where(u < fc,
                        a + np.sqrt(np.maximum(u * (b - a) * (c - a), 0.0)),
                        b - np.sqrt(np.maximum((1 - u) * (b - a) * (b - c), 0.0)))
    elif dtype == "uniform":
        return dist["min"] + norm.cdf(z_arr) * (dist["max"] - dist["min"])
    elif dtype == "beta":
        from scipy.stats import beta as _beta
        a, b = dist["alpha"], dist["beta_param"]
        u    = np.clip(norm.cdf(z_arr), 1e-6, 1 - 1e-6)
        raw  = _beta.ppf(u, a, b)
        expected = a / (a + b)
        return np.clip(raw * mu / expected, 0.0, 1.0) if expected > 0 else raw
    else:
        return np.full(len(z_arr), float(mu))


_DEMO_MUS = {"WACC": 0.12, "g1": 0.05, "FCF": 2.5e9, "g2": 0.025, "LGD": 0.45, "rho": 0.25}

print(f"\n{'='*72}")
print(f"=== Block 5 — Configurable Distributions (10,000 samples per parameter) ===")
print(f"{'='*72}")
print(f"{'Parameter':<8} {'Type':<12} {'E[X] (Input)':>16} {'P10':>12} {'P90':>12}")
print("-" * 62)
for _pname, _mu_demo in _DEMO_MUS.items():
    _samp = sample_distribution(_pname, _mu_demo, 10_000, seed=42)
    _p10  = float(np.percentile(_samp, 10))
    _p90  = float(np.percentile(_samp, 90))
    _fmt  = ".4f" if abs(_mu_demo) < 1 else ".2e"
    print(f"{_pname:<8} {DISTRIBUTIONS[_pname]['type']:<12} {_mu_demo:>16{_fmt}} {_p10:>12{_fmt}} {_p90:>12{_fmt}}")
# endregion


# region Block 6 - Correlated Simulation with Cholesky

_TICKERS_5 = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]

# Read the DCF peer summary from the latest DCF_Results_*.xlsx (written by DCF/DCF_Valuation.py).
# The "Summary" sheet (peer group) is identical across tickers, so the most recent file is used.
_REPORTS_BASE   = config.OUTPUT_DIR
_dcf_xlsx_files = glob.glob(os.path.join(_REPORTS_BASE, "*", "DCF_Results_*.xlsx"))
if not _dcf_xlsx_files:
    raise FileNotFoundError(
        f"No DCF_Results_*.xlsx found under {_REPORTS_BASE}. "
        f"Run DCF/DCF_Valuation.py first to generate the peer summary."
    )
_dcf_xlsx_path = max(_dcf_xlsx_files, key=os.path.getmtime)
df_dcf = pd.read_excel(_dcf_xlsx_path, sheet_name="Summary")
print(f"DCF summary loaded from: {_dcf_xlsx_path}")

_ticker_wacc = {}; _ticker_fcf  = {}; _ticker_g1   = {}
_ticker_g2   = {}; _ticker_nd   = {}; _ticker_shr  = {}
_ticker_price = {}; _ticker_prog = {}

for _tkr in _TICKERS_5:
    _row    = df_dcf[df_dcf["Ticker"] == _tkr]
    _cfg_t  = importlib.import_module(f"Config.{_tkr}")
    _bs_t   = _load_json(f"{_tkr}_balance-sheet-statement.json")[0]
    _km_t   = _load_json(f"{_tkr}_key-metrics.json")[0]

    _ticker_wacc[_tkr] = float(_row["WACC"].iloc[0])              if not _row.empty else 0.12
    _ticker_fcf[_tkr]  = float(_row["FCF_Norm_Bn"].iloc[0]) * 1e9 if not _row.empty else 1e9
    _ticker_price[_tkr] = float(_row["Price"].iloc[0])             if not _row.empty else 100.0
    _ticker_g1[_tkr]   = getattr(_cfg_t, "GROWTH_MEAN", 0.05)
    _ticker_g2[_tkr]   = _cfg_t.TERMINAL_GROWTH
    _ticker_prog[_tkr] = _cfg_t.FORECAST_YEARS

    _debt_t = float(_bs_t.get("totalDebt",              0) or 0)
    _cash_t = float(_bs_t.get("cashAndCashEquivalents", 0) or 0)
    _mc_t   = float(_km_t.get("marketCap",              0) or 0)
    _ticker_nd[_tkr]  = _debt_t - _cash_t
    _ticker_shr[_tkr] = _mc_t / _ticker_price[_tkr] if _ticker_price[_tkr] > 0 else 1.0

# Sector correlation matrix (5×5, off-diagonal = 0.60)
_RHO_SECTOR = 0.60
_CORR_MAT   = np.full((5, 5), _RHO_SECTOR)
np.fill_diagonal(_CORR_MAT, 1.0)
_L_CHOL = np.linalg.cholesky(_CORR_MAT)

np.random.seed(42)
_Z_indep = np.random.standard_normal((N_SIM, 5))
_Z_corr  = _Z_indep @ _L_CHOL.T  # shape (N_SIM, 5) — correlated


def _dcf_array(wacc_arr, g1_arr, fcf_start_arr, g2_arr, prog, nd, shares):
    """Vectorized two-phase DCF. Returns equity-per-share array (NaN if invalid)."""
    valid  = wacc_arr > g2_arr
    fcf_t  = np.where(fcf_start_arr > -1e13, fcf_start_arr, 0.0)
    pv_sum = np.zeros(len(wacc_arr))
    for t in range(1, int(prog) + 1):
        fcf_t   = fcf_t * (1 + g1_arr)
        pv_sum += fcf_t / (1 + wacc_arr) ** t
    tv     = np.where(valid, fcf_t * (1 + g2_arr) / (wacc_arr - g2_arr), 0.0)
    pv_tv  = np.where(valid, tv / (1 + wacc_arr) ** prog, 0.0)
    equity = pv_sum + pv_tv - nd
    wa     = np.where(shares > 0, equity / shares, np.nan)
    return np.where(valid, wa, np.nan)


_sim_wa = {}
for _i, _tkr in enumerate(_TICKERS_5):
    _z_i  = _Z_corr[:, _i]
    _wc   = np.clip(apply_distribution("WACC", _ticker_wacc[_tkr], _z_i),        0.04, 0.25)
    _g    = np.clip(apply_distribution("g1",   _ticker_g1[_tkr],   _z_i),        0.00, 0.15)
    _fcf  =         apply_distribution("FCF",  _ticker_fcf[_tkr],  _z_i)
    _g2   = np.clip(apply_distribution("g2",   _ticker_g2[_tkr],   _z_i),        0.01, 0.04)
    _sim_wa[_tkr] = _dcf_array(_wc, _g, _fcf, _g2, _ticker_prog[_tkr],
                                _ticker_nd[_tkr], _ticker_shr[_tkr])

# Terminal output
print(f"\n{'='*72}")
print(f"=== Block 6 — Correlated Simulation (Cholesky, ρ={_RHO_SECTOR:.0%}) ===")
print(f"{'='*72}")
print("Correlation matrix (off-diagonal = 0.60):")
print(f"  {'':8s}" + "".join(f"{t:>8s}" for t in _TICKERS_5))
for _i, _ti in enumerate(_TICKERS_5):
    print(f"  {_ti:<8s}" + "".join(f"{_CORR_MAT[_i, _j]:>8.2f}" for _j in range(5)))

print(f"\nFirst 3 simulations — DCF value/share (USD):")
print(f"  {'Sim':>5}" + "".join(f"{t:>9s}" for t in _TICKERS_5))
for _row_i in range(3):
    _vals = [_sim_wa[_tkr][_row_i] for _tkr in _TICKERS_5]
    print(f"  {_row_i+1:>5}" + "".join(f"{v:>9.2f}" if not np.isnan(v) else f"{'N/A':>9}" for v in _vals))

print(f"\nSim statistics (median value/share | price):")
for _tkr in _TICKERS_5:
    _med = float(np.nanmedian(_sim_wa[_tkr]))
    print(f"  {_tkr:<6s}: Sim Median = {_med:7.2f} USD | Price = {_ticker_price[_tkr]:7.2f} USD "
          f"| Upside = {(_med/_ticker_price[_tkr]-1)*100:+.1f}%")
# endregion


# region Block 7 - Macro Scenario Overlay

MACRO_REGIME = {
    "Recession": {"weight": 0.25, "wacc_adj": +0.02, "g1_adj": -0.02, "fcf_mult": 0.75},
    "Base":      {"weight": 0.50, "wacc_adj":  0.00, "g1_adj":  0.00, "fcf_mult": 1.00},
    "Boom":      {"weight": 0.25, "wacc_adj": -0.01, "g1_adj": +0.01, "fcf_mult": 1.20},
}

_regime_names = list(MACRO_REGIME.keys())
_regime_probs = np.array([v["weight"] for v in MACRO_REGIME.values()])
np.random.seed(43)
_regime_idx   = np.random.choice(len(_regime_names), size=N_SIM, p=_regime_probs)
regime_labels = np.array(_regime_names)[_regime_idx]

_sim_wa_regime = {}
for _i, _tkr in enumerate(_TICKERS_5):
    _z_i  = _Z_corr[:, _i]
    _wc   = apply_distribution("WACC", _ticker_wacc[_tkr], _z_i).copy()
    _g    = apply_distribution("g1",   _ticker_g1[_tkr],   _z_i).copy()
    _fcf  = apply_distribution("FCF",  _ticker_fcf[_tkr],  _z_i).copy()
    _g2_r = apply_distribution("g2",   _ticker_g2[_tkr],   _z_i).copy()

    for _ri, _rn in enumerate(_regime_names):
        _mask = _regime_idx == _ri
        _r    = MACRO_REGIME[_rn]
        _wc[_mask]  = np.clip(_wc[_mask]   + _r["wacc_adj"], 0.04, 0.25)
        _g[_mask]   = np.clip(_g[_mask]    + _r["g1_adj"],   0.00, 0.15)
        _fcf[_mask] = _fcf[_mask] * _r["fcf_mult"]

    _g2_r = np.clip(_g2_r, 0.01, 0.04)
    _sim_wa_regime[_tkr] = _dcf_array(
        _wc, _g, _fcf, _g2_r,
        _ticker_prog[_tkr], _ticker_nd[_tkr], _ticker_shr[_tkr]
    )

print(f"\n{'='*60}")
print(f"=== Block 7 — Macro Scenario Overlay ===")
print(f"{'='*60}")
print(f"{'Regime':<12} {'Share':>8} {'WACC_adj':>10} {'g1_adj':>8} {'FCF_mult':>10}")
print("-" * 50)
for _rn in _regime_names:
    _cnt = int(np.sum(_regime_idx == _regime_names.index(_rn)))
    _r   = MACRO_REGIME[_rn]
    print(f"{_rn:<12} {_cnt/N_SIM:>8.1%} {_r['wacc_adj']:>+10.1%} {_r['g1_adj']:>+8.1%} {_r['fcf_mult']:>10.2f}×")

print(f"\nMedian DCF value/share by regime — {TICKER} ({COMPANY}):")
_wa_active = _sim_wa_regime[TICKER]
for _rn in _regime_names:
    _mask = regime_labels == _rn
    _med  = float(np.nanmedian(_wa_active[_mask])) if _mask.sum() > 0 else float("nan")
    print(f"  {_rn:<12}: {_med:7.2f} USD  (vs. price {_ticker_price[TICKER]:.2f} USD, "
          f"{(_med/_ticker_price[TICKER]-1)*100:+.1f}%)")
# endregion


# region Block 8 - Portfolio VaR DCF

_ptf_rel = np.zeros(N_SIM)
for _tkr in _TICKERS_5:
    _wa  = _sim_wa_regime[_tkr]
    _rel = np.where(np.isnan(_wa) | (_ticker_price[_tkr] == 0), 1.0, _wa / _ticker_price[_tkr])
    _rel = np.clip(_rel, -2.0, 5.0)
    _ptf_rel += 0.20 * _rel

_ptf_value = _ptf_rel * 100       # normalized to 100
_ptf_loss  = 100.0 - _ptf_value   # positive = loss

_ptf_var_95  = float(np.percentile(_ptf_loss, 95))
_ptf_var_99  = float(np.percentile(_ptf_loss, 99))
_ptf_cvar_99 = float(np.mean(_ptf_loss[_ptf_loss >= _ptf_var_99]))
_p_under_ptf = float(np.mean(_ptf_loss < 0))

# Diversification effect
_indiv_stds = []
for _tkr in _TICKERS_5:
    _wa = _sim_wa_regime[_tkr]
    _rel = np.where(np.isnan(_wa) | (_ticker_price[_tkr] == 0), 1.0, _wa / _ticker_price[_tkr])
    _indiv_stds.append(float(np.nanstd(np.clip(_rel, -2.0, 5.0)) * 100))
_port_std    = float(np.nanstd(_ptf_value))
_avg_std     = float(np.mean(_indiv_stds))
_divers      = 1.0 - _port_std / _avg_std if _avg_std > 0 else 0.0

# Per-ticker VaR/CVaR (analogous to the portfolio logic, per ticker)
_ticker_risk = {}
for _tkr in _TICKERS_5:
    _wa_tkr   = _sim_wa_regime[_tkr]
    _rel_tkr  = np.where(np.isnan(_wa_tkr) | (_ticker_price[_tkr] == 0), 1.0, _wa_tkr / _ticker_price[_tkr])
    _rel_tkr  = np.clip(_rel_tkr, -2.0, 5.0)
    _loss_tkr = 100.0 - (_rel_tkr * 100)
    _var95_t  = float(np.percentile(_loss_tkr, 95))
    _var99_t  = float(np.percentile(_loss_tkr, 99))
    _cvar99_t = float(np.mean(_loss_tkr[_loss_tkr >= _var99_t]))
    _ticker_risk[_tkr] = {"VaR_95": _var95_t, "VaR_99": _var99_t, "CVaR_99": _cvar99_t}

print(f"\n{'='*60}")
print(f"=== Block 8 — Portfolio VaR (DCF, equal-weighted 20% per ticker) ===")
print(f"{'='*60}")
print(f"{'Metric':<35} {'Value':>12}")
print("-" * 48)
print(f"{'Portfolio Starting Value (normalized)':<35} {'100.00':>12}")
print(f"{'Portfolio Median':<35} {float(np.median(_ptf_value)):>12.2f}")
print(f"{'Portfolio Std Dev':<35} {_port_std:>12.2f}")
print(f"{'VaR 95%':<35} {_ptf_var_95:>12.2f}")
print(f"{'VaR 99%':<35} {_ptf_var_99:>12.2f}")
print(f"{'CVaR 99% (Expected Shortfall)':<35} {_ptf_cvar_99:>12.2f}")
print(f"{'P(Portfolio > 100, Undervalued)':<35} {_p_under_ptf:>12.1%}")
print(f"{'Average Individual Std':<35} {_avg_std:>12.2f}")
print(f"{'Diversification Effect':<35} {_divers:>12.1%}")
print()
print(f"{'Ticker':<8}" + "".join(f"{t:>8}" for t in _TICKERS_5))
print(f"{'Std (%)':<8}" + "".join(f"{s:>8.2f}" for s in _indiv_stds))

print(f"\nRisk measures: per-ticker vs. portfolio (loss in % of starting value):")
print(f"{'Ticker':<10} {'VaR 95%':>10} {'VaR 99%':>10} {'CVaR 99%':>10}")
print("-" * 42)
for _tkr in _TICKERS_5:
    _r = _ticker_risk[_tkr]
    print(f"{_tkr:<10} {_r['VaR_95']:>10.2f} {_r['VaR_99']:>10.2f} {_r['CVaR_99']:>10.2f}")
print("-" * 42)
print(f"{'Portfolio':<10} {_ptf_var_95:>10.2f} {_ptf_var_99:>10.2f} {_ptf_cvar_99:>10.2f}")

# Histogram: portfolio loss distribution
_x_lo_p = min(-40.0, float(np.percentile(_ptf_loss, 0.5)) - 5)
_x_hi_p = max( 60.0, float(np.percentile(_ptf_loss, 99.95)) + 5)

fig8 = go.Figure()
_m_norm = _ptf_loss <  _ptf_var_95
_m_orng = (_ptf_loss >= _ptf_var_95) & (_ptf_loss < _ptf_var_99)
_m_red  = _ptf_loss >= _ptf_var_99

fig8.add_trace(go.Histogram(x=_ptf_loss[_m_norm], name="Normal",
    xbins=dict(start=_x_lo_p, end=_ptf_var_95, size=1.0),
    marker=dict(color=BLUE_1,   line=dict(color=BLUE_1,   width=0.3)), opacity=0.60))
fig8.add_trace(go.Histogram(x=_ptf_loss[_m_orng], name="Tail VaR95–VaR99",
    xbins=dict(start=_ptf_var_95, end=_ptf_var_99, size=1.0),
    marker=dict(color=ORANGE_1, line=dict(color=ORANGE_1, width=0.3)), opacity=0.80))
fig8.add_trace(go.Histogram(x=_ptf_loss[_m_red],  name="Tail > VaR99",
    xbins=dict(start=_ptf_var_99, end=_x_hi_p, size=1.0),
    marker=dict(color=ORANGE_2,    line=dict(color=ORANGE_2,    width=0.3)), opacity=0.88))

for _xv, _lbl, _col in [
    (0.0,          "Fair Value",       GRAY_1),
    (_ptf_var_95,  f"VaR95 {_ptf_var_95:.1f}", ORANGE_1),
    (_ptf_var_99,  f"VaR99 {_ptf_var_99:.1f}", ORANGE_2),
    (_ptf_cvar_99, f"CVaR99 {_ptf_cvar_99:.1f}", ORANGE_2),
]:
    fig8.add_vline(x=_xv, line_dash="dash" if _xv == _ptf_cvar_99 else "solid",
                   line_color=_col, line_width=1.8)
    fig8.add_annotation(x=_xv, y=0.97, yref="paper", text=_lbl, showarrow=False,
                        font=dict(color=_col, size=9), xanchor="left",
                        bgcolor="rgba(255,255,255,0.80)", borderpad=2)

fig8.update_layout(**LAYOUT)
fig8.update_layout(
    title=dict(text=f"Portfolio Loss Distribution — DCF Model (5 Tickers, 20% each)<br>"
                    f"<sup>ρ={_RHO_SECTOR:.0%} sector correlation | macro regime | "
                    f"{N_SIM:,} simulations | P(Undervalued)={_p_under_ptf:.1%}</sup>",
               font=dict(size=14, color="#0B1220"), x=0.0),
    barmode="overlay",
    xaxis=dict(title="Portfolio Loss / Gain (%)", range=[_x_lo_p, _x_hi_p],
               showgrid=False, showline=True, linecolor=BORDER),
    yaxis=dict(title="Frequency", showgrid=False, showline=True, linecolor=BORDER),
    height=440,
    margin=dict(l=60, r=40, t=100, b=60),
    legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0, x=0.68, y=0.99, xanchor="left", yanchor="top"),
)
_chart8_path = os.path.join(OUTPUT_DIR, f"Portfolio_Loss_Distribution_{date.today()}.png")
try:
    fig8.write_image(_chart8_path, width=900, height=440, scale=1.5)
    print(f"\nChart saved: {_chart8_path}")
except Exception:
    _chart8_path = _chart8_path.replace(".png", ".html")
    fig8.write_html(_chart8_path)
    print(f"\nChart (HTML) saved: {_chart8_path}")
# endregion


# region Block 8b - QCOM Dashboard Chart
from plotly.subplots import make_subplots

_IMAGES_FOLDER = os.path.join(PROJECT_ROOT, "images")
os.makedirs(_IMAGES_FOLDER, exist_ok=True)

_qcom_wa       = _sim_wa_regime["QCOM"]
_qcom_wa_valid = _qcom_wa[~np.isnan(_qcom_wa)]
_qcom_price     = _ticker_price["QCOM"]

# P5 / P95 / Mean directly on the raw value/share distribution (USD), not on %-loss
_p5_usd   = float(np.percentile(_qcom_wa_valid, 5))
_p95_usd  = float(np.percentile(_qcom_wa_valid, 95))
_mean_usd = float(np.mean(_qcom_wa_valid))


# Parameter samples for QCOM (same Z values used in Block 6)
_qcom_idx  = _TICKERS_5.index("QCOM")
_z_qcom    = _Z_corr[:, _qcom_idx]
_wacc_qcom = np.clip(apply_distribution("WACC", _ticker_wacc["QCOM"], _z_qcom), 0.04, 0.25)
_g1_qcom   = np.clip(apply_distribution("g1",   _ticker_g1["QCOM"],   _z_qcom), 0.00, 0.15)
_fcf_qcom  =         apply_distribution("FCF",  _ticker_fcf["QCOM"],  _z_qcom)
_g2_qcom   = np.clip(apply_distribution("g2",   _ticker_g2["QCOM"],   _z_qcom), 0.01, 0.04)

# Shared x-range for the confidence-band bar and histogram (identical axis)
_x_pad   = (float(np.max(_qcom_wa_valid)) - float(np.min(_qcom_wa_valid))) * 0.02
_x_range = [float(np.min(_qcom_wa_valid)) - _x_pad, float(np.max(_qcom_wa_valid)) + _x_pad]

fig_qcom = make_subplots(
    rows=5, cols=2,
    column_widths=[0.75, 0.25],
    row_heights=[0.06, 0.235, 0.235, 0.235, 0.235],
    specs=[
        [{}, None],
        [{"rowspan": 4}, {}],
        [None,           {}],
        [None,           {}],
        [None,           {}],
    ],
    horizontal_spacing=0.08,
    vertical_spacing=0.09,
    subplot_titles=["", "", "WACC", "Growth g₁", "FCF", "Terminal g₂"],
)

# Shrink the right column's subplot titles to leave more vertical space
for _ann in fig_qcom.layout.annotations:
    if _ann.text in ("WACC", "Growth g₁", "FCF", "Terminal g₂"):
        _ann.font.size = 10

# ── Row 1: confidence-band bar (@RISK style: 5% | 90% | 5%) ────────────
_band_segments = [
    (_x_range[0], _p5_usd,  "#F1F5F9"),   # left tail (0–P5)
    (_p5_usd,     _p95_usd, "#1D6FD8"),   # confidence band (P5–P95)
    (_p95_usd,    _x_range[1], "#F1F5F9"),  # right tail (P95–100)
]
for _x0, _x1, _col in _band_segments:
    fig_qcom.add_trace(go.Bar(
        y=[""], x=[_x1 - _x0], base=_x0, width=1.0,
        orientation="h",
        marker=dict(color=_col, line=dict(color=BORDER, width=1)),
        showlegend=False, hoverinfo="skip",
    ), row=1, col=1)

for (_x0, _x1, _), _pct, _txtcol in zip(
    _band_segments, ["5.0%", "90.0%", "5.0%"], ["#6B7280", "#FFFFFF", "#6B7280"]
):
    fig_qcom.add_annotation(
        x=(_x0 + _x1) / 2, y=0, yref="y", text=_pct, showarrow=False,
        font=dict(size=10, color=_txtcol), xanchor="center", yanchor="middle",
        row=1, col=1,
    )

for _xv, _val in [(_p5_usd, _p5_usd), (_p95_usd, _p95_usd)]:
    fig_qcom.add_annotation(
        x=_xv, y=1.0, yref="y domain", text=f"{_val:.2f}<br>▼", showarrow=False,
        font=dict(size=9, color="#1A1A1A"), xanchor="center", yanchor="bottom",
        row=1, col=1,
    )

fig_qcom.update_xaxes(
    range=_x_range, showticklabels=False,
    showgrid=False, zeroline=False, showline=False,
    row=1, col=1,
)
fig_qcom.update_yaxes(
    showticklabels=False, showgrid=False, zeroline=False, showline=False,
    row=1, col=1,
)

# ── Rows 2-5: main left panel — histogram of QCOM value/share ───────────
fig_qcom.add_trace(go.Histogram(
    x=_qcom_wa_valid, nbinsx=60,
    marker=dict(color="#1D6FD8", line=dict(color="#1D6FD8", width=0.3)),
    opacity=0.80, showlegend=False,
), row=2, col=1)

_line_specs = [
    (_p5_usd,   "#D1D5DB", "dot",   1.5, f"P5 = {_p5_usd:.2f}",     0.97),
    (_mean_usd, "#1D6FD8", "solid", 2.0, f"Mean = {_mean_usd:.2f}", 0.97),
    (_p95_usd,  "#D1D5DB", "dot",   1.5, f"P95 = {_p95_usd:.2f}",   0.97),
]
for _xv, _col, _dash, _wid, _lbl, _ypos in _line_specs:
    fig_qcom.add_vline(x=_xv, line_dash=_dash, line_color=_col, line_width=_wid, row=2, col=1)
    fig_qcom.add_annotation(
        x=_xv, y=_ypos, yref="y domain", text=_lbl, showarrow=False,
        textangle=-90, font=dict(size=9, color="#1A1A1A"),
        xanchor="left", yanchor="top",
        bgcolor="rgba(255,255,255,0.92)", bordercolor="#9CA3AF", borderwidth=1, borderpad=2,
        row=2, col=1,
    )

fig_qcom.update_xaxes(
    title_text="Value/Share", range=_x_range,
    showgrid=False, zeroline=False, showline=True, linecolor=BORDER,
    row=2, col=1,
)
fig_qcom.update_yaxes(
    title_text="Frequency",
    showgrid=False, zeroline=False, showline=True, linecolor=BORDER,
    row=2, col=1,
)

# Right column: 4 small parameter histograms (sparkline-style)
# Index 2 = FCF (stays USD/Bn), all others (WACC, g1, g2) shown as percent
_PARAM_ARRAYS = [_wacc_qcom, _g1_qcom, _fcf_qcom, _g2_qcom]
for _i, _arr in enumerate(_PARAM_ARRAYS):
    fig_qcom.add_trace(go.Histogram(
        x=_arr, nbinsx=30,
        marker=dict(color="#5B9BD5", line=dict(width=0)),
        opacity=0.85, showlegend=False,
    ), row=_i + 2, col=2)
    fig_qcom.update_xaxes(
        showticklabels=True, tickfont=dict(size=7),
        tickformat=".1%" if _i != 2 else None,
        showgrid=False, zeroline=False, showline=True, linecolor=BORDER,
        row=_i + 2, col=2,
    )
    fig_qcom.update_yaxes(
        showticklabels=False, showgrid=False, zeroline=False, showline=False,
        row=_i + 2, col=2,
    )

fig_qcom.update_layout(**LAYOUT)
fig_qcom.update_layout(
    title=dict(
        text="QCOM — Monte Carlo DCF Distribution (10,000 Simulations, Macro Regime)",
        font=dict(size=16, color="#0B1220"), x=0.5, xanchor="center",
    ),
    width=1100, height=500,
    barmode="overlay",
    showlegend=False,
    margin=dict(l=80, r=30, t=100, b=70),
)
fig_qcom.add_annotation(
    xref="paper", yref="paper", x=1.0, y=1.07,
    text="Source: FMP",
    showarrow=False, font=dict(size=9, color="#9CA3AF"),
    xanchor="right", yanchor="bottom",
)

_chart_qcom_path = os.path.join(_IMAGES_FOLDER, "QCOM_MCS_Dashboard.png")
try:
    fig_qcom.write_image(_chart_qcom_path, width=1100, height=500, scale=2)
    print(f"\n{'='*60}")
    print(f"=== Block 8b — QCOM Dashboard Chart (@RISK style) ===")
    print(f"{'='*60}")
    print(f"P5={_p5_usd:.2f} USD | Mean={_mean_usd:.2f} USD | P95={_p95_usd:.2f} USD")
    print(f"Chart saved: {_chart_qcom_path}")
except Exception as _exc_qcom:
    print(f"\nQCOM Dashboard Chart export failed: {_exc_qcom}")
# endregion


# region Block 9 - Convergence Test

N_LEVELS = [100, 250, 500, 1000, 2500, 5000, 7500, 10_000]

_conv_rows = []
_prev_var9 = None
for _n in N_LEVELS:
    _var9_n = float(np.percentile(_ptf_loss[:_n], 99))
    _delta  = _var9_n - _prev_var9 if _prev_var9 is not None else 0.0
    _conv_rows.append({"N_Sim": _n, "VaR_99": round(_var9_n, 3), "Delta": round(_delta, 3)})
    _prev_var9 = _var9_n

print(f"\n{'='*50}")
print(f"=== Block 9 — Convergence Test (Portfolio VaR 99%) ===")
print(f"{'='*50}")
print(f"{'N_Sim':>8} {'VaR_99':>10} {'Δ vs. Previous':>18}")
print("-" * 38)
for _cr in _conv_rows:
    _d_str = f"{_cr['Delta']:>+18.3f}" if _cr["Delta"] != 0 else f"{'—':>18}"
    print(f"{_cr['N_Sim']:>8,} {_cr['VaR_99']:>10.3f} {_d_str}")

fig9 = go.Figure()
fig9.add_trace(go.Scatter(
    x=[r["N_Sim"] for r in _conv_rows],
    y=[r["VaR_99"] for r in _conv_rows],
    mode="lines+markers",
    name="VaR 99%",
    line=dict(color=BLUE_1, width=2),
    marker=dict(size=8, color=BLUE_1),
))
fig9.add_hline(y=_ptf_var_99, line_dash="dot", line_color=ORANGE_2, line_width=1.5,
               annotation_text=f"VaR99 (N=10k): {_ptf_var_99:.2f}",
               annotation_position="top right",
               annotation_font=dict(color=ORANGE_2, size=10))
fig9.update_layout(**LAYOUT)
fig9.update_layout(
    title=dict(text="Convergence — Portfolio VaR 99% vs. Number of Simulations",
               font=dict(size=14, color="#0B1220"), x=0.0),
    xaxis=dict(title="Simulations (N)", showgrid=False, showline=True, linecolor=BORDER, type="log"),
    yaxis=dict(title="VaR 99% (%)", showgrid=True, gridcolor=BORDER),
    height=380,
    margin=dict(l=60, r=60, t=80, b=60),
)
_chart9_path = os.path.join(OUTPUT_DIR, f"Convergence_VaR99_{date.today()}.png")
try:
    fig9.write_image(_chart9_path, width=800, height=380, scale=1.5)
    print(f"Convergence chart saved: {_chart9_path}")
except Exception:
    _chart9_path = _chart9_path.replace(".png", ".html")
    fig9.write_html(_chart9_path)
    print(f"Convergence chart (HTML) saved: {_chart9_path}")
# endregion


# region Block 10 - Tornado Chart of Uncertainty


def _ptf_var99_override(wacc_delta=0.0, g1_delta=0.0, fcf_mult=1.0, g2_delta=0.0):
    """Compute portfolio VaR 99% with uniform parameter override across all tickers."""
    _pv = np.zeros(N_SIM)
    for _ti, _tkr in enumerate(_TICKERS_5):
        _z  = _Z_corr[:, _ti]
        _wc = np.clip(apply_distribution("WACC", _ticker_wacc[_tkr], _z) + wacc_delta, 0.04, 0.25)
        _g  = np.clip(apply_distribution("g1",   _ticker_g1[_tkr],   _z) + g1_delta,  0.00, 0.15)
        _fc = apply_distribution("FCF", _ticker_fcf[_tkr], _z) * fcf_mult
        _g2 = np.clip(apply_distribution("g2", _ticker_g2[_tkr], _z) + g2_delta, 0.01, 0.04)
        _wa = _dcf_array(_wc, _g, _fc, _g2, _ticker_prog[_tkr], _ticker_nd[_tkr], _ticker_shr[_tkr])
        _rel = np.where(np.isnan(_wa) | (_ticker_price[_tkr] == 0), 1.0, _wa / _ticker_price[_tkr])
        _pv += 0.20 * np.clip(_rel, -2.0, 5.0)
    return float(np.percentile((1.0 - _pv) * 100, 99))


_base_var_tor = _ptf_var99_override()

_TORNADO_PARAMS = {
    "WACC": {"mu": float(np.mean(list(_ticker_wacc.values()))), "delta_fn": lambda p10, p90, mu: (p10 - mu, p90 - mu, "wacc_delta")},
    "g1":   {"mu": float(np.mean(list(_ticker_g1.values()))),   "delta_fn": lambda p10, p90, mu: (p10 - mu, p90 - mu, "g1_delta")},
    "FCF":  {"mu": 2.5e9,                                       "delta_fn": lambda p10, p90, mu: (p10 / mu, p90 / mu, "fcf_mult")},
    "g2":   {"mu": float(np.mean(list(_ticker_g2.values()))),   "delta_fn": lambda p10, p90, mu: (p10 - mu, p90 - mu, "g2_delta")},
}

_tornado_rows = []
for _pn, _pinfo in _TORNADO_PARAMS.items():
    _mu_p  = _pinfo["mu"]
    _samp  = sample_distribution(_pn, _mu_p, 50_000, seed=42)
    _p10   = float(np.percentile(_samp, 10))
    _p90   = float(np.percentile(_samp, 90))
    _d10, _d90, _kw = _pinfo["delta_fn"](_p10, _p90, _mu_p)

    if _kw == "wacc_delta":
        _var_p10 = _ptf_var99_override(wacc_delta=_d10)
        _var_p90 = _ptf_var99_override(wacc_delta=_d90)
    elif _kw == "g1_delta":
        _var_p10 = _ptf_var99_override(g1_delta=_d10)
        _var_p90 = _ptf_var99_override(g1_delta=_d90)
    elif _kw == "fcf_mult":
        _var_p10 = _ptf_var99_override(fcf_mult=_d10)
        _var_p90 = _ptf_var99_override(fcf_mult=_d90)
    else:
        _var_p10 = _ptf_var99_override(g2_delta=_d10)
        _var_p90 = _ptf_var99_override(g2_delta=_d90)

    _tornado_rows.append({
        "Parameter":      _pn,
        "P10_VaR99":      round(_var_p10, 2),
        "P90_VaR99":      round(_var_p90, 2),
        "P10_Impact":     round(_var_p10 - _base_var_tor, 2),
        "P90_Impact":     round(_var_p90 - _base_var_tor, 2),
        "Total_Impact":   round(abs(_var_p90 - _var_p10), 2),
    })

_tornado_rows.sort(key=lambda x: x["Total_Impact"], reverse=True)

print(f"\n{'='*68}")
print(f"=== Block 10 — Tornado Chart (Base VaR99 = {_base_var_tor:.2f}%) ===")
print(f"{'='*68}")
print(f"{'Parameter':<10} {'VaR99 @P10':>12} {'VaR99 @P90':>12} {'Impact':>12}")
print("-" * 48)
for _tr in _tornado_rows:
    print(f"{_tr['Parameter']:<10} {_tr['P10_VaR99']:>12.2f} {_tr['P90_VaR99']:>12.2f} {_tr['Total_Impact']:>12.2f}")

fig10 = go.Figure()
for _tr in _tornado_rows:
    _p     = _tr["Parameter"]
    _lo_v  = min(_tr["P10_Impact"], _tr["P90_Impact"])
    _hi_v  = max(_tr["P10_Impact"], _tr["P90_Impact"])
    _color = BLUE_1 if _lo_v >= 0 else ORANGE_2
    fig10.add_trace(go.Bar(
        y=[_p], x=[_hi_v - _lo_v],
        base=_lo_v,
        orientation="h",
        name=_p,
        marker_color=_color, opacity=0.80,
        text=f"±{_tr['Total_Impact']:.1f}%",
        textposition="outside",
    ))
fig10.add_vline(x=0, line_color=GRAY_1, line_width=1.5, line_dash="solid")
fig10.update_layout(**LAYOUT)
fig10.update_layout(
    title=dict(text=f"Tornado Chart — Impact on Portfolio VaR 99% (Base: {_base_var_tor:.2f}%)",
               font=dict(size=14, color="#0B1220"), x=0.0),
    showlegend=False,
    xaxis=dict(title="Δ VaR 99% (%)", showgrid=True, gridcolor=BORDER, showline=True, linecolor=BORDER),
    yaxis=dict(showgrid=False, showline=False, autorange="reversed"),
    height=320,
    margin=dict(l=80, r=80, t=80, b=60),
)
_chart10_path = os.path.join(OUTPUT_DIR, f"Tornado_VaR99_{date.today()}.png")
try:
    fig10.write_image(_chart10_path, width=800, height=320, scale=1.5)
    print(f"Tornado chart saved: {_chart10_path}")
except Exception:
    _chart10_path = _chart10_path.replace(".png", ".html")
    fig10.write_html(_chart10_path)
    print(f"Tornado chart (HTML) saved: {_chart10_path}")
# endregion


# region Block 11 - Excel Export
# ─────────────────────────────────────────────────────────────
# Exports all MCS results into a single .xlsx workbook with one
# sheet per result set. Same output folder as Merton_Model.py
# and DCF_Valuation.py: OUTPUT_DIR/{TICKER}/.
# ─────────────────────────────────────────────────────────────

_export_date = date.today().isoformat()

# Sheet 1: Portfolio (10,000 simulations)
_ptf_rows = []
for _si in range(N_SIM):
    _ptf_rows.append({
        "Simulation":           _si + 1,
        "Portfolio_Value_Norm": round(float(_ptf_value[_si]), 4),
        "Regime":               regime_labels[_si],
        "Undervalued":          int(_ptf_loss[_si] < 0),
        "VaR_95":              round(_ptf_var_95,  3),
        "VaR_99":              round(_ptf_var_99,  3),
        "CVaR_99":             round(_ptf_cvar_99, 3),
    })
df_ptf = pd.DataFrame(_ptf_rows)

# Sheet 2: Ticker
_ticker_rows = []
for _tkr in _TICKERS_5:
    _wa = _sim_wa_regime[_tkr]
    _ticker_rows.append({
        "Date":              _export_date,
        "Ticker":            _tkr,
        "Price":             round(_ticker_price[_tkr], 2),
        "Sim_Median":        round(float(np.nanmedian(_wa)), 2),
        "Sim_P10":           round(float(np.nanpercentile(_wa, 10)), 2),
        "Sim_P90":           round(float(np.nanpercentile(_wa, 90)), 2),
        "P_Undervalued":     round(float(np.nanmean(_wa > _ticker_price[_tkr])), 4),
        "WACC_mean":         round(_ticker_wacc[_tkr], 4),
        "g1_mean":           round(_ticker_g1[_tkr], 4),
        "Distribution_WACC": DISTRIBUTIONS["WACC"]["type"],
        "Distribution_g1":   DISTRIBUTIONS["g1"]["type"],
        "VaR_95":            round(_ticker_risk[_tkr]["VaR_95"],  3),
        "VaR_99":            round(_ticker_risk[_tkr]["VaR_99"],  3),
        "CVaR_99":           round(_ticker_risk[_tkr]["CVaR_99"], 3),
    })
df_tkr = pd.DataFrame(_ticker_rows)

# Sheet 3: Convergence
df_conv = pd.DataFrame(_conv_rows)

# Sheet 4: Tornado
df_tor = pd.DataFrame(_tornado_rows)
df_tor.insert(0, "Date", _export_date)
print(df_tor[["Parameter", "P10_VaR99", "P90_VaR99", "Total_Impact"]].to_string(index=False))

# Sheet 5: Risk_Comparison — per-ticker vs. portfolio (VaR/CVaR comparison)
_risk_rows = []
for _tkr in _TICKERS_5:
    _r = _ticker_risk[_tkr]
    _risk_rows.append({
        "Ticker":  _tkr,
        "VaR_95":  round(_r["VaR_95"],  3),
        "VaR_99":  round(_r["VaR_99"],  3),
        "CVaR_99": round(_r["CVaR_99"], 3),
    })
_risk_rows.append({
    "Ticker":  "Portfolio",
    "VaR_95":  round(_ptf_var_95,  3),
    "VaR_99":  round(_ptf_var_99,  3),
    "CVaR_99": round(_ptf_cvar_99, 3),
})
df_risk_comp = pd.DataFrame(_risk_rows)
print(df_risk_comp.to_string(index=False))


def export_excel_mcs(df_portfolio, df_ticker, df_convergence, df_tornado, df_risk, output_path):
    """Export all MCS results to a single .xlsx workbook (one sheet per result set)."""
    excel_path = os.path.join(output_path, f"MCS_Results_{TICKER}_{date.today()}.xlsx")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_portfolio.to_excel(writer,   sheet_name="Portfolio",       index=False)
        df_ticker.to_excel(writer,      sheet_name="Ticker",          index=False)
        df_convergence.to_excel(writer, sheet_name="Convergence",     index=False)
        df_tornado.to_excel(writer,     sheet_name="Tornado",         index=False)
        df_risk.to_excel(writer,        sheet_name="Risk_Comparison", index=False)
    return excel_path


_MCS_REPORTS_DIR = os.path.join(config.OUTPUT_DIR, ACTIVE_CONFIG)
os.makedirs(_MCS_REPORTS_DIR, exist_ok=True)
_mcs_xlsx_path = export_excel_mcs(df_ptf, df_tkr, df_conv, df_tor, df_risk_comp, _MCS_REPORTS_DIR)
print(f"\nExcel saved: {_mcs_xlsx_path}")
print(f"  Portfolio       — {len(df_ptf)} row(s)")
print(f"  Ticker          — {len(df_tkr)} row(s)")
print(f"  Convergence     — {len(df_conv)} row(s)")
print(f"  Tornado         — {len(df_tor)} row(s)")
print(f"  Risk_Comparison — {len(df_risk_comp)} row(s)")
# endregion


# region Interpretation
print("\n=== Interpretation ===")
print(f">>> PD(Merton) = {pd_merton:.4%}: "
      f"{'Low' if pd_merton < 0.01 else 'Moderate' if pd_merton < 0.05 else 'High'} "
      f"single-name default probability — "
      f"{'investment-grade range.' if pd_merton < 0.01 else 'sub-investment-grade range.'}")

if pd_floor_applied:
    print(f">>> Merton PD was < 1e-6 (DD={_merton['dd']:.2f}) — portfolio hypothetical, "
          f"with a 0.1% PD floor for model demonstration purposes.")
if not np.isnan(rc_el):
    if rc_el > 5:
        print(f">>> RC/EL = {rc_el:.1f}x: Strong capital multiplier — "
              f"high tail concentration relative to EL, ρ={RHO:.0%} dominates.")
    else:
        print(f">>> RC/EL = {rc_el:.1f}x: Moderate capital multiplier.")

# UL of a fully concentrated single loan (ρ=1, N=1)
ul_single = float(np.sqrt(pd_merton * (1 - pd_merton)) * LGD)
diversif  = 1 - (UL / ul_single) if ul_single > 0 and UL < ul_single else 0.0
print(f">>> Diversification effect: {diversif:.1%} UL reduction vs. single-loan exposure "
      f"(σ_single = {ul_single:.4%} vs. UL_portfolio = {ul_pct:.4f}%).")

if VaR_99 > 0 and VaR_999 / VaR_99 > 2:
    print(f">>> VaR99.9 / VaR99 = {VaR_999/VaR_99:.2f}x: "
          f"Pronounced tail asymmetry — systematic risk (ρ={RHO:.0%}) "
          f"drives the fat tail.")

_act_med   = float(np.nanmedian(_sim_wa_regime[TICKER]))
_act_price  = _ticker_price[TICKER]
_act_up    = (_act_med / _act_price - 1) * 100 if _act_price > 0 else float("nan")
print(f">>> DCF portfolio VaR 99% = {_ptf_var_99:.2f}% (normalized to 100) — "
      f"{'conservative' if _ptf_var_99 < 20 else 'moderate' if _ptf_var_99 < 40 else 'high'} "
      f"tail risk at ρ={_RHO_SECTOR:.0%} sector correlation.")
print(f">>> Diversification effect, DCF portfolio: {_divers:.1%} std reduction vs. "
      f"single names (portfolio std = {_port_std:.1f}, individual avg = {_avg_std:.1f}).")
if _tornado_rows:
    _top_tor = _tornado_rows[0]
    print(f">>> Largest uncertainty driver: {_top_tor['Parameter']} "
          f"(impact ±{_top_tor['Total_Impact']:.1f}% on VaR99 across P10/P90 variation).")
print(f">>> {TICKER} Sim Median = {_act_med:.2f} USD "
      f"({'undervalued' if _act_up > 10 else 'overvalued' if _act_up < -10 else 'fair'}, "
      f"{_act_up:+.1f}%) across all regimes and 10,000 simulations.")
# endregion


# region Legende
print("\n=== Legende ===")
print("N_LOANS        = Number of equally weighted individual loans in the portfolio")
print("EXPOSURE       = Single exposure = 1/N_LOANS (normalized to portfolio size 1)")
print("LGD            = Loss Given Default = 45% (Basel II standard assumption, unsecured)")
print("RHO            = Asset correlation ρ (Basel II = 20% for corporate loans)")
print("pd_merton      = Probability of default from the Merton (1974) model")
print("pd_portfolio   = pd_merton (single borrower = the company under analysis)")
print("Z_sys          = Systematic factor ~ N(0,1), one per simulation")
print("pd_cond        = Conditional PD | Z = N((N_inv(PD) - sqrt(ρ)·Z) / sqrt(1-ρ))")
print("U              = Uniformly distributed Bernoulli triggers (SIMULATIONS × N_LOANS)")
print("defaults       = Indicator matrix: 1 = default, 0 = no default")
print("portfolio_losses = Portfolio loss = defaults.sum × EXPOSURE × LGD (per simulation)")
print("EL             = Expected Loss = E[portfolio_losses]")
print("UL             = Unexpected Loss = Std[portfolio_losses] (1σ buffer)")
print("VaR_99         = Value at Risk 99% = quantile of the loss distribution")
print("VaR_999        = Value at Risk 99.9% (Basel III regulatory level)")
print("CVaR_99        = Conditional VaR 99% = Expected Shortfall = E[L | L >= VaR_99]")
print("RC             = Risk Capital = VaR_999 − EL (unexpected extreme loss)")
print("RC/EL          = Capital multiplier: ratio of risk buffer to expected loss")
print("pd_floor_applied = True if Merton PD < 1e-6 → PD set to 0.1% (hypothetical)")
print("N_SIM          = Number of simulations for the DCF blocks (10,000)")
print("DISTRIBUTIONS  = Dict: distribution type and parameters per DCF parameter")
print("sample_distribution(name, mu, n) = Draws n samples from the configured distribution")
print("apply_distribution(name, mu, z)  = Gaussian copula: Z~N(0,1) → target distribution")
print("_TICKERS_5     = The 5 peer tickers: MCHP, INTC, ON, QCOM, MPWR")
print("_CORR_MAT      = 5×5 sector correlation matrix (ρ=0.60 off-diagonal)")
print("_L_CHOL        = Cholesky factor of _CORR_MAT (L @ L.T = _CORR_MAT)")
print("_Z_indep       = Uncorrelated N(0,1) draws (N_SIM × 5)")
print("_Z_corr        = Correlated draws: _Z_indep @ _L_CHOL.T")
print("_dcf_array()   = Vectorized two-phase DCF (arrays, no Python loop)")
print("_sim_wa        = Dict: Ticker → sim array of value/share (Block 6, no regime)")
print("MACRO_REGIME   = Dict: Recession/Base/Boom with weights and parameter adjustments")
print("_regime_idx    = Per-simulation regime index (multinomial draw)")
print("regime_labels  = Regime name per simulation as a string array")
print("_sim_wa_regime = Dict: Ticker → sim array of value/share (Block 7, with regime)")
print("_ptf_value     = Total portfolio value normalized to 100 (weighted mean of relative values)")
print("_ptf_loss      = Portfolio loss = 100 − _ptf_value (positive = loss)")
print("_ptf_var_95    = Portfolio VaR 95% from the DCF simulation")
print("_ptf_var_99    = Portfolio VaR 99% from the DCF simulation")
print("_ptf_cvar_99   = Portfolio CVaR 99% = Expected Shortfall")
print("_p_under_ptf   = Share of sims with portfolio value > 100 (DCF upside)")
print("_divers        = Diversification effect: 1 − PortfolioStd/IndividualStd (in %)")
print("N_LEVELS       = Simulation counts for the convergence test [100…10,000]")
print("_conv_rows     = List: N_Sim, VaR_99, Delta for the convergence CSV")
print("_base_var_tor  = Base VaR99 without parameter override (tornado reference)")
print("_ptf_var99_override() = Computes portfolio VaR99 with a parameter override")
print("_tornado_rows  = List: Parameter, P10/P90 VaR99, impact — sorted by impact")
print("export_excel_mcs() = Writes all MCS results to one .xlsx workbook (one sheet per set)")
print("MCS_Results_*.xlsx = Workbook in OUTPUT_DIR/{TICKER}/ (same folder as Merton/DCF exports)")
print("  Sheet Portfolio       = 10,000 rows: portfolio value, regime, VaR per simulation")
print("  Sheet Ticker          = 5 rows: sim statistics per ticker (Median, P10, P90, VaR/CVaR)")
print("  Sheet Convergence     = 8 rows: VaR99 at N=100/250/.../10,000")
print("  Sheet Tornado         = 4 rows: tornado results per parameter")
print("  Sheet Risk_Comparison = 6 rows: VaR95/VaR99/CVaR99 per ticker + portfolio")
print("_dcf_xlsx_path = Latest DCF_Results_*.xlsx read for the peer summary (Block 6)")
print("_ticker_risk        = Dict: Ticker -> {VaR_95, VaR_99, CVaR_99} (loss in %)")
print("_wacc_qcom/_g1_qcom/_fcf_qcom/_g2_qcom = QCOM parameter samples (Block 8b)")
print("fig_qcom            = Plotly subplot figure: histogram + 4 parameter sparklines (QCOM)")
print("QCOM_MCS_Dashboard.png  = images/ export for README (Block 8b)")
# endregion
