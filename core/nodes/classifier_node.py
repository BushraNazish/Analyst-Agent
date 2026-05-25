"""
Node 1 — Query Classifier
===========================
Classifies the user query as 'metadata' or 'data' using GPT-4o Mini
with structured output (Pydantic model → guaranteed schema).

Flow:
  user_query
      │
      ▼
  GPT-4o Mini (structured output)
      │
      ├── query_type = "metadata"  → routes to metadata_resolver_node
      ├── query_type = "data"      → routes to schema_selector_node
      └── confidence < 0.6         → graph can route to clarification

State fields populated:
  - query_type                : Literal["metadata", "data"]
  - classification_confidence : float (0.0 – 1.0)
  - classification_reasoning  : str
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from core.state import AnalystState
from core.clients import get_light_llm
from core.logger import setup_logger

logger = setup_logger("CLASSIFIER")

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "classifier_prompt.md"


# ── Pydantic output schema ─────────────────────────────────────────────────

class ClassificationOutput(BaseModel):
    """Structured output guaranteed by GPT-4o Mini's with_structured_output()."""

    query_type: Literal["metadata", "data"] = Field(
        description=(
            "'metadata' for schema/definition questions, "
            "'data' for actual data retrieval questions"
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="How confident you are in the classification (0.0 = uncertain, 1.0 = certain)",
    )
    reasoning: str = Field(
        description="One sentence explaining why you chose this category"
    )


# ── Helpers ────────────────────────────────────────────────────────────────

def _load_system_prompt() -> str:
    with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _build_chain():
    """Build the LangChain chain: prompt | GPT-4o Mini with structured output."""
    system_prompt = _load_system_prompt()

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "Classify this query:\n\n{query}"),
    ])

    llm = get_light_llm().with_structured_output(ClassificationOutput)
    return prompt | llm


# ── Node ───────────────────────────────────────────────────────────────────

def classifier_node(state: AnalystState) -> dict:
    """
    LangGraph node — Query Classifier.

    Reads:  state["user_query"]
    Writes: state["query_type"], state["classification_confidence"],
            state["classification_reasoning"]

    Fallback: on any LLM failure → defaults to "data" (safer — avoids silently
    dropping valid data queries into the metadata path).
    """
    user_query = state["user_query"]
    logger.info(f"[CLASSIFIER] Classifying: '{user_query[:80]}...' ")

    try:
        chain = _build_chain()
        result: ClassificationOutput = chain.invoke({"query": user_query})

        logger.info(
            f"[CLASSIFIER] → type={result.query_type} | "
            f"confidence={result.confidence:.2f} | "
            f"reason={result.reasoning[:70]}"
        )

        return {
            "query_type":                result.query_type,
            "classification_confidence": result.confidence,
            "classification_reasoning":  result.reasoning,
        }

    except Exception as e:
        # Hard fallback — never crash the pipeline
        logger.error(f"[CLASSIFIER] LLM failure, defaulting to 'data': {e}")
        return {
            "query_type":                "data",
            "classification_confidence": 0.5,
            "classification_reasoning":  (
                f"Classifier failed ({type(e).__name__}: {str(e)[:60]}), "
                "defaulted to 'data' as safe fallback."
            ),
        }
