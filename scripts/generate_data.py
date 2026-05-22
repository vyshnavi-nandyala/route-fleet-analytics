"""Synthetic data generator for route-fleet-analytics."""

import argparse
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

fake = Faker()
random.seed(42)
np.random.seed(42)

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"

HOUSTON_LAT = (29.5, 30.1)
HOUSTON_LON = (-95.8, -95.1)

MAKES_MODELS = {
    "Ford": ["F-150", "Transit", "Explorer", "E-350"],
    "Chevrolet": ["Silverado", "Express", "Colorado", "Tahoe"],
    "Toyota": ["Tundra", "Tacoma", "Camry", "Highlander"],
    "Freightliner": ["M2 106", "Cascadia", "Sprinter", "XB"],
    "Isuzu": ["NPR", "NQR", "FTR", "NRR"],
    "Kenworth": ["T680", "T880", "T270", "W990"],
}

VEHICLE_CLASS_MAP = {
    "Ford": {"F-150": "light", "Transit": "medium", "Explorer": "light", "E-350": "medium"},
    "Chevrolet": {"Silverado": "light", "Express": "medium", "Colorado": "light", "Tahoe": "light"},
    "Toyota": {"Tundra": "light", "Tacoma": "light", "Camry": "light", "Highlander": "light"},
    "Freightliner": {"M2 106": "heavy", "Cascadia": "heavy", "Sprinter": "medium", "XB": "medium"},
    "Isuzu": {"NPR": "medium", "NQR": "medium", "FTR": "heavy", "NRR": "medium"},
    "Kenworth": {"T680": "heavy", "T880": "heavy", "T270": "medium", "W990": "heavy"},
}

ZONES = ["North", "South", "East", "West", "Central", "Northeast", "Southwest"]
DISTRICTS = ["District-1", "District-2", "District-3", "District-4", "District-5"]
SERVICE_TYPES = [
    "Oil Change", "Tire Rotation", "Brake Inspection", "Engine Tune-up",
    "Transmission Service", "Air Filter Replacement", "Battery Replacement",
    "Coolant Flush", "Alignment", "Annual Inspection",
]


def generate_routes(n: int = 50) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        n_stops = random.randint(4, 20)
        rows.append({
            "route_id": f"RT-{i:04d}",
            "route_name": f"{random.choice(ZONES)} Route {i}",
            "zone": random.choice(ZONES),
            "district": random.choice(DISTRICTS),
            "total_stops": n_stops,
            "created_at": fake.date_time_between(start_date="-3y", end_date="-1y").isoformat(),
        })
    return pd.DataFrame(rows)


def generate_vehicles(n: int = 200) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        make = random.choice(list(MAKES_MODELS.keys()))
        model = random.choice(MAKES_MODELS[make])
        vclass = VEHICLE_CLASS_MAP[make][model]
        rows.append({
            "vehicle_id": f"VH-{i:04d}",
            "make": make,
            "model": model,
            "year": random.randint(2015, 2024),
            "vehicle_class": vclass,
            "status": random.choices(["active", "inactive", "maintenance"], weights=[0.75, 0.15, 0.10])[0],
            "vin": fake.unique.bothify(text="?#?#?#?#?#?#?#?#?"),
            "license_plate": fake.bothify(text="??-####"),
        })
    return pd.DataFrame(rows)


def generate_stops(routes_df: pd.DataFrame, n: int = 500) -> pd.DataFrame:
    route_ids = routes_df["route_id"].tolist()
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "stop_id": f"ST-{i:05d}",
            "route_id": random.choice(route_ids),
            "stop_name": fake.street_address(),
            "stop_sequence": random.randint(1, 20),
            "lat": round(random.uniform(*HOUSTON_LAT), 6),
            "lon": round(random.uniform(*HOUSTON_LON), 6),
            "stop_type": random.choice(["pickup", "dropoff", "transfer", "depot"]),
        })
    return pd.DataFrame(rows)


def generate_gps_events(
    vehicles_df: pd.DataFrame,
    routes_df: pd.DataFrame,
    n: int = 50000,
) -> pd.DataFrame:
    vehicle_ids = vehicles_df[vehicles_df["status"] == "active"]["vehicle_id"].tolist()
    route_ids = routes_df["route_id"].tolist()

    base_ts = datetime.now() - timedelta(days=90)
    timestamps = [base_ts + timedelta(seconds=random.randint(0, 90 * 86400)) for _ in range(n)]
    timestamps.sort()

    lats = np.random.uniform(*HOUSTON_LAT, size=n).round(6)
    lons = np.random.uniform(*HOUSTON_LON, size=n).round(6)

    speeds = np.concatenate([
        np.random.uniform(0, 4, size=int(n * 0.12)),
        np.random.uniform(5, 35, size=int(n * 0.55)),
        np.random.uniform(36, 65, size=int(n * 0.30)),
        np.random.uniform(66, 80, size=n - int(n * 0.97)),
    ])
    np.random.shuffle(speeds)
    speeds = speeds[:n].round(1)

    rows = {
        "event_id": [f"EV-{i:07d}" for i in range(1, n + 1)],
        "vehicle_id": [random.choice(vehicle_ids) for _ in range(n)],
        "route_id": [random.choice(route_ids) for _ in range(n)],
        "lat": lats,
        "lon": lons,
        "speed_mph": speeds,
        "heading_deg": np.random.randint(0, 360, size=n),
        "event_ts": [ts.isoformat() for ts in timestamps],
        "event_date": [ts.date().isoformat() for ts in timestamps],
    }
    return pd.DataFrame(rows)


def generate_maintenance_logs(vehicles_df: pd.DataFrame, n: int = 2000) -> pd.DataFrame:
    vehicle_ids = vehicles_df["vehicle_id"].tolist()
    rows = []
    for i in range(1, n + 1):
        service_date = fake.date_between(start_date="-2y", end_date="today")
        service_type = random.choice(SERVICE_TYPES)
        cost = round(random.uniform(50, 2500), 2)
        rows.append({
            "log_id": f"ML-{i:06d}",
            "vehicle_id": random.choice(vehicle_ids),
            "service_type": service_type,
            "service_date": service_date.isoformat(),
            "cost_usd": cost,
            "mileage_at_service": random.randint(5000, 250000),
            "technician": fake.name(),
            "notes": fake.sentence(nb_words=8),
        })
    return pd.DataFrame(rows)


def save(df: pd.DataFrame, name: str) -> None:
    out_path = RAW_DIR / f"{name}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"  Wrote {len(df):,} rows → {out_path}")


def main(rows: int = 50000) -> None:
    print("Generating synthetic fleet data...")

    routes = generate_routes(50)
    save(routes, "routes")

    vehicles = generate_vehicles(200)
    save(vehicles, "vehicles")

    stops = generate_stops(routes, 500)
    save(stops, "stops")

    gps_events = generate_gps_events(vehicles, routes, rows)
    save(gps_events, "gps_events")

    maintenance_logs = generate_maintenance_logs(vehicles, 2000)
    save(maintenance_logs, "maintenance_logs")

    print(f"\nDone. All files written to {RAW_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic fleet data")
    parser.add_argument("--rows", type=int, default=50000, help="Number of GPS event rows")
    args = parser.parse_args()
    main(rows=args.rows)
