"""
Merton_Dashboard_Chart — 2x2 Structural Credit Risk Dashboard, Semiconductor Sector
=====================================================================================
Run with: python Merton/Merton_Dashboard_Chart.py

  Block 0: Imports & Setup
  Block 1: Load Data (Merton_Summary_*.xlsx from Reports folder)
  Block 2: Create 2x2 Subplot Chart
    Panel 1 (top-left):     DD Time Series — all 5 tickers
    Panel 2 (top-right):    Bubble Chart — DD vs. Credit Spread (Bn)
    Panel 3 (bottom-left):  Rating Migration Heatmap (MCHP)
    Panel 4 (bottom-right): IFRS 9 ECL Stage Horizontal Bars
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
from plotly.subplots import make_subplots

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plot_style import (
    LAYOUT, TICKER_COLORS, STAGE_COLORS,
    DD_STAGE1, DD_STAGE2,
    CHART_WIDTH, CHART_HEIGHT, CHART_SCALE,
    TITLE_FONT, AXIS_FONT, ANNOTATION_FONT, SOURCE_FONT, TICK_FONT,
    AXIS_DEFAULTS, SOURCE_TEXT,
    GRAY_1,
)

OUTPUT_DIR  = r"C:\Python\Outputs\Reports\DCF_Merton_MC"
TODAY          = date.today().strftime("%Y-%m-%d")
RATING_ORDER   = ["AAA/AA", "A", "BBB", "BB", "B", "CCC"]
TICKER_LIST    = ["MCHP", "INTC", "ON", "QCOM", "MPWR"]

os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"\n{'='*60}")
print(f"Merton Dashboard Chart — {TODAY}")
print(f"{'='*60}")
# endregion


# region Block 1 - Load Data
print("\nLoading data from Merton_Summary_*.xlsx ...")

_xlsx_files = glob.glob(os.path.join(OUTPUT_DIR, "Merton_Summary_*.xlsx"))
if not _xlsx_files:
    raise FileNotFoundError(
        f"No Merton_Summary_*.xlsx found under {OUTPUT_DIR}. "
        f"Run Merton/Merton_Model.py first."
    )
_xlsx_path = max(_xlsx_files, key=os.path.getmtime)
print(f"  Source: {_xlsx_path}")

df_dd = pd.read_excel(_xlsx_path, sheet_name="DD_TimeSeries_All")
df_dd["Date"] = pd.to_datetime(df_dd["Date"])
print(f"  DD_TimeSeries_All:  {df_dd.shape}")

df_summary = pd.read_excel(_xlsx_path, sheet_name="Summary")
print(f"  Summary:            {df_summary.shape}")

df_migration = pd.read_excel(_xlsx_path, sheet_name="Rating_Migration")
print(f"  Rating_Migration:   {df_migration.shape}")
# endregion


# region Block 2 - 2x2 Subplot Chart
print("\nCreating 2x2 dashboard chart ...")

fig = make_subplots(
    rows=2, cols=2,
    subplot_titles=[
        "Distance to Default — 5 Tickers (Quarterly)",
        "DD vs. Credit Spread (Bubble = Market Cap)",
        "Rating Migration Matrix (MCHP)",
        "IFRS 9 — 12M Expected Credit Loss",
    ],
    vertical_spacing=0.16,
    horizontal_spacing=0.10,
)

# ── Panel 1: DD time series, all 5 tickers ────────────────────────
for tkr in TICKER_LIST:
    sub = df_dd[df_dd["Ticker"] == tkr].sort_values("Date")
    fig.add_trace(go.Scatter(
        x=sub["Date"],
        y=sub["DD"],
        name=tkr,
        mode="lines",
        line=dict(color=TICKER_COLORS.get(tkr, "#888"), width=2),
        legendgroup=tkr,
        showlegend=True,
    ), row=1, col=1)

fig.add_hline(
    y=DD_STAGE1,
    line_dash="dash", line_color=GRAY_1, line_width=1,
    annotation_text="Stage 1/2",
    annotation_font=ANNOTATION_FONT,
    annotation_position="top right",
    row=1, col=1,
)
fig.add_hline(
    y=DD_STAGE2,
    line_dash="dash", line_color="#C0392B", line_width=1,
    annotation_text="Stage 2/3",
    annotation_font=dict(family="Inter, Arial, sans-serif", size=10, color="#C0392B"),
    annotation_position="bottom right",
    row=1, col=1,
)

# ── Panel 2: Bubble chart DD vs. Spread_bps ─────────────────────
_max_mkt  = df_summary["MarketCap_Bn"].max()
_sizeref  = 2.0 * (_max_mkt * 3) / (50 ** 2)

for _, row_data in df_summary.iterrows():
    tkr = str(row_data["Ticker"])
    fig.add_trace(go.Scatter(
        x=[float(row_data["DD"])],
        y=[float(row_data["Spread_bps"])],
        name=tkr,
        mode="markers+text",
        marker=dict(
            size=float(row_data["MarketCap_Bn"]) * 3,
            sizemode="area",
            sizeref=_sizeref,
            color=TICKER_COLORS.get(tkr, "#888"),
            opacity=0.85,
            line=dict(width=1.5, color="white"),
        ),
        text=[tkr],
        textposition="top center",
        textfont=dict(family="Inter, Arial, sans-serif", size=10,
                      color=TICKER_COLORS.get(tkr, "#888")),
        legendgroup=tkr,
        showlegend=False,
    ), row=1, col=2)

# ── Panel 3: Rating migration heatmap ──────────────────────────
pivot = (
    df_migration
    .pivot_table(
        index="From_Rating", columns="To_Rating",
        values="Probability", aggfunc="first",
    )
    .reindex(index=RATING_ORDER, columns=RATING_ORDER)
    .fillna(0.0)
)

z_vals    = pivot.values.tolist()
text_vals = [
    [f"{v:.0%}" if v > 0 else "" for v in row]
    for row in pivot.values
]

fig.add_trace(go.Heatmap(
    z=z_vals,
    x=RATING_ORDER,
    y=RATING_ORDER,
    colorscale=[[0.0, "#FFFFFF"], [1.0, "#1B4332"]],
    showscale=False,
    text=text_vals,
    texttemplate="%{text}",
    textfont=dict(family="Inter, Arial, sans-serif", size=10, color="#1A1A1A"),
), row=2, col=1)

# ── Panel 4: IFRS 9 ECL stage horizontal bars ──────────────────
_shown_stages = set()
for _, row_data in df_summary.iterrows():
    tkr   = str(row_data["Ticker"])
    stage = int(row_data["ECL_Stage"])
    ecl   = float(row_data["ECL_12M"])
    color = STAGE_COLORS.get(stage, "#888")
    _first = stage not in _shown_stages
    if _first:
        _shown_stages.add(stage)
    fig.add_trace(go.Bar(
        y=[tkr],
        x=[ecl],
        orientation="h",
        marker_color=color,
        name=f"Stage {stage}",
        text=[f"{ecl:.4f}" if ecl >= 0.0001 else "0"],
        textposition="outside",
        textfont=TICK_FONT,
        legendgroup=f"stage{stage}",
        showlegend=_first,
    ), row=2, col=2)
# endregion


# region Block 3 - Layout & PNG Export
fig.update_layout(**LAYOUT)
fig.update_layout(
    title=dict(
        text=(
            "Merton Structural Credit Risk — Semiconductor Sector<br>"
            "<sup>Distance to Default · Credit Spread · Rating Migration · IFRS 9 ECL</sup>"
        ),
        font=TITLE_FONT,
        x=0.5,
        xanchor="center",
        y=0.98,
    ),
    width=CHART_WIDTH,
    height=CHART_HEIGHT,
    showlegend=True,
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        borderwidth=0,
        x=0.01,
        y=0.99,
        font=TICK_FONT,
        tracegroupgap=2,
    ),
    margin=dict(t=110, b=80, l=60, r=50),
)

# Panel 1 axes
fig.update_xaxes(**AXIS_DEFAULTS, row=1, col=1)
fig.update_yaxes(
    title_text="DD", title_font=AXIS_FONT,
    **AXIS_DEFAULTS, row=1, col=1,
)

# Panel 2 axes
fig.update_xaxes(
    title_text="Distance to Default", title_font=AXIS_FONT,
    **AXIS_DEFAULTS, row=1, col=2,
)
fig.update_yaxes(
    title_text="Spread (bps)", title_font=AXIS_FONT,
    **AXIS_DEFAULTS, row=1, col=2,
)

# Panel 3 heatmap axes (no gridlines, reverse y so AAA/AA at top)
fig.update_xaxes(
    title_text="To Rating", title_font=AXIS_FONT,
    tickfont=TICK_FONT, showgrid=False, showline=False,
    row=2, col=1,
)
fig.update_yaxes(
    title_text="From Rating", title_font=AXIS_FONT,
    tickfont=TICK_FONT, showgrid=False, showline=False,
    autorange="reversed",
    row=2, col=1,
)

# Panel 4 axes
fig.update_xaxes(
    title_text="ECL 12M", title_font=AXIS_FONT,
    **AXIS_DEFAULTS, row=2, col=2,
)
fig.update_yaxes(**AXIS_DEFAULTS, row=2, col=2)

# Source annotation bottom-right
fig.add_annotation(
    text=SOURCE_TEXT,
    xref="paper", yref="paper",
    x=1.0, y=-0.05,
    xanchor="right", yanchor="top",
    showarrow=False,
    font=SOURCE_FONT,
)

# Export PNG
png_path = os.path.join(OUTPUT_DIR, f"Merton_Dashboard_{TODAY}.png")
fig.write_image(png_path, width=CHART_WIDTH, height=CHART_HEIGHT, scale=CHART_SCALE)

print(f"\nPNG saved:        {png_path}")
print(f"Dimensions:       {CHART_WIDTH} x {CHART_HEIGHT} px @ {CHART_SCALE}x")
# endregion


# region Interpretation
print("\n=== Interpretation ===")
_best  = df_summary.loc[df_summary["DD"].idxmax()]
_worst = df_summary.loc[df_summary["DD"].idxmin()]
_s2    = df_summary[df_summary["ECL_Stage"] == 2]
_s3    = df_summary[df_summary["ECL_Stage"] == 3]

print(f">>> Highest DD:   {_best['Ticker']} (DD={float(_best['DD']):.2f}) "
      f"— Rating {_best['Rating']} — lowest credit risk")
print(f">>> Lowest DD:    {_worst['Ticker']} (DD={float(_worst['DD']):.2f}) "
      f"— Rating {_worst['Rating']} — highest credit risk")
if not _s2.empty:
    for _, r in _s2.iterrows():
        print(f">>> IFRS9 Stage 2:  {r['Ticker']} — significant increase in risk, "
              f"ECL_12M={float(r['ECL_12M']):.4f}")
if not _s3.empty:
    for _, r in _s3.iterrows():
        print(f">>> IFRS9 Stage 3:  {r['Ticker']} — default, ECL_12M={float(r['ECL_12M']):.4f}")
if _s2.empty and _s3.empty:
    print(">>> IFRS9: All tickers in Stage 1 — no significant increase in credit risk")
print(f">>> Dashboard saved: {png_path}")
# endregion


# region Legende
print("\n=== Legende ===")
print("DD             = Distance to Default from the Merton model (number of standard deviations to default)")
print("PD             = Probability of Default = N(-DD)")
print("Spread_bps     = Credit spread in basis points (calculated from Merton PD)")
print("MarketCap_Bn   = Market capitalization in Bn USD (bubble size in Panel 2)")
print("ECL_Stage      = IFRS9 stage: 1=unchanged, 2=significant increase, 3=default")
print("ECL_12M        = Expected Credit Loss over 12 months (ECL = PD * LGD * EAD)")
print("From_Rating    = Starting rating at the beginning of the period (row of the migration matrix)")
print("To_Rating      = Ending rating at the end of the period (column of the migration matrix)")
print("Probability    = Empirical transition probability (Count / row sum)")
print("DD_STAGE1      = 4.0  (IFRS9 boundary Stage 1 / Stage 2)")
print("DD_STAGE2      = 2.0  (IFRS9 boundary Stage 2 / Stage 3)")
print("CHART_WIDTH    = 1400 (width in pixels)")
print("CHART_HEIGHT   = 900  (height in pixels)")
print("CHART_SCALE    = 2    (DPI scaling for PNG export)")
print("RATING_ORDER   = ['AAA/AA','A','BBB','BB','B','CCC']  (heatmap y-axis)")
# endregion
