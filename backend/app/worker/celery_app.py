"""Celery application (RabbitMQ broker, no result backend — job state lives in PostgreSQL).

Run a worker:  celery -A app.worker.celery_app worker -Q analysis   (or `make worker`)

Reliability settings:
- acks_late + prefetch 1: a message is acknowledged only after the job finished, and each
  worker process holds at most one job; if a worker dies, RabbitMQ redelivers the job
  (task_reject_on_worker_lost). Jobs are idempotent, so redelivery never duplicates results.
- Failed tasks are rejected without requeue, so RabbitMQ moves them to the dead-letter
  queue "<queue>.dead" for inspection instead of retrying deterministic failures forever.
- Transient errors are retried by the task itself with exponential backoff (see tasks.py).
"""

from celery import Celery
from kombu import Exchange, Queue

from app.config import Settings, get_settings

TASK_OBJECT_DETECTION = "analysis.object_detection"


def dead_letter_queue(queue: str) -> str:
    return f"{queue}.dead"


def analysis_queues(queue: str) -> list[Queue]:
    """Main queue (dead-lettering to <queue>.dead) and the dead-letter queue itself."""
    dlx = Exchange(f"{queue}.dlx", type="direct", durable=True)
    return [
        Queue(
            queue,
            Exchange(queue, type="direct", durable=True),
            routing_key=queue,
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": dlx.name,
                "x-dead-letter-routing-key": dead_letter_queue(queue),
            },
        ),
        Queue(dead_letter_queue(queue), dlx, routing_key=dead_letter_queue(queue), durable=True),
    ]


def create_celery(settings: Settings | None = None) -> Celery:
    settings = settings or get_settings()
    queue = settings.analysis_queue
    app = Celery("satellite_detection", broker=settings.rabbitmq_url, include=["app.worker.tasks"])
    app.conf.update(
        task_queues=analysis_queues(queue),
        task_default_queue=queue,
        task_default_exchange=queue,
        task_default_routing_key=queue,
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,
        task_acks_late=True,
        task_acks_on_failure_or_timeout=False,  # failed → rejected → dead-letter queue
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_concurrency=settings.worker_concurrency,
        task_soft_time_limit=settings.job_soft_time_limit_seconds,
        task_time_limit=settings.job_time_limit_seconds,
        # Fail fast when publishing, so the API can report that the queue is unavailable.
        task_publish_retry_policy={
            "max_retries": 2,
            "interval_start": 0,
            "interval_step": 0.5,
            "interval_max": 1,
        },
        broker_connection_retry_on_startup=True,
        worker_send_task_events=False,
    )
    return app


celery_app = create_celery()
