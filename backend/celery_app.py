"""Celery worker + beat schedule.

    celery -A celery_app worker --loglevel=info
    celery -A celery_app beat --loglevel=info
"""

from celery import Celery
from celery.schedules import crontab

from core.config import settings
from core.logging_config import setup_logging

setup_logging(settings.log_level)

celery_app = Celery("smartdeal", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    timezone="Asia/Kolkata",  # crontab times below are IST
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=24 * 3600,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "daily-price-collection": {
            "task": "collect_daily_prices",
            "schedule": crontab(hour=6, minute=0),
        },
        "refresh-offers": {
            "task": "refresh_offers",
            "schedule": crontab(hour="*/6", minute=15),
        },
    },
)

# Register tasks
import data_pipeline.coupon_collector  # noqa: E402,F401
import data_pipeline.daily_collector  # noqa: E402,F401
