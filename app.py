"""
Gradio UI — app.py
===================
Single-page web interface for the Olist Text-to-SQL Analyst Agent.

Run with:
    python app.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import gradio as gr
import plotly.graph_objects as go

from core.graph import compiled_graph
from core.logger import setup_logger
from config.config_loader import get_config

logger = setup_logger("APP")


# ── Pipeline runner ────────────────────────────────────────────────────────

def run_pipeline(user_query: str):
    import html as html_mod

    if not user_query or not user_query.strip():
        return (
            "",
            gr.update(visible=False),
            gr.update(value="⚠️ Please enter a question.", visible=True),
            "",
            "",
        )

    logger.info(f"[APP] Running pipeline for: '{user_query.strip()[:80]}'")

    try:
        result = compiled_graph.invoke({"user_query": user_query.strip()})
    except Exception as e:
        logger.error(f"[APP] Pipeline error: {e}")
        import html
        error_msg = (
            f"❌ **Pipeline Error**\n\n"
            f"An unexpected error occurred: `{type(e).__name__}: {str(e)}`\n\n"
            "Please check the logs and try again."
        )
        return (
            "",
            gr.update(value=f"<div class='user-bubble'>{html.escape(user_query)}</div>", visible=True),
            gr.update(value=error_msg, visible=True),
            "",
            "",
        )

    query_type = result.get("query_type", "data")
    is_error   = result.get("is_error", False)

    sql      = result.get("generated_sql") or ""
    show_sql = bool(sql) and query_type == "data" and not is_error

    if is_error:
        response_md = result.get("final_response") or result.get("error_message") or "An error occurred."
    elif query_type == "metadata":
        response_md = result.get("metadata_response") or "No response generated."
    else:
        response_md = result.get("analytical_response") or "No response generated."

    viz_json   = result.get("visualization_json")
    show_chart = False
    if viz_json and not is_error:
        try:
            go.Figure(json.loads(viz_json))
            show_chart = True
        except Exception as e:
            logger.warning(f"[APP] Could not deserialise chart: {e}")

    follow_ups = result.get("follow_up_questions") or []
    while len(follow_ups) < 3:
        follow_ups.append("")
    q1, q2, q3   = follow_ups[0], follow_ups[1], follow_ups[2]
    show_followup = bool(q1 or q2 or q3)

    import html

    insights_html = ""
    if not is_error and query_type == "data":
        raw_insights = result.get("insights_response") or ""
        if raw_insights.strip():
            insights_html = f"<div class='insights-section'>\n\n**⚡ KEY INSIGHTS**\n\n{raw_insights}\n\n</div>"

    analysis_html = f"<div class='analysis-section'>\n\n**📋 ANALYSIS**\n\n{response_md}\n\n</div>"

    if show_followup:
        pass # Chips are now native Gradio buttons

    buttons_html = ""
    if show_sql or show_chart:
        buttons_html += "<hr class='resp-divider'>\n<div class='action-buttons'>\n"
        if show_sql:
            buttons_html += "<button class='action-btn' id='btn-view-sql'>📝 View SQL</button>\n"
        if show_chart:
            buttons_html += "<button class='action-btn' id='btn-view-chart'>📊 View Chart</button>\n"
        buttons_html += "</div>"

    final_response   = f"{insights_html}\n{analysis_html}\n{buttons_html}"
    user_bubble_html = f"<div class='user-bubble'>{html.escape(user_query)}</div>"

    logger.info(
        f"[APP] Done. type={query_type}, sql={show_sql}, "
        f"chart={show_chart}, followup={show_followup}"
    )

    return (
        "",
        gr.update(value=user_bubble_html, visible=True),
        gr.update(value=final_response,   visible=True),
        sql if show_sql else "",
        viz_json if show_chart else "",
        gr.update(visible=show_followup),
        gr.update(value=f"→ {q1}" if q1 else "", visible=bool(q1)),
        gr.update(value=f"→ {q2}" if q2 else "", visible=bool(q2)),
        gr.update(value=f"→ {q3}" if q3 else "", visible=bool(q3)),
        q1 or "",
        q2 or "",
        q3 or "",
    )


# ── SVG Icons ──────────────────────────────────────────────────────────────

_ARROW_SVG = (
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2.5" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<line x1="12" y1="19" x2="12" y2="5"/>'
    '<polyline points="5 12 12 5 19 12"/>'
    '</svg>'
)


# ── Custom CSS ────────────────────────────────────────────────────────────

_CSS = """
/* ══════════════════════════════════════════════════════════════════════════
   Olist Text-to-SQL Analyst  —  Ocean Neo-Brutalist UI  v5.0
   ══════════════════════════════════════════════════════════════════════════ */

