"""COPY INTO raw Snowflake tables from S3 stage."""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import snowflake.connector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

STAGE = "RAW.FLEET_S3_STAGE"

# Map table → (schema.table, S3 prefix under the stage root)
TABLE_CONFIG = {
    "routes": {
        "target": "RAW.ROUTES",
        "stage_prefix": "raw/routes/",
        "columns": "(ROUTE_ID, ROUTE_NAME, ZONE, DISTRICT, TOTAL_STOPS, CREATED_AT)",
    },
    "vehicles": {
        "target": "RAW.VEHICLES",
        "stage_prefix": "raw/vehicles/",
        "columns": "(VEHICLE_ID, MAKE, MODEL, YEAR, VEHICLE_CLASS, STATUS, VIN, LICENSE_PLATE)",
    },
    "stops": {
        "target": "RAW.STOPS",
        "stage_prefix": "raw/stops/",
        "columns": "(STOP_ID, ROUTE_ID, STOP_NAME, STOP_SEQUENCE, LAT, LON, STOP_TYPE)",
    },
    "gps_events": {
        "target": "RAW.GPS_EVENTS",
        "stage_prefix": "raw/gps_events/",
        "columns": "(EVENT_ID, VEHICLE_ID, ROUTE_ID, LAT, LON, SPEED_MPH, HEADING_DEG, EVENT_TS, EVENT_DATE)",
    },
    "maintenance_logs": {
        "target": "RAW.MAINTENANCE_LOGS",
        "stage_prefix": "raw/maintenance_logs/",
        "columns": "(LOG_ID, VEHICLE_ID, SERVICE_TYPE, SERVICE_DATE, COST_USD, MILEAGE_AT_SERVICE, TECHNICIAN, NOTES)",
    },
}


@dataclass
class LoadResult:
    table: str
    rows_loaded: int
    rows_errored: int
    status: str


def get_connection() -> snowflake.connector.SnowflakeConnection:
    required = [
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_WAREHOUSE",
    ]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        raise EnvironmentError(f"Missing Snowflake env vars: {missing}")

    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        schema="RAW",
    )


def copy_into(
    cursor,
    table: str,
    config: dict,
    partition_date: Optional[str] = None,
) -> LoadResult:
    target = config["target"]
    columns = config["columns"]
    prefix = config["stage_prefix"]

    if partition_date:
        stage_path = f"@{STAGE}/{prefix}date={partition_date}/"
    else:
        stage_path = f"@{STAGE}/{prefix}"

    sql = f"""
        COPY INTO {target} {columns}
        FROM {stage_path}
        FILE_FORMAT = (FORMAT_NAME = 'RAW.CSV_FORMAT')
        ON_ERROR = 'CONTINUE'
        PURGE = FALSE;
    """
    log.info("Running COPY INTO %s from %s", target, stage_path)
    cursor.execute(sql)

    results = cursor.fetchall()
    rows_loaded = sum(r[3] for r in results if r[3] is not None)
    rows_errored = sum(r[4] for r in results if r[4] is not None)

    count_sql = f"SELECT COUNT(*) FROM {target}"
    cursor.execute(count_sql)
    total_rows = cursor.fetchone()[0]

    log.info(
        "  %s → loaded=%d, errors=%d, total_in_table=%d",
        target, rows_loaded, rows_errored, total_rows,
    )
    return LoadResult(
        table=table,
        rows_loaded=rows_loaded,
        rows_errored=rows_errored,
        status="success" if rows_errored == 0 else "partial",
    )


def load_all(tables: Optional[list] = None, partition_date: Optional[str] = None) -> list[LoadResult]:
    tables = tables or list(TABLE_CONFIG.keys())
    results = []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"USE DATABASE {os.environ['SNOWFLAKE_DATABASE']}")
            cur.execute("USE WAREHOUSE " + os.environ["SNOWFLAKE_WAREHOUSE"])

            for table in tables:
                if table not in TABLE_CONFIG:
                    log.warning("Unknown table '%s', skipping.", table)
                    continue
                result = copy_into(cur, table, TABLE_CONFIG[table], partition_date)
                results.append(result)

    return results


if __name__ == "__main__":
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser(description="Load CSV data from S3 into Snowflake raw tables")
    parser.add_argument(
        "--tables",
        nargs="+",
        choices=list(TABLE_CONFIG.keys()),
        default=None,
        help="Tables to load (default: all)",
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        dest="partition_date",
        help="S3 partition date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    results = load_all(tables=args.tables, partition_date=args.partition_date)
    print("\nLoad summary:")
    for r in results:
        print(f"  {r.table}: {r.rows_loaded} loaded, {r.rows_errored} errors [{r.status}]")
