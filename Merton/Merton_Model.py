"""
DCF_Merton_MC — Combined Risk Model (Merton + DCF + Monte Carlo)
=======================================================================
Run with: python Merton/Merton_Model.py [--ticker MCHP]

Select the active company via --ticker (default: MCHP | INTC | ON | QCOM | MPWR).
  Block 0: Imports & Setup
  Block 1: Load Data from FMP Cache
  Block 2: Merton Model (Distance to Default, PD)
  Block 3: Historical DD Time Series (5 years, quarterly)
  Block 4: Sensitivity Analysis + Tornado Chart
  Block 5: Stress Test Bear/Base/Bull
  Block 6: Credit Spread Derivation
  Block 7: Visualization (Stock Price + Rolling Volatility)
  Block 8: Excel Export
  Block 9: IFRS 9 ECL Integration
  Block 10: Rating Migration Matrix
  Block 11: LGD Sensitivity
  Block 12: Excel Export (Portfolio / Dashboard feed)
"""

# ----------------------------------------------------------------------------
# region BLOCK 0 - IMPORTS & SETUP
# ----------------------------------------------------------------------------
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import os
import json
import argparse
import importlib
import warnings
from datetime import date
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import norm

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
_parser = argparse.ArgumentParser(description="Merton (1974) structural credit risk model for one ticker.")
_parser.add_argument("--ticker", default="MCHP", choices=["MCHP", "INTC", "ON", "QCOM", "MPWR"],
                      help="Ticker to analyze (default: MCHP)")
ACTIVE_CONFIG = _parser.parse_args().ticker
# ─────────────────────────────────────────────────────────────

# Repo root (semiconductor-risk-analysis/) → for Config import
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load Config dynamically
config = importlib.import_module(f"Config.{ACTIVE_CONFIG}")

TICKER            = config.TICKER
COMPANY       = config.COMPANY
RISK_FREE_RATE = config.RISK_FREE_RATE
MATURITY          = config.MATURITY
EXCEL_DIR      = os.path.join(config.OUTPUT_DIR, "Excel", ACTIVE_CONFIG)
VIZ_DIR        = os.path.join(config.OUTPUT_DIR, "Visualisierung", ACTIVE_CONFIG)

# Cache lives outside the repo: set FMP_CACHE_DIR, else the project-local default applies.
CACHE_FOLDER = os.environ.get("FMP_CACHE_DIR", os.path.join(PROJECT_ROOT, "data", "FMP_Cache"))

os.makedirs(EXCEL_DIR, exist_ok=True)
os.makedirs(VIZ_DIR, exist_ok=True)

# plot_style — central design template
from plot_style import LAYOUT, BLUE_1, BLUE_2, BLUE_3, ORANGE_1, ORANGE_2, ORANGE_3, GRAY_1
BG     = "#FFFFFF"; TEXT = "#1A1A1A"; BORDER = "#E5E5E5"; TEXT_MUTED = "#9CA3AF"

# Pure calculation functions — extracted to merton_core.py (no I/O, safe to unit test)
try:
    from .merton_core import merton_model, get_rating_info, calculate_spread, RATING_TABLE
except ImportError:  # running directly as a script (python Merton/Merton_Model.py)
    from merton_core import merton_model, get_rating_info, calculate_spread, RATING_TABLE  # type: ignore[import-not-found,no-redef]


class MarketData(TypedDict):
    prices: pd.Series
    log_returns: pd.Series
    sigma_e: float
    total_debt: float
    equity_book: float
    market_cap: float

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 1 - LOAD DATA FROM FMP CACHE
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Loads price data, balance sheet, and key metrics from the local JSON cache.
# ─────────────────────────────────────────────────────────────

