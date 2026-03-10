# TFT Meta Mind

A RAG-powered chatbot that provides real-time Teamfight Tactics meta insights, powered by daily data pipelines and Claude AI.

## Overview

TFT Meta Mind scrapes meta data from multiple sources (tactics.tools, Riot API, Twitter), converts it into natural language documents, stores them in a vector database, and serves answers through a conversational chatbot interface.

## Setup

1. Clone the repository
2. Create a virtual environment: `python -m venv .venv`
3. Activate: `.venv/Scripts/activate` (Windows) or `source .venv/bin/activate` (Unix)
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in your API keys
6. Install Playwright browsers: `playwright install chromium`

## Architecture

```
scraper/          - Data collection from tactics.tools, Riot API, Twitter
pipeline/         - Document generation and daily orchestration
rag/              - ChromaDB vector store for TFT knowledge
chatbot/          - RAG chatbot using Claude API
streamlit_app.py  - Streamlit web UI
utils/            - Shared utilities (Data Dragon ID translation)
data/raw/         - Raw scraped data (gitignored)
```

## Usage

**Run the chatbot UI:**
```bash
streamlit run streamlit_app.py
```

**Run the daily pipeline:**
```bash
python -m pipeline.daily_run
```
