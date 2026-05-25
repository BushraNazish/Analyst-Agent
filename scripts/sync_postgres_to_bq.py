"""
Script 2 of 3 — Sync Postgres → BigQuery
==========================================
Reads all rows from the Postgres `data_dictionary` and `join_metadata`
tables and inserts them into their BigQuery counterparts.

The `embedding` column is left as an empty REPEATED FLOAT64 array at
this stage — it will be populated by generate_embeddings.py (Script 3).

Run AFTER setup_bigquery.py.

Usage:
    python scripts/sync_postgres_to_bq.py
"""

import os
import sys
import json

# ── ensure project root is on path ────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import psycopg2
import psycopg2.extras
from google.cloud import bigquery
from config.config_loader import get_config
from core.logger import setup_logger

logger = setup_logger("BQ-SYNC")


# ── Helpers ────────────────────────────────────────────────────────────────

def get_postgres_conn():
    """Return a synchronous psycopg2 connection to the Olist Postgres DB."""
    conn = psycopg2.connect(
        dbname=get_config("POSTGRES_DB"),
        user=get_config("POSTGRES_USER"),
        password=get_config("POSTGRES_PASSWORD"),
        host=get_config("POSTGRES_HOST"),
        port=get_config("POSTGRES_PORT", 5432),
    )
    logger.info("PostgreSQL connection established.")
    return conn


def get_bq_client() -> bigquery.Client:
    """Initialise BigQuery client using service account credentials."""
    creds_path = get_config("GOOGLE_APPLICATION_CREDENTIALS")
    project_id = get_config("GCP_PROJECT_ID")

    if not os.path.isabs(creds_path):
        creds_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", creds_path))

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
    client = bigquery.Client(project=project_id)
    logger.info(f"BigQuery client initialised for project: {project_id}")
    return client


def build_embedding_text(row: dict) -> str:
    """
    Build the text string that will be embedded for a data_dictionary row.
    Combines the most semantically rich fields into a single string.
    """
    parts = [
        f"table: {row.get('table_name', '')}",
        f"column: {row.get('column_name', '')}",
        f"definition: {row.get('column_definition', '')}",
        f"type: {row.get('column_type', '')}",
        f"data_type: {row.get('column_data_type', '')}",
        f"metadata: {row.get('column_metadata', '')}",
        f"sample_values: {row.get('sample_values', '')}",
    ]
    return " | ".join(p for p in parts if p.split(": ", 1)[1])


# ── Sync data_dictionary ────────────────────────────────────────────────────

def sync_data_dictionary(pg_conn, bq_client: bigquery.Client) -> None:
    """
    Read all rows from Postgres data_dictionary and insert into BigQuery.
    Clears the BQ table first to avoid duplicates on re-runs.
    """
    project_id = get_config("GCP_PROJECT_ID")
    dataset_id = get_config("BQ_DATASET")
    table_id = get_config("BQ_DD_TABLE")
    full_table_id = f"{project_id}.{dataset_id}.{table_id}"

    logger.info("Reading data_dictionary from PostgreSQL...")
    with pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM data_dictionary ORDER BY id")
        rows = cur.fetchall()

    logger.info(f"Fetched {len(rows)} rows from data_dictionary.")

    # Clear existing BQ rows before re-inserting (idempotent sync)
    bq_client.query(f"DELETE FROM `{full_table_id}` WHERE TRUE").result()
    logger.info(f"Cleared existing rows from {full_table_id}.")

    # Build BQ rows (embedding is empty — will be filled by Script 3)
    bq_rows = []
    for row in rows:
        row = dict(row)
        embedding_text = build_embedding_text(row)
        bq_rows.append({
            "id":                 row["id"],
            "table_name":         row.get("table_name") or "",
            "column_name":        row.get("column_name") or "",
            "column_definition":  row.get("column_definition") or "",
            "column_type":        row.get("column_type") or "",
            "column_data_type":   row.get("column_data_type") or "",
            "column_metadata":    row.get("column_metadata") or "",
            "sample_values":      row.get("sample_values") or "",
            "embedding_text":     embedding_text,
            "embedding":          [],   # populated by generate_embeddings.py
        })

    errors = bq_client.insert_rows_json(full_table_id, bq_rows)
    if errors:
        logger.error(f"BigQuery insert errors for data_dictionary: {errors}")
        raise RuntimeError(f"Failed to insert data_dictionary rows: {errors}")

    logger.info(f"✅ Synced {len(bq_rows)} rows → {full_table_id}")


# ── Sync join_metadata ──────────────────────────────────────────────────────

def sync_join_metadata(pg_conn, bq_client: bigquery.Client) -> None:
    """
    Read all rows from Postgres join_metadata and insert into BigQuery.
    """
    project_id = get_config("GCP_PROJECT_ID")
    dataset_id = get_config("BQ_DATASET")
    table_id = get_config("BQ_JOIN_TABLE")
    full_table_id = f"{project_id}.{dataset_id}.{table_id}"

    logger.info("Reading join_metadata from PostgreSQL...")
    with pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM join_metadata ORDER BY id")
        rows = cur.fetchall()

    logger.info(f"Fetched {len(rows)} rows from join_metadata.")

    # Clear existing rows first
    bq_client.query(f"DELETE FROM `{full_table_id}` WHERE TRUE").result()
    logger.info(f"Cleared existing rows from {full_table_id}.")

    bq_rows = []
    for row in rows:
        row = dict(row)
        # column_list is stored as JSON in Postgres — keep it as a string in BQ
        col_list = row.get("column_list")
        if col_list is not None and not isinstance(col_list, str):
            col_list = json.dumps(col_list)

        bq_rows.append({
            "id":             row["id"],
            "table_name_1":   row.get("table_name_1") or "",
            "table_name_2":   row.get("table_name_2") or "",
            "join_type":      row.get("join_type") or "",
            "join_condition": row.get("join_condition") or "",
            "column_list":    col_list or "",
            "sample_sql":     row.get("sample_sql") or "",
        })

    errors = bq_client.insert_rows_json(full_table_id, bq_rows)
    if errors:
        logger.error(f"BigQuery insert errors for join_metadata: {errors}")
        raise RuntimeError(f"Failed to insert join_metadata rows: {errors}")

    logger.info(f"✅ Synced {len(bq_rows)} rows → {full_table_id}")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("Phase 0.5 — Step 2: Sync Postgres → BigQuery")
    logger.info("=" * 60)

    pg_conn = get_postgres_conn()
    bq_client = get_bq_client()

    try:
        sync_data_dictionary(pg_conn, bq_client)
        sync_join_metadata(pg_conn, bq_client)
    finally:
        pg_conn.close()
        logger.info("PostgreSQL connection closed.")

    logger.info("=" * 60)
    logger.info("✅ Sync complete. Run generate_embeddings.py next.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