def load_json(filename: str) -> Any:
    """Load a JSON cache file and return its contents."""
    path = os.path.join(CACHE_FOLDER, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_market_data() -> MarketData:
    """Load and process FMP cache data for the active ticker."""

    # Historical prices — newest first in API response, sort ascending
    prices_raw   = load_json(f"{TICKER}_historical-price-eod_full.json")
    df_prices    = pd.DataFrame(prices_raw)
    df_prices["date"] = pd.to_datetime(df_prices["date"])
    df_prices    = df_prices.sort_values("date").set_index("date")
    prices       = df_prices["close"]

    # Daily log returns + annualized volatility (252 trading days)
    log_returns  = cast(pd.Series, np.log(prices / prices.shift(1))).dropna()
    sigma_e      = float(log_returns.std() * np.sqrt(252))

    # Balance sheet — index 0 = most recent fiscal year
    bs           = load_json(f"{TICKER}_balance-sheet-statement.json")[0]
    total_debt   = float(bs.get("totalDebt", 0))
    equity_book  = float(bs.get("totalStockholdersEquity", 0))

    # Key metrics — index 0 = most recent
    km           = load_json(f"{TICKER}_key-metrics.json")[0]
    market_cap   = float(km.get("marketCap", 0))

    return {
        "prices":      prices,
        "log_returns": log_returns,
        "sigma_e":     sigma_e,
        "total_debt":  total_debt,
        "equity_book": equity_book,
        "market_cap":  market_cap,
    }


market_data  = load_market_data()

prices       = market_data["prices"]
log_returns  = market_data["log_returns"]
sigma_e      = market_data["sigma_e"]
total_debt   = market_data["total_debt"]
market_cap   = market_data["market_cap"]

print(f"\n{'='*60}")
print(f"Ticker:                    {TICKER}  ({COMPANY})")
print(f"Market Capitalization:     {market_cap / 1e9:.2f} Bn USD")
print(f"Total Debt:                {total_debt / 1e9:.2f} Bn USD")
print(f"Annualized Volatility:     {sigma_e:.1%}")
print(f"{'='*60}")

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 2 - MERTON MODEL
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# The Merton (1974) model treats equity as a call option
# on the firm's asset value V with strike = debt D.
#
# Iterative Black-Scholes solution:
#   E_model   = V·N(d1) − D·e^(−rT)·N(d2)     [call price]
#   σ_E·E     = N(d1)·σ_V·V                    [Ito relation]
#
# Distance to Default:
#   DD = (ln(V/D) + (r − ½σ_V²)·T) / (σ_V·√T)
# Probability of Default:
#   PD = N(−DD)
# ─────────────────────────────────────────────────────────────

E      = market_cap
D      = total_debt
r      = RISK_FREE_RATE
T      = MATURITY

merton = merton_model(E, D, r, T, sigma_e)

print(f"\n=== Merton Model Results ===")
print(f"Firm Asset Value V:        {merton['V'] / 1e9:.2f} Bn USD")
print(f"Asset Volatility σ_V:      {merton['sigma_v']:.1%}")
print(f"Distance to Default:       {merton['dd']:.4f}")
print(f"Probability of Default:    {merton['pd']:.4%}")
print(f"Expected Loss (LGD=45%):   {merton['el'] / 1e6:.1f} Mn USD")

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 3 - HISTORICAL DD TIME SERIES
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Computes DD on a rolling basis over 5 years, sampling every 63 trading
# days (~1 quarter). Market cap = price × estimated share count.
# ─────────────────────────────────────────────────────────────

def calculate_historical_dd(
    prices: pd.Series, log_returns: pd.Series, total_debt: float, market_cap: float, r: float, T: float,
) -> pd.DataFrame:
    """Rolling Merton DD sampled every 63 trading days over 5 years."""
    cutoff    = prices.index.max() - pd.DateOffset(years=5)
    prices_5y = prices[prices.index >= cutoff]
    shares    = market_cap / float(prices.iloc[-1])
    roll_sig  = log_returns.rolling(252).std() * np.sqrt(252)

    records = []
    for i in range(0, len(prices_5y), 63):
        dt     = prices_5y.index[i]
        price  = float(prices_5y.iloc[i])
        sig_e  = float(roll_sig.get(dt, np.nan))
        mktcap = price * shares

        if np.isnan(sig_e) or sig_e <= 0 or mktcap <= 0 or total_debt <= 0:
            continue
        try:
            res = merton_model(mktcap, total_debt, r, T, sig_e)
            records.append({
                "Date":    dt,
                "DD":      res["dd"],
                "PD":      res["pd"],
                "Price":   price,
                "sigma_E": sig_e,
            })
        except Exception:
            continue

    return pd.DataFrame(records).set_index("Date")


df_dd_hist = calculate_historical_dd(prices, log_returns, total_debt, market_cap, r, T)

print(f"\n=== Historical DD Time Series ({len(df_dd_hist)} data points, 5 years) ===")
print(df_dd_hist[["DD", "PD", "Price", "sigma_E"]].round(4).to_string())


def create_dd_time_series_chart(df: pd.DataFrame, output_path: str) -> str:
    """Two-panel chart: rolling DD with reference lines + stock price."""
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=[
            f"{COMPANY} — Distance to Default (5 Years, Quarterly)",
            "Stock Price (USD)",
        ],
        row_heights=[0.6, 0.4],
    )

    # Panel 1: DD time series
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["DD"],
            mode="lines+markers", name="Distance to Default",
            line=dict(color=BLUE_1, width=2),
            marker=dict(size=5),
        ),
        row=1, col=1,
    )

    # Reference lines as horizontal traces
    for level, color, label in [
        (2, ORANGE_2,    "DD=2 (critical)"),
        (4, ORANGE_1, "DD=4 (elevated)"),
        (6, BLUE_2,  "DD=6 (safe)"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=[df.index[0], df.index[-1]], y=[level, level],
                mode="lines", name=label,
                line=dict(color=color, dash="dash", width=1.2),
                showlegend=True,
            ),
            row=1, col=1,
        )

    # Panel 2: Stock price
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["Price"],
            mode="lines", name="Stock Price",
            line=dict(color=ORANGE_1, width=1.6),
        ),
        row=2, col=1,
    )

    fig.update_layout(
        **LAYOUT,
        title=dict(text=f"{COMPANY} — Historical Distance to Default",
                   font=dict(size=15, color="#0B1220"), x=0.0),
        showlegend=True,
        height=700,
        margin=dict(l=60, r=40, t=80, b=60),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor=BORDER)
    fig.update_yaxes(showgrid=False, showline=True, linecolor=BORDER)
    fig.update_yaxes(title_text="DD", row=1, col=1)
    fig.update_yaxes(title_text="USD", row=2, col=1)

    chart_path = os.path.join(output_path, f"{TICKER}_DD_TimeSeries.png")
    try:
        fig.write_image(chart_path, width=1200, height=700, scale=1.5)
        print(f"DD time series chart saved: {chart_path}")
    except Exception:
        html_path = chart_path.replace(".png", ".html")
        fig.write_html(html_path)
        print(f"DD time series chart (HTML) saved: {html_path}")

    return chart_path


create_dd_time_series_chart(df_dd_hist, VIZ_DIR)

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 4 - SENSITIVITY ANALYSIS + TORNADO CHART
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Varies D, E, sigma_E individually from -30% to +30% in 10% steps.
# All other inputs held constant at base values.
# Tornado chart shows ΔDD vs. base for ±30% per variable.
# ─────────────────────────────────────────────────────────────

SENS_STEPS = [-0.30, -0.20, -0.10, 0.0, 0.10, 0.20, 0.30]

sens_params = {
    "Debt D":       ("D",       D),
    "Market Cap E": ("E",       E),
    "Volatility σ_E": ("sigma_e", sigma_e),
}

sens_records = []
for label, (key, base_val) in sens_params.items():
    for delta in SENS_STEPS:
        varied = base_val * (1 + delta)
        kw = {"E": E, "D": D, "r": r, "T": T, "sigma_e": sigma_e}
        kw[key] = varied
        try:
            res = merton_model(kw["E"], kw["D"], kw["r"], kw["T"], kw["sigma_e"])
            sens_records.append({
                "Variable": label,
                "Delta_%":  round(delta * 100),
                "DD":       res["dd"],
                "PD":       res["pd"],
            })
        except Exception:
            pass

df_sens = pd.DataFrame(sens_records)

# Terminal output: -30% and +30% per variable, sorted by impact
dd_base_val = merton["dd"]
print(f"\n=== Sensitivity Analysis ===")
print(f"{'Variable':<22} {'DD -30%':>9} {'DD Base':>9} {'DD +30%':>9} {'Impact':>10}")
print("-" * 63)

sens_summary = []
for label in sens_params:
    sub   = df_sens[df_sens["Variable"] == label]
    dd_lo = float(sub[sub["Delta_%"] == -30]["DD"].iloc[0])
    dd_hi = float(sub[sub["Delta_%"] ==  30]["DD"].iloc[0])
    impact = abs(dd_hi - dd_lo)
    sens_summary.append((label, dd_lo, dd_hi, impact))

sens_summary.sort(key=lambda x: x[3], reverse=True)
for label, dd_lo, dd_hi, impact in sens_summary:
    print(f"{label:<22} {dd_lo:>9.4f} {dd_base_val:>9.4f} {dd_hi:>9.4f} {impact:>10.4f}")


