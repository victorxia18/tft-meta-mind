"""Orchestrate the daily TFT data pipeline.

Coordinates scraping, document generation, vector store ingestion, and
old-file cleanup.  Designed to be called from cron, APScheduler, or
imported directly (e.g. from the Streamlit UI).

Usage:
    python -m pipeline.daily_run              # run once (default)
    python -m pipeline.daily_run --once       # same as above
    python -m pipeline.daily_run --schedule   # daily at 6 AM UTC via APScheduler
    python -m pipeline.daily_run --scrape-only   # scrape only
    python -m pipeline.daily_run --ingest-only   # ingest latest scrape only
    python -m pipeline.daily_run --youtube URL1 URL2   # ingest YouTube videos
    python -m pipeline.daily_run --youtube-file youtube_sources.txt
"""

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("pipeline.daily_run")

DATA_DIR = Path("data/raw")
LOG_DIR = Path("logs")
CLEANUP_DAYS = 7


# ── Logging setup ────────────────────────────────────────────

def _setup_logging():
    """Configure root logger to write to both console and logs/pipeline.log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "pipeline.log"

    root = logging.getLogger()
    # Avoid duplicate handlers on repeated calls
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(log_file.resolve())
               for h in root.handlers):
        fmt = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # File handler
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)

        # Console handler (only if none exists)
        if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
                   for h in root.handlers):
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            ch.setFormatter(fmt)
            root.addHandler(ch)

        root.setLevel(logging.DEBUG)


# ── Helper: find latest scrape file ──────────────────────────

def _latest_scrape_file() -> Path | None:
    """Return the most recent tactics_tools JSON file, or None."""
    files = sorted(DATA_DIR.glob("tactics_tools_*.json"))
    return files[-1] if files else None


# ── Step 1: Scrape ───────────────────────────────────────────

def _step_scrape(*, retry: bool = True) -> dict:
    """Run the tactics.tools scraper and save output.

    If the first attempt fails and *retry* is True, waits 30 minutes and
    retries once.

    Returns:
        {"success": bool, "path": Path|None, "comps": int, "units": int, "error": str|None}
    """
    result = _do_scrape()

    if not result["success"] and retry:
        logger.warning("Scrape failed — retrying in 30 minutes...")
        time.sleep(30 * 60)
        logger.info("Retrying scrape...")
        result = _do_scrape()

    return result


def _do_scrape() -> dict:
    """Execute a single scrape attempt."""
    from scraper.tactics_tools import scrape_tactics_tools, save_data

    result = {"success": False, "path": None, "comps": 0, "units": 0, "error": None}

    try:
        t0 = time.time()
        raw_data = asyncio.run(scrape_tactics_tools())
        elapsed = time.time() - t0
        logger.info("Scraping completed in %.1fs", elapsed)

        categories = [k for k in raw_data if k != "metadata"]
        if not categories:
            result["error"] = "Scraper returned no data categories"
            logger.error(result["error"])
            return result

        path = save_data(raw_data)
        result["success"] = True
        result["path"] = path

        # Count comps and units for summary
        comps_data = raw_data.get("comps", {})
        result["comps"] = len(comps_data.get("groups", []))

        units_data = raw_data.get("units", {})
        result["units"] = len(units_data.get("units", {}))

        logger.info(
            "Scrape saved to %s (%d comps, %d units)",
            path, result["comps"], result["units"],
        )

    except Exception as exc:
        result["error"] = str(exc)
        logger.error("Scrape failed: %s", exc, exc_info=True)

    return result


# ── Step 2: Generate documents + ingest ──────────────────────

def _step_generate_and_ingest(scrape_path: Path | None = None) -> dict:
    """Load scraped data, generate documents, and ingest into ChromaDB.

    Args:
        scrape_path: Explicit path to a scrape file.  If None, uses the
                     most recent file in data/raw/.

    Returns:
        {"success": bool, "docs_generated": int, "total_chunks": int, "error": str|None}
    """
    from pipeline.document_generator import TFTDocumentGenerator
    from rag.vector_store import TFTVectorStore

    result = {"success": False, "docs_generated": 0, "total_chunks": 0, "error": None}

    path = scrape_path or _latest_scrape_file()
    if path is None or not path.exists():
        result["error"] = "No scraped data file found"
        logger.error(result["error"])
        return result

    logger.info("Loading scraped data from %s", path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    # ── Data Dragon ──
    dd = None
    try:
        from utils.data_dragon import DataDragon
        t0 = time.time()
        dd = DataDragon()
        logger.info("Data Dragon initialized (v%s) in %.1fs", dd.version, time.time() - t0)
    except Exception as exc:
        logger.warning("Data Dragon fetch failed: %s — names will be raw IDs", exc)

    generator = TFTDocumentGenerator(data_dragon=dd)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Generate documents ──
    documents = []
    comps_data = raw.get("comps", {})
    units_data = raw.get("units", {})

    if comps_data:
        meta_doc = generator.generate_meta_snapshot(comps_data, units_data, date=today)
        documents.append(meta_doc)
        logger.info("Generated meta_snapshot document")

    if units_data:
        unit_doc = generator.generate_unit_document(units_data, date=today)
        documents.append(unit_doc)
        logger.info("Generated unit_analysis document")

    if not documents:
        result["error"] = "No comp or unit data in scrape file — nothing to generate"
        logger.error(result["error"])
        return result

    result["docs_generated"] = len(documents)

    # ── Ingest into ChromaDB ──
    try:
        t0 = time.time()
        store = TFTVectorStore()

        for doc in documents:
            store.ingest_document(doc)

        stats = store.get_stats()
        result["total_chunks"] = stats["total_chunks"]
        result["success"] = True
        logger.info(
            "Ingestion complete in %.1fs — %d total chunks",
            time.time() - t0, result["total_chunks"],
        )
    except Exception as exc:
        result["error"] = f"ChromaDB ingestion failed: {exc}"
        logger.error(result["error"], exc_info=True)

    return result


# ── Step 3: Cleanup old files ────────────────────────────────

def _step_cleanup() -> dict:
    """Delete scraped JSON files older than CLEANUP_DAYS.

    Returns:
        {"deleted": int, "error": str|None}
    """
    result = {"deleted": 0, "error": None}

    try:
        cutoff = time.time() - (CLEANUP_DAYS * 86400)
        for path in DATA_DIR.glob("tactics_tools_*.json"):
            if path.stat().st_mtime < cutoff:
                path.unlink()
                logger.info("Deleted old file: %s", path.name)
                result["deleted"] += 1

        logger.info("Cleanup complete — deleted %d old file(s)", result["deleted"])
    except Exception as exc:
        result["error"] = str(exc)
        logger.error("Cleanup failed: %s", exc)

    return result


# ── Main pipeline function ───────────────────────────────────

def daily_pipeline(
    *,
    scrape_only: bool = False,
    ingest_only: bool = False,
) -> dict:
    """Run the full daily pipeline (or a subset).

    Args:
        scrape_only: If True, only scrape — skip doc gen / ingestion.
        ingest_only: If True, skip scraping — load latest file and ingest.

    Returns:
        Dict with results from each step, suitable for programmatic use.
    """
    _setup_logging()

    pipeline_start = time.time()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.info("=" * 50)
    logger.info("TFT Meta Mind Daily Pipeline — %s", today)
    logger.info("=" * 50)

    results = {
        "date": today,
        "scrape": None,
        "documents": None,
        "ingestion": None,
        "youtube": None,
        "cleanup": None,
    }

    scrape_path = None

    # ── Scrape ──
    if not ingest_only:
        logger.info("[1/5] Scraping tactics.tools...")
        scrape_result = _step_scrape()
        results["scrape"] = scrape_result
        scrape_path = scrape_result.get("path")

        if scrape_only:
            duration = time.time() - pipeline_start
            results["duration_s"] = round(duration, 1)
            _print_summary(results, duration)
            return results

        # If scrape failed, don't proceed to ingestion
        if not scrape_result["success"]:
            logger.warning("Scrape failed — skipping document generation and ingestion")
            duration = time.time() - pipeline_start
            results["duration_s"] = round(duration, 1)
            _print_summary(results, duration)
            return results
    else:
        logger.info("[1/5] Scraping skipped (--ingest-only)")

    # ── Generate + Ingest ──
    logger.info("[2/5] Generating documents...")
    logger.info("[3/5] Ingesting into ChromaDB...")
    ingest_result = _step_generate_and_ingest(scrape_path=scrape_path)
    results["documents"] = {
        "success": ingest_result["docs_generated"] > 0,
        "count": ingest_result["docs_generated"],
    }
    results["ingestion"] = {
        "success": ingest_result["success"],
        "total_chunks": ingest_result["total_chunks"],
        "error": ingest_result["error"],
    }

    # ── YouTube ingestion ──
    logger.info("[4/5] Ingesting YouTube videos...")
    youtube_file = Path("config/youtube_sources.txt")
    youtube_urls = _read_youtube_file(str(youtube_file)) if youtube_file.exists() else []
    if youtube_urls:
        try:
            youtube_result = _ingest_youtube_urls(youtube_urls)
            results["youtube"] = youtube_result
        except Exception as exc:
            logger.error("YouTube ingestion failed: %s", exc, exc_info=True)
            results["youtube"] = {"success": False, "processed": 0, "skipped": 0, "error": str(exc)}
    else:
        logger.info("No YouTube URLs found in %s — skipping", youtube_file)
        results["youtube"] = {"success": True, "processed": 0, "skipped": 0, "error": None}

    # If ingestion failed, skip cleanup to preserve the scrape file
    if not ingest_result["success"]:
        logger.warning(
            "Ingestion failed — skipping cleanup so scraped JSON is preserved for retry"
        )
    else:
        # ── Cleanup ──
        logger.info("[5/5] Cleaning up old files...")
        cleanup_result = _step_cleanup()
        results["cleanup"] = cleanup_result

    duration = time.time() - pipeline_start
    results["duration_s"] = round(duration, 1)
    _print_summary(results, duration)

    return results


# ── Summary printer ──────────────────────────────────────────

def _status(result: dict | None) -> str:
    """Return a checkmark or X for a pipeline step result."""
    if result is None:
        return "— (skipped)"
    return "✓" if result.get("success", False) else f"✗ ({result.get('error', 'unknown')})"


def _print_summary(results: dict, duration: float):
    """Print a human-readable pipeline summary."""
    lines = [
        "",
        "=== TFT Meta Mind Daily Pipeline Summary ===",
        f"Date: {results['date']}",
    ]

    # Scrape
    scrape = results.get("scrape")
    if scrape is None:
        lines.append("Scrape: — (skipped)")
    elif scrape["success"]:
        lines.append(f"Scrape: ✓ (captured {scrape['comps']} comps, {scrape['units']} units)")
    else:
        lines.append(f"Scrape: ✗ ({scrape['error']})")

    # Documents
    docs = results.get("documents")
    if docs is None:
        lines.append("Documents: — (skipped)")
    elif docs["success"]:
        lines.append(f"Documents: ✓ (generated {docs['count']} documents)")
    else:
        lines.append("Documents: ✗ (no documents generated)")

    # Ingestion
    ingestion = results.get("ingestion")
    if ingestion is None:
        lines.append("Ingestion: — (skipped)")
    elif ingestion["success"]:
        lines.append(f"Ingestion: ✓ ({ingestion['total_chunks']} total chunks in knowledge base)")
    else:
        lines.append(f"Ingestion: ✗ ({ingestion['error']})")

    # YouTube
    youtube = results.get("youtube")
    if youtube is None:
        lines.append("YouTube: — (skipped)")
    elif youtube.get("error"):
        lines.append(f"YouTube: ✗ ({youtube['error']})")
    else:
        lines.append(
            f"YouTube: ✓ ({youtube.get('processed', 0)} ingested, "
            f"{youtube.get('skipped', 0)} skipped)"
        )

    # Cleanup
    cleanup = results.get("cleanup")
    if cleanup is None:
        lines.append("Cleanup: — (skipped)")
    elif cleanup.get("error"):
        lines.append(f"Cleanup: ✗ ({cleanup['error']})")
    else:
        lines.append(f"Cleanup: ✓ (deleted {cleanup['deleted']} old files)")

    lines.append(f"Duration: {duration:.1f}s")
    lines.append("Next run: tomorrow at 06:00 UTC")
    lines.append("=" * 45)

    summary = "\n".join(lines)
    logger.info(summary)
    print(summary)


# ── CLI entry point ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TFT Meta Mind daily pipeline orchestrator.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once", action="store_true", default=False,
        help="Run the pipeline once and exit (default behavior).",
    )
    mode.add_argument(
        "--schedule", action="store_true", default=False,
        help="Run daily at 6 AM UTC via APScheduler (with retry on failure).",
    )
    mode.add_argument(
        "--scrape-only", action="store_true", default=False,
        help="Only scrape and save JSON — skip doc generation and ingestion.",
    )
    mode.add_argument(
        "--ingest-only", action="store_true", default=False,
        help="Skip scraping — load latest JSON and generate + ingest.",
    )
    parser.add_argument(
        "--youtube", nargs="+", metavar="URL",
        help="Ingest one or more YouTube video transcripts into the knowledge base.",
    )
    parser.add_argument(
        "--youtube-file", metavar="FILE",
        help="Read YouTube URLs from a text file (one per line, # comments ignored).",
    )
    args = parser.parse_args()

    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _setup_logging()

    # ── YouTube ingestion (independent of daily pipeline) ──
    youtube_urls = list(args.youtube or [])
    if args.youtube_file:
        youtube_urls.extend(_read_youtube_file(args.youtube_file))

    if youtube_urls:
        _ingest_youtube_urls(youtube_urls)
        return

    if args.schedule:
        _run_scheduled()
    else:
        results = daily_pipeline(
            scrape_only=args.scrape_only,
            ingest_only=args.ingest_only,
        )

        # Print crontab hint after a successful full run
        if (results.get("ingestion") or {}).get("success"):
            print(
                "\nTo schedule daily via cron (or use --schedule for APScheduler):\n"
                "  0 6 * * * cd /path/to/tft-project "
                "&& /path/to/.venv/bin/python -m pipeline.daily_run "
                ">> logs/cron.log 2>&1"
            )


def _read_youtube_file(filepath: str) -> list[str]:
    """Read YouTube URLs from a text file (one per line, # comments ignored)."""
    urls = []
    path = Path(filepath)
    if not path.exists():
        logger.error("YouTube file not found: %s", filepath)
        print(f"Error: file not found: {filepath}")
        return urls

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)

    return urls


