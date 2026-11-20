import uuid
from datetime import datetime
from typing import Any, Literal

from geoalchemy2.shape import to_shape
from pydantic import BaseModel
from shapely.geometry import mapping

from app.models import AnalysisJob, Detection, Image


class UploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: str


class ImageSummary(BaseModel):
    id: uuid.UUID
    filename: str
    file_size: int
    width: int
    height: int
    band_count: int
    crs: str
    resolution_x: float
    resolution_y: float
    resolution_unit: str | None  # "metre", "degree", "US survey foot", ...
    bounds: dict[str, Any]  # GeoJSON Polygon, EPSG:4326
    acquisition_date: datetime | None
    uploaded_at: datetime
    processing_status: str

    @classmethod
    def from_model(cls, image: Image) -> "ImageSummary":
        return cls(
            id=image.id,
            filename=image.filename,
            file_size=image.file_size,
            width=image.width,
            height=image.height,
            band_count=int(image.raster_metadata.get("band_count", 0)),
            crs=image.crs,
            resolution_x=image.resolution_x,
            resolution_y=image.resolution_y,
            resolution_unit=image.raster_metadata.get("crs_units"),
            bounds=dict(mapping(to_shape(image.bounds))),
            acquisition_date=image.acquisition_date,
            uploaded_at=image.uploaded_at,
            processing_status=image.processing_status,
        )


class ImageDetail(ImageSummary):
    metadata: dict[str, Any]

    @classmethod
    def from_model(cls, image: Image) -> "ImageDetail":
        summary = ImageSummary.from_model(image)
        return cls(**summary.model_dump(), metadata=image.raster_metadata)


class ImageList(BaseModel):
    items: list[ImageSummary]
    total: int


class TileJSON(BaseModel):
    """TileJSON 3.0.0 (https://github.com/mapbox/tilejson-spec)."""

    tilejson: str = "3.0.0"
    name: str
    tiles: list[str]
    minzoom: int
    maxzoom: int
    bounds: list[float]  # west, south, east, north


def detections_feature_collection(detections: list[Detection]) -> dict[str, Any]:
    """GeoJSON FeatureCollection (RFC 7946, EPSG:4326) of detections."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": str(d.id),
                "geometry": mapping(to_shape(d.geometry)),
                "properties": {
                    "class_name": d.class_name,
                    "class_id": d.class_id,
                    "confidence": d.confidence,
                    "job_id": str(d.job_id),
                    "image_id": str(d.image_id),
                    "pixel_bbox": d.pixel_bbox,
                },
            }
            for d in detections
        ],
    }


class AnalysisRequest(BaseModel):
    image_id: uuid.UUID
    analysis_type: Literal["object_detection"] = "object_detection"
    model: Literal["default"] = "default"


class AnalysisAccepted(BaseModel):
    job_id: uuid.UUID
    status: str


class JobResponse(BaseModel):
    job_id: uuid.UUID
    image_id: uuid.UUID
    image_filename: str | None
    job_type: str
    status: str
    progress: int
    message: str | None
    error_message: str | None
    model_name: str | None
    model_version: str | None
    parameters: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_model(cls, job: AnalysisJob, image_filename: str | None) -> "JobResponse":
        return cls(
            job_id=job.id,
            image_id=job.image_id,
            image_filename=image_filename,
            job_type=job.job_type,
            status=job.status,
            progress=job.progress,
            message=job.status_message,
            error_message=job.error_message,
            model_name=job.model_name,
            model_version=job.model_version,
            parameters=job.parameters,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )


class JobList(BaseModel):
    items: list[JobResponse]
    total: int