:root {
    --ocean-deep:    #0c4a6e;
    --ocean-mid:     #0891b2;
    --ocean-light:   #bae6fd;
    --ocean-pale:    #f0f9ff;
    --ocean-bg:      #e0f2fe;
    --text-primary:  #0c1f2e;
    --text-secondary:#334155;
    --text-muted:    #64748b;
    --neo-shadow:    4px 4px 0px var(--ocean-deep);
    --neo-shadow-sm: 3px 3px 0px var(--ocean-deep);
    --neo-shadow-xs: 2px 2px 0px var(--ocean-deep);
}

body, .gradio-container {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    background: var(--ocean-bg) !important;
}

.gradio-container > .main,
.gradio-container > .main > .wrap {
    display: flex !important;
    flex-direction: column !important;
    min-height: 100vh !important;
    padding-bottom: 0 !important;
    max-width: 100% !important;
    gap: 0 !important;
}

/* ══ HEADER ════════════════════════════════════════════════════════════════ */

#header {
    background: linear-gradient(135deg, #0c4a6e 0%, #0891b2 55%, #38bdf8 100%);
    border-radius: 0 0 20px 20px;
    padding: 22px 40px 18px;
    color: white;
    border-bottom: 3px solid var(--ocean-deep);
    box-shadow: 0 4px 0px var(--ocean-deep), 0 8px 24px rgba(8,145,178,0.2);
}
#header h1 {
    font-size: 1.6rem; font-weight: 800; margin: 0 0 4px;
    letter-spacing: -0.02em; font-family: 'Plus Jakarta Sans', sans-serif;
}
#header p {
    font-size: 0.9rem; opacity: 0.88; margin: 0;
    font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 500;
}

/* ══ CHAT AREA ══════════════════════════════════════════════════════════════ */

#chat-area {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    flex: 0 !important;
    padding: 0 !important;
    min-height: 0 !important;
    overflow: hidden !important;
    gap: 0 !important;
}
body.active-mode #chat-area {
    flex: 1 !important;
    padding: 28px 10% 20px !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 16px !important;
    min-height: 200px !important;
    overflow: visible !important;
}

.user-bubble-wrapper > div.form,
.user-bubble-wrapper .block,
.user-bubble-wrapper > div {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 0 !important;
}

.user-bubble-wrapper .user-bubble {
    align-self: flex-end;
    background: white !important;
    color: black !important;
    border-radius: 20px 20px 4px 20px !important;
    border: 2px solid var(--ocean-deep) !important;
    box-shadow: var(--neo-shadow-sm) !important;
    padding: 16px 24px !important;
    max-width: 68% !important;
    font-size: 1.1rem !important;
    font-weight: 700 !important;
    line-height: 1.55 !important;
    word-break: break-word !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    margin-left: auto !important;
    width: fit-content !important;
    display: inline-block !important;
}

.response-card {
    background: white;
    border-radius: 4px 20px 20px 20px;
    border: 2px solid var(--ocean-light);
    box-shadow: var(--neo-shadow);
    padding: 28px 32px;
    animation: slideUp 0.35s cubic-bezier(0.16, 1, 0.3, 1);
    font-family: 'Plus Jakarta Sans', sans-serif;
}
@keyframes slideUp {
    from { opacity: 0; transform: translateY(18px); }
    to   { opacity: 1; transform: translateY(0); }
}

