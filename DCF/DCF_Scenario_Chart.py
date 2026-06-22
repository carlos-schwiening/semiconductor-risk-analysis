"""
DCF_Scenario_Chart — DCF Scenario Analysis Bear/Base/Bull for all 5 Tickers
=============================================================================
Run with: python DCF/DCF_Scenario_Chart.py

  Block 0: Imports & Setup
  Block 1: Load Data (Excel or hardcoded fallback)
  Block 2: Create Chart
  Block 3: PNG Export
"""

# region Block 0 - Imports & Setup
import sys
sys.stdout.reconfigure(encoding="utf-8")
import os
import glob
from datetime import date

import pandas as pd
import plotly.graph_objects as go

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plot_style import (
    LAYOUT, ORANGE_1, GRAY_1,
    TITLE_FONT, AXIS_FONT, SOURCE_FONT, TICK_FONT,
)

REPORTS_BASE   = r"C:\Python\Outputs\Reports\DCF_Merton_MC"
IMAGES_FOLDER  = os.path.join(PROJECT_ROOT, "images")
TICKER_LIST    = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]

BEAR_COLOR = "#C0392B"
BASE_COLOR = "#6B7280"
BULL_COLOR = "#1B4332"

WIDTH  = 1100
HEIGHT = 600
SCALE  = 2

os.makedirs(IMAGES_FOLDER, exist_ok=True)

print(f"\n{'='*60}")
print(f"DCF Scenario Chart — {date.today()}")
print(f"{'='*60}")
# endregion


# region Block 1 - Load Data
# Fallback values (from model output, hardcoded for robustness)
FALLBACK = {
    "MCHP": {"Bear":  36.95, "Base":  61.03, "Bull":  90.58, "Market":   87.91},
    "INTC": {"Bear":  None,  "Base":  None,  "Bull":  None,  "Market":  107.04},
    "ON":   {"Bear":  28.50, "Base":  56.56, "Bull":  82.00, "Market":  110.17},
    "QCOM": {"Bear":  55.00, "Base": 100.25, "Bull": 145.00, "Market":  191.20},
    "MPWR": {"Bear": 120.00, "Base": 235.54, "Bull": 340.00, "Market": 1473.04},
}

data = {tkr: dict(FALLBACK[tkr]) for tkr in TICKER_LIST}

# DCF_Results_*.xlsx — read the latest workbook (Scenarios + Summary sheets)
_dcf_files = glob.glob(os.path.join(REPORTS_BASE, "*", "DCF_Results_*.xlsx"))
_dcf_xlsx  = max(_dcf_files, key=os.path.getmtime) if _dcf_files else None

if _dcf_xlsx is None:
    print(f"  No DCF_Results_*.xlsx found under {REPORTS_BASE} — fallback for all tickers")
else:
    print(f"  Source: {_dcf_xlsx}")

    # Scenarios sheet — Bear/Base/Bull values per ticker (may contain only the active ticker)
    try:
        df_scen = pd.read_excel(_dcf_xlsx, sheet_name="Scenarios")
        for tkr in TICKER_LIST:
            sub = df_scen[df_scen["Ticker"] == tkr]
            if not sub.empty:
                for _, row in sub.iterrows():
                    scen = str(row.get("Scenario", ""))
                    if scen in ("Bear", "Base", "Bull"):
                        val = row.get("DCF_Value_Per_Share")
                        data[tkr][scen] = float(val) if pd.notna(val) and float(val) > 0 else None
                    price = row.get("Price")
                    if pd.notna(price):
                        data[tkr]["Market"] = float(price)
                print(f"  XLSX: {tkr} — Bear={data[tkr]['Bear']}  "
                      f"Base={data[tkr]['Base']}  Bull={data[tkr]['Bull']}")
            else:
                print(f"  Fallback: {tkr}")
        print(f"  Scenarios sheet: {len(df_scen)} rows loaded")
    except Exception as _exc_scen:
        print(f"  Scenarios sheet not available — fallback ({_exc_scen})")

    # Summary sheet — current market prices for all 5 tickers
    try:
        df_sum = pd.read_excel(_dcf_xlsx, sheet_name="Summary")
        for tkr in TICKER_LIST:
            row = df_sum[df_sum["Ticker"] == tkr]
            if not row.empty:
                data[tkr]["Market"] = float(row.iloc[0]["Price"])
        print("  Summary sheet: market prices updated")
    except Exception:
        print("  Summary sheet not available — fallback market prices")

print("\nFinal data:")
for tkr in TICKER_LIST:
    d = data[tkr]
    print(f"  {tkr:<5}  Bear={str(d['Bear']):<7}  Base={str(d['Base']):<7}  "
          f"Bull={str(d['Bull']):<7}  Market={d['Market']}")
# endregion


# region Block 2 - Create Chart
print("\nCreating DCF Scenario Chart ...")

def _y(tkr, scen):
    v = data[tkr][scen]
    return 0.0 if (v is None or v <= 0) else float(v)

def _is_neg(tkr, scen):
    v = data[tkr][scen]
    return v is None or v <= 0

fig = go.Figure()

# Bear bars
fig.add_trace(go.Bar(
    name="Bear",
    x=TICKER_LIST,
    y=[_y(tkr, "Bear") for tkr in TICKER_LIST],
    marker_color=BEAR_COLOR,
    opacity=0.85,
    text=[("neg." if _is_neg(tkr, "Bear") else f"${_y(tkr, 'Bear'):.0f}")
          for tkr in TICKER_LIST],
    textposition="outside",
    textfont=dict(size=9, color=BEAR_COLOR, family="Inter, Arial, sans-serif"),
    cliponaxis=False,
))

