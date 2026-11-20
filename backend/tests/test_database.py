import uuid

import pytest
from geoalchemy2 import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalysisJob, Detection, Image, ImageStatus, JobStatus, JobType
from app.repositories import BBox, find_detections


def box(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> WKTElement:
    wkt = (
        f"POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, {max_lon} {max_lat}, "
        f"{min_lon} {max_lat}, {min_lon} {min_lat}))"
    )
    return WKTElement(wkt, srid=4326)


async def add_image(session: AsyncSession) -> Image:
    image = Image(
        filename="oslo.tif",
        object_key=f"images/{uuid.uuid4()}/original.tif",
        content_type="image/tiff",
        file_size=1024,
        width=2000,
        height=1000,
        crs="EPSG:32632",
        resolution_x=0.5,
        resolution_y=0.5,
        bounds=box(10.70, 59.90, 10.80, 59.95),
        raster_metadata={"band_count": 3, "dtype": "uint8", "nodata": None},
    )
    session.add(image)
    await session.flush()
    return image


async def add_job(session: AsyncSession, image: Image) -> AnalysisJob:
    job = AnalysisJob(image_id=image.id, job_type=JobType.OBJECT_DETECTION)
    session.add(job)
    await session.flush()
    return job


def detection(
    image: Image, job: AnalysisJob, name: str, confidence: float, geom: WKTElement
) -> Detection:
    return Detection(
        image_id=image.id,
        job_id=job.id,
        class_name=name,
        class_id=0,
        confidence=confidence,
        pixel_bbox={"points": [[0, 0], [10, 0], [10, 10], [0, 10]]},
        geometry=geom,
    )


async def test_postgis_tables_and_spatial_indexes_exist(db_session: AsyncSession) -> None:
    rows = await db_session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE indexname LIKE 'ix_%'")
    )
    indexes = {name: definition for name, definition in rows.all()}
    assert "USING gist (bounds)" in indexes["ix_images_bounds"]
    assert "USING gist (geometry)" in indexes["ix_detections_geometry"]


async def test_image_metadata_roundtrip(db_session: AsyncSession) -> None:
    image = await add_image(db_session)
    db_session.expunge_all()

    stored = await db_session.get(Image, image.id)
    assert stored is not None
    assert stored.processing_status == ImageStatus.UPLOADED
    assert stored.uploaded_at is not None
    assert stored.acquisition_date is None  # never invented
    assert stored.raster_metadata == {"band_count": 3, "dtype": "uint8", "nodata": None}
    bounds = await db_session.scalar(
        select(func.ST_AsText(Image.bounds)).where(Image.id == image.id)
    )
    assert bounds == "POLYGON((10.7 59.9,10.8 59.9,10.8 59.95,10.7 59.95,10.7 59.9))"
    assert await db_session.scalar(select(func.ST_SRID(Image.bounds))) == 4326


async def test_new_job_defaults(db_session: AsyncSession) -> None:
    job = await add_job(db_session, await add_image(db_session))
    assert job.status == JobStatus.PENDING
    assert job.progress == 0
    assert job.parameters == {}


async def test_find_detections_in_bbox(db_session: AsyncSession) -> None:
    image = await add_image(db_session)
    job = await add_job(db_session, image)
    inside_ship = detection(image, job, "ship", 0.9, box(10.72, 59.91, 10.721, 59.911))
    inside_plane = detection(image, job, "plane", 0.4, box(10.73, 59.92, 10.731, 59.921))
    crossing_edge = detection(image, job, "ship", 0.6, box(10.749, 59.91, 10.751, 59.911))
    outside = detection(image, job, "ship", 0.99, box(10.78, 59.94, 10.781, 59.941))
    db_session.add_all([inside_ship, inside_plane, crossing_edge, outside])
    await db_session.flush()

    bbox = BBox(10.70, 59.90, 10.75, 59.93)
    found = await find_detections(db_session, bbox=bbox)
    # Intersecting counts (edge-crossing included), ordered by confidence.
    assert [d.id for d in found] == [inside_ship.id, crossing_edge.id, inside_plane.id]

    ships = await find_detections(db_session, bbox=bbox, class_names=["ship"])
    assert {d.id for d in ships} == {inside_ship.id, crossing_edge.id}

    confident = await find_detections(db_session, bbox=bbox, min_confidence=0.5)
    assert {d.id for d in confident} == {inside_ship.id, crossing_edge.id}

    page = await find_detections(db_session, bbox=bbox, limit=1, offset=1)
    assert [d.id for d in page] == [crossing_edge.id]

    other_image = await find_detections(db_session, bbox=bbox, image_id=uuid.uuid4())
    assert other_image == []


async def test_bbox_query_can_use_spatial_index(db_session: AsyncSession) -> None:
    await db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = await db_session.execute(
        text(
            "EXPLAIN SELECT id FROM detections "
            "WHERE ST_Intersects(geometry, ST_MakeEnvelope(10.7, 59.9, 10.75, 59.93, 4326))"
        )
    )
    assert "ix_detections_geometry" in "\n".join(plan.scalars().all())


async def test_deleting_image_cascades_to_jobs_and_detections(db_session: AsyncSession) -> None:
    image = await add_image(db_session)
    job = await add_job(db_session, image)
    db_session.add(detection(image, job, "ship", 0.8, box(10.72, 59.91, 10.721, 59.911)))
    await db_session.flush()

    await db_session.delete(image)
    await db_session.flush()
    assert await db_session.scalar(select(func.count()).select_from(Detection)) == 0
    assert await db_session.scalar(select(func.count()).select_from(AnalysisJob)) == 0


async def test_constraints_reject_invalid_confidence(db_session: AsyncSession) -> None:
    image = await add_image(db_session)
    job = await add_job(db_session, image)
    db_session.add(detection(image, job, "ship", 1.5, box(10.72, 59.91, 10.721, 59.911)))
    with pytest.raises(IntegrityError, match="ck_detections_confidence"):
        await db_session.flush()


async def test_geometry_column_rejects_wrong_srid(db_session: AsyncSession) -> None:
    image = await add_image(db_session)
    job = await add_job(db_session, image)
    utm = WKTElement("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))", srid=32632)
    db_session.add(detection(image, job, "ship", 0.5, utm))
    with pytest.raises(Exception, match="SRID"):
        await db_session.flush()


@pytest.mark.parametrize(
    "coords",
    [
        (10.8, 59.9, 10.7, 59.95),  # min > max
        (-181, 0, 0, 1),  # longitude out of range
        (0, -91, 1, 0),  # latitude out of range
    ],
)
def test_bbox_validation(coords: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValueError):
        BBox(*coords)