def _ingest_youtube_urls(urls: list[str]) -> dict:
    """Fetch, process, and ingest YouTube videos into the knowledge base.

    Skips videos already tracked in data/youtube_videos.json to avoid
    wasting Gemini API tokens on duplicates.

    Returns:
        {"success": bool, "processed": int, "skipped": int, "error": str|None}
    """
    import os
    import re
    import time as _time

    from dotenv import load_dotenv
    load_dotenv()

    result = {"success": False, "processed": 0, "skipped": 0, "error": None}

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        result["error"] = "GEMINI_API_KEY not found in .env file"
        logger.error(result["error"])
        return result

    from scraper.youtube import (
        TFTYouTubeScraper,
        ingest_youtube_video,
        load_youtube_videos,
        _extract_video_id,
    )

    # Build set of already-ingested video IDs for duplicate detection
    existing_ids = {v.get("video_id") for v in load_youtube_videos()}

    scraper = TFTYouTubeScraper(gemini_api_key=api_key)
    total = len(urls)

    for i, url in enumerate(urls, 1):
        # Check for duplicate before calling Gemini
        try:
            video_id = _extract_video_id(url)
        except Exception:
            video_id = None

        if video_id and video_id in existing_ids:
            logger.info("[%d/%d] Skipping already-ingested video: %s", i, total, video_id)
            result["skipped"] += 1
            continue

        logger.info("[%d/%d] Processing: %s", i, total, url)
        ingest_result = ingest_youtube_video(url, scraper)

        if ingest_result["success"]:
            logger.info("  Ingested: %s", ingest_result["title"])
            result["processed"] += 1
            # Add to existing set so later duplicates in the same file are caught
            if ingest_result.get("video_id"):
                existing_ids.add(ingest_result["video_id"])
        else:
            logger.warning("  Failed: %s", ingest_result["error"])

        # Rate limit between videos
        if i < total:
            _time.sleep(3)

    result["success"] = True
    logger.info(
        "YouTube ingestion done — %d processed, %d skipped",
        result["processed"], result["skipped"],
    )
    return result


def _run_scheduled():
    """Start an APScheduler loop that runs the pipeline daily at 6 AM UTC."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()

    # Run immediately on startup, then daily at 06:00 UTC
    scheduler.add_job(
        daily_pipeline,
        "cron",
        hour=6,
        next_run_time=datetime.now(),
        id="daily_pipeline",
        name="TFT Meta Mind Daily Pipeline",
    )

    logger.info("Scheduler started — running daily at 06:00 UTC. Press Ctrl+C to stop.")
    print("Scheduler started — running daily at 06:00 UTC. Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
        print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
