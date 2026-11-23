"""Deterministic synthetic observation fixtures and generators."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from survivallab.models import Observation

DEFAULT_TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)
OBSERVED_FIELDS = (
    "patient_id",
    "version",
    "duration_months",
    "event_observed",
    "observed_at",
)


@dataclass(frozen=True)
class SyntheticCohort:
    observations: tuple[Observation, ...]
    truth: tuple[dict[str, float | str], ...]
    metadata: dict[str, Any]


def fixed_fixture() -> tuple[Observation, ...]:
    """Return the contract's fixed eight-observation teaching fixture."""
    durations = [6, 10, 12, 15, 18, 20, 24, 30]
    events = [1, 0, 1, 0, 1, 0, 1, 0]
    return tuple(
        Observation(
            patient_id=f"P{index:03d}",
            version=1,
            duration_months=duration,
            event_observed=event,
            observed_at=DEFAULT_TIMESTAMP,
        )
        for index, (duration, event) in enumerate(
            zip(durations, events, strict=True), start=1
        )
    )


def generate_cohort(
    *,
    size: int,
    seed: int,
    rate: float = 0.03,
    censor_min: float = 12.0,
    censor_max: float = 60.0,
    observed_at: datetime = DEFAULT_TIMESTAMP,
) -> SyntheticCohort:
    """Generate reproducible exponential event times and uniform censoring."""
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ValueError("size must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if not np.isfinite(rate) or rate <= 0:
        raise ValueError("rate must be finite and positive")
    if (
        not np.isfinite(censor_min)
        or not np.isfinite(censor_max)
        or censor_min < 0
        or censor_max <= censor_min
    ):
        raise ValueError("censor bounds must be finite, non-negative, and increasing")
    offset = observed_at.utcoffset()
    if observed_at.tzinfo is None or offset is None:
        raise ValueError("observed_at must be timezone-aware UTC")
    if offset.total_seconds() != 0:
        raise ValueError("observed_at must be UTC")

    rng = np.random.default_rng(seed)
    event_times = rng.exponential(scale=1 / rate, size=size)
    censor_times = rng.uniform(censor_min, censor_max, size=size)
    durations = np.minimum(event_times, censor_times)
    events = (event_times <= censor_times).astype(int)
    stamp = observed_at.astimezone(UTC)
    observations = tuple(
        Observation(
            patient_id=f"P{index:03d}",
            version=1,
            duration_months=float(duration),
            event_observed=int(event),
            observed_at=stamp,
        )
        for index, (duration, event) in enumerate(
            zip(durations, events, strict=True), start=1
        )
    )
    truth: tuple[dict[str, float | str], ...] = tuple(
        {
            "patient_id": f"P{index:03d}",
            "event_time_months": float(event_time),
            "censor_time_months": float(censor_time),
        }
        for index, (event_time, censor_time) in enumerate(
            zip(event_times, censor_times, strict=True), start=1
        )
    )
    metadata = {
        "seed": seed,
        "cohort_size": size,
        "true_rate_per_month": rate,
        "censoring": {
            "distribution": "uniform",
            "min_months": censor_min,
            "max_months": censor_max,
        },
        "observed_at": stamp.isoformat(),
        "time_unit": "months",
    }
    return SyntheticCohort(observations, truth, metadata)


def write_cohort(cohort: SyntheticCohort, output_dir: Path) -> None:
    """Write observed data, simulation truth, and generator metadata separately."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "observed.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=OBSERVED_FIELDS)
        writer.writeheader()
        for row in cohort.observations:
            writer.writerow(
                {
                    **row.model_dump(mode="json"),
                    "duration_months": format(row.duration_months, ".17g"),
                }
            )
    with (output_dir / "simulation_truth.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        fields = ["patient_id", "event_time_months", "censor_time_months"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(cohort.truth)
    (output_dir / "metadata.json").write_text(
        json.dumps(cohort.metadata, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def validate_csv(path: Path) -> list[str]:
    """Return row-scoped validation errors; an empty list means valid input."""
    errors: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(OBSERVED_FIELDS):
            return [
                f"header: expected {','.join(OBSERVED_FIELDS)}, got "
                f"{','.join(reader.fieldnames or [])}"
            ]
        for line, row in enumerate(reader, start=2):
            try:
                parsed: dict[str, Any] = dict(row)
                parsed["version"] = int(parsed["version"])
                parsed["event_observed"] = int(parsed["event_observed"])
                parsed["duration_months"] = float(parsed["duration_months"])
                Observation.model_validate(parsed)
            except (ValueError, TypeError) as error:
                errors.append(f"row {line}: {error}")
    return errors
