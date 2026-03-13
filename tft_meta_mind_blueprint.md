# TFT Meta Mind — System Architecture

A RAG-powered chatbot for real-time Teamfight Tactics meta insights. Combines daily data scraping pipelines with Gemini 2.5 Flash and ChromaDB to serve a Streamlit web interface.

**Live:** https://tftmetamind.duckdns.org

---

## System Diagram

```
                          ┌──────────────────────────────┐
                          │        DATA SOURCES           │
                          ├───────────────┬──────────────┤
                          │ tactics.tools │   YouTube     │
                          │  (web scrape) │ (transcripts) │
                          └───────┬───────┴──────┬───────┘
                                  │              │
                     ┌────────────┘              └─────────────┐
                     ▼                                         ▼
         ┌───────────────────────┐              ┌──────────────────────────┐
         │  Playwright Scraper   │              │  YouTube Scraper         │
         │  (XHR interception)   │              │  (transcript API +       │
         │                       │              │   Gemini extraction)     │
         │  Runs on Lightsail    │              │  Runs LOCALLY only       │
         └───────────┬───────────┘              └────────────┬─────────────┘
                     │                                       │
                     ▼                                       ▼
         ┌───────────────────────┐              ┌──────────────────────────┐
         │  data/raw/            │              │  data/youtube_docs/      │
         │  tactics_tools_       │              │  {video_id}.json         │
         │  YYYY-MM-DD.json      │              │  (git-tracked)           │
         │  (gitignored)         │              └────────────┬─────────────┘
         └───────────┬───────────┘                           │
                     │                                       │
                     ▼                                       │
         ┌───────────────────────┐                           │
         │  Document Generator   │                           │
         │  + Data Dragon        │                           │
         │  (ID → name lookup)   │                           │
         └───────────┬───────────┘                           │
                     │                                       │
                     │  ┌────────────────────────────────────┘
                     │  │
                     ▼  ▼
         ┌─────────────────────────────────────┐
         │  ChromaDB Vector Store              │
         │  ─────────────────────              │
         │  Collection: "tft_knowledge"        │
         │  Embedding: all-MiniLM-L6-v2        │
         │  Chunking: ## header splitting      │
         │  IDs: MD5(type_date_src_idx)        │
         │                                     │
         │  Document types:                    │
         │   • meta_snapshot  (comp rankings)  │
         │   • unit_analysis  (unit tier list) │
         │   • video_guide    (YouTube advice) │
         └──────────────┬──────────────────────┘
                        │
                        ▼
         ┌─────────────────────────────────────┐
         │  Chatbot (Gemini 2.5 Flash)         │
         │  ─────────────────────              │
         │  1. Classify question (regex)       │
         │  2. Route retrieval by doc type     │
         │  3. Inject context + chat history   │
         │  4. Generate grounded answer        │
         └──────────────┬──────────────────────┘
                        │
                        ▼
         ┌─────────────────────────────────────┐
         │  Streamlit Web UI                   │
         │  ─────────────────                  │
         │  Session-based multi-turn chat      │
         │  Stat cards, starter questions      │
         │  Admin: YouTube doc review + edit   │
         │  Re-ingest button                   │
         └─────────────────────────────────────┘
```

---

## Daily Pipeline

Orchestrated by `pipeline/daily_run.py` via APScheduler. Runs immediately on container startup, then daily at **06:00 UTC**. The pipeline runs inside the `pipeline` Docker container on Lightsail.

```
┌─────────────────────────────────────────────────────────────┐
│  [1/5] SCRAPE                                               │
│  Playwright launches headless Chromium, navigates to        │
│  tactics.tools /units and /team-compositions, evaluates     │
│  __NEXT_DATA__ script to extract pageProps JSON.            │
│                                                             │
│  Rank filter: Grand Master (default), configurable.        │
│  Output: data/raw/tactics_tools_YYYY-MM-DD.json            │
│                                                             │
│  On failure: retries once after 30 minutes.                │
├─────────────────────────────────────────────────────────────┤
│  [2/5] GENERATE DOCUMENTS                                   │
│  Loads latest scrape JSON. Initializes Data Dragon for      │
│  ID→name translation (graceful fallback to raw IDs).        │
│                                                             │
│  Produces two documents:                                    │
│   • meta_snapshot — top 10 comps by avg placement           │
│   • unit_analysis — all units grouped into S/A/B/C tiers   │
├─────────────────────────────────────────────────────────────┤
│  [3/5] INGEST INTO CHROMADB                                 │
│  Chunks each document by ## headers, generates              │
│  deterministic IDs, upserts into the vector store.          │
├─────────────────────────────────────────────────────────────┤
│  [4/5] INGEST YOUTUBE DOCS                                  │
│  Reads pre-processed JSON files from data/youtube_docs/.    │
│  Each file is a complete RAG document ready for ingestion.  │
│  (These were generated locally and pushed via git.)         │
├─────────────────────────────────────────────────────────────┤
│  [5/5] CLEANUP                                              │
│  Deletes scrape files older than 7 days.                    │
│  Skipped if ingestion failed (preserves data for retry).    │
└─────────────────────────────────────────────────────────────┘
```

