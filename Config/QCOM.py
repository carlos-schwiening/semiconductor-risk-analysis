"""
Used by: Merton/Merton_Model.py, DCF/DCF_Valuation.py, MCS/Monte_Carlo_Sim.py
Qualcomm - Configuration for DCF_Merton_MC
"""

import os

# ----------------------------------------------------------------------------
# region COMPANY
# ----------------------------------------------------------------------------
COMPANY           = "Qualcomm"
TICKER            = "QCOM"
RATING            = "A-"
# endregion

# ----------------------------------------------------------------------------
# region MERTON PARAMETERS
# ----------------------------------------------------------------------------
RISK_FREE_RATE    = 0.043
MATURITY          = 1
# endregion

# ----------------------------------------------------------------------------
# region DCF PARAMETERS
# ----------------------------------------------------------------------------
WACC_MEAN         = 0.09
WACC_STD          = 0.01
GROWTH_MEAN       = 0.06
GROWTH_STD        = 0.015
TERMINAL_GROWTH   = 0.025
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
