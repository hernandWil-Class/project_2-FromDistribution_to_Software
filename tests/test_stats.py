import math

import numpy as np
import pytest

from survivallab.stats import (
    conditional_survival,
    event_probability,
    fit_exponential,
    interval_event_probability,
    kaplan_meier,
    log_likelihood,
    mean_survival_time,
    median_survival_time,
    rate_intervals,
    survival_probability,
)

DURATIONS = [6, 10, 12, 15, 18, 20, 24, 30]
EVENTS = [1, 0, 1, 0, 1, 0, 1, 0]


def test_fixture_fit_and_predictions():
    fit = fit_exponential(DURATIONS, EVENTS)
    assert (fit.n, fit.events, fit.person_time) == (8, 4, 135)
    assert fit.rate == pytest.approx(4 / 135)
    assert survival_probability(fit.rate, 24) == pytest.approx(0.4910982295)
    assert survival_probability(fit.rate, 0) == 1
    assert event_probability(fit.rate, 24) == pytest.approx(-math.expm1(-24 * 4 / 135))
    assert mean_survival_time(fit.rate) == pytest.approx(33.75)
    assert median_survival_time(fit.rate) == pytest.approx(math.log(2) * 33.75)
    assert conditional_survival(fit.rate, 18, 6) == survival_probability(fit.rate, 6)
    assert interval_event_probability(fit.rate, 6, 12) == pytest.approx(
        survival_probability(fit.rate, 6) - survival_probability(fit.rate, 12)
    )


def test_intervals_match_contract():
    fit = fit_exponential(DURATIONS, EVENTS)
    intervals = rate_intervals(fit)
    assert intervals["likelihood_ratio"] == pytest.approx(
        (0.0091985194, 0.0688318046), abs=1e-9
    )
    assert intervals["log_wald"] == pytest.approx((0.01112033, 0.07894685), abs=1e-8)


@pytest.mark.parametrize(
    ("durations", "events"),
    [
        ([], []),
        ([1], [1, 0]),
        ([[1]], [1]),
        ([0], [1]),
        ([float("nan")], [1]),
        ([1], [0.5]),
        ([1], [True]),
    ],
)
def test_invalid_fit_input(durations, events):
    with pytest.raises(ValueError):
        fit_exponential(durations, events)


def test_zero_events_boundary_and_horizon_validation():
    fit = fit_exponential([2, 4], [0, 0])
    assert fit.status == "not_fitted"
    assert fit.rate is None
    for horizon in (-1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            survival_probability(0.2, horizon)
    with pytest.raises(ValueError):
        interval_event_probability(0.2, 5, 2)


def test_scale_equivalence_unit_invariance_and_km():
    fit = fit_exponential(DURATIONS, EVENTS)
    scaled = fit_exponential(np.array(DURATIONS) * 12, EVENTS)
    assert scaled.rate == pytest.approx(fit.rate / 12)
    assert fit.rate == pytest.approx(1 / (135 / 4))
    curve = kaplan_meier(DURATIONS, EVENTS)
    assert curve[0]["survival"] == 1
    assert all(
        left["survival"] >= right["survival"]
        for left, right in zip(curve, curve[1:], strict=False)
    )
    assert log_likelihood(fit.rate, DURATIONS, EVENTS) < 0


def test_binary_float_events_are_validated_before_cast():
    fit = fit_exponential([2, 4], np.array([1.0, 0.0]))
    assert (fit.events, fit.person_time) == (1, 6)
    with pytest.raises(ValueError):
        fit_exponential([2, 4], np.array([1.0, 0.5]))
    with pytest.raises(ValueError):
        fit_exponential(["2"], [1])
