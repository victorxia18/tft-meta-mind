"""Scrape tactics.tools for TFT meta data via Playwright XHR interception.

Launches a headless browser, intercepts Next.js data responses from
tactics.tools, and extracts unit stats, comp tier lists, and augment stats.

Usage:
    python -m scraper.tactics_tools
    python -m scraper.tactics_tools --rank master
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

logger = logging.getLogger("scraper.tactics_tools")

BASE_URL = "https://tactics.tools"
DATA_DIR = Path("data/raw")

# Each entry: (url_path_suffix, capture_key, pageProps_data_key)
# The data key is the field inside pageProps that holds the stats.
PAGES = [
    ("/units", "units", "statsData"),
    ("/team-compositions", "comps", "initialData"),
]

DEFAULT_RANK = "gm"
PAGE_TIMEOUT_MS = 30_000


async def scrape_tactics_tools(rank: str = DEFAULT_RANK) -> dict:
    """Scrape tactics.tools by intercepting _next/data responses.

    Args:
        rank: Rank group slug (e.g. "gm", "master", "all").

    Returns:
        Dict with metadata and captured data keyed by category.
    """
    captured_data: dict = {}

    # JavaScript to extract pageProps from the __NEXT_DATA__ script tag
    # that Next.js SSG embeds in the initial HTML.
    EXTRACT_JS = """() => {
        const el = document.getElementById('__NEXT_DATA__');
        if (!el) return null;
        return JSON.parse(el.textContent).props.pageProps;
    }"""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()

            for url_path, capture_key, data_key in PAGES:
                full_url = f"{BASE_URL}{url_path}/{rank}"
                logger.info("Navigating to %s", full_url)
                try:
                    await page.goto(
                        full_url,
                        timeout=PAGE_TIMEOUT_MS,
                        wait_until="domcontentloaded",
                    )
                except Exception as exc:
                    logger.warning("Failed to load %s: %s", full_url, exc)
                    continue

                page_props = await page.evaluate(EXTRACT_JS)
                if page_props and data_key in page_props:
                    captured_data[capture_key] = page_props[data_key]
                    logger.info(
                        "Captured '%s' (%d bytes)",
                        capture_key,
                        len(json.dumps(captured_data[capture_key])),
                    )
                else:
                    logger.warning("No data captured for '%s'", capture_key)

        finally:
            await browser.close()

    logger.info(
        "Scraping complete — captured categories: %s",
        list(captured_data.keys()),
    )

    return {
        "metadata": {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "rank": rank,
            "source": "tactics.tools",
        },
        **captured_data,
    }


def save_data(data: dict, output_dir: Path = DATA_DIR) -> Path:
    """Save scraped data to a dated JSON file.

    Returns:
        Path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = output_dir / f"tactics_tools_{date_str}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Saved data to %s", path)
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Scrape tactics.tools TFT data via Playwright."
    )
    parser.add_argument(
        "--rank",
        default=DEFAULT_RANK,
        help=f"Rank group slug (default: {DEFAULT_RANK})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DATA_DIR,
        help=f"Output directory (default: {DATA_DIR})",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    data = asyncio.run(scrape_tactics_tools(rank=args.rank))

    categories = [k for k in data if k != "metadata"]
    if not categories:
        logger.error("No data captured — nothing to save.")
        return

    path = save_data(data, output_dir=args.output_dir)
    size_kb = path.stat().st_size / 1024
    print(f"\nSummary:")
    print(f"  Categories captured: {categories}")
    print(f"  Output file: {path}")
    print(f"  File size: {size_kb:.1f} KB")


if __name__ == "__main__":
    main()
