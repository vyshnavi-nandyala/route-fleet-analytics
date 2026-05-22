"""Unit tests for ingestion layer: schema validation, S3 path generation, load mocking."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.s3_loader import TABLES, build_s3_key
from scripts.generate_data import (
    generate_gps_events,
    generate_maintenance_logs,
    generate_routes,
    generate_vehicles,
)


# ── Schema validation ─────────────────────────────────────────────────────────

class TestRouteSchema:
    def test_required_columns(self):
        df = generate_routes(5)
        expected = {"route_id", "route_name", "zone", "district", "total_stops", "created_at"}
        assert expected.issubset(set(df.columns))

    def test_route_id_unique(self):
        df = generate_routes(10)
        assert df["route_id"].nunique() == 10

    def test_total_stops_positive(self):
        df = generate_routes(20)
        assert (df["total_stops"] > 0).all()

    def test_zone_not_null(self):
        df = generate_routes(10)
        assert df["zone"].notna().all()


class TestVehicleSchema:
    def test_required_columns(self):
        df = generate_vehicles(5)
        expected = {"vehicle_id", "make", "model", "year", "vehicle_class", "status"}
        assert expected.issubset(set(df.columns))

    def test_vehicle_class_values(self):
        df = generate_vehicles(50)
        assert set(df["vehicle_class"].unique()).issubset({"light", "medium", "heavy"})

    def test_status_values(self):
        df = generate_vehicles(50)
        assert set(df["status"].unique()).issubset({"active", "inactive", "maintenance"})

    def test_year_range(self):
        df = generate_vehicles(50)
        assert df["year"].between(2010, 2025).all()


class TestGpsEventSchema:
    @pytest.fixture
    def gps_df(self):
        routes = generate_routes(5)
        vehicles = generate_vehicles(10)
        return generate_gps_events(vehicles, routes, n=100)

    def test_required_columns(self, gps_df):
        expected = {"event_id", "vehicle_id", "route_id", "lat", "lon", "speed_mph", "event_ts", "event_date"}
        assert expected.issubset(set(gps_df.columns))

    def test_lat_bounds(self, gps_df):
        assert gps_df["lat"].between(29.5, 30.1).all()

    def test_lon_bounds(self, gps_df):
        assert gps_df["lon"].between(-95.8, -95.1).all()

    def test_speed_non_negative(self, gps_df):
        assert (gps_df["speed_mph"] >= 0).all()

    def test_event_id_unique(self, gps_df):
        assert gps_df["event_id"].nunique() == len(gps_df)


class TestMaintenanceSchema:
    @pytest.fixture
    def maint_df(self):
        vehicles = generate_vehicles(10)
        return generate_maintenance_logs(vehicles, n=50)

    def test_required_columns(self, maint_df):
        expected = {"log_id", "vehicle_id", "service_type", "service_date", "cost_usd", "mileage_at_service"}
        assert expected.issubset(set(maint_df.columns))

    def test_cost_positive(self, maint_df):
        assert (maint_df["cost_usd"] > 0).all()

    def test_mileage_positive(self, maint_df):
        assert (maint_df["mileage_at_service"] > 0).all()

    def test_log_id_unique(self, maint_df):
        assert maint_df["log_id"].nunique() == len(maint_df)


# ── S3 path generation ────────────────────────────────────────────────────────

class TestS3PathGeneration:
    def test_basic_path(self):
        key = build_s3_key("routes", "2024-01-15", "routes.csv")
        assert key == "raw/routes/date=2024-01-15/routes.csv"

    def test_all_tables_generate_valid_keys(self):
        for table in TABLES:
            key = build_s3_key(table, "2024-06-01", f"{table}.csv")
            assert key.startswith(f"raw/{table}/date=")
            assert key.endswith(".csv")

    def test_path_contains_partition(self):
        key = build_s3_key("gps_events", "2024-03-22", "gps_events.csv")
        assert "date=2024-03-22" in key

    def test_filename_in_path(self):
        key = build_s3_key("vehicles", "2024-01-01", "vehicles_v2.csv")
        assert "vehicles_v2.csv" in key


# ── S3 upload (mocked boto3) ──────────────────────────────────────────────────

class TestS3Upload:
    @patch("ingestion.s3_loader.boto3")
    def test_dry_run_does_not_call_boto3(self, mock_boto3, tmp_path, monkeypatch):
        monkeypatch.setenv("FLEET_S3_BUCKET", "test-bucket")

        # Create dummy CSVs
        raw_dir = tmp_path / "data" / "raw"
        raw_dir.mkdir(parents=True)
        for table in TABLES:
            (raw_dir / f"{table}.csv").write_text("col1,col2\nval1,val2\n")

        with patch("ingestion.s3_loader.RAW_DIR", raw_dir):
            from ingestion.s3_loader import upload_all
            upload_all(bucket="test-bucket", partition_date="2024-01-01", dry_run=True)

        mock_boto3.client.assert_not_called()

    @patch("ingestion.s3_loader.boto3")
    def test_upload_creates_s3_client(self, mock_boto3, tmp_path, monkeypatch):
        monkeypatch.setenv("FLEET_S3_BUCKET", "test-bucket")
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        raw_dir = tmp_path / "data" / "raw"
        raw_dir.mkdir(parents=True)
        for table in TABLES:
            (raw_dir / f"{table}.csv").write_text("col1,col2\nval1,val2\n")

        with patch("ingestion.s3_loader.RAW_DIR", raw_dir):
            from ingestion.s3_loader import upload_all
            upload_all(bucket="test-bucket", partition_date="2024-01-01", dry_run=False)

        mock_boto3.client.assert_called_once_with("s3")
        assert mock_s3.upload_file.call_count == len(TABLES)

    def test_missing_csv_raises(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with patch("ingestion.s3_loader.RAW_DIR", empty_dir):
            from ingestion.s3_loader import upload_all
            with pytest.raises(FileNotFoundError):
                upload_all(bucket="test-bucket", partition_date="2024-01-01", dry_run=True)


# ── Row count after load (mocked Snowflake) ───────────────────────────────────

def _snowflake_available() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("snowflake") is not None
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(not _snowflake_available(), reason="snowflake-connector-python not installed")
class TestSnowflakeLoader:
    @patch("snowflake.connector.connect")
    def test_copy_into_fetches_row_count(self, mock_connect, monkeypatch):
        monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test_account")
        monkeypatch.setenv("SNOWFLAKE_USER", "test_user")
        monkeypatch.setenv("SNOWFLAKE_PASSWORD", "test_pass")
        monkeypatch.setenv("SNOWFLAKE_DATABASE", "FLEET_ANALYTICS")
        monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "FLEET_WH")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # COPY INTO returns rows_loaded, rows_errored in position 3 and 4
        mock_cursor.fetchall.return_value = [("file.csv", "LOADED", "2024-01-01", 100, 0)]
        mock_cursor.fetchone.return_value = (100,)

        from ingestion.snowflake_loader import TABLE_CONFIG, copy_into

        result = copy_into(mock_cursor, "routes", TABLE_CONFIG["routes"])
        assert result.rows_loaded == 100
        assert result.rows_errored == 0
        assert result.status == "success"
