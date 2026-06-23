"""
DCF_Report — HTML Valuation Report (DCF Model)
================================================
Run with: python DCF/DCF_Report.py

  Block 0: Imports & Setup
  Block 1: All Calculations (FMP → WACC → DCF → Sensitivity → MC)
  Block 2: Create Charts (FCF, Waterfall, Heatmap, MC Histogram)
  Block 3: Generate and Open HTML Report
"""

# ─────────────────────────────────────────────────────────────
ACTIVE_CONFIG = "MCHP"  # Change ticker: MCHP | INTC | ON | QCOM | MPWR
# ─────────────────────────────────────────────────────────────

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

warnings.filterwarnings("ignore")

debug = False

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

config            = importlib.import_module(f"Config.{ACTIVE_CONFIG}")
TICKER            = config.TICKER
COMPANY       = config.COMPANY
RISK_FREE_RATE = config.RISK_FREE_RATE
WACC_CONFIG       = config.WACC_MEAN
TERMINAL_GROWTH   = config.TERMINAL_GROWTH
FORECAST_YEARS     = config.FORECAST_YEARS
SIMULATIONS      = getattr(config, "SIMULATIONS",  10000)
WACC_STD          = getattr(config, "WACC_STD",      0.015)
GROWTH_STD      = getattr(config, "GROWTH_STD",  0.020)

CACHE_FOLDER  = r"C:\Python\Data\FMP\FMP_Cache"
OUTPUT_DIR    = r"C:\Python\Outputs\Visualisierung"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Design tokens — imported directly from plot_style.py (central color palette)
from plot_style import BLUE_1, BLUE_2, ORANGE_1, ORANGE_2, GRAY_1, TEXT, BG
BORDER     = "#E5E5E5"
TEXT_MUTED = "#888888"

# endregion


# region Block 1 - All Calculations


def _load_json(filename):
    with open(os.path.join(CACHE_FOLDER, filename), "r", encoding="utf-8") as f:
        return json.load(f)


def _load_prices(filename):
    raw = _load_json(filename)
    df  = pd.DataFrame(raw)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").set_index("date")["close"]


print(f"Calculating DCF Report — {TICKER} ({COMPANY}) ...")

# ── 1a: Load FMP cache ──────────────────────────────────────
km         = _load_json(f"{TICKER}_key-metrics.json")[0]
cf_list    = _load_json(f"{TICKER}_cash-flow-statement.json")[:5]
inc_list   = _load_json(f"{TICKER}_income-statement.json")[:5]
bs         = _load_json(f"{TICKER}_balance-sheet-statement.json")[0]

fcf        = [float(e.get("freeCashFlow",       0) or 0) for e in cf_list]
cf_dates   = [e.get("date", "") for e in cf_list]

market_cap = float(km.get("marketCap",                0) or 0)
total_debt = float(bs.get("totalDebt",                0) or 0)
cash       = float(bs.get("cashAndCashEquivalents",   0) or 0)

ev       = market_cap + total_debt - cash
net_debt = total_debt - cash

# ── 1b: WACC via CAPM ────────────────────────────────────────
prices_ticker = _load_prices(f"{TICKER}_historical-price-eod_full.json")
sp500         = _load_prices("SP500_historical-price-eod_full.json")

ret_stk = np.log(prices_ticker / prices_ticker.shift(1)).dropna()
ret_mkt = np.log(sp500 / sp500.shift(1)).dropna()
common  = ret_stk.index.intersection(ret_mkt.index)[-252:]
rs, rm  = ret_stk.loc[common].values, ret_mkt.loc[common].values
cov_mat = np.cov(rs, rm)
beta    = cov_mat[0, 1] / cov_mat[1, 1]
ke      = RISK_FREE_RATE + beta * 0.055

kd = 0.0
for entry in inc_list:
    i_exp = float(entry.get("interestExpense", 0) or 0)
    if i_exp > 0 and total_debt > 0:
        kd = i_exp / total_debt
        break

