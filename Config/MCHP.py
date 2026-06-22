"""
Used by: Merton/Merton_Model.py, DCF/DCF_Valuation.py, MCS/Monte_Carlo_Sim.py
Microchip Technology - Configuration for DCF_Merton_MC
"""

# region COMPANY
COMPANY           = "Microchip Technology"
TICKER            = "MCHP"
RATING            = "BB+"
# endregion

# region MERTON PARAMETERS
RISK_FREE_RATE    = 0.043    # Risk-free rate
MATURITY          = 1        # Years
# endregion

# region DCF PARAMETERS
WACC_MEAN         = 0.10
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
