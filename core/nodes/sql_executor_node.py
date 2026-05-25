"""
Node 6 — SQL Executor
=======================
Executes the generated SQL against PostgreSQL and persists results to disk.

On SUCCESS:
  - Loads results into a pandas DataFrame
  - Saves to  output/result_{uuid}.csv
  - Saves companion output/result_{uuid}_types.json   ← dtype map for visualizer
  - Writes result_csv_path, result_types_path, row_count, column_names, sql_error=None

On FAILURE:
  - Captures the PostgreSQL error (clean, user-readable)
  - Increments retry_count
  - Sets sql_error so the conditional edge routes to sql_corrector_node

Query timeout: 30 seconds (enforced via PostgreSQL statement_timeout).
Zero-row results are NOT treated as errors — they populate the fields normally
and the Response Sub-Agent will explain "no data found" in natural language.

Routing helper exported:
  route_after_execution(state) → "phase3" | "sql_corrector" | "error_handler"
"""

import json
import os
import uuid
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

from core.state import AnalystState
from core.logger import setup_logger
from config.config_loader import get_config

logger = setup_logger("SQL-EXECUTOR")

# Absolute path to the project-root output/ directory
_OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"
_MAX_RETRIES = 3


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_pg_conn_with_timeout():
    """
    Open a synchronous psycopg2 connection with a 30-second statement timeout.
    The timeout prevents runaway queries from blocking the pipeline.
    """
    conn = psycopg2.connect(
        dbname=get_config("POSTGRES_DB"),
        user=get_config("POSTGRES_USER"),
        password=get_config("POSTGRES_PASSWORD"),
        host=get_config("POSTGRES_HOST"),
        port=int(get_config("POSTGRES_PORT", 5432)),
        options="-c statement_timeout=30000",   # 30 s hard limit
    )
    return conn


def _clean_pg_error(exc: Exception) -> str:
    """
    Extract a clean, user-readable error message from a psycopg2 exception.
    Strips internal Postgres detail lines and keeps only the primary message.
    """
    msg = str(exc)
    # psycopg2 errors often include DETAIL/HINT/CONTEXT — keep just the first line
    first_line = msg.split("\n")[0].strip()
    # Remove the 'LINE N:' prefix that psycopg2 sometimes adds
    return first_line


def _save_results(df: pd.DataFrame) -> tuple[str, str]:
    """
    Persist the query result DataFrame to CSV and companion _types.json.

    Returns:
        (csv_path, types_path) — absolute path strings
    """
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run_id   = uuid.uuid4().hex[:12]
    csv_path  = str(_OUTPUT_DIR / f"result_{run_id}.csv")
    json_path = str(_OUTPUT_DIR / f"result_{run_id}_types.json")

    # Save CSV (no index column)
    df.to_csv(csv_path, index=False, encoding="utf-8")

    # Save dtype map so the Visualizer Sub-Agent can parse dates/numbers correctly
    type_map = {col: str(dtype) for col, dtype in df.dtypes.items()}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(type_map, f, indent=2)

    logger.info(f"[SQL-EXECUTOR] Saved CSV → {csv_path}  ({len(df)} rows)")
    logger.info(f"[SQL-EXECUTOR] Saved types → {json_path}")
    return csv_path, json_path


# ── Routing helper (used as conditional edge in graph.py) ─────────────────

def route_after_execution(state: AnalystState) -> str:
    """
    Conditional edge function called by LangGraph after sql_executor_node.

    Returns one of three node names:
      "phase3"        — SQL succeeded; proceed to parallel sub-agents
      "sql_corrector" — SQL failed but retries remain; fix and retry
      "error_handler" — Retries exhausted; surface the error to the user
    """
    if not state.get("sql_error"):
        return "phase3"

    retry_count = state.get("retry_count", 0)
    if retry_count < _MAX_RETRIES:
        return "sql_corrector"

    return "error_handler"


# ── Node ───────────────────────────────────────────────────────────────────

def sql_executor_node(state: AnalystState) -> dict:
    """
    LangGraph node — SQL Executor.

    Reads:  state["generated_sql"], state["retry_count"]
    Writes (success): result_csv_path, result_types_path, row_count,
                      column_names, sql_error=None
    Writes (failure): sql_error (clean string), retry_count += 1
    """
    sql         = state.get("generated_sql") or ""
    retry_count = state.get("retry_count", 0)

    if not sql:
        logger.error("[SQL-EXECUTOR] generated_sql is empty — cannot execute.")
        return {
            "sql_error":   "No SQL query was generated.",
            "retry_count": retry_count + 1,
        }

    logger.info(
        f"[SQL-EXECUTOR] Executing SQL (attempt {retry_count + 1}/{_MAX_RETRIES}):\n"
        f"{sql[:200]}{'...' if len(sql) > 200 else ''}"
    )

    conn = None
    try:
        conn = _get_pg_conn_with_timeout()

        # Execute and load into DataFrame via pandas
        df = pd.read_sql_query(sql, conn)

        row_count    = len(df)
        column_names = list(df.columns)

        logger.info(
            f"[SQL-EXECUTOR] Query succeeded: {row_count} rows, "
            f"{len(column_names)} columns."
        )

        # Zero rows is NOT an error — response sub-agent will handle the messaging
        if row_count == 0:
            logger.warning("[SQL-EXECUTOR] Query returned 0 rows.")

        # Persist results
        csv_path, types_path = _save_results(df)

        return {
            "result_csv_path":   csv_path,
            "result_types_path": types_path,
            "row_count":         row_count,
            "column_names":      column_names,
            "sql_error":         None,   # ← clear any previous error
        }

    except psycopg2.errors.QueryCanceled:
        # Statement timeout hit
        error_msg = (
            "Query timed out after 30 seconds. "
            "Try narrowing the date range or adding more filters."
        )
        logger.warning(f"[SQL-EXECUTOR] Timeout on attempt {retry_count + 1}.")
        return {
            "sql_error":   error_msg,
            "retry_count": retry_count + 1,
        }

    except Exception as e:
        error_msg = _clean_pg_error(e)
        logger.warning(
            f"[SQL-EXECUTOR] Execution error (attempt {retry_count + 1}): {error_msg}"
        )
        return {
            "sql_error":   error_msg,
            "retry_count": retry_count + 1,
        }

    finally:
        if conn:
            conn.close()