tax_rates = [
    float(e.get("incomeTaxExpense", 0) or 0) / float(e.get("incomeBeforeTax", 1) or 1)
    for e in inc_list
    if float(e.get("incomeBeforeTax", 0) or 0) > 0
    and float(e.get("incomeTaxExpense", 0) or 0) > 0
]
tax_rate     = float(np.mean(tax_rates)) if tax_rates else 0.21
kd_after_tax = kd * (1 - tax_rate)

V    = market_cap + total_debt
wacc = ke * (market_cap / V) + kd_after_tax * (total_debt / V)

# ── 1c: DCF Base Case ────────────────────────────────────────
fcf_norm           = float(np.median(fcf))
g1                 = getattr(config, "GROWTH_MEAN", 0.05)
g2                 = TERMINAL_GROWTH
current_price       = float(prices_ticker.iloc[-1])
shares_outstanding = market_cap / current_price

fcf_cagr = ((fcf[0] / fcf[4]) ** (1 / 4) - 1
            if fcf[4] != 0 and (fcf[0] / fcf[4]) > 0
            else float("nan"))

fcf_prognose = []
fcf_t = fcf_norm
for t in range(1, FORECAST_YEARS + 1):
    fcf_t = fcf_t * (1 + g1)
    fcf_prognose.append({"Year": t, "FCF": fcf_t, "PV_FCF": fcf_t / (1 + wacc) ** t})

tv         = fcf_prognose[-1]["FCF"] * (1 + g2) / (wacc - g2)
pv_tv      = tv / (1 + wacc) ** FORECAST_YEARS
pv_fcf_sum = sum(d["PV_FCF"] for d in fcf_prognose)
ev_dcf     = pv_fcf_sum + pv_tv
tv_anteil  = pv_tv / ev_dcf if ev_dcf > 0 else 0

equity_value     = ev_dcf - net_debt
equity_per_share = equity_value / shares_outstanding
upside           = (equity_per_share / current_price - 1) * 100
valuation        = ("UNDERVALUED" if upside > 10
                    else "OVERVALUED" if upside < -10
                    else "FAIR VALUED")

# ── 1d: Sensitivity matrix ──────────────────────────────────
WACC_RANGE = [0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14]
G1_RANGE   = [0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]


def _dcf_eps(w, gp1):
    if w <= g2:
        return float("nan")
    f_t = fcf_norm
    pv  = 0.0
    for t in range(1, FORECAST_YEARS + 1):
        f_t  = f_t * (1 + gp1)
        pv  += f_t / (1 + w) ** t
    return (pv + f_t * (1 + g2) / (w - g2) / (1 + w) ** FORECAST_YEARS - net_debt) / shares_outstanding


matrix   = [[_dcf_eps(w, g) for g in G1_RANGE] for w in WACC_RANGE]
x_labels = [f"{g:.0%}" for g in G1_RANGE]
y_labels = [f"{w:.0%}" for w in WACC_RANGE]

fair_combos = [
    (w, g, matrix[i][j])
    for i, w in enumerate(WACC_RANGE)
    for j, g in enumerate(G1_RANGE)
    if not np.isnan(matrix[i][j]) and abs(matrix[i][j] / current_price - 1) < 0.05
]
wacc_idx = int(np.argmin([abs(w - wacc) for w in WACC_RANGE]))
g1_idx   = int(np.argmin([abs(g - g1)   for g  in G1_RANGE]))

# ── 1e: Monte Carlo ──────────────────────────────────────────
FCF_STD_FACTOR = 0.15
np.random.seed(42)
wacc_sim = np.clip(np.random.normal(wacc,     WACC_STD,                  SIMULATIONS), 0.04, None)
g1_sim   = np.clip(np.random.normal(g1,       GROWTH_STD,              SIMULATIONS), 0.00, None)
fcf0_sim =         np.random.normal(fcf_norm, fcf_norm * FCF_STD_FACTOR, SIMULATIONS)


def _mc_dcf(ws, gs, f0):
    if ws <= g2:
        return float("nan")
    f_t = f0
    pv  = 0.0
    for t in range(1, FORECAST_YEARS + 1):
        f_t  = f_t * (1 + gs)
        pv  += f_t / (1 + ws) ** t
    return (pv + f_t * (1 + g2) / (ws - g2) / (1 + ws) ** FORECAST_YEARS - net_debt) / shares_outstanding


