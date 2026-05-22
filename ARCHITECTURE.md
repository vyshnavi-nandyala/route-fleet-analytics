# Architecture

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Local / CI                                                             │
│  scripts/generate_data.py  →  data/raw/*.csv                           │
└─────────────────────────┬───────────────────────────────────────────────┘
                          │ boto3 upload
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Amazon S3                                                              │
│  s3://<FLEET_S3_BUCKET>/raw/{table}/date={YYYY-MM-DD}/{table}.csv      │
└─────────────────────────┬───────────────────────────────────────────────┘
                          │ COPY INTO (Snowflake stage)
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Snowflake — RAW schema                                                 │
│  RAW.ROUTES  RAW.VEHICLES  RAW.STOPS  RAW.GPS_EVENTS  RAW.MAINT_LOGS  │
└─────────────────────────┬───────────────────────────────────────────────┘
                          │ dbt build
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Snowflake — SILVER schema (dbt staging + intermediate)                 │
│  stg_routes   stg_vehicles   stg_gps_events   stg_maintenance          │
│  int_route_segments          int_vehicle_daily_stats                   │
└─────────────────────────┬───────────────────────────────────────────────┘
                          │ dbt build (marts)
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Snowflake — GOLD schema (dbt marts)                                    │
│  mart_route_efficiency   mart_fleet_health   mart_driver_performance    │
└────────────┬──────────────────────────────────┬────────────────────────┘
             │ Snowflake Cortex Analyst          │ Snowflake connector
             ▼                                  ▼
     ┌───────────────┐                  ┌──────────────────┐
     │ NLP question  │                  │ Streamlit app    │
     │ → SQL → df    │                  │ KPIs + charts    │
     └───────────────┘                  └──────────────────┘
```

## Orchestration

Apache Airflow runs a `@daily` DAG (`airflow/dags/fleet_pipeline.py`):

```
ingest_to_s3 → load_to_snowflake → run_dbt_build → run_quality_checks
                                                          │ (on_failure)
                                                          ▼
                                                   notify_on_failure
```

---

## Data Dictionary

### GOLD.MART_ROUTE_EFFICIENCY

| Column | Type | Description |
|---|---|---|
| `route_id` | VARCHAR | Unique route identifier (e.g. RT-0001) |
| `route_name` | VARCHAR | Human-readable route name |
| `zone` | VARCHAR | Geographic zone (North / South / East / West / Central) |
| `district` | VARCHAR | Administrative district (District-1 to 5) |
| `segment_date` | DATE | Calendar date of the aggregation window |
| `vehicles_on_route` | INTEGER | Count of distinct vehicles active on this route |
| `avg_speed` | FLOAT | Mean vehicle speed in mph across all GPS events |
| `total_miles` | FLOAT | Sum of haversine-approximated segment distances |
| `avg_idle_pct` | FLOAT | % of events where speed < 5 mph |
| `total_events` | INTEGER | Raw GPS ping count |
| `efficiency_score` | FLOAT | `100 - (avg_idle_pct×0.5) - (GREATEST(0, 35-avg_speed)×0.3)` clipped to [0, 100] |

### GOLD.MART_FLEET_HEALTH

| Column | Type | Description |
|---|---|---|
| `vehicle_id` | VARCHAR | Unique vehicle identifier |
| `make` | VARCHAR | Manufacturer (Ford, Chevrolet, …) |
| `model` | VARCHAR | Model name |
| `year` | INTEGER | Model year |
| `vehicle_class` | VARCHAR | `light` / `medium` / `heavy` |
| `status` | VARCHAR | `active` / `inactive` / `maintenance` |
| `last_service_date` | DATE | Most recent maintenance event date |
| `days_since_service` | INTEGER | Calendar days since `last_service_date` |
| `total_cost_ytd` | FLOAT | Sum of maintenance costs in the current calendar year (USD) |
| `total_service_events` | INTEGER | Lifetime maintenance event count |
| `maintenance_urgency` | VARCHAR | `high` (>90 days) / `medium` (>60 days) / `low` |

### GOLD.MART_DRIVER_PERFORMANCE

| Column | Type | Description |
|---|---|---|
| `vehicle_id` | VARCHAR | Unique vehicle identifier |
| `make` | VARCHAR | Manufacturer |
| `model` | VARCHAR | Model name |
| `vehicle_class` | VARCHAR | `light` / `medium` / `heavy` |
| `month` | DATE | First day of the calendar month |
| `avg_speed` | FLOAT | Mean driving speed (mph) for the month |
| `idle_pct` | FLOAT | % of active time spent idling |
| `total_miles` | FLOAT | Total miles driven during the month |
| `total_trips` | INTEGER | Number of distinct daily route trips |
| `active_days` | INTEGER | Number of days the vehicle had GPS events |
| `avg_active_mins_per_day` | FLOAT | Average minutes active per operating day |
| `safety_score` | FLOAT | `70 + (MIN(avg_speed,45)/45×20) - (idle_pct×0.3)` clipped to [0, 100] |

---

## Cortex Analyst Semantic Model

The file `cortex/semantic_model.yaml` defines three logical tables over the
GOLD schema:

| Semantic table | Base table | Key measures | Key dimensions |
|---|---|---|---|
| `mart_route_efficiency` | GOLD.MART_ROUTE_EFFICIENCY | avg_speed, total_miles, avg_idle_pct, efficiency_score | route_id, segment_date, zone, district |
| `mart_fleet_health` | GOLD.MART_FLEET_HEALTH | days_since_service, total_cost_ytd | vehicle_id, vehicle_class, maintenance_urgency |
| `mart_driver_performance` | GOLD.MART_DRIVER_PERFORMANCE | avg_speed, idle_pct, total_miles, safety_score | vehicle_id, month, vehicle_class |

### Example NLP Queries and Expected SQL

**"Which routes had the highest idle time last week?"**
```sql
SELECT route_id, route_name, zone, AVG(avg_idle_pct) AS avg_idle_pct
FROM FLEET_ANALYTICS.GOLD.MART_ROUTE_EFFICIENCY
WHERE segment_date >= DATEADD('day', -7, CURRENT_DATE())
GROUP BY route_id, route_name, zone
ORDER BY avg_idle_pct DESC
LIMIT 10;
```

**"Show me vehicles overdue for maintenance"**
```sql
SELECT vehicle_id, make, model, vehicle_class, last_service_date,
       days_since_service, maintenance_urgency
FROM FLEET_ANALYTICS.GOLD.MART_FLEET_HEALTH
WHERE maintenance_urgency IN ('medium', 'high')
ORDER BY days_since_service DESC;
```

**"What is the average speed by route zone?"**
```sql
SELECT zone, AVG(avg_speed) AS avg_speed_mph
FROM FLEET_ANALYTICS.GOLD.MART_ROUTE_EFFICIENCY
GROUP BY zone
ORDER BY avg_speed_mph DESC;
```

**"What is the total maintenance cost per vehicle class this year?"**
```sql
SELECT vehicle_class, SUM(total_cost_ytd) AS total_cost_usd
FROM FLEET_ANALYTICS.GOLD.MART_FLEET_HEALTH
GROUP BY vehicle_class
ORDER BY total_cost_usd DESC;
```

---

## Scoring Formulas

### Efficiency Score
```
efficiency_score = CLIP(
    100 - (avg_idle_pct × 0.5) - (GREATEST(0, 35 - avg_speed) × 0.3),
    min=0, max=100
)
```
- Penalises idling (weight 0.5 per idle %)
- Penalises speeds below 35 mph (weight 0.3 per mph below threshold)

### Safety Score
```
safety_score = CLIP(
    70 + (MIN(avg_speed, 45) / 45 × 20) - (idle_pct × 0.3),
    min=0, max=100
)
```
- Rewards higher speed up to 45 mph (max +20 pts)
- Penalises idling (0.3 per idle %)
- Base score of 70 for average driving behaviour
