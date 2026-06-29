# ============================================================
# [JSON API] SFC - 香港证券及期货事务监察委员会 (新闻)
# URL: https://apps.sfc.hk/edistributionWeb/gateway/EN/news-and-announcements/news/
# Search: POST /api/news/search (pageNo, pageSize, lang, year, month, sort)
# Detail: GET /api/news/content?refNo=xxx&lang=EN
# 分页: JSON body, 0-indexed, pageSize 最高可 pull 全部
# ============================================================

import asyncio
import json
import logging
import random
import sys
from pathlib import Path

import httpx
from tqdm import tqdm

logger = logging.getLogger(__name__)


class SFCNewsScraper:
    BASE_URL = "https://apps.sfc.hk"
    SEARCH_URL = f"{BASE_URL}/edistributionWeb/api/news/search"
    CONTENT_URL = f"{BASE_URL}/edistributionWeb/api/news/content"
    SOURCE_NAME = "sfc_news"

    PAGE_SIZE = 200
    REQUEST_DELAY = (0.5, 1.5)
    MAX_RETRIES = 5
    CONCURRENCY = 10

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36",
                "Accept": "application/json, */*",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": f"{self.BASE_URL}/edistributionWeb/gateway/EN/news-and-announcements/news/",
                "Origin": self.BASE_URL,
            },
            follow_redirects=True,
            timeout=60.0,
        )
        self.results: list[dict] = []
        self.data_dir = Path(__file__).resolve().parent.parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._semaphore = asyncio.Semaphore(self.CONCURRENCY)

    async def _rate_limit(self):
        await asyncio.sleep(random.uniform(*self.REQUEST_DELAY))

    async def _post(self, url: str, body: dict) -> dict | None:
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await self.client.post(url, json=body)
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1) + random.uniform(0, 1)
                    logger.warning(f"429 on {url}, retrying in {wait:.1f}s")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
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

    async def _get(self, url: str) -> dict | None:
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = await self.client.get(url)
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1) + random.uniform(0, 1)
                    logger.warning(f"429 on {url}, retrying in {wait:.1f}s")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
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

    def _save(self):
        self.results.sort(key=lambda x: x.get("date", "") or "", reverse=True)
        output_path = self.data_dir / f"{self.SOURCE_NAME}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(self.results)} results to {output_path}")

    async def fetch_page(self, page_no: int) -> list[dict] | None:
        body = {
            "lang": "EN",
            "year": "all",
            "month": "all",
            "pageNo": page_no,
            "pageSize": self.PAGE_SIZE,
            "sort": {"field": "issueDate", "order": "desc"},
        }
        data = await self._post(self.SEARCH_URL, body)
        if data is None:
            return None
        items = data.get("items", [])
        await self._rate_limit()
        return items

    async def _fetch_content(self, ref_no: str) -> str:
        async with self._semaphore:
            url = f"{self.CONTENT_URL}?refNo={ref_no}&lang=EN"
            data = await self._get(url)
            if data is None:
                return ""
            return data.get("html", "")

    async def get_total(self) -> int:
        body = {
            "lang": "EN",
            "year": "all",
            "month": "all",
            "pageNo": 0,
            "pageSize": 1,
            "sort": {"field": "issueDate", "order": "desc"},
        }
        data = await self._post(self.SEARCH_URL, body)
        if data is None:
            return 0
        return data.get("total", 0)

    async def scrape(self, max_pages: int | None = None):
        total = await self.get_total()
        logger.info(f"Total items: {total}")
        total_pages = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        logger.info(f"Total pages (pageSize={self.PAGE_SIZE}): {total_pages}")

        if max_pages is not None:
            total_pages = min(total_pages, max_pages)
            logger.info(f"Limited to {total_pages} pages")

        for page_no in tqdm(range(0, total_pages), desc="SFC news pages"):
            items = await self.fetch_page(page_no)
            if items is None:
                logger.error(f"Failed to fetch page {page_no}, stopping")
                break
            if not items:
                logger.info(f"No items on page {page_no}, stopping")
                break

            async def fetch_one(item: dict) -> dict:
                ref_no = item.get("newsRefNo", "")
                date_str = item.get("issueDate", "")
                content_html = await self._fetch_content(ref_no)
                url = f"{self.BASE_URL}/edistributionWeb/gateway/EN/news-and-announcements/news/{ref_no}"
                return {
                    "date": date_str,
                    "title": item.get("title", ""),
                    "content": content_html,
                    "url": url,
                    "source": self.SOURCE_NAME,
                    "raw": {
                        "newsRefNo": item.get("newsRefNo"),
                        "lang": item.get("lang"),
                        "newsType": item.get("newsType"),
                        "issueDate": item.get("issueDate"),
                        "newsExtLink": item.get("newsExtLink"),
                    },
                }

            tasks = [fetch_one(item) for item in items]
            for coro in tqdm(
                asyncio.as_completed(tasks),
                total=len(tasks),
                desc=f"Page {page_no} details",
                leave=False,
            ):
                self.results.append(await coro)

            self._save()

        self._save()

    async def close(self):
        await self.client.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    async def main():
        scraper = SFCNewsScraper()

        max_pages = None
        if "--pages" in sys.argv:
            idx = sys.argv.index("--pages")
            if idx + 1 < len(sys.argv):
                max_pages = int(sys.argv[idx + 1])

        try:
            await scraper.scrape(max_pages=max_pages)
        finally:
            await scraper.close()

    asyncio.run(main())
