# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TFT Meta Mind — a RAG-powered chatbot for real-time Teamfight Tactics meta insights. Combines daily data scraping pipelines with Claude API and ChromaDB to serve a Streamlit web interface.

## Commands

```bash
# Setup
python -m venv .venv && .venv/Scripts/activate  # Windows
pip install -r requirements.txt
playwright install chromium

# Run scraper (only implemented module so far)
python -m scraper.tactics_tools
python -m scraper.tactics_tools --rank master --output-dir data/raw

# Run web UI (when implemented)
streamlit run streamlit_app.py
```

No test framework, linter, or CI/CD is configured yet.

## Architecture

**Data flow:** Scrapers → Document Generator → ChromaDB Vector Store → Claude RAG Chatbot → Streamlit UI

| Package | Role | Status |
|---------|------|--------|
| `scraper/` | Data collection (tactics.tools, Riot API, Twitter) | `tactics_tools.py` implemented; others are stubs |
| `pipeline/` | Orchestration: `daily_run.py` (APScheduler cron), `document_generator.py` (raw JSON → natural language docs) | Stubs |
| `rag/` | `vector_store.py` — ChromaDB wrapper for semantic search with metadata filtering | Stub |
| `chatbot/` | `app.py` — Claude API integration with RAG context injection | Stub |
| `utils/` | `data_dragon.py` — Riot Data Dragon CDN lookups for ID→name translation | Stub |
| `streamlit_app.py` | Main web UI entry point | Stub |

**Key patterns in `scraper/tactics_tools.py`:**
- Async Playwright with `_next/data` response interception (tactics.tools is a Next.js app)
- Captures `pageProps.statsData` from intercepted JSON responses
- Outputs dated JSON to `data/raw/` with metadata envelope
- CLI via `argparse` with `--rank` and `--output-dir` flags

## Environment

Requires `.env` file (see `.env.example`): `ANTHROPIC_API_KEY`, `RIOT_API_KEY`, `TWITTER_BEARER_TOKEN`.

## Key Files

- `tft_meta_mind_blueprint.md` — detailed technical spec and phased implementation plan
- `data/raw/` — scraped JSON output (gitignored)
- `chroma_db/` — vector store data (gitignored)
