"""
Merton_Report — HTML Summary Report (all 5 tickers)
====================================================
Run with: python Merton/Merton_Report.py

  Block 0: Imports & Setup
  Block 1: Collect Data (all 5 tickers)
  Block 2: Generate HTML Report
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

TICKER_LIST   = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]
CACHE_FOLDER  = r"C:\Python\Data\FMP\FMP_Cache"
OUTPUT_DIR    = r"C:\Python\Outputs\Visualisierung"
NAVBAR_BG     = "#0B1220"
SIDEBAR_BG    = "#F1F5F9"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Design tokens — imported directly from plot_style.py (central color palette)
from plot_style import BLUE_1, BLUE_2, ORANGE_1, ORANGE_2, GRAY_1, TEXT, BG
BORDER     = "#E5E5E5"
TEXT_MUTED = "#888888"

# endregion


# region Block 1 - Collect Data (all 5 tickers)
# ─────────────────────────────────────────────────────────────
# Loads for each ticker: Merton base values, historical DD,
# stress test, sensitivity (σ_E ±30%), credit spread.
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
        d1     = (np.log(V / D) + (r + 0.5 * sigma_v ** 2) * T) / (sigma_v * sqrt_t)
        d2     = d1 - sigma_v * sqrt_t
        e_mod  = V * norm.cdf(d1) - D * np.exp(-r * T) * norm.cdf(d2)
        se_mod = (V / E) * norm.cdf(d1) * sigma_v
        v_new  = V * (E / e_mod)
        sv_new = sigma_e * (E / v_new)
        if abs(v_new - V) < tol and abs(sv_new - sigma_v) < tol:
            V, sigma_v = v_new, sv_new
            break
        V, sigma_v = v_new, sv_new
    sqrt_t = np.sqrt(T)
    dd     = (np.log(V / D) + (r - 0.5 * sigma_v ** 2) * T) / (sigma_v * sqrt_t)
    pd_val = float(norm.cdf(-dd))
    el     = pd_val * D * 0.45
    return {"V": V, "sigma_v": sigma_v, "dd": dd, "pd": pd_val, "el": el}


def calculate_historical_dd(prices, log_returns, total_debt, market_cap, r, T):
    """Rolling Merton DD sampled every 63 trading days over 5 years."""
    cutoff    = prices.index.max() - pd.DateOffset(years=5)
    prices_5y = prices[prices.index >= cutoff]
    shares    = market_cap / float(prices.iloc[-1])
    roll_sig  = log_returns.rolling(252).std() * np.sqrt(252)
    records   = []
    for i in range(0, len(prices_5y), 63):
        dt     = prices_5y.index[i]
        price  = float(prices_5y.iloc[i])
        sig_e  = float(roll_sig.get(dt, np.nan))
        mktcap = price * shares
        if np.isnan(sig_e) or sig_e <= 0 or mktcap <= 0 or total_debt <= 0:
            continue
        try:
            res = merton_model(mktcap, total_debt, r, T, sig_e)
            records.append({"Date": dt, "DD": res["dd"], "PD": res["pd"], "Price": price})
        except Exception:
            continue
    return pd.DataFrame(records).set_index("Date") if records else pd.DataFrame()


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


def calculate_spread(pd_val, T, lgd=0.45):
    pd_lgd = min(pd_val * lgd, 0.9999)
    if pd_lgd <= 0:
        return 0.0
    return -np.log(1 - pd_lgd) / T


def load_ticker_data(ticker):
    """Load prices, balance sheet, key metrics for one ticker from FMP cache."""
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
    return prices, log_ret, sigma_e, total_debt, market_cap


def collect_all_results():
    """Run Merton analysis for all tickers and return list of result dicts."""
    all_results = []
    for ticker_name in TICKER_LIST:
        print(f"  Loading {ticker_name} ...", end=" ")
        try:
            cfg  = importlib.import_module(f"Config.{ticker_name}")
            name = cfg.COMPANY
            r    = cfg.RISK_FREE_RATE
            T    = getattr(cfg, "MATURITY", 1)

            prices, log_ret, sigma_e, total_debt, market_cap = load_ticker_data(ticker_name)
            E = market_cap
            D = total_debt

            # Base Merton
            base = merton_model(E, D, r, T, sigma_e)

            # Historical DD (quarterly, 5 years)
            df_zt = calculate_historical_dd(prices, log_ret, total_debt, market_cap, r, T)

            # Stress Test
            bear = merton_model(E * 0.60, D * 1.10, r, T, sigma_e * 1.50)
            bull = merton_model(E * 1.25, D * 0.90, r, T, sigma_e * 0.80)
            stress = {"Bear": bear, "Base": base, "Bull": bull}

            # Sensitivity: σ_E ±30%
            dd_vol_low  = merton_model(E, D, r, T, sigma_e * 0.70)["dd"]
            dd_vol_high = merton_model(E, D, r, T, sigma_e * 1.30)["dd"]
            vol_impact  = abs(dd_vol_high - dd_vol_low)

            # Credit Spread
            base_bps  = calculate_spread(base["pd"], T) * 10000
            bear_bps  = calculate_spread(bear["pd"], T) * 10000
            rat, bps_lo, bps_hi = get_rating_info(base["dd"])
            puzzle_gap = bps_lo - bear_bps

            all_results.append({
                "ticker":         ticker_name,
                "name":           name,
                "dd":             base["dd"],
                "pd":             base["pd"],
                "sigma_v":        base["sigma_v"],
                "sigma_e":        sigma_e,
                "market_cap":     market_cap / 1e9,
                "debt":           total_debt / 1e9,
                "rating":         rat,
                "df_time_series": df_zt,
                "stress":         stress,
                "sens_vol_low":   dd_vol_low,
                "sens_vol_high":  dd_vol_high,
                "vol_impact":     vol_impact,
                "credit_base":    base_bps,
                "credit_bear":    bear_bps,
                "bench_lo":       bps_lo,
                "bench_hi":       bps_hi,
                "puzzle_gap":     puzzle_gap,
            })
            print(f"DD={base['dd']:.3f}  PD={base['pd']:.4%}")
        except Exception as e:
            print(f"ERROR: {e}")

    return all_results


print(f"\n{'='*60}")
print(f"Merton Report — {date.today()}")
print(f"{'='*60}")
results = collect_all_results()
print(f"\n{len(results)}/5 tickers loaded.")

# endregion


# region Block 2 - Generate HTML Report
# ─────────────────────────────────────────────────────────────
# Builds a complete HTML report with 5 sections:
#   1. Risk overview table (sorted by DD ascending)
#   2. Historical DD time series (2-column grid)
#   3. Stress test grouped bar chart (all 5 tickers)
#   4. Sensitivity table with CSS mini bars
#   5. Credit spread table
# ─────────────────────────────────────────────────────────────

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
    .navbar-sub { font-size: 13px; color: rgba(255,255,255,0.55); margin-left: auto; }
    .container { max-width: 1400px; margin: 0 auto; padding: 36px 40px; }
    .section { margin-bottom: 56px; }
    .section h2 {
        color: #1D6FD8;
        font-size: 17px;
        font-weight: 600;
        border-bottom: 2px solid #E5E5E5;
        padding-bottom: 10px;
        margin-top: 0;
        margin-bottom: 20px;
    }
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
    thead th:first-child, thead th:nth-child(2) { text-align: left; }
    tbody td {
        padding: 9px 14px;
        border-bottom: 1px solid #E5E5E5;
        text-align: right;
        white-space: nowrap;
    }
    tbody td:first-child, tbody td:nth-child(2) { text-align: left; }
    tbody tr:hover { background: #f8fafc; }
    .charts-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 24px;
    }
    .chart-card {
        border: 1px solid #E5E5E5;
        border-radius: 6px;
        padding: 12px;
        background: #FFFFFF;
        overflow: hidden;
    }
    .bar-wrap { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
    .bar-inner { height: 13px; background: #1D6FD8; border-radius: 2px; opacity: 0.72; }
    .footnote {
        font-size: 12px;
        color: #888888;
        margin-top: 12px;
        font-style: italic;
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


def _dd_cell_style(dd):
    if dd > 6:   return 'style="background:#d4edda;"'
    elif dd > 4: return 'style="background:#fff3cd;"'
    elif dd > 2: return 'style="background:#f8d7da;"'
    else:        return 'style="background:#721c24;color:#ffffff;"'


def _dd_chart_html(df, ticker, name):
    """Plotly DD time series chart embedded as HTML snippet."""
    if df is None or df.empty:
        return f'<p style="color:#888;padding:20px;">No time series data for {ticker}.</p>'

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index, y=df["DD"],
        mode="lines+markers", name="DD",
        line=dict(color=BLUE_1, width=2), marker=dict(size=5),
    ))
    for level, color, label in [(6, BLUE_2, "DD=6"), (4, ORANGE_1, "DD=4"), (2, ORANGE_2, "DD=2")]:
        fig.add_hline(y=level, line_dash="dash", line_color=color, line_width=1.2,
                      annotation_text=label, annotation_position="top right",
                      annotation_font=dict(size=10, color=color))

    fig.update_layout(
        title=dict(text=f"{name} ({ticker})", font=dict(size=13, color=TEXT)),
        paper_bgcolor=BG, plot_bgcolor=BG, template="plotly_white",
        font=dict(color=TEXT, size=11),
        height=300, margin=dict(l=50, r=30, t=50, b=40),
        showlegend=False,
        xaxis=dict(showgrid=True, gridcolor=BORDER),
        yaxis=dict(showgrid=True, gridcolor=BORDER, title="DD"),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _stress_chart_html(results):
    """Grouped bar chart: Bear/Base/Bull DD for all 5 tickers."""
    tickers = [r["ticker"] for r in results]
    bear_dd = [r["stress"]["Bear"]["dd"] for r in results]
    base_dd = [r["stress"]["Base"]["dd"] for r in results]
    bull_dd = [r["stress"]["Bull"]["dd"] for r in results]

    fig = go.Figure()
    for label, vals, color in [
        ("Bear", bear_dd, ORANGE_2),
        ("Base", base_dd, BLUE_1),
        ("Bull", bull_dd, BLUE_2),
    ]:
        fig.add_trace(go.Bar(
            x=tickers, y=vals, name=label,
            marker_color=color, opacity=0.85,
            text=[f"{v:.2f}" for v in vals],
            textposition="outside",
            textfont=dict(size=11),
        ))

    for level, color, label in [(6, BLUE_2, "DD=6"), (4, ORANGE_1, "DD=4"), (2, ORANGE_2, "DD=2")]:
        fig.add_hline(y=level, line_dash="dash", line_color=color, line_width=1.2,
                      annotation_text=label, annotation_position="top right",
                      annotation_font=dict(size=10, color=color))

    fig.update_layout(
        barmode="group",
        title=dict(
            text="Stress Test: Bear / Base / Bull — All 5 Tickers<br>"
                 "<sup>Bear: Price −40%, Vol +50%, D +10% | Bull: Price +25%, Vol −20%, D −10%</sup>",
            font=dict(size=14, color=TEXT),
        ),
        paper_bgcolor=BG, plot_bgcolor=BG, template="plotly_white",
        font=dict(color=TEXT, size=11),
        yaxis=dict(title="Distance to Default", showgrid=True, gridcolor=BORDER),
        xaxis=dict(showgrid=False, linecolor=BORDER),
        legend=dict(bgcolor=BG, bordercolor=BORDER, borderwidth=1),
        height=460,
        margin=dict(l=60, r=60, t=90, b=50),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def create_html_report(results):
    """Assemble the complete HTML report from all sections."""
    if not results:
        return "<html><body><p>No data available.</p></body></html>"

    sorted_res  = sorted(results, key=lambda x: x["dd"])  # ascending = highest risk first
    max_vol_impact = max(r["vol_impact"] for r in results) or 1.0

    # ── Section 1: Summary table ────────────────────────────
    rows_s1 = ""
    for r in sorted_res:
        style = _dd_cell_style(r["dd"])
        rows_s1 += (
            f'<tr>'
            f'<td><strong>{r["ticker"]}</strong></td>'
            f'<td>{r["name"]}</td>'
            f'<td {style}>{r["dd"]:.3f}</td>'
            f'<td>{r["pd"]:.4%}</td>'
            f'<td>{r["sigma_v"]:.1%}</td>'
            f'<td>{r["sigma_e"]:.1%}</td>'
            f'<td>{r["market_cap"]:.1f} Bn</td>'
            f'<td>{r["debt"]:.2f} Bn</td>'
            f'<td>{r["rating"]}</td>'
            f'</tr>\n'
        )

    s1 = (
        '<table>\n'
        '<thead><tr>'
        '<th>Ticker</th><th>Company</th><th>DD</th><th>PD</th>'
        '<th>σ_V</th><th>σ_E</th><th>Market Cap</th><th>Debt</th><th>Rating</th>'
        '</tr></thead>\n'
        f'<tbody>{rows_s1}</tbody>\n</table>'
    )

    # ── Section 2: DD time series ──────────────────────────────
    dd_cards = ""
    for r in sorted_res:
        ch = _dd_chart_html(r["df_time_series"], r["ticker"], r["name"])
        dd_cards += '<div class="chart-card">' + ch + '</div>\n'
    s2 = '<div class="charts-grid">' + dd_cards + '</div>'

    # ── Section 3: Stress test chart ─────────────────────────
    s3 = _stress_chart_html(results)

    # ── Section 4: Sensitivity table ──────────────────────
    rows_s4 = ""
    for r in sorted_res:
        width = int(r["vol_impact"] / max_vol_impact * 120)
        bar   = (
            f'<div class="bar-wrap">'
            f'<div class="bar-inner" style="width:{width}px;"></div>'
            f'<span>{r["vol_impact"]:.3f}</span>'
            f'</div>'
        )
        rows_s4 += (
            f'<tr>'
            f'<td><strong>{r["ticker"]}</strong></td>'
            f'<td>{r["dd"]:.3f}</td>'
            f'<td>{r["sens_vol_low"]:.3f}</td>'
            f'<td>{r["sens_vol_high"]:.3f}</td>'
            f'<td>{bar}</td>'
            f'</tr>\n'
        )

    s4 = (
        '<table>\n'
        '<thead><tr>'
        '<th>Ticker</th><th>DD Base</th><th>DD Vol −30%</th>'
        '<th>DD Vol +30%</th><th>Impact ΔDD</th>'
        '</tr></thead>\n'
        f'<tbody>{rows_s4}</tbody>\n</table>'
    )

    # ── Section 5: Credit spread table ─────────────────────
    rows_s5 = ""
    for r in sorted_res:
        gap_str = f"{r['puzzle_gap']:+.1f} bps"
        gap_col = "color:#C0392B;" if r["puzzle_gap"] < 0 else "color:#1B4332;"
        rows_s5 += (
            f'<tr>'
            f'<td><strong>{r["ticker"]}</strong></td>'
            f'<td>{r["rating"]}</td>'
            f'<td>{r["credit_base"]:.1f}</td>'
            f'<td>{r["credit_bear"]:.1f}</td>'
            f'<td>{r["bench_lo"]}–{r["bench_hi"]}</td>'
            f'<td style="{gap_col}">{gap_str}</td>'
            f'</tr>\n'
        )

    s5 = (
        '<table>\n'
        '<thead><tr>'
        '<th>Ticker</th><th>Rating</th>'
        '<th>Base Spread (bps)</th><th>Bear Spread (bps)</th>'
        '<th>Benchmark (bps)</th><th>Puzzle Gap</th>'
        '</tr></thead>\n'
        f'<tbody>{rows_s5}</tbody>\n</table>\n'
        '<p class="footnote">Note: The Merton model systematically underestimates credit spreads '
        'for investment-grade issuers (Credit Spread Puzzle). '
        'Puzzle Gap = Benchmark Low − Bear Spread.</p>'
    )

    # ── Assemble full HTML ────────────────────────────────────
    head = (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>Merton Risk Report — {date.today()}</title>\n'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">\n'
        '<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>\n'
        '<style>' + _CSS + '</style>\n'
        '</head>\n'
    )

    navbar = (
        '<body>\n'
        '<nav class="navbar">\n'
        f'  <span class="navbar-title">Merton Credit Risk Report</span>\n'
        f'  <span class="navbar-sub">{date.today()} &nbsp;|&nbsp; Structural Credit Risk Model</span>\n'
        '</nav>\n'
    )

    def _section(title, content):
        return (
            '<div class="section">\n'
            f'  <h2>{title}</h2>\n'
            f'  {content}\n'
            '</div>\n'
        )

    footer = (
        f'<div class="footer">'
        f'Generated: {date.today()} &nbsp;|&nbsp; Merton Structural Model &nbsp;|&nbsp; '
        f'Data: Financial Modeling Prep API'
        f'</div>\n'
        '</body>\n</html>'
    )

    return (
        head + navbar +
        '<div class="container">\n' +
        _section("Risk Overview", s1) +
        _section("Historical Distance to Default (5 Years)", s2) +
        _section("Stress Test: Bear / Base / Bull", s3) +
        _section("Sensitivity: Volatility Impact on DD", s4) +
        _section("Credit Spread Analysis", s5) +
        '</div>\n' +
        footer
    )


print("\nGenerating HTML report ...")
html_content = create_html_report(results)

html_path = os.path.join(OUTPUT_DIR, f"Merton_Report_{date.today()}.html")
with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Report saved: {html_path}")
webbrowser.open(html_path)
print(f"Report opened: {html_path}")

# endregion


# region Interpretation
print("\n=== Interpretation ===")

if results:
    sorted_i = sorted(results, key=lambda x: x["dd"])
    riskiest = sorted_i[0]
    safest   = sorted_i[-1]

    print(f">>> {riskiest['ticker']} has the lowest DD ({riskiest['dd']:.3f}) "
          f"— highest structural default risk by comparison.")
    print(f">>> {safest['ticker']} has the highest DD ({safest['dd']:.3f}) "
          f"— lowest default risk in the portfolio.")

    critical = [r for r in results if r["dd"] < 2]
    if critical:
        print(f">>> CRITICAL: {', '.join(r['ticker'] for r in critical)} below DD=2 — "
              f"elevated default risk, close monitoring required.")

    max_impact = max(results, key=lambda x: x["vol_impact"])
    print(f">>> {max_impact['ticker']} reacts most strongly to volatility swings "
          f"(ΔDD = {max_impact['vol_impact']:.3f} at ±30% σ_E).")

    all_neg_gap = [r for r in results if r["puzzle_gap"] > 50]
    if all_neg_gap:
        tickers_puzzle = ", ".join(r["ticker"] for r in all_neg_gap)
        print(f">>> Credit Spread Puzzle visible for {tickers_puzzle}: "
              f"the Merton model significantly underestimates spreads vs. market benchmarks.")
# endregion


# region Legende
print("\n=== Legende ===")
print("TICKER_LIST      = List of all analyzed companies (5 tickers)")
print("DD               = Distance to Default — standard deviations to default")
print("PD               = Probability of Default")
print("sigma_V          = Asset volatility (Merton-iterated from sigma_E)")
print("sigma_E          = Equity volatility (annualized, from stock prices)")
print("E                = Market capitalization (Market Cap)")
print("D                = Total debt (Total Debt)")
print("Bear scenario    = E −40%, D +10%, σ_E +50% (market stress)")
print("Bull scenario    = E +25%, D −10%, σ_E −20% (upswing)")
print("sens_vol_low/high= DD at σ_E −30% / +30% (sensitivity analysis)")
print("vol_impact       = |DD_vol_high − DD_vol_low| (total impact range)")
print("credit_base/bear = Merton spread in bps under Base/Bear scenario")
print("bench_lo/hi      = Market benchmark spread range (bps) by rating class")
print("puzzle_gap       = Benchmark_low − Bear_Spread (Credit Spread Puzzle)")
print("LGD              = Loss Given Default = 45% (assumption)")
# endregion
