"""
Visualizer Sub-Agent — core/agents/visualizer_agent.py
=========================================================
Reads the SQL result CSV and generates a Plotly figure, serialised as a
JSON string for the Gradio UI.

Runs in PARALLEL with response_agent via LangGraph fan-out.

Chart type decision — LLM-DRIVEN (GPT-4o Mini + structured output):
  The LLM reads the user's question, column names, dtypes, and a data
  sample, then returns a structured ChartDecision (Pydantic model).
  This replaces all previous hardcoded rules.

  The LLM decides:
    - chart_type  : "bar" | "line" | "pie" | "scatter" | "none"
    - x_col       : exact column name for the X axis / category axis
    - y_col       : exact numeric column name for the Y axis / values
    - color_col   : optional column for color grouping (nullable)
    - title       : short, business-friendly chart title
    - sort_descending : bool — sort bars high→low (default True)

  _build_figure() uses these decisions to construct the Plotly figure.
  It always trims bar charts to top 20 rows for readability.

  On any failure (LLM error, invalid column names, Plotly error) the node
  returns viz_chart_type="none" — fully non-fatal.

State fields written:
  - visualization_json : str | None   — Plotly JSON (or None if no chart)
  - viz_chart_type     : str          — "bar", "line", "scatter", "pie", "none"
"""

import json
from pathlib import Path
from typing import Optional, Literal

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from core.state import AnalystState
from core.clients import get_light_llm
from core.logger import setup_logger

logger = setup_logger("VISUALIZER")

_PLOTLY_TEMPLATE = "plotly_white"
_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "visualizer_agent_prompt.md"


# ── Structured Output Schema ────────────────────────────────────────────────

class ChartDecision(BaseModel):
    """Structured chart selection returned by the LLM."""

    chart_type: Literal["bar", "line", "pie", "scatter", "none"] = Field(
        description=(
            "The Plotly chart type to generate. "
            "Use 'none' if the data cannot be meaningfully visualised."
        )
    )
    x_col: Optional[str] = Field(
        default=None,
        description=(
            "Exact column name (case-sensitive) to place on the X axis or use "
            "as the category/label axis. Must match a column in the data. "
            "Set to null if chart_type is 'none'."
        ),
    )
    y_col: Optional[str] = Field(
        default=None,
        description=(
            "Exact column name (case-sensitive) of the numeric measure for the "
            "Y axis / pie values. Must match a numeric column in the data. "
            "Set to null if chart_type is 'none'."
        ),
    )
    color_col: Optional[str] = Field(
        default=None,
        description=(
            "Optional column name for color grouping. Set to null if not needed."
        ),
    )
    title: Optional[str] = Field(
        default=None,
        description="Short, business-friendly chart title (under 10 words).",
    )
    sort_descending: bool = Field(
        default=True,
        description=(
            "For bar charts, whether to sort bars from highest to lowest value. "
            "Set to false when natural ordering is more meaningful (e.g. states A–Z)."
        ),
    )


# ── Column Context Builder ─────────────────────────────────────────────────

def _build_column_context(
    df: pd.DataFrame,
    type_map: dict[str, str],
    max_sample_values: int = 3,
) -> str:
    """
    Build a concise, LLM-readable description of the result columns.

    Example output:
        Total rows: 27
        Columns (2):
          - 'customer_state' [object]: sample values = ['SP', 'RJ', 'MG']
          - 'avg_delivery_time_days' [float64]: sample values = [-20.1, -16.5, -11.1]
    """
    lines = [
        f"Total rows: {len(df)}",
        f"Columns ({len(df.columns)}):",
    ]
    for col in df.columns:
        dtype = type_map.get(col, str(df[col].dtype))
        sample = df[col].dropna().head(max_sample_values).tolist()
        lines.append(f"  - {col!r} [{dtype}]: sample values = {sample}")
    return "\n".join(lines)


# ── LLM Chart Decision ────────────────────────────────────────────────────

def _ask_llm_for_chart(user_query: str, col_context: str) -> ChartDecision:
    """
    Call GPT-4o Mini and parse the response as JSON into a ChartDecision.

    Uses plain text + JSON parsing instead of with_structured_output() for
    maximum compatibility across langchain-openai versions.

    Falls back to ChartDecision(chart_type="none") on any parse / validation
    error so the rest of the pipeline is never blocked.
    """
    system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")

    user_message = (
        f"User question: {user_query}\n\n"
        f"Data summary:\n{col_context}\n\n"
        "Return ONLY a JSON object. No markdown, no explanation. Example format:\n"
        '{"chart_type": "bar", "x_col": "customer_state", '
        '"y_col": "avg_delivery_time_days", "color_col": null, '
        '"title": "Delivery Time by State", "sort_descending": false}'
    )

    llm = get_light_llm()

    logger.debug("[VISUALIZER] Sending chart decision request to LLM...")
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ])

    raw = response.content.strip()
    logger.debug(f"[VISUALIZER] Raw LLM response: {raw[:300]}")

    # Strip markdown code fences if the LLM adds them despite instructions
    if raw.startswith("```"):
        parts = raw.split("```")
        # parts[1] is the block content; strip optional "json" language tag
        raw = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[VISUALIZER] JSON parse failed: {e} | raw={raw[:200]}")
        return ChartDecision(chart_type="none")

    try:
        decision = ChartDecision(**data)
    except Exception as e:
        logger.error(f"[VISUALIZER] ChartDecision validation failed: {e} | data={data}")
        return ChartDecision(chart_type="none")

    logger.info(
        f"[VISUALIZER] LLM decision → type={decision.chart_type!r}, "
        f"x={decision.x_col!r}, y={decision.y_col!r}, "
        f"color={decision.color_col!r}, sort_desc={decision.sort_descending}"
    )
    return decision


