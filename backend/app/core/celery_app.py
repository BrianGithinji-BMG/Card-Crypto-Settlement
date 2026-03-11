"""Celery application configuration for background worker tasks."""

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "card_crypto",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

# Keep worker behavior predictable across local and container environments.
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)

# Import tasks from service modules when they are added.
celery_app.autodiscover_tasks(["app.services"])
