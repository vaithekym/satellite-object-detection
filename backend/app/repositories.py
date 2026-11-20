"""Database queries used by the API and workers."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from geoalchemy2.shape import from_shape
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.pipeline import GeoDetection
from app.models import WGS84, Detection


@dataclass(frozen=True)
class BBox:
    """Geographic bounding box in EPSG:4326 (degrees)."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def __post_init__(self) -> None:
        if not (-180 <= self.min_lon <= 180 and -180 <= self.max_lon <= 180):
            raise ValueError("Longitude must be between -180 and 180")
        if not (-90 <= self.min_lat <= 90 and -90 <= self.max_lat <= 90):
            raise ValueError("Latitude must be between -90 and 90")
        if self.min_lon >= self.max_lon or self.min_lat >= self.max_lat:
            # Boxes crossing the antimeridian are not supported.
            raise ValueError("min values must be smaller than max values")

    @classmethod
    def parse(cls, text: str) -> "BBox":
        """From "min_lon,min_lat,max_lon,max_lat"."""
        parts = text.split(",")
        if len(parts) != 4:
            raise ValueError("bbox must be min_lon,min_lat,max_lon,max_lat")
        return cls(*(float(p) for p in parts))


async def find_detections(
    session: AsyncSession,
    *,
    bbox: BBox | None = None,
    image_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    class_names: Sequence[str] | None = None,
    min_confidence: float | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> list[Detection]:
    """Filtered detections, highest confidence first. The bbox filter uses the GiST index."""
    query = select(Detection)
    if bbox is not None:
        envelope = func.ST_MakeEnvelope(
            bbox.min_lon, bbox.min_lat, bbox.max_lon, bbox.max_lat, WGS84
        )
        query = query.where(func.ST_Intersects(Detection.geometry, envelope))
    if image_id is not None:
        query = query.where(Detection.image_id == image_id)
    if job_id is not None:
        query = query.where(Detection.job_id == job_id)
    if class_names:
        query = query.where(Detection.class_name.in_(class_names))
    if min_confidence is not None:
        query = query.where(Detection.confidence >= min_confidence)
    query = query.order_by(Detection.confidence.desc(), Detection.id).limit(limit).offset(offset)
    return list((await session.scalars(query)).all())


async def replace_detections(
    session: AsyncSession,
    job_id: uuid.UUID,
    image_id: uuid.UUID,
    detections: Sequence[GeoDetection],
    batch_size: int = 1000,
) -> int:
    """Replace a job's detections (idempotent: re-running a job never duplicates results).

    Runs in the caller's transaction; commit afterwards.
    """
    await session.execute(delete(Detection).where(Detection.job_id == job_id))
    rows = [
        {
            "id": uuid.uuid4(),
            "image_id": image_id,
            "job_id": job_id,
            "class_name": d.class_name,
            "class_id": d.class_id,
            "confidence": round(d.confidence, 6),
            "pixel_bbox": {
                "points": [[round(c, 2), round(r, 2)] for c, r in d.pixel_points],
                "clipped_to_image": d.clipped_to_image,
            },
            "geometry": from_shape(d.geometry, srid=WGS84),
        }
        for d in detections
    ]
    for start in range(0, len(rows), batch_size):
        await session.execute(insert(Detection), rows[start : start + batch_size])
    return len(rows)
