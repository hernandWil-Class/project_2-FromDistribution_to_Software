"""Exponential survival likelihood, predictions, intervals, and diagnostics."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any, Literal

import numpy as np

LR_CHI2_95_DF1 = 3.841458820694124


@dataclass(frozen=True)
class FitResult:
    status: Literal["fitted", "not_fitted"]
    n: int
    events: int
    person_time: float
    rate: float | None
    units: str = "per month"
    time_unit: str = "months"

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe fields without undefined numeric values."""
        return asdict(self)


def _validated_inputs(durations: Any, events: Any) -> tuple[np.ndarray, np.ndarray]:
    raw_durations = np.asarray(durations, dtype=object)
    raw_events = np.asarray(events, dtype=object)
    if raw_durations.ndim != 1 or raw_events.ndim != 1:
        raise ValueError("durations and events must be one-dimensional")
    if len(raw_durations) != len(raw_events):
        raise ValueError("durations and events must have equal lengths")
    if len(raw_durations) == 0:
        raise ValueError("at least one observation is required")
    parsed_durations: list[float] = []
    for value in raw_durations:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise ValueError("durations must be finite and strictly positive")
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError("durations must be finite and strictly positive")
        parsed_durations.append(number)
    parsed_events: list[int] = []
    for value in raw_events:
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise ValueError("events must be exactly integer 0 or 1")
        numeric = float(value)
        if not math.isfinite(numeric) or numeric not in (0, 1):
            raise ValueError("events must be exactly 0 or 1")
        parsed_events.append(int(numeric))
    return np.asarray(parsed_durations), np.asarray(parsed_events, dtype=int)


def fit_exponential(durations: Any, events: Any) -> FitResult:
    """Fit the common hazard using lambda-hat = observed events / person-time."""
    times, observed = _validated_inputs(durations, events)
    n = len(times)
    event_count = int(observed.sum())
    person_time = math.fsum(times)
    if not math.isfinite(person_time) or person_time <= 0:
        raise ValueError("total person-time must be finite and positive")
    if event_count == 0:
        return FitResult("not_fitted", n, 0, person_time, None)
    rate = event_count / person_time
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("fitted rate is not representable as a finite positive number")
    return FitResult("fitted", n, event_count, person_time, rate)


def log_likelihood(rate: float, durations: Any, events: Any) -> float:
    """Return the right-censored exponential log-likelihood at a rate."""
    times, observed = _validated_inputs(durations, events)
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("rate must be finite and positive")
    total = int(observed.sum()) * math.log(rate) - math.fsum(times) * rate
    if not math.isfinite(total):
        raise ValueError("log-likelihood is not finite for these inputs")
    return total


def _validate_horizon(horizon: float) -> float:
    if isinstance(horizon, bool):
        raise ValueError("horizon must be finite and non-negative")
    try:
        value = float(horizon)
    except (TypeError, ValueError) as error:
        raise ValueError("horizon must be finite and non-negative") from error
    if not math.isfinite(value) or value < 0:
        raise ValueError("horizon must be finite and non-negative")
    return value


def _require_rate(rate: float) -> float:
    if isinstance(rate, bool) or not math.isfinite(rate) or rate <= 0:
        raise ValueError("rate must be finite and positive")
    return float(rate)


def survival_probability(rate: float, horizon: float) -> float:
    """Probability of remaining event-free beyond a non-negative horizon."""
    return math.exp(-_require_rate(rate) * _validate_horizon(horizon))


def event_probability(rate: float, horizon: float) -> float:
    """Probability of an event by a non-negative horizon."""
    return -math.expm1(-_require_rate(rate) * _validate_horizon(horizon))


def interval_event_probability(rate: float, start: float, end: float) -> float:
    """Unconditional probability of an event occurring between start and end."""
    rate_value = _require_rate(rate)
    first, last = _validate_horizon(start), _validate_horizon(end)
    if last < first:
        raise ValueError("end must be greater than or equal to start")
    return survival_probability(rate_value, first) - survival_probability(
        rate_value, last
    )


def conditional_survival(rate: float, elapsed: float, future: float) -> float:
    """Survival for an additional future duration given survival to elapsed."""
    _validate_horizon(elapsed)
    return survival_probability(rate, future)


def mean_survival_time(rate: float) -> float:
    return 1 / _require_rate(rate)


def median_survival_time(rate: float) -> float:
    return math.log(2) / _require_rate(rate)


def _bisect(function: Any, left: float, right: float) -> float:
    f_left = function(left)
    f_right = function(right)
    if f_left == 0:
        return left
    if f_right == 0:
        return right
    if f_left * f_right > 0:
        raise ArithmeticError("root is not bracketed")
    for _ in range(200):
        midpoint = (left + right) / 2
        f_mid = function(midpoint)
        if abs(f_mid) < 1e-14 or abs(right - left) < 1e-14:
            return midpoint
        if f_left * f_mid <= 0:
            right, f_right = midpoint, f_mid
        else:
            left, f_left = midpoint, f_mid
    return (left + right) / 2


def rate_intervals(fit: FitResult, z: float = 1.96) -> dict[str, tuple[float, float]]:
    """Return asymptotic log-Wald and likelihood-ratio 95%-style intervals."""
    if fit.status != "fitted" or fit.rate is None:
        raise ValueError("intervals require a fitted model")
    if not math.isfinite(z) or z <= 0:
        raise ValueError("z must be finite and positive")
    rate, events = fit.rate, fit.events
    se_log = 1 / math.sqrt(events)
    wald = (
        rate * math.exp(-z * se_log),
        rate * math.exp(z * se_log),
    )
    cutoff = LR_CHI2_95_DF1

    def deviance(log_ratio: float) -> float:
        ratio = math.exp(log_ratio)
        return 2 * events * (ratio - 1 - log_ratio) - cutoff

    left_edge = -1.0
    while deviance(left_edge) < 0:
        left_edge *= 2
    right_edge = 1.0
    while deviance(right_edge) < 0:
        right_edge *= 2
    lr = (
        rate * math.exp(_bisect(deviance, left_edge, 0)),
        rate * math.exp(_bisect(deviance, 0, right_edge)),
    )
    return {"log_wald": wald, "likelihood_ratio": lr}


def kaplan_meier(durations: Any, events: Any) -> list[dict[str, float | int]]:
    """Compute an aggregate Kaplan–Meier step curve, including time zero."""
    times, observed = _validated_inputs(durations, events)
    survival = 1.0
    result: list[dict[str, float | int]] = [
        {"time_months": 0.0, "survival": 1.0, "at_risk": len(times)}
    ]
    for time in np.unique(times[observed == 1]):
        at_risk = int(np.sum(times >= time))
        deaths = int(np.sum((times == time) & (observed == 1)))
        survival *= 1 - deaths / at_risk
        result.append(
            {
                "time_months": float(time),
                "survival": float(survival),
                "at_risk": at_risk,
            }
        )
    return result
