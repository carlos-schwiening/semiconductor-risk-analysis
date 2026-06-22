"""
Used by: Merton/Merton_Model.py, DCF/DCF_Valuation.py, MCS/Monte_Carlo_Sim.py
Intel Corporation - Configuration for DCF_Merton_MC
"""

# region COMPANY
COMPANY           = "Intel Corporation"
TICKER            = "INTC"
RATING            = "BBB"
# endregion

# region MERTON PARAMETERS
RISK_FREE_RATE    = 0.043
MATURITY          = 1
# endregion

# region DCF PARAMETERS
WACC_MEAN         = 0.09
WACC_STD          = 0.015
GROWTH_MEAN       = 0.03
GROWTH_STD        = 0.025
TERMINAL_GROWTH   = 0.02
FORECAST_YEARS    = 5
# endregion

# region MONTE CARLO
SIMULATIONS      = 10000
# endregion

# region OUTPUT
OUTPUT_DIR        = r"C:\Python\Outputs\Reports\DCF_Merton_MC"
# endregion
