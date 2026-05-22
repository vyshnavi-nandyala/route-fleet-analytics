# route-fleet-analytics

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![Snowflake](https://img.shields.io/badge/Snowflake-Data_Warehouse-29b5e8?logo=snowflake)
![dbt](https://img.shields.io/badge/dbt-Snowflake-FF694B?logo=dbt)
![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?logo=streamlit)
![Airflow](https://img.shields.io/badge/Apache_Airflow-Orchestration-017CEE?logo=apacheairflow)

End-to-end data engineering project for a Houston-area fleet operations platform.
Synthetic GPS telemetry and maintenance data flows from CSV generation through S3,
into Snowflake raw tables, through a three-layer dbt transformation pipeline,
and surfaces in a Streamlit dashboard with Snowflake Cortex Analyst NLP queries.

---

## Architecture

```
CSV Generator → S3 → Snowflake RAW → dbt (SILVER) → dbt Marts (GOLD)
                                                            │
                                          ┌─────────────────┴───────────────┐
                                          │                                 │
                                   Streamlit Dashboard          Cortex Analyst NLP
                                   (KPIs + Plotly charts)       (natural-language SQL)
```

Full data flow diagram: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Stack

| Layer | Technology |
|---|---|
| Data generation | Python, Faker, Pandas, NumPy |
| Cloud storage | Amazon S3 (boto3) |
| Data warehouse | Snowflake |
| Transformation | dbt-snowflake (staging → intermediate → marts) |
| Orchestration | Apache Airflow (TaskFlow API, `@daily`) |
| NLP queries | Snowflake Cortex Analyst |
| Dashboard | Streamlit + Plotly |
| Testing | pytest, dbt tests |
| CI/CD | GitHub Actions |

---

## Quickstart

### 1. Clone and install

```bash
git clone https://github.com/your-org/route-fleet-analytics.git
cd route-fleet-analytics
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your Snowflake account, S3 bucket, and AWS credentials
source .env   # or use python-dotenv
```

### 3. Initialise Snowflake

```bash
# Run once to create database, schemas, tables, and S3 stage
snowsql -f ingestion/snowflake_setup.sql
```

### 4. Run the full pipeline

```bash
make all
# Equivalent to:
#   make generate-data    → writes data/raw/*.csv
#   make upload-s3        → uploads to S3 with date partition
#   make load-snowflake   → COPY INTO Snowflake RAW tables
#   make dbt-build        → compile + run + test all dbt models
#   make test             → pytest suite
```

### 5. Launch the dashboard

```bash
make streamlit
# Opens http://localhost:8501
```

---

## Data Model

Three dbt layers on top of Snowflake:

```
RAW            SILVER (staging views)         SILVER (intermediate tables)
───────        ──────────────────────         ────────────────────────────
raw.routes  →  stg_routes                  ┐
raw.vehicles → stg_vehicles                ├→ int_route_segments
raw.gps_events → stg_gps_events            │   int_vehicle_daily_stats
raw.maintenance_logs → stg_maintenance     ┘

GOLD (marts / final tables)
───────────────────────────────────────────────────────
mart_route_efficiency   mart_fleet_health   mart_driver_performance
```

Full column-level data dictionary: [ARCHITECTURE.md#data-dictionary](ARCHITECTURE.md#data-dictionary)

---

## Cortex Analyst NLP Queries

The `cortex/semantic_model.yaml` registers three GOLD tables with Snowflake
Cortex Analyst so users can query them in plain English.

Example questions:

| Question | What it returns |
|---|---|
| "Which routes had the highest idle time last week?" | Top 10 routes by avg idle % |
| "Show me vehicles overdue for maintenance" | All medium/high urgency vehicles |
| "What is the average speed by route zone?" | Zone-level speed leaderboard |
| "What is the total maintenance cost per vehicle class this year?" | YTD cost by light/medium/heavy |
| "Which routes have the lowest efficiency scores this month?" | Bottom 10 efficiency scores |

The `CortexAnalystClient` class (`cortex/query_client.py`) wraps the REST API,
returns a `CortexResult` dataclass with `sql`, `df`, and `confidence`, and
surfaces results directly in the Streamlit NLP query box.

---

## Dashboard

The Streamlit app (`streamlit/app.py`) provides:

- **Sidebar filters**: date range, route multiselect, vehicle class
- **Row 1 KPIs**: active routes, avg speed, fleet utilisation %, maintenance alerts
- **Row 2**: Speed & idle % time-series by day
- **Row 3**: Fleet health bar chart + urgent vehicles table
- **Row 4**: Cortex Analyst NLP input → live DataFrame + SQL expander

> **Screenshot placeholder**
> ![Dashboard screenshot](docs/dashboard_screenshot.png)

---

## CI/CD

| Trigger | Workflow | Steps |
|---|---|---|
| Pull Request to `main` | `.github/workflows/ci.yml` | pytest → dbt compile → dbt test |
| Merge to `main` | `.github/workflows/cd.yml` | Trigger Airflow `fleet_pipeline` DAG via REST API |

### Required GitHub Secrets

```
SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
SNOWFLAKE_DATABASE, SNOWFLAKE_WAREHOUSE,
FLEET_S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
SLACK_WEBHOOK_URL, AIRFLOW_URL, AIRFLOW_USER, AIRFLOW_PASSWORD
```

---

## Make Targets

```bash
make generate-data    # Generate synthetic data (data/raw/*.csv)
make upload-s3        # Upload to S3
make load-snowflake   # COPY INTO Snowflake
make dbt-build        # dbt build (compile + run + test)
make dbt-test         # dbt test only
make streamlit        # Launch Streamlit dashboard
make test             # Run pytest
make all              # Full pipeline end-to-end
```

---

## Project Structure

```
route-fleet-analytics/
├── data/raw/                  # Generated CSVs (gitignored)
├── scripts/generate_data.py   # Synthetic data generator
├── ingestion/
│   ├── s3_loader.py           # Upload to S3
│   ├── snowflake_setup.sql    # DDL for raw tables
│   └── snowflake_loader.py    # COPY INTO from S3 stage
├── dbt/models/
│   ├── staging/               # stg_* views: rename + cast
│   ├── intermediate/          # int_* tables: joins + derived fields
│   └── marts/                 # mart_* tables: business-facing aggregates
├── cortex/
│   ├── semantic_model.yaml    # Cortex Analyst semantic model
│   └── query_client.py        # CortexAnalystClient REST wrapper
├── airflow/dags/
│   └── fleet_pipeline.py      # @daily DAG: ingest → dbt → quality
├── streamlit/app.py           # Analytics dashboard
├── tests/                     # pytest: ingestion + data quality
├── .github/workflows/         # CI (pytest + dbt) + CD (Airflow trigger)
├── Makefile
├── requirements.txt
├── ARCHITECTURE.md
└── README.md
```
