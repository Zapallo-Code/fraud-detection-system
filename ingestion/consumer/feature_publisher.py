"""Kafka publisher for transaction feature messages."""

from __future__ import annotations

import io
import json
import logging
from dataclasses import asdict
from datetime import UTC
from pathlib import Path
from typing import Any

from confluent_kafka import KafkaException, Producer
from fastavro import parse_schema, schemaless_writer

from .feature_models import HistoricalFeatures, WindowFeatures
from .models import TransactionRaw

logger = logging.getLogger(__name__)


class FeaturePublisher:
    """Publish enriched transaction features to Kafka using Avro serialization."""

    def __init__(
        self,
        broker_url: str,
        topic: str,
        schema_path: str,
        acks: str = "all",
        retries: int = 3,
        max_in_flight: int = 5,
    ) -> None:
        self._broker_url = broker_url
        self._topic = topic
        self._schema_path = Path(schema_path)

        self._avro_schema = self._load_schema(self._schema_path)

        config = {
            "bootstrap.servers": broker_url,
            "acks": acks,
            "retries": retries,
            "max.in.flight.requests.per.connection": max_in_flight,
            "compression.type": "snappy",
            "enable.idempotence": True,
            "client.id": "fraud-feature-engineering-publisher",
        }
        self._producer = Producer(config)

        logger.info(
            "Initialized Kafka feature publisher for topic %s with broker %s",
            self._topic,
            self._broker_url,
        )

    @staticmethod
    def _load_schema(schema_path: Path) -> dict[str, Any]:
        try:
            with schema_path.open("r", encoding="utf-8") as file:
                raw_schema = json.load(file)
        except FileNotFoundError:
            logger.error("Avro schema not found at %s", schema_path)
            raise
        except json.JSONDecodeError as exc:
            logger.error("Invalid Avro schema JSON at %s", schema_path)
            raise ValueError("Invalid Avro schema JSON") from exc

        return parse_schema(raw_schema)

    def publish(
        self,
        transaction: TransactionRaw,
        window_features: WindowFeatures,
        historical_features: HistoricalFeatures,
    ) -> None:
        """Publish a transaction enriched with calculated features."""

        payload = self._build_payload(transaction, window_features, historical_features)
        serialized = self._serialize_avro(payload)
        transaction_id = transaction.transaction_id

        try:
            self._producer.produce(
                self._topic,
                key=transaction_id,
                value=serialized,
                on_delivery=lambda err, msg: self._delivery_callback(err, msg, transaction_id),
            )
            self._producer.poll(0.0)
        except KafkaException as exc:
            logger.error("Failed to publish features for transaction %s: %s", transaction_id, exc)
            raise
        except BufferError as exc:
            logger.error("Publisher queue full for transaction %s: %s", transaction_id, exc)
            raise

    def flush(self) -> None:
        """Wait until all pending messages are delivered."""

        try:
            remaining = self._producer.flush()
        except KafkaException as exc:
            logger.error("Failed to flush feature publisher: %s", exc)
            raise

        if remaining:
            logger.warning(
                "Feature publisher flush completed with %s messages remaining", remaining
            )

    def close(self) -> None:
        """Close the publisher cleanly."""

        logger.info("Closing Kafka feature publisher for topic %s", self._topic)
        self.flush()

    @staticmethod
    def _flatten_features(
        window_features: WindowFeatures,
        historical_features: HistoricalFeatures,
    ) -> dict[str, float]:
        window_values = {key: float(value) for key, value in asdict(window_features).items()}
        historical_values = {
            key: float(value) for key, value in asdict(historical_features).items()
        }
        return {**window_values, **historical_values}

    def _build_payload(
        self,
        transaction: TransactionRaw,
        window_features: WindowFeatures,
        historical_features: HistoricalFeatures,
    ) -> dict[str, Any]:
        timestamp = transaction.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        else:
            timestamp = timestamp.astimezone(UTC)
        timestamp_millis = int(timestamp.timestamp() * 1000)

        return {
            "transaction_id": transaction.transaction_id,
            "user_id": transaction.user_id,
            "merchant_id": transaction.merchant_id,
            "merchant_category": transaction.merchant_category,
            "amount": float(transaction.amount),
            "country": transaction.country,
            "timestamp": timestamp_millis,
            "device_type": transaction.device_type,
            "ip_hash": transaction.ip_hash,
            "features": self._flatten_features(window_features, historical_features),
        }

    def _serialize_avro(self, payload: dict[str, Any]) -> bytes:
        buffer = io.BytesIO()
        schemaless_writer(buffer, self._avro_schema, payload)
        return buffer.getvalue()

    def _delivery_callback(self, error: Exception | None, message, transaction_id: str) -> None:
        if error is not None:
            logger.error("Feature delivery failed for transaction %s: %s", transaction_id, error)
            return

        logger.debug(
            "Delivered features for transaction %s to %s [%s] at offset %s",
            transaction_id,
            message.topic(),
            message.partition(),
            message.offset(),
        )


__all__ = ["FeaturePublisher"]
