"""
DCF_Valuation — Discounted Cash Flow Valuation Model
======================================================
Run with: python DCF/DCF_Valuation.py [--ticker MCHP]

  Block 0: Imports & Setup
  Block 1: Load FMP Data + WACC Calculation (CAPM)
  Block 2: DCF Base Case (deterministic)
  Block 3: DCF Sensitivity Analysis (WACC × Growth Heatmap)
  Block 4: Monte Carlo DCF (10,000 simulations, histogram)
  Block 5: Scenario Analysis Bear / Base / Bull
  Block 6: Peer Group Comparison (all 5 tickers)
  Block 7: Multiples Cross-Check (EV/EBITDA, P/E, EV/Sales)
  Block 8: Excel Export (DCF_Results_{TICKER}.xlsx)
"""

# region Block 0 - Imports & Setup
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import os
import argparse
import importlib
import warnings
from collections.abc import Sequence
from datetime import date
from typing import Any, Optional, TypedDict

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

debug = False

# ─────────────────────────────────────────────────────────────
_parser = argparse.ArgumentParser(description="DCF valuation model for one ticker.")
_parser.add_argument("--ticker", default="MCHP", choices=["MCHP", "INTC", "ON", "QCOM", "MPWR"],
                      help="Ticker to analyze (default: MCHP)")
ACTIVE_CONFIG = _parser.parse_args().ticker
# ─────────────────────────────────────────────────────────────

# Project root = semiconductor-risk-analysis/ (1 level up from DCF/)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load Config dynamically
config = importlib.import_module(f"Config.{ACTIVE_CONFIG}")

TICKER            = config.TICKER
COMPANY       = config.COMPANY
RISK_FREE_RATE = config.RISK_FREE_RATE
WACC_CONFIG       = config.WACC_MEAN
TERMINAL_GROWTH   = config.TERMINAL_GROWTH
FORECAST_YEARS     = config.FORECAST_YEARS
EXCEL_DIR      = os.path.join(config.OUTPUT_DIR, "Excel", ACTIVE_CONFIG)
VIZ_DIR        = os.path.join(config.OUTPUT_DIR, "Visualisierung", ACTIVE_CONFIG)

os.makedirs(EXCEL_DIR, exist_ok=True)
os.makedirs(VIZ_DIR, exist_ok=True)

# plot_style — central design template
from plot_style import LAYOUT, BLUE_1, BLUE_2, BLUE_3, ORANGE_1, ORANGE_2, ORANGE_3, GRAY_1
BG     = "#FFFFFF"; TEXT = "#1A1A1A"; BORDER = "#E5E5E5"; TEXT_MUTED = "#9CA3AF"

# Pure calculation functions — extracted to dcf_core.py (no I/O, safe to unit test)
try:
    from .dcf_core import (DcfParams, cagr, calculate_beta, classify_valuation,
                           compute_multiples, cost_of_debt, dcf_full, dcf_schedule,
                           effective_tax_rate, g2_sensitivity, rate_multiple,
                           sensitivity_matrix, simulate_dcf, wacc_capm, with_params)
except ImportError:
    from dcf_core import (DcfParams, cagr, calculate_beta, classify_valuation,  # type: ignore[import-not-found,no-redef]
                          compute_multiples, cost_of_debt, dcf_full, dcf_schedule,
                          effective_tax_rate, g2_sensitivity, rate_multiple,
                          sensitivity_matrix, simulate_dcf, wacc_capm, with_params)

# FMP cache access and field mapping — the only place that knows FMP field names
try:
    from .fmp_extract import extract_wacc_inputs, load_json, load_prices
except ImportError:
    from fmp_extract import extract_wacc_inputs, load_json, load_prices  # type: ignore[import-not-found,no-redef]

# endregion


# region Block 1 - Load FMP Data
# ─────────────────────────────────────────────────────────────
# Loads all DCF-relevant data from the local FMP cache:
#   key-metrics       → WACC, EarningsYield, FCF-Yield, MarketCap
#   cash-flow         → FCF, OperatingCashFlow (5 years)
#   income-statement  → Revenue, EBITDA, NetIncome (5 years)
#   balance-sheet     → Debt, Cash, Equity (current)
# ─────────────────────────────────────────────────────────────

class DcfData(TypedDict):
    """Everything Block 1 pulls out of the FMP cache for one ticker."""
    wacc_fmp: Optional[float]   # None on the FMP free plan
    earnings_yield: float
    fcf_yield: float
    market_cap: float
    fcf: list[float]            # 5 years, newest first
    cf_dates: list[str]
    revenue: list[float]
    ebitda: list[float]
    net_income: list[float]
    total_debt: float
    cash: float
    equity_bk: float


def load_dcf_data() -> DcfData:
    """Load all DCF-relevant fields from FMP cache files."""

    # key-metrics — annual, newest entry first
    km_list = load_json(f"{TICKER}_key-metrics.json")
    km      = km_list[0]

    # cash-flow-statement — 5 years, newest first
    cf_list  = load_json(f"{TICKER}_cash-flow-statement.json")[:5]
    fcf      = [float(e.get("freeCashFlow",    0) or 0) for e in cf_list]
    cf_dates = [e.get("date", "") for e in cf_list]

    # income-statement — 5 years, newest first
    inc_list   = load_json(f"{TICKER}_income-statement.json")[:5]
    revenue    = [float(e.get("revenue",   0) or 0) for e in inc_list]
    ebitda     = [float(e.get("ebitda",    0) or 0) for e in inc_list]
    net_income = [float(e.get("netIncome", 0) or 0) for e in inc_list]

    # balance-sheet — current (index 0 = most recent statement)
    bs         = load_json(f"{TICKER}_balance-sheet-statement.json")[0]
    total_debt = float(bs.get("totalDebt",                  0) or 0)
    cash       = float(bs.get("cashAndCashEquivalents",     0) or 0)
    equity_bk  = float(bs.get("totalStockholdersEquity",   0) or 0)

    # key-metrics ratios
    wacc_fmp       = km.get("wacc")               # None on the FMP free plan
    earnings_yield = float(km.get("earningsYield",     0) or 0)
    fcf_yield      = float(km.get("freeCashFlowYield", 0) or 0)
    market_cap     = float(km.get("marketCap",         0) or 0)

    return {
        "wacc_fmp":      wacc_fmp,
        "earnings_yield": earnings_yield,
        "fcf_yield":     fcf_yield,
        "market_cap":    market_cap,
        "fcf":           fcf,
        "cf_dates":      cf_dates,
        "revenue":       revenue,
        "ebitda":        ebitda,
        "net_income":    net_income,
        "total_debt":    total_debt,
        "cash":          cash,
        "equity_bk":     equity_bk,
    }


data       = load_dcf_data()

# Extract core variables
market_cap = data["market_cap"]
total_debt = data["total_debt"]
cash       = data["cash"]
equity_bk  = data["equity_bk"]
fcf        = data["fcf"]
revenue    = data["revenue"]
ebitda     = data["ebitda"]
net_income = data["net_income"]
cf_dates   = data["cf_dates"]

# WACC: FMP value if available, otherwise Config fallback
wacc_fmp    = data["wacc_fmp"]
wacc        = float(wacc_fmp) if wacc_fmp is not None else WACC_CONFIG
wacc_source = "FMP" if wacc_fmp is not None else "Config"

# FCF 5-year CAGR (4 growth periods: index 0 = newest, index 4 = oldest)
fcf_cagr = cagr(fcf[0], fcf[4], 4)

# Enterprise Value and Net Debt
ev       = market_cap + total_debt - cash
net_debt = total_debt - cash

