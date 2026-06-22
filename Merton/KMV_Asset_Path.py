"""
KMV_Asset_Path — KMV/Merton Asset Value Simulation (all 5 tickers)
===================================================================
Run with: python Merton/KMV_Asset_Path.py

  Block 0: Imports & Setup
  Block 1: Load Data & Calculate Merton (all 5 tickers)
  Block 2: Simulate GBM Asset Path
  Block 3: Calculate Normal Distribution at Horizon
  Block 4: Plotly Chart per Ticker (KMV Visualization)
  Block 5: HTML Summary (all 5 tickers)
"""

# region Block 0 - Imports & Setup
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import os
import json
import importlib
import warnings
import webbrowser
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.stats import norm

warnings.filterwarnings("ignore")

debug = False

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TODAY = date.today().strftime("%Y-%m-%d")

TICKER_LIST   = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]
CACHE_FOLDER  = r"C:\Python\Data\FMP\FMP_Cache"
OUTPUT_DIR = r"C:\Python\Outputs\Visualisierung"
NAVBAR_BG     = "#0B1220"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# plot_style — central design template
from plot_style import LAYOUT, BLUE_1, BLUE_2, BLUE_3, ORANGE_1, ORANGE_2, ORANGE_3, GRAY_1
BG     = "#FFFFFF"; TEXT = "#1A1A1A"; BORDER = "#E5E5E5"; TEXT_MUTED = "#9CA3AF"

# endregion


# region Block 1 - Load Data & Calculate Merton
# ─────────────────────────────────────────────────────────────
# Loads FMP cache data for each ticker, runs merton_model()
# and stores all results in `all_results`.
# ─────────────────────────────────────────────────────────────

