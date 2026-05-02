"""Generators for legitimate transaction events."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from .models import Transaction

MERCHANT_CATEGORIES = [
    "retail",
    "food",
    "travel",
    "entertainment",
    "gas_station",
    "online",
    "pharmacy",
]

CATEGORY_MEDIANS = {
    "pharmacy": 30.0,
    "travel": 500.0,
    "retail": 80.0,
    "food": 25.0,
    "entertainment": 60.0,
    "gas_station": 40.0,
    "online": 120.0,
}

CATEGORY_SIGMA = {
    "pharmacy": 0.4,
    "travel": 0.6,
    "retail": 0.5,
    "food": 0.4,
    "entertainment": 0.5,
    "gas_station": 0.4,
    "online": 0.6,
}

MAIN_COUNTRIES = ["AR", "BR", "US", "MX"]
MAIN_WEIGHTS = [0.70, 0.10, 0.08, 0.05]
OTHER_COUNTRIES = ["CL", "CO", "PE", "UY", "PY", "BO", "ES", "UK", "FR", "DE"]

DEVICE_TYPES = ["mobile", "web", "pos"]
DEVICE_WEIGHTS = [0.6, 0.3, 0.1]

AMOUNT_ANOMALY_MULTIPLIER_RANGE = (5.0, 10.0)
AMOUNT_ANOMALY_BASELINE_MIN = 300.0
HIGH_FREQUENCY_MIN_COUNT = 5
HIGH_FREQUENCY_MAX_COUNT = 8
HIGH_FREQUENCY_WINDOW_MINUTES = 30
UNKNOWN_MERCHANT_HIGH_AMOUNT_RANGE = (300.0, 1200.0)

LATAM_COUNTRIES = {"AR", "BR", "MX", "CL", "CO", "PE", "UY", "PY", "BO"}
NON_LATAM_COUNTRIES = {"US", "ES", "UK", "FR", "DE"}
UNCOMMON_COUNTRIES = set(OTHER_COUNTRIES)


@dataclass(frozen=True)
class UserProfile:
    """Represents the typical behavior of a user."""

    user_id: str
    home_country: str
    preferred_device: str
    spend_multiplier: float
    activity_weight: float
    frequent_merchants: list[str]


def build_country_weights() -> tuple[list[str], list[float]]:
    """Return countries and weights aligned with the reference distribution."""

    other_weight = (1.0 - sum(MAIN_WEIGHTS)) / len(OTHER_COUNTRIES)
    countries = MAIN_COUNTRIES + OTHER_COUNTRIES
    weights = MAIN_WEIGHTS + [other_weight] * len(OTHER_COUNTRIES)
    return countries, weights


def build_hour_weights() -> list[float]:
    """Return hour weights for realistic daily activity."""

    weights = []
    for hour in range(24):
        if 0 <= hour <= 6:
            weights.append(0.5)
        elif 7 <= hour <= 8:
            weights.append(1.0)
        elif 9 <= hour <= 11:
            weights.append(3.0)
        elif 12 <= hour <= 14:
            weights.append(5.0)
        elif 15 <= hour <= 17:
            weights.append(4.0)
        elif 18 <= hour <= 20:
            weights.append(5.0)
        elif 21 <= hour <= 22:
            weights.append(3.0)
        else:
            weights.append(1.0)
    return weights


def build_merchants(rng: random.Random, count: int) -> tuple[list[str], dict[str, str]]:
    """Return merchant ids and their categories."""

    merchant_ids: list[str] = []
    merchant_categories: dict[str, str] = {}
    for idx in range(1, count + 1):
        merchant_id = f"merchant_{idx:04d}"
        category = MERCHANT_CATEGORIES[(idx - 1) % len(MERCHANT_CATEGORIES)]
        merchant_ids.append(merchant_id)
        merchant_categories[merchant_id] = category
    rng.shuffle(merchant_ids)
    return merchant_ids, merchant_categories


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a float between minimum and maximum bounds."""

    return max(minimum, min(maximum, value))


def generate_timestamp(
    rng: random.Random,
    reference_time: datetime,
    hour_weights: list[float],
    days_back: int,
) -> datetime:
    """Generate a timestamp within the configured window using hour weights."""

    day_offset = rng.randint(0, days_back - 1)
    base = reference_time - timedelta(days=day_offset)
    hour = rng.choices(range(24), weights=hour_weights, k=1)[0]
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return base.replace(hour=hour, minute=minute, second=second, microsecond=0)


