"""
Node 4 — Join Resolver (data path)
=====================================
Given the tables selected by Schema Selector, fetches all relevant join
conditions from the BigQuery join_metadata table.

Why from BigQuery and not Postgres?
  join_metadata is already synced to BigQuery as part of Phase 0.5.
  Keeping all metadata lookups in BigQuery ensures consistency with the
  Schema Selector and avoids an extra Postgres connection here.

Filtering logic:
  A join record is "relevant" if at least ONE of its two table names
  appears in the selected_tables list. This ensures we capture:
    - Direct joins between two selected tables  (both in selection)
    - Bridge joins via intermediate tables      (one in selection)

State fields populated:
  - relevant_joins : list[dict]  — join records with condition + sample SQL
"""

import json
import os
from pathlib import Path

from core.state import AnalystState
from core.clients import get_bq_client
from core.logger import setup_logger
from config.config_loader import get_config

logger = setup_logger("JOIN-RESOLVER")


# ── Node ───────────────────────────────────────────────────────────────────

def join_resolver_node(state: AnalystState) -> dict:
    """
    LangGraph node — Join Resolver.

    Reads:  state["selected_tables"]
    Writes: state["relevant_joins"]

    Fallback: on failure → returns empty relevant_joins list (non-fatal;
    SQL generator will proceed without explicit join hints).
    """
    selected_tables = state.get("selected_tables") or []

    if not selected_tables:
        logger.warning("[JOIN-RESOLVER] No tables selected — skipping join lookup.")
        return {"relevant_joins": []}

    logger.info(f"[JOIN-RESOLVER] Finding joins for: {selected_tables}")

    try:
        bq_client  = get_bq_client()
        project_id = get_config("GCP_PROJECT_ID")
        dataset_id = get_config("BQ_DATASET")
        table_id   = get_config("BQ_JOIN_TABLE")

        # Fetch all 10 join records (tiny — no need to filter in SQL)
        query = f"""
            SELECT id, table_name_1, table_name_2, join_type,
                   join_condition, column_list, sample_sql
            FROM `{project_id}.{dataset_id}.{table_id}`
            ORDER BY id
        """
        all_joins = list(bq_client.query(query).result())
        logger.debug(f"[JOIN-RESOLVER] Fetched {len(all_joins)} total join records from BQ.")

        # Filter: at least one table in the join matches a selected table
        selected_set = set(selected_tables)
        relevant_joins = []

        for jr in all_joins:
            t1, t2 = jr["table_name_1"], jr["table_name_2"]
            if t1 in selected_set or t2 in selected_set:
                # Parse column_list JSON if it's a string
                col_list = jr["column_list"]
                if isinstance(col_list, str) and col_list:
                    try:
                        col_list = json.loads(col_list)
                    except json.JSONDecodeError:
                        pass  # keep as raw string

                relevant_joins.append({
                    "table_name_1":   t1,
                    "table_name_2":   t2,
                    "join_type":      jr["join_type"],
                    "join_condition": jr["join_condition"],
                    "column_list":    col_list,
                    "sample_sql":     jr["sample_sql"],
                })

        logger.info(
            f"[JOIN-RESOLVER] Found {len(relevant_joins)} relevant joins "
            f"out of {len(all_joins)} total."
        )

        return {"relevant_joins": relevant_joins}

    except Exception as e:
        # Non-fatal — SQL generator can still attempt the query without joins
        logger.error(f"[JOIN-RESOLVER] Failed (non-fatal): {e}")
        return {
            "relevant_joins": [],
            # NOTE: We do NOT set is_error=True here — missing joins is recoverable.
            # The SQL generator will still try; it may produce a less accurate query.
        }
