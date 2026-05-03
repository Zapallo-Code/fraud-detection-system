"""Data models for the transaction consumer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TransactionRaw:
    """Represents a raw transaction event consumed from Kafka."""

    transaction_id: str
    user_id: str
    merchant_id: str
    merchant_category: str
    amount: float
    country: str
    timestamp: datetime
    device_type: str
    ip_hash: str


__all__ = ["TransactionRaw"]
