"""Daily Airflow DAG: ingest → stage → dbt → quality checks → notify."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import requests
from airflow.decorators import dag, task
from airflow.utils.dates import days_ago

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
DBT_DIR = PROJECT_ROOT / "dbt"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


default_args = {
    "owner": "fleet-data-team",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}


@dag(
    dag_id="fleet_pipeline",
    description="Daily fleet data pipeline: ingest → Snowflake → dbt → quality checks",
    schedule="@daily",
    start_date=days_ago(1),
    catchup=False,
    default_args=default_args,
    tags=["fleet", "snowflake", "dbt"],
)
def fleet_pipeline():

    @task()
    def ingest_to_s3(**context) -> dict:
        """Generate synthetic data and upload to S3."""
        exec_date = context["ds"]
        bucket = os.environ["FLEET_S3_BUCKET"]

        log.info("Generating data for partition %s", exec_date)
        gen_result = subprocess.run(
            ["python", str(SCRIPTS_DIR / "generate_data.py"), "--rows", "50000"],
            capture_output=True,
            text=True,
            check=True,
        )
        log.info(gen_result.stdout)

        log.info("Uploading to s3://%s (partition=%s)", bucket, exec_date)
        upload_result = subprocess.run(
            [
                "python",
                str(PROJECT_ROOT / "ingestion" / "s3_loader.py"),
                "--bucket", bucket,
                "--date", exec_date,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        log.info(upload_result.stdout)
        return {"bucket": bucket, "partition_date": exec_date, "status": "success"}

    @task()
    def load_to_snowflake(ingest_result: dict) -> dict:
        """COPY INTO Snowflake raw tables from S3 stage."""
        partition_date = ingest_result["partition_date"]

        load_result = subprocess.run(
            [
                "python",
                str(PROJECT_ROOT / "ingestion" / "snowflake_loader.py"),
                "--date", partition_date,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        log.info(load_result.stdout)
        return {"partition_date": partition_date, "status": "success"}

    @task()
    def run_dbt_build(load_result: dict) -> dict:
        """Run dbt build (compile + run + test all models)."""
        log.info("Running dbt build in %s", DBT_DIR)
        result = subprocess.run(
            ["dbt", "build", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        log.info(result.stdout)
        if result.returncode != 0:
            log.error(result.stderr)
            raise RuntimeError(f"dbt build failed:\n{result.stderr}")
        return {"dbt_status": "success"}

    @task()
    def run_quality_checks(dbt_result: dict) -> dict:
        """Run pytest data quality checks."""
        result = subprocess.run(
            ["pytest", str(PROJECT_ROOT / "tests" / "test_data_quality.py"), "-v"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        log.info(result.stdout)
        if result.returncode != 0:
            log.error(result.stderr)
            raise RuntimeError(f"Quality checks failed:\n{result.stderr}")
        return {"quality_status": "passed"}

    @task(trigger_rule="one_failed")
    def notify_on_failure(**context) -> None:
        """Send Slack alert on pipeline failure."""
        webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        if not webhook_url:
            log.warning("SLACK_WEBHOOK_URL not set; skipping notification.")
            return

        dag_run = context.get("dag_run")
        exec_date = context.get("ds", "unknown")
        failed_task = context.get("task_instance", {})

        message = {
            "text": (
                f":red_circle: *Fleet Pipeline Failed*\n"
                f"• DAG: `{dag_run.dag_id if dag_run else 'fleet_pipeline'}`\n"
                f"• Execution date: `{exec_date}`\n"
                f"• Failed task: `{failed_task}`\n"
                f"• Check Airflow for details."
            )
        }
        try:
            resp = requests.post(webhook_url, json=message, timeout=10)
            resp.raise_for_status()
            log.info("Slack notification sent.")
        except requests.RequestException as exc:
            log.error("Failed to send Slack notification: %s", exc)

    # ── DAG wiring ─────────────────────────────────────────────────────────────
    ingest_result = ingest_to_s3()
    load_result = load_to_snowflake(ingest_result)
    dbt_result = run_dbt_build(load_result)
    quality_result = run_quality_checks(dbt_result)
    notify_on_failure()


fleet_pipeline_dag = fleet_pipeline()
