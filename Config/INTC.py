"""
Used by: Merton/Merton_Model.py, DCF/DCF_Valuation.py, MCS/Monte_Carlo_Sim.py
Intel Corporation - Configuration for DCF_Merton_MC
"""

import os

# ----------------------------------------------------------------------------
# region COMPANY
# ----------------------------------------------------------------------------
COMPANY           = "Intel Corporation"
TICKER            = "INTC"
RATING            = "BBB"   # S&P, cut from BBB+ 2025-08; Intel states this in its own 10-K — SOURCES.md #8
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
WACC_MEAN         = 0.09
WACC_STD          = 0.015
GROWTH_MEAN       = 0.03
GROWTH_STD        = 0.025
TERMINAL_GROWTH   = 0.02    # long-run assumption anchored to the 2% central-bank inflation target, not a datum
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
