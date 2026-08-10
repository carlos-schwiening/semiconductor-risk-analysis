"""
test_mcs_core — Unit tests for MCS/mcs_core.py.
Run with: python -m pytest tests/test_mcs_core.py

Most of these test invariants rather than values. The two defects this module was
extracted for were not wrong arithmetic — every line computed exactly what it
said — but results that no arithmetic check would question: a loss above 100% of
the invested amount, and a base case that disagreed with the headline figure
because one of five copies of the same three lines had not been corrected.

So the assertions here are of the form "this can never happen", not "this equals
that". A stock cannot lose more than everything; a conditional VaR cannot fall
below its VaR; a scenario the model could not evaluate must not be recorded as a
total loss.
"""

import os
import sys

import numpy as np
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "MCS")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from mcs_core import (DISTRIBUTIONS, REL_CAP, REL_FLOOR, apply_distribution,
                      correlation_matrix, dcf_array, diversification_benefit,
                      loss_percent, relative_value, risk_measures,
                      sample_distribution, vasicek_conditional_pd)


# ----------------------------------------------------------------------------
# region LIMITED LIABILITY
# ----------------------------------------------------------------------------
def test_a_loss_can_never_exceed_one_hundred_percent():
    """
    The defect this module exists for.

    A shareholder cannot lose more than the amount invested. With the floor at
    zero this holds for any input, however extreme — which is why the test feeds
    values far beyond anything the simulation would produce.
    """
    absurd = np.array([-1e9, -5.0, -1.0, 0.0, 1.0, 1e9])
    losses = loss_percent(relative_value(absurd, price=100.0))
    assert losses.max() <= 100.0


def test_relative_value_is_floored_at_zero():
    values = np.array([-500.0, -1.0, 0.0, 50.0])
    assert relative_value(values, price=100.0).min() == REL_FLOOR


def test_relative_value_is_capped():
    """A six-fold outcome says the input distribution has a fat tail, not that
    the company is worth that much; uncapped it would dominate the average."""
    assert relative_value(np.array([1e6]), price=100.0)[0] == REL_CAP


def test_a_scenario_the_model_could_not_evaluate_is_not_a_total_loss():
    """
    NaN means "no result", and recording it as a wipeout would invent a default
    the model never predicted. It is carried as an unchanged value instead.
    """
    rel = relative_value(np.array([np.nan, np.nan]), price=100.0)
    assert np.all(rel == 1.0)
    assert np.all(loss_percent(rel) == 0.0)


def test_a_price_of_zero_does_not_divide():
    rel = relative_value(np.array([42.0]), price=0.0)
    assert np.all(np.isfinite(rel))


def test_an_unchanged_value_is_a_loss_of_zero():
    assert loss_percent(relative_value(np.array([80.0]), price=80.0))[0] == pytest.approx(0.0)


def test_a_halved_value_is_a_loss_of_fifty_percent():
    assert loss_percent(relative_value(np.array([40.0]), price=80.0))[0] == pytest.approx(50.0)
# endregion


# ----------------------------------------------------------------------------
# region RISK MEASURES
# ----------------------------------------------------------------------------
def test_cvar_is_never_below_its_var():
    """
    CVaR averages the losses at or beyond VaR 99, so it cannot come out lower.
    A violation would mean the tail was taken from the wrong end.
    """
    rng = np.random.default_rng(7)
    for _ in range(20):
        losses = rng.normal(0, 25, 5_000)
        measures = risk_measures(losses)
        assert measures.cvar_99 >= measures.var_99


def test_var_grows_with_the_confidence_level():
    losses = np.random.default_rng(1).normal(0, 25, 10_000)
    measures = risk_measures(losses)
    assert measures.var_95 <= measures.var_99


def test_risk_measures_of_a_constant_distribution_all_agree():
    measures = risk_measures(np.full(1_000, 12.5))
    assert measures.var_95 == pytest.approx(12.5)
    assert measures.var_99 == pytest.approx(12.5)
    assert measures.cvar_99 == pytest.approx(12.5)


def test_risk_measures_stay_within_the_possible_range_for_real_inputs():
    """The headline figures are percentages of capital: bounded by 100."""
    rng = np.random.default_rng(3)
    values = rng.normal(100.0, 40.0, 20_000)
    measures = risk_measures(loss_percent(relative_value(values, price=100.0)))
    assert measures.var_99 <= 100.0
    assert measures.cvar_99 <= 100.0


def test_diversification_benefit_is_zero_without_dispersion():
    assert diversification_benefit(portfolio_std=5.0, average_single_std=0.0) == 0.0


def test_diversification_benefit_grows_as_the_portfolio_steadies():
    assert diversification_benefit(5.0, 10.0) == pytest.approx(0.5)
    assert diversification_benefit(10.0, 10.0) == pytest.approx(0.0)
# endregion


# ----------------------------------------------------------------------------
# region VASICEK
# ----------------------------------------------------------------------------
def test_conditional_pd_averages_to_the_unconditional_one():
    """
    Integrating the conditional PD over the systematic factor must return the
    input. If it does not, the threshold or the scaling is wrong.
    """
    z = np.random.default_rng(11).normal(0, 1, 200_000)
    conditional = vasicek_conditional_pd(0.02, rho=0.20, systematic=z)
    assert float(np.mean(conditional)) == pytest.approx(0.02, abs=0.001)


def test_a_bad_systematic_draw_raises_the_default_probability():
    """Negative Z is the downturn; every borrower gets riskier at once, which is
    what makes the loss distribution skewed rather than binomial."""
    bad = vasicek_conditional_pd(0.02, 0.20, np.array([-2.0]))[0]
    good = vasicek_conditional_pd(0.02, 0.20, np.array([2.0]))[0]
    assert bad > 0.02 > good


