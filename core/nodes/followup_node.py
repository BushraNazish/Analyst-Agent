"""
Node 9 — Follow-Up Generator
===============================
Generates 3 contextual follow-up questions after any pipeline completion.
Runs at the end of both the metadata path and the data (success) path.

Uses GPT-4o Mini — cheap and fast, this is simple text generation.
On failure → returns 3 sensible generic fallback questions.

State fields written:
  - follow_up_questions : list[str]  — always exactly 3 questions
"""

import re
from langchain_core.prompts import ChatPromptTemplate

from core.state import AnalystState
from core.clients import get_light_llm
from core.logger import setup_logger

logger = setup_logger("FOLLOWUP")

# Inline prompt — simple enough to not warrant a .md file
_SYSTEM_PROMPT = """You are a helpful assistant for a Text-to-SQL system built on the \
Olist Brazilian e-commerce database (9 tables: customers, orders, order_items, \
order_payments, order_reviews, products, sellers, geolocation, product_category_name_translation).

The user just asked a question and received an answer. Suggest exactly 3 follow-up \
questions they might want to explore next.

Rules:
1. All 3 questions must be answerable by the Olist database
2. Make each question a different angle: one drill-down, one broader context, one comparison
3. Keep questions specific, concise (under 15 words each)
4. Output ONLY the 3 numbered questions — no introduction, no explanation
5. Format: 1. <question>  2. <question>  3. <question>"""

_FALLBACK_QUESTIONS = [
    "Which product categories generate the highest total revenue?",
    "What is the average delivery time by customer state?",
    "Which sellers have the best average review scores?",
]


def _parse_questions(text: str) -> list[str]:
    """
    Extract exactly 3 questions from the LLM's numbered list output.
    Handles formats: '1. Q', '1) Q', '1 Q', lines without numbers, etc.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    questions: list[str] = []

    for line in lines:
        # Strip leading number and punctuation: "1. ", "1) ", "1 "
        q = re.sub(r"^\d+[\.\)\s]\s*", "", line).strip()
        if q and len(q) > 8:   # skip very short fragments
            questions.append(q)

    # Fill up to 3 if parsing extracted fewer
    while len(questions) < 3:
        questions.append(_FALLBACK_QUESTIONS[len(questions)])

    return questions[:3]


def followup_node(state: AnalystState) -> dict:
    """
    LangGraph node — Follow-Up Generator.

    Reads:  state["user_query"], state["query_type"],
            state["analytical_response"] or state["metadata_response"]

    Writes: state["follow_up_questions"]  — list of 3 strings

    Fallback: never raises; always returns 3 questions.
    """
    user_query  = state.get("user_query", "")
    query_type  = state.get("query_type", "data")

    # Use whichever response was generated
    if query_type == "metadata":
        response_ctx = (state.get("metadata_response") or "")[:400]
    else:
        response_ctx = (state.get("analytical_response") or "")[:400]

    logger.info("[FOLLOWUP] Generating 3 follow-up questions...")

    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", _SYSTEM_PROMPT),
            (
                "human",
                "User's question: {query}\n\n"
                "Answer summary: {response}\n\n"
                "Suggest 3 follow-up questions:",
            ),
        ])

        chain = prompt | get_light_llm()
        result = chain.invoke({"query": user_query, "response": response_ctx})
        questions = _parse_questions(result.content.strip())

        logger.info(f"[FOLLOWUP] Questions: {questions}")
        return {"follow_up_questions": questions}

    except Exception as e:
        logger.error(f"[FOLLOWUP] LLM failed (returning fallback): {e}")
        return {"follow_up_questions": list(_FALLBACK_QUESTIONS)}