def create_tornado_chart(
    sens_summary: list[tuple[str, float, float, float]], dd_base_val: float, output_path: str,
) -> str:
    """Horizontal tornado chart: ΔDD at ±30% per variable, sorted by influence."""
    sorted_asc   = sorted(sens_summary, key=lambda x: x[3])  # smallest at bottom
    labels_chart = [s[0] for s in sorted_asc]

    fig = go.Figure()
    legend_shown = {"pos": False, "neg": False}

    for label, dd_lo, dd_hi, impact in sorted_asc:
        for delta_dd, direction in [
            (dd_lo - dd_base_val, "-30%"),
            (dd_hi - dd_base_val, "+30%"),
        ]:
            is_pos = delta_dd >= 0
            group  = "pos" if is_pos else "neg"
            color  = BLUE_1  if is_pos else ORANGE_2
            lname  = "DD increases (+)" if is_pos else "DD decreases (−)"
            fig.add_trace(go.Bar(
                x=[delta_dd], y=[label],
                orientation="h",
                marker_color=color,
                name=lname,
                legendgroup=group,
                showlegend=not legend_shown[group],
                opacity=0.85,
            ))
            legend_shown[group] = True

    fig.add_vline(x=0, line_color=TEXT, line_width=1.5)

    fig.update_layout(
        **LAYOUT,
        title=dict(
            text=(f"{COMPANY} — Sensitivity Analysis Distance to Default<br>"
                  f"<sup>Base DD = {dd_base_val:.4f} | Variation ±10% / ±20% / ±30%</sup>"),
            font=dict(size=15, color="#0B1220"), x=0.0,
        ),
        barmode="overlay",
        xaxis_title="ΔDD vs. Base",
        yaxis=dict(categoryorder="array", categoryarray=labels_chart,
                   showgrid=False, showline=True, linecolor=BORDER),
        height=420,
        margin=dict(l=160, r=60, t=110, b=60),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor=BORDER,
                     zeroline=True, zerolinecolor=TEXT, zerolinewidth=1.5)

    chart_path = os.path.join(output_path, f"{TICKER}_Tornado.png")
    try:
        fig.write_image(chart_path, width=900, height=420, scale=1.5)
        print(f"Tornado chart saved: {chart_path}")
    except Exception:
        html_path = chart_path.replace(".png", ".html")
        fig.write_html(html_path)
        print(f"Tornado chart (HTML) saved: {html_path}")

    return chart_path


create_tornado_chart(sens_summary, dd_base_val, VIZ_DIR)

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 5 - STRESS TEST BEAR/BASE/BULL
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Three scenarios vary E, D, and sigma_E simultaneously:
#   Bear: market crash — price −40%, vol +50%, debt +10%
#   Base: current      — base values unchanged
#   Bull: upswing       — price +25%, vol −20%, debt −10%
# ─────────────────────────────────────────────────────────────

SCENARIOS: dict[str, dict[str, Any]] = {
    "Bear": {"E": E * 0.60, "D": D * 1.10, "sigma_e": sigma_e * 1.50, "color": ORANGE_2},
    "Base": {"E": E,        "D": D,         "sigma_e": sigma_e,         "color": BLUE_1},
    "Bull": {"E": E * 1.25, "D": D * 0.90,  "sigma_e": sigma_e * 0.80, "color": BLUE_2},
}


def rating_assessment(dd: float) -> str:
    if dd > 6:   return "AA/A  — very safe"
    elif dd > 4: return "BBB   — investment grade"
    elif dd > 2: return "BB/B  — sub-investment grade"
    else:        return "CCC   — critical"


stress_results: dict[str, dict[str, Any]] = {}
for scen, params in SCENARIOS.items():
    res = merton_model(params["E"], params["D"], r, T, params["sigma_e"])
    stress_results[scen] = {
        "V":      res["V"],
        "DD":     res["dd"],
        "PD":     res["pd"],
        "EL":     res["el"],
        "Rating": rating_assessment(res["dd"]),
        "color":  params["color"],
    }

print(f"\n=== Stress Test Scenarios ===")
print(f"{'Scenario':<8} {'V (Bn)':>9} {'DD':>8} {'PD':>10} {'EL (Mn)':>10}  Rating")
print("-" * 72)
for scen, sd in stress_results.items():
    print(f"{scen:<8} {sd['V']/1e9:>9.2f} {sd['DD']:>8.4f} {sd['PD']:>10.4%} {sd['EL']/1e6:>10.2f}  {sd['Rating']}")


def create_stress_chart(stress_results: dict[str, dict[str, Any]], output_path: str) -> str:
    """Grouped bar chart: DD (primary y-axis) and PD% (secondary y-axis) per scenario."""
    scenarios = list(stress_results.keys())
    dd_vals   = [stress_results[s]["DD"] for s in scenarios]
    pd_vals   = [stress_results[s]["PD"] * 100 for s in scenarios]
    colors    = [stress_results[s]["color"] for s in scenarios]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=scenarios, y=dd_vals,
        name="Distance to Default",
        marker_color=colors,
        opacity=0.85,
        text=[f"{v:.4f}" for v in dd_vals],
        textposition="outside",
        yaxis="y",
    ))

    fig.add_trace(go.Bar(
        x=scenarios, y=pd_vals,
        name="PD (%)",
        marker_color=colors,
        opacity=0.40,
        text=[f"{v:.4f}%" for v in pd_vals],
        textposition="outside",
        yaxis="y2",
    ))

    for level, color, label in [
        (2, ORANGE_2,    "DD=2 critical"),
        (4, ORANGE_1, "DD=4 elevated"),
        (6, BLUE_2,  "DD=6 safe"),
    ]:
        fig.add_hline(y=level, line_dash="dash", line_color=color, line_width=1.2,
                      annotation_text=label, annotation_position="top left")

    fig.update_layout(
        **LAYOUT,
        title=dict(
            text=(f"{COMPANY} — Stress Test Scenarios<br>"
                  f"<sup>Bear: Price −40%, Vol +50%, D +10% | Bull: Price +25%, Vol −20%, D −10%</sup>"),
            font=dict(size=15, color="#0B1220"), x=0.0,
        ),
        barmode="group",
        height=520,
        margin=dict(l=60, r=100, t=110, b=60),
        yaxis=dict(title="Distance to Default", showgrid=False, showline=True, linecolor=BORDER),
        yaxis2=dict(title="PD (%)", overlaying="y", side="right",
                    showgrid=False, tickformat=".4f"),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor=BORDER)

    chart_path = os.path.join(output_path, f"{TICKER}_StressTest.png")
    try:
        fig.write_image(chart_path, width=900, height=520, scale=1.5)
        print(f"Stress test chart saved: {chart_path}")
    except Exception:
        html_path = chart_path.replace(".png", ".html")
        fig.write_html(html_path)
        print(f"Stress test chart (HTML) saved: {html_path}")

    return chart_path


create_stress_chart(stress_results, VIZ_DIR)

df_stress = pd.DataFrame([
    {
        "Scenario": scen,
        "E_Bn":     SCENARIOS[scen]["E"] / 1e9,
        "D_Bn":     SCENARIOS[scen]["D"] / 1e9,
        "sigma_E":  SCENARIOS[scen]["sigma_e"],
        "V_Bn":     stress_results[scen]["V"] / 1e9,
        "DD":       stress_results[scen]["DD"],
        "PD":       stress_results[scen]["PD"],
        "EL_Mio":   stress_results[scen]["EL"] / 1e6,
        "Rating":   stress_results[scen]["Rating"],
    }
    for scen in SCENARIOS
])

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 6 - CREDIT SPREAD DERIVATION
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Theoretical spread from Merton PD and LGD=45%:
#   s = -ln(1 − PD · LGD) / T  →  in basis points × 10000
# Compared against market benchmarks by DD-based rating class.
# ─────────────────────────────────────────────────────────────

