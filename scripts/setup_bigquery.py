"""
Script 1 of 3 — BigQuery Setup
================================
Creates the BigQuery dataset `olist_metadata` and two tables:
  1. data_dictionary_embeddings  — metadata rows + 1536-dim embedding vectors
  2. join_metadata               — join relationship records (no embeddings)

Run once before any other BigQuery scripts.

Usage:
    python scripts/setup_bigquery.py
"""

import os
import sys

# ── ensure project root is on path ────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from google.cloud import bigquery
from google.api_core.exceptions import Conflict
from config.config_loader import get_config
from core.logger import setup_logger

logger = setup_logger("BQ-SETUP")


def get_bq_client() -> bigquery.Client:
    """Initialise BigQuery client using service account credentials."""
    creds_path = get_config("GOOGLE_APPLICATION_CREDENTIALS")
    project_id = get_config("GCP_PROJECT_ID")

    # Resolve relative path from project root
    if not os.path.isabs(creds_path):
        creds_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", creds_path))

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
    client = bigquery.Client(project=project_id)
    logger.info(f"BigQuery client initialised for project: {project_id}")
    return client


def create_dataset(client: bigquery.Client) -> None:
    """Create the BigQuery dataset if it doesn't already exist."""
    project_id = get_config("GCP_PROJECT_ID")
    dataset_id = get_config("BQ_DATASET")
    location = get_config("GCP_LOCATION", "asia-south1")

    full_dataset_id = f"{project_id}.{dataset_id}"
    dataset = bigquery.Dataset(full_dataset_id)
    dataset.location = location
    dataset.description = "Olist e-commerce metadata: data dictionary + join relationships"

    try:
        client.create_dataset(dataset, timeout=30)
        logger.info(f"✅ Dataset created: {full_dataset_id} (location: {location})")
    except Conflict:
        logger.info(f"ℹ️  Dataset already exists: {full_dataset_id} — skipping creation")


def create_data_dictionary_table(client: bigquery.Client) -> None:
    """
    Create `data_dictionary_embeddings` table.

    Schema:
        id                  INTEGER     — row ID from Postgres
        table_name          STRING      — domain table name
        column_name         STRING      — column name within the table
        column_definition   STRING      — human-readable description
        column_type         STRING      — 'dimension' or 'measure'
        column_data_type    STRING      — physical data type (VARCHAR, TIMESTAMP, etc.)
        column_metadata     STRING      — business rules, FK info, enum values
        sample_values       STRING      — real values from the column (for WHERE clause grounding)
        embedding_text      STRING      — the concatenated text that was embedded
        embedding           FLOAT64[]   — 1536-dim text-embedding-3-small vector
    """
    project_id = get_config("GCP_PROJECT_ID")
    dataset_id = get_config("BQ_DATASET")
    table_id = get_config("BQ_DD_TABLE")

    full_table_id = f"{project_id}.{dataset_id}.{table_id}"

    schema = [
        bigquery.SchemaField("id",                "INTEGER",  mode="REQUIRED"),
        bigquery.SchemaField("table_name",         "STRING",   mode="REQUIRED"),
        bigquery.SchemaField("column_name",        "STRING",   mode="REQUIRED"),
        bigquery.SchemaField("column_definition",  "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("column_type",        "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("column_data_type",   "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("column_metadata",    "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("sample_values",      "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("embedding_text",     "STRING",   mode="NULLABLE"),
        bigquery.SchemaField(
            "embedding",
            "FLOAT64",
            mode="REPEATED",  # ARRAY<FLOAT64> — 1536 elements
        ),
    ]

    table = bigquery.Table(full_table_id, schema=schema)
    table.description = (
        "Olist data dictionary with OpenAI text-embedding-3-small vectors "
        "(1536 dims) for schema-aware semantic search."
    )

    try:
        client.create_table(table, timeout=30)
        logger.info(f"✅ Table created: {full_table_id}")
    except Conflict:
        logger.info(f"ℹ️  Table already exists: {full_table_id} — skipping creation")


def create_join_metadata_table(client: bigquery.Client) -> None:
    """
    Create `join_metadata` table.

    Schema mirrors the Postgres join_metadata table.
    No embeddings needed — this is fetched by table name at query time.
    """
    project_id = get_config("GCP_PROJECT_ID")
    dataset_id = get_config("BQ_DATASET")
    table_id = get_config("BQ_JOIN_TABLE")

    full_table_id = f"{project_id}.{dataset_id}.{table_id}"

    schema = [
        bigquery.SchemaField("id",            "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("table_name_1",  "STRING",  mode="REQUIRED"),
        bigquery.SchemaField("table_name_2",  "STRING",  mode="REQUIRED"),
        bigquery.SchemaField("join_type",     "STRING",  mode="NULLABLE"),
        bigquery.SchemaField("join_condition","STRING",  mode="NULLABLE"),
        bigquery.SchemaField("column_list",   "STRING",  mode="NULLABLE"),  # JSON string
        bigquery.SchemaField("sample_sql",    "STRING",  mode="NULLABLE"),
    ]

    table = bigquery.Table(full_table_id, schema=schema)
    table.description = (
        "Olist join relationships — defines how the 9 domain tables connect. "
        "Fetched at query time based on selected table names."
    )

    try:
        client.create_table(table, timeout=30)
        logger.info(f"✅ Table created: {full_table_id}")
    except Conflict:
        logger.info(f"ℹ️  Table already exists: {full_table_id} — skipping creation")


def main():
    logger.info("=" * 60)
    logger.info("Phase 0.5 — Step 1: BigQuery Setup")
    logger.info("=" * 60)

    client = get_bq_client()
    create_dataset(client)
    create_data_dictionary_table(client)
    create_join_metadata_table(client)

    logger.info("=" * 60)
    logger.info("✅ BigQuery setup complete. Run sync_postgres_to_bq.py next.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