# ── Terminal Output ──────────────────────────────────────────
print(f"\n{'='*60}")
print(f"=== DCF Data — {TICKER} ({COMPANY}) ===")
print(f"{'='*60}")
print(f"WACC ({wacc_source}):            {wacc:.2%}")
print(f"FCF last year:           {fcf[0] / 1e9:.2f} Bn USD")
print(f"FCF growth (5Y CAGR):    {fcf_cagr:.2%}")
print(f"Enterprise Value:        {ev / 1e9:.2f} Bn USD")
print(f"Net Debt:                {net_debt / 1e9:.2f} Bn USD")
print(f"Market Capitalization:  {market_cap / 1e9:.2f} Bn USD")

print(f"\n--- Additional Info ---")
print(f"Earnings Yield:          {data['earnings_yield']:.2%}")
print(f"FCF Yield:               {data['fcf_yield']:.2%}")
print(f"Equity (book):           {equity_bk / 1e9:.2f} Bn USD")
print(f"Total Debt:              {total_debt / 1e9:.2f} Bn USD")
print(f"Cash & Equivalents:      {cash / 1e9:.2f} Bn USD")

print(f"\n--- Revenue & Profitability (5 years, newest first) ---")
for i, cf_date in enumerate(cf_dates):
    margin = ebitda[i] / revenue[i] if revenue[i] != 0 else 0.0
    net_m  = net_income[i] / revenue[i] if revenue[i] != 0 else 0.0
    print(f"  {cf_date}: Rev = {revenue[i]/1e9:.2f} Bn | EBITDA = {ebitda[i]/1e9:.2f} Bn ({margin:.1%}) | Net = {net_income[i]/1e9:.2f} Bn ({net_m:.1%})")

# ── WACC Calculation via CAPM ─────────────────────────────────

def calculate_wacc(
    prices: pd.Series,
    market_cap_: float,
    total_debt: float,
    income_data: Sequence[dict[str, Any]],
    risk_free_rate: float,
) -> dict[str, float]:
    """CAPM-based WACC: Beta (252-day OLS), Ke, Kd after tax, E/V weights."""
    sp500 = load_prices("SP500_historical-price-eod_full.json")
    beta  = calculate_beta(prices, sp500)

    interest_expense, tax_and_ebt = extract_wacc_inputs(income_data, total_debt)

    return wacc_capm(
        beta       = beta,
        risk_free  = risk_free_rate,
        kd         = cost_of_debt(interest_expense, total_debt),
        tax_rate   = effective_tax_rate(tax_and_ebt),
        market_cap = market_cap_,
        total_debt = total_debt,
    )


prices_ticker = load_prices(f"{TICKER}_historical-price-eod_full.json")
inc_raw       = load_json(f"{TICKER}_income-statement.json")[:5]

wacc_res = calculate_wacc(
    prices         = prices_ticker,
    market_cap_    = market_cap,
    total_debt     = total_debt,
    income_data    = inc_raw,
    risk_free_rate = RISK_FREE_RATE,
)

print(f"\n=== WACC Calculation (CAPM) ===")
print(f"Beta (252 trading days): {wacc_res['beta']:.4f}")
print(f"Cost of Equity Ke:       {wacc_res['ke']:.2%}")
print(f"Cost of Debt Kd:         {wacc_res['kd']:.2%}")
print(f"Tax Rate (eff.):         {wacc_res['tax_rate']:.1%}")
print(f"Kd after tax:            {wacc_res['kd_after_tax']:.2%}")
print(f"Capital Structure E/V:   {wacc_res['ev_ratio']:.1%}")
print(f"Capital Structure D/V:   {wacc_res['dv_ratio']:.1%}")
print(f"WACC (CAPM):             {wacc_res['wacc_calc']:.2%}")
print(f"WACC (Config):           {WACC_CONFIG:.2%}")
print(f"Difference:              {(wacc_res['wacc_calc'] - WACC_CONFIG)*10000:+.0f} basis points")

# Calculated WACC overrides the Config fallback for all further blocks
wacc        = wacc_res["wacc_calc"]
wacc_source = "CAPM"

# endregion


# region Block 2 - DCF Base Case (deterministic)
# ─────────────────────────────────────────────────────────────
# Two-phase DCF model with normalized FCF:
#   Phase 1 (years 1-5): recovery from cycle trough at g1 = GROWTH_MEAN
#   Phase 2 (terminal):  perpetual growth rate g2 = TERMINAL_GROWTH
# Discounted with the CAPM WACC from Block 1.
# ─────────────────────────────────────────────────────────────

# STEP 1 — Normalized FCF (median, robust against outliers)
fcf_norm = float(np.median(fcf))

# A DCF discounts future cash flows the company is assumed to generate. With a
# negative normalized FCF the model still produces a number, but that number is
# not an intrinsic value — it is the present value of continued cash burn.
# Everything downstream (base case, sensitivity, Monte Carlo, peer rank) inherits
# this, so the limitation is stated up front rather than buried in the results.
fcf_norm_negative = fcf_norm <= 0

# STEP 2 — Growth assumptions
g1 = getattr(config, "GROWTH_MEAN", 0.05)   # Phase 1: recovery (Config = 5%)
g2 = TERMINAL_GROWTH                            # Phase 2: terminal growth (Config = 2.5%)

# STEP 3 — Share count implied by market cap and last close
current_price      = float(prices_ticker.iloc[-1])
shares_outstanding = market_cap / current_price

# STEP 4 — DCF forecast (explicit years 1 through FORECAST_YEARS) + terminal value
base_params: DcfParams = {
    "fcf_start": fcf_norm,
    "g1":        g1,
    "g2":        g2,
    "wacc":      wacc,
    "years":     FORECAST_YEARS,
    "net_debt":  net_debt,
    "shares":    shares_outstanding,
}

fcf_prognose, base_result = dcf_schedule(base_params)

tv         = fcf_prognose[-1]["FCF"] * (1 + g2) / (wacc - g2)
pv_tv      = base_result["pv_terminal_value"]
pv_fcf_sum = base_result["ev"] - pv_tv
ev_dcf     = base_result["ev"]

# STEP 5 — Equity value and comparison with market value
equity_value     = base_result["equity"]
equity_per_share = base_result["value_per_share"]
upside           = (equity_per_share / current_price - 1) * 100
valuation        = classify_valuation(upside)

# ── Terminal Output ──────────────────────────────────────────
print(f"\n{'='*60}")
print(f"=== DCF Base Case — {TICKER} ({COMPANY}) ===")
print(f"{'='*60}")
print(f"FCF last year:           {fcf[0]/1e9:.3f} Bn USD")
print(f"FCF normalized (Med.):   {fcf_norm/1e9:.3f} Bn USD")
if fcf_norm_negative:
    print(f"  [!] Normalized FCF is negative — a DCF cannot produce a meaningful")
    print(f"      intrinsic value here. All DCF figures below are the present value")
    print(f"      of continued cash burn, not a valuation. Use the Merton model and")
    print(f"      the multiples cross-check for {TICKER} instead.")
print(f"FCF Peak (5Y):           {max(fcf)/1e9:.3f} Bn USD")
print(f"WACC:                    {wacc:.2%}  (CAPM)")
print(f"Growth Phase 1 (5Y):     {g1:.1%}  (assumption: normalization after inventory drawdown cycle)")
print(f"Terminal Growth:         {g2:.1%}")

print(f"\n--- Forecast (Years 1–{FORECAST_YEARS}) ---")
print(f"{'Year':>5} {'FCF (Bn)':>12} {'PV (Bn)':>12}")
print("-" * 32)
for year_row in fcf_prognose:
    print(f"{int(year_row['Year']):>5} {year_row['FCF']/1e9:>12.3f} {year_row['PV_FCF']/1e9:>12.3f}")