basis_spread_bps            = calculate_spread(merton["pd"], T) * 10000
basis_rating, basis_lo, basis_hi = get_rating_info(merton["dd"])

print(f"\n=== Credit Spread Analysis ===")
print(f"Merton PD:                {merton['pd']:.4%}")
print(f"Theoretical Spread:      {basis_spread_bps:.1f} bps")
print(f"Rating Class (DD-Based):  {basis_rating}")
print(f"Market Benchmark Spread:  {basis_lo}-{basis_hi} bps")
_valuation_flag_basis = "UNDER" if basis_spread_bps < basis_lo else ("OVER" if basis_spread_bps > basis_hi else "WITHIN")
print(f"Valuation:                Model {_valuation_flag_basis} market range")

print(f"\n{'Scenario':<8} {'PD':>10} {'Spread (bps)':>14} {'Benchmark':<22} {'Valuation':>10}")
print("-" * 68)

spread_records = []
for scen in ["Bear", "Base", "Bull"]:
    sd          = stress_results[scen]
    s_bps       = calculate_spread(sd["PD"], T) * 10000
    rat, lo, hi = get_rating_info(sd["DD"])
    valuation_flag = "UNDER" if s_bps < lo else ("OVER" if s_bps > hi else "WITHIN")
    bench_str   = f"{rat}: {lo}-{hi} bps"
    print(f"{scen:<8} {sd['PD']:>10.4%} {s_bps:>14.1f} {bench_str:<22} {valuation_flag:>10}")
    spread_records.append({
        "Scenario":     scen,
        "DD":           sd["DD"],
        "PD":           sd["PD"],
        "Spread_bps":   s_bps,
        "Rating":       rat,
        "Benchmark_lo": lo,
        "Benchmark_hi": hi,
        "Valuation":    valuation_flag,
    })

df_credit = pd.DataFrame(spread_records)


def create_spread_chart(df_credit: pd.DataFrame, output_path: str) -> str:
    """Grouped bar chart: model spread vs. benchmark midpoint with error bars."""
    scenarios    = df_credit["Scenario"].tolist()
    spreads      = df_credit["Spread_bps"].tolist()
    bench_lo     = df_credit["Benchmark_lo"].tolist()
    bench_hi     = df_credit["Benchmark_hi"].tolist()
    bench_mid    = [(lo + hi) / 2 for lo, hi in zip(bench_lo, bench_hi)]
    bench_err_hi = [(hi - mid) for hi, mid in zip(bench_hi, bench_mid)]
    bench_err_lo = [(mid - lo) for mid, lo in zip(bench_mid, bench_lo)]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=scenarios, y=spreads,
        name="Model Spread (Merton)",
        marker_color=BLUE_1,
        opacity=0.85,
        text=[f"{v:.1f} bps" for v in spreads],
        textposition="outside",
    ))

    fig.add_trace(go.Bar(
        x=scenarios, y=bench_mid,
        name="Market Benchmark (Mid)",
        marker_color=GRAY_1,
        opacity=0.55,
        error_y=dict(
            type="data",
            array=bench_err_hi,
            arrayminus=bench_err_lo,
            visible=True,
            color=GRAY_1,
            thickness=2,
            width=8,
        ),
        text=[f"{lo}–{hi} bps" for lo, hi in zip(bench_lo, bench_hi)],
        textposition="outside",
    ))

    fig.update_layout(
        **LAYOUT,
        title=dict(
            text=(f"{COMPANY} — Credit Spread Analysis<br>"
                  f"<sup>Merton Spread vs. Market Benchmark | s = −ln(1 − PD·LGD) / T</sup>"),
            font=dict(size=15, color="#0B1220"), x=0.0,
        ),
        barmode="group",
        yaxis=dict(title="Credit Spread (bps)", showgrid=False, showline=True, linecolor=BORDER),
        height=480,
        margin=dict(l=60, r=60, t=110, b=60),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor=BORDER)

    chart_path = os.path.join(output_path, f"{TICKER}_CreditSpread.png")
    try:
        fig.write_image(chart_path, width=900, height=480, scale=1.5)
        print(f"\nCredit spread chart saved: {chart_path}")
    except Exception:
        html_path = chart_path.replace(".png", ".html")
        fig.write_html(html_path)
        print(f"\nCredit spread chart (HTML) saved: {html_path}")

    return chart_path


create_spread_chart(df_credit, VIZ_DIR)

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 7 - VISUALIZATION
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Plotly chart with two panels:
#   Panel 1: Historical stock price (last 2 years)
#   Panel 2: Rolling 30-day volatility (annualized)
# ─────────────────────────────────────────────────────────────

def create_merton_chart(
    prices: pd.Series, log_returns: pd.Series, merton_results: dict[str, float], output_path: str,
) -> str:
    """Two-panel plotly chart: stock price (2y) + 30d rolling volatility."""

    cutoff    = prices.index.max() - pd.DateOffset(years=2)
    prices_2y = prices[prices.index >= cutoff]
    ret_2y    = log_returns[log_returns.index >= cutoff]
    roll_vol  = ret_2y.rolling(30).std() * np.sqrt(252)

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=[
            f"{COMPANY} — Stock Price (2 Years)",
            "Rolling 30-Day Volatility (Annualized)",
        ],
        row_heights=[0.65, 0.35],
    )

    # Panel 1: Stock price
    fig.add_trace(
        go.Scatter(
            x=prices_2y.index, y=prices_2y.values,
            mode="lines", name="Price",
            line=dict(color=BLUE_1, width=1.8),
        ),
        row=1, col=1,
    )

    # Panel 2: Rolling volatility
    fig.add_trace(
        go.Scatter(
            x=roll_vol.index, y=roll_vol.values,
            mode="lines", name="Volatility 30d",
            line=dict(color=ORANGE_1, width=1.6),
            fill="tozeroy",
            fillcolor="rgba(212,168,67,0.15)",
        ),
        row=2, col=1,
    )

    fig.update_layout(
        **LAYOUT,
        title=dict(
            text=(f"{COMPANY} — Merton Model Analysis<br>"
                  f"<sup>DD = {merton_results['dd']:.4f} | "
                  f"PD = {merton_results['pd']:.4%} | "
                  f"σ_V = {merton_results['sigma_v']:.1%}</sup>"),
            font=dict(size=15, color="#0B1220"), x=0.0,
        ),
        showlegend=True,
        height=700,
        margin=dict(l=60, r=40, t=110, b=60),
    )
    fig.update_xaxes(showgrid=False, showline=True, linecolor=BORDER)
    fig.update_yaxes(showgrid=False, showline=True, linecolor=BORDER)
    fig.update_yaxes(title_text="USD", row=1, col=1)
    fig.update_yaxes(title_text="σ (ann.)", tickformat=".0%", row=2, col=1)

    chart_path = os.path.join(output_path, f"{TICKER}_Merton.png")
    try:
        fig.write_image(chart_path, width=1200, height=700, scale=1.5)
        print(f"\nChart saved: {chart_path}")
    except Exception:
        # kaleido not installed → save as HTML
        html_path = chart_path.replace(".png", ".html")
        fig.write_html(html_path)
        print(f"\nChart (HTML) saved: {html_path}")
        print("  Note: 'pip install kaleido' for PNG export")

    return chart_path