**Failure isolation:** If scrape fails, ingestion is skipped. If ingestion fails, cleanup is skipped. Each step logs results and the pipeline prints a summary with checkmarks/Xs.

**CLI modes:**
```bash
python -m pipeline.daily_run              # run once (default)
python -m pipeline.daily_run --schedule   # APScheduler daemon
python -m pipeline.daily_run --scrape-only
python -m pipeline.daily_run --ingest-only
python -m pipeline.daily_run --youtube URL1 URL2
python -m pipeline.daily_run --youtube-file config/youtube_sources.txt
```

---

## Module Reference

### `scraper/tactics_tools.py` — Web Scraper

Launches headless Chromium via Playwright to scrape tactics.tools. Instead of parsing rendered HTML or intercepting XHR, it evaluates the `__NEXT_DATA__` script tag to extract Next.js server-side props directly as JSON.

**Pages scraped:**

| URL | Data Key | pageProps Field |
|-----|----------|-----------------|
| `/units` | `units` | `statsData` |
| `/team-compositions` | `comps` | `initialData` |

**Output data shape:**
```
{
  "metadata": { "scraped_at", "rank", "source" },
  "comps": {
    "groups": [                       # list of comp group objects
      {
        "full": {
          "comps": [{ "count", "place", "top4", "win", "units" }],
          "carryUnits": [[champion_id, carry_score], ...],
          "traits": [[trait_id, tier, count, avg_place], ...]
        }
      }
    ]
  },
  "units": {
    "units": {                        # dict, NOT list
      "unit_id": {
        "count", "place", "top4", "won",
        "topItems", "starCount", "starPlace", "starTop4", "starWon"
      }
    },
    "totalEntries": int
  }
}
```

**Key detail:** The raw data is deeply nested — `comps["groups"]` is a list of group objects where each group has a `full` property containing comp variants, carry units, and traits. `units["units"]` is a dict keyed by unit ID, not a flat list.

---

### `scraper/youtube.py` — YouTube Transcript Processor

Fetches video transcripts via `youtube-transcript-api` and sends them to Gemini 2.5 Flash for structured extraction of actionable TFT advice.

**Why this runs locally:** YouTube blocks transcript API requests from cloud provider IPs (AWS/Lightsail). The workaround is a two-stage pipeline:

1. **Local machine:** Fetch transcript, process with Gemini, save document JSON to `data/youtube_docs/{video_id}.json`
2. **Git push** the JSON files (this directory is git-tracked)
3. **Lightsail pipeline** step [4/5] reads and ingests those JSONs — no YouTube access needed

**Long video handling:** Videos over 30 minutes are split into ~15-minute chunks using timestamped transcript data. Each chunk is sent to Gemini separately (with 2s sleep between calls for rate limiting), and results are concatenated.

**Duplicate detection:** `data/youtube_videos.json` (gitignored) tracks processed video IDs locally. The pipeline checks this before calling Gemini to avoid wasting API tokens on already-processed videos.

**Gemini extraction prompt:** Instructs the model to extract only actionable advice — comp recommendations, item priorities, openers, transition paths, strategy tips. Ignores intros, outros, ads, and personal anecdotes. Explicitly prohibits augment mentions (the system has no augment data to cross-reference).

---

### `pipeline/document_generator.py` — Document Generation

Converts raw scraped data into natural-language markdown documents suitable for RAG ingestion. Optionally uses Data Dragon for ID-to-name translation (falls back to raw IDs if unavailable).

**Document types produced:**