mc_raw     = np.array([_mc_dcf(w, g, f) for w, g, f in zip(wacc_sim, g1_sim, fcf0_sim)])
mc_results = mc_raw[~np.isnan(mc_raw)]
mc_mean    = float(np.mean(mc_results))
mc_median  = float(np.median(mc_results))
mc_std     = float(np.std(mc_results))
mc_p10     = float(np.percentile(mc_results, 10))
mc_p25     = float(np.percentile(mc_results, 25))
mc_p75     = float(np.percentile(mc_results, 75))
mc_p90     = float(np.percentile(mc_results, 90))
p_undervalued    = float(np.mean(mc_results > current_price))

print("  Calculations complete.")

# endregion


# region Block 2 - Create Charts

_CONF   = dict(displayModeBar=True, displaylogo=False,
               modeBarButtonsToRemove=["lasso2d", "select2d"])
_LAYOUT = dict(paper_bgcolor=BG, plot_bgcolor=BG, template="plotly_white",
               font=dict(color=TEXT, size=11))


def _html(fig):
    return fig.to_html(full_html=False, include_plotlyjs=False, config=_CONF)


# ── Chart 1: FCF trend (bar chart) ────────────────────
_yr   = list(reversed(cf_dates))
_fv   = [v / 1e9 for v in reversed(fcf)]
_col  = [BLUE_2 if v >= 0 else ORANGE_2 for v in _fv]

fig1 = go.Figure()
fig1.add_trace(go.Bar(
    x=_yr, y=_fv,
    marker_color=_col, marker_line_width=0, opacity=0.85,
    name="FCF",
    text=[f"{v:.2f}" for v in _fv],
    textposition="outside", textfont=dict(size=10),
))
fig1.add_hline(
    y=fcf_norm / 1e9, line_dash="dash", line_color=BLUE_1, line_width=1.8,
    annotation_text=f"Median {fcf_norm/1e9:.2f} Bn",
    annotation_position="top left",
    annotation_font=dict(size=10, color=BLUE_1),
)
fig1.update_layout(
    **_LAYOUT,
    title=dict(text=f"Free Cash Flow — {TICKER} (5 Years)", font=dict(size=14, color=TEXT)),
    xaxis=dict(title="Fiscal Year", showgrid=False),
    yaxis=dict(title="FCF (Bn USD)", showgrid=True, gridcolor=BORDER,
               zeroline=True, zerolinecolor=BORDER),
    height=380, margin=dict(l=60, r=40, t=70, b=50),
    showlegend=False,
)
chart1_html = _html(fig1)
print("  Chart 1 (FCF) ready.")

# ── Chart 2: DCF Waterfall ───────────────────────────────────
_wf_y_fcf = [d["PV_FCF"] / 1e9 for d in fcf_prognose]
_wf_y_tv  = [pv_tv / 1e9]

fig2 = go.Figure()
fig2.add_trace(go.Bar(
    x=[f"PV J{d['Year']}" for d in fcf_prognose],
    y=_wf_y_fcf,
    marker_color=BLUE_1, marker_opacity=0.85, marker_line_width=0,
    name="PV FCF",
    text=[f"{v:.2f}" for v in _wf_y_fcf],
    textposition="outside", textfont=dict(size=10),
))
fig2.add_trace(go.Bar(
    x=["PV TV"],
    y=_wf_y_tv,
    marker_color=ORANGE_1, marker_opacity=0.85, marker_line_width=0,
    name="PV Terminal Value",
    text=[f"{pv_tv/1e9:.2f}"],
    textposition="outside", textfont=dict(size=10),
))
fig2.add_hline(
    y=ev / 1e9, line_dash="dash", line_color=ORANGE_2, line_width=2,
    annotation_text=f"EV Market {ev/1e9:.1f} Bn",
    annotation_position="top right",
    annotation_font=dict(size=10, color=ORANGE_2),
)
fig2.add_hline(
    y=ev_dcf / 1e9, line_dash="dot", line_color=TEXT_MUTED, line_width=1.5,
    annotation_text=f"EV DCF {ev_dcf/1e9:.1f} Bn",
    annotation_position="bottom right",
    annotation_font=dict(size=10, color=TEXT_MUTED),
)
fig2.update_layout(
    **_LAYOUT,
    title=dict(
        text=(f"DCF Waterfall — {TICKER}<br>"
              f"<sup>PV FCF (blue) + PV Terminal Value (orange) = EV DCF {ev_dcf/1e9:.1f} Bn</sup>"),
        font=dict(size=14, color=TEXT),
    ),
    xaxis=dict(showgrid=False, linecolor=BORDER),
    yaxis=dict(title="Bn USD", showgrid=True, gridcolor=BORDER),
    height=380,
    margin=dict(l=60, r=140, t=90, b=50),
    legend=dict(bgcolor=BG, bordercolor=BORDER, borderwidth=1,
                orientation="h", x=0, y=-0.12),
)
chart2_html = _html(fig2)
print("  Chart 2 (Waterfall) ready.")