def generate_ip_hash(rng: random.Random) -> str:
    """Generate a deterministic hash from a random IP address."""

    ip_address = ".".join(str(rng.randint(1, 255)) for _ in range(4))
    return hashlib.sha256(ip_address.encode("utf-8")).hexdigest()


def generate_amount(
    rng: random.Random,
    category: str,
    spend_multiplier: float,
    category_medians: dict[str, float],
    category_sigma: dict[str, float],
) -> float:
    """Generate a log-normal amount adjusted by a user multiplier."""

    median = category_medians.get(category, 50.0)
    sigma = category_sigma.get(category, 0.5)
    mu = math.log(median)
    amount = rng.lognormvariate(mu, sigma) * spend_multiplier
    return round(max(amount, 1.0), 2)


def choose_country(
    rng: random.Random,
    home_country: str,
    countries: list[str],
    country_weights: list[float],
) -> str:
    """Choose a country with a strong bias toward the user's home."""

    if rng.random() < 0.85:
        return home_country
    return rng.choices(countries, weights=country_weights, k=1)[0]


def choose_device(rng: random.Random, preferred_device: str) -> str:
    """Choose a device with a strong bias toward the preferred one."""

    if rng.random() < 0.8:
        return preferred_device
    alternatives = [device for device in DEVICE_TYPES if device != preferred_device]
    return rng.choice(alternatives)


def choose_merchant(
    rng: random.Random, frequent_merchants: list[str], merchant_ids: list[str]
) -> str:
    """Choose a merchant, favoring the user's frequent list."""

    if rng.random() < 0.8:
        return rng.choice(frequent_merchants)
    return rng.choice(merchant_ids)


class LegitimateTransactionGenerator:
    """Generate realistic, non-fraudulent transaction events."""

    def __init__(
        self,
        seed: int | None = None,
        user_count: int = 1000,
        merchant_count: int = 500,
        days_back: int = 30,
        session_minutes: int = 60,
        category_medians: dict[str, float] | None = None,
        category_sigma: dict[str, float] | None = None,
    ) -> None:
        if user_count < 1:
            raise ValueError("user_count must be at least 1")
        if merchant_count < 5:
            raise ValueError("merchant_count must be at least 5")
        if days_back < 1:
            raise ValueError("days_back must be at least 1")
        if session_minutes < 1:
            raise ValueError("session_minutes must be at least 1")

        self._rng = random.Random(seed)
        self._user_count = user_count
        self._merchant_count = merchant_count
        self._days_back = days_back
        self._session_minutes = session_minutes
        self._category_medians = {**CATEGORY_MEDIANS, **(category_medians or {})}
        self._category_sigma = {**CATEGORY_SIGMA, **(category_sigma or {})}
        self._reference_time = datetime.now(UTC)

        self._merchant_ids, self._merchant_categories = build_merchants(self._rng, merchant_count)
        self._countries, self._country_weights = build_country_weights()
        self._hour_weights = build_hour_weights()
        self._users = self.generate_user_profiles()
        self._user_weights = [user.activity_weight for user in self._users]
        self._session_cache: dict[tuple[str, datetime], str] = {}

    def generate_user_profiles(self) -> list[UserProfile]:
        """Create user profiles with stable spending behavior and preferences."""

        users: list[UserProfile] = []
        for idx in range(1, self._user_count + 1):
            user_id = f"user_{idx:04d}"
            home_country = self._rng.choices(self._countries, weights=self._country_weights, k=1)[0]
            preferred_device = self._rng.choices(DEVICE_TYPES, weights=DEVICE_WEIGHTS, k=1)[0]
            spend_multiplier = clamp(self._rng.lognormvariate(0.0, 0.4), 0.4, 2.5)
            activity_weight = clamp(self._rng.lognormvariate(0.0, 0.6), 0.2, 3.0)
            frequent_merchants = self._rng.sample(self._merchant_ids, k=5)
            users.append(
                UserProfile(
                    user_id=user_id,
                    home_country=home_country,
                    preferred_device=preferred_device,
                    spend_multiplier=spend_multiplier,
                    activity_weight=activity_weight,
                    frequent_merchants=frequent_merchants,
                )
            )
        return users

    def generate_transaction(self) -> Transaction:
        """Generate a single legitimate transaction event."""

        user = self._rng.choices(self._users, weights=self._user_weights, k=1)[0]
        merchant_id = choose_merchant(self._rng, user.frequent_merchants, self._merchant_ids)
        merchant_category = self._merchant_categories[merchant_id]
        amount = generate_amount(
            self._rng,
            merchant_category,
            user.spend_multiplier,
            self._category_medians,
            self._category_sigma,
        )
        country = choose_country(
            self._rng, user.home_country, self._countries, self._country_weights
        )
        device_type = choose_device(self._rng, user.preferred_device)
        timestamp = generate_timestamp(
            self._rng, self._reference_time, self._hour_weights, self._days_back
        )
        ip_hash = self._get_session_ip_hash(user.user_id, timestamp)

        return Transaction(
            transaction_id=self._generate_transaction_id(),
            user_id=user.user_id,
            merchant_id=merchant_id,
            merchant_category=merchant_category,
            amount=amount,
            country=country,
            timestamp=timestamp,
            device_type=device_type,
            ip_hash=ip_hash,
        )

    def generate_batch(self, count: int) -> list[Transaction]:
        """Generate a batch of legitimate transactions."""

        if count < 0:
            raise ValueError("count must be non-negative")
        return [self.generate_transaction() for _ in range(count)]

    def _generate_transaction_id(self) -> UUID:
        return UUID(int=self._rng.getrandbits(128), version=4)

    def _get_session_ip_hash(self, user_id: str, timestamp: datetime) -> str:
        session_start = self._get_session_start(timestamp)
        cache_key = (user_id, session_start)
        cached = self._session_cache.get(cache_key)
        if cached is not None:
            return cached
        ip_hash = generate_ip_hash(self._rng)
        self._session_cache[cache_key] = ip_hash
        return ip_hash

    def _get_session_start(self, timestamp: datetime) -> datetime:
        total_minutes = timestamp.hour * 60 + timestamp.minute
        session_bucket = total_minutes // self._session_minutes
        session_start_minutes = session_bucket * self._session_minutes
        session_hour = session_start_minutes // 60
        session_minute = session_start_minutes % 60
        return timestamp.replace(
            hour=session_hour,
            minute=session_minute,
            second=0,
            microsecond=0,
        )


