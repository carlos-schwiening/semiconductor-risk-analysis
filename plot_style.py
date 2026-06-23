"""
plot_style — Central Plotly design template for all charts in the project.
===========================================================================
Import with:
  from plot_style import (
      LAYOUT, BLUE_1, BLUE_2, BLUE_3, ORANGE_1, ORANGE_2, ORANGE_3, GRAY_1,
      TITLE_FONT, AXIS_FONT, ANNOTATION_FONT, SOURCE_FONT, TICK_FONT,
      TICKER_COLORS, STAGE_COLORS,
      DD_STAGE1, DD_STAGE2,
      CHART_WIDTH, CHART_HEIGHT, CHART_SCALE,
      AXIS_DEFAULTS, SOURCE_TEXT,
  )
"""

# ── Color Palette ────────────────────────────────────────────────
BLUE_1   = "#1D6FD8"   # Primary blue   (main lines, bars, active elements)
BLUE_2   = "#5B9BD5"   # Secondary blue (comparison lines, positive scenarios)
BLUE_3   = "#A8C8E8"   # Tertiary blue  (background band, fill areas)

ORANGE_1 = "#D4A843"   # Warm orange   (median, benchmark, expected value)
ORANGE_2 = "#E8853D"   # Strong orange (warning, tail risk, stress scenario)
ORANGE_3 = "#F2C27A"   # Light orange  (band fill, background areas)

GRAY_1   = "#6B7280"   # Primary gray  (reference lines, secondary labels)

BG   = "#FFFFFF"
TEXT = "#1A1A1A"

# ── Central Layout Template ─────────────────────────────────
LAYOUT = dict(
    template="plotly_white",
    paper_bgcolor=BG,
    plot_bgcolor=BG,
    font=dict(family="Inter, Arial, sans-serif", size=12, color=TEXT),
    legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0),
)

# ── Typography ─────────────────────────────────────────────────
TITLE_FONT      = dict(family="Inter, Arial, sans-serif", size=16, color="#0B1220")
AXIS_FONT       = dict(family="Inter, Arial, sans-serif", size=11, color="#6B7280")
ANNOTATION_FONT = dict(family="Inter, Arial, sans-serif", size=10, color="#1A1A1A")
SOURCE_FONT     = dict(family="Inter, Arial, sans-serif", size=9,  color="#9CA3AF")
TICK_FONT       = dict(family="Inter, Arial, sans-serif", size=10, color="#6B7280")

# ── Ticker Colors ──────────────────────────────────────────────
TICKER_COLORS = {
    "MCHP": "#1B4332",   # BBB  — dark green
    "INTC": "#C0392B",   # BB   — red
    "ON":   "#2D6A4F",   # BBB  — green
    "QCOM": "#1D6FD8",   # A    — blue
    "MPWR": "#0B1220",   # AAA  — navy
}

# ── IFRS 9 Stage Colors ────────────────────────────────────────
STAGE_COLORS = {1: "#1B4332", 2: "#D4A843", 3: "#C0392B"}

# ── DD Thresholds (IFRS 9 Stage Boundaries) ──────────────────
DD_STAGE1 = 4.0   # Stage 1 / Stage 2
DD_STAGE2 = 2.0   # Stage 2 / Stage 3

# ── Chart Dimensions ──────────────────────────────────────────
CHART_WIDTH  = 1400
CHART_HEIGHT = 900
CHART_SCALE  = 2

# ── Axis Defaults ────────────────────────────────────────────
AXIS_DEFAULTS = dict(
    showgrid=False,
    zeroline=False,
    showline=True,
    linecolor="#E5E5E5",
    tickfont=TICK_FONT,
)

# ── Source Attribution ──────────────────────────────────────────
SOURCE_TEXT = "Source: FMP API · Merton (1974)"