print(f"\nTerminal Value:          {tv/1e9:.2f} Bn USD")
print(f"PV Terminal Value:       {pv_tv/1e9:.2f} Bn USD")
print(f"PV FCF Sum (5Y):         {pv_fcf_sum/1e9:.2f} Bn USD")
print(f"\nEnterprise Value (DCF):  {ev_dcf/1e9:.2f} Bn USD")
print(f"Enterprise Value (Market):{ev/1e9:.2f} Bn USD")
print(f"Net Debt:                {net_debt/1e9:.2f} Bn USD")
print(f"Equity Value (DCF):      {equity_value/1e9:.2f} Bn USD")
print(f"Market Capitalization:  {market_cap/1e9:.2f} Bn USD")
print(f"\nIntrinsic Value/Share:   {equity_per_share:.2f} USD")
print(f"Current Price:           {current_price:.2f} USD")
print(f"Upside/Downside:         {upside:+.1f}%")
print(f"Valuation:               {valuation}")

# endregion


# region Block 3 - DCF Sensitivity Analysis
import plotly.graph_objects as go

WACC_RANGE = [0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14]
G1_RANGE   = [0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]


matrix    = sensitivity_matrix(base_params, WACC_RANGE, G1_RANGE)
x_labels  = [f"{g:.0%}" for g in G1_RANGE]
y_labels  = [f"{w:.0%}" for w in WACC_RANGE]

df_sens              = pd.DataFrame(matrix, index=y_labels, columns=x_labels)
df_sens.index.name   = "WACC"
df_sens.columns.name = "Growth"

# --- Terminal output ---
print(f"\n{'='*62}")
print(f"=== Sensitivity Analysis: Intrinsic Value/Share (USD) ===")
print(f"{'='*62}")
print(f"Rows: WACC | Columns: Phase 1 Growth | Price: {current_price:.2f} USD")
print()

header_line = f"{'WACC':>6} " + " ".join(f"{c:>9}" for c in x_labels)
print(header_line)
print("-" * len(header_line))
for label, row in zip(y_labels, matrix):
    cells = []
    for val in row:
        if np.isnan(val):
            cells.append("      n/a")
        elif val > current_price * 1.10:
            cells.append(f"↑{val:8.1f}")
        elif val < current_price * 0.90:
            cells.append(f"↓{val:8.1f}")
        else:
            cells.append(f"≈{val:8.1f}")
    print(f"{label:>6} " + " ".join(cells))

# --- Fair-value search (±5 %) ---
print(f"\nFair value search (±5% around {current_price:.2f} USD):")
fair_combos = [
    (w, g, matrix[i][j])
    for i, w in enumerate(WACC_RANGE)
    for j, g in enumerate(G1_RANGE)
    if not np.isnan(matrix[i][j]) and abs(matrix[i][j] / current_price - 1) < 0.05
]
if fair_combos:
    for w_f, g_f, v_f in fair_combos:
        print(f"  WACC={w_f:.0%}, Growth={g_f:.0%} → {v_f:.2f} USD/share")
else:
    diffs = sorted(
        [(abs(matrix[i][j] / current_price - 1), w, g, matrix[i][j])
         for i, w in enumerate(WACC_RANGE)
         for j, g in enumerate(G1_RANGE)
         if not np.isnan(matrix[i][j])]
    )
    dev_c, w_c, g_c, v_c = diffs[0]
    print(f"  Closest: WACC={w_c:.0%}, Growth={g_c:.0%} → {v_c:.2f} USD ({dev_c:.1%} dev.)")

# --- Heatmap ---
text_matrix = []
for row in matrix:
    text_row = []
    for val in row:
        if np.isnan(val):
            text_row.append("n/a")
        elif val > current_price * 1.10:
            text_row.append(f"↑ {val:.0f}")
        elif val < current_price * 0.90:
            text_row.append(f"↓ {val:.0f}")
        else:
            text_row.append(f"≈ {val:.0f}")
    text_matrix.append(text_row)

wacc_idx = int(np.argmin([abs(w - wacc) for w in WACC_RANGE]))
g1_idx   = int(np.argmin([abs(g - g1)   for g  in G1_RANGE]))

fig3 = go.Figure()

fig3.add_trace(go.Heatmap(
    z=matrix,
    x=x_labels,
    y=y_labels,
    text=text_matrix,
    texttemplate="%{text}",
    textfont=dict(size=10, color="#1A1A1A"),
    colorscale=[[0, ORANGE_2], [0.5, "#F1F5F9"], [1.0, BLUE_2]],
    zmid=current_price,
    colorbar=dict(title=dict(text="USD/Share", side="right"), thickness=15),
    hovertemplate="WACC: %{y}<br>Growth: %{x}<br>Value: %{z:.2f} USD<extra></extra>",
))

fig3.add_trace(go.Contour(
    z=matrix,
    x=x_labels,
    y=y_labels,
    contours=dict(
        coloring="none",
        start=current_price - 5,
        end=current_price + 5,
        size=10.01,
    ),
    line=dict(color="black", width=2.5, dash="dash"),
    showscale=False,
    name=f"≈ Price {current_price:.0f} USD",
))

fig3.add_trace(go.Scatter(
    x=[x_labels[g1_idx]],
    y=[y_labels[wacc_idx]],
    mode="markers",
    marker=dict(
        color="rgba(0,0,0,0)",
        size=26,
        symbol="circle",
        line=dict(color="black", width=3),
    ),
    name=f"Current (WACC≈{wacc:.1%}, g={g1:.0%})",
))

fig3.update_layout(**LAYOUT)
fig3.update_layout(
    title=dict(
        text=(f"{COMPANY} — DCF Sensitivity WACC × Growth<br>"
              f"<sup>Intrinsic Value/Share (USD) | Current Price: {current_price:.2f} USD | "
              f"↑ UNDERVALUED · ↓ OVERVALUED · ≈ FAIR (±10%)</sup>"),
        font=dict(size=15, color="#0B1220"), x=0.0,
    ),
    xaxis=dict(title="Growth Phase 1 (g1)", side="bottom",
               showgrid=False, showline=True, linecolor=BORDER),
    yaxis=dict(title="WACC", autorange="reversed",
               showgrid=False, showline=True, linecolor=BORDER),
    height=480,
    margin=dict(l=70, r=140, t=100, b=60),
    legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0, x=1.10, y=0.5),
)

chart3_path = os.path.join(VIZ_DIR, f"{TICKER}_DCF_Sensitivitaet.png")
try:
    fig3.write_image(chart3_path, width=920, height=480, scale=1.5)
    print(f"\nHeatmap saved: {chart3_path}")
except Exception:
    html3_path = chart3_path.replace(".png", ".html")
    fig3.write_html(html3_path)
    print(f"\nHeatmap (HTML) saved: {html3_path}")

excel_path = os.path.join(EXCEL_DIR, f"{TICKER}_DCF_Sensitivitaet.xlsx")
try:
    df_sens.round(2).to_excel(excel_path, sheet_name="DCF_Sensitivitaet")
    print(f"Excel saved: {excel_path}")
except Exception as exc_xl:
    print(f"Excel export failed: {exc_xl}")

# Summary counts for Interpretation
_n_total = len(WACC_RANGE) * len(G1_RANGE)
_n_under = sum(1 for row in matrix for v in row if not np.isnan(v) and v > current_price * 1.10)
_n_over  = sum(1 for row in matrix for v in row if not np.isnan(v) and v < current_price * 0.90)
_n_fair  = _n_total - _n_under - _n_over

# endregion


# region Block 4 - Monte Carlo DCF
SIMULATIONS   = getattr(config, "SIMULATIONS",   10000)
WACC_STD       = getattr(config, "WACC_STD",       0.015)
GROWTH_STD   = getattr(config, "GROWTH_STD",   0.020)
FCF_STD_FACTOR = 0.15  # ±15% FCF uncertainty

mc_results = simulate_dcf(
    base_params,
    n              = SIMULATIONS,
    wacc_std       = WACC_STD,
    growth_std     = GROWTH_STD,
    fcf_std_factor = FCF_STD_FACTOR,
)