create_merton_chart(prices, log_returns, merton, VIZ_DIR)

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 8 - EXPORT
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Excel export with two sheets:
#   Sheet 1: Merton_Ergebnisse — all calculated values + parameters
#   Sheet 2: Marktdaten — prices, log returns, rolling volatility
# ─────────────────────────────────────────────────────────────

def export_excel(
    prices: pd.Series, log_returns: pd.Series, merton_results: dict[str, float],
    df_dd: pd.DataFrame, df_sens: pd.DataFrame, df_stress: pd.DataFrame, df_credit: pd.DataFrame,
    output_path: str,
) -> str:
    """Export Merton results, market data, DD time series, sensitivity, stress test, and credit spreads to Excel."""

    excel_path = os.path.join(output_path, f"{TICKER}_Merton.xlsx")

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:

        # Sheet 1: Merton results
        df_results = pd.DataFrame({
            "Parameter": [
                "Company", "Ticker", "Date",
                "Market Cap (USD)", "Total Debt (USD)",
                "Risk-free Rate", "Maturity (Years)",
                "Equity Volatility σ_E (ann.)",
                "---",
                "Firm Asset Value V (USD)", "Asset Volatility σ_V",
                "Distance to Default (DD)", "Probability of Default PD",
                "Expected Loss (LGD=45%, USD)",
            ],
            "Value": [
                COMPANY, TICKER, str(date.today()),
                f"{market_cap:,.0f}", f"{total_debt:,.0f}",
                f"{r:.3%}", str(T),
                f"{sigma_e:.4%}",
                "",
                f"{merton_results['V']:,.0f}", f"{merton_results['sigma_v']:.4%}",
                f"{merton_results['dd']:.6f}", f"{merton_results['pd']:.6%}",
                f"{merton_results['el']:,.0f}",
            ],
        })
        df_results.to_excel(writer, sheet_name="Merton_Results", index=False)

        # Sheet 2: Market data
        roll_vol = log_returns.rolling(30).std() * np.sqrt(252)
        df_market = pd.DataFrame({
            "Date":          prices.index,
            "Price_USD":     prices.values,
            "Log_Return":    log_returns.reindex(prices.index).values,
            "Roll_Vol_30d":  roll_vol.reindex(prices.index).values,
        })
        df_market.to_excel(writer, sheet_name="Market_Data", index=False)

        # Sheet 3: DD time series
        df_dd_export = df_dd.reset_index()
        df_dd_export.columns = ["Date", "DD", "PD", "Price_USD", "sigma_E"]
        df_dd_export.to_excel(writer, sheet_name="DD_TimeSeries", index=False)

        # Sheet 4: Sensitivity analysis
        df_sens.to_excel(writer, sheet_name="Sensitivity", index=False)

        # Sheet 5: Stress test
        df_stress.to_excel(writer, sheet_name="Stress_Test", index=False)

        # Sheet 6: Credit spread
        df_credit.to_excel(writer, sheet_name="Credit_Spread", index=False)

    print(f"Excel saved: {excel_path}")
    return excel_path


export_excel(prices, log_returns, merton, df_dd_hist, df_sens, df_stress, df_credit, EXCEL_DIR)

print(f"\n{'='*60}")
print(f"Done. Excel: {EXCEL_DIR}  |  Charts: {VIZ_DIR}")
print(f"{'='*60}\n")

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 9 - IFRS 9 ECL INTEGRATION
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Expected Credit Loss per IFRS 9:
#   Stage 1 (12M ECL):      PD_12M      * LGD * EAD
#   Stage 2 (Lifetime ECL): PD_lifetime * LGD * EAD
#   Stage 3 (credit-impaired): LGD * EAD  (PD=1)
# Stage assignment: DD>4 → Stage 1 | DD 2-4 → Stage 2 | DD<2 → Stage 3
# ─────────────────────────────────────────────────────────────

LGD_IFRS9 = 0.45
EAD       = total_debt

merton_1y   = merton_model(E, D, r, 1.0, sigma_e)
PD_12M      = merton_1y["pd"]

merton_5y   = merton_model(E, D, r, 5.0, sigma_e)
PD_lifetime = merton_5y["pd"]

ECL_12M      = PD_12M      * LGD_IFRS9 * EAD
ECL_Lifetime = PD_lifetime * LGD_IFRS9 * EAD
ECL_Stage3   = LGD_IFRS9 * EAD

_dd_ifrs = merton["dd"]
if _dd_ifrs > 4:
    ifrs9_stage = 1
    ecl_used    = ECL_12M
elif _dd_ifrs >= 2:
    ifrs9_stage = 2
    ecl_used    = ECL_Lifetime
else:
    ifrs9_stage = 3
    ecl_used    = ECL_Stage3

print(f"\n=== IFRS 9 Expected Credit Loss ===")
print(f"{'Parameter':<30} {'Value':>15}")
print("-" * 47)
print(f"{'EAD (Total Debt)':<30} {EAD/1e9:>14.2f}B")
print(f"{'LGD (ISDA Standard)':<30} {LGD_IFRS9:>14.0%}")
print(f"{'PD 12M (T=1)':<30} {PD_12M:>14.6%}")
print(f"{'PD Lifetime (T=5)':<30} {PD_lifetime:>14.6%}")
print(f"{'ECL Stage 1 (12M, Mn)':<30} {ECL_12M/1e6:>14.3f}")
print(f"{'ECL Stage 2 (Lifetime, Mn)':<30} {ECL_Lifetime/1e6:>14.3f}")
print(f"{'ECL Stage 3 (impaired, Mn)':<30} {ECL_Stage3/1e6:>14.3f}")
print(f"{'─'*47}")
print(f"{'IFRS 9 Stage':<30} {'Stage ' + str(ifrs9_stage):>15}")
print(f"{'ECL (current stage, Mn)':<30} {ecl_used/1e6:>14.3f}")

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 10 - RATING MIGRATION MATRIX
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Derives rating per quarter from the historical DD time series.
# Counts transitions between ratings and shows
# transition probabilities as a matrix + heatmap.
# ─────────────────────────────────────────────────────────────

RATINGS_ORDERED = ["AAA/AA", "A", "BBB", "BB", "B", "CCC"]


def dd_to_rating(dd: float) -> str:
    if dd >= 8:   return "AAA/AA"
    elif dd >= 6: return "A"
    elif dd >= 4: return "BBB"
    elif dd >= 2: return "BB"
    elif dd >= 1: return "B"
    else:         return "CCC"


