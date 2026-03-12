"""Streamlit web UI for TFT Meta Mind chatbot.

Provides a chat interface where users can ask questions about
the current TFT meta and receive AI-powered answers.

Usage:
    streamlit run streamlit_app.py
"""

import glob
import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from chatbot.app import TFTChatbot
from pipeline.document_generator import TFTDocumentGenerator
from rag.vector_store import TFTVectorStore
from utils.data_dragon import DataDragon

WELCOME_MESSAGE = (
    "Hey! I'm **TFT Meta Mind** — your AI-powered TFT analyst. "
    "Ask me anything about the current meta: best comps, unit tier lists, "
    "item recommendations, or how to climb. What do you want to know?"
)

STARTER_QUESTIONS = [
    "What are the strongest comps right now?",
    "What items should I build on Yone?",
    "Which units are S-tier this patch?",
    "What comps are most consistent for top 4?",
]

# ── Custom CSS ──────────────────────────────────────────

CUSTOM_CSS = """
<style>
/* Accent bar at top */
.stApp::before {
    content: "";
    display: block;
    width: 100%;
    height: 4px;
    background: linear-gradient(90deg, #C89B3C 0%, #0AC8B9 50%, #C89B3C 100%);
    position: fixed;
    top: 0;
    left: 0;
    z-index: 9999;
}

/* Hide default footer and hamburger */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* Sidebar styling */
section[data-testid="stSidebar"] {
    background-color: #0e1117;
}
section[data-testid="stSidebar"] .stMarkdown {
    color: #c9d1d9;
}

/* Chat message styling */
.stChatMessage[data-testid="chat-message-assistant"] {
    background-color: #e8f4f8;
    border-radius: 12px;
    padding: 4px 8px;
}
.stChatMessage[data-testid="chat-message-user"] {
    background-color: #f0f0f0;
    border-radius: 12px;
    padding: 4px 8px;
}

/* Larger chat text */
.stChatMessage p {
    font-size: 1.05rem;
    line-height: 1.6;
}

/* Stat card styling */
div[data-testid="stMetric"] {
    background-color: #f8f9fa;
    border: 1px solid #e1e4e8;
    border-radius: 12px;
    padding: 16px 20px;
    text-align: center;
}
div[data-testid="stMetric"] label {
    color: #6c757d;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    color: #0AC8B9;
    font-size: 2rem;
    font-weight: 700;
}

/* Starter question buttons — pill style */
.starter-btn button {
    border-radius: 20px !important;
    border: 1px solid #C89B3C !important;
    color: #C89B3C !important;
    background-color: transparent !important;
    font-size: 0.9rem !important;
    padding: 6px 18px !important;
    white-space: nowrap !important;
    transition: all 0.2s ease !important;
}
.starter-btn button:hover {
    background-color: #C89B3C !important;
    color: #fff !important;
}

/* Title styling */
.main-title {
    font-size: 2.2rem;
    font-weight: 800;
    color: #C89B3C;
    margin-bottom: 0;
    line-height: 1.2;
}
.subtitle {
    font-size: 1.05rem;
    color: #8b949e;
    margin-top: 0;
    margin-bottom: 1.5rem;
}

/* Sidebar section headers */
.sidebar-header {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #C89B3C;
    font-weight: 600;
    margin-top: 1rem;
    margin-bottom: 0.5rem;
}

/* Powered-by text */
.powered-by {
    font-size: 0.75rem;
    color: #6c757d;
    line-height: 1.5;
}
</style>
"""


@st.cache_resource
def init_vector_store():
    return TFTVectorStore()


@st.cache_resource
def init_chatbot():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    store = init_vector_store()
    return TFTChatbot(gemini_api_key=api_key, vector_store=store)


def get_latest_scrape_date() -> str | None:
    files = sorted(glob.glob("data/raw/tactics_tools_*.json"))
    if not files:
        return None
    name = Path(files[-1]).stem
    return name.replace("tactics_tools_", "")


def get_youtube_video_count() -> int:
    youtube_docs_dir = Path("data/youtube_docs")
    if not youtube_docs_dir.exists():
        return 0
    return len(list(youtube_docs_dir.glob("*.json")))


def get_comp_and_unit_counts() -> tuple[int, int]:
    """Get comp group and unit counts from the latest scrape."""
    files = sorted(glob.glob("data/raw/tactics_tools_*.json"))
    if not files:
        return 0, 0
    try:
        with open(files[-1]) as f:
            raw = json.load(f)
        comps_data = raw.get("comps", {})
        units_data = raw.get("units", {})
        # Comps are stored as groups in comps["groups"]
        comps = len(comps_data.get("groups", []))
        # Units are stored as a dict in units["units"]
        units = len(units_data.get("units", {}))
        return comps, units
    except (json.JSONDecodeError, OSError):
        return 0, 0


def reingest_data():
    """Re-run document generation and ingestion from the latest scrape."""
    files = sorted(glob.glob("data/raw/tactics_tools_*.json"))
    if not files:
        st.error("No scraped data found in data/raw/.")
        return

    with open(files[-1]) as f:
        raw = json.load(f)

    dd = DataDragon()
    gen = TFTDocumentGenerator(data_dragon=dd)
    store = init_vector_store()

    meta_doc = gen.generate_meta_snapshot(raw.get("comps", {}), raw.get("units", {}))
    unit_doc = gen.generate_unit_document(raw.get("units", {}))
    store.ingest_document(meta_doc)
    store.ingest_document(unit_doc)

    st.success(f"Re-ingested from {Path(files[-1]).name}")


