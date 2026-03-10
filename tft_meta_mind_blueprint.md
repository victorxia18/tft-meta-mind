# TFT Meta Mind — Technical Blueprint

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     DATA SOURCES                            │
├──────────────┬──────────────────┬───────────────────────────┤
│ tactics.tools│  Riot TFT API    │  Twitter/X + Patch Notes  │
│ (scraped)    │  (supplemental)  │  (community signal)       │
└──────┬───────┴────────┬─────────┴─────────────┬─────────────┘
       │                │                       │
       ▼                ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│              DAILY PIPELINE (cron / APScheduler)            │
│  1. Scrape tactics.tools comp/augment/item stats            │
│  2. (Optional) Pull high-elo matches from Riot API          │
│  3. Scrape Twitter/X for pro player meta calls              │
│  4. Fetch latest patch notes                                │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              DOCUMENT GENERATION                            │
│  Convert raw data → natural language text documents         │
│  e.g. "Daily Meta Snapshot - March 9, 2026"                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              RAG VECTOR DB (ChromaDB)                        │
│  Chunk documents → embed → store with metadata              │
│  metadata: {source, date, type, patch}                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              CHATBOT (Streamlit + Claude API)                │
│  User asks question → retrieve relevant chunks →            │
│  inject into prompt → Claude generates grounded answer      │
└─────────────────────────────────────────────────────────────┘
```

---

## Part 1: Data Collection — Two Approaches

### Approach A: Scrape tactics.tools (Recommended Starting Point)

tactics.tools is a JavaScript-rendered site, so its data loads via internal
API calls (XHR/fetch). The strategy is to intercept those network requests
rather than parsing HTML, which gives you clean JSON data directly.

**Step 1: Discover the internal API endpoints**

Open Chrome DevTools → Network tab → filter by "Fetch/XHR" → load
tactics.tools/team-compositions. You'll see the fetch requests that return
comp data as JSON. The URL patterns typically look like:

```
https://api.tactics.tools/api/v1/comps?...
https://api.tactics.tools/api/v1/augments?...
https://api.tactics.tools/api/v1/items?...
```

These internal APIs return pre-aggregated stats (avg placement, play rate,
win rate, top 4 rate) which saves you from computing these yourself.

**Step 2: Scrape with Playwright (handles JS rendering)**

```python
# scraper/tactics_tools.py
import asyncio
import json
from datetime import datetime
from playwright.async_api import async_playwright


async def scrape_tactics_tools():
    """
    Intercept XHR requests from tactics.tools to capture
    pre-aggregated comp, augment, and item data.
    """
    captured_data = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Intercept network responses
        async def handle_response(response):
            url = response.url
            if response.ok and "api" in url:
                try:
                    body = await response.json()
                    # Categorize by endpoint
                    if "comp" in url.lower():
                        captured_data["comps"] = body
                    elif "augment" in url.lower():
                        captured_data["augments"] = body
                    elif "item" in url.lower():
                        captured_data["items"] = body
                except Exception:
                    pass  # Not all responses are JSON

        page.on("response", handle_response)

        # Visit the comps page
        await page.goto("https://tactics.tools/team-compositions")
        await page.wait_for_timeout(5000)  # Let data load

        # Visit augments page
        await page.goto("https://tactics.tools/augments")
        await page.wait_for_timeout(5000)

        # Visit items page
        await page.goto("https://tactics.tools/items")
        await page.wait_for_timeout(5000)

        await browser.close()

    # Save raw data with timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d")
    with open(f"data/raw/tactics_tools_{timestamp}.json", "w") as f:
        json.dump(captured_data, f, indent=2)

    return captured_data


if __name__ == "__main__":
    asyncio.run(scrape_tactics_tools())
```

**Alternative: Direct requests (if you find stable API URLs)**

If the API endpoints don't require special auth or cookies, you can skip
Playwright entirely and just use `requests`:

```python
import requests

# These URLs are examples — you'll need to discover the real ones
# from the Network tab in Chrome DevTools
COMPS_URL = "https://api.tactics.tools/api/v1/comps"
AUGMENTS_URL = "https://api.tactics.tools/api/v1/augments"

def fetch_comps():
    """Direct API call — faster and simpler than browser scraping."""
    headers = {
        "User-Agent": "TFT-Meta-Mind/1.0 (personal project)",
        "Accept": "application/json",
    }
    response = requests.get(COMPS_URL, headers=headers)
    response.raise_for_status()
    return response.json()