mc_mean   = float(np.mean(mc_results))
mc_median = float(np.median(mc_results))
mc_std    = float(np.std(mc_results))
mc_p10    = float(np.percentile(mc_results, 10))
mc_p25    = float(np.percentile(mc_results, 25))
mc_p75    = float(np.percentile(mc_results, 75))
mc_p90    = float(np.percentile(mc_results, 90))
p_undervalued   = float(np.mean(mc_results > current_price))

print(f"\n{'='*55}")
print(f"=== Monte Carlo DCF — {SIMULATIONS:,} Simulations ===")
print(f"{'='*55}")
print(f"Mean:            {mc_mean:.2f} USD")
print(f"Median:          {mc_median:.2f} USD")
print(f"Std Dev:         {mc_std:.2f} USD")
print(f"P10 / P90:       {mc_p10:.2f} / {mc_p90:.2f} USD")
print(f"P25 / P75:       {mc_p25:.2f} / {mc_p75:.2f} USD")
print(f"P(Undervalued):  {p_undervalued:.1%}")
print(f"Current Price:   {current_price:.2f} USD")

# --- Histogram ---
x_lo  = float(np.percentile(mc_results, 0.5))
x_hi  = float(np.percentile(mc_results, 99.5))
bsize = (x_hi - x_lo) / 60

fig4 = go.Figure()

fig4.add_trace(go.Histogram(
    x=mc_results[mc_results < current_price],
    autobinx=False,
    xbins=dict(start=x_lo, end=current_price + bsize, size=bsize),
    marker=dict(color=ORANGE_2,  line=dict(color=ORANGE_2,  width=0.4)),
    opacity=0.78,
    name=f"Overvalued (<{current_price:.0f} USD)",
))

fig4.add_trace(go.Histogram(
    x=mc_results[mc_results >= current_price],
    autobinx=False,
    xbins=dict(start=current_price, end=x_hi + bsize, size=bsize),
    marker=dict(color=BLUE_2, line=dict(color=BLUE_2, width=0.4)),
    opacity=0.78,
    name=f"Undervalued (≥{current_price:.0f} USD)",
))

for x_val, label, col, dash, ypos in [
    (current_price, f"Price {current_price:.0f}",  ORANGE_2,   "solid", 0.97),
    (mc_median,    f"Median {mc_median:.0f}",    BLUE_1,  "solid", 0.88),
    (mc_p10,       f"P10 {mc_p10:.0f}",          GRAY_1,  "dot",   0.97),
    (mc_p90,       f"P90 {mc_p90:.0f}",          GRAY_1,  "dot",   0.88),
]:
    fig4.add_vline(x=x_val, line_dash=dash, line_color=col, line_width=2)
    fig4.add_annotation(
        x=x_val, y=ypos, yref="paper",
        text=label, showarrow=False,
        font=dict(color=col, size=9, family="Inter"),
        xanchor="center", yanchor="bottom",
        bgcolor="rgba(255,255,255,0.75)", borderpad=2,
    )

fig4.update_layout(**LAYOUT)
fig4.update_layout(
    title=dict(
        text=(f"{COMPANY} — Monte Carlo DCF ({SIMULATIONS:,} Simulations)<br>"
              f"<sup>WACC σ={WACC_STD:.1%} | Growth σ={GROWTH_STD:.1%} | "
              f"FCF σ={FCF_STD_FACTOR:.0%} | P(Undervalued)={p_undervalued:.1%}</sup>"),
        font=dict(size=15, color="#0B1220"), x=0.0,
    ),
    barmode="overlay",
    xaxis=dict(title="Intrinsic Value/Share (USD)", range=[x_lo, x_hi],
               showgrid=False, showline=True, linecolor=BORDER),
    yaxis=dict(title="Frequency", showgrid=False, showline=True, linecolor=BORDER),
    height=460,
    margin=dict(l=65, r=40, t=100, b=60),
    legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0,
                x=0.01, y=0.99, xanchor="left", yanchor="top"),
)

chart4_path = os.path.join(VIZ_DIR, f"{TICKER}_DCF_MonteCarlo.png")
try:
    fig4.write_image(chart4_path, width=900, height=460, scale=1.5)
    print(f"\nHistogram saved: {chart4_path}")
except Exception:
    html4_path = chart4_path.replace(".png", ".html")
    fig4.write_html(html4_path)
    print(f"\nHistogram (HTML) saved: {html4_path}")

# endregion


# region Block 5 - Scenario Analysis Bear / Base / Bull


SCENARIOS_DCF = {
    "Bear": {"g1_delta": -0.02, "wacc_delta": +0.015, "fcf_factor": 0.85},
    "Base": {"g1_delta":  0.00, "wacc_delta":  0.000, "fcf_factor": 1.00},
    "Bull": {"g1_delta": +0.02, "wacc_delta": -0.010, "fcf_factor": 1.15},
}
SCENARIO_COLORS = {"Bear": ORANGE_2, "Base": BLUE_1, "Bull": BLUE_2}

scen_results = {}
for scen, params in SCENARIOS_DCF.items():
    g1_s  = g1   + params["g1_delta"]
    wc_s  = wacc + params["wacc_delta"]
    fs_s  = fcf_norm * params["fcf_factor"]
    res_s = dcf_full(with_params(base_params, g1=g1_s, wacc=wc_s, fcf_start=fs_s))
    wa_s  = res_s["value_per_share"]
    up_s  = (wa_s / current_price - 1) * 100 if not np.isnan(wa_s) else float("nan")
    scen_results[scen] = {
        "g1": g1_s, "wacc": wc_s, "fcf_mrd": fs_s / 1e9,
        "ev_mrd":     res_s["ev"] / 1e9 if not np.isnan(res_s["ev"]) else float("nan"),
        "value_per_share": wa_s, "upside": up_s,
    }

print(f"\n{'='*75}")
print(f"=== DCF Scenario Analysis — {TICKER} ({COMPANY}) ===")
print(f"{'='*75}")
print(f"{'Scenario':<8} {'WACC':>7} {'g1':>6} {'FCF Norm (Bn)':>15} {'EV (Bn)':>10} {'Value/Share (USD)':>17} {'Upside':>9}")
print("-" * 75)
for scen, sd in scen_results.items():
    print(f"{scen:<8} {sd['wacc']:>7.1%} {sd['g1']:>6.1%} {sd['fcf_mrd']:>15.2f} "
          f"{sd['ev_mrd']:>10.1f} {sd['value_per_share']:>17.2f} {sd['upside']:>8.1f}%")

fig5 = go.Figure()
for scen, sd in scen_results.items():
    fig5.add_trace(go.Bar(
        x=[scen], y=[sd["value_per_share"]],
        name=scen,
        marker_color=SCENARIO_COLORS[scen],
        opacity=0.85,
        text=[f"${sd['value_per_share']:.1f} ({sd['upside']:+.0f}%)"],
        textposition="outside",
        textfont=dict(size=11),
    ))
fig5.add_hline(y=current_price, line_dash="dash", line_color=GRAY_1, line_width=1.5,
               annotation_text=f"Price: ${current_price:.2f}",
               annotation_position="top right",
               annotation_font=dict(size=11, color=GRAY_1))
fig5.update_layout(
    **LAYOUT,
    title=dict(text=f"{COMPANY} — Scenario Analysis: Intrinsic Value/Share",
               font=dict(size=14, color="#0B1220"), x=0.0),
    showlegend=False,
    xaxis=dict(title="Scenario", showgrid=False, showline=True, linecolor=BORDER),
    yaxis=dict(title="Value/Share (USD)", showgrid=True, gridcolor=BORDER),
    height=420,
    margin=dict(l=60, r=60, t=90, b=60),
)
chart5_path = os.path.join(VIZ_DIR, f"{TICKER}_DCF_Szenarien.png")
try:
    fig5.write_image(chart5_path, width=800, height=420, scale=1.5)
    print(f"Scenario chart saved: {chart5_path}")
