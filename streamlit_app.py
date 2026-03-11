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
    "Hey! I'm TFT Meta Mind. Ask me anything about the current meta "
    "— best comps, unit tier lists, item recommendations, or how to climb. "
    "What do you want to know?"
)

STARTER_QUESTIONS = [
    "What are the strongest comps right now?",
    "What items should I build on Fizz?",
    "Which units are S-tier this patch?",
    "I keep going bot 4, what comps are most consistent for top 4?",
]


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


def reingest_data():
    """Re-run document generation and ingestion from the latest scrape."""
    files = sorted(glob.glob("data/raw/tactics_tools_*.json"))
    if not files:
        st.sidebar.error("No scraped data found in data/raw/.")
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

    st.sidebar.success(f"Re-ingested from {Path(files[-1]).name}")


def process_question(question: str):
    """Process a user question through the chatbot."""
    st.session_state.messages.append({"role": "user", "content": question})

    bot = init_chatbot()

    # Build chat history for multi-turn (exclude current question)
    chat_history = []
    for msg in st.session_state.messages[:-1]:
        chat_history.append({"role": msg["role"], "content": msg["content"]})

    with st.chat_message("assistant"):
        with st.spinner("Searching TFT knowledge base..."):
            response = bot.ask(
                question,
                chat_history=chat_history if chat_history else None,
            )
        st.write(response)

    st.session_state.messages.append({"role": "assistant", "content": response})


# ── Page config ──────────────────────────────────────────

st.set_page_config(page_title="TFT Meta Mind", page_icon="\U0001f3ae")

# ── Sidebar ──────────────────────────────────────────────

st.sidebar.title("\U0001f3ae TFT Meta Mind")

store = init_vector_store()
stats = store.get_stats()
st.sidebar.metric("Knowledge Chunks", stats["total_chunks"])

scrape_date = get_latest_scrape_date()
if scrape_date:
    st.sidebar.text(f"Latest scrape: {scrape_date}")
else:
    st.sidebar.warning("No scraped data found.")

if st.sidebar.button("Re-ingest Data"):
    reingest_data()
    st.rerun()

# ── YouTube video ingestion ─────────────────────────────
st.sidebar.markdown("---")
st.sidebar.subheader("Add YouTube Video")

youtube_url = st.sidebar.text_input(
    "YouTube URL",
    placeholder="Paste YouTube URL...",
    label_visibility="collapsed",
)

if st.sidebar.button("Ingest Video"):
    if youtube_url.strip():
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            st.sidebar.error("GEMINI_API_KEY not set in .env")
        else:
            with st.sidebar:
                with st.spinner("Processing video transcript..."):
                    try:
                        from scraper.youtube import TFTYouTubeScraper, ingest_youtube_video
                        scraper = TFTYouTubeScraper(gemini_api_key=api_key)
                        result = ingest_youtube_video(youtube_url, scraper)

                        if result["success"]:
                            st.success(f"Ingested: {result['title']}")
                            st.rerun()
                        else:
                            st.error(f"Failed: {result['error']}")
                    except Exception as e:
                        st.error(f"Error: {e}")
    else:
        st.sidebar.warning("Please paste a YouTube URL first.")

# Show ingested videos
from scraper.youtube import load_youtube_videos
ingested_videos = load_youtube_videos()
if ingested_videos:
    st.sidebar.markdown(f"**Ingested Videos ({len(ingested_videos)})**")
    for vid in ingested_videos:
        st.sidebar.caption(
            f"[{vid.get('title', vid.get('video_id', '?'))}]({vid.get('url', '')})\n"
            f"{vid.get('channel', '')} \u2022 {vid.get('date_ingested', '')}"
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
        "python -m pipeline.document_generator  # to verify\n"
        "```\n\n"
        'Then click "Re-ingest Data" in the sidebar.'
    )
    st.stop()

# ── Chat interface ───────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display conversation history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Welcome message and starter questions (only when no messages yet)
if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.write(WELCOME_MESSAGE)

    cols = st.columns(2)
    for i, question in enumerate(STARTER_QUESTIONS):
        if cols[i % 2].button(question, key=f"starter_{i}"):
            process_question(question)
            st.rerun()

# Chat input
if prompt := st.chat_input("Ask about the TFT meta..."):
    with st.chat_message("user"):
        st.write(prompt)
    process_question(prompt)
    st.rerun()
