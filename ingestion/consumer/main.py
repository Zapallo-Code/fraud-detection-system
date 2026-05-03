"""Entry point for the transaction consumer."""

from __future__ import annotations

import logging
import os
import signal
import threading

from config import kafka_settings

from .kafka_consumer import TransactionConsumer
from .windows import SlidingWindowStore

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure structured logging for the consumer."""

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = logging.getLevelNamesMapping().get(level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def install_signal_handlers(stop_event: threading.Event) -> None:
    """Register signal handlers for graceful shutdown."""

    def _handle_signal(signum, _frame) -> None:
        logger.info("Received signal %s, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)


def main() -> None:
    configure_logging()

    consumer = TransactionConsumer(
        broker_url=kafka_settings.broker_url,
        topic=kafka_settings.topics_raw,
        group_id="fraud-feature-engineering",
    )
    window_store = SlidingWindowStore()

    stop_event = threading.Event()
    install_signal_handlers(stop_event)

    try:
        while not stop_event.is_set():
            transaction = consumer.consume(timeout=1.0)
            if transaction is None:
                continue
            logger.debug(
                "Consumed transaction %s for user %s",
                transaction.transaction_id,
                transaction.user_id,
            )
            features = window_store.compute_features(transaction)
            window_store.add(transaction)
            logger.debug(
                "Computed window features for %s: %s",
                transaction.transaction_id,
                features,
            )
            consumer.commit()
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
