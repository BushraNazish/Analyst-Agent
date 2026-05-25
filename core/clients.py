"""
Shared Client Factories — core/clients.py
==========================================
Centralised factory functions for all external clients used across nodes.
Import from here instead of duplicating connection logic in every node.

Clients provided:
  - get_bq_client()    → google.cloud.bigquery.Client
  - get_openai_client()→ openai.OpenAI
  - get_pg_conn()      → psycopg2 synchronous connection
  - get_sql_llm()      → ChatOpenAI (gpt-5.1  — heavy: SQL generation + NL response)
  - get_medium_llm()   → ChatOpenAI (gpt-5-mini — medium: reserved for future use)
  - get_light_llm()    → ChatOpenAI (gpt-4o-mini — extra light: routing / followup / chart)
"""

import os
import yaml
from pathlib import Path

from config.config_loader import get_config
from core.logger import setup_logger

logger = setup_logger("CLIENTS")

# ── Resolve paths relative to project root ────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
_LLM_CONFIG_PATH = _PROJECT_ROOT / "config" / "llm-config.yaml"


def _load_llm_config() -> dict:
    with open(_LLM_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── BigQuery ───────────────────────────────────────────────────────────────

def get_bq_client():
    """Return an authenticated BigQuery client using the service account JSON."""
    from google.cloud import bigquery

    creds_path = get_config("GOOGLE_APPLICATION_CREDENTIALS")
    project_id = get_config("GCP_PROJECT_ID")

    if not os.path.isabs(creds_path):
        creds_path = str(_PROJECT_ROOT / creds_path)

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
    client = bigquery.Client(project=project_id)
    logger.debug(f"BigQuery client ready (project: {project_id})")
    return client


# ── OpenAI ─────────────────────────────────────────────────────────────────

def get_openai_client():
    """Return an OpenAI client for embeddings and chat."""
    from openai import OpenAI

    api_key = get_config("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in agent_config.yaml")
    return OpenAI(api_key=api_key)


# ── PostgreSQL (synchronous — used in setup scripts and resolver nodes) ────

def get_pg_conn():
    """Return a synchronous psycopg2 connection to the Olist PostgreSQL DB."""
    import psycopg2

    conn = psycopg2.connect(
        dbname=get_config("POSTGRES_DB"),
        user=get_config("POSTGRES_USER"),
        password=get_config("POSTGRES_PASSWORD"),
        host=get_config("POSTGRES_HOST"),
        port=int(get_config("POSTGRES_PORT", 5432)),
    )
    logger.debug("PostgreSQL connection established.")
    return conn


# ── LangChain LLMs ─────────────────────────────────────────────────────────

def get_sql_llm():
    """
    Return ChatOpenAI configured for SQL generation (GPT-5.1).
    temperature=0 for deterministic SQL output.
    """
    from langchain_openai import ChatOpenAI

    cfg = _load_llm_config()["llm_model"]
    api_key = get_config("OPENAI_API_KEY")

    llm = ChatOpenAI(
        model=cfg["default_model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        max_retries=cfg["max_retries"],
        api_key=api_key,
    )
    logger.debug(f"SQL LLM ready: {cfg['default_model']}")
    return llm


def get_medium_llm():
    """
    Return ChatOpenAI configured for medium tasks (gpt-5-mini).
    Reserved tier — not yet assigned to any node. Available for future use.
    """
    from langchain_openai import ChatOpenAI

    cfg     = _load_llm_config()["medium_llm"]
    api_key = get_config("OPENAI_API_KEY")

    llm = ChatOpenAI(
        model=cfg["default_model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        max_retries=cfg["max_retries"],
        api_key=api_key,
    )
    logger.debug(f"Medium LLM ready: {cfg['default_model']}")
    return llm


def get_light_llm():
    """
    Return ChatOpenAI configured for extra-light tasks (gpt-4o-mini).
    Used for: query routing (classifier), follow-up generation, chart type selection.
    """
    from langchain_openai import ChatOpenAI

    cfg     = _load_llm_config()["light_llm"]
    api_key = get_config("OPENAI_API_KEY")

    llm = ChatOpenAI(
        model=cfg["default_model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        max_retries=cfg["max_retries"],
        api_key=api_key,
    )
    logger.debug(f"Light LLM ready: {cfg['default_model']}")
    return llm