```

**What you'll get from tactics.tools:**
- Top comps with avg placement, play rate, win rate, top 4 rate
- Augment tier list with pick rate, avg placement per augment
- Item stats and best holders
- All pre-computed from high-elo games

---

### Approach B: Riot API Direct (Supplemental / Learning Project)

Use this alongside tactics.tools scraping, or as a Phase 2 learning exercise.
The Riot API gives you raw match data that you'd need to aggregate yourself,
but it lets you do custom analysis (e.g., "what comps work at MY elo").

```python
# scraper/riot_api.py
import requests
import time
from typing import Optional


class TFTApiClient:
    """
    Wrapper for the Riot TFT API endpoints.

    Routing rules:
    - League/Summoner endpoints → platform routes (na1, euw1, kr)
    - Match endpoints → regional routes (americas, europe, asia)
    - Account endpoints → regional routes (americas, europe, asia)
    """

    def __init__(self, api_key: str, platform: str = "na1", region: str = "americas"):
        self.api_key = api_key
        self.platform = platform
        self.region = region
        self.headers = {"X-Riot-Token": api_key}

    def _platform_url(self, path: str) -> str:
        return f"https://{self.platform}.api.riotgames.com{path}"

    def _region_url(self, path: str) -> str:
        return f"https://{self.region}.api.riotgames.com{path}"

    def _get(self, url: str) -> dict:
        """Make a rate-limit-aware GET request."""
        response = requests.get(url, headers=self.headers)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 5))
            print(f"Rate limited. Waiting {retry_after}s...")
            time.sleep(retry_after)
            return self._get(url)
        response.raise_for_status()
        return response.json()

    # ──────────────────────────────────────────────
    # TFT-League-V1: Find high-elo players
    # ──────────────────────────────────────────────

    def get_challenger_ladder(self) -> list[dict]:
        """Get all Challenger players with LP, wins, losses."""
        url = self._platform_url("/tft/league/v1/challenger")
        data = self._get(url)
        return data.get("entries", [])

    def get_grandmaster_ladder(self) -> list[dict]:
        url = self._platform_url("/tft/league/v1/grandmaster")
        data = self._get(url)
        return data.get("entries", [])

    def get_master_ladder(self) -> list[dict]:
        url = self._platform_url("/tft/league/v1/master")
        data = self._get(url)
        return data.get("entries", [])

    # ──────────────────────────────────────────────
    # TFT-Summoner-V1: Convert IDs
    # ──────────────────────────────────────────────

    def summoner_id_to_puuid(self, summoner_id: str) -> str:
        """Convert encrypted summonerId → PUUID."""
        url = self._platform_url(f"/tft/summoner/v1/summoners/{summoner_id}")
        data = self._get(url)
        return data["puuid"]

    # ──────────────────────────────────────────────
    # Account-V1: Riot ID lookups
    # ──────────────────────────────────────────────

    def get_account_by_riot_id(self, game_name: str, tag_line: str) -> dict:
        """Look up a player by Riot ID (e.g., 'Player#NA1')."""
        url = self._region_url(
            f"/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        )
        return self._get(url)

    def get_account_by_puuid(self, puuid: str) -> dict:
        """Reverse lookup: PUUID → Riot ID."""
        url = self._region_url(f"/riot/account/v1/accounts/by-puuid/{puuid}")
        return self._get(url)

    # ──────────────────────────────────────────────
    # TFT-Match-V1: The gold mine
    # ──────────────────────────────────────────────

    def get_match_ids(
        self,
        puuid: str,
        count: int = 20,
        start_time: Optional[int] = None,
    ) -> list[str]:
        """
        Get recent match IDs for a player.

        Args:
            puuid: Player's PUUID
            count: Number of match IDs (default 20, max 200)
            start_time: Epoch timestamp in seconds (optional)
        """
        params = f"?count={count}"
        if start_time:
            params += f"&startTime={start_time}"
        url = self._region_url(
            f"/tft/match/v1/matches/by-puuid/{puuid}/ids{params}"
        )
        return self._get(url)

    def get_match_detail(self, match_id: str) -> dict:
        """
        Get full match details including all 8 players' boards.

        Returns a dict with:
        - metadata: {data_version, match_id, participants}
        - info: {game_datetime, game_length, tft_set_number,
                 tft_set_core_name, participants: [...]}

        Each participant has:
        - placement (1-8)
        - level
        - augments (list of 3 augment IDs)
        - traits (list of {name, num_units, style, tier_current})
        - units (list of {character_id, tier, items, rarity})
        - gold_left, last_round, time_eliminated
        """
        url = self._region_url(f"/tft/match/v1/matches/{match_id}")
        return self._get(url)


# ──────────────────────────────────────────────
# Example: Full pipeline to collect high-elo data
# ──────────────────────────────────────────────

def collect_high_elo_matches(api_key: str, num_players: int = 20):
    """
    Daily collection pipeline:
    1. Get top Challenger players
    2. Convert their IDs to PUUIDs
    3. Pull their recent matches
    4. Fetch full match details
    """
    client = TFTApiClient(api_key)
    all_matches = {}

    # Step 1: Get top players from Challenger ladder
    ladder = client.get_challenger_ladder()
    # Sort by LP descending, take top N
    top_players = sorted(ladder, key=lambda x: x["leaguePoints"], reverse=True)[
        :num_players
    ]
    print(f"Found {len(top_players)} top Challenger players")

    for i, player in enumerate(top_players):
        summoner_id = player["summonerId"]
        print(f"  [{i+1}/{num_players}] Processing {summoner_id}...")

        # Step 2: Get PUUID
        try:
            puuid = client.summoner_id_to_puuid(summoner_id)
        except Exception as e:
            print(f"    Skipping (summoner lookup failed): {e}")
            continue

        time.sleep(0.1)  # Be nice to rate limits

        # Step 3: Get recent match IDs (last 10 games)
        try:
            match_ids = client.get_match_ids(puuid, count=10)
        except Exception as e:
            print(f"    Skipping (match list failed): {e}")
            continue

        time.sleep(0.1)

        # Step 4: Fetch each match (skip duplicates)
        for match_id in match_ids:
            if match_id not in all_matches:
                try:
                    match_data = client.get_match_detail(match_id)
                    all_matches[match_id] = match_data
                    print(f"    Fetched {match_id}")
                except Exception as e:
                    print(f"    Failed {match_id}: {e}")
                time.sleep(0.1)

    print(f"\nCollected {len(all_matches)} unique matches")
    return all_matches
```

---

## Part 2: Data Dragon — Translating IDs to Names

The Riot API returns IDs like `TFT12_Ahri` and `TFT_Item_BFSword`.
Data Dragon maps these to human-readable names.

```python
# utils/data_dragon.py
import requests
from functools import lru_cache


class DataDragon:
    """
    Fetches and caches TFT static data from Riot's Data Dragon.
    This translates internal IDs to human-readable names.
    """

    BASE_URL = "https://ddragon.leagueoflegends.com"

    def __init__(self):
        self.version = self._get_latest_version()
        self._champions = None
        self._items = None
        self._augments = None
        self._traits = None

    def _get_latest_version(self) -> str:
        url = f"{self.BASE_URL}/api/versions.json"
        versions = requests.get(url).json()
        return versions[0]  # First entry is latest

    def _fetch_json(self, filename: str) -> dict:
        url = f"{self.BASE_URL}/cdn/{self.version}/data/en_US/{filename}"
        return requests.get(url).json()

    @property
    def champions(self) -> dict:
        if self._champions is None:
            data = self._fetch_json("tft-champion.json")
            # Build lookup: internal_id → {name, cost, ...}
            self._champions = {}
            for key, champ in data.get("data", {}).items():
                self._champions[key] = {
                    "name": champ.get("name", key),
                    "cost": champ.get("tier", 0),
                }
        return self._champions

    @property
    def items(self) -> dict:
        if self._items is None:
            data = self._fetch_json("tft-item.json")
            self._items = {}
            for key, item in data.get("data", {}).items():
                self._items[key] = {"name": item.get("name", key)}
        return self._items

    @property
    def augments(self) -> dict:
        if self._augments is None:
            data = self._fetch_json("tft-augments.json")
            self._augments = {}
            for key, aug in data.get("data", {}).items():
                self._augments[key] = {"name": aug.get("name", key)}
        return self._augments

    def champion_name(self, champion_id: str) -> str:
        return self.champions.get(champion_id, {}).get("name", champion_id)

    def item_name(self, item_id) -> str:
        """Accept either string ID or integer ID."""
        if isinstance(item_id, int):
            # Some match data uses integer item IDs
            # You may need a separate mapping for these
            return str(item_id)
        return self.items.get(str(item_id), {}).get("name", str(item_id))

    def augment_name(self, augment_id: str) -> str:
        return self.augments.get(augment_id, {}).get("name", augment_id)
```

---

## Part 3: Document Generation — Converting Data to RAG-Friendly Text

This is the critical bridge between raw data and your chatbot.
The key insight: **LLMs understand natural language, not JSON tables.**
You need to convert your scraped/API data into well-structured text
documents that read like TFT game knowledge.

### Document Types

Your RAG system will store several types of documents:

```python
# pipeline/document_generator.py
from datetime import datetime


class TFTDocumentGenerator:
    """
    Converts raw TFT data into natural language documents
    suitable for RAG ingestion.
    """

    def __init__(self, data_dragon=None):
        self.dd = data_dragon  # For ID → name translation

    # ──────────────────────────────────────────────
    # Type 1: Daily Meta Snapshot
    # ──────────────────────────────────────────────

    def generate_meta_snapshot(self, comps_data: list, date: str = None) -> dict:
        """
        Generate a daily meta overview document from comp stats.

        This is the most important document type — it answers
        questions like "what's strong right now?"

        Returns:
            {
                "text": "...",      # The document content
                "metadata": {...}    # For filtering in vector DB
            }
        """
        date = date or datetime.now().strftime("%Y-%m-%d")

        lines = [
            f"# TFT Meta Snapshot — {date}",
            f"",
            f"## Top Performing Team Compositions",
            f"",
            f"The following comps are ranked by average placement "
            f"in high-elo (Master+) games on this date.",
            f"",
        ]

        # Sort comps by average placement (lower is better)
        sorted_comps = sorted(comps_data, key=lambda c: c.get("avg_placement", 9))

        for i, comp in enumerate(sorted_comps[:10], 1):
            name = comp.get("name", "Unknown Comp")
            avg_place = comp.get("avg_placement", "N/A")
            play_rate = comp.get("play_rate", "N/A")
            win_rate = comp.get("win_rate", "N/A")
            top4_rate = comp.get("top4_rate", "N/A")

            # List core units
            units = comp.get("units", [])
            unit_names = [u.get("name", u.get("id", "?")) for u in units]

            # List core items
            items = comp.get("core_items", [])

            # List traits
            traits = comp.get("traits", [])

            lines.append(f"### {i}. {name}")
            lines.append(f"")
            lines.append(
                f"Average Placement: {avg_place} | "
                f"Play Rate: {play_rate}% | "
                f"Win Rate: {win_rate}% | "
                f"Top 4 Rate: {top4_rate}%"
            )
            lines.append(f"")
            lines.append(f"Core Units: {', '.join(unit_names)}")
            if traits:
                lines.append(f"Active Traits: {', '.join(traits)}")
            if items:
                lines.append(f"Core Items: {', '.join(items)}")
            lines.append(f"")

        text = "\n".join(lines)

        return {
            "text": text,
            "metadata": {
                "source": "tactics_tools",
                "type": "meta_snapshot",
                "date": date,
                "patch": comp.get("patch", "unknown"),
            },
        }

    # ──────────────────────────────────────────────
    # Type 2: Augment Tier List
    # ──────────────────────────────────────────────

    def generate_augment_document(self, augments_data: list, date: str = None) -> dict:
        """
        Generate an augment analysis document.

        Answers questions like "what augments should I take?"
        or "is [augment X] good?"
        """
        date = date or datetime.now().strftime("%Y-%m-%d")

        lines = [
            f"# TFT Augment Analysis — {date}",
            f"",
            f"## Augment Performance Rankings",
            f"",
            f"Augments ranked by average placement in high-elo games.",
            f"Lower average placement = stronger augment.",
            f"",
        ]

        # Group by tier (Silver, Gold, Prismatic)
        for tier in ["Prismatic", "Gold", "Silver"]:
            tier_augments = [
                a for a in augments_data if a.get("tier", "").lower() == tier.lower()
            ]
            if not tier_augments:
                continue

            tier_augments.sort(key=lambda a: a.get("avg_placement", 9))

            lines.append(f"### {tier} Augments")
            lines.append(f"")

            for aug in tier_augments[:15]:  # Top 15 per tier
                name = aug.get("name", "Unknown")
                avg_place = aug.get("avg_placement", "N/A")
                pick_rate = aug.get("pick_rate", "N/A")

                lines.append(
                    f"- **{name}**: Avg Placement {avg_place}, "
                    f"Pick Rate {pick_rate}%"
                )

            lines.append(f"")

        return {
            "text": "\n".join(lines),
            "metadata": {
                "source": "tactics_tools",
                "type": "augment_analysis",
                "date": date,
            },
        }

    # ──────────────────────────────────────────────
    # Type 3: Match-Level Comp Document (from Riot API)
    # ──────────────────────────────────────────────

    def generate_match_document(self, match_data: dict) -> dict:
        """
        Convert a single match's data into a readable document.
        Shows what the top players ran and how they placed.

        Useful for answering "how do people itemize X?" or
        "what does a winning Y board look like?"
        """
        info = match_data.get("info", {})
        metadata = match_data.get("metadata", {})
        match_id = metadata.get("match_id", "unknown")
        game_version = info.get("game_version", "unknown")
        set_name = info.get("tft_set_core_name", "unknown")

        participants = info.get("participants", [])
        # Sort by placement
        participants.sort(key=lambda p: p.get("placement", 9))

        lines = [
            f"# TFT Match Report — {match_id}",
            f"Set: {set_name} | Patch: {game_version}",
            f"",
        ]

        for p in participants:
            placement = p.get("placement", "?")
            level = p.get("level", "?")
            augments = p.get("augments", [])
            traits = p.get("traits", [])
            units = p.get("units", [])

            # Translate IDs to names
            aug_names = [self.dd.augment_name(a) if self.dd else a for a in augments]
            active_traits = [
                t["name"]
                for t in traits
                if t.get("style", 0) > 0  # style 0 = inactive
            ]

            unit_descriptions = []
            for u in units:
                name = self.dd.champion_name(u["character_id"]) if self.dd else u["character_id"]
                stars = u.get("tier", 1)
                items = u.get("items", [])
                item_names = [self.dd.item_name(i) if self.dd else str(i) for i in items]
                item_str = f" [{', '.join(item_names)}]" if item_names else ""
                unit_descriptions.append(f"{name} {'★' * stars}{item_str}")

            lines.append(f"## {placement} Place (Level {level})")
            lines.append(f"Augments: {', '.join(aug_names)}")
            lines.append(f"Active Traits: {', '.join(active_traits)}")
            lines.append(f"Board: {' | '.join(unit_descriptions)}")
            lines.append(f"")

        return {
            "text": "\n".join(lines),
            "metadata": {
                "source": "riot_api",
                "type": "match_report",
                "match_id": match_id,
                "patch": game_version,
            },
        }

    # ──────────────────────────────────────────────
    # Type 4: Twitter/X Community Signal
    # ──────────────────────────────────────────────

    def generate_twitter_digest(self, tweets: list[dict], date: str = None) -> dict:
        """
        Convert classified tweets into a community signal document.

        Each tweet dict should have:
        - author: str
        - text: str
        - category: str (meta_call, patch_reaction, comp_guide, etc.)
        - url: str
        """
        date = date or datetime.now().strftime("%Y-%m-%d")

        lines = [
            f"# TFT Community Signals — {date}",
            f"",
            f"Notable tweets and insights from TFT content creators,",
            f"pro players, and analysts.",
            f"",
        ]

        # Group by category
        categories = {}
        for tweet in tweets:
            cat = tweet.get("category", "other")
            categories.setdefault(cat, []).append(tweet)

        category_labels = {
            "meta_call": "Meta Calls & Comp Recommendations",
            "patch_reaction": "Patch Reactions",
            "comp_guide": "Comp Guides & Tips",
            "item_discussion": "Item Discussion",
            "other": "Other Notable Tweets",
        }

        for cat, label in category_labels.items():
            cat_tweets = categories.get(cat, [])
            if not cat_tweets:
                continue

            lines.append(f"## {label}")
            lines.append(f"")
            for t in cat_tweets:
                author = t.get("author", "Unknown")
                text = t.get("text", "")
                lines.append(f"- @{author}: {text}")
            lines.append(f"")

        return {
            "text": "\n".join(lines),
            "metadata": {
                "source": "twitter",
                "type": "community_signal",
                "date": date,
            },
        }

    # ──────────────────────────────────────────────
    # Type 5: Patch Notes
    # ──────────────────────────────────────────────

    def generate_patch_document(self, patch_text: str, patch_version: str) -> dict:
        """
        Store patch notes as a RAG document.
        The patch text should be pre-scraped from the official site.
        """
        return {
            "text": f"# TFT Patch Notes — {patch_version}\n\n{patch_text}",
            "metadata": {
                "source": "official_patch_notes",
                "type": "patch_notes",
                "patch": patch_version,
            },
        }
```

---

## Part 4: RAG Ingestion — Vector DB Setup

```python
# rag/vector_store.py
import chromadb
from chromadb.utils import embedding_functions
from typing import Optional
import hashlib


class TFTVectorStore:
    """
    ChromaDB-backed vector store for TFT knowledge.

    Documents are chunked, embedded, and stored with metadata
    so the chatbot can retrieve relevant context.
    """

    def __init__(self, persist_dir: str = "./chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_dir)

        # Use the default embedding function (all-MiniLM-L6-v2)
        # This is free and runs locally — no API key needed
        self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()

        # Create (or get) the collection
        self.collection = self.client.get_or_create_collection(
            name="tft_knowledge",
            embedding_function=self.embedding_fn,
            metadata={"description": "TFT meta knowledge base"},
        )

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
        """
        Split text into overlapping chunks for embedding.

        Why chunk?
        - Embeddings work best on focused passages (not whole documents)
        - Smaller chunks = more precise retrieval
        - Overlap ensures context isn't lost at boundaries

        chunk_size and overlap are in words (not characters).
        """
        words = text.split()
        chunks = []

        i = 0
        while i < len(words):
            chunk = " ".join(words[i : i + chunk_size])
            chunks.append(chunk)
            i += chunk_size - overlap

        return chunks

    def ingest_document(self, document: dict):
        """
        Ingest a generated document into the vector store.

        Args:
            document: {
                "text": str,        # The full document text
                "metadata": {       # Metadata for filtering
                    "source": str,  # e.g. "tactics_tools", "riot_api", "twitter"
                    "type": str,    # e.g. "meta_snapshot", "augment_analysis"
                    "date": str,    # e.g. "2026-03-09"
                    "patch": str,   # e.g. "16.5"
                }
            }
        """
        text = document["text"]
        base_metadata = document.get("metadata", {})

        chunks = self.chunk_text(text)

        ids = []
        documents = []
        metadatas = []

        for i, chunk in enumerate(chunks):
            # Create a deterministic ID so re-ingestion overwrites
            chunk_id = hashlib.md5(
                f"{base_metadata.get('type', '')}_{base_metadata.get('date', '')}_{i}".encode()
            ).hexdigest()

            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({**base_metadata, "chunk_index": i})

        # Upsert (add or update)
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

        print(f"Ingested {len(chunks)} chunks from {base_metadata.get('type', 'unknown')}")

    def query(
        self,
        question: str,
        n_results: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """
        Retrieve the most relevant chunks for a question.

        Args:
            question: The user's natural language question
            n_results: Number of chunks to retrieve
            where: Optional metadata filter, e.g.:
                {"type": "meta_snapshot"}
                {"source": "twitter"}
                {"date": {"$gte": "2026-03-01"}}

        Returns:
            List of {text, metadata, distance} dicts
        """
        kwargs = {
            "query_texts": [question],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where

        results = self.collection.query(**kwargs)

        # Flatten the results into a cleaner format
        output = []
        for i in range(len(results["documents"][0])):
            output.append(
                {
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                }
            )

        return output

    def get_stats(self) -> dict:
        """Get collection statistics."""
        return {
            "total_chunks": self.collection.count(),
        }
```

---

## Part 5: The Chatbot — Putting It All Together

```python
# chatbot/app.py
import anthropic
from rag.vector_store import TFTVectorStore


class TFTChatbot:
    """
    RAG-powered TFT chatbot using Claude API.

    Flow:
    1. User asks a question
    2. Retrieve relevant chunks from vector DB
    3. Inject chunks into the prompt as context
    4. Claude generates a grounded answer
    """

    def __init__(self, anthropic_api_key: str, vector_store: TFTVectorStore):
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.vector_store = vector_store

    def build_system_prompt(self) -> str:
        return """You are TFT Meta Mind, an expert Teamfight Tactics analyst
and coach. You help players understand the current meta, choose comps,
pick augments, and improve their gameplay.

You have access to up-to-date meta data, community insights, and match
analysis. When answering questions:

1. Base your answers on the provided context (retrieved data)
2. Cite specific stats when available (avg placement, win rate, etc.)
3. If the context doesn't contain enough info, say so honestly
4. Give actionable advice — not just data dumps
5. Consider the player's perspective (climbing ranked, understanding meta)

If asked about something outside the provided context, share your general
TFT knowledge but note that the specific data may not be current."""

    def ask(self, question: str, n_context_chunks: int = 5) -> str:
        """
        Answer a TFT question using RAG.

        Args:
            question: The user's question
            n_context_chunks: How many context chunks to retrieve

        Returns:
            The chatbot's response string
        """
        # Step 1: Retrieve relevant context
        results = self.vector_store.query(question, n_results=n_context_chunks)

        # Step 2: Format context for the prompt
        context_parts = []
        for r in results:
            source = r["metadata"].get("source", "unknown")
            date = r["metadata"].get("date", "unknown")
            doc_type = r["metadata"].get("type", "unknown")
            context_parts.append(
                f"[Source: {source} | Type: {doc_type} | Date: {date}]\n{r['text']}"
            )

        context_block = "\n\n---\n\n".join(context_parts)

        # Step 3: Build the user message with injected context
        user_message = f"""Here is relevant TFT data and context to help answer the question:

<context>
{context_block}
</context>

Player's Question: {question}

Please provide a helpful, specific answer based on the context above."""

        # Step 4: Call Claude
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=self.build_system_prompt(),
            messages=[{"role": "user", "content": user_message}],
        )

        return response.content[0].text


# ──────────────────────────────────────────────
# Streamlit UI (streamlit_app.py)
# ──────────────────────────────────────────────

STREAMLIT_APP_CODE = '''
import streamlit as st
from chatbot.app import TFTChatbot
from rag.vector_store import TFTVectorStore

st.set_page_config(page_title="TFT Meta Mind", page_icon="🎮")
st.title("🎮 TFT Meta Mind")
st.caption("Ask me anything about the current TFT meta")

# Initialize (cached so it persists across reruns)
@st.cache_resource
def init():
    store = TFTVectorStore(persist_dir="./chroma_db")
    bot = TFTChatbot(
        anthropic_api_key=st.secrets["ANTHROPIC_API_KEY"],
        vector_store=store,
    )
    return bot

bot = init()

# Show DB stats
stats = bot.vector_store.get_stats()
st.sidebar.metric("Knowledge Chunks", stats["total_chunks"])

# Chat interface
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if prompt := st.chat_input("What comps are strong right now?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Searching TFT knowledge base..."):
            response = bot.ask(prompt)
        st.write(response)
    st.session_state.messages.append({"role": "assistant", "content": response})
'''
```

---

## Part 6: Daily Pipeline Orchestration

```python
# pipeline/daily_run.py
"""
Run this daily via cron or APScheduler.

Cron example (run at 6 AM daily):
    0 6 * * * cd /path/to/project && python -m pipeline.daily_run

APScheduler example:
    from apscheduler.schedulers.blocking import BlockingScheduler
    scheduler = BlockingScheduler()
    scheduler.add_job(daily_pipeline, 'cron', hour=6)
    scheduler.start()
"""
import json
import asyncio
from datetime import datetime
from scraper.tactics_tools import scrape_tactics_tools
from pipeline.document_generator import TFTDocumentGenerator
from rag.vector_store import TFTVectorStore


def daily_pipeline():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"=== TFT Meta Mind Daily Pipeline — {today} ===")

    store = TFTVectorStore()
    generator = TFTDocumentGenerator()

    # ── Step 1: Scrape tactics.tools ──
    print("\n[1/3] Scraping tactics.tools...")
    try:
        raw_data = asyncio.run(scrape_tactics_tools())

        # Generate and ingest meta snapshot
        if "comps" in raw_data:
            doc = generator.generate_meta_snapshot(raw_data["comps"], date=today)
            store.ingest_document(doc)
            print(f"  ✓ Ingested meta snapshot ({len(raw_data['comps'])} comps)")

        # Generate and ingest augment analysis
        if "augments" in raw_data:
            doc = generator.generate_augment_document(raw_data["augments"], date=today)
            store.ingest_document(doc)
            print(f"  ✓ Ingested augment analysis")

    except Exception as e:
        print(f"  ✗ tactics.tools scraping failed: {e}")

    # ── Step 2: Twitter/X signals (Phase 3) ──
    print("\n[2/3] Collecting Twitter signals...")
    # TODO: Implement Twitter scraping in Phase 3
    # tweets = scrape_tft_twitter()
    # classified = classify_tweets(tweets)
    # doc = generator.generate_twitter_digest(classified, date=today)
    # store.ingest_document(doc)
    print("  ⏭ Skipped (Phase 3)")

    # ── Step 3: Patch notes (when new patch drops) ──
    print("\n[3/3] Checking for new patch notes...")
    # TODO: Check if there's a new patch and scrape notes
    print("  ⏭ Skipped (check manually for now)")

    # ── Summary ──
    stats = store.get_stats()
    print(f"\n=== Pipeline Complete ===")
    print(f"Total chunks in knowledge base: {stats['total_chunks']}")


if __name__ == "__main__":
    daily_pipeline()
```

---

## Part 7: Suggested Project Structure

```
tft-meta-mind/
├── README.md
├── requirements.txt
├── .env                      # API keys (NEVER commit this)
├── .gitignore
│
├── scraper/
│   ├── __init__.py
│   ├── tactics_tools.py      # Playwright-based scraper
│   ├── riot_api.py           # Riot API client
│   └── twitter.py            # Twitter/X scraper (Phase 3)
│
├── utils/
│   ├── __init__.py
│   └── data_dragon.py        # ID → name translation
│
├── pipeline/
│   ├── __init__.py
│   ├── document_generator.py # Raw data → text documents
│   └── daily_run.py          # Orchestrates the daily pipeline
│
├── rag/
│   ├── __init__.py
│   └── vector_store.py       # ChromaDB wrapper
│
├── chatbot/
│   ├── __init__.py
│   └── app.py                # Claude API + RAG chatbot logic
│
├── streamlit_app.py          # Web UI
│
├── data/
│   └── raw/                  # Raw scraped data (timestamped)
│
└── chroma_db/                # Vector DB persistence (gitignored)
```

### requirements.txt

```
# Core
anthropic>=0.40.0
chromadb>=0.5.0
streamlit>=1.30.0

# Scraping
playwright>=1.40.0
requests>=2.31.0
beautifulsoup4>=4.12.0

# Scheduling
apscheduler>=3.10.0

# Utilities
python-dotenv>=1.0.0
```

---

## Chunking Strategy — Why It Matters

How you chunk documents directly impacts retrieval quality.
Here's the thinking behind the choices above:

**Chunk size: ~500 words with 100-word overlap**
- Too small (100 words): loses context, retrieves fragments
- Too large (2000 words): dilutes relevance, wastes context window
- 500 words is a sweet spot for TFT data — roughly one comp description
  or a few augment entries, which is a natural "unit of knowledge"

**Document-type-aware chunking (future improvement):**
- Meta snapshots: chunk per comp (each comp = one chunk)
- Augment docs: chunk per tier section
- Match reports: chunk per match
- Twitter digests: chunk per category

```python
# Example: smarter per-comp chunking
def chunk_by_comp(meta_snapshot_text: str) -> list[str]:
    """Split a meta snapshot so each comp is its own chunk."""
    chunks = []
    current_chunk = ""

    for line in meta_snapshot_text.split("\n"):
        if line.startswith("### ") and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = ""
        current_chunk += line + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks
```

---

## Metadata Filtering — Keeping Answers Fresh

ChromaDB supports metadata filtering on queries. This is critical
for a TFT chatbot because stale meta data is worse than no data.

```python
# Always prefer recent data
results = store.query(
    question="what are the best comps?",
    n_results=5,
    where={
        "date": {"$gte": "2026-03-01"},   # Last week only
        "type": {"$in": ["meta_snapshot", "augment_analysis"]},
    },
)

# Filter by source for specific questions
# "what are people saying about X?" → twitter only
results = store.query(
    question="what are pros saying about reroll comps?",
    where={"source": "twitter"},
)

# "what changed in the patch?" → patch notes only
results = store.query(
    question="what got nerfed this patch?",
    where={"type": "patch_notes"},
)
```

---

## Quick-Start Sequence (What to Build First)

1. **Day 1-2:** Set up project structure, install deps, get Riot API dev key
2. **Day 3-4:** Build the tactics.tools scraper (discover API endpoints in DevTools)
3. **Day 5-6:** Build document generator + ChromaDB ingestion
4. **Day 7-8:** Build the chatbot with Claude API + Streamlit UI
5. **Day 9-10:** Wire up the daily pipeline, test end-to-end
6. **Week 3+:** Add Riot API direct data, Twitter ingestion, polish UI
