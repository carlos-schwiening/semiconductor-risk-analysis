"""
test_dcf_core — Unit tests for the pure DCF functions in DCF/dcf_core.py.
Run with: python -m pytest tests/test_dcf_core.py
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

DCF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "DCF")
if DCF_DIR not in sys.path:
    sys.path.insert(0, DCF_DIR)

from dcf_core import (cagr, calculate_beta, classify_valuation, compute_multiples,
                      cost_of_debt, dcf_full, dcf_schedule, effective_tax_rate,
                      g2_sensitivity, rate_multiple, sensitivity_matrix,
                      simulate_dcf, wacc_capm, with_params)


def params(**overrides):
    """Base DcfParams for the tests, individual fields overridable."""
    base = {
        "fcf_start": 100.0, "g1": 0.05, "g2": 0.025, "wacc": 0.10,
        "years": 5, "net_debt": 0.0, "shares": 1.0,
    }
    base.update(overrides)
    return base


# region dcf_full
def test_dcf_full_zero_growth_equals_perpetuity():
    """With g1 = g2 = 0 the whole model must collapse to FCF / WACC."""
    result = dcf_full(params(fcf_start=100.0, g1=0.0, g2=0.0, wacc=0.10, years=5))
    assert result["ev"] == pytest.approx(1000.0)


def test_dcf_full_perpetuity_independent_of_forecast_length():
    """Splitting the same cash flows differently between phases cannot change EV."""
    ev_1y = dcf_full(params(g1=0.0, g2=0.0, wacc=0.10, years=1))["ev"]
    ev_20y = dcf_full(params(g1=0.0, g2=0.0, wacc=0.10, years=20))["ev"]
    assert ev_1y == pytest.approx(ev_20y)


def test_dcf_full_higher_wacc_lowers_value():
    """Monotonicity: a higher discount rate must never raise the valuation."""
    values = [dcf_full(params(wacc=w))["value_per_share"] for w in [0.08, 0.10, 0.12, 0.14]]
    assert all(a > b for a, b in zip(values, values[1:]))


def test_dcf_full_higher_growth_raises_value():
    values = [dcf_full(params(g1=g))["value_per_share"] for g in [0.02, 0.04, 0.06, 0.08]]
    assert all(a < b for a, b in zip(values, values[1:]))


def test_dcf_full_returns_nan_when_wacc_not_above_g2():
    """The Gordon terminal value is undefined for wacc <= g2 — no division blow-up."""
    for wacc in [0.025, 0.02, 0.0]:
        result = dcf_full(params(wacc=wacc, g2=0.025))
        assert all(np.isnan(v) for v in result.values())


def test_dcf_full_net_debt_reduces_equity_one_for_one():
    no_debt = dcf_full(params(net_debt=0.0))
    with_debt = dcf_full(params(net_debt=250.0))
    assert no_debt["equity"] - with_debt["equity"] == pytest.approx(250.0)
    assert no_debt["ev"] == pytest.approx(with_debt["ev"])


def test_dcf_full_zero_shares_gives_nan_per_share_not_crash():
    result = dcf_full(params(shares=0.0))
    assert np.isnan(result["value_per_share"])
    assert not np.isnan(result["ev"])
# endregion


# region dcf_schedule
def test_dcf_schedule_has_one_row_per_forecast_year():
    schedule, _ = dcf_schedule(params(years=7))
    assert len(schedule) == 7
    assert [row["Year"] for row in schedule] == [1, 2, 3, 4, 5, 6, 7]


def test_dcf_schedule_pv_sum_plus_terminal_equals_ev():
    """The schedule must reconcile with the headline EV — no silently dropped year."""
    schedule, result = dcf_schedule(params())
    pv_sum = sum(row["PV_FCF"] for row in schedule)
    assert pv_sum + result["pv_terminal_value"] == pytest.approx(result["ev"])


def test_dcf_schedule_matches_dcf_full():
    p = params(g1=0.07, wacc=0.11)
    _, from_schedule = dcf_schedule(p)
    assert from_schedule == dcf_full(p)


def test_dcf_schedule_discounting_shrinks_later_years():
    """FCF grows, but its present value must grow more slowly (or fall)."""
    schedule, _ = dcf_schedule(params(g1=0.05, wacc=0.10))
    assert schedule[-1]["FCF"] > schedule[0]["FCF"]
    assert schedule[-1]["PV_FCF"] < schedule[0]["PV_FCF"]
# endregion


# region with_params
def test_with_params_does_not_mutate_the_original():
    original = params()
    modified = with_params(original, wacc=0.20)
    assert modified["wacc"] == 0.20
    assert original["wacc"] == 0.10


def test_with_params_keeps_untouched_fields():
    modified = with_params(params(), g1=0.09)
    assert modified["fcf_start"] == 100.0
    assert modified["years"] == 5
# endregion


# region CAPM / WACC
def _price_series(returns):
    idx = pd.date_range("2020-01-01", periods=len(returns) + 1, freq="D")
    return pd.Series(100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)])), index=idx)


def test_calculate_beta_of_market_against_itself_is_one():
    rng = np.random.default_rng(0)
    market = _price_series(rng.normal(0, 0.01, 300))
    assert calculate_beta(market, market) == pytest.approx(1.0)


def test_calculate_beta_detects_double_amplitude():
    """A stock moving exactly twice as hard as the market has beta 2."""
    rng = np.random.default_rng(0)
    market_returns = rng.normal(0, 0.01, 300)
    market = _price_series(market_returns)
    stock = _price_series(2 * market_returns)
    assert calculate_beta(stock, market) == pytest.approx(2.0)


def test_cost_of_debt_basic_ratio():
    assert cost_of_debt(interest_expense=50.0, total_debt=1000.0) == pytest.approx(0.05)


def test_cost_of_debt_without_debt_is_zero():
    assert cost_of_debt(interest_expense=0.0, total_debt=1000.0) == 0.0
    assert cost_of_debt(interest_expense=50.0, total_debt=0.0) == 0.0


def test_effective_tax_rate_averages_profitable_years():
    assert effective_tax_rate([(200.0, 1000.0), (100.0, 1000.0)]) == pytest.approx(0.15)


def test_effective_tax_rate_ignores_loss_years():
    """A loss year would produce a meaningless negative rate — it must be skipped."""
    with_loss = effective_tax_rate([(200.0, 1000.0), (50.0, -400.0)])
    assert with_loss == pytest.approx(0.20)


def test_effective_tax_rate_falls_back_when_no_profitable_year():
    assert effective_tax_rate([]) == pytest.approx(0.21)
    assert effective_tax_rate([(0.0, -100.0)], default=0.25) == pytest.approx(0.25)


def test_wacc_capm_without_debt_equals_cost_of_equity():
    result = wacc_capm(beta=1.2, risk_free=0.04, kd=0.0, tax_rate=0.21,
                       market_cap=1000.0, total_debt=0.0)
    assert result["ke"] == pytest.approx(0.04 + 1.2 * 0.055)
    assert result["wacc_calc"] == pytest.approx(result["ke"])
    assert result["ev_ratio"] == pytest.approx(1.0)


def test_wacc_capm_weights_sum_to_one():
    result = wacc_capm(beta=1.0, risk_free=0.04, kd=0.05, tax_rate=0.21,
                       market_cap=600.0, total_debt=400.0)
    assert result["ev_ratio"] + result["dv_ratio"] == pytest.approx(1.0)
    assert result["kd_after_tax"] == pytest.approx(0.05 * 0.79)


def test_wacc_capm_debt_lowers_wacc_via_tax_shield():
    """Cheap after-tax debt in the mix must pull the WACC below pure equity cost."""
    equity_only = wacc_capm(beta=1.0, risk_free=0.04, kd=0.05, tax_rate=0.21,
                            market_cap=1000.0, total_debt=0.0)
    levered = wacc_capm(beta=1.0, risk_free=0.04, kd=0.05, tax_rate=0.21,
                        market_cap=600.0, total_debt=400.0)
    assert levered["wacc_calc"] < equity_only["wacc_calc"]


def test_wacc_capm_without_capital_base_falls_back_to_ke():
    result = wacc_capm(beta=1.0, risk_free=0.04, kd=0.05, tax_rate=0.21,
                       market_cap=0.0, total_debt=0.0)
    assert result["wacc_calc"] == pytest.approx(result["ke"])
# endregion


# region Sensitivity
def test_sensitivity_matrix_has_wacc_rows_and_growth_columns():
    matrix = sensitivity_matrix(params(), [0.08, 0.10, 0.12], [0.02, 0.04, 0.06, 0.08])
    assert len(matrix) == 3
    assert all(len(row) == 4 for row in matrix)


def test_sensitivity_matrix_falls_down_the_wacc_axis():
    matrix = sensitivity_matrix(params(), [0.08, 0.10, 0.12], [0.02, 0.05])
    for col in range(2):
        column = [matrix[row][col] for row in range(3)]
        assert all(a > b for a, b in zip(column, column[1:]))


def test_sensitivity_matrix_marks_impossible_combinations_as_nan():
    matrix = sensitivity_matrix(params(g2=0.025), [0.02, 0.10], [0.05])
    assert np.isnan(matrix[0][0])
    assert not np.isnan(matrix[1][0])


def test_g2_sensitivity_base_row_has_zero_delta():
    rows = g2_sensitivity(params(), [0.015, 0.025, 0.035], g2_base=0.025)
    base_row = next(r for r in rows if r["g2"] == 0.025)
    assert base_row["delta_pct"] == pytest.approx(0.0)


def test_g2_sensitivity_value_rises_with_terminal_growth():
    rows = g2_sensitivity(params(), [0.015, 0.020, 0.025, 0.030, 0.035], g2_base=0.025)
    values = [r["value_per_share"] for r in rows]
    assert all(a < b for a, b in zip(values, values[1:]))
    assert rows[0]["delta_pct"] < 0 < rows[-1]["delta_pct"]
# endregion


# region Monte Carlo
def test_simulate_dcf_is_reproducible_for_a_fixed_seed():
    kwargs = dict(n=500, wacc_std=0.015, growth_std=0.02, fcf_std_factor=0.15)
    first = simulate_dcf(params(), seed=42, **kwargs)
    second = simulate_dcf(params(), seed=42, **kwargs)
    assert np.array_equal(first, second)


def test_simulate_dcf_differs_across_seeds():
    kwargs = dict(n=500, wacc_std=0.015, growth_std=0.02, fcf_std_factor=0.15)
    assert not np.array_equal(simulate_dcf(params(), seed=1, **kwargs),
                              simulate_dcf(params(), seed=2, **kwargs))


def test_simulate_dcf_drops_undefined_runs_and_keeps_the_rest():
    result = simulate_dcf(params(), n=500, wacc_std=0.015, growth_std=0.02,
                          fcf_std_factor=0.15)
    assert 0 < len(result) <= 500
    assert np.all(np.isfinite(result))


def test_simulate_dcf_centres_near_the_deterministic_case():
    """Symmetric noise around the base case must not shift the median far off it."""
    base = dcf_full(params())["value_per_share"]
    result = simulate_dcf(params(), n=5000, wacc_std=0.01, growth_std=0.01,
                          fcf_std_factor=0.10)
    assert np.median(result) == pytest.approx(base, rel=0.15)


def test_simulate_dcf_wider_spread_with_more_uncertainty():
    narrow = simulate_dcf(params(), n=2000, wacc_std=0.005, growth_std=0.005,
                          fcf_std_factor=0.05)
    wide = simulate_dcf(params(), n=2000, wacc_std=0.02, growth_std=0.02,
                        fcf_std_factor=0.25)
    assert np.std(wide) > np.std(narrow)


def test_simulate_dcf_survives_negative_starting_fcf():
    """INTC can have a negative normalized FCF — the draw width uses abs()."""
    result = simulate_dcf(params(fcf_start=-500.0), n=200, wacc_std=0.015,
                          growth_std=0.02, fcf_std_factor=0.15)
    assert len(result) > 0
    assert np.all(np.isfinite(result))
# endregion


# region Classification & Multiples
def test_cagr_known_doubling():
    assert cagr(newest=200.0, oldest=100.0, periods=4) == pytest.approx(2 ** 0.25 - 1)


def test_cagr_flat_series_is_zero():
    assert cagr(newest=100.0, oldest=100.0, periods=4) == pytest.approx(0.0)


def test_cagr_is_nan_on_sign_change_or_zero_base():
    """A swing from loss to profit has no meaningful growth rate."""
    assert np.isnan(cagr(newest=100.0, oldest=-100.0, periods=4))
    assert np.isnan(cagr(newest=100.0, oldest=0.0, periods=4))


def test_classify_valuation_thresholds():
    assert classify_valuation(15.0) == "UNDERVALUED"
    assert classify_valuation(-15.0) == "OVERVALUED"
    assert classify_valuation(0.0) == "FAIR"
    assert classify_valuation(10.0) == "FAIR"
    assert classify_valuation(-10.0) == "FAIR"


def test_classify_valuation_treats_nan_as_fair():
    assert classify_valuation(float("nan")) == "FAIR"


def test_rate_multiple_bands():
    assert rate_multiple(10.0, 15.0, 25.0) == "CHEAP"
    assert rate_multiple(20.0, 15.0, 25.0) == "FAIR"
    assert rate_multiple(30.0, 15.0, 25.0) == "EXPENSIVE"
    assert rate_multiple(float("nan"), 15.0, 25.0) == "N/A"


def test_compute_multiples_known_values():
    result = compute_multiples(ev=1000.0, ebitda=100.0, revenue=500.0,
                               price=50.0, net_income=200.0, shares=100.0)
    assert result["EV/EBITDA"] == pytest.approx(10.0)
    assert result["EV/Sales"] == pytest.approx(2.0)
    assert result["P/E"] == pytest.approx(25.0)


def test_compute_multiples_nan_on_loss_or_missing_denominator():
    result = compute_multiples(ev=1000.0, ebitda=0.0, revenue=0.0,
                               price=50.0, net_income=-200.0, shares=100.0)
    assert all(np.isnan(v) for v in result.values())
# endregion
