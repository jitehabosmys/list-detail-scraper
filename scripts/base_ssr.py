import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from tqdm import tqdm

logger = logging.getLogger(__name__)


class BaseSSRScraper:
    BASE_URL: str
    SOURCE_NAME: str
    LISTING_PAGE_TEMPLATE: str
    ITEMS_PER_PAGE: int = 25
    MAX_PAGES: int = 500
    REQUEST_DELAY: tuple[float, float] = (1.0, 3.0)
    MAX_RETRIES: int = 5
    CONCURRENCY: int = 5

    NEED_DETAIL: bool = True

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            follow_redirects=True,
            timeout=60.0,
        )
        self.results: list[dict[str, Any]] = []
        self.data_dir = Path(__file__).resolve().parent.parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._semaphore = asyncio.Semaphore(self.CONCURRENCY)

    async def _rate_limit(self):
        await asyncio.sleep(random.uniform(*self.REQUEST_DELAY))

    async def _fetch(self, url: str) -> str | None:
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await self.client.get(url)
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1) + random.uniform(0, 1)
                    logger.warning(f"429 on {url}, retrying in {wait:.1f}s")
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code in (403, 405):
                    logger.warning(f"{resp.status_code} on {url}, retrying after delay")
                    await asyncio.sleep(5)
                    continue
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error {e.response.status_code} on {url}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                else:
                    return None
            except httpx.RequestError as e:
                logger.error(f"Request error on {url}: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                else:
                    return None
        return None

    async def fetch_listing(self, page: int) -> str | None:
        url = self.LISTING_PAGE_TEMPLATE.format(page=page)
        return await self._fetch(url)

    async def _fetch_detail(self, url: str) -> str | None:
        await self._rate_limit()
        async with self._semaphore:
            return await self._fetch(url)

    def parse_listing_page(self, html: str) -> tuple[list[dict], bool]:
        raise NotImplementedError

    def parse_detail_page(self, html: str, item: dict) -> str:
        raise NotImplementedError

    def _save(self):
        self.results.sort(key=lambda x: x.get("date", "") or "", reverse=True)
        output_path = self.data_dir / f"{self.SOURCE_NAME}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(self.results)} results to {output_path}")

    async def scrape(self, max_pages: int | None = None, start_page: int = 0):
        if max_pages is not None:
            self.MAX_PAGES = max_pages

        for page in range(start_page, self.MAX_PAGES):
            logger.info(f"Fetching listing page {page}...")
            html = await self.fetch_listing(page)
            if html is None:
                logger.error(f"Failed to fetch page {page}, stopping")
                break

            items, has_more = self.parse_listing_page(html)
            if not items:
                logger.info(f"No items on page {page}, stopping")
                break

            async def fetch_one(item: dict) -> dict:
                if self.NEED_DETAIL and item.get("url"):
                    detail_html = await self._fetch_detail(item["url"])
                    item["content"] = (
                        self.parse_detail_page(detail_html, item)
                        if detail_html
                        else ""
                    )
                else:
                    item["content"] = item.get("content", "")
                item.setdefault("source", self.SOURCE_NAME)
                item.setdefault("raw", {})
                return item

            tasks = [fetch_one(item) for item in items]
            for coro in tqdm(
                asyncio.as_completed(tasks), total=len(tasks), desc=f"Page {page}"
            ):
                self.results.append(await coro)

            self._save()

            if not has_more:
                logger.info("No more pages")
                break

            await self._rate_limit()

        self._save()

    async def close(self):
        await self.client.aclose()
