#!/usr/bin/env python3
import argparse
import hashlib
import math
import os
import random
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

import psycopg2
from psycopg2.extras import execute_values

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed synthetic transactions into TimescaleDB.")
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--fraud-rate", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def get_db_config() -> dict:
    return {
        "host": os.getenv("TIMESCALEDB_HOST", "localhost"),
        "port": int(os.getenv("TIMESCALEDB_PORT", "5432")),
        "user": os.getenv("TIMESCALEDB_USER", "postgres"),
        "password": os.getenv("TIMESCALEDB_PASSWORD", "postgres"),
        "dbname": os.getenv("TIMESCALEDB_DB", "timescaledb"),
    }


def build_country_weights() -> tuple[list[str], list[float]]:
    other_weight = (1.0 - sum(MAIN_WEIGHTS)) / len(OTHER_COUNTRIES)
    countries = MAIN_COUNTRIES + OTHER_COUNTRIES
    weights = MAIN_WEIGHTS + [other_weight] * len(OTHER_COUNTRIES)
    return countries, weights


def build_hour_weights() -> list[float]:
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
    merchant_ids = []
    merchant_categories = {}
    for idx in range(1, count + 1):
        merchant_id = f"merchant_{idx:04d}"
        category = MERCHANT_CATEGORIES[(idx - 1) % len(MERCHANT_CATEGORIES)]
        merchant_ids.append(merchant_id)
        merchant_categories[merchant_id] = category
    rng.shuffle(merchant_ids)
    return merchant_ids, merchant_categories


def build_users(
    rng: random.Random,
    count: int,
    merchant_ids: list[str],
    countries: list[str],
    country_weights: list[float],
) -> list[dict]:
    users = []
    for idx in range(1, count + 1):
        user_id = f"user_{idx:04d}"
        home_country = rng.choices(countries, weights=country_weights, k=1)[0]
        preferred_device = rng.choices(DEVICE_TYPES, weights=DEVICE_WEIGHTS, k=1)[0]
        spend_multiplier = max(0.4, min(2.5, rng.lognormvariate(0.0, 0.4)))
        activity_weight = max(0.2, min(3.0, rng.lognormvariate(0.0, 0.6)))
        frequent_merchants = rng.sample(merchant_ids, k=5)
        users.append(
            {
                "user_id": user_id,
                "home_country": home_country,
                "preferred_device": preferred_device,
                "spend_multiplier": spend_multiplier,
                "activity_weight": activity_weight,
                "frequent_merchants": frequent_merchants,
            }
        )
    return users


def generate_timestamp(rng: random.Random, now: datetime, hour_weights: list[float]) -> datetime:
    day_offset = rng.randint(0, 29)
    base = now - timedelta(days=day_offset)
    hour = rng.choices(range(24), weights=hour_weights, k=1)[0]
    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    return base.replace(hour=hour, minute=minute, second=second, microsecond=0)


def generate_ip_hash(rng: random.Random) -> str:
    ip = ".".join(str(rng.randint(1, 255)) for _ in range(4))
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()


def generate_amount(rng: random.Random, category: str, spend_multiplier: float) -> float:
    median = CATEGORY_MEDIANS.get(category, 50.0)
    sigma = CATEGORY_SIGMA.get(category, 0.5)
    mu = math.log(median)
    amount = rng.lognormvariate(mu, sigma) * spend_multiplier
    amount = max(amount, 1.0)
    return round(amount, 2)


def choose_country(
    rng: random.Random,
    home_country: str,
    countries: list[str],
    country_weights: list[float],
) -> str:
    if rng.random() < 0.85:
        return home_country
    return rng.choices(countries, weights=country_weights, k=1)[0]


def choose_device(rng: random.Random, preferred_device: str) -> str:
    if rng.random() < 0.8:
        return preferred_device
    return rng.choice([d for d in DEVICE_TYPES if d != preferred_device])


def choose_merchant(
    rng: random.Random, frequent_merchants: list[str], merchant_ids: list[str]
) -> str:
    if rng.random() < 0.8:
        return rng.choice(frequent_merchants)
    return rng.choice(merchant_ids)


def generate_transactions(
    rng: random.Random,
    count: int,
    users: list[dict],
    merchant_ids: list[str],
    merchant_categories: dict[str, str],
    countries: list[str],
    country_weights: list[float],
    hour_weights: list[float],
    transaction_namespace: uuid.UUID,
) -> list[dict]:
    now = datetime.now(UTC)
    user_weights = [user["activity_weight"] for user in users]
    transactions = []
    for idx in range(count):
        user = rng.choices(users, weights=user_weights, k=1)[0]
        merchant_id = choose_merchant(rng, user["frequent_merchants"], merchant_ids)
        category = merchant_categories[merchant_id]
        amount = generate_amount(rng, category, user["spend_multiplier"])
        country = choose_country(rng, user["home_country"], countries, country_weights)
        device_type = choose_device(rng, user["preferred_device"])
        timestamp = generate_timestamp(rng, now, hour_weights)
        transactions.append(
            {
                "transaction_id": uuid.uuid5(transaction_namespace, f"transaction-{idx}"),
                "user_id": user["user_id"],
                "merchant_id": merchant_id,
                "merchant_category": category,
                "amount": amount,
                "country": country,
                "timestamp": timestamp,
                "device_type": device_type,
                "ip_hash": generate_ip_hash(rng),
                "is_fraud": False,
                "model_score": None,
                "latency_ms": None,
            }
        )
    return transactions


