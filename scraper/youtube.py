"""Fetch and process YouTube video transcripts for TFT RAG ingestion.

Uses youtube-transcript-api to get transcripts and Gemini to extract
actionable TFT advice from raw transcript text.

Usage:
    python -m scraper.youtube https://www.youtube.com/watch?v=VIDEO_ID
    python -m scraper.youtube URL1 URL2 URL3
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from youtube_transcript_api import YouTubeTranscriptApi

from google import genai

logger = logging.getLogger(__name__)

YOUTUBE_VIDEOS_PATH = Path("data/youtube_videos.json")

EXTRACTION_PROMPT = """\
You are a TFT (Teamfight Tactics) analyst. I'm giving you the transcript of a TFT guide video.
Extract ONLY the actionable gameplay advice and meta analysis. Structure it as a knowledge document.

For each distinct piece of advice or recommendation, capture:
- What comp/unit/item/strategy is being discussed
- The specific advice or recommendation
- Any conditions ("if you hit X early", "below Diamond", "on this patch")
- The approximate timestamp in the video

Ignore: intros, outros, ad reads, subscriber calls, off-topic tangents, filler words.
Do NOT mention augments — we do not have augment data in our system.

Format the output as a clean document with sections like:
## Comp Recommendations
## Item Priorities
## Openers & Transitions
## General Strategy Tips
## Patch-Specific Changes

If a section has no relevant content, omit it.

Here is the transcript:

{transcript}
"""


def _extract_video_id(url_or_id: str) -> str:
    """Extract a YouTube video ID from a URL or return the ID directly."""
    url_or_id = url_or_id.strip()

    # Already a bare video ID (11 chars, alphanumeric + _ -)
    if re.fullmatch(r"[\w-]{11}", url_or_id):
        return url_or_id

    # Standard and short URL patterns
    patterns = [
        r"(?:youtube\.com/watch\?.*v=)([\w-]{11})",
        r"(?:youtu\.be/)([\w-]{11})",
        r"(?:youtube\.com/embed/)([\w-]{11})",
        r"(?:youtube\.com/shorts/)([\w-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)

    raise ValueError(f"Could not extract video ID from: {url_or_id}")


class TFTYouTubeScraper:
    """Fetches YouTube transcripts and processes them for TFT RAG ingestion."""

    def __init__(self, gemini_api_key: str | None = None):
        api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found — pass it or set it in .env")
        self.gemini_client = genai.Client(api_key=api_key)

    def fetch_transcript(self, video_url_or_id: str) -> dict:
        """Fetch the English transcript for a YouTube video.

        Args:
            video_url_or_id: A YouTube URL or bare video ID.

        Returns:
            {
                "video_id": str,
                "transcript_raw": str,
                "transcript_timestamped": list,
                "duration_seconds": float,
            }
        """
        video_id = _extract_video_id(video_url_or_id)

        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id, languages=["en"])

        # Convert FetchedTranscriptSnippet objects to dicts
        snippets = [
            {"text": s.text, "start": s.start, "duration": s.duration}
            for s in fetched
        ]

        raw_text = " ".join(s["text"] for s in snippets)

        duration = 0.0
        if snippets:
            last = snippets[-1]
            duration = last["start"] + last.get("duration", 0)

        return {
            "video_id": video_id,
            "transcript_raw": raw_text,
            "transcript_timestamped": snippets,
            "duration_seconds": duration,
        }

    def fetch_video_metadata(self, video_url_or_id: str) -> dict:
        """Scrape basic video metadata from the YouTube page (no API key needed).

        Returns:
            {"title": str, "channel": str, "upload_date": str}
        """
        video_id = _extract_video_id(video_url_or_id)
        url = f"https://www.youtube.com/watch?v={video_id}"

        defaults = {
            "title": f"YouTube Video {video_id}",
            "channel": "Unknown Channel",
            "upload_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }

        try:
            resp = requests.get(
                url,
                headers={"Accept-Language": "en-US,en;q=0.9"},
                timeout=15,
            )
            resp.raise_for_status()
            html = resp.text

            # Title from <title> tag (format: "Video Title - YouTube")
            title_match = re.search(r"<title>(.*?)</title>", html)
            if title_match:
                title = title_match.group(1).replace(" - YouTube", "").strip()
                if title:
                    defaults["title"] = title

            # Channel name from link tag or structured data
            channel_match = re.search(
                r'"ownerChannelName"\s*:\s*"([^"]+)"', html
            )
            if channel_match:
                defaults["channel"] = channel_match.group(1)
            else:
                channel_match2 = re.search(
                    r'"author"\s*:\s*"([^"]+)"', html
                )
                if channel_match2:
                    defaults["channel"] = channel_match2.group(1)

            # Upload date
            date_match = re.search(
                r'"uploadDate"\s*:\s*"(\d{4}-\d{2}-\d{2})', html
            )
            if date_match:
                defaults["upload_date"] = date_match.group(1)
            else:
                date_match2 = re.search(
                    r'"publishDate"\s*:\s*"(\d{4}-\d{2}-\d{2})', html
                )
                if date_match2:
                    defaults["upload_date"] = date_match2.group(1)

        except Exception as exc:
            logger.warning("Failed to fetch metadata for %s: %s", video_id, exc)

        return defaults

    def process_transcript_for_rag(
        self, transcript_data: dict, video_metadata: dict
    ) -> dict:
        """Use Gemini to extract actionable TFT advice from the raw transcript.

        For long videos (>30 min), splits the transcript and processes chunks
        separately before combining.

        Returns:
            {"text": str, "metadata": dict}
        """
        video_id = transcript_data["video_id"]
        duration = transcript_data["duration_seconds"]
        raw = transcript_data["transcript_raw"]

        # Split long transcripts into ~15-minute chunks by timestamp
        if duration > 1800:
            processed_parts = self._process_long_transcript(transcript_data)
        else:
            processed_parts = [self._call_gemini(raw)]

        combined_text = "\n\n".join(processed_parts)

        video_url = f"https://www.youtube.com/watch?v={video_id}"

        return {
            "text": combined_text,
            "metadata": {
                "source": "youtube",
                "type": "video_guide",
                "video_id": video_id,
                "video_title": video_metadata.get("title", ""),
                "channel": video_metadata.get("channel", ""),
                "date": video_metadata.get("upload_date", ""),
                "video_url": video_url,
            },
        }

    def _process_long_transcript(self, transcript_data: dict) -> list[str]:
        """Split a long transcript into ~15-min chunks and process each."""
        snippets = transcript_data["transcript_timestamped"]
        chunk_duration = 900  # 15 minutes in seconds
        chunks = []
        current_chunk = []
        chunk_start = 0.0

        for s in snippets:
            current_chunk.append(s["text"])
            if s["start"] - chunk_start >= chunk_duration:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                chunk_start = s["start"]

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        results = []
        for i, chunk_text in enumerate(chunks):
            logger.info("Processing transcript chunk %d/%d...", i + 1, len(chunks))
            result = self._call_gemini(chunk_text)
            results.append(result)
            if i < len(chunks) - 1:
                time.sleep(2)

        return results

    def _call_gemini(self, transcript_text: str) -> str:
        """Call Gemini to extract TFT advice from transcript text."""
        prompt = EXTRACTION_PROMPT.format(transcript=transcript_text)

        response = self.gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "max_output_tokens": 4096,
            },
        )

        return response.text


def load_youtube_videos() -> list[dict]:
    """Load the list of ingested YouTube videos from the tracking file."""
    if YOUTUBE_VIDEOS_PATH.exists():
        return json.loads(YOUTUBE_VIDEOS_PATH.read_text(encoding="utf-8"))
    return []


def save_youtube_video(entry: dict):
    """Append a video entry to the tracking file."""
    videos = load_youtube_videos()

    # Avoid duplicates by video_id
    videos = [v for v in videos if v.get("video_id") != entry.get("video_id")]
    videos.append(entry)

    YOUTUBE_VIDEOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    YOUTUBE_VIDEOS_PATH.write_text(
        json.dumps(videos, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def ingest_youtube_video(video_url: str, scraper: TFTYouTubeScraper) -> dict:
    """Full pipeline: fetch transcript, process with Gemini, ingest into ChromaDB.

    Returns:
        {"success": bool, "video_id": str, "title": str, "error": str|None}
    """
    from pipeline.document_generator import TFTDocumentGenerator
    from rag.vector_store import TFTVectorStore

    result = {"success": False, "video_id": "", "title": "", "error": None}

    try:
        video_id = _extract_video_id(video_url)
        result["video_id"] = video_id
        logger.info("Fetching transcript for %s...", video_id)

        transcript_data = scraper.fetch_transcript(video_url)
        metadata = scraper.fetch_video_metadata(video_url)
        result["title"] = metadata.get("title", "")

        logger.info("Processing transcript with Gemini...")
        processed = scraper.process_transcript_for_rag(transcript_data, metadata)

        # Wrap with document generator
        gen = TFTDocumentGenerator()
        document = gen.generate_youtube_document(processed)

        # Ingest into ChromaDB
        store = TFTVectorStore()
        store.ingest_document(document)

        # Track the ingested video
        save_youtube_video({
            "video_id": video_id,
            "title": metadata.get("title", ""),
            "channel": metadata.get("channel", ""),
            "date_ingested": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "upload_date": metadata.get("upload_date", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
        })

        result["success"] = True
        logger.info("Successfully ingested video: %s", metadata.get("title", video_id))

    except Exception as exc:
        result["error"] = str(exc)
        logger.error("Failed to ingest video %s: %s", video_url, exc, exc_info=True)

    return result


if __name__ == "__main__":
    import argparse
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Fetch and process YouTube TFT guide transcripts.",
    )
    parser.add_argument(
        "urls", nargs="+",
        help="One or more YouTube video URLs or video IDs.",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Print raw transcript instead of Gemini-processed output.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    scraper = TFTYouTubeScraper()

    for i, url in enumerate(args.urls):
        if i > 0:
            time.sleep(3)

        print(f"\n{'=' * 60}")
        print(f"Processing: {url}")
        print("=" * 60)

        try:
            transcript_data = scraper.fetch_transcript(url)
            metadata = scraper.fetch_video_metadata(url)

            print(f"Title: {metadata['title']}")
            print(f"Channel: {metadata['channel']}")
            print(f"Upload Date: {metadata['upload_date']}")
            print(f"Duration: {transcript_data['duration_seconds']:.0f}s")
            print()

            if args.raw:
                print(transcript_data["transcript_raw"])
            else:
                processed = scraper.process_transcript_for_rag(
                    transcript_data, metadata
                )
                print(processed["text"])
                print(f"\n[Metadata: {processed['metadata']}]")

        except Exception as exc:
            print(f"Error: {exc}")