def process_question(question: str):
    """Process a user question through the chatbot."""
    st.session_state.messages.append({"role": "user", "content": question})

    bot = init_chatbot()

    # Build chat history for multi-turn (exclude current question)
    chat_history = []
    for msg in st.session_state.messages[:-1]:
        chat_history.append({"role": msg["role"], "content": msg["content"]})

    with st.chat_message("assistant", avatar="🧠"):
        with st.spinner("Searching TFT knowledge base..."):
            response = bot.ask(
                question,
                chat_history=chat_history if chat_history else None,
            )
        st.write(response)

    st.session_state.messages.append({"role": "assistant", "content": response})


# ── Page config ──────────────────────────────────────────

st.set_page_config(
    page_title="TFT Meta Mind",
    page_icon="🧠",
    layout="wide",
)

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────

store = init_vector_store()
stats = store.get_stats()
scrape_date = get_latest_scrape_date()
video_count = get_youtube_video_count()

with st.sidebar:
    st.markdown("# 🧠 TFT Meta Mind")

    # Data Sources section
    st.markdown('<p class="sidebar-header">Data Sources</p>', unsafe_allow_html=True)

    if scrape_date:
        st.markdown(f"📊 **Last scrape:** {scrape_date}")
    else:
        st.warning("No scraped data found.")

    st.markdown(f"📹 **Videos ingested:** {video_count}")
    st.markdown(f"🧩 **Knowledge chunks:** {stats['total_chunks']}")

    st.markdown("---")

    # Ingested videos list
    youtube_docs_dir = Path("data/youtube_docs")
    youtube_doc_files = sorted(youtube_docs_dir.glob("*.json")) if youtube_docs_dir.exists() else []
    if youtube_doc_files:
        with st.expander(f"📹 Ingested Videos ({len(youtube_doc_files)})"):
            for doc_path in youtube_doc_files:
                doc = json.load(open(doc_path, encoding="utf-8"))
                meta = doc.get("metadata", {})
                video_id = doc_path.stem
                title = meta.get("video_title", video_id)
                channel = meta.get("channel", "")
                url = meta.get("video_url", f"https://www.youtube.com/watch?v={video_id}")
                st.caption(f"[{title}]({url})\n{channel}")

    st.markdown("---")

    # Admin section
    with st.expander("⚙️ Admin Tools"):
        if st.button("🔄 Re-ingest Data"):
            reingest_data()
            st.rerun()

    # Powered by
    st.markdown("---")
    st.markdown(
        '<p class="powered-by">'
        "Data from tactics.tools<br>"
        "Videos from YouTube<br>"
        "AI by Google Gemini"
        "</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "[📂 GitHub Repository](https://github.com/victorxia18/tft-meta-mind)",
    )


# ── Check prerequisites ─────────────────────────────────

bot = init_chatbot()

if bot is None:
    st.error(
        "GEMINI_API_KEY not found. "
        "Add it to your .env file and restart."
    )
    st.stop()

if stats["total_chunks"] == 0:
    st.warning(
        "Knowledge base is empty. Run the scraper and ingestion pipeline first:\n\n"
        "```bash\n"
        "python -m scraper.tactics_tools\n"
        "python -m pipeline.daily_run --once\n"
        "```\n\n"
        'Then click "Re-ingest Data" in the Admin Tools section.'
    )
    st.stop()

# ── Header ───────────────────────────────────────────────

st.markdown('<p class="main-title">TFT Meta Mind</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitle">AI-powered TFT meta analyst — powered by real-time data</p>',
    unsafe_allow_html=True,
)

# Stat cards
comp_count, unit_count = get_comp_and_unit_counts()
col1, col2, col3, col4 = st.columns(4)
col1.metric("Knowledge Chunks", stats["total_chunks"])
col2.metric("Comps Tracked", comp_count)
col3.metric("Units Analyzed", unit_count)
col4.metric("Videos Ingested", video_count)

st.markdown("---")

# ── Chat interface ───────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display conversation history
for msg in st.session_state.messages:
    avatar = "🧠" if msg["role"] == "assistant" else None
    with st.chat_message(msg["role"], avatar=avatar):
        st.write(msg["content"])

# Welcome message and starter questions (only when no messages yet)
if not st.session_state.messages:
    with st.chat_message("assistant", avatar="🧠"):
        st.write(WELCOME_MESSAGE)

    cols = st.columns(len(STARTER_QUESTIONS))
    for i, question in enumerate(STARTER_QUESTIONS):
        with cols[i]:
            st.markdown('<div class="starter-btn">', unsafe_allow_html=True)
            if st.button(question, key=f"starter_{i}"):
                process_question(question)
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

# Chat input
if prompt := st.chat_input("Ask about the TFT meta..."):
    with st.chat_message("user"):
        st.write(prompt)
    process_question(prompt)
    st.rerun()
