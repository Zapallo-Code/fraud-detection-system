"""Entry point for the transaction consumer."""

from __future__ import annotations

import logging
import os
import signal
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from config import kafka_settings, redis_settings

from .feature_publisher import FeaturePublisher
from .historical import HistoricalProfileStore, _UserProfile
from .kafka_consumer import TransactionConsumer
from .models import TransactionRaw
from .redis_store import RedisFeatureStore
from .windows import SEVEN_DAYS_SECONDS, SlidingWindowStore

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


def hydrate_user_state(
    user_id: str,
    reference_time: datetime,
    window_store: SlidingWindowStore,
    historical_store: HistoricalProfileStore,
    redis_store: RedisFeatureStore,
    max_window_seconds: int,
) -> None:
    """Load cached state from Redis into in-memory stores."""

    window_transactions = redis_store.load_user_window(user_id)
    if window_transactions:
        filtered_transactions = filter_window_transactions(
            window_transactions,
            reference_time,
            max_window_seconds,
        )
        filtered_transactions.sort(key=lambda item: item.timestamp)
        for item in filtered_transactions:
            window_store.add(item)

    historical_profile = redis_store.load_user_historical(user_id)
    if historical_profile:
        apply_historical_profile(historical_store, user_id, historical_profile)


def filter_window_transactions(
    transactions: list[TransactionRaw],
    reference_time: datetime,
    max_window_seconds: int,
) -> list[TransactionRaw]:
    """Filter transactions to those within the sliding window."""

    cutoff = reference_time.timestamp() - max_window_seconds
    filtered: list[TransactionRaw] = []
    for transaction in transactions:
        if transaction.timestamp.timestamp() < cutoff:
            continue
        if transaction.timestamp > reference_time:
            continue
        filtered.append(transaction)
    return filtered


def apply_historical_profile(
    historical_store: HistoricalProfileStore,
    user_id: str,
    raw_profile: dict[str, Any],
) -> None:
    """Hydrate the historical store with Redis aggregates."""

    amount_total = float(raw_profile.get("amount_total", 0.0))
    amount_count = int(raw_profile.get("amount_count", 0))
    countries_raw = raw_profile.get("countries_seen", [])
    merchants_raw = raw_profile.get("merchants_seen", [])
    countries_seen = (
        {str(item) for item in countries_raw} if isinstance(countries_raw, list) else set()
    )
    merchants_seen = (
        {str(item) for item in merchants_raw} if isinstance(merchants_raw, list) else set()
    )

    historical_store._profiles[user_id] = _UserProfile(
        amount_total=amount_total,
        amount_count=amount_count,
        countries_seen=countries_seen,
        merchants_seen=merchants_seen,
    )


def build_historical_payload(
    historical_store: HistoricalProfileStore,
    user_id: str,
) -> dict[str, Any]:
    """Build a JSON-serializable snapshot of the historical profile."""

    profile = historical_store._profiles.get(user_id)
    if profile is None:
        return {
            "amount_total": 0.0,
            "amount_count": 0,
            "countries_seen": [],
            "merchants_seen": [],
        }

    return {
        "amount_total": float(profile.amount_total),
        "amount_count": int(profile.amount_count),
        "countries_seen": sorted(profile.countries_seen),
        "merchants_seen": sorted(profile.merchants_seen),
    }


def extract_window_transactions(
    window_store: SlidingWindowStore,
    user_id: str,
) -> list[TransactionRaw]:
    """Return the current window transactions for a user."""

    history = window_store._history.get(user_id)
    if not history:
        return []
    return list(history)


def main() -> None:
    configure_logging()

    window_max_seconds = SEVEN_DAYS_SECONDS
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "transaction_features.avsc"
    consumer = TransactionConsumer(
        broker_url=kafka_settings.broker_url,
        topic=kafka_settings.topics_raw,
        group_id="fraud-feature-engineering",
    )
    window_store = SlidingWindowStore(max_window_seconds=window_max_seconds)
    historical_store = HistoricalProfileStore()
    redis_store = RedisFeatureStore(
        host=redis_settings.host,
        port=redis_settings.port,
    )
    feature_publisher = FeaturePublisher(
        broker_url=kafka_settings.broker_url,
        topic=kafka_settings.topics_features,
        schema_path=str(schema_path),
    )
    initialized_users: set[str] = set()

    stop_event = threading.Event()
    install_signal_handlers(stop_event)

    try:
        while not stop_event.is_set():
            transaction = consumer.consume(timeout=1.0)
            if transaction is None:
                continue
            if transaction.user_id not in initialized_users:
                if redis_store.is_available:
                    hydrate_user_state(
                        transaction.user_id,
                        transaction.timestamp,
                        window_store,
                        historical_store,
                        redis_store,
                        window_max_seconds,
                    )
                initialized_users.add(transaction.user_id)
            logger.debug(
                "Consumed transaction %s for user %s",
                transaction.transaction_id,
                transaction.user_id,
            )
            window_features = window_store.compute_features(transaction)
            historical_features = historical_store.compute_features(transaction)
            window_store.add(transaction)
            historical_store.update(transaction)
            if redis_store.is_available:
                transactions = extract_window_transactions(window_store, transaction.user_id)
                historical_payload = build_historical_payload(
                    historical_store,
                    transaction.user_id,
                )
                redis_store.save_user_state(
                    transaction.user_id,
                    transactions,
                    historical_payload,
                )
            try:
                feature_publisher.publish(transaction, window_features, historical_features)
            except Exception as exc:
                logger.error(
                    "Failed to publish features for %s: %s",
                    transaction.transaction_id,
                    exc,
                )
            logger.debug(
                "Computed window features for %s: %s",
                transaction.transaction_id,
                window_features,
            )
            logger.debug(
                "Computed historical features for %s: %s",
                transaction.transaction_id,
                historical_features,
            )
            consumer.commit()
    finally:
        feature_publisher.close()
        redis_store.close()
        consumer.close()


if __name__ == "__main__":
    main()
