"""
Node 3 — Schema Selector (data path)
======================================
Performs metadata-aware semantic schema selection using vector similarity.

Algorithm:
  1. Embed the user query with OpenAI text-embedding-3-small (1536 dims)
  2. Fetch all 52 pre-computed embeddings from BigQuery (≈ 300 KB payload)
  3. Compute cosine similarity in NumPy (< 1ms for 52 vectors)
  4. Select top-k most relevant columns (default k=8)
  5. Extract unique table names from top-k results

Why not use BigQuery VECTOR_SEARCH()?
  The project is on BigQuery on-demand pricing where VECTOR_SEARCH() requires
  Enterprise/Enterprise Plus reservations. The client-side cosine similarity
  approach is equally fast for 52 vectors and has zero additional cost.

State fields populated:
  - selected_columns : list[dict]  — top-k columns with metadata + similarity score
  - selected_tables  : list[str]   — unique table names in selection order
"""

import os
import numpy as np
from pathlib import Path

from core.state import AnalystState
from core.clients import get_bq_client, get_openai_client
from core.logger import setup_logger
from config.config_loader import get_config

logger = setup_logger("SCHEMA-SELECTOR")

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS  = 1536
TOP_K           = 8    # number of top columns to retrieve
LOW_SIM_THRESH  = 0.25  # below this → warn about out-of-domain query


# ── Helpers ────────────────────────────────────────────────────────────────

def _embed_query(openai_client, query: str) -> np.ndarray:
    """Embed the user query. Returns a 1536-dim float32 NumPy array."""
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
        dimensions=EMBEDDING_DIMS,
    )
    return np.array(response.data[0].embedding, dtype=np.float32)


def _fetch_all_bq_rows(bq_client) -> list[dict]:
    """
    Fetch ALL rows from BigQuery data_dictionary_embeddings.
    52 rows × 1536 floats ≈ 300 KB — negligible payload, no pagination needed.
    """
    project_id = get_config("GCP_PROJECT_ID")
    dataset_id = get_config("BQ_DATASET")
    table_id   = get_config("BQ_DD_TABLE")

    query = f"""
        SELECT id, table_name, column_name, column_definition,
               column_type, column_data_type, column_metadata,
               sample_values, embedding
        FROM `{project_id}.{dataset_id}.{table_id}`
        ORDER BY id
    """
    rows = list(bq_client.query(query).result())
    logger.info(f"[SCHEMA-SELECTOR] Fetched {len(rows)} rows from BigQuery.")
    return [dict(r) for r in rows]


def _cosine_similarity(query_vec: np.ndarray, stored_vecs: np.ndarray) -> np.ndarray:
    """
    Batch cosine similarity between one query vector and N stored vectors.

    Args:
        query_vec   : shape (D,)    — query embedding
        stored_vecs : shape (N, D)  — all stored embeddings

    Returns:
        similarities : shape (N,)  — cosine similarity scores [−1, 1]
    """
    # L2-normalise both to convert dot product → cosine similarity
    eps = 1e-10
    q_norm = query_vec / (np.linalg.norm(query_vec) + eps)
    s_norms = stored_vecs / (np.linalg.norm(stored_vecs, axis=1, keepdims=True) + eps)
    return s_norms @ q_norm  # (N, D) @ (D,) → (N,)


# ── Node ───────────────────────────────────────────────────────────────────

def schema_selector_node(state: AnalystState) -> dict:
    """
    LangGraph node — Schema Selector.

    Reads:  state["user_query"]
    Writes: state["selected_columns"], state["selected_tables"]

    Fallback: on BigQuery failure → returns is_error=True with a descriptive message.
    """
    user_query = state["user_query"]
    logger.info(f"[SCHEMA-SELECTOR] Selecting schema for: '{user_query[:80]}...'")

    try:
        bq_client     = get_bq_client()
        openai_client = get_openai_client()

        # 1. Embed the user query
        query_vec = _embed_query(openai_client, user_query)
        logger.debug(f"[SCHEMA-SELECTOR] Query embedded ({EMBEDDING_DIMS} dims).")

        # 2. Fetch all BigQuery embeddings
        all_rows = _fetch_all_bq_rows(bq_client)

        if not all_rows:
            logger.error("[SCHEMA-SELECTOR] BigQuery table is empty.")
            return {
                "is_error":     True,
                "error_stage":  "schema_selector",
                "error_message": (
                    "The metadata table in BigQuery is empty. "
                    "Please run: python scripts/generate_embeddings.py"
                ),
            }

        # 3. Build embedding matrix: shape (N, 1536)
        stored_vecs = np.array(
            [row["embedding"] for row in all_rows], dtype=np.float32
        )

        # 4. Cosine similarity
        similarities = _cosine_similarity(query_vec, stored_vecs)

        # 5. Top-k indices (descending)
        top_k_indices = np.argsort(similarities)[::-1][:TOP_K]
        top_score = float(similarities[top_k_indices[0]])

        if top_score < LOW_SIM_THRESH:
            logger.warning(
                f"[SCHEMA-SELECTOR] Low top similarity ({top_score:.3f}). "
                "Query may be out-of-domain or very generic."
            )

        # 6. Build selected_columns list
        selected_columns = []
        for idx in top_k_indices:
            row = all_rows[int(idx)]
            selected_columns.append({
                "table_name":       row["table_name"],
                "column_name":      row["column_name"],
                "column_definition":row["column_definition"],
                "column_type":      row["column_type"],
                "column_data_type": row["column_data_type"],
                "column_metadata":  row["column_metadata"],
                "sample_values":    row["sample_values"],
                "similarity_score": float(similarities[int(idx)]),
            })

        # 7. Unique table names — preserve similarity rank order
        seen: set[str] = set()
        selected_tables: list[str] = []
        for col in selected_columns:
            t = col["table_name"]
            if t not in seen:
                seen.add(t)
                selected_tables.append(t)

        logger.info(
            f"[SCHEMA-SELECTOR] Selected {len(selected_columns)} columns from "
            f"{len(selected_tables)} tables: {selected_tables} | "
            f"top_score={top_score:.3f}"
        )

        return {
            "selected_columns": selected_columns,
            "selected_tables":  selected_tables,
        }

    except Exception as e:
        logger.error(f"[SCHEMA-SELECTOR] Failed: {e}")
        return {
            "is_error":     True,
            "error_stage":  "schema_selector",
            "error_message": f"Schema selection failed: {type(e).__name__}: {str(e)}",
        }
