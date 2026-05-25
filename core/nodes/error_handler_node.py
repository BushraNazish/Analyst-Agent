"""
Node 8 — Error Handler
========================
Terminal node for the self-correction loop when all retries are exhausted.

Triggered when: retry_count >= 3 AND sql_error is not None

Formats a clear, user-friendly final response that includes:
  1. A plain-language explanation of what went wrong
  2. The last SQL attempt (so the user can see what was tried)
  3. The last error message (technical detail for advanced users)
  4. A suggestion for how to rephrase the question

State fields populated:
  - is_error      : True
  - error_stage   : "sql_execution"
  - error_message : clean technical description
  - final_response: user-facing formatted message
"""

from core.state import AnalystState
from core.logger import setup_logger

logger = setup_logger("ERROR-HANDLER")

_MAX_SQL_DISPLAY_LEN = 600   # truncate very long SQL for display


def error_handler_node(state: AnalystState) -> dict:
    """
    LangGraph node — Error Handler.

    Reads:  state["generated_sql"] (last SQL attempt)
            state["sql_error"]     (last PostgreSQL error)
            state["retry_count"]   (how many attempts were made)
            state["user_query"]    (original question)

    Writes: state["is_error"], state["error_stage"], state["error_message"],
            state["final_response"]
    """
    sql         = state.get("generated_sql") or "—"
    sql_error   = state.get("sql_error") or "Unknown error"
    retry_count = state.get("retry_count", 0)
    user_query  = state.get("user_query") or "—"

    logger.error(
        f"[ERROR-HANDLER] All {retry_count} retry attempts exhausted. "
        f"Last error: {sql_error[:120]}"
    )

    # Truncate SQL for display
    sql_display = sql if len(sql) <= _MAX_SQL_DISPLAY_LEN else sql[:_MAX_SQL_DISPLAY_LEN] + "\n... [truncated]"

    # Format a clean user-facing message
    final_response = (
        f"⚠️ **I was unable to answer your question after {retry_count} attempt(s).**\n\n"
        f"**Your question:** {user_query}\n\n"
        f"**What went wrong:** {sql_error}\n\n"
        f"**Last SQL attempted:**\n```sql\n{sql_display}\n```\n\n"
        "**Suggestion:** Try rephrasing your question with more specific column or table names, "
        "or simplify the request. For example, instead of a complex multi-step analysis, "
        "break it into smaller questions."
    )

    logger.info("[ERROR-HANDLER] Final error response formatted.")

    return {
        "is_error":       True,
        "error_stage":    "sql_execution",
        "error_message":  sql_error,
        "final_response": final_response,
    }
