-- ============================================================
-- Snowflake setup: databases, schemas, raw tables, and S3 stage
-- ============================================================

-- ── Database & schemas ────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS FLEET_ANALYTICS;
USE DATABASE FLEET_ANALYTICS;

CREATE SCHEMA IF NOT EXISTS RAW;
CREATE SCHEMA IF NOT EXISTS SILVER;
CREATE SCHEMA IF NOT EXISTS GOLD;

-- ── File format ───────────────────────────────────────────────
CREATE OR REPLACE FILE FORMAT RAW.CSV_FORMAT
    TYPE = 'CSV'
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    SKIP_HEADER = 1
    NULL_IF = ('', 'NULL', 'null')
    EMPTY_FIELD_AS_NULL = TRUE
    DATE_FORMAT = 'AUTO'
    TIMESTAMP_FORMAT = 'AUTO';

-- ── S3 stage ──────────────────────────────────────────────────
-- Replace $FLEET_S3_BUCKET with your bucket name before running.
CREATE OR REPLACE STAGE RAW.FLEET_S3_STAGE
    URL = 's3://$FLEET_S3_BUCKET/'
    CREDENTIALS = (
        AWS_KEY_ID = '$AWS_ACCESS_KEY_ID'
        AWS_SECRET_KEY = '$AWS_SECRET_ACCESS_KEY'
    )
    FILE_FORMAT = RAW.CSV_FORMAT;

-- ── Raw tables ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS RAW.ROUTES (
    ROUTE_ID        VARCHAR(20)     NOT NULL,
    ROUTE_NAME      VARCHAR(100),
    ZONE            VARCHAR(50),
    DISTRICT        VARCHAR(50),
    TOTAL_STOPS     INTEGER,
    CREATED_AT      TIMESTAMP_NTZ,
    _LOADED_AT      TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (ROUTE_ID)
);

CREATE TABLE IF NOT EXISTS RAW.VEHICLES (
    VEHICLE_ID      VARCHAR(20)     NOT NULL,
    MAKE            VARCHAR(50),
    MODEL           VARCHAR(50),
    YEAR            INTEGER,
    VEHICLE_CLASS   VARCHAR(20),
    STATUS          VARCHAR(20),
    VIN             VARCHAR(20),
    LICENSE_PLATE   VARCHAR(20),
    _LOADED_AT      TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (VEHICLE_ID)
);

CREATE TABLE IF NOT EXISTS RAW.STOPS (
    STOP_ID         VARCHAR(20)     NOT NULL,
    ROUTE_ID        VARCHAR(20),
    STOP_NAME       VARCHAR(200),
    STOP_SEQUENCE   INTEGER,
    LAT             FLOAT,
    LON             FLOAT,
    STOP_TYPE       VARCHAR(20),
    _LOADED_AT      TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (STOP_ID)
);

CREATE TABLE IF NOT EXISTS RAW.GPS_EVENTS (
    EVENT_ID        VARCHAR(20)     NOT NULL,
    VEHICLE_ID      VARCHAR(20),
    ROUTE_ID        VARCHAR(20),
    LAT             FLOAT,
    LON             FLOAT,
    SPEED_MPH       FLOAT,
    HEADING_DEG     INTEGER,
    EVENT_TS        TIMESTAMP_NTZ,
    EVENT_DATE      DATE,
    _LOADED_AT      TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (EVENT_ID)
)
CLUSTER BY (EVENT_DATE);

CREATE TABLE IF NOT EXISTS RAW.MAINTENANCE_LOGS (
    LOG_ID              VARCHAR(20)     NOT NULL,
    VEHICLE_ID          VARCHAR(20),
    SERVICE_TYPE        VARCHAR(100),
    SERVICE_DATE        DATE,
    COST_USD            FLOAT,
    MILEAGE_AT_SERVICE  INTEGER,
    TECHNICIAN          VARCHAR(100),
    NOTES               VARCHAR(500),
    _LOADED_AT          TIMESTAMP_NTZ   DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (LOG_ID)
);

-- ── Warehouses ────────────────────────────────────────────────
CREATE WAREHOUSE IF NOT EXISTS FLEET_WH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE;
