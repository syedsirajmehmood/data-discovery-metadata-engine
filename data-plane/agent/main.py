"""Agent entrypoint.

Usage:
    python -m agent.main            # run forever on the configured schedule
    python -m agent.main --once     # run a single cycle and exit
                                     # (matches architecture.md §5's
                                     # "in-process scheduler OR k8s CronJob"
                                     # -- a CronJob just calls this with
                                     # --once on its own schedule instead of
                                     # using the in-process Scheduler loop)

Configuration is entirely environment-driven (see `config.py`):
  DP_CONTROL_PLANE_URL       required, e.g. https://ingest.example.com
  DP_API_KEY                 required
  DP_DATA_PLANE_ID           required
  DP_SOURCES_CONFIG_FILE     path to a YAML/JSON file listing source connections
  DP_SCRAPE_INTERVAL_SECONDS default 21600 (6h)
  DP_MAX_BATCH_ENTITIES      default 500
  DP_MAX_BATCH_INTERVAL_SECONDS default 60
  DP_CURSOR_DIR              default ./data/cursors
  DP_DEAD_LETTER_DIR         default ./data/dead_letter
"""
from __future__ import annotations

import argparse
import logging
import sys

from .config import AgentConfig, ConfigError
from .cursor_store import CursorStore
from .dead_letter import DeadLetterQueue
from .push_client import PushClient
from .runner import AgentRunner
from .scheduler import Scheduler


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def build_runner(config: AgentConfig) -> AgentRunner:
    return AgentRunner(
        config=config,
        cursor_store=CursorStore(config.cursor_dir),
        push_client=PushClient(config),
        dead_letter=DeadLetterQueue(config.dead_letter_dir),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Data-plane agent")
    parser.add_argument("--once", action="store_true", help="run a single scrape+push cycle and exit")
    args = parser.parse_args(argv)

    _setup_logging()
    logger = logging.getLogger("data_plane.agent.main")

    try:
        config = AgentConfig.from_env()
    except ConfigError as exc:
        logger.error(str(exc))
        return 2

    if not config.sources:
        logger.warning("no sources configured (DP_SOURCES_CONFIG_FILE unset or empty) -- nothing to do")

    runner = build_runner(config)

    if args.once:
        report = runner.run_cycle()
        logger.info("cycle complete: %s", report)
        return 0 if report.sources_failed == 0 else 1

    scheduler = Scheduler(interval_seconds=config.scrape_interval_seconds)

    def _cycle() -> None:
        report = runner.run_cycle()
        logger.info("cycle complete: %s", report)

    try:
        scheduler.run_forever(_cycle)
    except KeyboardInterrupt:
        logger.info("shutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
