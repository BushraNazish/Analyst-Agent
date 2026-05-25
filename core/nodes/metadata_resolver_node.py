"""
Node 2 — Metadata Resolver (metadata path only)
=================================================
Answers schema/definition questions DIRECTLY from the PostgreSQL
data_dictionary and join_metadata tables — no SQL generation needed.

Triggered when: state["query_type"] == "metadata"

Flow:
  user_query (metadata type)
      │
      ▼
  Fetch full data_dictionary + join_metadata from Postgres
      │
      ▼
  GPT-5-mini formats a natural language answer
      │
      ▼
  state["metadata_response"] + state["final_response"]

State fields populated:
  - metadata_response : str  — the NL answer to the schema question
  - final_response    : str  — same as metadata_response (pipeline exits here)
"""

import psycopg2.extras
from langchain_core.prompts import ChatPromptTemplate

from core.state import AnalystState
from core.clients import get_pg_conn, get_medium_llm
from core.logger import setup_logger

logger = setup_logger("METADATA-RESOLVER")

# ── System Prompt (inline — concise enough to not warrant a .md file) ─────

_SYSTEM_PROMPT = """You are a helpful data analyst assistant with expert knowledge \
of the Olist Brazilian e-commerce dataset stored in PostgreSQL.

You have been given the COMPLETE data dictionary and join relationships for this database.
Answer the user's question about the database schema, tables, columns, or relationships \
using ONLY the provided context. Do NOT make up information.

Guidelines:
- Be clear, well-organised, and concise
- Use bullet points or markdown tables where they aid readability
- When describing columns, include data type and any important business notes
- When describing joins, explain the relationship in plain English with the join key
- If the user asks about available tables, list all 9 with a one-line description
- If the user asks about a specific table's columns, list them with types + definitions"""


# ── Schema Context Builder ─────────────────────────────────────────────────

def _build_schema_context(conn) -> str:
    """
    Fetch the full data_dictionary and join_metadata from Postgres and
    format them as a compact plain-text context block for the LLM.
    """
    context_parts = ["=== OLIST DATA DICTIONARY ===\n"]

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

        # ── data_dictionary: group by table ───────────────────────────────
        cur.execute("""
            SELECT table_name, column_name, column_definition,
                   column_type, column_data_type, column_metadata, sample_values
            FROM data_dictionary
            ORDER BY table_name, id
        """)
        rows = cur.fetchall()

        tables: dict[str, list] = {}
        for row in rows:
            t = row["table_name"]
            tables.setdefault(t, []).append(row)

        for table_name, cols in tables.items():
            context_parts.append(f"Table: {table_name}")
            for col in cols:
                line = (
                    f"  • {col['column_name']} "
                    f"[{col['column_data_type']}, {col['column_type']}]: "
                    f"{col['column_definition']}"
                )
                if col.get("column_metadata"):
                    line += f" | Notes: {col['column_metadata']}"
                if col.get("sample_values"):
                    line += f" | Sample: {col['sample_values']}"
                context_parts.append(line)
            context_parts.append("")  # blank line between tables

        # ── join_metadata ──────────────────────────────────────────────────
        context_parts.append("=== JOIN RELATIONSHIPS ===\n")
        cur.execute("""
            SELECT table_name_1, table_name_2, join_type, join_condition, sample_sql
            FROM join_metadata
            ORDER BY id
        """)
        joins = cur.fetchall()

        for jr in joins:
            context_parts.append(
                f"{jr['table_name_1']} ↔ {jr['table_name_2']} ({jr['join_type']})"
            )
            context_parts.append(f"  Condition : {jr['join_condition']}")
            if jr.get("sample_sql"):
                context_parts.append(f"  Sample SQL: {jr['sample_sql'][:120]}...")
            context_parts.append("")

    return "\n".join(context_parts)


# ── Node ───────────────────────────────────────────────────────────────────

def metadata_resolver_node(state: AnalystState) -> dict:
    """
    LangGraph node — Metadata Resolver.

    Reads:  state["user_query"]
    Writes: state["metadata_response"], state["final_response"]

    Fallback: on failure → returns a descriptive error message so the
    pipeline always gives a response.
    """
    user_query = state["user_query"]
    logger.info(f"[METADATA-RESOLVER] Resolving: '{user_query[:80]}...'")

    conn = None
    try:
        conn = get_pg_conn()
        schema_context = _build_schema_context(conn)

        prompt = ChatPromptTemplate.from_messages([
            ("system", _SYSTEM_PROMPT),
            ("human", "Database Context:\n{context}\n\nUser Question:\n{query}"),
        ])

        chain = prompt | get_medium_llm()
        response = chain.invoke({"context": schema_context, "query": user_query})
        answer = response.content

        logger.info(f"[METADATA-RESOLVER] Generated answer ({len(answer)} chars).")

        return {
            "metadata_response": answer,
            "final_response":    answer,  # metadata path terminates here
        }

    except Exception as e:
        error_msg = (
            f"I encountered an error while looking up schema information: {str(e)}\n\n"
            "Please try again or rephrase your question."
        )
        logger.error(f"[METADATA-RESOLVER] Failed: {e}")
        return {
            "metadata_response": error_msg,
            "final_response":    error_msg,
            "is_error":          True,
            "error_stage":       "metadata_resolver",
            "error_message":     str(e),
        }

    finally:
        if conn:
            conn.close()
            logger.debug("[METADATA-RESOLVER] Postgres connection closed.")