# ── Chart 3: Sensitivity heatmap ──────────────────────────
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

fig3 = go.Figure()
fig3.add_trace(go.Heatmap(
    z=matrix, x=x_labels, y=y_labels,
    text=text_matrix, texttemplate="%{text}",
    textfont=dict(size=10, color="#1A1A1A"),
    colorscale=[[0, ORANGE_2], [0.5, "#F1F5F9"], [1.0, BLUE_2]],
    zmid=current_price,
    colorbar=dict(title=dict(text="USD/Share", side="right"), thickness=14),
    hovertemplate="WACC: %{y}<br>Growth: %{x}<br>Value: %{z:.2f} USD<extra></extra>",
))
fig3.add_trace(go.Contour(
    z=matrix, x=x_labels, y=y_labels,
    contours=dict(coloring="none", start=current_price - 5, end=current_price + 5, size=10.01),
    line=dict(color="black", width=2.5, dash="dash"),
    showscale=False, name=f"≈ Price {current_price:.0f} USD",
))
fig3.add_trace(go.Scatter(
    x=[x_labels[g1_idx]], y=[y_labels[wacc_idx]],
    mode="markers",
    marker=dict(color="rgba(0,0,0,0)", size=26, symbol="circle",
                line=dict(color="black", width=3)),
    name=f"Current (WACC≈{wacc:.1%}, g={g1:.0%})",
))
fig3.update_layout(
    **_LAYOUT,
    title=dict(
        text=(f"{COMPANY} — DCF Sensitivity WACC × Growth<br>"
              f"<sup>Intrinsic Value/Share (USD) | Price: {current_price:.2f} USD | "
              f"↑ UNDER · ↓ OVER · ≈ FAIR (±10%)</sup>"),
        font=dict(size=14, color=TEXT),
    ),
    xaxis=dict(title="Growth Phase 1 (g1)"),
    yaxis=dict(title="WACC", autorange="reversed"),
    height=460,
    margin=dict(l=70, r=160, t=100, b=60),
    legend=dict(bgcolor=BG, bordercolor=BORDER, borderwidth=1, x=1.12, y=0.5),
)
chart3_html = _html(fig3)
print("  Chart 3 (Heatmap) ready.")

# ── Chart 4: Monte Carlo histogram ─────────────────────────
x_lo  = float(np.percentile(mc_results, 0.5))
x_hi  = float(np.percentile(mc_results, 99.5))
bsize = (x_hi - x_lo) / 60