except Exception:
    chart5_path = chart5_path.replace(".png", ".html")
    fig5.write_html(chart5_path)
    print(f"Scenario chart (HTML) saved: {chart5_path}")
# endregion


# region Block 6 - Peer Group Comparison

_ALL_TICKERS = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]
_sp500_peer  = load_prices("SP500_historical-price-eod_full.json")


def _peer_wacc(
    mktcap_p: float,
    debt_p: float,
    prices_p: pd.Series,
    inc_data_p: Sequence[dict[str, Any]],
    rf_p: float,
) -> tuple[float, float]:
    """CAPM WACC for a peer — same core routine as the active ticker, S&P 500 cached."""
    beta_p = calculate_beta(prices_p, _sp500_peer)
    ie_p, tax_and_ebt_p = extract_wacc_inputs(inc_data_p, debt_p)
    res_p = wacc_capm(
        beta       = beta_p,
        risk_free  = rf_p,
        kd         = cost_of_debt(ie_p, debt_p),
        tax_rate   = effective_tax_rate(tax_and_ebt_p),
        market_cap = mktcap_p,
        total_debt = debt_p,
    )
    return res_p["wacc_calc"], res_p["beta"]


peer_rows = []
_peer_base_params = {}
for _tkr in _ALL_TICKERS:
    try:
        _cfg_p     = importlib.import_module(f"Config.{_tkr}")
        _pr_p      = load_prices(f"{_tkr}_historical-price-eod_full.json")
        _cf_p      = load_json(f"{_tkr}_cash-flow-statement.json")[:5]
        _inc_p     = load_json(f"{_tkr}_income-statement.json")[:5]
        _bs_p      = load_json(f"{_tkr}_balance-sheet-statement.json")[0]
        _km_p      = load_json(f"{_tkr}_key-metrics.json")[0]

        _mktcap_p  = float(_km_p.get("marketCap", 0) or 0)
        _debt_p    = float(_bs_p.get("totalDebt", 0) or 0)
        _cash_p    = float(_bs_p.get("cashAndCashEquivalents", 0) or 0)
        _nd_p      = _debt_p - _cash_p
        _price_p   = float(_pr_p.iloc[-1])
        _shares_p  = _mktcap_p / _price_p if _price_p > 0 else 1.0

        _fcf_p      = [float(e.get("freeCashFlow", 0) or 0) for e in _cf_p]
        _fcf_norm_p = float(np.median(_fcf_p))

        _wacc_p, _beta_p = _peer_wacc(_mktcap_p, _debt_p, _pr_p, _inc_p, _cfg_p.RISK_FREE_RATE)
        _g1_p   = getattr(_cfg_p, "GROWTH_MEAN", 0.05)
        _g2_p   = _cfg_p.TERMINAL_GROWTH
        _prog_p = _cfg_p.FORECAST_YEARS

        _params_p: DcfParams = {
            "fcf_start": _fcf_norm_p, "g1": _g1_p, "g2": _g2_p, "wacc": _wacc_p,
            "years": _prog_p, "net_debt": _nd_p, "shares": _shares_p,
        }
        _res_p  = dcf_full(_params_p)
        _ev_p   = _res_p["ev"]
        _wa_p   = _res_p["value_per_share"]
        _up_p = (_wa_p / _price_p - 1) * 100 if not np.isnan(_wa_p) and _price_p > 0 else float("nan")
        _valuation_flag_p = classify_valuation(_up_p)
        _tv_share_p = (_res_p["pv_terminal_value"] / _ev_p * 100
                       if not np.isnan(_ev_p) and _ev_p > 0 else float("nan"))

        # Save Base Case parameters for Block 6b (g2 sensitivity analysis)
        _peer_base_params[_tkr] = _params_p

        peer_rows.append({
            "Ticker":       _tkr,
            "Name":         _cfg_p.COMPANY,
            "WACC":         round(_wacc_p, 4),
            "Beta":         round(_beta_p, 3),
            "FCF_Norm_Bn":  round(_fcf_norm_p / 1e9, 2),
            "Value_Per_Share": round(_wa_p, 2) if not np.isnan(_wa_p) else float("nan"),
            "Price":        round(_price_p, 2),
            "Upside_Pct":   round(_up_p, 1) if not np.isnan(_up_p) else float("nan"),
            "MarketCap_Bn": round(_mktcap_p / 1e9, 1),
            "Valuation":    _valuation_flag_p,
            "Terminal_Value_Share_Pct": round(_tv_share_p, 1) if not np.isnan(_tv_share_p) else float("nan"),
        })
    except Exception as _e_p:
        print(f"[WARNING] Peer {_tkr} skipped: {_e_p}")

df_peer = pd.DataFrame(peer_rows).sort_values("Upside_Pct", ascending=False).reset_index(drop=True)

print(f"\n{'='*95}")
print(f"=== Peer Group Comparison — Semiconductor Sector ===")
print(f"{'='*95}")
print(f"{'Ticker':<7} {'Name':<25} {'WACC':>7} {'Beta':>6} {'FCF (Bn)':>10} "
      f"{'DCF Value':>10} {'Price':>8} {'Upside':>9} Valuation")
print("-" * 95)
for _, peer_row in df_peer.iterrows():
    print(f"{peer_row['Ticker']:<7} {peer_row['Name']:<25} {peer_row['WACC']:>7.1%} {peer_row['Beta']:>6.2f} "
          f"{peer_row['FCF_Norm_Bn']:>10.2f} {peer_row['Value_Per_Share']:>10.2f} {peer_row['Price']:>8.2f} "
          f"{peer_row['Upside_Pct']:>8.1f}%  {peer_row['Valuation']}")

print(f"\n{'='*60}")
print(f"=== Terminal Value Share of EV_DCF (Base Case, all 5 tickers) ===")
print(f"{'='*60}")
print(f"{'Ticker':<7} {'TV Share':>10}")
print("-" * 19)
for _, peer_row in df_peer.sort_values("Ticker").iterrows():
    _tv_s = peer_row["Terminal_Value_Share_Pct"]
    print(f"{peer_row['Ticker']:<7} {_tv_s:>9.1f}%" if not np.isnan(_tv_s)
          else f"{peer_row['Ticker']:<7} {'n/a':>10}")

fig6 = go.Figure()
fig6.add_trace(go.Bar(
    x=df_peer["Ticker"], y=df_peer["Price"],
    name="Price (USD)",
    marker_color=GRAY_1, opacity=0.6,
))
fig6.add_trace(go.Bar(
    x=df_peer["Ticker"], y=df_peer["Value_Per_Share"],
    name="DCF Value/Share (USD)",
    marker_color=BLUE_1, opacity=0.85,
    text=[f"${v:.1f}" for v in df_peer["Value_Per_Share"]],
    textposition="outside",
))
fig6.update_layout(
    **LAYOUT,
    title=dict(text="Peer Group DCF Comparison — Value/Share vs. Price (USD)",
               font=dict(size=14, color="#0B1220"), x=0.0),
    barmode="group",
    xaxis=dict(title="Ticker", showgrid=False, showline=True, linecolor=BORDER),
    yaxis=dict(title="USD / Share", showgrid=True, gridcolor=BORDER),
    height=420,
    margin=dict(l=60, r=40, t=90, b=60),
)
chart6_path = os.path.join(VIZ_DIR, f"PeerGroup_DCF_Vergleich.png")
try:
    fig6.write_image(chart6_path, width=900, height=420, scale=1.5)
    print(f"Peer chart saved: {chart6_path}")