class FraudPatternGenerator:
    """Generate fraudulent transactions based on known patterns."""

    def __init__(
        self,
        legit_generator: LegitimateTransactionGenerator,
        seed: int | None = None,
        transactions: Iterable[Transaction] | None = None,
        amount_multiplier_range: tuple[float, float] = AMOUNT_ANOMALY_MULTIPLIER_RANGE,
        amount_baseline_min: float = AMOUNT_ANOMALY_BASELINE_MIN,
        high_frequency_range: tuple[int, int] = (
            HIGH_FREQUENCY_MIN_COUNT,
            HIGH_FREQUENCY_MAX_COUNT,
        ),
        high_frequency_window_minutes: int = HIGH_FREQUENCY_WINDOW_MINUTES,
        unknown_merchant_amount_range: tuple[float, float] = UNKNOWN_MERCHANT_HIGH_AMOUNT_RANGE,
    ) -> None:
        self._rng = random.Random(seed)
        self._legit_generator = legit_generator
        self._amount_multiplier_range = amount_multiplier_range
        self._amount_baseline_min = amount_baseline_min
        self._high_frequency_range = high_frequency_range
        self._high_frequency_window_minutes = high_frequency_window_minutes
        self._unknown_merchant_amount_range = unknown_merchant_amount_range

        self._merchant_ids = legit_generator._merchant_ids
        self._merchant_categories = legit_generator._merchant_categories
        self._countries = legit_generator._countries
        self._country_weights = legit_generator._country_weights
        self._hour_weights = legit_generator._hour_weights
        self._category_medians = legit_generator._category_medians
        self._category_sigma = legit_generator._category_sigma
        self._days_back = legit_generator._days_back
        self._reference_time = legit_generator._reference_time

        self._user_totals: defaultdict[str, float] = defaultdict(float)
        self._user_counts: defaultdict[str, int] = defaultdict(int)
        self._user_countries: defaultdict[str, set[str]] = defaultdict(set)
        self._user_merchants: defaultdict[str, set[str]] = defaultdict(set)

        if transactions is not None:
            self.update_context(transactions)

    def update_context(self, transactions: Iterable[Transaction]) -> None:
        """Record transactions to build user-level history."""

        for transaction in transactions:
            self._record_transaction(transaction)

    def apply_amount_anomaly(
        self, user_profile: UserProfile, transaction_history: list[Transaction]
    ) -> Transaction:
        """Generate a transaction with an unusually high amount."""

        base_transaction = self._build_transaction(user_profile)
        avg_amount = self._calculate_average_amount(user_profile.user_id, transaction_history)
        if avg_amount is None:
            median = self._category_medians.get(base_transaction.merchant_category, 50.0)
            avg_amount = max(self._amount_baseline_min, median * user_profile.spend_multiplier)

        multiplier = self._rng.uniform(*self._amount_multiplier_range)
        amount = round(max(avg_amount * multiplier, self._amount_baseline_min), 2)

        transaction = Transaction(
            transaction_id=self._generate_transaction_id(),
            user_id=base_transaction.user_id,
            merchant_id=base_transaction.merchant_id,
            merchant_category=base_transaction.merchant_category,
            amount=amount,
            country=base_transaction.country,
            timestamp=base_transaction.timestamp,
            device_type=base_transaction.device_type,
            ip_hash=base_transaction.ip_hash,
        )
        self._record_transaction(transaction)
        return transaction

    def apply_unusual_country(
        self, user_profile: UserProfile, countries_visited: list[str] | set[str]
    ) -> Transaction:
        """Generate a transaction from an unusual, distant country."""

        visited = self._resolve_countries_visited(user_profile.user_id, countries_visited)
        unusual_country = self._choose_unusual_country(user_profile.home_country, visited)
        base_transaction = self._build_transaction(user_profile, country=unusual_country)
        self._record_transaction(base_transaction)
        return base_transaction

    def apply_high_frequency(self, user_profile: UserProfile, count: int = 6) -> list[Transaction]:
        """Generate a burst of transactions within a short time window."""

        min_count, max_count = self._high_frequency_range
        burst_size = max(min_count, min(max_count, count))
        base_time = generate_timestamp(
            self._rng, self._reference_time, self._hour_weights, self._days_back
        )
        timestamps = sorted(
            base_time
            + timedelta(minutes=self._rng.randint(0, self._high_frequency_window_minutes - 1))
            + timedelta(seconds=self._rng.randint(0, 59))
            for _ in range(burst_size)
        )

        transactions: list[Transaction] = []
        merchant_pool = list(self._merchant_ids)
        self._rng.shuffle(merchant_pool)
        for idx, timestamp in enumerate(timestamps):
            merchant_id = merchant_pool[idx % len(merchant_pool)]
            merchant_category = self._merchant_categories[merchant_id]
            amount = generate_amount(
                self._rng,
                merchant_category,
                user_profile.spend_multiplier,
                self._category_medians,
                self._category_sigma,
            )
            device_type = choose_device(self._rng, user_profile.preferred_device)
            country = choose_country(
                self._rng, user_profile.home_country, self._countries, self._country_weights
            )
            transaction = self._build_transaction(
                user_profile,
                merchant_id=merchant_id,
                merchant_category=merchant_category,
                amount=amount,
                country=country,
                device_type=device_type,
                timestamp=self._clamp_timestamp(timestamp),
            )
            self._record_transaction(transaction)
            transactions.append(transaction)

        return transactions

    def apply_unknown_merchant_high_amount(
        self, user_profile: UserProfile, merchants_used: list[str] | set[str]
    ) -> Transaction:
        """Generate a transaction with a new merchant and elevated amount."""

        seen_merchants = self._resolve_merchants_used(user_profile.user_id, merchants_used)
        excluded = seen_merchants | set(user_profile.frequent_merchants)
        candidates = list(set(self._merchant_ids) - excluded)
        if not candidates:
            candidates = list(set(self._merchant_ids) - set(user_profile.frequent_merchants))
        if not candidates:
            candidates = list(self._merchant_ids)

        merchant_id = self._rng.choice(candidates)
        merchant_category = self._merchant_categories[merchant_id]
        amount = round(self._rng.uniform(*self._unknown_merchant_amount_range), 2)
        transaction = self._build_transaction(
            user_profile,
            merchant_id=merchant_id,
            merchant_category=merchant_category,
            amount=amount,
        )
        self._record_transaction(transaction)
        return transaction

    def _build_transaction(
        self,
        user_profile: UserProfile,
        *,
        merchant_id: str | None = None,
        merchant_category: str | None = None,
        amount: float | None = None,
        country: str | None = None,
        device_type: str | None = None,
        timestamp: datetime | None = None,
    ) -> Transaction:
        if merchant_id is None:
            merchant_id = choose_merchant(
                self._rng, user_profile.frequent_merchants, self._merchant_ids
            )
        if merchant_category is None:
            merchant_category = self._merchant_categories[merchant_id]
        if amount is None:
            amount = generate_amount(
                self._rng,
                merchant_category,
                user_profile.spend_multiplier,
                self._category_medians,
                self._category_sigma,
            )
        if country is None:
            country = choose_country(
                self._rng, user_profile.home_country, self._countries, self._country_weights
            )
        if device_type is None:
            device_type = choose_device(self._rng, user_profile.preferred_device)
        if timestamp is None:
            timestamp = generate_timestamp(
                self._rng, self._reference_time, self._hour_weights, self._days_back
            )

        ip_hash = self._legit_generator._get_session_ip_hash(user_profile.user_id, timestamp)

        return Transaction(
            transaction_id=self._generate_transaction_id(),
            user_id=user_profile.user_id,
            merchant_id=merchant_id,
            merchant_category=merchant_category,
            amount=amount,
            country=country,
            timestamp=timestamp,
            device_type=device_type,
            ip_hash=ip_hash,
        )

    def _record_transaction(self, transaction: Transaction) -> None:
        self._user_totals[transaction.user_id] += float(transaction.amount)
        self._user_counts[transaction.user_id] += 1
        self._user_countries[transaction.user_id].add(transaction.country)
        self._user_merchants[transaction.user_id].add(transaction.merchant_id)

    def _calculate_average_amount(
        self, user_id: str, transaction_history: Iterable[Transaction]
    ) -> float | None:
        total = 0.0
        count = 0
        for transaction in transaction_history:
            if transaction.user_id != user_id:
                continue
            total += float(transaction.amount)
            count += 1
        if count > 0:
            return total / count
        if self._user_counts.get(user_id, 0) > 0:
            return self._user_totals[user_id] / self._user_counts[user_id]
        return None

    def _resolve_countries_visited(
        self, user_id: str, countries_visited: Iterable[str]
    ) -> set[str]:
        visited = set(countries_visited)
        visited.update(self._user_countries.get(user_id, set()))
        return visited

    def _resolve_merchants_used(self, user_id: str, merchants_used: Iterable[str]) -> set[str]:
        used = set(merchants_used)
        used.update(self._user_merchants.get(user_id, set()))
        return used

    def _choose_unusual_country(self, home_country: str, visited: set[str]) -> str:
        visited = set(visited)
        visited.add(home_country)
        distant_candidates = self._get_distant_countries(home_country)
        candidates = [country for country in distant_candidates if country not in visited]
        if candidates:
            return self._rng.choice(candidates)

        uncommon_candidates = [country for country in UNCOMMON_COUNTRIES if country not in visited]
        if uncommon_candidates:
            return self._rng.choice(uncommon_candidates)

        remaining = [country for country in self._countries if country not in visited]
        if remaining:
            return self._rng.choice(remaining)

        fallback = [country for country in self._countries if country != home_country]
        if fallback:
            return self._rng.choice(fallback)
        return home_country

    def _get_distant_countries(self, home_country: str) -> set[str]:
        if home_country in LATAM_COUNTRIES:
            return set(NON_LATAM_COUNTRIES)
        if home_country in NON_LATAM_COUNTRIES:
            return set(LATAM_COUNTRIES)
        return set(self._countries)

    def _generate_transaction_id(self) -> UUID:
        return UUID(int=self._rng.getrandbits(128), version=4)

    def _clamp_timestamp(self, timestamp: datetime) -> datetime:
        if timestamp <= self._reference_time:
            return timestamp
        return self._reference_time - timedelta(
            minutes=self._rng.randint(0, self._high_frequency_window_minutes - 1)
        )