fig4 = go.Figure()
fig4.add_trace(go.Histogram(
    x=mc_results[mc_results < current_price],
    autobinx=False,
    xbins=dict(start=x_lo, end=current_price + bsize, size=bsize),
    marker=dict(color=ORANGE_2,  line=dict(color=ORANGE_2,  width=0.4)),
    opacity=0.78, name=f"Overvalued (<{current_price:.0f} USD)",
))
fig4.add_trace(go.Histogram(
    x=mc_results[mc_results >= current_price],
    autobinx=False,
    xbins=dict(start=current_price, end=x_hi + bsize, size=bsize),
    marker=dict(color=BLUE_2, line=dict(color=BLUE_2, width=0.4)),
    opacity=0.78, name=f"Undervalued (≥{current_price:.0f} USD)",
))
for x_val, label, col, dash, ypos in [
    (current_price, f"Price {current_price:.0f}",  ORANGE_2,  "solid", 0.97),
    (mc_median,    f"Median {mc_median:.0f}",    BLUE_1, "solid", 0.88),
    (mc_p10,       f"P10 {mc_p10:.0f}",          GRAY_1, "dot",   0.97),
    (mc_p90,       f"P90 {mc_p90:.0f}",          GRAY_1, "dot",   0.88),
]:
    fig4.add_vline(x=x_val, line_dash=dash, line_color=col, line_width=2)
    fig4.add_annotation(
        x=x_val, y=ypos, yref="paper",
        text=label, showarrow=False,
        font=dict(color=col, size=9),
        xanchor="center", yanchor="bottom",
        bgcolor="rgba(255,255,255,0.75)", borderpad=2,
    )
fig4.update_layout(
    **_LAYOUT,
    title=dict(
        text=(f"{COMPANY} — Monte Carlo DCF ({SIMULATIONS:,} Simulations)<br>"
              f"<sup>WACC σ={WACC_STD:.1%} | Growth σ={GROWTH_STD:.1%} | "
              f"FCF σ={FCF_STD_FACTOR:.0%} | P(Undervalued)={p_undervalued:.1%}</sup>"),
        font=dict(size=14, color=TEXT),
    ),
    barmode="overlay",
    xaxis=dict(title="Intrinsic Value/Share (USD)", range=[x_lo, x_hi]),
    yaxis=dict(title="Frequency"),
    height=440,
    margin=dict(l=65, r=40, t=100, b=60),
    legend=dict(bgcolor=BG, bordercolor=BORDER, borderwidth=1,
                x=0.01, y=0.99, xanchor="left", yanchor="top"),
)
chart4_html = _html(fig4)
print("  Chart 4 (Monte Carlo) ready.")

# endregion


# region Block 3 - Generate HTML Report

_CSS = """
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
        gap: 20px;
    }
    .navbar-title { font-size: 18px; font-weight: 700; color: #FFFFFF; margin: 0; }
    .navbar-sub   { font-size: 13px; color: rgba(255,255,255,0.55); margin-left: auto; }
    .container    { max-width: 1400px; margin: 0 auto; padding: 36px 40px; }
    .section      { margin-bottom: 56px; }
    .section h2 {
        color: #1D6FD8;
        font-size: 17px;
        font-weight: 600;
        border-bottom: 2px solid #E5E5E5;
        padding-bottom: 10px;
        margin-top: 0;
        margin-bottom: 20px;
    }
    .kpi-grid { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
    .kpi-tile {
        border: 1px solid #E5E5E5;
        border-radius: 6px;
        padding: 18px 22px;
        min-width: 170px;
        flex: 1;
        background: #FFFFFF;
    }
    .kpi-label {
        font-size: 11px;
        color: #888888;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 8px;
    }
    .kpi-value          { font-size: 24px; font-weight: 700; color: #1A1A1A; }
    .kpi-value.positive { color: #1B4332; }
    .kpi-value.negative { color: #C0392B; }
    .kpi-value.neutral  { color: #1D6FD8; }
    .badge {
        display: inline-block;
        font-size: 13px;
        font-weight: 600;
        padding: 4px 12px;
        border-radius: 4px;
    }
    .badge-red   { background: #fdecea; color: #C0392B; }
    .badge-green { background: #e8f5e9; color: #1B4332; }
    .badge-blue  { background: #e8f0fd; color: #1D6FD8; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    thead th {
        background: #F1F5F9;
        color: #1A1A1A;
        font-weight: 600;
        padding: 10px 14px;
        text-align: right;
        border-bottom: 2px solid #E5E5E5;
        white-space: nowrap;
    }
    thead th:first-child { text-align: left; }
    tbody td {
        padding: 9px 14px;
        border-bottom: 1px solid #E5E5E5;
        text-align: right;
        white-space: nowrap;
    }
    tbody td:first-child { text-align: left; }
    tbody tr:hover { background: #f8fafc; }
    tbody tr.hl td { background: #eff6ff; font-weight: 600; }
    .chart-card {
        border: 1px solid #E5E5E5;
        border-radius: 6px;
        padding: 12px;
        background: #FFFFFF;
        overflow: hidden;
        margin-bottom: 20px;
    }
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
    .meta-row {
        display: flex;
        gap: 28px;
        font-size: 13px;
        color: #4A4A4A;
        margin-top: 12px;
        flex-wrap: wrap;
    }
    .meta-row span b { color: #1A1A1A; }
    .footnote { font-size: 12px; color: #888888; margin-top: 10px; font-style: italic; }
    .footer {
        background: #F1F5F9;
        padding: 14px 40px;
        text-align: center;
        font-size: 12px;
        color: #888888;
        border-top: 1px solid #E5E5E5;
    }
    @media (max-width: 900px) {
        .two-col { grid-template-columns: 1fr; }
        .kpi-tile { min-width: 140px; }
    }
"""