except Exception:
    chart6_path = chart6_path.replace(".png", ".html")
    fig6.write_html(chart6_path)
    print(f"Peer chart (HTML) saved: {chart6_path}")
# endregion


# region Block 6b - g2 Sensitivity Analysis (Terminal Growth)
# ─────────────────────────────────────────────────────────────
# Varies g2 (Terminal Growth) for each ticker at constant
# Base Case values for WACC, g1, FCF_norm. The g2 range covers the
# same uniform distribution width as Block 5 in MCS/Monte_Carlo_Sim.py.
# ─────────────────────────────────────────────────────────────

G2_SENS_RANGE = [0.015, 0.020, 0.025, 0.030, 0.035]
G2_SENS_BASE  = 0.025

g2_sens_rows = []
for _tkr, _bp in _peer_base_params.items():
    for _row_g2 in g2_sensitivity(_bp, G2_SENS_RANGE, G2_SENS_BASE):
        _wa_v      = _row_g2["value_per_share"]
        _delta_pct = _row_g2["delta_pct"]
        g2_sens_rows.append({
            "Ticker":            _tkr,
            "g2":                _row_g2["g2"],
            "Value_per_Share":   round(_wa_v, 2) if not np.isnan(_wa_v) else float("nan"),
            "Delta_Pct_vs_Base": round(_delta_pct, 1) if not np.isnan(_delta_pct) else float("nan"),
        })

df_g2_sens = pd.DataFrame(g2_sens_rows)

print(f"\n{'='*60}")
print(f"=== Block 6b — g2 Sensitivity Analysis (Terminal Growth) ===")
print(f"{'='*60}")
for _tkr in _ALL_TICKERS:
    if _tkr not in _peer_base_params:
        continue
    print(f"\n{_tkr}:")
    print(f"  {'g2':>6} {'Value/Share':>12} {'Δ% vs Base':>12}")
    print("  " + "-" * 32)
    _sub = df_g2_sens[df_g2_sens["Ticker"] == _tkr]
    for _, _row in _sub.iterrows():
        _vps = _row["Value_per_Share"]
        _dpc = _row["Delta_Pct_vs_Base"]
        if np.isnan(_vps):
            print(f"  {_row['g2']:>6.1%} {'n/a':>12} {'n/a':>12}")
        else:
            print(f"  {_row['g2']:>6.1%} {_vps:>12.2f} {_dpc:>+11.1f}%")
# endregion


# region Block 7 - Multiples Cross-Check

mult_values = compute_multiples(
    ev         = ev,
    ebitda     = ebitda[0],
    revenue    = revenue[0],
    price      = current_price,
    net_income = net_income[0],
    shares     = shares_outstanding,
)
ev_ebitda_mult = mult_values["EV/EBITDA"]
pe_ratio_mult  = mult_values["P/E"]
ev_sales_mult  = mult_values["EV/Sales"]

# Semiconductor sector benchmarks (Damodaran, Jan 2025)
BENCH = {
    "EV/EBITDA": (15.0, 25.0),
    "P/E":       (20.0, 35.0),
    "EV/Sales":  ( 3.0,  8.0),
}

mult_ratings = {name: rate_multiple(mult_values[name], lo, hi)
                for name, (lo, hi) in BENCH.items()}

print(f"\n{'='*60}")
print(f"=== Multiples Cross-Check — {TICKER} ({COMPANY}) ===")
print(f"{'='*60}")
print(f"{'Multiple':<12} {'Value':>10} {'Benchmark (Sector)':>22} {'Rating':>10}")
print("-" * 56)
for mult_name, (lo, hi) in BENCH.items():
    val     = mult_values[mult_name]
    rat     = mult_ratings[mult_name]
    val_str = f"{val:.1f}x" if not np.isnan(val) else "N/A"
    print(f"{mult_name:<12} {val_str:>10} {f'{lo:.0f}x – {hi:.0f}x':>22} {rat:>10}")

n_cheap     = sum(1 for r in mult_ratings.values() if r == "CHEAP")
n_expensive = sum(1 for r in mult_ratings.values() if r == "EXPENSIVE")
n_fair      = 3 - n_cheap - n_expensive
dcf_signal = "positive" if upside > 10 else ("negative" if upside < -10 else "neutral")
print(f"\nDCF Signal:     {dcf_signal.upper()} ({upside:+.1f}% Upside)")
print(f"Multiples:      {n_cheap}× CHEAP, {n_fair}× FAIR, {n_expensive}× EXPENSIVE")
if dcf_signal == "positive" and n_cheap >= 1:
    print(">>> Overall assessment: UNDERVALUED — DCF and multiples both signal upside.")
elif dcf_signal == "negative" and n_expensive >= 2:
    print(">>> Overall assessment: OVERVALUED — DCF and multiples both signal downside.")
elif dcf_signal == "positive" and n_expensive >= 2:
    print(">>> Overall assessment: MIXED — DCF shows upside, multiples expensive; check growth expectations.")
elif dcf_signal == "negative" and n_cheap >= 1:
    print(">>> Overall assessment: MIXED — multiples cheap, DCF shows downside; check FCF quality.")
else:
    print(">>> Overall assessment: FAIR — DCF and multiples are in line with the current valuation.")
# endregion


# region Block 8 - Excel Export
# ─────────────────────────────────────────────────────────────
# Exports all DCF results into a single .xlsx workbook with one
# sheet per result set. Same output folder as Merton_Model.py.
# The "Summary" sheet is read back by MCS/Monte_Carlo_Sim.py.
# ─────────────────────────────────────────────────────────────

_export_date = date.today().isoformat()

# Sheet 1: Summary — all 5 tickers (from df_peer)
df_dcf_summary = df_peer.copy()
if not df_dcf_summary.empty:
    df_dcf_summary.insert(0, "Date", _export_date)

# Sheet 2: Scenarios — 3 scenarios for the active ticker
_scen_rows = []
for scen, sd in scen_results.items():
    _scen_rows.append({
        "Date":                 _export_date,
        "Ticker":               TICKER,
        "Name":                 COMPANY,
        "Scenario":             scen,
        "WACC":                 round(sd["wacc"], 4),
        "Growth_g1":            round(sd["g1"],   4),
        "FCF_Norm_Bn":          round(sd["fcf_mrd"], 3),
        "EV_Bn":                round(sd["ev_mrd"], 2),
        "DCF_Value_Per_Share":  round(sd["value_per_share"], 2),
        "Price":                round(current_price, 2),
        "Upside_Pct":           round(sd["upside"], 1),
    })
df_scen = pd.DataFrame(_scen_rows)

# Sheet 3: Peer_Group — all 5 tickers with DCF value and price
df_peer_export = df_peer.copy()
if not df_peer_export.empty:
    df_peer_export.insert(0, "Date", _export_date)

# Sheet 4: G2_Sensitivity — g2 sensitivity (Value/Share, Delta% vs Base) all 5 tickers
df_g2_export = df_g2_sens.copy()
df_g2_export.insert(0, "Date", _export_date)


def export_excel_dcf(
    df_summary: pd.DataFrame,
    df_scenarios: pd.DataFrame,
    df_peer_grp: pd.DataFrame,
    df_g2: pd.DataFrame,
    output_path: str,
) -> str:
    """Export all DCF results to a single .xlsx workbook (one sheet per result set)."""
    excel_path = os.path.join(output_path, f"DCF_Results_{TICKER}.xlsx")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_summary.to_excel(writer,   sheet_name="Summary",        index=False)
        df_scenarios.to_excel(writer, sheet_name="Scenarios",      index=False)
        df_peer_grp.to_excel(writer,  sheet_name="Peer_Group",     index=False)
        df_g2.to_excel(writer,        sheet_name="G2_Sensitivity", index=False)
    return excel_path


