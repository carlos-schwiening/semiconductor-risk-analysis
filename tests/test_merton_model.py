"""
test_merton_model — Unit tests for the pure Merton model functions in Merton/merton_core.py.
Run with: python -m pytest tests/test_merton_model.py
"""

import os
import sys

MERTON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Merton")
if MERTON_DIR not in sys.path:
    sys.path.insert(0, MERTON_DIR)

from merton_core import merton_model, dd_band, BAND_LABELS, calculate_spread


# ----------------------------------------------------------------------------
# region MERTON_MODEL
# ----------------------------------------------------------------------------
def test_merton_model_pd_between_zero_and_one():
    """PD is a probability — must always be in [0, 1], regardless of input."""
    for E, D, sigma_e in [(100, 20, 0.25), (100, 95, 0.60), (50, 80, 0.90)]:
        result = merton_model(E=E, D=D, r=0.03, T=1, sigma_e=sigma_e)
        assert 0.0 <= result["pd"] <= 1.0


def test_merton_model_healthy_company_has_low_default_risk():
    """Large equity cushion + low volatility -> high DD, near-zero PD."""
    result = merton_model(E=100, D=20, r=0.03, T=1, sigma_e=0.25)
    assert result["dd"] > 8.0
    assert result["pd"] < 1e-10


def test_merton_model_distressed_company_has_high_default_risk():
    """Debt close to firm value + high volatility -> low DD, meaningful PD."""
    result = merton_model(E=100, D=95, r=0.03, T=1, sigma_e=0.60)
    assert result["dd"] < 3.0
    assert result["pd"] > 0.01


def test_merton_model_near_zero_debt_edge_case():
    """Negligible debt -> essentially no default risk (DD very high, PD ~0)."""
    result = merton_model(E=100, D=0.01, r=0.03, T=1, sigma_e=0.25)
    assert result["dd"] > 30.0
    assert result["pd"] < 1e-100
# endregion


# ----------------------------------------------------------------------------
# region DD_BAND
# ----------------------------------------------------------------------------
def test_dd_band_maps_a_high_dd_to_the_top_band():
    assert dd_band(dd=8.6) == "DD > 8"


def test_dd_band_maps_a_low_dd_to_the_bottom_band():
    assert dd_band(dd=0.5) == "DD < 1"


def test_a_negative_dd_still_lands_in_the_bottom_band():
    """Below the default point the model is out of range, not out of answers."""
    assert dd_band(dd=-2.0) == "DD < 1"


def test_every_band_edge_belongs_to_the_band_above_it():
    """The boundary is inclusive at the bottom, so 4.0 is 'DD 4-6', not 'DD 2-4'."""
    assert dd_band(4.0) == "DD 4-6"
    assert dd_band(3.999) == "DD 2-4"


def test_the_bands_carry_no_rating_letters():
    """
    The point of the rename. Letters made a reporting bucket look like a credit
    opinion and invited a comparison against agencies the model cannot support.
    """
    assert not any(any(c.isalpha() and c not in "Dd" for c in label)
                   for label in BAND_LABELS)
# endregion


# ----------------------------------------------------------------------------
# region CALCULATE_SPREAD
# ----------------------------------------------------------------------------
def test_calculate_spread_zero_pd_gives_zero_spread():
    assert calculate_spread(pd_val=0.0, T=1) == 0.0


def test_calculate_spread_increases_with_pd():
    """Higher default probability must translate into a wider credit spread."""
    low_spread  = calculate_spread(pd_val=0.01, T=1)
    high_spread = calculate_spread(pd_val=0.10, T=1)
    assert high_spread > low_spread
# endregion