| Method | Type | Source | Content |
|--------|------|--------|---------|
| `generate_meta_snapshot()` | `meta_snapshot` | tactics_tools | Top 10 comps ranked by avg placement, with stats, core units, key traits |
| `generate_unit_document()` | `unit_analysis` | tactics_tools | All units grouped into S/A/B/C tiers with placement stats, items, 3-star data |
| `generate_youtube_document()` | `video_guide` | youtube | Gemini-extracted advice wrapped with video title, channel, date, URL header |

**Comp name inference:** Since tactics.tools doesn't provide comp names, `_infer_comp_name()` constructs readable names from the top 2 carry units and the most prominent trait (e.g., "Fizz / Yone").

**Unit tier thresholds:**

| Tier | Avg Placement |
|------|---------------|
| S | < 4.0 |
| A | 4.0 – 4.3 |
| B | 4.3 – 4.6 |
| C | >= 4.6 |

**Output format:** Each method returns `{"text": str, "metadata": dict}` where text is structured markdown with `##` and `###` headers (important for downstream chunking) and metadata includes `source`, `type`, `date`, and document-specific fields.

---

### `rag/vector_store.py` — Vector Store

ChromaDB wrapper with header-based chunking and deterministic upsert semantics.

**Collection:** `tft_knowledge` with `DefaultEmbeddingFunction` (all-MiniLM-L6-v2, runs locally, no API key).

**Chunking strategy (two-tier):**

```
Input document
    │
    ├─ Split on "## " headers (primary)
    │
    ├─ For each chunk > 1500 chars:
    │     └─ Sub-split on "### " headers
    │        └─ Prepend parent "## " header to each sub-chunk
    │           (preserves section context)
    │
    └─ Result: list of semantically coherent chunks
```

This keeps each comp or unit as a single chunk when possible. A comp section with detailed item builds and transitions might exceed 1500 chars and get split into sub-sections, but each sub-chunk retains the parent header so the embedding captures which comp it belongs to.

**Deterministic IDs:**
```python
raw_id = f"{type}_{date}_{video_id}_{chunk_index}"
chunk_id = MD5(raw_id)
```

The `video_id` component (empty string for non-YouTube docs) prevents ID collisions when multiple videos are ingested on the same date. Re-ingesting the same document produces the same IDs, so ChromaDB upserts instead of duplicating.

**Query interface:**
```python
store.query(
    question="what comps are strong?",
    n_results=5,
    where={"type": "meta_snapshot"}  # optional metadata filter
)
# Returns: [{"text", "metadata", "distance"}, ...]
```

---

### `chatbot/app.py` — RAG Chatbot

Gemini 2.5 Flash chatbot with keyword-based retrieval routing and multi-turn conversation support.

**Question classification:** Three regex pattern sets detect question intent:

| Category | Example Triggers | Retrieval Strategy |
|----------|------------------|--------------------|
| **Unit** | "items on", "build", "3-star", "tier list", "s-tier" | 3 `unit_analysis` + 2 general |
| **Comp** | "comp", "meta", "strongest", "what to play", "top 4" | 2 `meta_snapshot` + 2 `video_guide` + 1 general |
| **Strategy** | "opener", "transition", "pivot", "early/mid/late game", "econ" | 3 `video_guide` + 2 general |
| **Ambiguous** | anything else | 5 general (pure embedding similarity) |

Retrieval results are deduplicated by chunk text before being injected into the prompt.

**Prompt construction:**
```
System: Role definition, formatting rules, stat citation guidelines,
        no augment mentions, actionable advice emphasis

User:   [Context block with source/type/date headers per chunk]
        Player's Question: {question}
```

**Multi-turn:** Chat history is passed as a list of `{"role", "content"}` dicts. The chatbot converts `"assistant"` role to `"model"` for Gemini's expected format and prepends the history before the current question.

**System prompt constraints:**
- Cite specific stats (placement, top 4 rate, win rate, items)
- Mention YouTube source channels by name
- Acknowledge when context is insufficient
- No augment recommendations (data unavailable)
- Use TFT-native language (top 4 = good, first = win)
- Keep responses concise and actionable

---

### `utils/data_dragon.py` — Riot Data Dragon

Lazy-loaded wrapper for Riot's static data CDN. Translates internal IDs (e.g., `TFT16_Fizz`) to human-readable names (e.g., `Fizz`).

