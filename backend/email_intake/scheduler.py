"""APScheduler entry point that runs the intake cycle on a fixed interval."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from . import config
from .poller import run_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def main() -> None:
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_cycle,
        trigger="interval",
        minutes=config.POLL_INTERVAL_MINUTES,
        max_instances=1,
        coalesce=True,
        id="intake_cycle",
    )

    # Run once immediately at startup.
    logger.info("Running initial intake cycle.")
    try:
        run_cycle()
    except Exception:
        logger.exception("Initial intake cycle failed.")

    logger.info(
        "Starting scheduler (every %d minute(s)).",
        config.POLL_INTERVAL_MINUTES,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
