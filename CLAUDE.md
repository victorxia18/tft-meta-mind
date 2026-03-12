# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TFT Meta Mind — a RAG-powered chatbot for real-time Teamfight Tactics meta insights. Combines daily data scraping pipelines with Gemini 2.5 Flash and ChromaDB to serve a Streamlit web interface. Deployed to AWS Lightsail via Docker Compose with GitHub Actions CI/CD.

Live at: https://tftmetamind.duckdns.org

## Commands

```bash
# Setup
python -m venv .venv && .venv/Scripts/activate  # Windows
pip install -r requirements.txt
playwright install chromium

# Run scraper
python -m scraper.tactics_tools
python -m scraper.tactics_tools --rank master --output-dir data/raw

# Run full pipeline (scrape + generate docs + ingest + YouTube docs + cleanup)
python -m pipeline.daily_run --once

# Run pipeline subsets
python -m pipeline.daily_run --scrape-only
python -m pipeline.daily_run --ingest-only

# Process YouTube videos locally (saves doc JSONs to data/youtube_docs/)
python -m pipeline.daily_run --youtube-file config/youtube_sources.txt

# Run web UI
streamlit run streamlit_app.py
```

No test framework or linter is configured.

## Architecture

**Data flow:** Scrapers → Document Generator → ChromaDB Vector Store → Gemini RAG Chatbot → Streamlit UI

| Package | Role |
|---------|------|
| `scraper/` | Data collection: `tactics_tools.py` (Playwright XHR interception), `youtube.py` (transcript fetching + Gemini extraction) |
| `pipeline/` | Orchestration: `daily_run.py` (5-step pipeline with APScheduler + retry), `document_generator.py` (raw JSON → natural language docs) |
| `rag/` | `vector_store.py` — ChromaDB wrapper, chunks by `## ` headers, deterministic IDs for upsert |
| `chatbot/` | `app.py` — Gemini 2.5 Flash with keyword-based retrieval routing (unit vs comp vs strategy questions) |
| `utils/` | `data_dragon.py` — Riot Data Dragon CDN lookups with lazy loading and fallback to raw IDs |
| `streamlit_app.py` | Main web UI with custom CSS, stat cards, session-based chat |

### Daily Pipeline Steps (`daily_run.py`)

1. **[1/5] Scrape** — tactics.tools via Playwright (retry once after 30 min on failure)
2. **[2/5] Generate documents** — convert raw JSON to natural language
3. **[3/5] Ingest into ChromaDB** — chunk and embed documents
4. **[4/5] YouTube doc ingestion** — ingest pre-processed JSON files from `data/youtube_docs/`
5. **[5/5] Cleanup** — delete scrape files older than 7 days (skipped if ingestion failed)

### Scraped Data Structure

The raw JSON from tactics.tools has nested structure — **not** flat dicts:
- `comps["groups"]` — list of comp group objects (each has `full.comps`, stats, children)
- `units["units"]` — dict of unit IDs to unit data (101+ entries)
- `units["items"]` — list of item objects
- `units["traits"]` — dict of trait data

### Smart Retrieval Routing (`chatbot/app.py`)

The chatbot classifies questions by keyword regex and adjusts ChromaDB queries:
- **Unit questions** → prioritize `type: "unit_analysis"` chunks
- **Strategy questions** → prioritize `type: "video_guide"` chunks
- **Comp questions** → mix of `type: "meta_snapshot"` + `type: "video_guide"`
- **Ambiguous** → pure embedding similarity

### YouTube Ingestion Flow

YouTube transcript fetching is blocked from cloud provider IPs (AWS/Lightsail). The pipeline is split:

1. **Local machine:** Run `python -m pipeline.daily_run --youtube-file config/youtube_sources.txt` — fetches transcripts, processes with Gemini, saves document JSONs to `data/youtube_docs/`
2. **Commit & push:** The JSON files in `data/youtube_docs/` are git-tracked
3. **Lightsail pipeline:** Step [4/5] reads those JSON files and ingests into ChromaDB

Duplicate detection: `data/youtube_videos.json` (gitignored) tracks processed video IDs locally to avoid re-calling Gemini.

### Key Design Patterns

- **Deterministic chunk IDs:** `MD5(type + date + chunk_index)` — re-ingesting upserts instead of duplicating
- **Chunking by `## ` headers:** keeps each comp/unit together as one semantic chunk
- **Data Dragon lazy loading:** fetches Riot CDN once, caches in-memory, falls back to raw IDs on failure
- **Long video splitting:** YouTube transcripts >30 min are split into ~15-min chunks for Gemini processing

## Deployment

- **Platform:** AWS Lightsail (Docker Compose) at https://tftmetamind.duckdns.org
- **CI/CD:** GitHub Actions (`.github/workflows/deploy.yml`) — triggers on push to `master`
- **Containers:** `streamlit` (port 8501, 512MB) and `pipeline` (scheduled daily at 06:00 UTC, 1024MB)
- **Volumes:** `chroma_data`, `scrape_data`, `log_data` (persistent, shared between containers)
- **Dockerfile:** Based on `mcr.microsoft.com/playwright/python` image

## Environment

Requires `.env` file: `GEMINI_API_KEY` (required), `RIOT_API_KEY` (unused/Phase 2), `TWITTER_BEARER_TOKEN` (unused/Phase 3).

GitHub Secrets: `LIGHTSAIL_IP`, `LIGHTSAIL_SSH_KEY`, `GEMINI_API_KEY`.

## Key Files

- `tft_meta_mind_blueprint.md` — detailed technical spec and phased implementation plan
- `config/youtube_sources.txt` — YouTube URLs for scheduled ingestion
- `data/youtube_docs/` — pre-processed YouTube document JSONs (git-tracked)
- `data/raw/` — scraped JSON output (gitignored)
- `data/youtube_videos.json` — local YouTube duplicate tracking (gitignored)
- `chroma_db/` — vector store data (gitignored)
- `logs/pipeline.log` — pipeline execution log (DEBUG level)
