"""
DD_TimeSeries_Chart — Distance to Default Time Series for all 5 Tickers
========================================================================
Run with: python Merton/DD_TimeSeries_Chart.py

  Block 0: Imports & Setup
  Block 1: Load Data
  Block 2: Create Chart
  Block 3: PNG Export
"""

# region Block 0 - Imports & Setup
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import os
import glob
from datetime import date

import pandas as pd
import plotly.graph_objects as go

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plot_style import (
    LAYOUT,
    TICKER_COLORS,
    TITLE_FONT, AXIS_FONT, SOURCE_FONT, TICK_FONT,
    AXIS_DEFAULTS, SOURCE_TEXT,
)

REPORTS_BASE = r"C:\Python\Outputs\Reports\DCF_Merton_MC"
IMAGES_DIR   = os.path.join(PROJECT_ROOT, "images")
TODAY        = date.today().strftime("%Y-%m-%d")
TICKER_LIST  = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]

WIDTH  = 1100
HEIGHT = 550
SCALE  = 2

os.makedirs(IMAGES_DIR, exist_ok=True)

print(f"\n{'='*60}")
print(f"DD Time Series Chart — {TODAY}")
print(f"{'='*60}")
# endregion


# region Block 1 - Load Data
print("\nLoading DD_TimeSeries_All from Merton_Summary_*.xlsx ...")

_xlsx_files = glob.glob(os.path.join(REPORTS_BASE, "Merton_Summary_*.xlsx"))
if not _xlsx_files:
    raise FileNotFoundError(
        f"No Merton_Summary_*.xlsx found under {REPORTS_BASE}. "
        f"Run Merton/Merton_Model.py first."
    )
_xlsx_path = max(_xlsx_files, key=os.path.getmtime)
df = pd.read_excel(_xlsx_path, sheet_name="DD_TimeSeries_All")
df["Date"] = pd.to_datetime(df["Date"])
df = df.sort_values("Date")

print(f"  Source: {_xlsx_path}")
print(f"  Rows: {len(df)}  |  Tickers: {df['Ticker'].unique().tolist()}")
print(f"  Period: {df['Date'].min().date()} — {df['Date'].max().date()}")
# endregion


# region Block 2 - Create Chart
print("\nCreating DD time series chart ...")

fig = go.Figure()

for tkr in TICKER_LIST:
    sub = df[df["Ticker"] == tkr].sort_values("Date")
    fig.add_trace(go.Scatter(
        x=sub["Date"],
        y=sub["DD"],
        name=tkr,
        mode="lines",
        line=dict(color=TICKER_COLORS.get(tkr, "#888888"), width=2),
    ))

fig.update_layout(**LAYOUT)
fig.update_layout(
    title=dict(
        text="Distance to Default — 5 Tickers (Quarterly)",
        font=TITLE_FONT,
        x=0.0,
        xanchor="left",
    ),
    width=WIDTH,
    height=HEIGHT,
    margin=dict(l=60, r=30, t=70, b=80),
    showlegend=True,
    legend=dict(
        orientation="h",
        x=0.0,
        y=-0.18,
        bgcolor="rgba(0,0,0,0)",
        borderwidth=0,
        font=TICK_FONT,
    ),
    xaxis=dict(
        **AXIS_DEFAULTS,
        title=None,
        tickformat="%b %Y",
        dtick="M3",
        tickangle=-30,
    ),
    yaxis=dict(
        **AXIS_DEFAULTS,
        title=dict(text="Distance to Default (σ)", font=AXIS_FONT),
        rangemode="tozero",
    ),
)

fig.add_annotation(
    xref="paper", yref="paper",
    x=1.0, y=1.04,
    text=SOURCE_TEXT,
    showarrow=False,
    font=SOURCE_FONT,
    xanchor="right",
    yanchor="bottom",
)
# endregion


# region Block 3 - PNG Export
output_path = os.path.join(IMAGES_DIR, "DD_TimeSeries.png")
fig.write_image(output_path, width=WIDTH, height=HEIGHT, scale=SCALE)

size_kb = os.path.getsize(output_path) // 1024
print(f"\nPNG saved: {output_path}")
print(f"Dimensions:      {WIDTH} x {HEIGHT} px @ {SCALE}x  ({size_kb} KB)")
# endregion


# region Interpretation
print("\n=== Interpretation ===")
latest = df.groupby("Ticker")["DD"].last()
for tkr in TICKER_LIST:
    dd_val = latest.get(tkr, float("nan"))
    if dd_val < 2.0:
        stage = "Stage 3 (near default)"
    elif dd_val < 4.0:
        stage = "Stage 2 (elevated risk)"
    else:
        stage = "Stage 1 (low risk)"
    print(f">>> {tkr}: DD={dd_val:.3f}sigma — {stage}")
# endregion


# region Legende
print("\n=== Legende ===")
print("DD              = Distance to Default (standard deviations to the default point)")
print("Date            = Quarterly reference date from the Merton time series")
print("Ticker          = MCHP | INTC | ON | QCOM | MPWR")
print("TICKER_COLORS   = Per-ticker color mapping from plot_style.py")
print("REPORTS_BASE    = C:\\Python\\Outputs\\Reports\\DCF_Merton_MC (source: Merton_Summary_*.xlsx, sheet DD_TimeSeries_All)")
print("IMAGES_DIR      = images/ in repo root (DD_TimeSeries.png)")
print("WIDTH/HEIGHT    = 1100 x 550 px  (README-optimized)")
print("SCALE           = 2x  (2200 x 1100 px effective for sharp rendering)")
# endregion
