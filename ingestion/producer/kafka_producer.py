"""Kafka producer for transaction events."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

from confluent_kafka import KafkaException, Producer
from fastavro import parse_schema, schemaless_writer

from .models import Transaction

logger = logging.getLogger(__name__)


class TransactionProducer:
    """Produce transaction events to Kafka using Avro serialization."""

    def __init__(
        self,
        broker_url: str,
        schema_registry_url: str,
        topic: str,
        schema_path: str,
        acks: str = "all",
        retries: int = 3,
        max_in_flight: int = 5,
    ) -> None:
        self._broker_url = broker_url
        self._schema_registry_url = schema_registry_url
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
            "client.id": "fraud-detection-producer",
        }
        self._producer = Producer(config)

        logger.info(
            "Initialized Kafka producer for topic %s with broker %s",
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

    def _transaction_to_dict(self, transaction: Transaction) -> dict[str, Any]:
        """Convert Transaction to a dict compatible with the Avro schema."""

        timestamp = transaction.timestamp
        if timestamp.tzinfo is None:
            raise ValueError("Transaction timestamp must be timezone-aware")

        timestamp_millis = int(timestamp.timestamp() * 1000)
        return {
            "transaction_id": str(transaction.transaction_id),
            "user_id": transaction.user_id,
            "merchant_id": transaction.merchant_id,
            "merchant_category": transaction.merchant_category,
            "amount": float(transaction.amount),
            "country": transaction.country,
            "timestamp": timestamp_millis,
            "device_type": transaction.device_type,
            "ip_hash": transaction.ip_hash,
        }

    def _serialize_avro(self, data: dict[str, Any]) -> bytes:
        """Serialize a dict to Avro bytes using the loaded schema."""

        buffer = io.BytesIO()
        schemaless_writer(buffer, self._avro_schema, data)
        return buffer.getvalue()

    def send(self, transaction: Transaction) -> None:
        """Send a transaction to the Kafka topic."""

        payload = self._serialize_avro(self._transaction_to_dict(transaction))
        transaction_id = str(transaction.transaction_id)

        try:
            self._producer.produce(
                self._topic,
                key=transaction_id,
                value=payload,
                on_delivery=lambda err, msg: self._delivery_callback(err, msg, transaction_id),
            )
            self._producer.poll(0.0)
        except KafkaException as exc:
            logger.error("Failed to send transaction %s: %s", transaction_id, exc)
            raise
        except BufferError as exc:
            logger.error("Producer queue full for transaction %s: %s", transaction_id, exc)
            raise

    def flush(self) -> None:
        """Wait until all pending messages are delivered."""

        try:
            remaining = self._producer.flush()
        except KafkaException as exc:
            logger.error("Failed to flush producer: %s", exc)
            raise

        if remaining:
            logger.warning("Producer flush completed with %s messages remaining", remaining)

    def close(self) -> None:
        """Close the producer cleanly."""

        logger.info("Closing Kafka producer for topic %s", self._topic)
        self.flush()

    def _delivery_callback(self, error: Exception | None, message, transaction_id: str) -> None:
        if error is not None:
            logger.error("Delivery failed for transaction %s: %s", transaction_id, error)
            return

        logger.debug(
            "Delivered transaction %s to %s [%s] at offset %s",
            transaction_id,
            message.topic(),
            message.partition(),
            message.offset(),
        )


__all__ = ["TransactionProducer"]
