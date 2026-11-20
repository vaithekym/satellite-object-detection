"""Dashboard statistics, computed from the database (nothing is estimated or cached)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AnalysisJob, Detection, Image, JobStatus, JobType

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
RECENT = 10


class Activity(BaseModel):
    kind: Literal["upload", "job_completed", "job_failed", "job_cancelled", "job_queued"]
    at: datetime
    image_id: str
    image_filename: str
    job_id: str | None = None
    message: str | None = None


class Stats(BaseModel):
    images: int
    analyses_completed: int
    jobs_active: int  # pending, queued or running
    jobs_failed: int
    # Detections in each image's most recent completed analysis (what the map shows);
    # re-analysing an image does not double-count.
    detections: int
    detections_by_class: dict[str, int]
    recent_activity: list[Activity]


def latest_completed_jobs() -> Select[uuid.UUID]:
    """Id of the most recent completed object detection job per image."""
    return (
        select(AnalysisJob.id)
        .where(
            AnalysisJob.status == JobStatus.COMPLETED,
            AnalysisJob.job_type == JobType.OBJECT_DETECTION,
        )
        .ext(distinct_on(AnalysisJob.image_id))
        .order_by(AnalysisJob.image_id, AnalysisJob.completed_at.desc())
    )


@router.get("")
async def get_stats(session: SessionDep) -> Stats:
    count_jobs = select(func.count()).select_from(AnalysisJob)
    rows = await session.execute(
        select(Detection.class_name, func.count())
        .where(Detection.job_id.in_(latest_completed_jobs()))
        .group_by(Detection.class_name)
        .order_by(func.count().desc())
    )
    by_class = {class_name: int(count) for class_name, count in rows.all()}
    return Stats(
        images=await session.scalar(select(func.count()).select_from(Image)) or 0,
        analyses_completed=await session.scalar(
            count_jobs.where(AnalysisJob.status == JobStatus.COMPLETED)
        )
        or 0,
        jobs_active=await session.scalar(
            count_jobs.where(
                AnalysisJob.status.in_([JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING])
            )
        )
        or 0,
        jobs_failed=await session.scalar(count_jobs.where(AnalysisJob.status == JobStatus.FAILED))
        or 0,
        detections=sum(by_class.values()),
        detections_by_class=by_class,
        recent_activity=await _recent_activity(session),
    )


async def _recent_activity(session: AsyncSession) -> list[Activity]:
    uploads = await session.execute(
        select(Image.id, Image.filename, Image.uploaded_at)
        .order_by(Image.uploaded_at.desc())
        .limit(RECENT)
    )
    events = [
        Activity(kind="upload", at=at, image_id=str(image_id), image_filename=filename)
        for image_id, filename, at in uploads.all()
    ]
    jobs = await session.execute(
        select(AnalysisJob, Image.filename)
        .join(Image, Image.id == AnalysisJob.image_id)
        .order_by(func.coalesce(AnalysisJob.completed_at, AnalysisJob.created_at).desc())
        .limit(RECENT)
    )
    kinds = {
        JobStatus.COMPLETED: "job_completed",
        JobStatus.FAILED: "job_failed",
        JobStatus.CANCELLED: "job_cancelled",
    }
    for job, filename in jobs.all():
        events.append(
            Activity(
                kind=kinds.get(JobStatus(job.status), "job_queued"),
                at=job.completed_at or job.created_at,
                image_id=str(job.image_id),
                image_filename=filename,
                job_id=str(job.id),
                message=job.error_message if job.status == JobStatus.FAILED else job.status_message,
            )
        )
    events.sort(key=lambda e: e.at, reverse=True)
    return events[:RECENT]
