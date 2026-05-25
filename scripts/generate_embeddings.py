"""
Script 3 of 3 — Generate & Store Embeddings in BigQuery
=========================================================
For each row in the BigQuery `data_dictionary_embeddings` table:
  1. Reads the pre-built `embedding_text` field
  2. Calls OpenAI text-embedding-3-small to generate a 1536-dim vector
  3. Updates the `embedding` REPEATED FLOAT64 column in BigQuery

Uses batch embedding to minimise API calls (OpenAI supports up to 2048
texts per request; we have only 52, so it's a single call).

Run AFTER sync_postgres_to_bq.py.

Usage:
    python scripts/generate_embeddings.py
"""

import os
import sys
import time

# ── ensure project root is on path ────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from google.cloud import bigquery
from openai import OpenAI
from config.config_loader import get_config
from core.logger import setup_logger

logger = setup_logger("BQ-EMBEDDINGS")

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS  = 1536


# ── Clients ────────────────────────────────────────────────────────────────

def get_bq_client() -> bigquery.Client:
    creds_path = get_config("GOOGLE_APPLICATION_CREDENTIALS")
    project_id = get_config("GCP_PROJECT_ID")

    if not os.path.isabs(creds_path):
        creds_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", creds_path))

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
    return bigquery.Client(project=project_id)


def get_openai_client() -> OpenAI:
    api_key = get_config("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in agent_config.yaml")
    return OpenAI(api_key=api_key)


# ── Embedding generation ───────────────────────────────────────────────────

def embed_texts(openai_client: OpenAI, texts: list[str]) -> list[list[float]]:
    """
    Call OpenAI to embed a list of texts in a single batch request.
    Returns a list of 1536-dim float vectors in the same order as input.
    """
    logger.info(f"Generating embeddings for {len(texts)} texts using {EMBEDDING_MODEL}...")
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        dimensions=EMBEDDING_DIMS,
    )
    vectors = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
    logger.info(f"✅ Received {len(vectors)} embeddings (each {len(vectors[0])} dims).")
    return vectors


# ── BigQuery read & update ─────────────────────────────────────────────────

def fetch_rows_from_bq(bq_client: bigquery.Client) -> list[dict]:
    """Fetch ALL columns from data_dictionary_embeddings for re-insertion with embeddings."""
    project_id = get_config("GCP_PROJECT_ID")
    dataset_id = get_config("BQ_DATASET")
    table_id   = get_config("BQ_DD_TABLE")

    query = f"""
        SELECT id, table_name, column_name, column_definition,
               column_type, column_data_type, column_metadata,
               sample_values, embedding_text
        FROM `{project_id}.{dataset_id}.{table_id}`
        ORDER BY id
    """
    rows = list(bq_client.query(query).result())
    logger.info(f"Fetched {len(rows)} rows from BigQuery for embedding.")
    return [dict(r) for r in rows]