.resp-label {
    font-size: 0.68rem; font-weight: 800; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--ocean-mid);
    margin: 0 0 10px; display: flex; align-items: center; gap: 8px;
    border-left: 3px solid var(--ocean-mid); padding-left: 8px;
    font-family: 'Plus Jakarta Sans', sans-serif;
}

.insights-section {
    background: var(--ocean-pale);
    border: 2px solid var(--ocean-light);
    border-left: 4px solid var(--ocean-mid);
    border-radius: 0 12px 12px 0;
    box-shadow: 4px 4px 0px var(--ocean-light);
    padding: 18px 22px 18px 20px;
    margin-bottom: 24px;
    font-family: 'Plus Jakarta Sans', sans-serif;
}
.insights-section strong { color: var(--ocean-deep); font-weight: 700; }
.insights-section ul, .insights-section ol { margin: 0; padding-left: 20px; }
.insights-section li { color: var(--text-primary); font-size: 0.95rem; line-height: 1.65; margin-bottom: 6px; font-weight: 500; }
.insights-section li:last-child { margin-bottom: 0; }

.analysis-section { margin-bottom: 24px; font-family: 'Plus Jakarta Sans', sans-serif; }
.analysis-section ul, .analysis-section ol { margin: 0; padding-left: 20px; }
.analysis-section li { color: var(--text-secondary); font-size: 0.95rem; line-height: 1.7; margin-bottom: 8px; font-weight: 500; }
.analysis-section li:last-child { margin-bottom: 0; }
.analysis-section strong { color: var(--text-primary); font-weight: 700; }

.resp-divider { border: none; border-top: 2px solid var(--ocean-light); margin: 20px 0; }

#followup-container {
    margin-top: 30px !important; padding-top: 25px !important;
    border-top: 1px solid var(--ocean-light) !important;
    background: transparent !important;
    box-shadow: none !important;
}
.resp-label {
    font-size: 0.8rem; font-weight: 800; color: var(--ocean-mid);
    text-transform: uppercase; letter-spacing: 1px;
    margin-bottom: 15px; display: flex; align-items: center; gap: 8px;
}
#followup-chips { display: flex !important; flex-direction: column !important; gap: 10px !important; background: transparent !important; border: none !important; }
.followup-chip {
    background: white !important; border: 2px solid var(--ocean-deep) !important;
    border-radius: 12px !important; padding: 12px 18px !important;
    font-size: 0.95rem !important; font-weight: 600 !important; color: var(--text-primary) !important;
    cursor: pointer !important; box-shadow: var(--neo-shadow-xs) !important;
    transition: all 0.15s ease !important;
    display: block !important;
    text-align: left !important;
    white-space: normal !important;
    height: auto !important;
    min-height: unset !important;
}
.followup-chip:hover {
    background: var(--ocean-light) !important; transform: translate(2px, 2px) !important; box-shadow: none !important;
}

.action-buttons { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 4px; }
.action-btn {
    display: inline-flex; align-items: center; gap: 7px;
    background: white; border: 2px solid var(--ocean-deep); border-radius: 9px;
    box-shadow: var(--neo-shadow-xs); color: var(--ocean-deep);
    font-family: 'Plus Jakarta Sans', sans-serif; font-size: 0.855rem;
    font-weight: 600; padding: 8px 18px; cursor: pointer;
    transition: box-shadow 0.1s, transform 0.1s; white-space: nowrap;
}
.action-btn:hover { box-shadow: 1px 1px 0px var(--ocean-deep); transform: translate(2px, 2px); }

/* ══ LANDING ═════════════════════════════════════════════════════════════════ */

#landing-hero {
    flex: 1; display: flex; flex-direction: column;
    align-items: center; justify-content: flex-end;
    padding: 20px 20px 28px; text-align: center; min-height: 220px;
}
body.active-mode #landing-hero { display: none !important; }