**Lazy loading:** Each data category (`champions`, `items`, `traits`) is fetched from the CDN on first access and cached in memory. This avoids unnecessary HTTP calls if the pipeline doesn't need name translation.

**Fallback chain:**
1. Data Dragon lookup by ID
2. Manual override map (e.g., `TFT16_AnnieTibbers` → `Annie & Tibbers`)
3. Raw ID as-is

**Error handling:** All HTTP calls use a 10s timeout. If Data Dragon initialization fails entirely (CDN down, network issue), the pipeline continues with raw IDs — the document generator and chatbot still function, just with less readable names.

---

### `streamlit_app.py` — Web Interface

Streamlit app with session-based chat, data overview, and admin tools.

**Layout:**

```
┌─────────────────────────────────────────────────────────────┐
│  SIDEBAR                          │  MAIN CONTENT           │
│  ───────                          │  ────────────           │
│  Logo + title                     │  Header                 │
│                                   │                         │
│  Data Sources:                    │  Stat Cards (4 cols):   │
│   • Last scrape date              │   Knowledge Chunks      │
│   • Video count                   │   Comps Tracked         │
│   • Knowledge chunks              │   Units Analyzed        │
│                                   │   Videos Ingested       │
│  ▸ Ingested Videos                │                         │
│    (expandable list with          │  Chat Interface:        │
│     title, channel, URL)          │   • Conversation        │
│                                   │     history with        │
│  ▸ Review YouTube Docs            │     avatars             │
│    (select, edit, save)           │   • Starter question    │
│                                   │     buttons (first      │
│  ▸ Admin Tools                    │     visit only)         │
│    [Re-ingest Data]               │   • Chat input bar      │
│                                   │                         │
│  Footer: credits + GitHub         │                         │
└─────────────────────────────────────────────────────────────┘
```

**Prerequisite checks:**
- Missing `GEMINI_API_KEY` → error message, `st.stop()`
- Empty knowledge base → warning with instructions to run the pipeline

**Caching:** Vector store and chatbot instances use `@st.cache_resource` so they persist across Streamlit reruns without reinitialization.

**Starter questions:** Four pre-built buttons shown only on first visit:
1. "What are the strongest comps right now?"
2. "What items should I build on Yone?"
3. "Which units are S-tier this patch?"
4. "What comps are most consistent for top 4?"

---

## Deployment

### Infrastructure

```
┌──────────────────────────────────────────────────────┐
│  AWS Lightsail Instance                              │
│                                                      │
│  ┌────────────────────┐  ┌────────────────────────┐  │
│  │  streamlit         │  │  pipeline              │  │
│  │  container         │  │  container             │  │
│  │  (512 MB)          │  │  (1024 MB)             │  │
│  │                    │  │                        │  │
│  │  Streamlit app     │  │  APScheduler daemon    │  │
│  │  Port 8501         │  │  Daily at 06:00 UTC    │  │
│  └────────┬───────────┘  └────────┬───────────────┘  │
│           │                       │                   │
│           └───────────┬───────────┘                   │
│                       │                               │
│           ┌───────────┴───────────┐                   │
│           │   Shared Volumes      │                   │
│           │   • chroma_data       │                   │
│           │   • scrape_data       │                   │
│           │   • log_data          │                   │
│           └───────────────────────┘                   │
│                                                      │
│  DNS: tftmetamind.duckdns.org                        │
└──────────────────────────────────────────────────────┘
```

Both containers share Docker volumes so the pipeline's ingestion and Streamlit's queries see the same ChromaDB data.

**Base image:** `mcr.microsoft.com/playwright/python:v1.51.0-noble` — includes Chromium runtime for the scraper. Runs as non-root `appuser` for security.

### CI/CD

```
Push to master → GitHub Actions → SSH to Lightsail →
  git pull → docker compose up -d --build → docker image prune
```

The workflow writes `GEMINI_API_KEY` from GitHub Secrets into `.env` on each deploy.

**GitHub Secrets required:** `LIGHTSAIL_IP`, `LIGHTSAIL_SSH_KEY`, `GEMINI_API_KEY`

---

## Project Structure