# Base bars
fig.add_trace(go.Bar(
    name="Base",
    x=TICKER_LIST,
    y=[_y(tkr, "Base") for tkr in TICKER_LIST],
    marker_color=BASE_COLOR,
    opacity=0.85,
    text=[("neg." if _is_neg(tkr, "Base") else f"${_y(tkr, 'Base'):.0f}")
          for tkr in TICKER_LIST],
    textposition="outside",
    textfont=dict(size=9, color=BASE_COLOR, family="Inter, Arial, sans-serif"),
    cliponaxis=False,
))

# Bull bars
fig.add_trace(go.Bar(
    name="Bull",
    x=TICKER_LIST,
    y=[_y(tkr, "Bull") for tkr in TICKER_LIST],
    marker_color=BULL_COLOR,
    opacity=0.85,
    text=[("neg." if _is_neg(tkr, "Bull") else f"${_y(tkr, 'Bull'):.0f}")
          for tkr in TICKER_LIST],
    textposition="outside",
    textfont=dict(size=9, color=BULL_COLOR, family="Inter, Arial, sans-serif"),
    cliponaxis=False,
))

# Market prices as horizontal dash markers per ticker (ORANGE_1)
fig.add_trace(go.Scatter(
    name="Market Price",
    x=TICKER_LIST,
    y=[data[tkr]["Market"] for tkr in TICKER_LIST],
    mode="markers+text",
    marker=dict(
        symbol="line-ew",
        size=38,
        color=ORANGE_1,
        line=dict(width=2.5, color=ORANGE_1),
    ),
    text=[f"${data[tkr]['Market']:.0f}" for tkr in TICKER_LIST],
    textposition="top center",
    textfont=dict(size=9, color=ORANGE_1, family="Inter, Arial, sans-serif"),
))

# Source Annotation
fig.add_annotation(
    xref="paper", yref="paper",
    x=1.0, y=1.04,
    text="Source: FMP API · DCF Model",
    showarrow=False,
    font=SOURCE_FONT,
    xanchor="right",
    yanchor="bottom",
)

fig.update_layout(**LAYOUT)
fig.update_layout(
    title=dict(
        text="DCF Scenario Analysis — Bear / Base / Bull",
        font=TITLE_FONT,
        x=0.0,
        xanchor="left",
    ),
    barmode="group",
    bargap=0.20,
    bargroupgap=0.05,
    width=WIDTH,
    height=HEIGHT,
    margin=dict(l=70, r=30, t=70, b=100),
    showlegend=True,
    legend=dict(
        orientation="h",
        x=0.0,
        y=-0.22,
        bgcolor="rgba(0,0,0,0)",
        borderwidth=0,
        font=TICK_FONT,
    ),
    xaxis=dict(
        showgrid=False, zeroline=False,
        showline=True, linecolor="#E5E5E5",
        tickfont=TICK_FONT,
    ),
    yaxis=dict(
        title=dict(text="DCF Value per Share (USD)", font=AXIS_FONT),
        showgrid=False, zeroline=False,
        showline=True, linecolor="#E5E5E5",
        tickfont=TICK_FONT,
        rangemode="tozero",
    ),
)
# endregion


# region Block 3 - PNG Export
output_path = os.path.join(IMAGES_FOLDER, "DCF_Scenario.png")
fig.write_image(output_path, width=WIDTH, height=HEIGHT, scale=SCALE)
size_kb = os.path.getsize(output_path) // 1024
print(f"\nPNG saved: {output_path}")
print(f"Dimensions:      {WIDTH} x {HEIGHT} px @ {SCALE}x  ({size_kb} KB)")
# endregion


# region Interpretation
print("\n=== Interpretation ===")
for tkr in TICKER_LIST:
    d = data[tkr]
    market = d.get("Market", 0)
    bull  = d.get("Bull")
    bear  = d.get("Bear")
    if all(d[s] is None or d[s] <= 0 for s in ("Bear", "Base", "Bull")):
        print(f">>> {tkr}: All scenarios negative — market price ${market:.0f} "
              f"not supported by the DCF model (neg. FCF / high debt)")
    else:
        bull_up = (bull / market - 1) * 100 if bull and market else float("nan")
        bear_str = f"Bear=${bear:.0f}" if bear else "Bear=neg."
        print(f">>> {tkr}: {bear_str}  Base=${d['Base']:.0f}  Bull=${bull:.0f}  "
              f"Market=${market:.0f}  Bull-Upside={bull_up:+.1f}%")
# endregion


# region Legende
print("\n=== Legende ===")
print("Bear        = DCF value Bear scenario: WACC+1.5%, g1-2%, FCF x0.85")
print("Base        = DCF value Base Case: unchanged model assumptions")
print("Bull        = DCF value Bull scenario: WACC-1%, g1+2%, FCF x1.15")
print("Market      = Current stock price per share in USD")
print("neg.        = Negative DCF equity value (EV(DCF) < Net Debt)")
print("BEAR_COLOR  = #C0392B — red")
print("BASE_COLOR  = #6B7280 — gray")
print("BULL_COLOR  = #1B4332 — dark green")
print("ORANGE_1    = Market price color from plot_style.py")
print("line-ew     = Plotly marker symbol for horizontal dash per ticker")
print("FALLBACK    = Hardcoded values if the DCF_Results workbook is unavailable")
print(f"OUTPUT      = images/DCF_Scenario.png")
# endregion
