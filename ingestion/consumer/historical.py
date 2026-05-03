"""Historical behavior store for long-term user features."""

from __future__ import annotations

from dataclasses import dataclass

from .feature_models import HistoricalFeatures
from .models import TransactionRaw


@dataclass
class _UserProfile:
    amount_total: float
    amount_count: int
    countries_seen: set[str]
    merchants_seen: set[str]


class HistoricalProfileStore:
    """Maintain historical aggregates per user for feature engineering."""

    def __init__(self) -> None:
        self._profiles: dict[str, _UserProfile] = {}

    def compute_features(self, transaction: TransactionRaw) -> HistoricalFeatures:
        """Compute historical features using state before this transaction."""

        profile = self._profiles.get(transaction.user_id)
        if profile is None or profile.amount_count == 0:
            ratio = 1.0
            countries_seen = set()
            merchants_seen = set()
        else:
            avg_amount = profile.amount_total / profile.amount_count
            ratio = float(transaction.amount) / avg_amount if avg_amount > 0 else 1.0
            countries_seen = profile.countries_seen
            merchants_seen = profile.merchants_seen

        is_country_new = 1.0 if transaction.country not in countries_seen else 0.0
        is_merchant_new = 1.0 if transaction.merchant_id not in merchants_seen else 0.0

        return HistoricalFeatures(
            amount_ratio_vs_user_avg=ratio,
            is_country_new=is_country_new,
            distinct_countries_seen=len(countries_seen),
            is_merchant_new=is_merchant_new,
            distinct_merchants_seen=len(merchants_seen),
        )

    def update(self, transaction: TransactionRaw) -> None:
        """Update the historical aggregates with this transaction."""

        profile = self._profiles.get(transaction.user_id)
        if profile is None:
            profile = _UserProfile(
                amount_total=0.0,
                amount_count=0,
                countries_seen=set(),
                merchants_seen=set(),
            )
            self._profiles[transaction.user_id] = profile

        profile.amount_total += float(transaction.amount)
        profile.amount_count += 1
        profile.countries_seen.add(transaction.country)
        profile.merchants_seen.add(transaction.merchant_id)


__all__ = ["HistoricalProfileStore"]
