"""Data models for the transaction producer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Transaction:
    """Represents a raw transaction event for ingestion."""

    transaction_id: UUID
    user_id: str
    merchant_id: str
    merchant_category: str
    amount: float
    country: str
    timestamp: datetime
    device_type: str
    ip_hash: str
