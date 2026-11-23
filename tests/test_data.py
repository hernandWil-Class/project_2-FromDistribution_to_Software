from datetime import UTC

import pytest
from pydantic import ValidationError

from survivallab.data import fixed_fixture, generate_cohort, validate_csv, write_cohort
from survivallab.models import Observation


def test_fixture_matches_contract():
    rows = fixed_fixture()
    assert [row.patient_id for row in rows] == [f"P{i:03}" for i in range(1, 9)]
    assert sum(row.event_observed for row in rows) == 4
    assert sum(row.duration_months for row in rows) == 135


def test_generator_is_deterministic_and_truth_is_separate(tmp_path):
    first = generate_cohort(size=25, seed=7)
    second = generate_cohort(size=25, seed=7)
    other = generate_cohort(size=25, seed=8)
    assert first == second
    assert first.observations != other.observations
    write_cohort(first, tmp_path)
    assert validate_csv(tmp_path / "observed.csv") == []
    assert "event_time_months" not in (tmp_path / "observed.csv").read_text()
    assert "event_time_months" in (tmp_path / "simulation_truth.csv").read_text()


def observation(**overrides):
    data = {
        "patient_id": "P001",
        "version": 1,
        "duration_months": 2,
        "event_observed": 0,
        "observed_at": "2026-01-01T00:00:00Z",
    }
    return Observation.model_validate({**data, **overrides})


def test_observation_strict_validation():
    assert observation().observed_at.tzinfo == UTC
    with pytest.raises(ValidationError):
        observation(event_observed=0.5)
    with pytest.raises(ValidationError):
        observation(duration_months=float("inf"))
    with pytest.raises(ValidationError):
        observation(duration_months=0)
    with pytest.raises(ValidationError):
        observation(unexpected="extra")
    with pytest.raises(ValidationError):
        observation(observed_at="2026-01-01T00:00:00")


def test_generator_rejects_bad_settings():
    with pytest.raises(ValueError):
        generate_cohort(size=0, seed=1)
    with pytest.raises(ValueError):
        generate_cohort(size=2, seed=1, rate=float("nan"))