# ── Section 1: Executive Summary ─────────────────────────────
_up_cls  = "positive" if upside > 0 else "negative"
_bw_cls  = "badge-green" if upside > 10 else ("badge-red" if upside < -10 else "badge-blue")

s1_content = (
    '<div class="kpi-grid">\n'
    f'  <div class="kpi-tile"><div class="kpi-label">Intrinsic Value</div>'
    f'  <div class="kpi-value">{equity_per_share:.2f} USD</div></div>\n'
    f'  <div class="kpi-tile"><div class="kpi-label">Current Price</div>'
    f'  <div class="kpi-value neutral">{current_price:.2f} USD</div></div>\n'
    f'  <div class="kpi-tile"><div class="kpi-label">Upside / Downside</div>'
    f'  <div class="kpi-value {_up_cls}">{upside:+.1f}%</div></div>\n'
    f'  <div class="kpi-tile"><div class="kpi-label">Valuation</div>'
    f'  <div class="kpi-value"><span class="badge {_bw_cls}">{valuation}</span></div></div>\n'
    '</div>\n'
    '<div class="meta-row">'
    f'  <span>WACC: <b>{wacc:.2%}</b> (CAPM)</span>'
    f'  <span>Beta: <b>{beta:.2f}</b></span>'
    f'  <span>FCF norm.: <b>{fcf_norm/1e9:.2f} Bn USD</b></span>'
    f'  <span>TV share: <b>{tv_anteil:.0%}</b> of EV DCF</span>'
    f'  <span>EV DCF: <b>{ev_dcf/1e9:.1f} Bn</b> &nbsp;vs.&nbsp; EV Market: <b>{ev/1e9:.1f} Bn</b></span>'
    '</div>'
)

# ── Section 2: FCF Analysis ───────────────────────────────────
_cagr_str = f"{fcf_cagr:.1%}" if not np.isnan(fcf_cagr) else "n/a"
s2_content = (
    f'<div class="chart-card">{chart1_html}</div>\n'
    '<div class="meta-row">'
    f'  <span>FCF norm. (Median): <b>{fcf_norm/1e9:.2f} Bn USD</b></span>'
    f'  <span>FCF CAGR (5Y): <b>{_cagr_str}</b></span>'
    f'  <span>FCF Peak (5Y): <b>{max(fcf)/1e9:.2f} Bn USD</b></span>'
    f'  <span>FCF current: <b>{fcf[0]/1e9:.2f} Bn USD</b></span>'
    '</div>'
)