df_dd_rated = df_dd_hist.copy()
df_dd_rated["Rating"] = df_dd_rated["DD"].apply(dd_to_rating)

migration_counts = pd.DataFrame(0, index=RATINGS_ORDERED, columns=RATINGS_ORDERED)
ratings_list = df_dd_rated["Rating"].tolist()
for i in range(len(ratings_list) - 1):
    migration_counts.loc[ratings_list[i], ratings_list[i + 1]] += 1

row_sums = migration_counts.sum(axis=1).replace(0, 1)
migration_probs = migration_counts.div(row_sums, axis=0)

print(f"\n=== Rating Migration Matrix — {TICKER} (5Y, Quarterly) ===")
print("Transition counts:")
print(migration_counts.to_string())
print("\nTransition probabilities:")
print(migration_probs.round(4).to_string())


def create_migration_heatmap(migration_probs: pd.DataFrame, output_path: str) -> str:
    z_vals = migration_probs.values.tolist()
    text_vals = [[f"{v:.0%}" if v > 0 else "" for v in row] for row in z_vals]

    fig = go.Figure(go.Heatmap(
        z=z_vals,
        x=RATINGS_ORDERED,
        y=RATINGS_ORDERED,
        colorscale=[[0, BG], [1, BLUE_1]],
        text=text_vals,
        texttemplate="%{text}",
        textfont=dict(size=12, color=TEXT),
        colorbar=dict(title="P(Transition)", tickformat=".0%"),
    ))
    fig.update_layout(
        **LAYOUT,
        title=dict(
            text=(f"{COMPANY} — Rating Migration Matrix<br>"
                  f"<sup>Quarterly DD Time Series (5 Years) | Transition Probabilities</sup>"),
            font=dict(size=15, color="#0B1220"), x=0.0,
        ),
        xaxis=dict(title="To Rating", showgrid=False, showline=True, linecolor=BORDER),
        yaxis=dict(title="From Rating", showgrid=False, showline=True, linecolor=BORDER,
                   autorange="reversed"),
        height=480,
        margin=dict(l=80, r=40, t=110, b=80),
    )
    chart_path = os.path.join(output_path, f"{TICKER}_RatingMigration.png")
    try:
        fig.write_image(chart_path, width=800, height=480, scale=1.5)
        print(f"Migration heatmap saved: {chart_path}")
    except Exception:
        html_path = chart_path.replace(".png", ".html")
        fig.write_html(html_path)
        print(f"Migration heatmap (HTML) saved: {html_path}")
    return chart_path


create_migration_heatmap(migration_probs, VIZ_DIR)

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 11 - LGD SENSITIVITY
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# Varies LGD 10%–90%, computes EL, spread, ECL_12M
# for Bear/Base/Bull scenarios. Line chart + table.
# ─────────────────────────────────────────────────────────────

LGD_VALUES = [round(x * 0.10, 2) for x in range(1, 10)]

lgd_records = []
for scen_name in ["Bear", "Base", "Bull"]:
    params   = SCENARIOS[scen_name]
    res_scen = merton_model(params["E"], params["D"], r, T,   params["sigma_e"])
    res_1y   = merton_model(params["E"], params["D"], r, 1.0, params["sigma_e"])
    pd_scen  = res_scen["pd"]
    pd_1y_s  = res_1y["pd"]
    for lgd in LGD_VALUES:
        pd_lgd     = min(pd_scen * lgd, 0.9999)
        spread_bps = (-np.log(1 - pd_lgd) / T * 10000) if pd_lgd > 0 else 0.0
        lgd_records.append({
            "LGD":         lgd,
            "Scenario":    scen_name,
            "EL_Mio":      pd_scen * lgd * D / 1e6,
            "Spread_bps":  spread_bps,
            "ECL_12M_Mio": pd_1y_s * lgd * EAD / 1e6,
        })

df_lgd = pd.DataFrame(lgd_records)

print(f"\n=== LGD Sensitivity Analysis ===")
print(f"{'LGD':>6}  {'EL Bear (M)':>12} {'EL Base (M)':>12} {'EL Bull (M)':>12}  {'Spread Base (bps)':>18}")
print("-" * 68)
for lgd in LGD_VALUES:
    sub     = df_lgd[df_lgd["LGD"] == lgd]
    el_bear = sub[sub["Scenario"] == "Bear"]["EL_Mio"].values[0]
    el_base = sub[sub["Scenario"] == "Base"]["EL_Mio"].values[0]
    el_bull = sub[sub["Scenario"] == "Bull"]["EL_Mio"].values[0]
    sp_base = sub[sub["Scenario"] == "Base"]["Spread_bps"].values[0]
    print(f"{lgd:>6.0%}  {el_bear:>12.2f} {el_base:>12.2f} {el_bull:>12.2f}  {sp_base:>18.1f}")


def create_lgd_chart(df_lgd: pd.DataFrame, output_path: str) -> str:
    colors_scenario = {"Bear": ORANGE_2, "Base": BLUE_1, "Bull": BLUE_2}
    fig = go.Figure()
    for scen in ["Bear", "Base", "Bull"]:
        sub = df_lgd[df_lgd["Scenario"] == scen].sort_values("LGD")
        fig.add_trace(go.Scatter(
            x=[f"{v:.0%}" for v in sub["LGD"]],
            y=sub["EL_Mio"],
            mode="lines+markers",
            name=f"EL {scen}",
            line=dict(color=colors_scenario[scen], width=2),
            marker=dict(size=6),
        ))
    fig.update_layout(
        **LAYOUT,
        title=dict(
            text=(f"{COMPANY} — LGD Sensitivity<br>"
                  f"<sup>Expected Loss (USD Mn) across LGD 10%–90% | Bear / Base / Bull</sup>"),
            font=dict(size=15, color="#0B1220"), x=0.0,
        ),
        xaxis=dict(title="LGD", showgrid=False, showline=True, linecolor=BORDER),
        yaxis=dict(title="Expected Loss (USD Mn)", showgrid=False, showline=True, linecolor=BORDER),
        height=460,
        margin=dict(l=60, r=40, t=110, b=60),
    )
    chart_path = os.path.join(output_path, f"{TICKER}_LGD_Sensitivitaet.png")
    try:
        fig.write_image(chart_path, width=900, height=460, scale=1.5)
        print(f"LGD sensitivity chart saved: {chart_path}")
    except Exception:
        html_path = chart_path.replace(".png", ".html")
        fig.write_html(html_path)
        print(f"LGD sensitivity chart (HTML) saved: {html_path}")
    return chart_path


create_lgd_chart(df_lgd, VIZ_DIR)

# endregion


# ----------------------------------------------------------------------------
# region BLOCK 12 - EXCEL EXPORT (PORTFOLIO / DASHBOARD FEED)
# ----------------------------------------------------------------------------
# ─────────────────────────────────────────────────────────────
# All cross-ticker and dashboard datasets in one .xlsx workbook
# (one sheet each), saved to the shared Reports folder.
# Read back by the Merton chart scripts (Dashboard, DD time series).
# ─────────────────────────────────────────────────────────────