_dcf_xlsx_path = export_excel_dcf(df_dcf_summary, df_scen, df_peer_export, df_g2_export, EXCEL_DIR)
print(f"\nExcel saved: {_dcf_xlsx_path}")
print(f"  Summary        — {len(df_dcf_summary)} row(s)")
print(f"  Scenarios      — {len(df_scen)} row(s)")
print(f"  Peer_Group     — {len(df_peer_export)} row(s)")
print(f"  G2_Sensitivity — {len(df_g2_export)} row(s)")
if not df_dcf_summary.empty:
    print(df_dcf_summary[["Ticker", "WACC", "Value_Per_Share", "Price", "Upside_Pct", "Valuation"]].to_string(index=False))
# endregion


# region Interpretation
print("\n=== Interpretation ===")

if fcf_norm_negative:
    print(f">>> MODEL NOT APPLICABLE: normalized FCF is {fcf_norm/1e9:.2f} Bn USD. Every DCF")
    print(f"    figure in this run — intrinsic value, upside, sensitivity, Monte Carlo,")
    print(f"    peer rank — discounts a negative cash flow and must not be read as a")
    print(f"    valuation. The remaining comments describe the model's behaviour, not")
    print(f"    an investment case.")

if not np.isnan(fcf_cagr):
    if fcf_cagr > 0.10:
        print(f">>> FCF CAGR {fcf_cagr:.1%}: Strong FCF growth — supports a high DCF value.")
    elif fcf_cagr > 0:
        print(f">>> FCF CAGR {fcf_cagr:.1%}: Moderate FCF growth — DCF valuation on solid footing.")
    elif fcf_cagr > -0.20:
        print(f">>> FCF CAGR {fcf_cagr:.1%}: FCF declining — cycle slowdown, review the DCF forecast critically.")
    else:
        print(f">>> FCF CAGR {fcf_cagr:.1%}: Sharp FCF decline — use normalized FCF for DCF instead of the 5Y trend.")

lev_ratio = net_debt / market_cap if market_cap > 0 else 0
if lev_ratio > 0.5:
    print(f">>> Net Debt / MarketCap = {lev_ratio:.1%}: High net leverage — weighs on DCF equity value.")
elif lev_ratio > 0.1:
    print(f">>> Net Debt / MarketCap = {lev_ratio:.1%}: Moderate net leverage — within range for the sector.")
else:
    print(f">>> Net Debt / MarketCap = {lev_ratio:.1%}: Near debt-free net position — DCF value flows almost entirely to equity.")

diff_bp = (wacc - WACC_CONFIG) * 10000
if abs(diff_bp) > 150:
    print(f">>> WACC (CAPM) {wacc:.1%} deviates {diff_bp:+.0f} bp from Config ({WACC_CONFIG:.1%}) — check beta or capital structure.")
else:
    print(f">>> WACC (CAPM) {wacc:.1%} close to Config estimate ({WACC_CONFIG:.1%}, {diff_bp:+.0f} bp) — consistent cost-of-capital basis.")

ebitda_margin = ebitda[0] / revenue[0] if revenue[0] > 0 else 0
if ebitda_margin < 0.15:
    print(f">>> EBITDA margin {ebitda_margin:.1%}: Compressed margin in the most recent year — review recovery assumptions for later DCF blocks.")
elif ebitda_margin < 0.30:
    print(f">>> EBITDA margin {ebitda_margin:.1%}: Solid margin, but below historical level — use a normalized margin for the DCF.")
else:
    print(f">>> EBITDA margin {ebitda_margin:.1%}: Strong operating margin — supports a high FCF in the DCF forecast.")

tv_anteil = pv_tv / ev_dcf if ev_dcf > 0 else 0
if tv_anteil > 0.70:
    print(f">>> Terminal Value = {pv_tv/1e9:.1f} Bn = {tv_anteil:.0%} of DCF EV — high TV dependency, model sensitive to g2 and WACC.")
else:
    print(f">>> Terminal Value = {pv_tv/1e9:.1f} Bn = {tv_anteil:.0%} of DCF EV — balanced weighting between forecast and terminal value.")

if upside > 10:
    print(f">>> DCF signals {upside:+.1f}% upside — stock appears undervalued; review the normalization assumption and g1 critically.")
elif upside < -10:
    print(f">>> DCF signals {upside:+.1f}% downside — the market is pricing in higher FCF growth than the Base Case assumption.")
else:
    print(f">>> DCF signals {upside:+.1f}% — stock near fair value given the WACC ({wacc:.1%}) and growth assumptions ({g1:.0%}/{g2:.1%}).")

print(f">>> Sensitivity: {_n_under}/{_n_total} scenarios UNDERVALUED, {_n_over}/{_n_total} OVERVALUED, {_n_fair}/{_n_total} FAIR (±10%).")
if fair_combos:
    print(f">>> {len(fair_combos)} fair value combination(s) (±5%) identified — lowest model sensitivity in this range.")
else:
    print(f">>> No combination within ±5% of the market price — the market is pricing in assumptions outside the base matrix.")

mc_ci_width = mc_p90 - mc_p10
if p_undervalued < 0.10:
    print(f">>> Monte Carlo: P(Undervalued)={p_undervalued:.1%} — consistently expensive across all scenarios; Base Case downside statistically robust.")
elif p_undervalued > 0.60:
    print(f">>> Monte Carlo: P(Undervalued)={p_undervalued:.1%} — majority of scenarios show upside; review parameter choice critically.")
else:
    print(f">>> Monte Carlo: P(Undervalued)={p_undervalued:.1%} — mixed picture; significant uncertainty in the model.")
print(f">>> MC P10–P90 range: {mc_p10:.0f}–{mc_p90:.0f} USD ({mc_ci_width:.0f} USD) — {mc_ci_width/mc_median:.0%} relative dispersion.")
print(f">>> MC median {mc_median:.0f} USD vs. Base Case {equity_per_share:.0f} USD — {'consistent' if abs(mc_median - equity_per_share) / equity_per_share < 0.05 else 'difference due to non-linear discounting effects across a wide WACC distribution'}.")

_scen_wa = {k: v["value_per_share"] for k, v in scen_results.items()}
_scen_spread = _scen_wa["Bull"] - _scen_wa["Bear"]
_spread_rel  = _scen_spread / current_price if current_price > 0 else float("nan")
print(f">>> Scenario range: Bear ${_scen_wa['Bear']:.0f} — Bull ${_scen_wa['Bull']:.0f} "
      f"(${_scen_spread:.0f} USD, {_spread_rel:.0%} of price) — "
      f"{'high' if _spread_rel > 0.50 else 'moderate'} model sensitivity.")

if not df_peer.empty:
    _top_peer  = df_peer.iloc[0]
    _act_rows  = df_peer[df_peer["Ticker"] == TICKER]
    _rank      = int(_act_rows.index[0]) + 1 if not _act_rows.empty else "—"
    print(f">>> Peer Group: {TICKER} rank {_rank}/{len(df_peer)} by DCF upside; "
          f"highest upside: {_top_peer['Ticker']} ({_top_peer['Upside_Pct']:+.1f}%).")

print(f">>> Multiples Cross-Check: EV/EBITDA {ev_ebitda_mult:.1f}x ({mult_ratings['EV/EBITDA']}), "
      f"P/E {pe_ratio_mult:.1f}x ({mult_ratings['P/E']}), "
      f"EV/Sales {ev_sales_mult:.1f}x ({mult_ratings['EV/Sales']}).")
# endregion