# ── Section 3: DCF Base Case ─────────────────────────────────
_prows = "".join(
    f'<tr><td>Year {d["Year"]}</td>'
    f'<td>{d["FCF"]/1e9:.3f}</td>'
    f'<td>{d["PV_FCF"]/1e9:.3f}</td></tr>\n'
    for d in fcf_prognose
)
_prows += (
    f'<tr class="hl"><td>Terminal Value</td><td>{tv/1e9:.2f}</td><td>{pv_tv/1e9:.2f}</td></tr>\n'
    f'<tr class="hl"><td><b>Total EV DCF</b></td><td>{ev_dcf/1e9:.2f}</td><td>{ev_dcf/1e9:.2f}</td></tr>\n'
)
_prog_table = (
    '<table>\n'
    '<thead><tr><th>Component</th><th>FCF (Bn USD)</th><th>PV FCF (Bn USD)</th></tr></thead>\n'
    f'<tbody>{_prows}</tbody>\n</table>\n'
    f'<p class="footnote">WACC: {wacc:.2%} &nbsp;|&nbsp; g1: {g1:.1%} &nbsp;|&nbsp; g2: {g2:.1%}'
    f' &nbsp;|&nbsp; Net Debt: {net_debt/1e9:.2f} Bn &nbsp;|&nbsp; '
    f'Equity Value: {equity_value/1e9:.2f} Bn &nbsp;|&nbsp; '
    f'Shares: {shares_outstanding/1e6:.1f} Mn</p>'
)
s3_content = (
    '<div class="two-col">'
    f'<div class="chart-card">{chart2_html}</div>'
    f'<div style="overflow-x:auto;padding-top:4px;">{_prog_table}</div>'
    '</div>'
)

# ── Section 4: Sensitivity Analysis ─────────────────────────
if fair_combos:
    _fc_rows = "".join(
        f'<tr><td>{w:.0%}</td><td>{g:.0%}</td>'
        f'<td style="color:{BLUE_2 if v > current_price else ORANGE_2}">{v:.2f}</td>'
        f'<td style="color:{BLUE_2 if v > current_price else ORANGE_2}">{(v/current_price-1)*100:+.1f}%</td></tr>\n'
        for w, g, v in fair_combos
    )
    _fc_block = (
        f'<p style="font-size:13px;color:{TEXT_MUTED};margin-top:16px;">'
        f'Fair value combinations (±5% around price {current_price:.2f} USD):</p>\n'
        '<table style="max-width:440px;">\n'
        '<thead><tr><th>WACC</th><th>Growth</th><th>Value (USD)</th><th>vs. Price</th></tr></thead>\n'
        f'<tbody>{_fc_rows}</tbody></table>'
    )
else:
    _diffs = sorted(
        [(abs(matrix[i][j] / current_price - 1), w, g, matrix[i][j])
         for i, w in enumerate(WACC_RANGE)
         for j, g in enumerate(G1_RANGE)
         if not np.isnan(matrix[i][j])]
    )
    _d0, _w0, _g0, _v0 = _diffs[0]
    _fc_block = (
        f'<p class="footnote">No fair value combination within ±5%. '
        f'Next closest: WACC={_w0:.0%}, Growth={_g0:.0%} → {_v0:.2f} USD ({_d0:.1%} dev.)</p>'
    )
s4_content = (
    f'<div class="chart-card">{chart3_html}</div>\n'
    f'{_fc_block}'
)

# ── Section 5: Monte Carlo ───────────────────────────────────
_mc_col = f'color:{BLUE_2}' if p_undervalued > 0.5 else f'color:{ORANGE_2}'
_mc_rows = (
    f'<tr><td>Mean</td><td>{mc_mean:.2f} USD</td></tr>\n'
    f'<tr><td>Median</td><td>{mc_median:.2f} USD</td></tr>\n'
    f'<tr><td>Std Dev</td><td>{mc_std:.2f} USD</td></tr>\n'
    f'<tr><td>P10 / P90</td><td>{mc_p10:.2f} / {mc_p90:.2f} USD</td></tr>\n'
    f'<tr><td>P25 / P75</td><td>{mc_p25:.2f} / {mc_p75:.2f} USD</td></tr>\n'
    f'<tr class="hl"><td>P(Undervalued)</td>'
    f'<td style="{_mc_col};font-weight:700;">{p_undervalued:.1%}</td></tr>\n'
    f'<tr><td>Current Price</td><td>{current_price:.2f} USD</td></tr>\n'
)
_mc_table = (
    '<table style="max-width:360px;">\n'
    '<thead><tr><th>Metric</th><th>Value</th></tr></thead>\n'
    f'<tbody>{_mc_rows}</tbody></table>\n'
    f'<p class="footnote">Seed 42 &nbsp;|&nbsp; {SIMULATIONS:,} Simulations &nbsp;|&nbsp; '
    f'WACC ~ N({wacc:.2%}, {WACC_STD:.1%}) &nbsp;|&nbsp; '
    f'g ~ N({g1:.1%}, {GROWTH_STD:.1%}) &nbsp;|&nbsp; '
    f'FCF ~ N(norm., ±{FCF_STD_FACTOR:.0%})</p>'
)
s5_content = (
    '<div class="two-col">'
    f'<div class="chart-card">{chart4_html}</div>'
    f'<div style="padding-top:4px;">{_mc_table}</div>'
    '</div>'
)