# ── Figure Builder ────────────────────────────────────────────────────────

def _build_figure(df: pd.DataFrame, decision: ChartDecision) -> go.Figure:
    """
    Build a styled Plotly figure from the LLM's ChartDecision.

    The decision provides exact column names — no heuristic inference.
    Bar charts are always trimmed to the top 20 rows for readability.
    """
    chart_type = decision.chart_type
    x_col      = decision.x_col
    y_col      = decision.y_col
    color_col  = decision.color_col
    title      = decision.title or (f"{y_col} by {x_col}" if x_col and y_col else "Chart")

    if chart_type == "line":
        df_plot = df.copy()
        try:
            df_plot[x_col] = pd.to_datetime(df_plot[x_col], errors="coerce")
            df_plot = df_plot.sort_values(x_col)
        except Exception:
            pass    # keep as-is if parse fails
        fig = px.line(
            df_plot,
            x=x_col,
            y=y_col,
            color=color_col,
            title=title,
            markers=True,
        )

    elif chart_type == "bar":
        df_plot = df.copy()
        if decision.sort_descending and y_col:
            df_plot = df_plot.sort_values(y_col, ascending=False)
        df_plot = df_plot.head(20)      # always cap at top 20 for readability
        fig = px.bar(
            df_plot,
            x=x_col,
            y=y_col,
            color=color_col,
            title=title,
            text_auto=".2s",            # concise auto-formatted labels
        )
        fig.update_traces(textposition="outside")

    elif chart_type == "pie":
        fig = px.pie(
            df,
            names=x_col,
            values=y_col,
            title=title,
            hole=0.35,                  # donut style — more modern look
        )

    elif chart_type == "scatter":
        fig = px.scatter(
            df,
            x=x_col,
            y=y_col,
            color=color_col,
            title=title,
        )

    else:
        fig = go.Figure()

    # Consistent styling across all chart types
    fig.update_layout(
        template=_PLOTLY_TEMPLATE,
        font=dict(family="Inter, Arial, sans-serif", size=13),
        title_font=dict(size=16, color="#1f2937"),
        margin=dict(t=60, b=40, l=40, r=40),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    return fig


# ── Column Validation ─────────────────────────────────────────────────────

def _validate_decision(decision: ChartDecision, df: pd.DataFrame) -> bool:
    """
    Guard against LLM hallucinating column names that don't exist.
    Returns True if the decision is safe to use.
    """
    if decision.chart_type == "none":
        return True

    valid_cols = set(df.columns)

    if decision.x_col not in valid_cols:
        logger.warning(f"[VISUALIZER] x_col {decision.x_col!r} not in data columns.")
        return False

    if decision.y_col not in valid_cols:
        logger.warning(f"[VISUALIZER] y_col {decision.y_col!r} not in data columns.")
        return False

    if decision.color_col and decision.color_col not in valid_cols:
        logger.warning(
            f"[VISUALIZER] color_col {decision.color_col!r} not found — clearing it."
        )
        decision.color_col = None   # safe to clear; doesn't break the chart

    return True


# ── Node ──────────────────────────────────────────────────────────────────

def visualizer_agent_node(state: AnalystState) -> dict:
    """
    LangGraph node — Visualizer Sub-Agent.

    Reads:  state["result_csv_path"], state["result_types_path"],
            state["user_query"], state["row_count"]

    Writes: state["visualization_json"] (Plotly JSON string, or None)
            state["viz_chart_type"]     ("bar", "line", "scatter", "pie", "none")

    Fully non-fatal — if any step fails, returns viz_chart_type="none" and
    visualization_json=None so the UI gracefully degrades to text-only.
    """
    csv_path   = state.get("result_csv_path")
    types_path = state.get("result_types_path")
    row_count  = state.get("row_count", 0)
    user_query = state.get("user_query", "")

    logger.info(f"[VISUALIZER] Processing {row_count} rows for visualization.")

    _no_viz = {"visualization_json": None, "viz_chart_type": "none"}

    # Early exit: no data to visualise
    if not csv_path or row_count == 0:
        logger.info("[VISUALIZER] No data — skipping visualization.")
        return _no_viz

    try:
        # 1. Load companion type map (for accurate dtype labels)
        type_map: dict[str, str] = {}
        if types_path:
            try:
                with open(types_path, "r", encoding="utf-8") as f:
                    type_map = json.load(f)
            except Exception as e:
                logger.warning(f"[VISUALIZER] Could not load types.json: {e}")

        # 2. Load CSV
        df = pd.read_csv(csv_path)

        # 3. Build column context for the LLM
        col_context = _build_column_context(df, type_map)

        # 4. Ask the LLM for a chart decision
        decision = _ask_llm_for_chart(user_query, col_context)

        if decision.chart_type == "none":
            logger.info("[VISUALIZER] LLM decided: no chart appropriate.")
            return _no_viz

        # 5. Validate column names (guard against hallucination)
        if not _validate_decision(decision, df):
            logger.warning("[VISUALIZER] Invalid column names in LLM decision — skipping chart.")
            return _no_viz

        # 6. Build Plotly figure
        fig = _build_figure(df, decision)

        # 7. Serialise to JSON string for Gradio
        viz_json = fig.to_json()
        logger.info(f"[VISUALIZER] Figure serialised ({len(viz_json)} chars).")

        return {
            "visualization_json": viz_json,
            "viz_chart_type":     decision.chart_type,
        }

    except Exception as e:
        logger.error(f"[VISUALIZER] Failed (non-fatal): {e}", exc_info=True)
        return _no_viz
