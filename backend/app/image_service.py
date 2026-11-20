"""Image ingestion: validate → convert to COG → store in object storage → save metadata."""

import asyncio
import logging
import re
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from geoalchemy2.shape import from_shape
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Image, ImageStatus
from app.raster import RasterLimits, create_cog, inspect_raster, render_preview

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

TIFF_CONTENT_TYPE = "image/tiff"
COG_CONTENT_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"


def original_key(image_id: uuid.UUID) -> str:
    return f"images/{image_id}/original.tif"


def cog_key(image_id: uuid.UUID) -> str:
    return f"images/{image_id}/cog.tif"


def preview_key(image_id: uuid.UUID) -> str:
    return f"images/{image_id}/preview.png"


def sanitize_filename(filename: str | None) -> str:
    """Display name only. Never used in storage keys or file paths."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:255] or "upload.tif"


def raster_limits(settings: Settings) -> RasterLimits:
    return RasterLimits(
        max_pixels=settings.max_raster_pixels,
        max_bands=settings.max_raster_bands,
        max_uncompressed_bytes=settings.max_uncompressed_bytes,
    )


async def ingest_image(
    session: AsyncSession,
    s3: "S3Client",
    settings: Settings,
    upload_path: Path,
    filename: str | None,
    file_size: int,
) -> Image:
    """Validate an uploaded GeoTIFF and store it. Raises RasterValidationError if rejected."""
    info = await asyncio.to_thread(inspect_raster, upload_path, raster_limits(settings))
    image_id = uuid.uuid4()
    bucket = settings.s3_bucket

    with tempfile.TemporaryDirectory(prefix="satellite-detection-") as tmp:
        cog_path = Path(tmp) / "cog.tif"
        await asyncio.to_thread(create_cog, upload_path, cog_path)
        preview = await asyncio.to_thread(render_preview, cog_path)

        stored: list[str] = []
        try:
            await asyncio.to_thread(
                s3.upload_file,
                str(upload_path),
                bucket,
                original_key(image_id),
                ExtraArgs={"ContentType": TIFF_CONTENT_TYPE},
            )
            stored.append(original_key(image_id))
            await asyncio.to_thread(
                s3.upload_file,
                str(cog_path),
                bucket,
                cog_key(image_id),
                ExtraArgs={"ContentType": COG_CONTENT_TYPE},
            )
            stored.append(cog_key(image_id))
            await asyncio.to_thread(
                s3.put_object,
                Bucket=bucket,
                Key=preview_key(image_id),
                Body=preview.png,
                ContentType="image/png",
            )
            stored.append(preview_key(image_id))

            image = Image(
                id=image_id,
                filename=sanitize_filename(filename),
                object_key=original_key(image_id),
                content_type=TIFF_CONTENT_TYPE,
                file_size=file_size,
                width=info.width,
                height=info.height,
                crs=info.crs,
                resolution_x=info.resolution_x,
                resolution_y=info.resolution_y,
                bounds=from_shape(info.footprint_wgs84, srid=4326),
                acquisition_date=info.acquisition_date,
                processing_status=ImageStatus.READY,
                raster_metadata=info.metadata
                | {
                    "cog_object_key": cog_key(image_id),
                    "preview_object_key": preview_key(image_id),
                    # Same band choice and contrast stretch for the preview and all map tiles.
                    "display_bands": preview.bands,
                    "display_ranges": preview.display_ranges,
                },
            )
            session.add(image)
            await session.commit()
        except BaseException:
            await session.rollback()
            await asyncio.to_thread(_delete_objects, s3, bucket, stored)
            raise
    return image


def _delete_objects(s3: "S3Client", bucket: str, keys: list[str]) -> None:
    for key in keys:
        try:
            s3.delete_object(Bucket=bucket, Key=key)
        except Exception:
            logger.exception("Failed to clean up object %s", key)