# ── Assemble HTML ─────────────────────────────────────────────
def _section(title, content):
    return (
        '<div class="section">\n'
        f'  <h2>{title}</h2>\n'
        f'  {content}\n'
        '</div>\n'
    )


html = (
    '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
    '<meta charset="UTF-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    f'<title>DCF Report — {TICKER} — {date.today()}</title>\n'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"'
    ' rel="stylesheet">\n'
    '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>\n'
    '<style>' + _CSS + '</style>\n'
    '</head>\n<body>\n'
    '<nav class="navbar">\n'
    f'  <span class="navbar-title">DCF Valuation Report — {COMPANY} ({TICKER})</span>\n'
    f'  <span class="navbar-sub">{date.today()} &nbsp;|&nbsp; Discounted Cash Flow Model</span>\n'
    '</nav>\n'
    '<div class="container">\n'
    + _section("DCF Valuation Summary", s1_content)
    + _section("Free Cash Flow Analysis", s2_content)
    + _section("DCF Base Case", s3_content)
    + _section("Sensitivity Analysis — WACC × Growth", s4_content)
    + _section("Monte Carlo Simulation", s5_content)
    + '</div>\n'
    f'<div class="footer">Generated: {date.today()} &nbsp;|&nbsp; '
    f'DCF Valuation Model &nbsp;|&nbsp; Data: Financial Modeling Prep API</div>\n'
    '</body>\n</html>'
)

html_path = os.path.join(OUTPUT_DIR, f"DCF_Report_{TICKER}_{date.today()}.html")
with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nDCF Report saved: {html_path}")
webbrowser.open(html_path)
print(f"DCF Report opened: {html_path}")

# endregion


# region Interpretation
print("\n=== Interpretation ===")
print(f">>> {TICKER}: Intrinsic value {equity_per_share:.2f} USD vs. price {current_price:.2f} USD — {valuation} ({upside:+.1f}%).")
if p_undervalued < 0.15:
    print(f">>> Monte Carlo: P(Undervalued)={p_undervalued:.1%} — DCF downside statistically robust across {SIMULATIONS:,} scenarios.")
elif p_undervalued > 0.60:
    print(f">>> Monte Carlo: P(Undervalued)={p_undervalued:.1%} — majority of scenarios signal upside.")
else:
    print(f">>> Monte Carlo: P(Undervalued)={p_undervalued:.1%} — mixed picture, significant parameter uncertainty.")
if fair_combos:
    _wf, _gf = fair_combos[0][0], fair_combos[0][1]
    print(f">>> {len(fair_combos)} fair value combination(s) (±5%); example: WACC={_wf:.0%}, g={_gf:.0%}.")
# endregion


# region Legende
print("\n=== Legende ===")
print("ACTIVE_CONFIG    = Ticker code for Config import (switchable above)")
print("chart1..4_html   = Plotly charts as HTML snippets (no standalone Plotly JS)")
print("_CONF            = Plotly displayModeBar configuration (no Plotly logo)")
print("_LAYOUT          = Shared Plotly layout parameters (bgcolor, template, font)")
print("fair_combos      = List of all (WACC, g1, value) combinations within ±5% of the price")
print("p_undervalued          = P(equity_per_share > current_price) across all MC simulations")
print("mc_results       = Cleaned MC outputs (NaN removed)")
print("FCF_STD_FACTOR   = Relative FCF uncertainty (±15%)")
print("html_path        = Output path of the HTML report")
print("_CSS             = Inline CSS of the report (Inter font, navbar, KPI tiles, tables)")
# endregion
