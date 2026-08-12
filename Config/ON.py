"""
Used by: Merton/Merton_Model.py, DCF/DCF_Valuation.py, MCS/Monte_Carlo_Sim.py
ON Semiconductor - Configuration for DCF_Merton_MC
"""

import os

# ----------------------------------------------------------------------------
# region COMPANY
# ----------------------------------------------------------------------------
COMPANY           = "ON Semiconductor"
TICKER            = "ON"
RATING            = "BB+"   # S&P; Moody's Ba1 affirmed 2026-01 — speculative grade — SOURCES.md #8
# endregion

# ----------------------------------------------------------------------------
# region MERTON PARAMETERS
# ----------------------------------------------------------------------------
RISK_FREE_RATE    = 0.043   # 10Y US Treasury, as of 2026-06-30 (SOURCES.md #7)
MATURITY          = 1
# endregion

# ----------------------------------------------------------------------------
# region DCF PARAMETERS
# ----------------------------------------------------------------------------
WACC_MEAN         = 0.095
WACC_STD          = 0.015
GROWTH_MEAN       = 0.05
GROWTH_STD        = 0.02
TERMINAL_GROWTH   = 0.025   # long-run assumption anchored to the 2% central-bank inflation target, not a datum
FORECAST_YEARS    = 5
# endregion

# ----------------------------------------------------------------------------
# region MONTE CARLO
# ----------------------------------------------------------------------------
SIMULATIONS      = 10000
# endregion

# ----------------------------------------------------------------------------
# region OUTPUT
# ----------------------------------------------------------------------------
PROJECT_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR        = os.path.join(PROJECT_ROOT, "Outputs")
# endregion
