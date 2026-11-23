"""Transactional persistence operations for immutable inputs and model outputs."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, and_, func, insert, select, text, update
from sqlalchemy.engine import Connection

from survivallab.db.schema import (
    active_model,
    candidate_fits,
    metadata,
    observations,
    pipeline_runs,
    snapshot_members,
    snapshots,
)
from survivallab.models import (
    Observation,
    StoredObservation,
    canonical_observation_content,
)


class ObservationConflict(ValueError):
    """Raised when an immutable patient/version pair has different content."""


class CorrectionError(ValueError):
    """Raised when a revision violates follow-up rules or correction references."""


def observation_hash(observation: Observation) -> str:
    content = canonical_observation_content(observation)
    encoded = json.dumps(
        content, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


class Repository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create_tables(self) -> None:
        with self.engine.begin() as connection:
            for schema_name in ("raw", "meta", "model"):
                if self.engine.dialect.name == "postgresql":
                    connection.exec_driver_sql(
                        f"CREATE SCHEMA IF NOT EXISTS {schema_name}"
                    )
            metadata.create_all(connection)

    def _connection(self, *, repeatable_read: bool = False) -> Connection:
        connection = self.engine.connect()
        if repeatable_read and self.engine.dialect.name == "postgresql":
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
        return connection

    def healthcheck(self) -> bool:
        with self.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return True

    def ingest(
        self,
        observation: Observation,
        *,
        correction_reason: str | None = None,
        correction_of: str | None = None,
    ) -> tuple[StoredObservation, bool]:
        if (correction_reason is None) != (correction_of is None):
            raise CorrectionError(
                "correction reason and prior observation ID are both required"
            )
        content_hash = observation_hash(observation)
        observation_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            existing = (
                connection.execute(
                    select(observations).where(
                        and_(
                            observations.c.patient_id == observation.patient_id,
                            observations.c.version == observation.version,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["payload_hash"] == content_hash:
                    return self._to_stored(existing), True
                raise ObservationConflict(
                    "patient/version already exists with different content"
                )

            previous = (
                connection.execute(
                    select(observations)
                    .where(observations.c.patient_id == observation.patient_id)
                    .order_by(observations.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            supersedes_id = None
            if previous is not None:
                if observation.version != previous["version"] + 1:
                    raise CorrectionError(
                        "new versions must append exactly one version"
                    )
                correction_needed = observation.duration_months < previous[
                    "duration_months"
                ] or (
                    previous["event_observed"] == 1 and observation.event_observed == 0
                )
                if correction_needed and correction_reason is None:
                    raise CorrectionError(
                        "shorter follow-up or undoing an event requires "
                        "correction metadata"
                    )
                if correction_of is not None:
                    prior = (
                        connection.execute(
                            select(observations).where(
                                and_(
                                    observations.c.observation_id == correction_of,
                                    observations.c.patient_id == observation.patient_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if prior is None:
                        raise CorrectionError(
                            "correction reference must identify a prior observation "
                            "for this patient"
                        )
                    supersedes_id = correction_of
            elif correction_of is not None:
                raise CorrectionError(
                    "initial observations cannot correct a prior version"
                )

            row = {
                "observation_id": observation_id,
                **canonical_observation_content(observation),
                "observed_at": observation.observed_at,
                "ingested_at": now,
                "payload_hash": content_hash,
                "correction_reason": correction_reason,
                "supersedes_observation_id": supersedes_id,
            }
            connection.execute(insert(observations).values(**row))
        stored = {
            **row,
        }
        return self._to_stored(stored), False

    @staticmethod
    def _to_stored(row: Any) -> StoredObservation:
        observed_at = row["observed_at"]
        ingested_at = row["ingested_at"]
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        if ingested_at.tzinfo is None:
            ingested_at = ingested_at.replace(tzinfo=UTC)
        return StoredObservation.model_validate(
            {
                "patient_id": row["patient_id"],
                "version": row["version"],
                "duration_months": row["duration_months"],
                "event_observed": row["event_observed"],
                "observed_at": observed_at,
                "observation_id": row["observation_id"],
                "ingested_at": ingested_at,
                "payload_hash": row["payload_hash"],
            }
        )

    def create_snapshot(self) -> tuple[str, bool]:
        snapshot_id = str(uuid.uuid4())
        with self._connection(repeatable_read=True) as connection:
            transaction = connection.begin()
            latest = select(
                observations.c.observation_id,
                observations.c.patient_id,
                observations.c.version,
                observations.c.payload_hash,
                func.row_number()
                .over(
                    partition_by=observations.c.patient_id,
                    order_by=observations.c.version.desc(),
                )
                .label("rank"),
            ).subquery()
            rows = (
                connection.execute(
                    select(
                        latest.c.observation_id,
                        latest.c.patient_id,
                        latest.c.version,
                        latest.c.payload_hash,
                    )
                    .where(latest.c.rank == 1)
                    .order_by(latest.c.patient_id)
                )
                .mappings()
                .all()
            )
            members = [
                {
                    "patient_id": row["patient_id"],
                    "observation_id": row["observation_id"],
                    "version": row["version"],
                    "payload_hash": row["payload_hash"],
                }
                for row in rows
            ]
            encoded = json.dumps(members, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            existing = (
                connection.execute(
                    select(snapshots).where(snapshots.c.content_hash == digest)
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                transaction.commit()
                return str(existing["snapshot_id"]), True
            connection.execute(
                insert(snapshots).values(
                    snapshot_id=snapshot_id,
                    content_hash=digest,
                    created_at=datetime.now(UTC),
                    member_count=len(members),
                )
            )
            if members:
                connection.execute(
                    insert(snapshot_members),
                    [
                        {
                            "snapshot_id": snapshot_id,
                            "patient_id": item["patient_id"],
                            "observation_id": item["observation_id"],
                        }
                        for item in members
                    ],
                )
            transaction.commit()
        return snapshot_id, False

    def snapshot_rows(self, snapshot_id: str) -> list[dict[str, Any]]:
        statement = (
            select(observations)
            .join(
                snapshot_members,
                snapshot_members.c.observation_id == observations.c.observation_id,
            )
            .where(snapshot_members.c.snapshot_id == snapshot_id)
            .order_by(snapshot_members.c.patient_id)
        )
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(snapshots).where(snapshots.c.snapshot_id == snapshot_id)
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    def data_updated_at(self) -> datetime | None:
        with self.engine.connect() as connection:
            return connection.execute(
                select(func.max(observations.c.ingested_at))
            ).scalar_one()

    def dbt_statistics(self, snapshot_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT n, d, y FROM analytics.snapshot_statistics "
                        "WHERE snapshot_id = :snapshot_id"
                    ),
                    {"snapshot_id": snapshot_id},
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    def latest_model(self) -> dict[str, Any] | None:
        statement = (
            select(candidate_fits, active_model.c.published_at)
            .join(active_model, active_model.c.model_id == candidate_fits.c.model_id)
            .where(active_model.c.singleton_id == 1)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return dict(row) if row is not None else None

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(candidate_fits).where(candidate_fits.c.model_id == model_id)
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    def model_history(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(candidate_fits).order_by(candidate_fits.c.created_at.desc())
                ).mappings()
            ]

    @contextmanager
    def refresh_lock(self) -> Iterator[Connection]:
        with self.engine.connect() as connection:
            if self.engine.dialect.name == "postgresql":
                connection.exec_driver_sql("SELECT pg_advisory_lock(193704, 1)")
            try:
                yield connection
            finally:
                if self.engine.dialect.name == "postgresql":
                    connection.exec_driver_sql("SELECT pg_advisory_unlock(193704, 1)")

    def start_run(self, run_id: str, started_at: datetime) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(pipeline_runs).values(
                    run_id=run_id,
                    status="running",
                    started_at=started_at,
                )
            )

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        finished_at: datetime,
        snapshot_id: str | None = None,
        model_id: str | None = None,
        error_code: str | None = None,
        message: str | None = None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(pipeline_runs)
                .where(pipeline_runs.c.run_id == run_id)
                .values(
                    status=status,
                    finished_at=finished_at,
                    snapshot_id=snapshot_id,
                    model_id=model_id,
                    error_code=error_code,
                    message=message,
                )
            )

    def publish(
        self,
        *,
        model_id: str,
        snapshot_id: str,
        method: str,
        code_hash: str,
        config_hash: str,
        result: dict[str, Any],
        provenance: dict[str, Any],
        created_at: datetime,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(candidate_fits).values(
                    model_id=model_id,
                    snapshot_id=snapshot_id,
                    method=method,
                    code_hash=code_hash,
                    config_hash=config_hash,
                    result=result,
                    provenance=provenance,
                    created_at=created_at,
                )
            )
            connection.execute(
                update(active_model)
                .where(active_model.c.singleton_id == 1)
                .values(model_id=model_id, published_at=created_at)
            )
            active = connection.execute(
                select(active_model.c.singleton_id).where(
                    active_model.c.singleton_id == 1
                )
            ).scalar_one_or_none()
            if active is None:
                connection.execute(
                    insert(active_model).values(
                        singleton_id=1,
                        model_id=model_id,
                        published_at=created_at,
                    )
                )

    def has_candidate(
        self, snapshot_id: str, code_hash: str, config_hash: str, method: str
    ) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(candidate_fits).where(
                        and_(
                            candidate_fits.c.snapshot_id == snapshot_id,
                            candidate_fits.c.code_hash == code_hash,
                            candidate_fits.c.config_hash == config_hash,
                            candidate_fits.c.method == method,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row is not None else None

    def status(self) -> dict[str, Any]:
        with self.engine.connect() as connection:
            run = (
                connection.execute(
                    select(pipeline_runs)
                    .order_by(pipeline_runs.c.started_at.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return dict(run) if run is not None else {"status": "idle"}
