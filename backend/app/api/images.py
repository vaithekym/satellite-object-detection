import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.config import Settings
from app.db import get_session
from app.image_service import cog_key, ingest_image, preview_key
from app.models import AnalysisJob, Image, JobStatus, JobType
from app.raster import RasterValidationError, display_bands_for, has_tiff_signature
from app.repositories import BBox, find_detections
from app.schemas import (
    ImageDetail,
    ImageList,
    ImageSummary,
    TileJSON,
    UploadResponse,
    detections_feature_collection,
)
from app.tiles import render_tile, run_in_env, s3_gdal_env, s3_url, tile_info

router = APIRouter(prefix="/api/v1/images", tags=["images"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CHUNK_SIZE = 1024 * 1024
MULTIPART_OVERHEAD = 64 * 1024  # boundaries and part headers around the file

UPLOAD_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


def _error(code: int, description: str) -> dict[int | str, dict[str, str]]:
    return {code: {"description": description}}


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    openapi_extra=UPLOAD_OPENAPI,
    responses={
        **_error(411, "Content-Length header missing"),
        **_error(413, "File exceeds the upload size limit"),
        **_error(415, "Not a TIFF/GeoTIFF file"),
        **_error(422, "Invalid, corrupted or unsupported raster"),
        **_error(507, "Not enough free disk space to process the upload"),
    },
)
async def upload_image(request: Request, session: SessionDep) -> UploadResponse:
    """Upload a georeferenced GeoTIFF (multipart field `file`)."""
    settings: Settings = request.app.state.settings
    declared = request.headers.get("content-length", "")
    if not declared.isdigit():
        raise HTTPException(status.HTTP_411_LENGTH_REQUIRED, "Content-Length header is required")
    if int(declared) > settings.max_upload_bytes + MULTIPART_OVERHEAD:
        raise _too_large(settings)
    # Room for the spooled upload, our copy, and the COG.
    free = shutil.disk_usage(tempfile.gettempdir()).free
    if free < settings.min_free_disk_bytes + 3 * int(declared):
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE, "Not enough free disk space to process the upload"
        )

    async with request.form(max_files=1, max_fields=0) as form:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Form field 'file' with a GeoTIFF is required",
            )
        with tempfile.NamedTemporaryFile(
            prefix="satellite-detection-upload-", suffix=".tif"
        ) as tmp:
            size = 0
            while chunk := await upload.read(CHUNK_SIZE):
                if size == 0 and not has_tiff_signature(chunk):
                    raise HTTPException(
                        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only GeoTIFF files are supported"
                    )
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise _too_large(settings)
                tmp.write(chunk)
            if size == 0:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty")
            tmp.flush()
            try:
                image = await ingest_image(
                    session, request.app.state.s3, settings, Path(tmp.name), upload.filename, size
                )
            except RasterValidationError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    return UploadResponse(id=image.id, filename=image.filename, status=image.processing_status)


def _too_large(settings: Settings) -> HTTPException:
    limit_mb = settings.max_upload_bytes // (1024 * 1024)
    return HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds the upload limit of {limit_mb} MB"
    )


@router.get("")
async def list_images(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ImageList:
    total = await session.scalar(select(func.count()).select_from(Image)) or 0
    images = await session.scalars(
        select(Image).order_by(Image.uploaded_at.desc(), Image.id).limit(limit).offset(offset)
    )
    return ImageList(items=[ImageSummary.from_model(i) for i in images], total=total)


async def _get_image(session: AsyncSession, image_id: uuid.UUID) -> Image:
    image = await session.get(Image, image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    return image


@router.get("/{image_id}", responses=_error(404, "Image not found"))
async def get_image(image_id: uuid.UUID, session: SessionDep) -> ImageDetail:
    return ImageDetail.from_model(await _get_image(session, image_id))


@router.get(
    "/{image_id}/preview",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}, **_error(404, "Image not found")},
)
async def get_preview(image_id: uuid.UUID, request: Request, session: SessionDep) -> Response:
    await _get_image(session, image_id)
    settings: Settings = request.app.state.settings
    obj = await asyncio.to_thread(
        request.app.state.s3.get_object, Bucket=settings.s3_bucket, Key=preview_key(image_id)
    )
    body = await asyncio.to_thread(obj["Body"].read)
    return Response(
        body, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"}
    )


