import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from survivallab.db.repository import CorrectionError, ObservationConflict, Repository
from survivallab.models import Observation

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("SURVIVALLAB_TEST_DATABASE_URL"),
        reason="set SURVIVALLAB_TEST_DATABASE_URL to a disposable PostgreSQL database",
    ),
]


@pytest.fixture(scope="module")
def repository():
    url = os.environ["SURVIVALLAB_TEST_DATABASE_URL"]
    engine = create_engine(url, pool_pre_ping=True)
    instance = Repository(engine)
    instance.create_tables()
    yield instance
    engine.dispose()


def observation(
    patient_id: str, version: int, duration: float, event: int
) -> Observation:
    return Observation(
        patient_id=patient_id,
        version=version,
        duration_months=duration,
        event_observed=event,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_idempotent_ingestion_and_version_conflict(repository):
    patient = f"TEST-{uuid.uuid4()}"
    row = observation(patient, 1, 5, 0)
    stored, duplicate = repository.ingest(row)
    repeated, was_duplicate = repository.ingest(row)
    assert duplicate is False
    assert was_duplicate is True
    assert repeated.observation_id == stored.observation_id
    with pytest.raises(ObservationConflict):
        repository.ingest(observation(patient, 1, 6, 0))


def test_revision_rules_and_explicit_correction(repository):
    patient = f"TEST-{uuid.uuid4()}"
    first, _ = repository.ingest(observation(patient, 1, 5, 1))
    revised, duplicate = repository.ingest(observation(patient, 2, 8, 1))
    assert duplicate is False
    assert revised.version == 2
    with pytest.raises(CorrectionError):
        repository.ingest(observation(patient, 3, 4, 0))
    corrected, _ = repository.ingest(
        observation(patient, 3, 4, 0),
        correction_reason="synthetic data-entry correction",
        correction_of=str(first.observation_id),
    )
    assert corrected.version == 3


def test_snapshot_membership_is_immutable_and_idempotent(repository):
    patient = f"TEST-{uuid.uuid4()}"
    first, _ = repository.ingest(observation(patient, 1, 5, 0))
    snapshot_id, reused = repository.create_snapshot()
    assert reused is False
    same_snapshot, was_reused = repository.create_snapshot()
    assert (same_snapshot, was_reused) == (snapshot_id, True)

    next_patient = f"TEST-{uuid.uuid4()}"
    repository.ingest(observation(next_patient, 1, 7, 1))
    later_snapshot, later_reused = repository.create_snapshot()
    assert later_snapshot != snapshot_id
    assert later_reused is False
    old_member_ids = {
        row["observation_id"] for row in repository.snapshot_rows(snapshot_id)
    }
    new_member_ids = {
        row["observation_id"] for row in repository.snapshot_rows(later_snapshot)
    }
    assert str(first.observation_id) in old_member_ids
    assert str(first.observation_id) in new_member_ids
    assert not any(
        row["patient_id"] == next_patient
        for row in repository.snapshot_rows(snapshot_id)
    )