# region Legende
print("\n=== Legende ===")
print("dcf_core.py    = Pure calculation module (no I/O) — DCF, CAPM, sensitivity, Monte Carlo")
print("base_params    = DcfParams for the active ticker: fcf_start, g1, g2, wacc, years, net_debt, shares")
print("fmp_extract.py  = Cache access + FMP field mapping (load_json, load_prices, extract_wacc_inputs)")
print("WACC           = Weighted Average Cost of Capital")
print("FCF            = Free Cash Flow — operating CF minus capex")
print("FCF CAGR       = Compound Annual Growth Rate of FCF over 5 years")
print("OpCF           = Operating Cash Flow — operating cash flow before capex")
print("EV             = Enterprise Value = MarketCap + Debt − Cash")
print("Net Debt       = Net debt = total debt − cash & equivalents")
print("EBITDA         = Earnings before Interest, Taxes, Depreciation & Amortization")
print("Earnings Yield = Net income / market capitalization (inverse of P/E)")
print("FCF Yield      = Free cash flow / market capitalization")
print("TERMINAL_GROWTH= Perpetual growth rate for the DCF terminal value")
print("FORECAST_YEARS  = Number of explicit DCF forecast years")
print("Beta           = Market risk factor from a 252-day OLS regression vs S&P 500")
print("Ke             = Cost of equity = rf + Beta × market premium 5.5% (CAPM)")
print("Kd             = Cost of debt = interest expense / total debt")
print("Kd after tax   = Kd × (1 − effective tax rate)")
print("E/V, D/V       = Equity/debt share of total value (market basis)")
print("market_premium = Equity Risk Premium (ERP) = 5.5% (Damodaran estimate)")
print("fcf_norm       = Normalized FCF = median of the last 5 annual values")
print("g1             = Phase-1 growth rate (years 1–5, from Config GROWTH_MEAN)")
print("g2             = Perpetual growth rate = Terminal Growth Rate (from Config)")
print("TV             = Terminal Value = FCF_Year5 × (1+g2) / (WACC − g2)")
print("pv_tv          = Present value of the Terminal Value")
print("pv_fcf_sum     = Sum of discounted FCFs over the explicit forecast period")
print("ev_dcf         = Enterprise Value from DCF = pv_fcf_sum + pv_tv")
print("equity_value   = Equity value (DCF) = ev_dcf − Net Debt")
print("equity_per_share = Intrinsic share value = equity_value / shares_outstanding")
print("shares_outstanding = Implied share count = MarketCap / current_price")
print("current_price  = Last available closing price from the FMP cache")
print("upside         = (intrinsic value / current_price − 1) × 100 %")
print("WACC_RANGE     = Sensitivity range WACC [8%–14%] for the matrix")
print("G1_RANGE       = Sensitivity range Phase-1 growth [2%–8%] for the matrix")
print("matrix         = 7×7 sensitivity matrix: equity_per_share for each (WACC, g1) combination")
print("df_sens        = Sensitivity matrix as DataFrame (Index=WACC, Columns=g1)")
print("↑ UNDERVALUED  = Intrinsic value > price × 1.10 (>10% upside)")
print("↓ OVERVALUED   = Intrinsic value < price × 0.90 (>10% downside)")
print("≈ FAIR         = Intrinsic value within ±10% of the current price")
print("fair_combos    = List of all combinations within ±5% of the market price")
print("wacc_idx, g1_idx = Closest grid indices to the calculated WACC and g1 (for heatmap marker)")
print("fig3           = Plotly heatmap object (heatmap + contour line + scatter marker)")
print("chart3_path    = Output path of the heatmap (PNG or HTML)")
print("excel_path     = Output path of the Excel sensitivity table (.xlsx)")
print("_n_total       = Total number of scenarios in the sensitivity matrix (= 49)")
print("_n_under       = Number of undervalued scenarios (value > price × 1.10)")
print("_n_over        = Number of overvalued scenarios (value < price × 0.90)")
print("_n_fair        = Number of fair scenarios (±10% range)")
print("SIMULATIONS   = Number of Monte Carlo simulations (from Config)")
print("WACC_STD       = Standard deviation of the WACC draw (from Config, in %)")
print("GROWTH_STD   = Standard deviation of the growth draw (from Config, in %)")
print("FCF_STD_FACTOR = Relative FCF uncertainty (±15% of normalized FCF)")
print("simulate_dcf() = dcf_core: draws WACC (clipped ≥4%), g1 (clipped ≥0%) and starting FCF")
print("mc_results     = Array of simulated share values after cleanup (no NaN)")
print("mc_mean        = Arithmetic mean of the Monte Carlo distribution (USD)")
print("mc_median      = Median of the Monte Carlo distribution (USD)")
print("mc_std         = Standard deviation of the Monte Carlo distribution (USD)")
print("mc_p10/p90     = 10th / 90th percentile of the Monte Carlo distribution (USD)")
print("mc_p25/p75     = 25th / 75th percentile (interquartile range)")
print("p_undervalued        = Share of simulations with equity_per_share > current_price")
print("fig4           = Plotly histogram: ORANGE_2=overvalued, BLUE_2=undervalued")
print("chart4_path    = Output path of the MC histogram (PNG or HTML)")
print("SCENARIOS_DCF  = Three DCF scenarios (Bear/Base/Bull) with Δg1, ΔWACC, FCF factor")
print("dcf_full()     = dcf_core: full DCF → ev, equity, value_per_share, pv_terminal_value")
print("with_params()  = dcf_core: copy of base_params with single fields overridden")
print("scen_results   = Dict: results per scenario (WACC, g1, FCF, EV, Value/Share, Upside)")
print("SCENARIO_COLORS= Color mapping for the scenarios in Plotly")
print("fig5           = Bar chart: intrinsic value/share per scenario")
print("chart5_path    = Output path of the scenario chart (PNG or HTML)")
print("_ALL_TICKERS   = List of all 5 peer tickers: MCHP, INTC, ON, QCOM, MPWR")
print("_sp500_peer    = S&P 500 price series for beta calculation in the peer loop")
print("_peer_wacc()   = CAPM WACC for any ticker with explicit market_cap")
print("df_peer        = DataFrame: peer group results, sorted by upside (descending)")
print("fig6           = Bar chart: peer group — DCF value/share vs. price")
print("chart6_path    = Output path of the peer chart (PNG or HTML)")
print("ev_ebitda_mult = EV / EBITDA (most recent year, market EV)")
print("pe_ratio_mult  = Price / (NetIncome / Shares) — price-to-earnings ratio")
print("ev_sales_mult  = EV / Revenue (most recent year)")
print("BENCH          = Semiconductor sector benchmarks: EV/EBITDA 15–25×, P/E 20–35×, EV/Sales 3–8×")
print("mult_ratings   = Dict: valuation rating per multiple (CHEAP / FAIR / EXPENSIVE)")
print("mult_values    = Dict: calculated multiples per metric")
print("export_excel_dcf() = Writes all DCF results to one .xlsx workbook (one sheet per set)")
print("DCF_Results_*.xlsx = Workbook in EXCEL_DIR/{TICKER}/ (read back by MCS for the peer summary)")
print("  Sheet Summary        = All 5 tickers: WACC, Beta, FCF, DCF value, price, upside, valuation")
print("  Sheet Scenarios      = Bear/Base/Bull for ACTIVE_CONFIG: WACC, g1, FCF, EV, Value/Share")
print("  Sheet Peer_Group     = Peer group with DCF value, price, beta, WACC, valuation")
print("Terminal_Value_Share_Pct = PV(Terminal Value) / EV_DCF * 100 (Base Case, per ticker)")
print("_peer_base_params  = Dict: Ticker -> DcfParams of its Base Case (reused in Block 6b)")
print("G2_SENS_RANGE      = g2 sensitivity range [1.5%, 2.0%, 2.5%, 3.0%, 3.5%] (Block 6b)")
print("G2_SENS_BASE       = Reference g2 for the Delta% comparison (2.5%)")
print("df_g2_sens         = DataFrame: Ticker, g2, Value_per_Share, Delta_Pct_vs_Base (all 5 tickers)")
print("  Sheet G2_Sensitivity = g2 sensitivity for all 5 tickers x 5 g2 values")
# endregion
