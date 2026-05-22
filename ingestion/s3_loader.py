"""Upload generated CSVs to S3."""

import argparse
import os
from datetime import date
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
TABLES = ["routes", "vehicles", "stops", "gps_events", "maintenance_logs"]


def build_s3_key(table: str, partition_date: str, filename: str) -> str:
    return f"raw/{table}/date={partition_date}/{filename}"


def upload_file(
    s3_client,
    local_path: Path,
    bucket: str,
    s3_key: str,
    dry_run: bool = False,
) -> None:
    if dry_run:
        print(f"  [DRY-RUN] Would upload {local_path} → s3://{bucket}/{s3_key}")
        return

    try:
        s3_client.upload_file(str(local_path), bucket, s3_key)
        size_mb = local_path.stat().st_size / (1024 * 1024)
        print(f"  Uploaded {local_path.name} ({size_mb:.2f} MB) → s3://{bucket}/{s3_key}")
    except ClientError as exc:
        raise RuntimeError(f"Failed to upload {local_path} to s3://{bucket}/{s3_key}: {exc}") from exc


def upload_all(bucket: str, partition_date: str, dry_run: bool = False) -> None:
    if not dry_run:
        s3_client = boto3.client("s3")
    else:
        s3_client = None

    missing = [t for t in TABLES if not (RAW_DIR / f"{t}.csv").exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing CSVs in {RAW_DIR}: {missing}. Run scripts/generate_data.py first."
        )

    print(f"Uploading to s3://{bucket} (partition={partition_date}) [dry_run={dry_run}]")
    for table in TABLES:
        local_path = RAW_DIR / f"{table}.csv"
        s3_key = build_s3_key(table, partition_date, f"{table}.csv")
        upload_file(s3_client, local_path, bucket, s3_key, dry_run=dry_run)

    print("Upload complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload CSVs to S3")
    parser.add_argument(
        "--bucket",
        default=os.getenv("FLEET_S3_BUCKET", "route-fleet-analytics-raw"),
        help="S3 bucket name (or set FLEET_S3_BUCKET env var)",
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Partition date (YYYY-MM-DD)",
        dest="partition_date",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be uploaded without actually uploading",
    )
    args = parser.parse_args()
    upload_all(bucket=args.bucket, partition_date=args.partition_date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