REPORTS_BASE = os.path.join(config.OUTPUT_DIR, "Excel")   # <project>/Outputs/Excel
os.makedirs(REPORTS_BASE, exist_ok=True)

# 1. Summary — all 5 tickers
_ALL_TICKERS  = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]
_summary_rows = []
for _tkr in _ALL_TICKERS:
    _cfg  = importlib.import_module(f"Config.{_tkr}")
    _raw  = load_json(f"{_tkr}_historical-price-eod_full.json")
    _pr_df = pd.DataFrame(_raw)
    _pr_df["date"] = pd.to_datetime(_pr_df["date"])
    _pr   = _pr_df.sort_values("date").set_index("date")["close"]
    _se   = float(cast(pd.Series, np.log(_pr / _pr.shift(1))).dropna().std() * np.sqrt(252))
    _bs   = load_json(f"{_tkr}_balance-sheet-statement.json")[0]
    _km   = load_json(f"{_tkr}_key-metrics.json")[0]
    _E    = float(_km.get("marketCap", 0) or 0)
    _D    = float(_bs.get("totalDebt",  0) or 0)
    _r    = _cfg.RISK_FREE_RATE
    _T    = _cfg.MATURITY
    _m    = merton_model(_E, _D, _r, _T,  _se)
    _m1y  = merton_model(_E, _D, _r, 1.0, _se)
    _m5y  = merton_model(_E, _D, _r, 5.0, _se)
    _rat, _, _ = get_rating_info(_m["dd"])
    _stage = 1 if _m["dd"] > 4 else (2 if _m["dd"] >= 2 else 3)
    _summary_rows.append({
        "Ticker":        _tkr,
        "DD":            round(_m["dd"],      4),
        "PD":            round(_m["pd"],      6),
        # The 5-year PD was already computed for the lifetime ECL but never
        # reported. It is the more informative of the two: at a one-year horizon
        # the structural model returns a near-zero PD for any investment-grade
        # issuer, while the five-year figure lands in the range of observed
        # cumulative default rates.
        "PD_5Y":         round(_m5y["pd"],    6),
        "sigma_V":       round(_m["sigma_v"], 4),
        "sigma_E":       round(_se,           4),
        "MarketCap_Bn":  round(_E / 1e9,     2),
        "Debt_Bn":       round(_D / 1e9,     2),
        "Rating":        _rat,
        # The agency rating sits in the Config files but was never used. Carrying
        # it here makes the comparison explicit: the model letters are internal,
        # derived purely from equity volatility and leverage, and a structural
        # model runs more conservatively than an agency, which also weighs
        # qualitative factors the model cannot see.
        "Rating_Agency": getattr(_cfg, "RATING", "n/a"),
        "ECL_Stage":     _stage,
        "ECL_12M":       round(_m1y["pd"] * 0.45 * _D / 1e6, 4),
        "ECL_Lifetime":  round(_m5y["pd"] * 0.45 * _D / 1e6, 4),
        "Spread_bps":    round(calculate_spread(_m["pd"], _T) * 10000, 2),
    })
df_summary_csv = pd.DataFrame(_summary_rows)

# 2. DD_TimeSeries — active ticker (MCHP)
df_dd_csv = df_dd_hist.copy().reset_index()
df_dd_csv["Rating"] = df_dd_csv["DD"].apply(dd_to_rating)
df_dd_csv.columns  = ["Date", "DD", "PD", "Price", "sigma_E", "Rating"]

# 3. Stress_Test
df_stress_csv = df_stress.copy()
spreads_col = []
for scen in df_stress_csv["Scenario"]:
    sd = stress_results[scen]
    spreads_col.append(round(calculate_spread(sd["PD"], T) * 10000, 2))
df_stress_csv["Spread_bps"] = spreads_col

# 4. LGD_Sensitivity → df_lgd (already built in Block 11)

# 5. Rating_Migration
migration_flat = []
for from_rating in RATINGS_ORDERED:
    for to_rating in RATINGS_ORDERED:
        count = int(cast(int, migration_counts.loc[from_rating, to_rating]))
        prob  = round(float(cast(float, migration_probs.loc[from_rating, to_rating])), 4)
        migration_flat.append({
            "From_Rating":  from_rating,
            "To_Rating":    to_rating,
            "Count":        count,
            "Probability":  prob,
        })
df_migration_csv = pd.DataFrame(migration_flat)

# 6. DD_TimeSeries_All — DD time series for all 5 tickers (long format, 80 rows)
_dd_alle_rows = []
for _tkr in _ALL_TICKERS:
    _cfg_t = importlib.import_module(f"Config.{_tkr}")
    _raw_t = load_json(f"{_tkr}_historical-price-eod_full.json")
    _pr_t_df = pd.DataFrame(_raw_t)
    _pr_t_df["date"] = pd.to_datetime(_pr_t_df["date"])
    _pr_t  = _pr_t_df.sort_values("date").set_index("date")["close"]
    _lr_t  = cast(pd.Series, np.log(_pr_t / _pr_t.shift(1))).dropna()
    _bs_t  = load_json(f"{_tkr}_balance-sheet-statement.json")[0]
    _km_t  = load_json(f"{_tkr}_key-metrics.json")[0]
    _E_t   = float(_km_t.get("marketCap", 0) or 0)
    _D_t   = float(_bs_t.get("totalDebt",  0) or 0)
    _r_t   = _cfg_t.RISK_FREE_RATE
    _T_t   = _cfg_t.MATURITY
    _df_t  = calculate_historical_dd(_pr_t, _lr_t, _D_t, _E_t, _r_t, _T_t).reset_index()
    _df_t["Ticker"] = _tkr
    _df_t["Rating"] = _df_t["DD"].apply(dd_to_rating)
    _df_t  = _df_t[["Date", "Ticker", "DD", "PD", "Price", "Rating"]]
    _dd_alle_rows.append(_df_t)

df_dd_alle = pd.concat(_dd_alle_rows, ignore_index=True).sort_values(["Date", "Ticker"]).reset_index(drop=True)

# 7. DD_Pivot — same data, pivoted wide (16 rows × 6 columns)
df_dd_pivot = df_dd_alle.pivot_table(index="Date", columns="Ticker", values="DD", aggfunc="first")
df_dd_pivot.columns.name = None
df_dd_pivot = df_dd_pivot.rename(columns={t: f"{t}_DD" for t in _ALL_TICKERS})
_pivot_col_order = [f"{t}_DD" for t in _ALL_TICKERS if f"{t}_DD" in df_dd_pivot.columns]
df_dd_pivot = df_dd_pivot[_pivot_col_order].reset_index().sort_values("Date").reset_index(drop=True)