async def _load_image(request: Request, image_id: uuid.UUID) -> Image:
    """Short-lived session, so slow tile rendering does not hold a database connection."""
    async with request.app.state.sessionmaker() as session:
        return await _get_image(session, image_id)


def _cog_source(settings: Settings, image: Image) -> str:
    key = image.raster_metadata.get("cog_object_key") or cog_key(image.id)
    return s3_url(settings.s3_bucket, key)


@router.get("/{image_id}/tilejson.json", responses=_error(404, "Image not found"))
async def get_tilejson(image_id: uuid.UUID, request: Request) -> TileJSON:
    """TileJSON for adding the image as a raster layer in a web map (e.g. MapLibre)."""
    settings: Settings = request.app.state.settings
    image = await _load_image(request, image_id)
    info = await asyncio.to_thread(
        run_in_env, s3_gdal_env(settings), tile_info, _cog_source(settings, image)
    )
    base = str(request.base_url).rstrip("/")
    return TileJSON(
        name=image.filename,
        tiles=[f"{base}/api/v1/images/{image_id}/tiles/{{z}}/{{x}}/{{y}}.png"],
        minzoom=info.minzoom,
        maxzoom=info.maxzoom,
        bounds=list(info.bounds),
    )


@router.get(
    "/{image_id}/tiles/{z}/{x}/{y}.png",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {}}},
        **_error(404, "Image not found, or tile outside the image"),
    },
)
async def get_tile(
    image_id: uuid.UUID,
    z: Annotated[int, PathParam(ge=0, le=24)],
    x: Annotated[int, PathParam(ge=0)],
    y: Annotated[int, PathParam(ge=0)],
    request: Request,
) -> Response:
    """Web Mercator XYZ tile (256 px PNG, NoData transparent)."""
    if x >= 2**z or y >= 2**z:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tile coordinates out of range")
    settings: Settings = request.app.state.settings
    image = await _load_image(request, image_id)
    metadata = image.raster_metadata
    bands = metadata.get("display_bands") or display_bands_for(
        metadata.get("color_interpretation", []), int(metadata.get("band_count", 1))
    )
    png = await asyncio.to_thread(
        run_in_env,
        s3_gdal_env(settings),
        render_tile,
        _cog_source(settings, image),
        z,
        x,
        y,
        bands,
        metadata.get("display_ranges"),
    )
    if png is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tile is outside the image")
    headers = {"Cache-Control": "private, max-age=86400"}
    return Response(png, media_type="image/png", headers=headers)


GEOJSON = "application/geo+json"


@router.get(
    "/{image_id}/detections",
    response_class=JSONResponse,
    responses={
        200: {"content": {GEOJSON: {}}, "description": "GeoJSON FeatureCollection (EPSG:4326)"},
        **_error(404, "Image not found"),
        **_error(422, "Invalid filter"),
    },
)
async def get_detections(
    image_id: uuid.UUID,
    session: SessionDep,
    bbox: Annotated[
        str | None, Query(description="min_lon,min_lat,max_lon,max_lat (EPSG:4326)")
    ] = None,
    class_name: Annotated[list[str] | None, Query()] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    job_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=10_000)] = 5000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """Detections for an image as GeoJSON, optionally filtered. Polygons are oriented boxes.

    Without `job_id`, results of the image's most recent completed detection job are
    returned (so re-analysing an image does not show duplicates). `confidence` is the
    model's score, not a probability that the detection is correct.
    """
    image = await _get_image(session, image_id)
    if job_id is None:
        job_id = await session.scalar(
            select(AnalysisJob.id)
            .where(
                AnalysisJob.image_id == image.id,
                AnalysisJob.job_type == JobType.OBJECT_DETECTION,
                AnalysisJob.status == JobStatus.COMPLETED,
            )
            .order_by(AnalysisJob.completed_at.desc())
            .limit(1)
        )
        if job_id is None:
            return JSONResponse(detections_feature_collection([]), media_type=GEOJSON)
    try:
        parsed_bbox = BBox.parse(bbox) if bbox else None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    detections = await find_detections(
        session,
        bbox=parsed_bbox,
        image_id=image.id,
        job_id=job_id,
        class_names=class_name,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(detections_feature_collection(detections), media_type=GEOJSON)