```
tft-meta-mind/
├── chatbot/
│   └── app.py                # Gemini 2.5 Flash RAG chatbot with keyword routing
├── scraper/
│   ├── tactics_tools.py      # Playwright scraper (Next.js pageProps extraction)
│   └── youtube.py            # YouTube transcript fetch + Gemini extraction
├── pipeline/
│   ├── daily_run.py          # 5-step pipeline orchestrator with APScheduler
│   └── document_generator.py # Raw JSON → markdown documents for RAG
├── rag/
│   └── vector_store.py       # ChromaDB wrapper (## header chunking, deterministic IDs)
├── utils/
│   └── data_dragon.py        # Riot Data Dragon CDN (lazy-loaded ID → name)
├── ui/
│   ├── components.py         # HTML renderers (header, welcome message)
│   └── styles.py             # Custom CSS
├── config/
│   └── youtube_sources.txt   # YouTube URLs for batch ingestion
├── data/
│   ├── raw/                  # Scraped JSON (gitignored, cleaned after 7 days)
│   └── youtube_docs/         # Pre-processed video JSONs (git-tracked)
├── assets/
│   └── pengu_knight.png      # Assistant avatar
├── streamlit_app.py          # Web UI entry point
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .github/workflows/
│   └── deploy.yml            # CI/CD: push to master → deploy to Lightsail
└── CLAUDE.md                 # Development reference
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `google-genai` | >= 1.0.0 | Gemini 2.5 Flash API client |
| `chromadb` | >= 0.5.0 | Vector database (includes all-MiniLM-L6-v2 embeddings) |
| `streamlit` | 1.55.0 | Web UI framework |
| `playwright` | >= 1.40.0 | Browser automation for tactics.tools scraping |
| `youtube-transcript-api` | >= 1.0.0 | YouTube transcript fetching |
| `requests` | >= 2.31.0 | HTTP client (Data Dragon, YouTube metadata) |
| `beautifulsoup4` | >= 4.12.0 | HTML parsing |
| `apscheduler` | >= 3.10.0 | Cron-like scheduling for daily pipeline |
| `python-dotenv` | >= 1.0.0 | Environment variable loading |

**Environment:** Requires `.env` with `GEMINI_API_KEY`.

---

## Key Design Decisions

### Header-based chunking over word-count chunking

Documents are split on `## ` markdown headers rather than by word count. This keeps each comp or unit as a single semantic chunk, which produces better retrieval results than arbitrary word-boundary splits. Oversized chunks (>1500 chars) are sub-split on `### ` headers with the parent `## ` header prepended for context.

### Keyword routing over embedding-only retrieval

Pure embedding similarity retrieval struggled with question types that have obvious intent (e.g., "what items on Fizz" clearly wants unit data, not comp rankings). Regex-based keyword classification routes to the appropriate document type first, then uses embedding similarity within that subset. Ambiguous questions still fall through to pure similarity.

### Deterministic chunk IDs for idempotent ingestion

Chunk IDs are `MD5(type_date_sourceId_index)`. Re-running the pipeline on the same data produces the same IDs, so ChromaDB upserts (updates) instead of creating duplicates. This makes the pipeline safe to re-run at any time without data cleanup.

### Two-stage YouTube pipeline

YouTube blocks transcript API requests from cloud IPs. Rather than using a proxy or residential IP, the pipeline splits YouTube processing into a local step (fetch + Gemini extraction → JSON) and a server step (ingest JSON). The JSON files in `data/youtube_docs/` are git-tracked to bridge the gap.

### Gemini 2.5 Flash over larger models

Flash provides sufficient quality for both transcript extraction and conversational RAG at significantly lower latency and cost. The 4096-token response limit keeps answers concise and actionable.

### No augment data

The system prompt explicitly prohibits augment recommendations. While tactics.tools provides augment data, the scraper currently only captures comp and unit pages. This is an intentional scope boundary to avoid giving advice without supporting data.

---

## Roadmap

### Completed
- **Phase 1:** tactics.tools scraper, document generator, ChromaDB ingestion
- **Phase 1.5:** Gemini 2.5 Flash chatbot with smart retrieval routing, Streamlit UI
- **Phase 2:** YouTube transcript ingestion with Gemini-powered extraction
- **Deployment:** AWS Lightsail, Docker Compose, GitHub Actions CI/CD

### Future
- **Phase 3:** Twitter/X meta signal ingestion — track what top players are saying
- **Phase 4:** Personal match history tracking via Riot API — personalized advice
- **Phase 5:** Meta shift detection and alerts — notify when win rates change significantly