#landing-tagline {
    font-size: 2rem; font-weight: 800; color: var(--ocean-deep);
    font-family: 'Plus Jakarta Sans', sans-serif;
    letter-spacing: -0.03em; line-height: 1.25;
}
#landing-tagline span { color: var(--ocean-mid); }

#landing-chips { display: flex; justify-content: center; padding: 14px 10% 32px; }
body.active-mode #landing-chips { display: none !important; }
#landing-chips-row { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; }
.landing-chip {
    display: inline-flex; align-items: center; gap: 8px;
    background: white; border: 2px solid var(--ocean-deep); border-radius: 10px;
    box-shadow: var(--neo-shadow-xs); color: var(--ocean-deep);
    font-family: 'Plus Jakarta Sans', sans-serif; font-size: 0.875rem;
    font-weight: 600; padding: 10px 18px; cursor: pointer;
    transition: box-shadow 0.1s, transform 0.1s; white-space: nowrap;
}
.landing-chip:hover { box-shadow: 1px 1px 0px var(--ocean-deep); transform: translate(1px, 1px); }

/* ══ INPUT BAR ═══════════════════════════════════════════════════════════════ */

body:not(.active-mode) #input-bar {
    background: white !important;
    border: 2px solid var(--ocean-deep) !important;
    border-radius: 16px !important;
    box-shadow: var(--neo-shadow) !important;
    max-width: 720px !important;
    width: calc(100% - 48px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
    padding: 5px 8px 5px 5px !important;
    position: relative !important;
    align-items: center !important;
}
#input-bar {
    position: relative !important;
}

body.active-mode #input-bar {
    background: white !important;
    border: 2px solid var(--ocean-deep) !important;
    border-radius: 16px !important;
    box-shadow: var(--neo-shadow), 0 8px 32px rgba(8,145,178,0.15) !important;
    max-width: 760px !important;
    width: calc(100% - 48px) !important;
    margin-left: auto !important;
    margin-right: auto !important;
    margin-bottom: 16px !important;
    padding: 5px 8px 5px 5px !important;
    position: sticky !important;
    bottom: 16px !important;
    z-index: 100 !important;
    align-items: center !important;
}

#input-bar > div {
    display: flex !important;
    align-items: center !important;
    width: 100% !important;
    padding: 0 !important;
    gap: 6px !important;
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}

#query-input textarea, #query-input input {
    font-size: 1rem !important; border: none !important;
    background: transparent !important; padding: 10px 8px !important;
    resize: none !important; min-height: 42px !important;
    max-height: 120px !important; box-shadow: none !important;
    outline: none !important; font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 500 !important; color: var(--text-primary) !important;
}
#query-input textarea::placeholder { color: var(--text-muted) !important; font-weight: 400 !important; }
#query-input, #query-input > label, #query-input > div,
#query-input .block, #query-input .wrap {
    border: none !important; background: transparent !important;
    box-shadow: none !important; padding: 0 !important; margin: 0 !important;
}

/* ── Custom HTML Arrow Button (Underneath) ── */
#arrow-btn-wrapper {
    position: static !important;
    width: 0 !important;
    height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}

#submit-arrow {
    position: absolute !important;
    right: 8px !important;
    top: 50% !important;
    transform: translateY(-50%) !important;
    z-index: 1 !important;
    pointer-events: none !important;
    background: var(--ocean-light);
    color: var(--ocean-deep);
    border: 2px solid var(--ocean-deep);
    border-radius: 50%;
    width: 44px;
    height: 44px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    padding: 0;
    transition: box-shadow 0.1s, transform 0.1s, background 0.15s;
}
#submit-arrow:hover:not(.loading) {
    box-shadow: 1px 1px 0px var(--ocean-deep);
    transform: translate(2px, 2px);
}
#submit-arrow.loading {
    background: #7dd3fc;
    border-color: var(--ocean-mid);
    box-shadow: 2px 2px 0px var(--ocean-mid);
    cursor: not-allowed;
    animation: pulse 1s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }

