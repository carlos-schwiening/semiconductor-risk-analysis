"""
fmp_extract — Reads the local FMP JSON cache and maps its fields to plain numbers.

This is the only module that knows FMP field names. Everything downstream
(dcf_core in particular) works on plain floats and stays independent of the data
provider, so swapping the source means changing this file and nothing else.
"""

import json
import os
from typing import Any, Sequence

import pandas as pd

# Project root = semiconductor-risk-analysis/ (1 level up from DCF/)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Cache lives outside the repo: set FMP_CACHE_DIR, else the project-local default applies.
CACHE_DIR = os.environ.get("FMP_CACHE_DIR", os.path.join(PROJECT_ROOT, "data", "FMP_Cache"))


# ----------------------------------------------------------------------------
# region CACHE ACCESS
# ----------------------------------------------------------------------------
def load_json(filename: str) -> Any:
    """Load a JSON cache file and return its contents."""
    path = os.path.join(CACHE_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_prices(filename: str) -> pd.Series:
    """Closing prices from a cached price file, indexed by date and sorted ascending."""
    df = pd.DataFrame(load_json(filename))
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").set_index("date")["close"]
# endregion


# ----------------------------------------------------------------------------
# region FIELD MAPPING
# ----------------------------------------------------------------------------
def extract_wacc_inputs(
    income_data: Sequence[dict[str, Any]],
    total_debt: float,
) -> tuple[float, list[tuple[float, float]]]:
    """
    Pull the CAPM-relevant figures out of FMP income-statement entries.

    Returns (interest expense of the most recent year that carries debt service,
             [(income tax expense, income before tax), ...] for every year).
    Filtering out loss years is left to dcf_core.effective_tax_rate().
    """
    interest_expense = 0.0
    for entry in income_data:
        i_exp = float(entry.get("interestExpense", 0) or 0)
        if i_exp > 0 and total_debt > 0:
            interest_expense = i_exp
            break

    tax_and_ebt = [
        (float(e.get("incomeTaxExpense", 0) or 0), float(e.get("incomeBeforeTax", 0) or 0))
        for e in income_data
    ]
    return interest_expense, tax_and_ebt
# endregion
