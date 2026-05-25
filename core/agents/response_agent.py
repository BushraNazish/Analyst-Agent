"""
Response Sub-Agent — core/agents/response_agent.py
=====================================================
Reads the SQL query result from CSV and generates a structured business
report using GPT-5.1 — two sections parsed from one LLM call:

  KEY INSIGHTS  → state["insights_response"]     (5–6 executive summary bullets)
  ANALYSIS      → state["analytical_response"]   (5–6 business context bullets)

Runs in PARALLEL with visualizer_agent via LangGraph fan-out.

Data context strategy:
  - Always include: row count, column names, column dtypes
  - Rows ≤ 50    : include all rows as a formatted table
  - Rows > 50    : include first 30 rows + numeric column summary stats
  - Columns > 10 : show first 10 columns (noted to LLM)
"""

from pathlib import Path

import numpy as np
import pandas as pd
from langchain_core.prompts import ChatPromptTemplate

from core.state import AnalystState
from core.clients import get_sql_llm
from core.logger import setup_logger

logger = setup_logger("RESPONSE-AGENT")

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "response_agent_prompt.md"

_MAX_TABLE_ROWS   = 30   # rows included as formatted table in prompt
_MAX_TABLE_COLS   = 10   # columns included in the table
_MAX_SUMMARY_ROWS = 50   # above this, switch to summary stats mode


# ── Context Builder ────────────────────────────────────────────────────────

def _format_data_context(df: pd.DataFrame, row_count: int) -> str:
    """
    Build a concise, LLM-readable summary of the query result.

    For small results  (≤ 50 rows): include the full table
    For larger results (> 50 rows): include a 30-row sample + numeric summaries
    """
    n_rows = len(df)
    n_cols = len(df.columns)
    parts: list[str] = []

    # ── Header ─────────────────────────────────────────────────────────────
    parts.append(f"=== QUERY RESULT: {row_count} rows × {n_cols} columns ===")

    # Column type summary (helps LLM interpret values correctly)
    col_types = ", ".join(
        f"{col} ({str(dtype)})" for col, dtype in df.dtypes.items()
    )
    parts.append(f"Columns: {col_types}\n")

    if row_count == 0:
        parts.append("The query returned NO rows. There is no matching data.")
        return "\n".join(parts)

    # ── Sample table ────────────────────────────────────────────────────────
    sample_df = df.head(_MAX_TABLE_ROWS)

    # Cap columns to avoid token explosion (100-column results)
    col_note = ""
    if n_cols > _MAX_TABLE_COLS:
        sample_df = sample_df.iloc[:, :_MAX_TABLE_COLS]
        col_note = f"  (first {_MAX_TABLE_COLS} of {n_cols} columns shown)"

    parts.append(f"Data Sample{col_note}:")
    parts.append(sample_df.to_string(index=False))

    # ── Numeric summaries for large result sets ─────────────────────────────
    if row_count > _MAX_SUMMARY_ROWS:
        num_df = df.select_dtypes(include=[np.number])
        if not num_df.empty:
            parts.append(f"\nNumeric Summary ({row_count} total rows):")
            for col in num_df.columns:
                series = num_df[col].dropna()
                if len(series) == 0:
                    continue
                parts.append(
                    f"  {col}: "
                    f"min={series.min():,.2f}  "
                    f"max={series.max():,.2f}  "
                    f"mean={series.mean():,.2f}  "
                    f"sum={series.sum():,.2f}  "
                    f"nulls={num_df[col].isna().sum()}"
                )

    return "\n".join(parts)


# ── Section Parser ─────────────────────────────────────────────────────────

import re as _re

def _parse_two_sections(text: str) -> tuple[str, str]:
    """
    Split LLM output into (insights, analysis) based on the fixed headers
    '## KEY INSIGHTS' and '## ANALYSIS' that the prompt enforces.

    Returns:
        insights : the KEY INSIGHTS bullet block (empty string if not found)
        analysis : the ANALYSIS bullet block (full text if headers not found)
    """
    # Normalise: collapse Windows line endings
    text = text.replace("\r\n", "\n").strip()

    # Split on the ANALYSIS header (everything before = insights section)
    analysis_split = _re.split(r"##\s+ANALYSIS\b", text, maxsplit=1, flags=_re.IGNORECASE)

    if len(analysis_split) == 2:
        insights_raw = analysis_split[0]
        analysis     = analysis_split[1].strip()

        # Remove the '## KEY INSIGHTS' header from the insights block
        insights = _re.sub(
            r"##\s+KEY\s+INSIGHTS\b\s*\n?", "", insights_raw, flags=_re.IGNORECASE
        ).strip()
    else:
        # Prompt did not produce the expected structure — treat all as analysis
        insights = ""
        analysis = text

    return insights, analysis


# ── Node ───────────────────────────────────────────────────────────────────

def response_agent_node(state: AnalystState) -> dict:
    """
    LangGraph node — Response Sub-Agent.

    Reads:  state["result_csv_path"], state["user_query"], state["row_count"]

    Writes: state["insights_response"]    — KEY INSIGHTS (executive bullets)
            state["analytical_response"]  — ANALYSIS (business context bullets)

    One LLM call produces both sections; _parse_two_sections() splits them.
    Fallback: on any failure → returns a descriptive error so the UI always
    has something to show.
    """
    csv_path   = state.get("result_csv_path")
    user_query = state.get("user_query") or ""
    row_count  = state.get("row_count", 0)

    logger.info(f"[RESPONSE-AGENT] Generating report for: '{user_query[:60]}...'")

    if not csv_path:
        logger.error("[RESPONSE-AGENT] No CSV path in state.")
        err = "Could not generate analysis — query result file not found. Please retry."
        return {"insights_response": "", "analytical_response": err}

    try:
        # 1. Load CSV
        df = pd.read_csv(csv_path)

        # 2. Build data context
        data_context = _format_data_context(df, row_count)

        # 3. Load system prompt
        with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
            system_prompt = f.read()

        # 4. Build chain
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            (
                "human",
                "User Question:\n{query}\n\n"
                "Query Result:\n{data}\n\n"
                "Write your structured business report:",
            ),
        ])
        chain = prompt | get_sql_llm()

        # 5. Invoke
        response    = chain.invoke({"query": user_query, "data": data_context})
        raw_text    = response.content

        # 6. Split into two sections
        insights, analysis = _parse_two_sections(raw_text)

        if not insights.strip():
            logger.warning(
                "[RESPONSE-AGENT] KEY INSIGHTS section not found in LLM output — "
                "may indicate prompt deviation. All content routed to analytical_response."
            )

        logger.info(
            f"[RESPONSE-AGENT] Done. insights={len(insights)} chars, "
            f"analysis={len(analysis)} chars."
        )

        return {
            "insights_response":  insights,
            "analytical_response": analysis,
        }

    except Exception as e:
        logger.error(f"[RESPONSE-AGENT] Failed: {e}")
        err = (
            f"Error while analysing the results: {str(e)}\n\n"
            f"The query returned {row_count} rows. Please try again."
        )
        return {"insights_response": "", "analytical_response": err}