/* ── Native Gradio Button (Invisible Overlay) ── */
#overlay-submit-btn {
    position: absolute !important;
    right: 8px !important;
    top: 50% !important;
    transform: translateY(-50%) !important;
    width: 44px !important;
    height: 44px !important;
    z-index: 10 !important;
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    box-shadow: none !important;
    background: transparent !important;
}

#overlay-submit-btn > div,
#overlay-submit-btn button {
    position: absolute !important;
    top: 0 !important; 
    left: 0 !important;
    width: 100% !important; 
    height: 100% !important;
    transform: none !important; /* Fix double-transform bug! */
    opacity: 0 !important;
    cursor: pointer !important;
    margin: 0 !important; 
    padding: 0 !important;
    border: none !important; 
    box-shadow: none !important;
    background: transparent !important;
}

/* ══ MODALS ══════════════════════════════════════════════════════════════════ */

.modal-overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(12,31,46,0.6);
    backdrop-filter: blur(5px); -webkit-backdrop-filter: blur(5px);
    z-index: 10000; align-items: center; justify-content: center; padding: 24px;
}
.modal-overlay.open { display: flex; animation: fadeIn 0.2s ease; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.modal-dialog {
    background: white; border-radius: 18px;
    border: 2px solid var(--ocean-deep);
    box-shadow: 6px 6px 0px var(--ocean-deep);
    padding: 32px 36px; width: 92vw; max-width: 920px;
    max-height: 88vh; overflow-y: auto; position: relative;
    animation: modalIn 0.22s cubic-bezier(0.16, 1, 0.3, 1);
    font-family: 'Plus Jakarta Sans', sans-serif;
}
@keyframes modalIn {
    from { opacity: 0; transform: scale(0.96) translateY(8px); }
    to   { opacity: 1; transform: scale(1) translateY(0); }
}
.modal-close {
    position: absolute; top: 18px; right: 22px;
    background: var(--ocean-pale); border: 2px solid var(--ocean-deep);
    border-radius: 50%; width: 32px; height: 32px;
    font-size: 1.1rem; cursor: pointer; color: var(--ocean-deep);
    line-height: 28px; text-align: center;
    box-shadow: var(--neo-shadow-xs);
    transition: box-shadow 0.1s, transform 0.1s; font-weight: 700;
}
.modal-close:hover { box-shadow: 1px 1px 0px var(--ocean-deep); transform: translate(1px, 1px); }
.modal-title {
    font-size: 1.05rem; font-weight: 800; color: var(--ocean-deep);
    margin: 0 0 22px; padding-right: 40px;
    font-family: 'Plus Jakarta Sans', sans-serif;
}

.modal-sql-code {
    background: #0f172a; border-radius: 12px;
    border: 2px solid var(--ocean-deep);
    padding: 22px 24px; overflow-x: auto; position: relative;
}
.copy-sql-btn {
    position: absolute; top: 12px; right: 12px;
    background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.25);
    border-radius: 6px; color: #e2e8f0; padding: 4px 10px;
    font-size: 0.8rem; cursor: pointer; transition: background 0.15s;
    font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 500;
}
.copy-sql-btn:hover { background: rgba(255,255,255,0.22); color: white; }
.modal-sql-code pre { margin: 0; white-space: pre; }
.modal-sql-code code {
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    font-size: 0.9rem; color: #e2e8f0; line-height: 1.7;
}

#chart-modal-plot { width: 100%; min-height: 420px; }

/* ══ GRADIO CHROME CLEANUP ═══════════════════════════════════════════════════ */

footer { display: none !important; }

