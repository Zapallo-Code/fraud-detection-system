"""Data models for window-based features."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WindowFeatures:
    """Feature values computed from sliding transaction windows."""

    tx_count_1h: int
    tx_count_24h: int
    tx_count_7d: int
    amount_sum_1h: float
    amount_sum_24h: float
    tx_velocity_1h: float
    seconds_since_last_tx: float


__all__ = ["WindowFeatures"]
