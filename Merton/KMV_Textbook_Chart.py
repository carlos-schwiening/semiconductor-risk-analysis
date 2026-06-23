"""
KMV_Textbook_Chart — Merton (1974) Textbook Diagram for all 5 Tickers
========================================================================
Run with: python Merton/KMV_Textbook_Chart.py

  Block 0: Imports & Setup
  Block 1: Helper Functions & Merton Calculation (all 5 tickers)
  Block 2: GBM Simulation & Chart Creation (per ticker)
  Block 3: PNG Export
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
import plotly.graph_objects as go
from scipy.stats import norm

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plot_style import LAYOUT, ORANGE_1, GRAY_1, BG, TEXT, TICKER_COLORS

TICKER_LIST   = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]
CACHE_FOLDER  = r"C:\Python\Data\FMP\FMP_Cache"
OUTPUT_DIR = r"C:\Python\Outputs\Reports\DCF_Merton_MC"

TODAY   = date.today().strftime("%Y-%m-%d")
N_PATHS = 15      # 14 gray + 1 highlighted in ticker color
T_DAYS  = 252     # Simulation horizon in trading days

print(f"\n{'='*60}")
print(f"KMV Textbook Chart — {TODAY}")
print(f"{'='*60}")
# endregion


# region Block 1 - Helper Functions & Merton Calculation
def load_json(filename):
    with open(os.path.join(CACHE_FOLDER, filename), "r", encoding="utf-8") as f:
        return json.load(f)


def merton_model(E, D, r, T_val, sigma_e, max_iter=1000, tol=1e-6):
    """Iterative Merton (1974). Returns V, sigma_v, dd, pd."""
    V, sigma_v = E + D, sigma_e * (E / (E + D))
    for _ in range(max_iter):
        st    = np.sqrt(T_val)
        d1    = (np.log(V / D) + (r + 0.5 * sigma_v**2) * T_val) / (sigma_v * st)
        d2    = d1 - sigma_v * st
        e_mod = V * norm.cdf(d1) - D * np.exp(-r * T_val) * norm.cdf(d2)
        v_new = V * (E / e_mod)
        sv_new = sigma_e * (E / v_new)
        if abs(v_new - V) < tol and abs(sv_new - sigma_v) < tol:
            V, sigma_v = v_new, sv_new
            break
        V, sigma_v = v_new, sv_new
    st = np.sqrt(T_val)
    dd = (np.log(V / D) + (r - 0.5 * sigma_v**2) * T_val) / (sigma_v * st)
    return {"V": V, "sigma_v": sigma_v, "dd": dd, "pd": float(norm.cdf(-dd))}


print("\nMerton calculation (all 5 tickers):")
print(f"  {'Ticker':<6} {'V0 (Mrd)':>10} {'D (Mrd)':>9} {'DD':>7} {'sigma_V':>9} {'PD':>10}")
print(f"  {'-'*6} {'-'*10} {'-'*9} {'-'*7} {'-'*9} {'-'*10}")

ticker_params = {}
for tkr in TICKER_LIST:
    cfg     = importlib.import_module(f"Config.{tkr}")
    raw     = load_json(f"{tkr}_historical-price-eod_full.json")
    df_p    = pd.DataFrame(raw)
    df_p["date"] = pd.to_datetime(df_p["date"])
    prices  = df_p.sort_values("date").set_index("date")["close"]
    log_ret = np.log(prices / prices.shift(1)).dropna()
    sigma_e = float(log_ret.std() * np.sqrt(252))
    bs      = load_json(f"{tkr}_balance-sheet-statement.json")[0]
    km      = load_json(f"{tkr}_key-metrics.json")[0]
    E       = float(km.get("marketCap", 0) or 0)
    D       = float(bs.get("totalDebt",  0) or 0)
    m       = merton_model(E, D, cfg.RISK_FREE_RATE, cfg.MATURITY, sigma_e)
    ticker_params[tkr] = {
        "V0": m["V"], "sigma_V": m["sigma_v"],
        "mu": cfg.RISK_FREE_RATE, "D": D,
        "dd": m["dd"], "pd": m["pd"],
    }
    print(f"  {tkr:<6} {m['V']/1e9:>10.2f} {D/1e9:>9.2f} {m['dd']:>7.3f} "
          f"{m['sigma_v']:>9.1%} {m['pd']:>10.6%}")
# endregion


# region Block 2 - GBM Simulation & Chart Creation
def create_textbook_chart(tkr, params):
    """Build KMV textbook chart for one ticker. Returns fig."""
    V0     = params["V0"]
    sv     = params["sigma_V"]
    mu     = params["mu"]
    D      = params["D"]
    dd     = params["dd"]
    pd_val = params["pd"]
    color  = TICKER_COLORS[tkr]

    V0_bn = V0 / 1e9
    D_bn  = D  / 1e9

    # ── GBM path simulation (Seed=42 for reproducibility) ─────
    np.random.seed(42)
    dt      = 1.0 / T_DAYS
    Z       = np.random.standard_normal((N_PATHS, T_DAYS))
    log_inc = (mu - 0.5 * sv**2) * dt + sv * np.sqrt(dt) * Z
    log_cum = np.hstack([np.zeros((N_PATHS, 1)), np.cumsum(log_inc, axis=1)])
    paths   = V0_bn * np.exp(log_cum)   # (N_PATHS, T_DAYS+1) in Bn USD
    t_arr   = np.arange(T_DAYS + 1)

    # Expected asset value path: E[A_t] = V0 * exp(mu * t/252)
    expected = V0_bn * np.exp(mu * t_arr / T_DAYS)

    # ── Lognormal distribution at T=1 year ────────────────────────
    # log(A_T) ~ N(mu_T, sigma_T²)  with  mu_T = log(V0) + (mu - 0.5*sv²)*T
    mu_T       = np.log(V0) + (mu - 0.5 * sv**2) * 1.0
    sigma_T    = sv
    x_norm     = np.linspace(mu_T - 3.5 * sigma_T, mu_T + 3.5 * sigma_T, 300)
    y_norm     = norm.pdf(x_norm, mu_T, sigma_T)
    asset_vals = np.exp(x_norm) / 1e9   # Bn USD — corresponds to y-axis

    max_pdf = max(float(y_norm.max()), 1e-30)
    scale   = T_DAYS * 0.22 / max_pdf   # Distribution fits within ~22% of the time axis
    x_dist  = T_DAYS + y_norm * scale   # x-coordinates for right panel

    # Area below default point → EDF area
    edf_mask = asset_vals <= D_bn

    # ── Y-axis range ─────────────────────────────────────────
    y_min = max(0.0, min(D_bn * 0.50, float(paths.min()) * 0.85))
    y_max = max(float(paths.max()), float(expected[-1]), float(asset_vals[-1])) * 1.12

    # Density label at the height of the E[A_T] line
    density_y = float(expected[-1])

    # ── Build figure ──────────────────────────────────────────
    fig = go.Figure()

    # 1) Red background zone below default point (simulation range only)
    fig.add_shape(
        type="rect",
        x0=0, x1=T_DAYS,
        y0=0, y1=max(D_bn, 0.001),
        fillcolor="#C0392B", opacity=0.05,
        line_width=0, layer="below",
    )

    # 2) Gray GBM paths (N_PATHS - 1)
    for i in range(N_PATHS - 1):
        fig.add_trace(go.Scatter(
            x=t_arr, y=paths[i],
            mode="lines",
            line=dict(color="#D1D5DB", width=0.8),
            opacity=0.6,
            showlegend=False, hoverinfo="skip",
        ))

    # 3) Highlighted path in ticker color
    fig.add_trace(go.Scatter(
        x=t_arr, y=paths[-1],
        mode="lines",
        line=dict(color=color, width=1.5),
        name="Simulated Asset Path",
    ))

    # 4) Expected value path E[A_T] (dashed gray)
    fig.add_trace(go.Scatter(
        x=t_arr, y=expected,
        mode="lines",
        line=dict(color=GRAY_1, width=1.5, dash="dot"),
        name="E[A<sub>T</sub>] Expected Path",
    ))

    # 5) Default point as horizontal line (ends at T=252)
    fig.add_shape(
        type="line",
        x0=0, x1=T_DAYS,
        y0=D_bn, y1=D_bn,
        line=dict(color=ORANGE_1, width=2),
    )

    # 6) V₀ start marker (circle) + annotation to its left
    fig.add_trace(go.Scatter(
        x=[0], y=[V0_bn],
        mode="markers",
        marker=dict(color=color, size=8, symbol="circle"),
        showlegend=False, hoverinfo="skip",
    ))
    fig.add_annotation(
        x=0, y=V0_bn,
        text=f"V₀ = {V0_bn:.1f} Bn",
        showarrow=False,
        font=dict(size=10, color=TEXT),
        xanchor="right", yanchor="middle",
        xshift=-8,
        bgcolor="rgba(255,255,255,0.80)",
    )

    # 7) Lognormal distribution curve (right panel, sideways)
    fig.add_trace(go.Scatter(
        x=x_dist, y=asset_vals,
        mode="lines",
        line=dict(color="#1A1A1A", width=1.5),
        name="Asset Distribution at T",
    ))

    # 8) EDF area (polygon below default point in the distribution)
    if edf_mask.any():
        y_edf  = asset_vals[edf_mask]
        x_edf  = x_dist[edf_mask]
        x_poly = np.concatenate([x_edf, [T_DAYS, T_DAYS]])
        y_poly = np.concatenate([y_edf, [float(y_edf[-1]), float(y_edf[0])]])
        fig.add_trace(go.Scatter(
            x=x_poly, y=y_poly,
            fill="toself",
            fillcolor="rgba(192,57,43,0.40)",
            line=dict(color="#C0392B", width=0.5),
            name=f"EDF = {pd_val:.4%}",
        ))

    # 9) Vertical divider line at horizon T=252
    fig.add_vline(x=T_DAYS, line_color="#D1D5DB", line_width=1.0, line_dash="dot")

    # X-axis line only up to T=252 (showline=False, manual shape)
    fig.add_shape(type="line", x0=0, x1=T_DAYS, y0=y_min, y1=y_min,
                  line=dict(color="#E5E5E5", width=1), layer="above")

    # ── Annotations ────────────────────────────────────────────
    # Default point label (left)
    fig.add_annotation(
        x=6, y=D_bn,
        text=f"Default Point  D = {D_bn:.2f} Bn",
        showarrow=False,
        font=dict(size=10, color=ORANGE_1),
        xanchor="left", yanchor="bottom",
        bgcolor="rgba(255,255,255,0.80)",
    )

    # E[A_T] label at the right end of the expectation line
    fig.add_annotation(
        x=T_DAYS - 5, y=float(expected[-1]),
        text="E[A<sub>T</sub>]",
        showarrow=False,
        font=dict(size=10, color=GRAY_1),
        xanchor="right", yanchor="bottom",
        bgcolor="rgba(255,255,255,0.80)",
    )

    # Density label (top of right panel)
    fig.add_annotation(
        x=T_DAYS + T_DAYS * 0.13, y=density_y,
        text="Density of asset<br>value at T",
        showarrow=False,
        font=dict(size=9, color="#1A1A1A"),
        xanchor="center", yanchor="bottom",
    )

    # Horizon marker
    fig.add_annotation(
        x=T_DAYS, y=y_min + (y_max - y_min) * 0.01,
        text="H = 252",
        showarrow=False,
        font=dict(size=9, color=GRAY_1),
        xanchor="center", yanchor="bottom",
    )

    # Source attribution top right
    fig.add_annotation(
        xref="paper", yref="paper",
        x=1.0, y=1.02,
        text="Source: FMP API · Merton (1974)",
        showarrow=False,
        font=dict(size=9, color="#9CA3AF"),
        xanchor="right", yanchor="bottom",
    )

    # ── Layout (two-stage: LAYOUT first, legend separate) ───────
    fig.update_layout(**LAYOUT)
    fig.update_layout(
        title=dict(
            text=(f"{tkr} — KMV Asset Value Simulation (Merton 1974)<br>"
                  f"<sup>DD = {dd:.3f}σ  |  EDF = {pd_val:.4%}  |  "
                  f"σ_V = {sv*100:.1f}%</sup>"),
            font=dict(size=15, color="#0B1220"),
            x=0.0,
        ),
        width=1100, height=650,
        margin=dict(l=70, r=20, t=90, b=80),
        xaxis=dict(
            range=[0, T_DAYS * 1.20],
            title=dict(text="Time (Trading Days)", font=dict(size=12)),
            tickvals=[0, 63, 126, 189, 252],
            ticktext=["0", "63", "126", "189", "252"],
            showgrid=False, zeroline=False, showline=False,
        ),
        yaxis=dict(
            range=[y_min, y_max],
            title=dict(text="Market Value of Assets (Bn USD)", font=dict(size=12)),
            showgrid=False, zeroline=False,
            showline=True, linecolor="#E5E5E5",
        ),
        legend=dict(
            orientation="h", bgcolor="rgba(0,0,0,0)", borderwidth=0,
            x=0, y=-0.14, font=dict(size=10),
        ),
        showlegend=True,
    )
    return fig
# endregion


# region Block 3 - PNG Export
saved_files = []
for tkr in TICKER_LIST:
    print(f"\n  Creating chart: {tkr} ...", end=" ", flush=True)
    tkr_output = os.path.join(OUTPUT_DIR, tkr)
    os.makedirs(tkr_output, exist_ok=True)
    fig      = create_textbook_chart(tkr, ticker_params[tkr])
    png_path = os.path.join(tkr_output, f"{tkr}_KMV_Textbook_{TODAY}.png")
    fig.write_image(png_path, width=1100, height=650, scale=2)
    saved_files.append(png_path)
    print("saved.")

print(f"\n=== PNG Export ===")
for fpath in saved_files:
    size_kb = os.path.getsize(fpath) // 1024
    print(f"  {os.path.basename(fpath)}  ({size_kb} KB)")
print(f"\nFolder: {OUTPUT_DIR}")
# endregion


# region Interpretation
print("\n=== Interpretation ===")
for tkr in TICKER_LIST:
    p = ticker_params[tkr]
    edf_sichtbar = "EDF area visible" if p["pd"] > 1e-5 else "EDF too small for scaling"
    print(f">>> {tkr}: DD={p['dd']:.3f}  EDF={p['pd']:.4%}  "
          f"V0={p['V0']/1e9:.1f} Mrd  D={p['D']/1e9:.2f} Mrd  "
          f"sigma_V={p['sigma_V']:.1%}  [{edf_sichtbar}]")

riskiest = min(ticker_params, key=lambda t: ticker_params[t]["dd"])
safest   = max(ticker_params, key=lambda t: ticker_params[t]["dd"])
print(f"\n>>> Highest risk:    {riskiest} (DD={ticker_params[riskiest]['dd']:.3f}sigma) — "
      f"paths close to the default point, red EDF area visible")
print(f">>> Lowest risk:     {safest} (DD={ticker_params[safest]['dd']:.3f}sigma) — "
      f"wide buffer, default zone barely visible at the bottom edge")
# endregion


# region Legende
print("\n=== Legende ===")
print("V0          = Merton asset value (iterated from equity market cap, in Bn USD)")
print("D           = Default point = Total Debt (in Bn USD, constant = horizontal line)")
print("sigma_V     = Asset volatility (annualized, iterated from sigma_E via Merton)")
print("mu          = Drift = risk-free rate (risk-neutral GBM drift)")
print("E[A_T]      = V0 * exp(mu * t/252)  — expected asset value path")
print("mu_T        = log(V0) + (mu - 0.5*sigma_V^2)  — mean of log(A_T) at T=1")
print("sigma_T     = sigma_V  — std dev of log(A_T) at T=1")
print("x_norm      = grid points in log space: linspace(mu_T-3.5*sigma_T, ..., 300)")
print("y_norm      = norm.pdf(x_norm, mu_T, sigma_T)  — PDF in log space")
print("asset_vals  = exp(x_norm) / 1e9  — asset values in Bn USD (right y-axis)")
print("x_dist      = 252 + y_norm * scale  — x-coordinates for right panel")
print("scale       = T_DAYS * 0.22 / max(y_norm)  — normalization factor")
print("edf_mask    = asset_vals <= D/1e9  — range below default point")
print("density_y   = float(expected[-1])  — density label at E[A_T] line height")
print("EDF polygon = area between curve and x=252 below D")
print("N_PATHS     = 15  (14 gray #D1D5DB + 1 in ticker color, Seed=42)")
print("T_DAYS      = 252  (1 year of trading days)")
print("TICKER_COLORS: MCHP=#1B4332, INTC=#C0392B, ON=#2D6A4F, QCOM=#1D6FD8, MPWR=#0B1220")
# endregion
