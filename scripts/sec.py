# ============================================================
# [SSR HTML] SEC - 美国证券交易委员会 Press Releases
# URL: https://www.sec.gov/newsroom/press-releases
# 策略: curl_cffi impersonate（Akamai CDN 防护）
# 分页: ?page=N, 0-indexed, 25条/页, 共151页(3767条)
# 详情: .field--name-body
# ============================================================

import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from tqdm import tqdm

logger = logging.getLogger(__name__)

BASE_URL = "https://www.sec.gov"
LISTING_URL = "https://www.sec.gov/newsroom/press-releases"
SOURCE_NAME = "sec"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

REQUEST_DELAY = (1.5, 3.5)
MAX_RETRIES = 5
CONCURRENCY = 5


async def fetch_page(session: AsyncSession, url: str) -> str | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = await session.get(url, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1) + random.uniform(0, 1)
                logger.warning(f"429 on {url}, retrying in {wait:.1f}s")
                await asyncio.sleep(wait)
                continue
            if resp.status_code in (403, 404):
                logger.warning(f"{resp.status_code} on {url}, not retrying")
                return None
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.error(f"Failed {url} (attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** (attempt + 1))
            else:
                return None
    return None


def parse_listing(html: str) -> tuple[list[dict], bool]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("tr.pr-list-page-row")
    items = []
    for row in rows:
        title_el = row.select_one("td.views-field-field-display-title a")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        url = BASE_URL + href if href.startswith("/") else href

        date_el = row.select_one("td.views-field-field-publish-date time")
        date = date_el.get("datetime", "") if date_el else ""

        release_el = row.select_one("td.views-field-field-release-number")
        release_number = release_el.get_text(strip=True) if release_el else ""

        items.append({
            "date": date,
            "title": title,
            "url": url,
            "content": "",
            "release_number": release_number,
            "source": SOURCE_NAME,
            "raw": {},
        })

    has_next = bool(soup.select_one("a.usa-pagination__next-page"))
    return items, has_next


def parse_detail(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    body_el = soup.select_one(".field--name-body")
    if body_el:
        return body_el.get_text(separator="\n", strip=True)
    return ""


async def main(max_pages=2):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    async with AsyncSession(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        },
        impersonate="chrome120",
    ) as session:
        for pg in range(max_pages):
            url = f"{LISTING_URL}?page={pg}"
            logger.info(f"Fetching listing page {pg}...")
            html = await fetch_page(session, url)
            if not html:
                logger.error(f"Failed page {pg}, stopping")
                break

            items, has_more = parse_listing(html)
            if not items:
                logger.info(f"No items on page {pg}, stopping")
                break

            sem = asyncio.Semaphore(CONCURRENCY)

            async def fetch_detail(item: dict) -> dict:
                async with sem:
                    detail_html = await fetch_page(session, item["url"])
                    if detail_html:
                        content = parse_detail(detail_html)
                        if content:
                            item["content"] = content
                    await asyncio.sleep(random.uniform(*REQUEST_DELAY))
                    return item

            tasks = [fetch_detail(item) for item in items]
            for coro in tqdm(
                asyncio.as_completed(tasks), total=len(tasks), desc=f"Page {pg}"
            ):
                results.append(await coro)

            results.sort(key=lambda x: x.get("date", "") or "", reverse=True)
            output_path = DATA_DIR / f"{SOURCE_NAME}.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(results)} results")

            if not has_more:
                logger.info("No more pages")
                break

    results.sort(key=lambda x: x.get("date", "") or "", reverse=True)
    output_path = DATA_DIR / f"{SOURCE_NAME}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"Done. Total: {len(results)} results")


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    pages = 2
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        pages = 151
    elif len(sys.argv) > 1:
        try:
            pages = int(sys.argv[1])
        except ValueError:
            pass
    asyncio.run(main(max_pages=pages))
