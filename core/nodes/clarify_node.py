"""
Node 2b — Clarify Node (low-confidence path)
=============================================
Triggered when the Query Classifier returns a confidence score below the
LOW_CONFIDENCE_THRESHOLD (0.6). Instead of silently proceeding on an
uncertain classification, this node returns a user-facing clarification
message explaining the ambiguity and suggesting how to rephrase.

The node then routes to followup_generator so the user always receives
3 suggested questions they can click to immediately re-run the pipeline
with a clearer query.

Flow:
  classifier (confidence < 0.6)
      │
      ▼
  clarify_node  → returns clarification message
      │
      ▼
  followup_generator → 3 rephrase suggestions → END

State fields written:
  - metadata_response : str  — the clarification message (reuses metadata
                               display slot so app.py renders it correctly)
  - final_response    : str  — same value (marks the pipeline as complete)
"""

from core.state import AnalystState
from core.logger import setup_logger

logger = setup_logger("CLARIFY")

LOW_CONFIDENCE_THRESHOLD = 0.6


def clarify_node(state: AnalystState) -> dict:
    """
    LangGraph node — Clarify (low-confidence fallback).

    Reads:  state["classification_confidence"]
            state["classification_reasoning"]
            state["query_type"]  (the LLM's uncertain pick)

    Writes: state["metadata_response"]  — clarification message for display
            state["final_response"]     — same (marks end of this path)
            state["query_type"]         — forced to "metadata" so app.py
                                          renders the metadata_response field
    """
    confidence = state.get("classification_confidence") or 0.0
    reasoning  = state.get("classification_reasoning") or ""
    llm_pick   = state.get("query_type") or "data"

    logger.info(
        f"[CLARIFY] Low-confidence classification "
        f"(confidence={confidence:.2f}, llm_pick={llm_pick!r}). "
        "Returning clarification message."
    )

    msg = (
        f"⚠️ **I'm not quite sure how to interpret your question** "
        f"(confidence: {confidence:.0%}).\n\n"
    )

    if reasoning:
        msg += f"_{reasoning}_\n\n"

    msg += (
        "Could you rephrase to help me give you a more accurate answer?\n\n"
        "**If you want to explore data**, try:\n"
        "- *\"Show me the top 5 product categories by revenue\"*\n"
        "- *\"What is the average delivery time by state?\"*\n"
        "- *\"How many orders were placed in 2018?\"*\n\n"
        "**If you want to understand the schema**, try:\n"
        "- *\"What does the `review_score` column mean?\"*\n"
        "- *\"Describe the orders table and its columns\"*\n"
        "- *\"What tables are available in the database?\"*"
    )

    return {
        "metadata_response": msg,
        "final_response":    msg,
        # Force query_type to "metadata" so app.py reads metadata_response
        "query_type":        "metadata",
    }
