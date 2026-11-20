"""Database models. Geometries are stored in EPSG:4326 (WGS84 lon/lat)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

WGS84 = 4326


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s",
        }
    )


class ImageStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class JobType(StrEnum):
    OBJECT_DETECTION = "object_detection"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


def _in(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        CheckConstraint(_in("processing_status", ImageStatus), name="ck_images_processing_status"),
        CheckConstraint("width > 0 AND height > 0", name="ck_images_dimensions"),
        CheckConstraint("file_size > 0", name="ck_images_file_size"),
        Index("ix_images_bounds", "bounds", postgresql_using="gist"),
        Index("ix_images_uploaded_at", "uploaded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    crs: Mapped[str] = mapped_column(String(64))  # source CRS, e.g. "EPSG:32633"
    resolution_x: Mapped[float] = mapped_column(Double)  # in source CRS units
    resolution_y: Mapped[float] = mapped_column(Double)
    bounds: Mapped[WKBElement] = mapped_column(Geometry("POLYGON", srid=WGS84, spatial_index=False))
    acquisition_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processing_status: Mapped[str] = mapped_column(String(20), default=ImageStatus.UPLOADED)
    # "metadata" is reserved on SQLAlchemy models, so the attribute name differs from the column.
    raster_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        CheckConstraint(_in("job_type", JobType), name="ck_analysis_jobs_job_type"),
        CheckConstraint(_in("status", JobStatus), name="ck_analysis_jobs_status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_analysis_jobs_progress"),
        Index("ix_analysis_jobs_image_id", "image_id"),
        Index("ix_analysis_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    job_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.PENDING)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    status_message: Mapped[str | None] = mapped_column(String(255))
    model_name: Mapped[str | None] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(100))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Detection(Base):
    __tablename__ = "detections"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_detections_confidence"),
        Index("ix_detections_geometry", "geometry", postgresql_using="gist"),
        Index("ix_detections_job_id", "job_id"),
        Index("ix_detections_image_id_class_name", "image_id", "class_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    image_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"))
    class_name: Mapped[str] = mapped_column(String(100))
    class_id: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Double)
    # Corner points in full-image pixel coordinates: {"points": [[col, row], ...]}.
    # Polygons (not axis-aligned boxes) so oriented detections fit as well.
    pixel_bbox: Mapped[dict[str, Any]] = mapped_column(JSONB)
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry("POLYGON", srid=WGS84, spatial_index=False)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
