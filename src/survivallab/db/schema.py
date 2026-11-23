"""SQLAlchemy Core schema shared by Alembic and the repository."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

observations = Table(
    "observations",
    metadata,
    Column("observation_id", String(36), primary_key=True),
    Column("patient_id", String(128), nullable=False),
    Column("version", Integer, nullable=False),
    Column("duration_months", Float, nullable=False),
    Column("event_observed", SmallInteger, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("correction_reason", Text),
    Column(
        "supersedes_observation_id",
        String(36),
        ForeignKey("raw.observations.observation_id"),
    ),
    CheckConstraint("version >= 1", name="ck_observations_version_positive"),
    CheckConstraint("duration_months > 0", name="ck_observations_duration_positive"),
    CheckConstraint("event_observed IN (0, 1)", name="ck_observations_event_binary"),
    CheckConstraint(
        "(correction_reason IS NULL AND supersedes_observation_id IS NULL) OR "
        "(correction_reason IS NOT NULL AND supersedes_observation_id IS NOT NULL)",
        name="ck_observations_correction_pair",
    ),
    UniqueConstraint("patient_id", "version", name="uq_observations_patient_version"),
    schema="raw",
)
Index(
    "ix_observations_patient_version", observations.c.patient_id, observations.c.version
)

snapshots = Table(
    "snapshots",
    metadata,
    Column("snapshot_id", String(36), primary_key=True),
    Column("content_hash", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("member_count", Integer, nullable=False),
    schema="meta",
)

snapshot_members = Table(
    "snapshot_members",
    metadata,
    Column(
        "snapshot_id",
        String(36),
        ForeignKey("meta.snapshots.snapshot_id"),
        primary_key=True,
    ),
    Column("patient_id", String(128), primary_key=True),
    Column(
        "observation_id",
        String(36),
        ForeignKey("raw.observations.observation_id"),
        nullable=False,
    ),
    schema="meta",
)
Index("ix_snapshot_members_observation", snapshot_members.c.observation_id)

candidate_fits = Table(
    "candidate_fits",
    metadata,
    Column("model_id", String(36), primary_key=True),
    Column(
        "snapshot_id",
        String(36),
        ForeignKey("meta.snapshots.snapshot_id"),
        nullable=False,
    ),
    Column("method", String(64), nullable=False),
    Column("code_hash", String(64), nullable=False),
    Column("config_hash", String(64), nullable=False),
    Column("result", JSON, nullable=False),
    Column("provenance", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "snapshot_id",
        "code_hash",
        "config_hash",
        "method",
        name="uq_candidate_fit_inputs",
    ),
    schema="model",
)
Index("ix_candidate_fits_created_at", candidate_fits.c.created_at)

active_model = Table(
    "active_model",
    metadata,
    Column("singleton_id", Integer, primary_key=True),
    Column("model_id", String(36), ForeignKey("model.candidate_fits.model_id")),
    Column("published_at", DateTime(timezone=True)),
    CheckConstraint("singleton_id = 1", name="ck_active_model_singleton"),
    schema="model",
)

pipeline_runs = Table(
    "pipeline_runs",
    metadata,
    Column("run_id", String(36), primary_key=True),
    Column("snapshot_id", String(36), ForeignKey("meta.snapshots.snapshot_id")),
    Column("status", String(16), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("model_id", String(36), ForeignKey("model.candidate_fits.model_id")),
    Column("error_code", String(64)),
    Column("message", Text),
    CheckConstraint(
        "status IN ('running', 'succeeded', 'skipped', 'failed')",
        name="ck_pipeline_runs_status",
    ),
    schema="meta",
)
Index("ix_pipeline_runs_started_at", pipeline_runs.c.started_at)
