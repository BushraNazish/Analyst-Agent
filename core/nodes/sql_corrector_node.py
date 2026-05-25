"""
Node 7 — SQL Corrector
========================
Fixes a SQL query that failed at the execution stage.

Receives the failed SQL + the exact PostgreSQL error message + the original
user question + the schema context, and asks GPT-5.1 to return a corrected
SQL query.

Key design decisions:
  - Uses a DIFFERENT prompt from the generator (sql_corrector_prompt.md)
    → corrector prompt is laser-focused on fixing a specific error, not
      generating from scratch
  - Does NOT reset retry_count — the executor already incremented it, and
    the count must keep rising to enforce the 3-retry cap
  - On corrector LLM failure → preserves the original broken SQL so the
    executor will fail again and the error_handler will eventually fire

Flow:
  failed SQL + sql_error + user_query + schema context
      │
      ▼
  GPT-5.1 (sql_corrector_prompt) → corrected SQL string
      │
      ▼
  state["generated_sql"] ← overwritten with corrected version
      (retry_count is NOT touched here)
"""

from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate

from core.state import AnalystState
from core.clients import get_sql_llm
from core.nodes.sql_generator_node import build_schema_context, clean_sql
from core.logger import setup_logger

logger = setup_logger("SQL-CORRECTOR")

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "sql_corrector_prompt.md"


# ── Node ───────────────────────────────────────────────────────────────────

def sql_corrector_node(state: AnalystState) -> dict:
    """
    LangGraph node — SQL Corrector.

    Reads:  state["generated_sql"] (the failed SQL)
            state["sql_error"]     (PostgreSQL error string)
            state["user_query"]    (original question for context)
            state["selected_columns"], state["relevant_joins"] (schema context)

    Writes: state["generated_sql"] ← corrected SQL (overwrites failed version)

    Fallback: on LLM failure → keeps the original broken SQL unchanged;
              the executor will fail again, incrementing retry_count until
              error_handler fires.
    """
    failed_sql      = state.get("generated_sql") or ""
    sql_error       = state.get("sql_error") or "Unknown error"
    user_query      = state.get("user_query") or ""
    selected_columns = state.get("selected_columns") or []
    relevant_joins   = state.get("relevant_joins") or []
    retry_count     = state.get("retry_count", 1)

    logger.info(
        f"[SQL-CORRECTOR] Correction attempt {retry_count}. "
        f"Error: {sql_error[:100]}"
    )

    try:
        # 1. Rebuild schema context (same helper as the generator)
        schema_context = build_schema_context(selected_columns, relevant_joins)

        # 2. Load corrector system prompt
        with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
            system_prompt = f.read()

        # 3. Build prompt — corrector gets ALL the context it needs in one message
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            (
                "human",
                "=== ORIGINAL USER QUESTION ===\n{query}\n\n"
                "=== FAILED SQL ===\n{failed_sql}\n\n"
                "=== ERROR MESSAGE ===\n{error}\n\n"
                "=== SCHEMA CONTEXT ===\n{context}\n\n"
                "Return the corrected SQL query:",
            ),
        ])

        chain = prompt | get_sql_llm()
        response = chain.invoke({
            "query":      user_query,
            "failed_sql": failed_sql,
            "error":      sql_error,
            "context":    schema_context,
        })

        corrected_sql = clean_sql(response.content)

        logger.info(
            f"[SQL-CORRECTOR] Corrected SQL ({len(corrected_sql)} chars):\n"
            f"{corrected_sql[:200]}{'...' if len(corrected_sql) > 200 else ''}"
        )

        return {
            "generated_sql": corrected_sql,
            # Do NOT touch retry_count — executor already incremented it
        }

    except Exception as e:
        # Non-fatal at this level — keep original broken SQL; executor will
        # increment retry_count again until error_handler fires
        logger.error(
            f"[SQL-CORRECTOR] LLM failure on attempt {retry_count}: {e}. "
            "Keeping original SQL — executor will retry and eventually error_handler fires."
        )
        return {
            "generated_sql": failed_sql,  # preserve original (broken) SQL
        }
