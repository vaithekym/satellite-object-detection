"""Analysis job creation (queued to RabbitMQ) and job monitoring."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import get_session
from app.models import AnalysisJob, Image, ImageStatus, JobStatus, JobType
from app.schemas import AnalysisAccepted, AnalysisRequest, JobList, JobResponse
from app.worker.celery_app import TASK_OBJECT_DETECTION

logger = logging.getLogger(__name__)

analysis_router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])
jobs_router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ACTIVE = (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING)


def _error(code: int, description: str) -> dict[int | str, dict[str, str]]:
    return {code: {"description": description}}


@analysis_router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_error(404, "Image not found"),
        **_error(409, "An analysis of this image is already queued or running"),
        **_error(422, "Image is not ready for analysis, or invalid request"),
        **_error(503, "The job queue is unavailable"),
    },
)
async def create_analysis(
    body: AnalysisRequest, request: Request, session: SessionDep
) -> AnalysisAccepted:
    """Queue an analysis job. The message on the queue contains only the job id."""
    image = await session.get(Image, body.image_id)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    if image.processing_status != ImageStatus.READY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Image is not ready")

    active = await session.scalar(
        select(AnalysisJob.id).where(
            AnalysisJob.image_id == image.id,
            AnalysisJob.job_type == JobType.OBJECT_DETECTION,
            AnalysisJob.status.in_(ACTIVE),
        )
    )
    if active is not None:
        return JSONResponse(  # type: ignore[return-value]
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "An analysis of this image is already queued or running",
                "job_id": str(active),
            },
        )

    # QUEUED is committed before publishing: a fast worker must never see an older state.
    job = AnalysisJob(
        image_id=image.id,
        job_type=JobType.OBJECT_DETECTION,
        status=JobStatus.QUEUED,
        status_message="Waiting for a worker",
        parameters={"model": body.model, "trigger": "api"},
    )
    session.add(job)
    await session.commit()

    settings: Settings = request.app.state.settings
    celery: Celery = request.app.state.celery
    try:
        await asyncio.to_thread(
            celery.send_task,
            TASK_OBJECT_DETECTION,
            args=[str(job.id)],
            task_id=str(job.id),
            queue=settings.analysis_queue,
        )
    except Exception as exc:
        logger.exception("Could not publish job %s", job.id)
        job.status = JobStatus.FAILED
        job.status_message = "Failed"
        job.error_message = "The job queue is unavailable"
        job.completed_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The job queue is unavailable"
        ) from exc
    return AnalysisAccepted(job_id=job.id, status=job.status)


@jobs_router.get("")
async def list_jobs(
    session: SessionDep,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    image_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobList:
    """Jobs, newest first."""
    query = select(AnalysisJob, Image.filename).join(Image, Image.id == AnalysisJob.image_id)
    count = select(func.count()).select_from(AnalysisJob)
    if status_filter is not None:
        query = query.where(AnalysisJob.status == status_filter)
        count = count.where(AnalysisJob.status == status_filter)
    if image_id is not None:
        query = query.where(AnalysisJob.image_id == image_id)
        count = count.where(AnalysisJob.image_id == image_id)
    rows = await session.execute(
        query.order_by(AnalysisJob.created_at.desc(), AnalysisJob.id).limit(limit).offset(offset)
    )
    return JobList(
        items=[JobResponse.from_model(job, filename) for job, filename in rows.all()],
        total=await session.scalar(count) or 0,
    )


async def _get_job(session: AsyncSession, job_id: uuid.UUID) -> tuple[AnalysisJob, str | None]:
    row = (
        await session.execute(
            select(AnalysisJob, Image.filename)
            .join(Image, Image.id == AnalysisJob.image_id)
            .where(AnalysisJob.id == job_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return row[0], row[1]


@jobs_router.get("/{job_id}", responses=_error(404, "Job not found"))
async def get_job(job_id: uuid.UUID, session: SessionDep) -> JobResponse:
    job, filename = await _get_job(session, job_id)
    return JobResponse.from_model(job, filename)


@jobs_router.post(
    "/{job_id}/cancel",
    responses={**_error(404, "Job not found"), **_error(409, "Job is no longer waiting")},
)
async def cancel_job(job_id: uuid.UUID, session: SessionDep) -> JobResponse:
    """Cancel a job that has not started yet (running jobs cannot be interrupted)."""
    job, filename = await _get_job(session, job_id)
    if job.status not in (JobStatus.PENDING, JobStatus.QUEUED):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Job is {job.status}, not waiting")
    job.status = JobStatus.CANCELLED
    job.status_message = "Cancelled"
    job.completed_at = datetime.now(UTC)
    await session.commit()
    return JobResponse.from_model(job, filename)
