"""Initial schema: images, analysis_jobs, detections.

Requires the PostGIS extension to exist already (CREATE EXTENSION needs a superuser,
the application role is intentionally not one).

Revision ID: 0001
Revises:
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
                RAISE EXCEPTION 'PostGIS missing. As superuser: CREATE EXTENSION postgis;';
            END IF;
        END $$;
        """
    )

    op.create_table(
        "images",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("crs", sa.String(64), nullable=False),
        sa.Column("resolution_x", sa.Double(), nullable=False),
        sa.Column("resolution_y", sa.Double(), nullable=False),
        sa.Column(
            "bounds",
            Geometry("POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("acquisition_date", TZ, nullable=True),
        sa.Column("uploaded_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("processing_status", sa.String(20), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("object_key", name="uq_images_object_key"),
        sa.CheckConstraint(
            "processing_status IN ('UPLOADED', 'PROCESSING', 'READY', 'FAILED')",
            name="ck_images_processing_status",
        ),
        sa.CheckConstraint("width > 0 AND height > 0", name="ck_images_dimensions"),
        sa.CheckConstraint("file_size > 0", name="ck_images_file_size"),
    )
    op.create_index("ix_images_bounds", "images", ["bounds"], postgresql_using="gist")
    op.create_index("ix_images_uploaded_at", "images", ["uploaded_at"])

    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "image_id",
            sa.Uuid(),
            sa.ForeignKey("images.id", ondelete="CASCADE", name="fk_analysis_jobs_image_id"),
            nullable=False,
        ),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("status_message", sa.String(255), nullable=True),
        sa.Column("model_name", sa.String(100), nullable=True),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", TZ, nullable=True),
        sa.Column("completed_at", TZ, nullable=True),
        sa.CheckConstraint("job_type IN ('object_detection')", name="ck_analysis_jobs_job_type"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_analysis_jobs_status",
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_analysis_jobs_progress"),
    )
    op.create_index("ix_analysis_jobs_image_id", "analysis_jobs", ["image_id"])
    op.create_index("ix_analysis_jobs_status_created_at", "analysis_jobs", ["status", "created_at"])

    op.create_table(
        "detections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "image_id",
            sa.Uuid(),
            sa.ForeignKey("images.id", ondelete="CASCADE", name="fk_detections_image_id"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE", name="fk_detections_job_id"),
            nullable=False,
        ),
        sa.Column("class_name", sa.String(100), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("pixel_bbox", postgresql.JSONB(), nullable=False),
        sa.Column(
            "geometry",
            Geometry("POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_detections_confidence"),
    )
    op.create_index("ix_detections_geometry", "detections", ["geometry"], postgresql_using="gist")
    op.create_index("ix_detections_job_id", "detections", ["job_id"])
    op.create_index("ix_detections_image_id_class_name", "detections", ["image_id", "class_name"])


def downgrade() -> None:
    op.drop_table("detections")
    op.drop_table("analysis_jobs")
    op.drop_table("images")
