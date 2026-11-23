"""Create raw, meta, and model schemas."""

from alembic import op

from survivallab.db.schema import metadata

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")
    op.execute("CREATE SCHEMA IF NOT EXISTS meta")
    op.execute("CREATE SCHEMA IF NOT EXISTS model")
    metadata.create_all(bind=op.get_bind(), checkfirst=True)
    op.execute(
        "GRANT USAGE ON SCHEMA raw TO survivallab_ingest, "
        "survivallab_pipeline, survivallab_analytics"
    )
    op.execute(
        "GRANT USAGE ON SCHEMA meta TO survivallab_pipeline, "
        "survivallab_reader, survivallab_analytics"
    )
    op.execute(
        "GRANT USAGE ON SCHEMA model TO survivallab_pipeline, survivallab_reader"
    )
    op.execute("GRANT SELECT, INSERT ON raw.observations TO survivallab_ingest")
    op.execute(
        "GRANT SELECT ON raw.observations TO survivallab_pipeline, "
        "survivallab_analytics"
    )
    op.execute(
        "GRANT SELECT, INSERT ON meta.snapshots, meta.snapshot_members "
        "TO survivallab_pipeline"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON meta.pipeline_runs TO survivallab_pipeline"
    )
    op.execute("GRANT SELECT ON meta.pipeline_runs TO survivallab_reader")
    op.execute("GRANT SELECT, INSERT ON model.candidate_fits TO survivallab_pipeline")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON model.active_model TO survivallab_pipeline"
    )
    op.execute(
        "GRANT SELECT ON model.candidate_fits, model.active_model TO survivallab_reader"
    )
    op.execute(
        "GRANT SELECT ON meta.snapshots, meta.snapshot_members TO survivallab_analytics"
    )


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind(), checkfirst=True)
