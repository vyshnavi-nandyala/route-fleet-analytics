"""Data quality tests for generated data and mart-layer business rules."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.generate_data import (
    generate_gps_events,
    generate_maintenance_logs,
    generate_routes,
    generate_vehicles,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def routes():
    return generate_routes(50)


@pytest.fixture(scope="module")
def vehicles():
    return generate_vehicles(200)


@pytest.fixture(scope="module")
def gps_df(vehicles, routes):
    return generate_gps_events(vehicles, routes, n=5000)


@pytest.fixture(scope="module")
def maintenance_df(vehicles):
    return generate_maintenance_logs(vehicles, n=500)


# ── No nulls in key columns ───────────────────────────────────────────────────

class TestNoNullsInKeyColumns:
    def test_routes_no_nulls(self, routes):
        key_cols = ["route_id", "zone", "district", "total_stops"]
        for col in key_cols:
            assert routes[col].notna().all(), f"Nulls found in routes.{col}"

    def test_vehicles_no_nulls(self, vehicles):
        key_cols = ["vehicle_id", "make", "model", "year", "vehicle_class", "status"]
        for col in key_cols:
            assert vehicles[col].notna().all(), f"Nulls found in vehicles.{col}"

    def test_gps_events_no_nulls(self, gps_df):
        key_cols = ["event_id", "vehicle_id", "route_id", "lat", "lon", "speed_mph", "event_date"]
        for col in key_cols:
            assert gps_df[col].notna().all(), f"Nulls found in gps_events.{col}"

    def test_maintenance_no_nulls(self, maintenance_df):
        key_cols = ["log_id", "vehicle_id", "service_type", "service_date", "cost_usd"]
        for col in key_cols:
            assert maintenance_df[col].notna().all(), f"Nulls found in maintenance.{col}"


# ── Efficiency score bounds ───────────────────────────────────────────────────

class TestEfficiencyScoreBounds:
    @pytest.fixture
    def efficiency_df(self, gps_df, routes):
        """Simulate mart_route_efficiency aggregation logic in Python."""
        merged = gps_df.merge(
            routes[["route_id", "zone", "district"]],
            on="route_id",
            how="left",
        )
        merged["idle_flag"] = (merged["speed_mph"] < 5).astype(int)
        daily = (
            merged.groupby(["route_id", "event_date"])
            .agg(
                avg_speed=("speed_mph", "mean"),
                avg_idle_pct=("idle_flag", lambda x: x.mean() * 100),
                total_miles=("speed_mph", lambda x: x.sum() * 0.01),
                vehicles_on_route=("vehicle_id", "nunique"),
            )
            .reset_index()
        )
        daily["efficiency_score"] = (
            100
            - daily["avg_idle_pct"] * 0.5
            - np.maximum(0, 35 - daily["avg_speed"]) * 0.3
        ).clip(lower=0, upper=100)
        return daily

    def test_efficiency_score_min_zero(self, efficiency_df):
        assert (efficiency_df["efficiency_score"] >= 0).all(), \
            "Efficiency score below 0 found"

    def test_efficiency_score_max_100(self, efficiency_df):
        assert (efficiency_df["efficiency_score"] <= 100).all(), \
            "Efficiency score above 100 found"

    def test_efficiency_score_not_null(self, efficiency_df):
        assert efficiency_df["efficiency_score"].notna().all()

    def test_high_idle_lowers_score(self):
        """High idle percentage should yield a lower efficiency score."""
        # 100% idle, avg speed = 0
        score_high_idle = 100 - (100 * 0.5) - (max(0, 35 - 0) * 0.3)
        # 0% idle, avg speed = 40 mph
        score_low_idle = 100 - (0 * 0.5) - (max(0, 35 - 40) * 0.3)
        assert score_high_idle < score_low_idle

    def test_efficiency_formula_known_values(self):
        avg_idle_pct = 20.0
        avg_speed = 30.0
        # 100 - (20 * 0.5) - (max(0, 35-30) * 0.3) = 100 - 10 - 1.5 = 88.5
        expected = 100 - (avg_idle_pct * 0.5) - (max(0, 35 - avg_speed) * 0.3)
        assert abs(expected - 88.5) < 0.001


# ── Maintenance urgency categories ───────────────────────────────────────────

class TestMaintenanceUrgency:
    ALLOWED_VALUES = {"low", "medium", "high"}

    def _apply_urgency(self, days: int) -> str:
        if days > 90:
            return "high"
        elif days > 60:
            return "medium"
        return "low"

    def test_urgency_only_three_values(self, maintenance_df, vehicles):
        last_service = (
            maintenance_df.groupby("vehicle_id")["service_date"]
            .max()
            .reset_index()
            .rename(columns={"service_date": "last_service_date"})
        )
        fleet = vehicles.merge(last_service, on="vehicle_id", how="left")
        fleet["last_service_date"] = pd.to_datetime(
            fleet["last_service_date"], errors="coerce"
        )
        today = pd.Timestamp.today().normalize()
        fleet["days_since_service"] = (today - fleet["last_service_date"]).dt.days.fillna(999)
        fleet["maintenance_urgency"] = fleet["days_since_service"].apply(self._apply_urgency)

        actual_values = set(fleet["maintenance_urgency"].unique())
        assert actual_values.issubset(self.ALLOWED_VALUES), \
            f"Unexpected urgency values: {actual_values - self.ALLOWED_VALUES}"

    def test_high_urgency_over_90_days(self):
        assert self._apply_urgency(91) == "high"
        assert self._apply_urgency(100) == "high"
        assert self._apply_urgency(365) == "high"

    def test_medium_urgency_61_to_90_days(self):
        assert self._apply_urgency(61) == "medium"
        assert self._apply_urgency(75) == "medium"
        assert self._apply_urgency(90) == "medium"

    def test_low_urgency_under_60_days(self):
        assert self._apply_urgency(0) == "low"
        assert self._apply_urgency(30) == "low"
        assert self._apply_urgency(60) == "low"

    def test_urgency_boundary_90(self):
        assert self._apply_urgency(90) == "medium"
        assert self._apply_urgency(91) == "high"

    def test_urgency_boundary_60(self):
        assert self._apply_urgency(60) == "low"
        assert self._apply_urgency(61) == "medium"


# ── GPS bounding box ──────────────────────────────────────────────────────────

class TestGpsBoundingBox:
    def test_lat_within_houston(self, gps_df):
        assert gps_df["lat"].between(29.5, 30.1).all(), \
            "GPS lat values outside Houston bounding box"

    def test_lon_within_houston(self, gps_df):
        assert gps_df["lon"].between(-95.8, -95.1).all(), \
            "GPS lon values outside Houston bounding box"

    def test_speed_non_negative(self, gps_df):
        assert (gps_df["speed_mph"] >= 0).all()

    def test_speed_realistic_max(self, gps_df):
        assert (gps_df["speed_mph"] <= 120).all(), "Speed values unrealistically high"


# ── Row counts ────────────────────────────────────────────────────────────────

class TestRowCounts:
    def test_routes_count(self, routes):
        assert len(routes) == 50

    def test_vehicles_count(self, vehicles):
        assert len(vehicles) == 200

    def test_gps_events_count(self, gps_df):
        assert len(gps_df) == 5000

    def test_maintenance_count(self, maintenance_df):
        assert len(maintenance_df) == 500

    def test_no_duplicate_route_ids(self, routes):
        assert routes["route_id"].duplicated().sum() == 0

    def test_no_duplicate_vehicle_ids(self, vehicles):
        assert vehicles["vehicle_id"].duplicated().sum() == 0

    def test_no_duplicate_event_ids(self, gps_df):
        assert gps_df["event_id"].duplicated().sum() == 0