def compute_user_average_amount(transactions: list[dict]) -> dict[str, float]:
    totals = defaultdict(float)
    counts = defaultdict(int)
    for tx in transactions:
        totals[tx["user_id"]] += float(tx["amount"])
        counts[tx["user_id"]] += 1
    return {user_id: totals[user_id] / counts[user_id] for user_id in totals}


def compute_user_seen_merchants(transactions: list[dict]) -> dict[str, set[str]]:
    seen = defaultdict(set)
    for tx in transactions:
        seen[tx["user_id"]].add(tx["merchant_id"])
    return seen


def compute_user_home_countries(users: list[dict]) -> dict[str, str]:
    return {user["user_id"]: user["home_country"] for user in users}


def compute_user_indices(transactions: list[dict]) -> dict[str, list[int]]:
    user_indices = defaultdict(list)
    for idx, tx in enumerate(transactions):
        user_indices[tx["user_id"]].append(idx)
    return user_indices


def apply_amount_anomaly(
    rng: random.Random,
    transactions: list[dict],
    available_indices: set[int],
    user_avg_amount: dict[str, float],
    count: int,
) -> int:
    if count <= 0 or not available_indices:
        return 0
    chosen = rng.sample(list(available_indices), k=min(count, len(available_indices)))
    for idx in chosen:
        tx = transactions[idx]
        avg = user_avg_amount.get(tx["user_id"], float(tx["amount"]))
        multiplier = rng.uniform(5.0, 10.0)
        tx["amount"] = round(max(avg * multiplier, float(tx["amount"])), 2)
        tx["is_fraud"] = True
        available_indices.remove(idx)
    return len(chosen)


def apply_unusual_country(
    rng: random.Random,
    transactions: list[dict],
    available_indices: set[int],
    user_home_countries: dict[str, str],
    countries: list[str],
    count: int,
) -> int:
    if count <= 0 or not available_indices:
        return 0
    applied = 0
    attempts = 0
    max_attempts = count * 20
    while applied < count and attempts < max_attempts and available_indices:
        idx = rng.choice(list(available_indices))
        tx = transactions[idx]
        home_country = user_home_countries.get(tx["user_id"], tx["country"])
        different_countries = [c for c in countries if c != home_country]
        if not different_countries:
            attempts += 1
            continue
        tx["country"] = rng.choice(different_countries)
        tx["is_fraud"] = True
        available_indices.remove(idx)
        applied += 1
    return applied


def apply_high_frequency(
    rng: random.Random,
    transactions: list[dict],
    available_indices: set[int],
    user_indices: dict[str, list[int]],
    now: datetime,
    count: int,
) -> int:
    if count <= 0 or not available_indices:
        return 0
    remaining = count
    users = list(user_indices.keys())
    while remaining > 0:
        candidates = []
        for user_id in users:
            available_user_indices = [
                idx for idx in user_indices[user_id] if idx in available_indices
            ]
            if len(available_user_indices) >= 5:
                candidates.append((user_id, available_user_indices))
        if not candidates:
            break
        user_id, available_user_indices = rng.choice(candidates)
        burst_target = rng.randint(5, 8)
        burst_size = min(remaining, burst_target, len(available_user_indices))
        if burst_size < 5:
            break
        chosen = rng.sample(available_user_indices, k=burst_size)
        base_time = transactions[chosen[0]]["timestamp"]
        for idx in chosen:
            tx = transactions[idx]
            delta = timedelta(minutes=rng.randint(0, 29), seconds=rng.randint(0, 59))
            new_time = base_time + delta
            if new_time > now:
                new_time = now - timedelta(minutes=rng.randint(0, 29))
            tx["timestamp"] = new_time
            tx["is_fraud"] = True
            available_indices.remove(idx)
        remaining -= burst_size
    return count - remaining


def apply_unknown_merchant_high_amount(
    rng: random.Random,
    transactions: list[dict],
    available_indices: set[int],
    user_indices: dict[str, list[int]],
    user_seen_merchants: dict[str, set[str]],
    merchant_ids: list[str],
    merchant_categories: dict[str, str],
    count: int,
) -> int:
    if count <= 0 or not available_indices:
        return 0
    remaining = count
    users = list(user_indices.keys())
    all_merchants = set(merchant_ids)
    attempts = 0
    max_attempts = count * 50
    while remaining > 0 and attempts < max_attempts:
        user_id = rng.choice(users)
        available_user_indices = [idx for idx in user_indices[user_id] if idx in available_indices]
        if not available_user_indices:
            attempts += 1
            continue
        unseen = list(all_merchants - user_seen_merchants[user_id])
        if not unseen:
            attempts += 1
            continue
        idx = rng.choice(available_user_indices)
        merchant_id = rng.choice(unseen)
        tx = transactions[idx]
        tx["merchant_id"] = merchant_id
        tx["merchant_category"] = merchant_categories[merchant_id]
        tx["amount"] = round(rng.uniform(300.0, 1200.0), 2)
        tx["is_fraud"] = True
        available_indices.remove(idx)
        user_seen_merchants[user_id].add(merchant_id)
        remaining -= 1
    return count - remaining


