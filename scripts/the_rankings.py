# ============================================================
# [JSON API] Times Higher Education World University Rankings
# URL: https://www.timeshighereducation.com/world-university-rankings/latest/world-ranking
# 策略: httpx + JSON API (no pagination, single endpoint)
# 基类: None (JSON API, no HTML parsing for list data)
# 分页: None (single JSON endpoint returns all 3118 entries)
# 字段: rank, name, location, overall_score, introduction
# 详情: 从详情页 __NEXT_DATA__.viewProps.about.description.html 提取
# ============================================================

import asyncio
import json
import logging
import random
import re
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from tqdm import tqdm

logger = logging.getLogger(__name__)

SOURCE_NAME = "the_world_university_rankings"
JSON_API_URL = "https://www.timeshighereducation.com/json/ranking_tables/world_university_rankings/2026"
BASE_URL = "https://www.timeshighereducation.com"

REQUEST_DELAY = (0.5, 1.5)
MAX_RETRIES = 5
CONCURRENCY = 10
# For testing: set to small number (e.g., 20). Set to None for full run.
MAX_ITEMS = None

data_dir = Path(__file__).resolve().parent.parent / "data"
data_dir.mkdir(parents=True, exist_ok=True)


def _rank_sort_key(rank: str) -> tuple:
    rank = rank.lstrip("=")
    try:
        return (0, int(float(rank)))
    except ValueError:
        return (1, rank)


def extract_introduction(html: str) -> str:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return ""
    try:
        data = json.loads(match.group(1))
        view_props = data.get("props", {}).get("pageProps", {}).get("viewProps", {})
        about = view_props.get("about", {})
        desc = about.get("description", {})
        html_content = desc.get("html", "")
        if html_content:
            soup = BeautifulSoup(html_content, "html.parser")
            return soup.get_text(separator="\n").strip()
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return ""


async def fetch_with_retry(
    client: httpx.AsyncClient, url: str, timeout: int = 30
) -> str | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url, timeout=timeout)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1) + random.uniform(0, 1)
                logger.warning(f"429 on {url}, retrying in {wait:.1f}s")
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP {e.response.status_code} on {url}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** (attempt + 1))
            else:
                return None
        except httpx.RequestError as e:
            logger.error(f"Request error on {url}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** (attempt + 1))
            else:
                return None
    return None


async def fetch_all_rankings(client: httpx.AsyncClient) -> list[dict]:
    logger.info(f"Fetching rankings from {JSON_API_URL}")
    text = await fetch_with_retry(client, JSON_API_URL)
    if not text:
        logger.error("Failed to fetch rankings JSON")
        return []
    try:
        data = json.loads(text)
        entries = data.get("data", [])
        logger.info(f"Got {len(entries)} entries from JSON API")
        return entries
    except json.JSONDecodeError:
        logger.error("Failed to parse rankings JSON")
        return []


async def fetch_introduction(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, path: str
) -> str:
    if not path:
        return ""
    url = f"{BASE_URL}{path}"
    async with semaphore:
        await asyncio.sleep(random.uniform(*REQUEST_DELAY))
        html = await fetch_with_retry(client, url)
        if html:
            return extract_introduction(html)
        return ""


async def main(max_items: int | None = None):
    if max_items is not None:
        global MAX_ITEMS
        MAX_ITEMS = max_items

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
    }
    client = httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=60.0)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    entries = await fetch_all_rankings(client)
    if not entries:
        logger.error("No entries fetched, exiting")
        await client.aclose()
        return

    # Sort by rank_order (numeric sort key from API)
    entries.sort(key=lambda x: int(x.get("rank_order", 0)))

    if MAX_ITEMS is not None:
        entries = entries[:MAX_ITEMS]
        logger.info(f"Limited to first {MAX_ITEMS} entries for testing")

    all_results: list[dict[str, Any]] = []

    async def process_item(item: dict) -> dict:
        path = item.get("url", "")
        intro = await fetch_introduction(client, semaphore, path)
        rank = item.get("rank", "")
        result = {
            "rank": rank,
            "name": item.get("name", ""),
            "location": item.get("location", ""),
            "overall_score": item.get("scores_overall", ""),
            "introduction": intro,
            "url": f"{BASE_URL}{path}",
            "source": SOURCE_NAME,
        }
        return result

    tasks = [process_item(item) for item in entries]
    for coro in tqdm(
        asyncio.as_completed(tasks),
        total=len(tasks),
        desc="Fetching details",
    ):
        all_results.append(await coro)

    all_results.sort(key=lambda x: _rank_sort_key(x.get("rank", "")))

    output_path = data_dir / f"{SOURCE_NAME}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(all_results)} results to {output_path}")

    # Preview first 5
    for r in all_results[:5]:
        intro_preview = r["introduction"][:80] if r["introduction"] else "(empty)"
        logger.info(
            f"  #{r['rank']} {r['name']} | {r['location']} | Score: {r['overall_score']} | Intro: {intro_preview}..."
        )

    await client.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    import sys

    items = None
    if len(sys.argv) > 1:
        items = int(sys.argv[1])
    asyncio.run(main(max_items=items))