def export_excel_portfolio(output_path: str) -> str:
    """Export all cross-ticker / dashboard datasets to one .xlsx workbook (one sheet each)."""
    excel_path = os.path.join(output_path, "Merton_Summary.xlsx")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_summary_csv.to_excel(writer,   sheet_name="Summary",           index=False)
        df_dd_csv.to_excel(writer,        sheet_name="DD_TimeSeries",     index=False)
        df_stress_csv.to_excel(writer,    sheet_name="Stress_Test",       index=False)
        df_lgd.to_excel(writer,           sheet_name="LGD_Sensitivity",   index=False)
        df_migration_csv.to_excel(writer, sheet_name="Rating_Migration",  index=False)
        df_dd_alle.to_excel(writer,       sheet_name="DD_TimeSeries_All", index=False)
        df_dd_pivot.to_excel(writer,      sheet_name="DD_Pivot",          index=False)
    return excel_path


_portfolio_xlsx = export_excel_portfolio(REPORTS_BASE)
print(f"\n=== Excel Export (Portfolio / Dashboard feed) ===")
print(f"File: {_portfolio_xlsx}")
print(f"  Summary           — {len(df_summary_csv)} row(s)")
print(f"  DD_TimeSeries     — {len(df_dd_csv)} rows (MCHP only)")
print(f"  Stress_Test       — {len(df_stress_csv)} rows")
print(f"  LGD_Sensitivity   — {len(df_lgd)} rows")
print(f"  Rating_Migration  — {len(df_migration_csv)} rows")
print(f"  DD_TimeSeries_All — {len(df_dd_alle)} rows (all 5 tickers)")
print(f"  DD_Pivot          — {len(df_dd_pivot)} rows (pivot)")

# endregion


# ----------------------------------------------------------------------------
# region INTERPRETATION
# ----------------------------------------------------------------------------
print("\n=== Interpretation ===")

_dd  = merton['dd']
_pd  = merton['pd']
_sv  = merton['sigma_v']
_lev = total_debt / market_cap if market_cap > 0 else 0

if _dd >= 6:
    print(f">>> DD = {_dd:.4f}: Very high distance to default — the company is structurally very safe.")
elif _dd >= 4:
    print(f">>> DD = {_dd:.4f}: Solid buffer zone — low default risk under normal market conditions.")
elif _dd >= 2:
    print(f">>> DD = {_dd:.4f}: Elevated risk — the company is operating in a sensitive range.")
else:
    print(f">>> DD = {_dd:.4f}: Critically low DD — elevated default risk, close monitoring required.")

if _pd < 0.0001:
    print(f">>> PD ≈ 0.0000%: Default probability negligible.")
elif _pd < 0.001:
    print(f">>> PD = {_pd:.4%}: Very low but measurable default probability.")
elif _pd < 0.01:
    print(f">>> PD = {_pd:.4%}: Low default probability — within the investment-grade range.")
else:
    print(f">>> PD = {_pd:.4%}: Noticeable default probability — increased vigilance recommended.")

if sigma_e > 0 and (sigma_e - _sv) / sigma_e > 0.05:
    print(f">>> σ_V ({_sv:.1%}) < σ_E ({sigma_e:.1%}): Leverage effect visible — debt dampens asset volatility relative to equity.")
else:
    print(f">>> σ_V ({_sv:.1%}) ≈ σ_E ({sigma_e:.1%}): Little leverage effect — the company operates nearly debt-free.")

if _lev > 0.5:
    print(f">>> Leverage ratio {_lev:.1%}: High leverage — debt exceeds 50% of market capitalization.")
elif _lev > 0.2:
    print(f">>> Leverage ratio {_lev:.1%}: Moderate leverage — typical capital structure for an industrial company.")
else:
    print(f">>> Leverage ratio {_lev:.1%}: Low leverage — conservative capital structure.")

stage_label = {1: "Stage 1 (12M ECL)", 2: "Stage 2 (Lifetime ECL)", 3: "Stage 3 (credit-impaired)"}
print(f">>> IFRS 9 classification: {stage_label[ifrs9_stage]} — "
      f"ECL = {ecl_used/1e6:.3f} Mn USD "
      f"({'12M-PD' if ifrs9_stage == 1 else 'Lifetime-PD' if ifrs9_stage == 2 else 'LGD × EAD, PD=1'} basis).")

dominant_rating = df_dd_rated["Rating"].value_counts().index[0]
print(f">>> Dominant historical rating (5Y quarters): {dominant_rating} "
      f"({df_dd_rated['Rating'].value_counts().iloc[0]} of {len(df_dd_rated)} observations).")
# endregion


# ----------------------------------------------------------------------------
# region LEGENDE
# ----------------------------------------------------------------------------
print("\n=== Legende ===")
print("E              = Market capitalization (Equity Market Value)")
print("D              = Total debt (Total Debt)")
print("V              = Firm asset value — computed iteratively")
print("r              = Risk-free rate (Risk-free Rate)")
print("T              = Time to maturity in years (Time to Maturity)")
print("sigma_E        = Equity volatility (annualized from stock prices)")
print("sigma_V        = Asset volatility (volatility of the firm's asset value)")
print("d1, d2         = Black-Scholes auxiliary quantities")
print("DD             = Distance to Default — number of standard deviations to default")
print("PD             = Probability of Default — default probability in %")
print("EL             = Expected Loss = PD * D * LGD")
print("LGD            = Loss Given Default — loss rate on default (45% ISDA standard)")
print("N()            = Standard normal CDF")
print("EAD            = Exposure at Default = total debt (IFRS 9)")
print("LGD_IFRS9      = Loss Given Default for the ECL calculation (45%)")
print("PD_12M         = 12-month default probability (Merton T=1)")
print("PD_lifetime    = Lifetime default probability (Merton T=5)")
print("ECL_12M        = Expected Credit Loss Stage 1 = PD_12M * LGD * EAD")
print("ECL_Lifetime   = Expected Credit Loss Stage 2 = PD_lifetime * LGD * EAD")
print("ECL_Stage3     = Expected Credit Loss Stage 3 = LGD * EAD (PD=1)")
print("ifrs9_stage    = IFRS 9 stage assignment (1/2/3) based on DD")
print("ecl_used       = ECL to apply, depending on the stage assignment")
print("RATINGS_ORDERED= Rating classes for migration: AAA/AA, A, BBB, BB, B, CCC")
print("migration_counts = Counter matrix: how often a rating moved from X to Y (quarters)")
print("migration_probs  = Transition probabilities P(From → To)")
print("df_lgd         = LGD sensitivity table: LGD × Scenario × EL/Spread/ECL")
print("export_excel_portfolio() = Writes all cross-ticker / dashboard datasets to one .xlsx")
print("Merton_Summary.xlsx  = Workbook in Excel base dir (read back by the Merton chart scripts)")
print("  Sheets: Summary, DD_TimeSeries, Stress_Test, LGD_Sensitivity, Rating_Migration,")
print("          DD_TimeSeries_All, DD_Pivot")
# endregion