def update_embeddings_in_bq(
    bq_client: bigquery.Client,
    id_vector_pairs: list[tuple[int, list[float]]],
    all_rows: list[dict],
) -> None:
    """
    Write all rows + embeddings to BigQuery using a batch load job (WRITE_TRUNCATE).

    Why not DELETE + INSERT?
        Rows inserted via insert_rows_json (streaming API) sit in BigQuery's
        'streaming buffer' for ~90 min. DML (DELETE/UPDATE) cannot touch
        streaming-buffer rows — it raises a 400 BadRequest error.

    Why not MERGE SQL?
        52 rows × 1536 floats inlined as text = ~1.57MB, exceeding BigQuery's
        1MB SQL query size limit.

    Solution — load_table_from_json with WRITE_TRUNCATE:
        This is a batch load job that atomically replaces the entire table.
        It bypasses the streaming buffer restriction and has no SQL size limit.
        The table schema must be provided explicitly so BQ knows the REPEATED
        FLOAT64 type for the embedding column.
    """
    project_id = get_config("GCP_PROJECT_ID")
    dataset_id = get_config("BQ_DATASET")
    table_id   = get_config("BQ_DD_TABLE")
    full_table_id = f"{project_id}.{dataset_id}.{table_id}"

    # Build id → vector lookup
    vector_map = {row_id: vector for row_id, vector in id_vector_pairs}

    # Build complete rows with embeddings
    bq_rows = []
    for row in all_rows:
        row_id = row["id"]
        bq_rows.append({
            "id":                row_id,
            "table_name":        row.get("table_name") or "",
            "column_name":       row.get("column_name") or "",
            "column_definition": row.get("column_definition") or "",
            "column_type":       row.get("column_type") or "",
            "column_data_type":  row.get("column_data_type") or "",
            "column_metadata":   row.get("column_metadata") or "",
            "sample_values":     row.get("sample_values") or "",
            "embedding_text":    row.get("embedding_text") or "",
            "embedding":         vector_map.get(row_id, []),
        })

    # Define the table schema explicitly — required for REPEATED FLOAT64
    schema = [
        bigquery.SchemaField("id",                "INTEGER",  mode="REQUIRED"),
        bigquery.SchemaField("table_name",         "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("column_name",        "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("column_definition",  "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("column_type",        "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("column_data_type",   "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("column_metadata",    "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("sample_values",      "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("embedding_text",     "STRING",   mode="NULLABLE"),
        bigquery.SchemaField("embedding",          "FLOAT64",  mode="REPEATED"),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        # WRITE_TRUNCATE atomically replaces all table contents —
        # bypasses streaming buffer restriction, no SQL size limit
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )

    logger.info(f"Loading {len(bq_rows)} rows with embeddings via batch load (WRITE_TRUNCATE)...")
    load_job = bq_client.load_table_from_json(bq_rows, full_table_id, job_config=job_config)
    load_job.result()  # wait for completion

    if load_job.errors:
        logger.error(f"Load job errors: {load_job.errors}")
        raise RuntimeError(f"Failed to load rows with embeddings: {load_job.errors}")

    logger.info(f"✅ Successfully loaded {len(bq_rows)} rows with embeddings into {full_table_id}.")




# ── Verification ───────────────────────────────────────────────────────────

def verify_embeddings(bq_client: bigquery.Client) -> None:
    """Quick sanity check — count rows with non-empty embeddings."""
    project_id = get_config("GCP_PROJECT_ID")
    dataset_id = get_config("BQ_DATASET")
    table_id   = get_config("BQ_DD_TABLE")

    query = f"""
        SELECT
            COUNT(*) AS total_rows,
            COUNTIF(ARRAY_LENGTH(embedding) = {EMBEDDING_DIMS}) AS rows_with_embeddings
        FROM `{project_id}.{dataset_id}.{table_id}`
    """
    result = list(bq_client.query(query).result())[0]
    total  = result["total_rows"]
    filled = result["rows_with_embeddings"]

    logger.info(f"Verification: {filled}/{total} rows have {EMBEDDING_DIMS}-dim embeddings.")

    if filled != total:
        logger.warning(
            f"⚠️  {total - filled} rows are missing embeddings! "
            "Re-run this script to retry."
        )
    else:
        logger.info("✅ All rows have valid embeddings.")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("Phase 0.5 — Step 3: Generate & Store Embeddings")
    logger.info(f"Model: {EMBEDDING_MODEL} | Dims: {EMBEDDING_DIMS}")
    logger.info("=" * 60)

    bq_client     = get_bq_client()
    openai_client = get_openai_client()

    # 1. Fetch rows that need embedding
    rows = fetch_rows_from_bq(bq_client)
    if not rows:
        logger.error("No rows found in BigQuery. Run sync_postgres_to_bq.py first.")
        sys.exit(1)

    # 2. Extract texts in order
    texts = [r["embedding_text"] for r in rows]
    ids   = [r["id"] for r in rows]

    # 3. Generate embeddings in a single batch call
    start = time.time()
    vectors = embed_texts(openai_client, texts)
    elapsed = time.time() - start
    logger.info(f"Embedding generation took {elapsed:.2f}s")

    # 4. Pair ids with vectors and push to BigQuery
    id_vector_pairs = list(zip(ids, vectors))
    update_embeddings_in_bq(bq_client, id_vector_pairs, rows)

    # 5. Verify
    verify_embeddings(bq_client)

    logger.info("=" * 60)
    logger.info("✅ Phase 0.5 complete! BigQuery is ready for Phase 1.")
    logger.info("   Next: implement the Query Classifier node (Phase 1).")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
