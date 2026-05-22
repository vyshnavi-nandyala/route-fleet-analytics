.PHONY: generate-data upload-s3 load-snowflake dbt-build dbt-test streamlit test all help

PYTHON     := python
DBT        := dbt
DBT_DIR    := dbt
STREAMLIT  := streamlit

help:
	@echo ""
	@echo "  Route Fleet Analytics — available targets"
	@echo "  -----------------------------------------"
	@echo "  generate-data    Generate synthetic CSVs into data/raw/"
	@echo "  upload-s3        Upload CSVs to S3 (requires FLEET_S3_BUCKET env var)"
	@echo "  load-snowflake   COPY INTO Snowflake raw tables from S3 stage"
	@echo "  dbt-build        Run dbt build (compile + run + test all models)"
	@echo "  dbt-test         Run dbt tests only"
	@echo "  streamlit        Launch Streamlit dashboard on localhost:8501"
	@echo "  test             Run pytest suite"
	@echo "  all              Run full pipeline: generate → upload → load → dbt → test"
	@echo ""

generate-data:
	$(PYTHON) scripts/generate_data.py --rows 50000

upload-s3:
	$(PYTHON) ingestion/s3_loader.py

load-snowflake:
	$(PYTHON) ingestion/snowflake_loader.py

dbt-build:
	$(DBT) build --project-dir $(DBT_DIR) --profiles-dir $(DBT_DIR)

dbt-test:
	$(DBT) test --project-dir $(DBT_DIR) --profiles-dir $(DBT_DIR)

streamlit:
	$(STREAMLIT) run streamlit/app.py --server.port 8501

test:
	pytest tests/ -v --tb=short

all: generate-data upload-s3 load-snowflake dbt-build test
	@echo ""
	@echo "Full pipeline complete."
