import os
from celery import Celery
from config import settings

# Create the Celery app instance
celery_app = Celery(
    "o2c_worker",
    broker=settings.redis_url,
    backend=settings.redis_url
)

# Configure Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Kolkata',
    enable_utc=True,
    worker_hijack_root_logger=False,
)

# Autodiscover tasks from the 'agents' directory
celery_app.autodiscover_tasks(["agents"])

if __name__ == '__main__':
    celery_app.start()