def test_conditional_pd_stays_a_probability():
    z = np.random.default_rng(5).normal(0, 1, 50_000)
    conditional = vasicek_conditional_pd(0.05, 0.35, z)
    assert conditional.min() >= 0.0 and conditional.max() <= 1.0


def test_correlation_matrix_is_valid():
    matrix = correlation_matrix(5, 0.60)
    assert np.allclose(np.diag(matrix), 1.0)
    assert np.allclose(matrix, matrix.T)
    np.linalg.cholesky(matrix)      # raises if not positive definite
# endregion


# ----------------------------------------------------------------------------
# region INPUT DISTRIBUTIONS
# ----------------------------------------------------------------------------
def test_the_same_seed_reproduces_the_same_samples():
    """Without this a published figure cannot be recomputed by anyone."""
    first = sample_distribution("WACC", 0.10, 500, seed=42)
    second = sample_distribution("WACC", 0.10, 500, seed=42)
    assert np.array_equal(first, second)


def test_different_seeds_give_different_samples():
    assert not np.array_equal(sample_distribution("WACC", 0.10, 500, seed=1),
                              sample_distribution("WACC", 0.10, 500, seed=2))


@pytest.mark.parametrize("name", list(DISTRIBUTIONS))
def test_every_configured_distribution_produces_finite_samples(name):
    samples = sample_distribution(name, 0.10, 1_000, seed=42)
    assert samples.shape == (1_000,)
    assert np.all(np.isfinite(samples))


def test_bounded_distributions_respect_their_bounds():
    for name in ("g1", "g2"):
        spec = DISTRIBUTIONS[name]
        samples = sample_distribution(name, (spec["min"] + spec["max"]) / 2, 5_000, seed=42)
        assert samples.min() >= spec["min"]
        assert samples.max() <= spec["max"]


def test_a_negative_mean_does_not_break_the_lognormal():
    """
    INTC's normalised free cash flow is negative, and a lognormal has no negative
    values. The fallback keeps the simulation running; the calling script reports
    the model as inapplicable rather than printing the number.
    """
    samples = sample_distribution("FCF", -1.5e9, 1_000, seed=42)
    assert np.all(np.isfinite(samples))
    assert float(np.mean(samples)) < 0


def test_the_copula_transform_preserves_order():
    """
    The Gaussian copula must be monotone in z: correlation is generated among the
    normal variables and would be destroyed if the mapping reordered them.
    """
    z = np.linspace(-3, 3, 200)
    for name in ("WACC", "g2", "FCF"):
        mapped = apply_distribution(name, 0.10 if name != "FCF" else 2.5e9, z)
        assert np.all(np.diff(mapped) >= -1e-9), name


def test_the_copula_matches_the_configured_spread():
    """A z of zero must land on the mean of a normal margin."""
    assert apply_distribution("WACC", 0.09, np.array([0.0]))[0] == pytest.approx(0.09)
    assert apply_distribution("WACC", 0.09, np.array([1.0]))[0] == pytest.approx(
        0.09 + DISTRIBUTIONS["WACC"]["std"])
# endregion


# ----------------------------------------------------------------------------
# region VECTORISED DCF
# ----------------------------------------------------------------------------
def _flat(value: float, n: int = 4) -> np.ndarray:
    return np.full(n, value)


def test_a_discount_rate_below_terminal_growth_yields_no_value():
    """
    The Gordon formula divides by (wacc - g2). Below that point it returns a
    negative or explosive terminal value that still looks like a result, so the
    scenario is marked unusable instead.
    """
    result = dcf_array(_flat(0.02), _flat(0.03), _flat(1e9), _flat(0.03),
                       prog=5, nd=0.0, shares=1e6)
    assert np.all(np.isnan(result))


def test_more_debt_lowers_the_value_per_share():
    args = dict(prog=5, shares=1e6)
    low = dcf_array(_flat(0.09), _flat(0.03), _flat(1e9), _flat(0.02), nd=0.0, **args)
    high = dcf_array(_flat(0.09), _flat(0.03), _flat(1e9), _flat(0.02), nd=5e8, **args)
    assert np.all(high < low)


def test_a_higher_discount_rate_lowers_the_value():
    args = dict(g1_arr=_flat(0.03), fcf_start_arr=_flat(1e9), g2_arr=_flat(0.02),
                prog=5, nd=0.0, shares=1e6)
    assert np.all(dcf_array(_flat(0.12), **args) < dcf_array(_flat(0.08), **args))


def test_zero_shares_yield_no_per_share_value():
    result = dcf_array(_flat(0.09), _flat(0.03), _flat(1e9), _flat(0.02),
                       prog=5, nd=0.0, shares=0.0)
    assert np.all(np.isnan(result))


def test_it_computes_the_same_result_as_a_hand_written_loop():
    """
    One scenario, checked against the textbook two-phase formula written out
    step by step. The vectorised version exists for speed, not for a different
    answer.
    """
    wacc, g1, g2, fcf0, years, net_debt, shares = 0.09, 0.04, 0.02, 1_000.0, 5, 200.0, 10.0

    fcf, pv = fcf0, 0.0
    for t in range(1, years + 1):
        fcf *= (1 + g1)
        pv += fcf / (1 + wacc) ** t
    terminal = fcf * (1 + g2) / (wacc - g2)
    expected = (pv + terminal / (1 + wacc) ** years - net_debt) / shares

    actual = dcf_array(_flat(wacc, 1), _flat(g1, 1), _flat(fcf0, 1), _flat(g2, 1),
                       prog=years, nd=net_debt, shares=shares)[0]
    assert actual == pytest.approx(expected)
# endregion