def load_json(filename):
    """Load a JSON cache file and return its contents."""
    path = os.path.join(CACHE_FOLDER, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def merton_model(E, D, r, T, sigma_e, max_iter=1000, tol=1e-6):
    """Iterative Merton (1974) model. Returns dict: V, sigma_v, dd, pd, el."""
    V       = E + D
    sigma_v = sigma_e * (E / V)
    for _ in range(max_iter):
        sqrt_t = np.sqrt(T)
        d1     = (np.log(V / D) + (r + 0.5 * sigma_v**2) * T) / (sigma_v * sqrt_t)
        d2     = d1 - sigma_v * sqrt_t
        e_mod  = V * norm.cdf(d1) - D * np.exp(-r * T) * norm.cdf(d2)
        v_new  = V * (E / e_mod)
        sv_new = sigma_e * (E / v_new)
        if abs(v_new - V) < tol and abs(sv_new - sigma_v) < tol:
            V, sigma_v = v_new, sv_new
            break
        V, sigma_v = v_new, sv_new
    sqrt_t = np.sqrt(T)
    dd     = (np.log(V / D) + (r - 0.5 * sigma_v**2) * T) / (sigma_v * sqrt_t)
    pd_val = float(norm.cdf(-dd))
    el     = pd_val * D * 0.45
    return {"V": V, "sigma_v": sigma_v, "dd": dd, "pd": pd_val, "el": el}


RATING_TABLE = [
    ("AAA/AA",  8.0,  float("inf"),  30,    50),
    ("A",       6.0,  8.0,           60,    90),
    ("BBB",     4.0,  6.0,           120,  180),
    ("BB",      2.0,  4.0,           250,  400),
    ("B",       1.0,  2.0,           400,  650),
    ("CCC",     0.0,  1.0,           800, 1200),
]


def get_rating_info(dd):
    for rating, dd_min, dd_max, bps_lo, bps_hi in RATING_TABLE:
        if dd_min <= dd < dd_max or (dd_max == float("inf") and dd >= dd_min):
            return rating, bps_lo, bps_hi
    return "CCC", 800, 1200


def load_ticker_data(ticker):
    """Load prices, balance sheet, key metrics for one ticker."""
    raw       = load_json(f"{ticker}_historical-price-eod_full.json")
    df        = pd.DataFrame(raw)
    df["date"] = pd.to_datetime(df["date"])
    df        = df.sort_values("date").set_index("date")
    prices    = df["close"]
    log_ret   = np.log(prices / prices.shift(1)).dropna()
    sigma_e   = float(log_ret.std() * np.sqrt(252))
    bs        = load_json(f"{ticker}_balance-sheet-statement.json")[0]
    total_debt = float(bs.get("totalDebt", 0))
    km        = load_json(f"{ticker}_key-metrics.json")[0]
    market_cap = float(km.get("marketCap", 0))
    return sigma_e, total_debt, market_cap


print(f"\n{'='*60}")
print(f"KMV Asset Path Simulation — {date.today()}")
print(f"{'='*60}")

all_results = []
for tkr in TICKER_LIST:
    print(f"  Loading {tkr} ...", end=" ")
    try:
        cfg  = importlib.import_module(f"Config.{tkr}")
        name = cfg.COMPANY
        r    = cfg.RISK_FREE_RATE
        T    = getattr(cfg, "MATURITY", 1)

        sigma_e, total_debt, market_cap = load_ticker_data(tkr)
        E, D = market_cap, total_debt
        m    = merton_model(E, D, r, T, sigma_e)

        rating, _, _ = get_rating_info(m["dd"])
        all_results.append({
            "ticker":    tkr,
            "name":      name,
            "V":         m["V"],
            "D":         D,
            "mu":        r,
            "sigma_V":   m["sigma_v"],
            "sigma_E":   sigma_e,
            "dd":        m["dd"],
            "pd":        m["pd"],
            "T":         T,
            "rating":    rating,
        })
        print(f"V={m['V']/1e9:.1f} Bn  D={D/1e9:.2f} Bn  DD={m['dd']:.3f}  σ_V={m['sigma_v']:.1%}")
    except Exception as e:
        print(f"ERROR: {e}")

# endregion


# region Block 2 - Simulate GBM Asset Path
# ─────────────────────────────────────────────────────────────
# Geometric Brownian Motion: exact solution (incremental)
#   V_{t+dt} = V_t * exp((mu − 0.5*σ_V²)*dt + σ_V*√dt * Z)
# Returns: simulated path, E[V], upper/lower band (Bn)
# ─────────────────────────────────────────────────────────────

def simulate_gbm(V0_m, mu, sigma_V, N=252):
    """
    GBM simulation for one asset (values in Bn USD).
    Returns: path, expected, upper, lower — all arrays of length N+1.
    """
    np.random.seed(42)
    dt      = 1.0 / N
    Z       = np.random.normal(0, 1, N)
    steps   = np.exp((mu - 0.5 * sigma_V**2) * dt + sigma_V * np.sqrt(dt) * Z)
    path    = V0_m * np.concatenate([[1.0], np.cumprod(steps)])

    t_arr    = np.arange(N + 1) * dt
    expected = V0_m * np.exp(mu * t_arr)
    upper    = V0_m * np.exp((mu + sigma_V) * t_arr)
    lower    = V0_m * np.exp((mu - sigma_V) * t_arr)

    return path, expected, upper, lower

# endregion


# region Block 3 - Calculate Normal Distribution at Horizon
# ─────────────────────────────────────────────────────────────
# At time horizon T=1: ln(V_T) ~ N(ln(V0)+(mu-½σ²)T, σ√T)
# The asset distribution is log-normal; for chart visualization
# the approximated normal distribution around mean_VT is used.
# ─────────────────────────────────────────────────────────────

def compute_horizon_dist(V0_m, D_m, mu, sigma_V, T=1.0):
    """
    Compute normal distribution of asset value at horizon T.
    y_range extends downward to include D if D < 3.5-sigma range.
    Returns: y_range, pdf, mean_VT, std_VT (all in Bn)
    """
    mean_VT = V0_m * np.exp(mu * T)
    std_VT  = mean_VT * sigma_V * np.sqrt(T)

    y_lo    = min(mean_VT - 3.5 * std_VT, D_m * 0.90)
    y_hi    = mean_VT + 3.5 * std_VT
    y_range = np.linspace(y_lo, y_hi, 300)
    pdf     = norm.pdf(y_range, mean_VT, std_VT)

    return y_range, pdf, mean_VT, std_VT

# endregion


# region Block 4 - Plotly Chart per Ticker
# ─────────────────────────────────────────────────────────────
# KMV visualization following Kealhofer/McQuown/Vasicek (Moody's):
#   Left side:  GBM asset path (0 to T=252 trading days)
#   Right side: Normal distribution at horizon (sideways, x=PDF)
# Reference lines, double arrows (DD, σ_V), EDF area.
# ─────────────────────────────────────────────────────────────

def create_kmv_chart(rec):
    """Build KMV asset value simulation chart for one ticker. Returns fig."""
    ticker, name = rec["ticker"], rec["name"]
    V0_m  = rec["V"]    / 1e9
    D_m   = rec["D"]    / 1e9
    mu    = rec["mu"]
    sv    = rec["sigma_V"]
    dd    = rec["dd"]
    pd_v  = rec["pd"]
    T_d   = 252          # trading days
    N     = T_d

    # GBM simulation
    path, expected, upper, lower = simulate_gbm(V0_m, mu, sv, N)
    t_arr = np.arange(N + 1) * (1.0 / N)

    # Horizon distribution
    y_range, pdf, mean_VT, std_VT = compute_horizon_dist(V0_m, D_m, mu, sv)
    max_pdf = max(pdf.max(), 1e-20)

    # Distribution x-coords: T_d + scaled PDF (30 % of time axis)
    x_dist = T_d + pdf / max_pdf * (T_d * 0.30)

    # EDF polygon: y ≤ D_m
    edf_mask = y_range <= D_m

    # ── Build figure ─────────────────────────────────────────
    fig = go.Figure()

    # 1) ±1σ band (upper filled to lower)
    fig.add_trace(go.Scatter(
        x=list(range(N + 1)), y=upper,
        mode="lines", line=dict(width=0),
        showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=list(range(N + 1)), y=lower,
        mode="lines", line=dict(width=0),
        fill="tonexty",
        fillcolor="rgba(74,74,74,0.10)",
        name="±1σ Band", showlegend=True,
        hoverinfo="skip",
    ))

    # 2) Simulated GBM path
    fig.add_trace(go.Scatter(
        x=list(range(N + 1)), y=path,
        mode="lines",
        line=dict(color=BLUE_1, width=1.2),
        opacity=0.82,
        name="Simulated Asset Path",
    ))

    # 3) Expected value path
    fig.add_trace(go.Scatter(
        x=list(range(N + 1)), y=expected,
        mode="lines",
        line=dict(color=ORANGE_1, width=1.5, dash="dot"),
        name="Expected Asset Value E[V]",
    ))

    # 4) Default point line (extends across full chart)
    fig.add_trace(go.Scatter(
        x=[0, int(T_d * 1.28)],
        y=[D_m, D_m],
        mode="lines",
        line=dict(color=ORANGE_2, width=2),
        name=f"Default Point D = {D_m:.2f} Bn",
    ))

    # 5) Distribution curve (sideways)
    fig.add_trace(go.Scatter(
        x=x_dist, y=y_range,
        mode="lines",
        line=dict(color="black", width=1.5),
        name="Asset Value Distribution",
    ))

    # 6) EDF fill polygon (below default point)
    if edf_mask.any() and max_pdf > 1e-20 and D_m > y_range[0]:
        y_edf   = y_range[edf_mask]
        p_edf   = pdf[edf_mask]
        x_curve = T_d + p_edf / max_pdf * (T_d * 0.30)
        # Polygon: distribution curve → left vertical → close
        x_poly = np.concatenate([x_curve, [T_d, T_d]])
        y_poly = np.concatenate([y_edf,   [y_edf[-1], y_edf[0]]])
        fig.add_trace(go.Scatter(
            x=x_poly, y=y_poly,
            fill="toself",
            fillcolor="rgba(192,57,43,0.45)",
            line=dict(color=ORANGE_2, width=0.8),
            name=f"EDF = {pd_v:.4%}",
            showlegend=True,
        ))

    # ── Annotations ──────────────────────────────────────────
    mid_dd_y = (D_m + mean_VT) / 2

    # DD double arrow at x=T_d
    for y_head, y_tail in [(mean_VT, D_m), (D_m, mean_VT)]:
        fig.add_annotation(
            x=T_d, y=y_head, ax=T_d, ay=y_tail,
            xref="x", yref="y", axref="x", ayref="y",
            arrowhead=2, arrowsize=1.2, arrowwidth=1.5, arrowcolor=BLUE_1,
            text="", showarrow=True,
        )
    fig.add_annotation(
        x=T_d + 4, y=mid_dd_y,
        text=f"DD = {dd:.2f}σ",
        showarrow=False, font=dict(size=11, color=BLUE_1),
        xanchor="left",
        bgcolor="rgba(255,255,255,0.75)",
    )

    # σ_V double arrow in distribution panel
    x_sv = T_d + T_d * 0.20
    for y_head, y_tail in [
        (mean_VT + std_VT, mean_VT),
        (mean_VT, mean_VT + std_VT),
    ]:
        fig.add_annotation(
            x=x_sv, y=y_head, ax=x_sv, ay=y_tail,
            xref="x", yref="y", axref="x", ayref="y",
            arrowhead=2, arrowsize=1.0, arrowwidth=1.5, arrowcolor=GRAY_1,
            text="", showarrow=True,
        )
    fig.add_annotation(
        x=x_sv + 3, y=mean_VT + std_VT * 0.5,
        text="③ σ_V<br>(1 Std Dev)",
        showarrow=False, font=dict(size=9, color=GRAY_1),
        xanchor="left",
        bgcolor="rgba(255,255,255,0.65)",
    )

    # ① V₀ label (left)
    fig.add_annotation(
        x=4, y=V0_m,
        text=f"① V₀ = {V0_m:.1f} Bn",
        showarrow=False, font=dict(size=10, color=TEXT),
        xanchor="left", yanchor="middle",
        bgcolor="rgba(255,255,255,0.80)",
    )

    # ② Distribution title (right panel top)
    fig.add_annotation(
        x=T_d + T_d * 0.15,
        y=y_range[-1],
        text="② Distribution of asset<br>value at horizon",
        showarrow=False, font=dict(size=9, color=TEXT),
        xanchor="center", yanchor="bottom",
    )

    # ④ Default Point label (left)
    fig.add_annotation(
        x=4, y=D_m,
        text=f"④ Default Point = {D_m:.2f} Bn",
        showarrow=False, font=dict(size=10, color=ORANGE_2),
        xanchor="left", yanchor="top",
        bgcolor="rgba(255,255,255,0.80)",
    )

    # ⑤ Expected Growth Path label (middle of path)
    mid_t = 115
    mid_ev = float(V0_m * np.exp(mu * (mid_t / N)))
    fig.add_annotation(
        x=mid_t, y=mid_ev,
        text="⑤ Expected Growth Path",
        showarrow=True, arrowhead=2,
        ax=18, ay=-26,
        font=dict(size=9, color=ORANGE_1),
        bgcolor="rgba(255,255,255,0.70)",
    )

    # ⑥ H = 1 Year axis marker
    fig.add_annotation(
        x=T_d, y=y_range[0],
        text="⑥ H = 1 Year",
        showarrow=False, font=dict(size=9, color=TEXT),
        xanchor="center", yanchor="top",
        yshift=-6,
    )

    # EDF label (only if visible)
    if pd_v > 1e-7:
        fig.add_annotation(
            x=T_d + T_d * 0.04,
            y=D_m * 0.97,
            text=f"EDF = {pd_v:.4%}",
            showarrow=False, font=dict(size=11, color=ORANGE_2, family="Inter, Arial"),
            xanchor="left", yanchor="top",
            bgcolor="rgba(255,255,255,0.80)",
        )

    # Vertical separator line at T_d
    fig.add_vline(
        x=T_d, line_dash="dot", line_color=BORDER, line_width=1.0,
    )

    # ── Layout ───────────────────────────────────────────────
    fig.update_layout(**LAYOUT)
    fig.update_layout(
        title=dict(
            text=(f"{name} ({ticker}) — KMV Asset Value Simulation<br>"
                  f"<sup>DD = {dd:.3f}σ &nbsp;|&nbsp; EDF = {pd_v:.4%} &nbsp;|&nbsp; σ_V = {sv:.1%}</sup>"),
            font=dict(size=15, color="#0B1220"), x=0.0,
        ),
        height=500,
        margin=dict(l=65, r=20, t=85, b=95),
        xaxis=dict(
            range=[0, T_d * 1.30],
            title="Time (Trading Days)",
            tickvals=[0, 63, 126, 189, 252],
            ticktext=["0", "63", "126", "189", "252 (H)"],
            showgrid=False, showline=True, linecolor=BORDER,
        ),
        yaxis=dict(
            range=[
                min(D_m * 0.5, float(path.min()) * 0.85, float(lower.min()) * 0.85),
                max(float(expected.max()) * 1.15, float(upper.max()) * 1.10, float(y_range.max()) * 1.05),
            ],
            title="Market Value of Assets (Bn USD)",
            showgrid=False, showline=True, linecolor=BORDER,
        ),
        legend=dict(
            orientation="h", bgcolor="rgba(0,0,0,0)", borderwidth=0,
            x=0, y=-0.22, font=dict(size=10),
        ),
        showlegend=True,
    )
    return fig


# ── Create and save charts for all tickers ────────────
print()
figs = {}
for rec in all_results:
    tkr = rec["ticker"]
    print(f"  Creating chart: {tkr} ...", end=" ")
    fig = create_kmv_chart(rec)
    figs[tkr] = fig

    _tkr_out = os.path.join(r"C:\Python\Outputs\Reports\DCF_Merton_MC", tkr)
    os.makedirs(_tkr_out, exist_ok=True)
    html_path = os.path.join(_tkr_out, f"{tkr}_KMV_AssetPath_{TODAY}.html")
    fig.write_html(html_path)
    png_path = os.path.join(_tkr_out, f"{tkr}_KMV_AssetPath_{TODAY}.png")
    fig.write_image(png_path, width=1200, height=700, scale=2)
    print(f"saved: {os.path.basename(png_path)}")

# endregion


# region Block 5 - HTML Summary (all 5 tickers)
# ─────────────────────────────────────────────────────────────
# Collects all 5 Plotly charts in a single HTML page.
# Layout: 2 charts per row, summary box below each chart.
# ─────────────────────────────────────────────────────────────

_CSS_KMV = """
    *, *::before, *::after { box-sizing: border-box; }
    body {
        font-family: 'Inter', sans-serif;
        background: #FFFFFF;
        color: #1A1A1A;
        margin: 0;
        line-height: 1.5;
    }
    .navbar {
        background: #0B1220;
        padding: 16px 40px;
        display: flex;
        align-items: center;
        gap: 16px;
    }
    .navbar-title { font-size: 18px; font-weight: 700; color: #FFFFFF; margin: 0; }
    .navbar-sub   { font-size: 13px; color: rgba(255,255,255,0.55); margin-left: auto; }
    .container    { max-width: 1400px; margin: 0 auto; padding: 36px 40px; }
    .page-title   {
        font-size: 20px; font-weight: 700; color: #1D6FD8;
        border-bottom: 2px solid #E5E5E5;
        padding-bottom: 10px; margin-bottom: 28px;
    }
    .charts-grid  { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
    .chart-card   {
        border: 1px solid #E5E5E5;
        border-radius: 8px;
        background: #FFFFFF;
        overflow: hidden;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .chart-inner  { padding: 8px; }
    .summary-box  {
        display: flex; flex-wrap: wrap; gap: 10px 20px;
        padding: 10px 16px;
        background: #F1F5F9;
        border-top: 1px solid #E5E5E5;
        font-size: 12px;
    }
    .summary-box b { color: #1D6FD8; }
    .explanation  {
        margin-top: 36px;
        padding: 18px 22px;
        background: #F8F9FA;
        border-left: 4px solid #1D6FD8;
        border-radius: 4px;
        font-size: 13px;
        color: #4A4A4A;
        line-height: 1.7;
    }
    .footer {
        background: #F1F5F9;
        padding: 14px 40px;
        text-align: center;
        font-size: 12px;
        color: #888888;
        border-top: 1px solid #E5E5E5;
    }
    @media (max-width: 900px) { .charts-grid { grid-template-columns: 1fr; } }
"""


def create_html_summary(all_results, figs):
    """Assemble HTML page with all 5 KMV charts and summary boxes."""
    # Chart cards
    cards_html = ""
    for rec in all_results:
        tkr     = rec["ticker"]
        fig     = figs.get(tkr)
        if fig is None:
            continue
        chart_h = fig.to_html(full_html=False, include_plotlyjs=False)

        box_html = (
            '<div class="summary-box">'
            f'<span><b>V₀:</b> {rec["V"]/1e9:.1f} Bn</span>'
            f'<span><b>D:</b> {rec["D"]/1e9:.2f} Bn</span>'
            f'<span><b>DD:</b> {rec["dd"]:.3f}σ</span>'
            f'<span><b>EDF:</b> {rec["pd"]:.4%}</span>'
            f'<span><b>σ_V:</b> {rec["sigma_V"]:.1%}</span>'
            f'<span><b>σ_E:</b> {rec["sigma_E"]:.1%}</span>'
            f'<span><b>Rating:</b> {rec["rating"]}</span>'
            '</div>'
        )
        cards_html += (
            '<div class="chart-card">'
            '<div class="chart-inner">' + chart_h + '</div>'
            + box_html +
            '</div>\n'
        )

    explanation = (
        '<div class="explanation">'
        '<strong>Model Notes:</strong><br>'
        'The simulated paths follow Geometric Brownian Motion (GBM). '
        'The default point represents total debt (D). '
        'Distance to Default (DD) measures standard deviations '
        'between expected asset value and default point at horizon T = 1Y. '
        'EDF (Expected Default Frequency) equals the shaded area '
        'below the default point in the asset value distribution. '
        'σ_V is iterated from equity volatility σ_E via the Merton (1974) '
        'Black-Scholes framework. The ±1σ band reflects '
        'V₀ · exp((μ ± σ_V) · t).'
        '</div>'
    )

    head = (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>KMV Asset Value Simulation — {date.today()}</title>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">\n'
        '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>\n'
        '<style>' + _CSS_KMV + '</style>\n'
        '</head>\n'
    )

    body = (
        '<body>\n'
        '<nav class="navbar">\n'
        '  <span class="navbar-title">KMV Asset Value Simulation</span>\n'
        f'  <span class="navbar-sub">{date.today()} &nbsp;|&nbsp; '
        'Merton Structural Model &nbsp;|&nbsp; GBM Simulation</span>\n'
        '</nav>\n'
        '<div class="container">\n'
        '  <div class="page-title">KMV Asset Value Simulation — 5 Semiconductor Companies</div>\n'
        '  <div class="charts-grid">\n'
        + cards_html +
        '  </div>\n'
        + explanation +
        '</div>\n'
        f'<div class="footer">Generated: {date.today()} &nbsp;|&nbsp; '
        'KMV / Merton Structural Credit Risk Model &nbsp;|&nbsp; '
        'Data: Financial Modeling Prep API</div>\n'
        '</body>\n</html>'
    )

    return head + body


print("\nGenerating HTML Summary Report ...")
html_content = create_html_summary(all_results, figs)
html_path = os.path.join(OUTPUT_DIR, f"KMV_Report_{date.today()}.html")
with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

webbrowser.open(html_path)
print(f"KMV Report opened: {html_path}")

print(f"\n{'='*60}")
print(f"Done. Outputs: {OUTPUT_DIR}")
print(f"{'='*60}")

# endregion


# region Interpretation
print("\n=== Interpretation ===")

for rec in sorted(all_results, key=lambda x: x["dd"]):
    print(
        f">>> {rec['ticker']}: V={rec['V']/1e9:.1f} Bn, "
        f"D={rec['D']/1e9:.2f} Bn, "
        f"DD={rec['dd']:.3f}σ, "
        f"EDF={rec['pd']:.4%}, "
        f"σ_V={rec['sigma_V']:.1%}"
    )

if all_results:
    riskiest   = min(all_results, key=lambda x: x["dd"])
    safest     = max(all_results, key=lambda x: x["dd"])
    high_vol   = max(all_results, key=lambda x: x["sigma_V"])
    print(f"\n>>> Highest risk: {riskiest['ticker']} (DD={riskiest['dd']:.3f}σ) — "
          f"simulation shows a path close to the default point.")
    print(f">>> Lowest risk: {safest['ticker']} (DD={safest['dd']:.3f}σ) — "
          f"default point well below the asset value path.")
    print(f">>> Highest asset volatility: {high_vol['ticker']} (σ_V={high_vol['sigma_V']:.1%}) — "
          f"wide confidence band in the GBM chart.")
# endregion


# region Legende
print("\n=== Legende ===")
print("V0      = Current market value of assets (Merton-iterated, in Bn USD)")
print("D       = Default point = total debt (Total Debt)")
print("sigma_V = Asset volatility (annualized, Merton-iterated from σ_E)")
print("sigma_E = Equity volatility (annualized, from historical stock prices)")
print("mu      = Expected asset drift = risk-free rate (risk-neutral)")
print("GBM     = Geometric Brownian Motion")
print("        V_{t+dt} = V_t * exp((mu - 0.5*sigma_V²)*dt + sigma_V*sqrt(dt)*Z)")
print("E[V_t]  = V0 * exp(mu * t)  — expected asset value at time t")
print("±1σ     = V0 * exp((mu ± sigma_V) * t)  — confidence band")
print("DD      = Distance to Default in standard deviations at horizon T")
print("EDF     = Expected Default Frequency = N(-DD) = Merton PD")
print("KMV     = Kealhofer, McQuown, Vasicek (Moody's Analytics, 1993)")
print("T       = Time horizon = 1 year = 252 trading days")
print("LGD     = Loss Given Default = 45% (assumption, ISDA standard)")
# endregion