.hide-container > div.form {
    box-shadow: none !important; border: none !important;
    background: transparent !important;
}
"""


# ── Build UI ──────────────────────────────────────────────────────────────

def build_ui() -> tuple:

    _head_html = """
    <!-- Google Fonts -->
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,400;0,500;0,600;0,700;0,800;1,400&display=swap" rel="stylesheet">
    <!-- Plotly CDN -->
    <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
    <script>

    // ── State ────────────────────────────────────────────────────────────
    let isLandingMode = true;
    let isLoading     = false;

    // ── Landing → active layout transition ───────────────────────────────
    function activateMode() {
        if (!isLandingMode) return;
        document.body.classList.add('active-mode');
        isLandingMode = false;
    }
    window.activateMode = activateMode;

    // ── Set arrow to loading state ──────────────────────────────────
    function setLoading() {
        isLoading = true;
        const arrow = document.getElementById('submit-arrow');
        if (arrow) arrow.classList.add('loading');
    }

    // ── Reset arrow after pipeline completes ──────────────────────────
    function resetArrow() {
        isLoading = false;
        const arrow = document.getElementById('submit-arrow');
        if (arrow) arrow.classList.remove('loading');
    }

    // ── Called via Gradio js= BEFORE the Python pipeline fires ────────────
    // Receives and returns the query so Python gets the correct value.
    function onBeforeSubmit(query) {
        activateMode();
        if (!isLoading) setLoading();
        return query;
    }
    window.onBeforeSubmit = onBeforeSubmit;

    // ── Modal helpers ─────────────────────────────────────────────────────
    function openSqlModal() {
        const sqlInput = document.querySelector('#hidden-sql-state textarea');
        if (sqlInput) document.getElementById('sql-modal-code').textContent = sqlInput.value;
        document.getElementById('sql-modal').classList.add('open');
    }
    function openChartModal() {
        const chartInput = document.querySelector('#hidden-chart-state textarea');
        if (chartInput && chartInput.value) {
            try {
                const fig = JSON.parse(chartInput.value);
                Plotly.newPlot('chart-modal-plot', fig.data, fig.layout);
            } catch(e) { console.error('Chart parse error', e); }
        }
        document.getElementById('chart-modal').classList.add('open');
    }
    function closeModal(id) {
        document.getElementById(id).classList.remove('open');
    }
    function copySqlToClipboard() {
        const sql = document.getElementById('sql-modal-code').textContent;
        navigator.clipboard.writeText(sql).then(() => {
            const btn = document.querySelector('.copy-sql-btn');
            const orig = btn.innerHTML;
            btn.innerHTML = '✅ Copied!';
            setTimeout(() => { btn.innerHTML = orig; }, 2000);
        }).catch(err => console.error('Clipboard error', err));
    }
    window.openSqlModal       = openSqlModal;
    window.openChartModal     = openChartModal;
    window.closeModal         = closeModal;
    window.copySqlToClipboard = copySqlToClipboard;

    // ── DOM ready ─────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.modal-overlay').forEach(el =>
            el.addEventListener('click', e => { if (e.target === el) closeModal(el.id); })
        );

        // MutationObserver on chat-area: reset arrow when pipeline response arrives
        const setupObserver = () => {
            const chatArea = document.getElementById('chat-area');
            if (!chatArea) { setTimeout(setupObserver, 300); return; }
            new MutationObserver(() => {
                if (isLoading) resetArrow();
            }).observe(chatArea, { childList: true, subtree: true, characterData: true });
        };
        setupObserver();
    });

    // ── Escape closes modals ──────────────────────────────────────────────
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape')
            document.querySelectorAll('.modal-overlay.open').forEach(el => closeModal(el.id));
    });

    // ── Enter key in textbox: trigger visual transitions (activateMode + setLoading) ──
    // Fires in capture phase so it runs BEFORE Gradio's own Enter handler.
    // No e.preventDefault() — Gradio's native submit event must fire untouched.
    document.addEventListener('keydown', e => {
        if (e.key === 'Enter'
                && !e.shiftKey
                && e.target.closest('#query-input')
                && !isLoading) {
            activateMode();
            setLoading();
        }
    }, true);

    // ── Global click delegation (SQL/Chart buttons, overlay, follow-up chips) ──────
    document.addEventListener('click', e => {
        // Intercept native overlay clicks to add visual effects
        if (e.target.closest('#overlay-submit-btn')) {
            if (!isLoading) {
                setLoading();
                activateMode();
            }
        } else if (e.target.closest('#btn-view-sql')) {
            openSqlModal();
        } else if (e.target.closest('#btn-view-chart')) {
            openChartModal();
        } else {
            const chip = e.target.closest('.followup-chip');
            if (chip) {
                const rawText = chip.getAttribute('data-question') || (chip.textContent || chip.innerText).replace('→', '').trim();
                if (rawText) submitFollowUp(rawText);
            }
        }
    }, true);

    </script>
    """

    with gr.Blocks(title="Olist Text-to-SQL Analyst") as demo:

        # ── Header ──────────────────────────────────────────────────────────
        gr.HTML("""
        <div id="header">
          <h1>🔍 Olist Text-to-SQL Analyst</h1>
          <p>Ask any question about the Olist Brazilian e-commerce dataset in plain English.</p>
        </div>
        """)

        # ── Chat Area ────────────────────────────────────────────────────────
        with gr.Column(elem_id="chat-area"):
            user_bubble = gr.HTML(
                value="",
                visible=False,
                elem_classes=["user-bubble-wrapper"],
            )
            response_card = gr.Markdown(
                value="",
                visible=False,
                elem_classes=["response-card"],
            )
            
            with gr.Column(elem_id="followup-container", visible=False) as followup_container:
                gr.HTML("<div class='resp-label'>💬 Suggested Follow-Up Questions</div>")
                with gr.Column(elem_id="followup-chips"):
                    fup1 = gr.Button("", elem_classes=["followup-chip"], visible=False)
                    fup2 = gr.Button("", elem_classes=["followup-chip"], visible=False)
                    fup3 = gr.Button("", elem_classes=["followup-chip"], visible=False)
                    fup1_state = gr.State("")
                    fup2_state = gr.State("")
                    fup3_state = gr.State("")

        # ── Landing Hero ─────────────────────────────────────────────────────
        gr.HTML("""
        <div id="landing-hero">
            <div id="landing-tagline">
                What would you like to<br><span>know about Olist?</span>
            </div>
        </div>
        """)

        # ── Input Bar ────────────────────────────────────────────────────────
        with gr.Row(elem_id="input-bar"):
            query_input = gr.Textbox(
                placeholder="Ask anything about the Olist dataset...",
                label="",
                lines=1,
                elem_id="query-input",
                show_label=False,
                scale=9,
                container=False,
            )
            # HTML arrow button — pure SVG, underneath the native button overlay
            gr.HTML(
                f'<button type="button" id="submit-arrow" title="Submit query">{_ARROW_SVG}</button>',
                elem_id="arrow-btn-wrapper",
            )
            
            # Native Gradio button — invisible overlay directly on top of the arrow
            submit_btn = gr.Button("", elem_id="overlay-submit-btn")

        # ── Landing Chips ────────────────────────────────────────────────────
        with gr.Column(elem_id="landing-chips"):
            with gr.Row(elem_id="landing-chips-row"):
                chip1 = gr.Button("📦 Top 5 revenue categories", elem_classes=["landing-chip"])
                chip2 = gr.Button("📊 Monthly order trends 2018", elem_classes=["landing-chip"])
                chip3 = gr.Button("❓ What does seller_id mean?", elem_classes=["landing-chip"])

        # ── Hidden States (for SQL/chart modals & follow-up routing) ─────────
        gr.HTML("<style>#hidden-states { display: none !important; }</style>")
        with gr.Column(elem_id="hidden-states"):
            sql_state   = gr.Textbox(elem_id="hidden-sql-state")
            chart_state = gr.Textbox(elem_id="hidden-chart-state")

        # ── Modals ───────────────────────────────────────────────────────────
        gr.HTML("""
        <div id="sql-modal" class="modal-overlay">
            <div class="modal-dialog">
                <button class="modal-close" onclick="closeModal('sql-modal')">×</button>
                <div class="modal-title">📝 Generated SQL</div>
                <div class="modal-sql-code">
                    <button class="copy-sql-btn" onclick="copySqlToClipboard()">📋 Copy</button>
                    <pre><code id="sql-modal-code"></code></pre>
                </div>
            </div>
        </div>

        <div id="chart-modal" class="modal-overlay">
            <div class="modal-dialog">
                <button class="modal-close" onclick="closeModal('chart-modal')">×</button>
                <div class="modal-title">📊 Visualisation</div>
                <div id="chart-modal-plot"></div>
            </div>
        </div>
        """)

        # ── Event Wiring ─────────────────────────────────────────────────────
        all_outputs = [
            query_input,         # [0] cleared input
            user_bubble,         # [1] user bubble
            response_card,       # [2] response card
            sql_state,           # [3] sql for modal
            chart_state,         # [4] chart json for modal
            followup_container,  # [5] follow-up section visibility
            fup1,                # [6] follow-up chip 1
            fup2,                # [7] follow-up chip 2
            fup3,                # [8] follow-up chip 3
            fup1_state,          # [9] raw q1
            fup2_state,          # [10] raw q2
            fup3_state,          # [11] raw q3
        ]

        # No js= — Gradio natively reads the textbox value and passes it to Python.
        # Visual side-effects (activateMode, setLoading) are handled by:
        #   • Enter key path: keydown capture listener in _head_html
        #   • Arrow click path: click delegation on overlay-submit-btn
        query_input.submit(
            fn=run_pipeline,
            inputs=[query_input],
            outputs=all_outputs,
            show_progress="hidden",
        )
        submit_btn.click(
            fn=run_pipeline,
            inputs=[query_input],
            outputs=all_outputs,
            show_progress="hidden",
        )

        # Native buttons for Landing Chips
        _chip_js = "() => { window.activateMode && window.activateMode(); window.setLoading && window.setLoading(); }"
        
        chip1.click(
            fn=lambda: "Which 5 product categories generated the highest total revenue?",
            outputs=[query_input],
            js=_chip_js,
            show_progress="hidden"
        ).then(fn=run_pipeline, inputs=[query_input], outputs=all_outputs, show_progress="hidden")
        
        chip2.click(
            fn=lambda: "Show me the monthly order volume trends throughout 2018",
            outputs=[query_input],
            js=_chip_js,
            show_progress="hidden"
        ).then(fn=run_pipeline, inputs=[query_input], outputs=all_outputs, show_progress="hidden")
        
        chip3.click(
            fn=lambda: "What does the seller_id column represent in the database?",
            outputs=[query_input],
            js=_chip_js,
            show_progress="hidden"
        ).then(fn=run_pipeline, inputs=[query_input], outputs=all_outputs, show_progress="hidden")

        # Native buttons for Follow-up Chips
        fup1.click(
            fn=lambda q: q,
            inputs=[fup1_state],
            outputs=[query_input],
            js=_chip_js,
            show_progress="hidden"
        ).then(fn=run_pipeline, inputs=[query_input], outputs=all_outputs, show_progress="hidden")
        
        fup2.click(
            fn=lambda q: q,
            inputs=[fup2_state],
            outputs=[query_input],
            js=_chip_js,
            show_progress="hidden"
        ).then(fn=run_pipeline, inputs=[query_input], outputs=all_outputs, show_progress="hidden")
        
        fup3.click(
            fn=lambda q: q,
            inputs=[fup3_state],
            outputs=[query_input],
            js=_chip_js,
            show_progress="hidden"
        ).then(fn=run_pipeline, inputs=[query_input], outputs=all_outputs, show_progress="hidden")

    return demo, _head_html


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    port  = int(get_config("GRADIO_SERVER_PORT") or 7860)
    share = str(get_config("GRADIO_SHARE") or "false").lower() == "true"

    logger.info(f"Starting Gradio on port {port} (share={share})")
    app, _head = build_ui()
    app.launch(
        server_port=port,
        share=share,
        show_error=True,
        css=_CSS,
        theme=gr.themes.Ocean(),
        head=_head,
    )
