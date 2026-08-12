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
# MATURITY is a model parameter, not a datum. Merton needs one date on which all
# debt comes due; a real issuer has a ladder of maturities. One year is the
# convention in the literature and the horizon the PD is quoted over.
RISK_FREE_RATE    = 0.043   # 10Y US Treasury, as of 2026-06-30 (SOURCES.md #7)
MATURITY          = 1
# endregion

# ----------------------------------------------------------------------------
# region DCF PARAMETERS
# ----------------------------------------------------------------------------
# Assumed input distributions for the Monte Carlo, set per ticker from its own
# history and sector position. None of the four comes from a publication - they
# are this project's assumptions, and the tornado chart in Model 3 shows how much
# each one moves the result. WACC_MEAN is a prior only: DCF_Valuation.py computes
# the WACC actually used from CAPM.
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
