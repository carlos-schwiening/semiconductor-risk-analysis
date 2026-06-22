"""
Used by: Merton/Merton_Model.py, DCF/DCF_Valuation.py, MCS/Monte_Carlo_Sim.py
ON Semiconductor - Configuration for DCF_Merton_MC
"""

# region COMPANY
COMPANY           = "ON Semiconductor"
TICKER            = "ON"
RATING            = "BBB-"
# endregion

# region MERTON PARAMETERS
RISK_FREE_RATE    = 0.043
MATURITY          = 1
# endregion

# region DCF PARAMETERS
WACC_MEAN         = 0.095
WACC_STD          = 0.015
GROWTH_MEAN       = 0.05
GROWTH_STD        = 0.02
TERMINAL_GROWTH   = 0.025
FORECAST_YEARS    = 5
# endregion

# region MONTE CARLO
SIMULATIONS      = 10000
# endregion

# region OUTPUT
OUTPUT_DIR        = r"C:\Python\Outputs\Reports\DCF_Merton_MC"
# endregion
