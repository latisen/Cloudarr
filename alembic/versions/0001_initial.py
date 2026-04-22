"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-22
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("info_hash", sa.String(length=128), nullable=False),
        sa.Column("sonarr_title", sa.String(length=512), nullable=False),
        sa.Column("magnet_uri", sa.Text(), nullable=True),
        sa.Column("torrent_file_path", sa.String(length=1024), nullable=True),
        sa.Column("torrent_name", sa.String(length=512), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("save_path", sa.String(length=1024), nullable=False),
        sa.Column("torbox_job_id", sa.String(length=128), nullable=True),
        sa.Column("torbox_remote_path", sa.String(length=1024), nullable=True),
        sa.Column("exported_path", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_info_hash", "jobs", ["info_hash"], unique=True)
    op.create_index("ix_jobs_state", "jobs", ["state"], unique=False)
    op.create_index("ix_jobs_torbox_job_id", "jobs", ["torbox_job_id"], unique=False)

    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("message", sa.String(length=1024), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"], unique=False)
    op.create_index("ix_job_events_state", "job_events", ["state"], unique=False)

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "secret_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("secret_settings")
    op.drop_table("app_settings")
    op.drop_index("ix_job_events_state", table_name="job_events")
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_jobs_torbox_job_id", table_name="jobs")
    op.drop_index("ix_jobs_state", table_name="jobs")
    op.drop_index("ix_jobs_info_hash", table_name="jobs")
    op.drop_table("jobs")
