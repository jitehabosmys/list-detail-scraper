# ============================================================
# [ASP.NET Postback] Thailand SEC - 泰国证券交易委员会
# URL: https://www.sec.or.th/EN/Pages/News_LISTVIEW.aspx
# 分页: ASP.NET postback, 10条/页
# 详情: postback 获取, full article content
# ============================================================

import asyncio
import json
import logging
import random
import re
import sys
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from tqdm import tqdm

logger = logging.getLogger(__name__)

BASE_URL = "https://www.sec.or.th"
LIST_URL = "https://www.sec.or.th/EN/Pages/News_LISTVIEW.aspx"
SOURCE_NAME = "thailand_sec"

REQUEST_DELAY = (1.0, 2.0)
MAX_RETRIES = 5
CONCURRENCY = 5


class ThailandSECScraper:
    def __init__(self):
        self.client = AsyncSession(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            impersonate="chrome120",
            timeout=60.0,
        )
        self.results: list[dict[str, Any]] = []
        self.data_dir = Path(__file__).resolve().parent.parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _rate_limit(self):
        await asyncio.sleep(random.uniform(*REQUEST_DELAY))

    async def _fetch(self, url: str, method: str = "GET", data: dict | None = None) -> str | None:
        for attempt in range(MAX_RETRIES):
            try:
                if method == "POST":
                    resp = await self.client.post(url, data=data)
                else:
                    resp = await self.client.get(url)
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1) + random.uniform(0, 1)
                    logger.warning(f"429 on {url}, retrying in {wait:.1f}s")
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code == 403:
                    logger.warning(f"403 on {url}, retrying after delay")
                    await asyncio.sleep(5)
                    continue
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                logger.error(f"Error on {url} (attempt {attempt + 1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                else:
                    return None
        return None

    def _extract_form_fields(self, html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "lxml")
        form = soup.find("form", id="aspnetForm")
        if not form:
            return {}
        fields = {}
        for inp in form.find_all("input", type="hidden"):
            name = inp.get("name")
            value = inp.get("value", "")
            if name:
                fields[name] = value
        return fields

    def _extract_event_targets(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        items = []
        table = soup.find("table", id="grdView")
        if not table:
            return items

        rows = table.find_all("tr")
        for row in rows:
            title_link = row.find("a", id="lblTitle")
            if not title_link:
                continue

            onclick = title_link.get("href", "")
            event_target = ""
            m = re.search(
                r'WebForm_DoPostBackWithOptions\(new\s+WebForm_PostBackOptions\("([^"]+)"',
                onclick,
            )
            if m:
                event_target = m.group(1)

            news_no_el = row.find("span", id="lblNewsNo")
            news_no = news_no_el.get_text(strip=True) if news_no_el else ""

            title = title_link.get_text(strip=True)

            date_el = row.find("span", id="lblActiveDate")
            date = date_el.get_text(strip=True) if date_el else ""

            if title and event_target:
                items.append({
                    "news_no": news_no,
                    "title": title,
                    "date": date,
                    "event_target": event_target,
                })
        return items

    def _extract_next_page_target(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        for link in soup.find_all("a", href=re.compile(r"\$lnkNext\"")):
            onclick = link.get("href", "")
            if not onclick or "javascript:void" in onclick:
                continue
            m = re.search(
                r'WebForm_DoPostBackWithOptions\(new\s+WebForm_PostBackOptions\("([^"]+)"',
                onclick,
            )
            if m:
                return m.group(1)
        return None

    def parse_detail_page(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        content_parts = []

        highlight = soup.find("span", id=re.compile(r"lblHighlight$"), class_=re.compile(r"RecapnewsDetail"))
        news_desc = soup.find("div", id=re.compile(r"lblNewsDesc$"), class_=re.compile(r"DescriptNewsDetail"))

        if highlight:
            txt = highlight.get_text(strip=True)
            if txt:
                content_parts.append(txt)

        if news_desc:
            for p in news_desc.find_all("p"):
                txt = p.get_text(strip=True)
                if txt:
                    content_parts.append(txt)

        if not content_parts:
            for el in soup.find_all(["span", "div"], id=re.compile(r"lblHighlight|lblNewsDesc|Highlight|NewsDesc")):
                txt = el.get_text(strip=True)
                if txt and len(txt) > 50:
                    content_parts.append(txt)

        seen = set()
        unique = []
        for p in content_parts:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return "\n\n".join(unique)

    def _save(self):
        self.results.sort(key=lambda x: x.get("date", "") or "", reverse=True)
        output_path = self.data_dir / f"{SOURCE_NAME}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(self.results)} results to {output_path}")

    async def scrape(self, max_pages: int = 2):
        page_html = await self._fetch(LIST_URL)
        if not page_html:
            logger.error("Failed to fetch initial page")
            return

        for page_idx in range(max_pages):
            logger.info(f"Processing page {page_idx + 1}...")

            form_fields = self._extract_form_fields(page_html)
            items = self._extract_event_targets(page_html)
            if not items:
                logger.info(f"No items found on page {page_idx + 1}, stopping")
                break

            logger.info(f"Found {len(items)} items on page {page_idx + 1}")

            async def fetch_detail(item: dict) -> dict:
                async with self._semaphore:
                    data = dict(form_fields)
                    data["__EVENTTARGET"] = item["event_target"]
                    data["__EVENTARGUMENT"] = ""
                    detail_html = await self._fetch(LIST_URL, method="POST", data=data)
                    if detail_html:
                        content = self.parse_detail_page(detail_html)
                    else:
                        content = ""
                    return {
                        "date": item["date"],
                        "title": item["title"],
                        "content": content,
                        "url": LIST_URL,
                        "source": SOURCE_NAME,
                        "raw": {
                            "news_no": item["news_no"],
                            "event_target": item["event_target"],
                        },
                    }

            tasks = [fetch_detail(item) for item in items]
            for coro in tqdm(
                asyncio.as_completed(tasks),
                total=len(tasks),
                desc=f"Page {page_idx + 1}",
            ):
                self.results.append(await coro)

            self._save()

            next_target = self._extract_next_page_target(page_html)
            if not next_target:
                logger.info("No more pages")
                break

            await self._rate_limit()
            data = dict(form_fields)
            data["__EVENTTARGET"] = next_target
            data["__EVENTARGUMENT"] = ""
            next_html = await self._fetch(LIST_URL, method="POST", data=data)
            if not next_html:
                logger.error("Failed to navigate to next page")
                break
            page_html = next_html

        self._save()

    async def close(self):
        await self.client.close()


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    max_pages = 500
    if len(sys.argv) > 1 and sys.argv[1] == "--pages" and len(sys.argv) > 2:
        max_pages = int(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        max_pages = int(sys.argv[1])

    scraper = ThailandSECScraper()
    try:
        await scraper.scrape(max_pages=max_pages)
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
