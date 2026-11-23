"""Validated input models shared by the CLI and services."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from numbers import Real
from typing import Annotated, Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class Observation(BaseModel):
    """One immutable synthetic follow-up observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    patient_id: Annotated[str, Field(min_length=1, max_length=128)]
    version: Annotated[StrictInt, Field(ge=1)]
    duration_months: float
    event_observed: StrictInt
    observed_at: datetime

    @field_validator("duration_months", mode="before")
    @classmethod
    def positive_finite_duration(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("duration_months must be a finite positive number")
        duration = float(value)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("duration_months must be finite and greater than zero")
        return duration

    @field_validator("event_observed", mode="before")
    @classmethod
    def binary_integer_before_cast(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1):
            raise ValueError("event_observed must be the integer 0 or 1")
        return cast(int, value)

    @field_validator("observed_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None:
            raise ValueError("observed_at must include a UTC timezone")
        if offset.total_seconds() != 0:
            raise ValueError("observed_at must be UTC")
        return value.astimezone(UTC)


class StoredObservation(Observation):
    """Observation envelope with database identity and ingestion time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: UUID
    ingested_at: datetime
    payload_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("ingested_at")
    @classmethod
    def ingestion_time_is_utc(cls, value: datetime) -> datetime:
        return Observation.require_utc_timestamp(value)


def canonical_observation_content(observation: Observation) -> dict[str, Any]:
    """Return canonical patient content, excluding retry/ingestion metadata."""
    return {
        "patient_id": observation.patient_id,
        "version": observation.version,
        "duration_months": observation.duration_months,
        "event_observed": observation.event_observed,
        "observed_at": observation.observed_at.isoformat(),
    }
