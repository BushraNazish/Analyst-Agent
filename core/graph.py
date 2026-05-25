"""
LangGraph Graph Assembly — core/graph.py
==========================================
Wires all nodes into a complete StateGraph and compiles it into a runnable
callable. Import `compiled_graph` from this module in app.py.

Full topology:

  START
    │
    ▼
  classifier
    ├─ "metadata" ──► metadata_resolver ──────────────────────────────────┐
    │                                                                      │
    └─ "data" ──► schema_selector                                          │
                      │  ╠═ is_error ──► error_handler ──► END             │
                      ▼                                                    │
                  join_resolver                                            │
                      │                                                    │
                      ▼                                                    │
                  sql_generator                                            │
                      │  ╠═ is_error ──► error_handler ──► END             │
                      ▼                                                    │
                  sql_executor ─── route_after_execution ───┐              │
                      ▲               │                     │              │
                      │          "sql_corrector"            │              │
                  sql_corrector ──────┘                     │              │
                                                   "phase3" │              │
                                                       fan_out             │
                                                      ╱       ╲            │
                                            response_agent  visualizer     │
                                                      ╲       ╱            │
                                                followup_generator ◄───────┘
                                                       │
                                                      END

Early-exit routing:
  - schema_selector failure   → error_handler (skips SQL pipeline)
  - sql_generator failure     → error_handler (skips executor)
  - error_handler             → END (no follow-ups for hard failures)

Low-confidence routing:
  - classifier confidence < 0.6 → clarify_node → followup_generator → END
"""

from langgraph.graph import StateGraph, START, END

from core.state import AnalystState

# ── Node imports ───────────────────────────────────────────────────────────
from core.nodes.classifier_node       import classifier_node
from core.nodes.metadata_resolver_node import metadata_resolver_node
from core.nodes.schema_selector_node  import schema_selector_node
from core.nodes.join_resolver_node    import join_resolver_node
from core.nodes.sql_generator_node    import sql_generator_node
from core.nodes.sql_executor_node     import sql_executor_node, route_after_execution
from core.nodes.sql_corrector_node    import sql_corrector_node
from core.nodes.error_handler_node    import error_handler_node
from core.nodes.followup_node         import followup_node
from core.nodes.clarify_node          import clarify_node, LOW_CONFIDENCE_THRESHOLD
from core.agents.response_agent       import response_agent_node
from core.agents.visualizer_agent     import visualizer_agent_node
from core.logger import setup_logger

logger = setup_logger("GRAPH")


# ── Routing helpers ────────────────────────────────────────────────────────

def route_classifier(state: AnalystState) -> str:
    """
    Route based on classifier output.

    If confidence is below LOW_CONFIDENCE_THRESHOLD the query is ambiguous —
    route to clarify_node instead of proceeding on an uncertain path.
    """
    if (state.get("classification_confidence") or 1.0) < LOW_CONFIDENCE_THRESHOLD:
        return "clarify"
    return state.get("query_type") or "data"


def route_after_schema(state: AnalystState) -> str:
    """
    Early exit if Schema Selector failed (BigQuery unreachable, empty table, etc.).
    Avoids running the entire SQL pipeline on a bad schema.
    """
    if state.get("is_error"):
        return "error_handler"
    return "join_resolver"


def route_after_sql_generator(state: AnalystState) -> str:
    """
    Early exit if SQL Generator failed to produce a query.
    Avoids entering the executor/corrector loop with None SQL.
    """
    if state.get("is_error") or not state.get("generated_sql"):
        return "error_handler"
    return "sql_executor"


def fan_out_node(state: AnalystState) -> dict:
    """
    Pass-through node that enables LangGraph parallel fan-out.

    LangGraph runs all outgoing edges from this node concurrently:
        fan_out → response_agent   (parallel)
        fan_out → visualizer_agent (parallel)

    Both write to different state keys so there is no conflict.
    LangGraph merges their outputs before continuing to followup_generator.
    """
    return {}   # no state change — just a branch point


# ── Graph Builder ──────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """Assemble and compile the full Text-to-SQL StateGraph."""
    builder = StateGraph(AnalystState)

    # ── Register nodes ─────────────────────────────────────────────────────
    builder.add_node("classifier",         classifier_node)
    builder.add_node("clarify",            clarify_node)
    builder.add_node("metadata_resolver",  metadata_resolver_node)
    builder.add_node("schema_selector",    schema_selector_node)
    builder.add_node("join_resolver",      join_resolver_node)
    builder.add_node("sql_generator",      sql_generator_node)
    builder.add_node("sql_executor",       sql_executor_node)
    builder.add_node("sql_corrector",      sql_corrector_node)
    builder.add_node("error_handler",      error_handler_node)
    builder.add_node("fan_out",            fan_out_node)
    builder.add_node("response_agent",     response_agent_node)
    builder.add_node("visualizer_agent",   visualizer_agent_node)
    builder.add_node("followup_generator", followup_node)

    # ── Entry point ────────────────────────────────────────────────────────
    builder.add_edge(START, "classifier")

    # ── Classifier → clarify, metadata, or data path ──────────────────────
    builder.add_conditional_edges(
        "classifier",
        route_classifier,
        {
            "clarify":  "clarify",
            "metadata": "metadata_resolver",
            "data":     "schema_selector",
        },
    )

    # ── Clarify path: low-confidence → clarify → followup ─────────────────
    builder.add_edge("clarify", "followup_generator")

    # ── Metadata path ──────────────────────────────────────────────────────
    builder.add_edge("metadata_resolver", "followup_generator")

    # ── Data path: schema → join → SQL ────────────────────────────────────
    builder.add_conditional_edges(
        "schema_selector",
        route_after_schema,
        {
            "join_resolver": "join_resolver",
            "error_handler": "error_handler",
        },
    )
    builder.add_edge("join_resolver", "sql_generator")

    builder.add_conditional_edges(
        "sql_generator",
        route_after_sql_generator,
        {
            "sql_executor":  "sql_executor",
            "error_handler": "error_handler",
        },
    )

    # ── Self-correction loop ───────────────────────────────────────────────
    # route_after_execution is imported from sql_executor_node:
    #   "phase3"        → fan_out  (success)
    #   "sql_corrector" → sql_corrector → sql_executor  (retry)
    #   "error_handler" → error_handler  (retries exhausted)
    builder.add_conditional_edges(
        "sql_executor",
        route_after_execution,
        {
            "phase3":        "fan_out",
            "sql_corrector": "sql_corrector",
            "error_handler": "error_handler",
        },
    )
    builder.add_edge("sql_corrector", "sql_executor")

    # ── Error terminal ─────────────────────────────────────────────────────
    builder.add_edge("error_handler", END)

    # ── Fan-out: success → parallel sub-agents ─────────────────────────────
    builder.add_edge("fan_out", "response_agent")
    builder.add_edge("fan_out", "visualizer_agent")

    # ── Fan-in: both sub-agents → follow-up generator ─────────────────────
    # LangGraph waits for BOTH to complete before running followup_generator
    builder.add_edge("response_agent",   "followup_generator")
    builder.add_edge("visualizer_agent", "followup_generator")

    # ── Terminal ───────────────────────────────────────────────────────────
    builder.add_edge("followup_generator", END)

    return builder.compile()


# ── Module-level compiled graph (imported by app.py) ──────────────────────
logger.info("Compiling LangGraph StateGraph...")
compiled_graph = build_graph()
logger.info("Graph compiled successfully.")