def insert_transactions(connection, transactions: list[dict], batch_size: int) -> None:
    insert_sql = (
        "INSERT INTO public.transactions "
        "(transaction_id, user_id, merchant_id, merchant_category, amount, country, "
        '"timestamp", device_type, ip_hash, is_fraud, model_score, latency_ms) '
        "VALUES %s"
    )
    total = len(transactions)
    inserted = 0
    try:
        with connection.cursor() as cursor:
            for start in range(0, total, batch_size):
                batch = transactions[start : start + batch_size]
                values = [
                    (
                        str(tx["transaction_id"]),
                        tx["user_id"],
                        tx["merchant_id"],
                        tx["merchant_category"],
                        tx["amount"],
                        tx["country"],
                        tx["timestamp"],
                        tx["device_type"],
                        tx["ip_hash"],
                        tx["is_fraud"],
                        tx["model_score"],
                        tx["latency_ms"],
                    )
                    for tx in batch
                ]
                execute_values(cursor, insert_sql, values)
                connection.commit()
                inserted += len(batch)
                if inserted % 1000 == 0 or inserted == total:
                    print(f"Inserted {inserted}/{total} transactions")
    except psycopg2.Error:
        connection.rollback()
        raise


def print_summary(transactions: list[dict]) -> None:
    total = len(transactions)
    fraud_total = sum(1 for tx in transactions if tx["is_fraud"])
    countries = Counter(tx["country"] for tx in transactions)
    min_ts = min(tx["timestamp"] for tx in transactions)
    max_ts = max(tx["timestamp"] for tx in transactions)
    print("\nSummary")
    print(f"Total inserted: {total}")
    print(f"Total fraud: {fraud_total}")
    print("Country distribution:")
    for country, count in countries.most_common():
        pct = (count / total) * 100
        print(f"  {country}: {count} ({pct:.1f}%)")
    print(f"Date range: {min_ts.isoformat()} to {max_ts.isoformat()}")


def validate_args(args: argparse.Namespace) -> None:
    if args.count <= 0:
        raise SystemExit("--count must be greater than 0")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be greater than 0")
    if args.fraud_rate < 0 or args.fraud_rate > 1:
        raise SystemExit("--fraud-rate must be between 0 and 1")


def main() -> None:
    args = parse_args()
    validate_args(args)

    rng = random.Random(args.seed)
    countries, country_weights = build_country_weights()
    hour_weights = build_hour_weights()

    merchant_ids, merchant_categories = build_merchants(rng, 50)
    users = build_users(rng, 200, merchant_ids, countries, country_weights)
    transaction_namespace = uuid.uuid5(uuid.NAMESPACE_DNS, f"seed-{args.seed}")

    transactions = generate_transactions(
        rng,
        args.count,
        users,
        merchant_ids,
        merchant_categories,
        countries,
        country_weights,
        hour_weights,
        transaction_namespace,
    )

    user_avg_amount = compute_user_average_amount(transactions)
    user_seen_merchants = compute_user_seen_merchants(transactions)
    user_home_countries = compute_user_home_countries(users)
    user_indices = compute_user_indices(transactions)

    fraud_total = int(round(args.count * args.fraud_rate))
    fraud_total = min(max(fraud_total, 0), args.count)
    base = fraud_total // 4
    pattern_counts = [base, base, base, base]
    for idx in range(fraud_total - base * 4):
        pattern_counts[idx] += 1

    available_indices = set(range(len(transactions)))
    now = datetime.now(UTC)

    applied_counts = []
    applied_counts.append(
        apply_amount_anomaly(
            rng, transactions, available_indices, user_avg_amount, pattern_counts[0]
        )
    )
    applied_counts.append(
        apply_unusual_country(
            rng,
            transactions,
            available_indices,
            user_home_countries,
            countries,
            pattern_counts[1],
        )
    )
    applied_counts.append(
        apply_high_frequency(
            rng,
            transactions,
            available_indices,
            user_indices,
            now,
            pattern_counts[2],
        )
    )
    applied_counts.append(
        apply_unknown_merchant_high_amount(
            rng,
            transactions,
            available_indices,
            user_indices,
            user_seen_merchants,
            merchant_ids,
            merchant_categories,
            pattern_counts[3],
        )
    )

    remaining_fraud = fraud_total - sum(applied_counts)
    if remaining_fraud > 0:
        apply_amount_anomaly(rng, transactions, available_indices, user_avg_amount, remaining_fraud)

    config = get_db_config()
    with psycopg2.connect(**config) as connection:
        insert_transactions(connection, transactions, args.batch_size)

    print_summary(transactions)


if __name__ == "__main__":
    main()
