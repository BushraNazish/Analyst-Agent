"""
Node 5 — SQL Generator
========================
Generates a PostgreSQL SQL query from the user's question + schema context
assembled by Schema Selector (Phase 1).

Uses GPT-5.1 at temperature=0 for deterministic, accurate SQL output.

Flow:
  user_query + selected_columns + relevant_joins
      │
      ▼
  build_schema_context() — compact text block for the LLM
      │
      ▼
  GPT-5.1 (sql_generator_prompt) → raw SQL string
      │
      ▼
  clean_sql() — strip markdown fences if model adds them
      │
      ▼
  state["generated_sql"], state["retry_count"] = 0

This module also exports build_schema_context() and clean_sql() so that
sql_corrector_node.py can reuse them without circular imports.
"""

import re
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate

from core.state import AnalystState
from core.clients import get_sql_llm
from core.logger import setup_logger

logger = setup_logger("SQL-GENERATOR")

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "sql_generator_prompt.md"


# ── Shared Utilities (also imported by sql_corrector_node) ────────────────

def build_schema_context(
    selected_columns: list[dict],
    relevant_joins: list[dict],
) -> str:
    """
    Convert selected_columns + relevant_joins into a compact text block
    that fits cleanly in the LLM prompt.

    Format example:
        === RELEVANT COLUMNS ===
        Table: orders
          • order_id       [VARCHAR, dimension] Primary key for each order.
                            Sample values: —
          • order_status   [VARCHAR, dimension] Current lifecycle status.
                            Sample values: delivered, shipped, canceled, ...

        === JOIN CONDITIONS ===
        orders ↔ customers (INNER JOIN)
          ON orders.customer_id = customers.customer_id
          Sample SQL: SELECT ... FROM orders o JOIN customers c ON o.customer_id = c.customer_id
    """
    parts: list[str] = ["=== RELEVANT COLUMNS ===\n"]

    # Group columns by table — preserving similarity rank order
    table_cols: dict[str, list[dict]] = {}
    for col in selected_columns:
        t = col["table_name"]
        table_cols.setdefault(t, []).append(col)

    for table_name, cols in table_cols.items():
        parts.append(f"Table: {table_name}")
        for col in cols:
            line = (
                f"  • {col['column_name']} "
                f"[{col['column_data_type']}, {col['column_type']}]: "
                f"{col['column_definition']}"
            )
            if col.get("column_metadata"):
                line += f"\n    Notes: {col['column_metadata']}"
            if col.get("sample_values"):
                line += f"\n    Sample values: {col['sample_values']}"
            parts.append(line)
        parts.append("")  # blank line between tables

    if relevant_joins:
        parts.append("=== JOIN CONDITIONS ===\n")
        for jr in relevant_joins:
            parts.append(
                f"{jr['table_name_1']} ↔ {jr['table_name_2']} ({jr['join_type']})"
            )
            parts.append(f"  ON {jr['join_condition']}")
            if jr.get("sample_sql"):
                # Truncate long sample SQL to keep prompt size reasonable
                sample = str(jr["sample_sql"])[:300]
                parts.append(f"  Sample SQL: {sample}")
            parts.append("")

    return "\n".join(parts)


def clean_sql(raw: str) -> str:
    """
    Strip markdown code fences and surrounding whitespace from LLM output.

    GPT occasionally wraps SQL in:
        ```sql
        SELECT ...
        ```
    or just:
        ```
        SELECT ...
        ```
    This function handles both variants.
    """
    # Remove leading/trailing whitespace
    sql = raw.strip()

    # Strip code fences: ```sql ... ``` or ``` ... ```
    sql = re.sub(r"^```(?:sql)?\s*\n?", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\n?```\s*$", "", sql, flags=re.IGNORECASE)

    return sql.strip()


# ── Node ───────────────────────────────────────────────────────────────────

def sql_generator_node(state: AnalystState) -> dict:
    """
    LangGraph node — SQL Generator.

    Reads:  state["user_query"], state["selected_columns"],
            state["selected_tables"], state["relevant_joins"]
    Writes: state["generated_sql"], state["retry_count"] (initialised to 0)

    Fallback: on LLM failure → sets is_error=True with a descriptive message.
    """
    user_query      = state["user_query"]
    selected_columns = state.get("selected_columns") or []
    relevant_joins   = state.get("relevant_joins") or []

    logger.info(
        f"[SQL-GENERATOR] Generating SQL for: '{user_query[:80]}...' "
        f"| {len(selected_columns)} columns, {len(relevant_joins)} joins"
    )

    try:
        # 1. Build schema context
        schema_context = build_schema_context(selected_columns, relevant_joins)

        # 2. Load system prompt
        with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
            system_prompt = f.read()

        # 3. Build LangChain chain
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            (
                "human",
                "Schema Context:\n{context}\n\n"
                "User Question:\n{query}\n\n"
                "Write the PostgreSQL SQL query:",
            ),
        ])
        chain = prompt | get_sql_llm()

        # 4. Invoke
        response = chain.invoke({"context": schema_context, "query": user_query})
        generated_sql = clean_sql(response.content)

        logger.info(
            f"[SQL-GENERATOR] Generated SQL ({len(generated_sql)} chars):\n"
            f"{generated_sql[:200]}{'...' if len(generated_sql) > 200 else ''}"
        )

        return {
            "generated_sql": generated_sql,
            "retry_count":   0,   # initialise retry counter
            "sql_error":     None,
        }

    except Exception as e:
        logger.error(f"[SQL-GENERATOR] LLM failure: {e}")
        return {
            "generated_sql": None,
            "retry_count":   0,
            "is_error":      True,
            "error_stage":   "sql_generator",
            "error_message": f"SQL generation failed: {type(e).__name__}: {str(e)}",
        }
