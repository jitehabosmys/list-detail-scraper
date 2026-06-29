# ============================================================
# [SSR单页+Sitemap] FCA - 英国金融行为监管局
# URL: https://www.fca.org.uk/news/search-results?category=press%20releases
# 发现: 列表页被Cloudflare Turnstile保护, 详情页SSR可直接访问
# 策略: 从sitemap.xml提取所有press-releases URL, 再并发抓取详情页
# 详情: SSR, h1/time[datetime]/article
# ============================================================

import asyncio
import json
import logging
import random
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from tqdm import tqdm

logger = logging.getLogger(__name__)

SITEMAP_URLS = [
    "https://www.fca.org.uk/sitemap.xml?page=1",
    "https://www.fca.org.uk/sitemap.xml?page=2",
]
BASE_URL = "https://www.fca.org.uk"
SOURCE_NAME = "fca"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

REQUEST_DELAY = (1.0, 3.0)
MAX_RETRIES = 5
CONCURRENCY = 10

results: list[dict] = []


async def fetch_url(client: httpx.AsyncClient, url: str) -> str | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url)
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
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} on {url}")
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


def extract_pr_urls_from_sitemap(xml_content: str) -> list[str]:
    return re.findall(
        r"<loc>(https://www\.fca\.org\.uk/news/press-releases/[^<]+)</loc>",
        xml_content,
    )


def parse_detail_page(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.select_one("h1")
    if not title_el:
        return None
    title = title_el.get_text(strip=True)

    date_el = soup.select_one("time[datetime]")
    date = date_el.get("datetime", "") if date_el else ""

    content_el = soup.select_one("article")
    content = content_el.get_text(separator="\n", strip=True) if content_el else ""

    if not content:
        for sel in ["main[role=main]", ".c-article__body", ".field--name-body"]:
            el = soup.select_one(sel)
            if el:
                content = el.get_text(separator="\n", strip=True)
                break

    return {
        "date": date,
        "title": title,
        "content": content,
        "url": url,
        "source": SOURCE_NAME,
        "raw": {},
    }


def save():
    results.sort(key=lambda x: x.get("date", "") or "", reverse=True)
    output_path = DATA_DIR / f"{SOURCE_NAME}.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(results)} results to {output_path}")


async def scrape(max_urls: int | None = None):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    }

    async with httpx.AsyncClient(
        headers=headers, follow_redirects=True, timeout=30.0
    ) as client:
        logger.info("Fetching sitemap to discover press release URLs...")
        all_pr_urls: list[str] = []
        for sitemap_url in SITEMAP_URLS:
            xml = await fetch_url(client, sitemap_url)
            if xml:
                urls = extract_pr_urls_from_sitemap(xml)
                logger.info(f"Found {len(urls)} PR URLs in {sitemap_url}")
                all_pr_urls.extend(urls)

        logger.info(f"Total press release URLs found: {len(all_pr_urls)}")

        if max_urls is not None:
            all_pr_urls = all_pr_urls[:max_urls]
            logger.info(f"Limiting to first {max_urls} URLs for testing")

        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def fetch_one(url: str) -> dict | None:
            async with semaphore:
                await asyncio.sleep(random.uniform(*REQUEST_DELAY))
                html = await fetch_url(client, url)
                if html is None:
                    return None
                return parse_detail_page(html, url)

        tasks = [fetch_one(url) for url in all_pr_urls]
        for coro in tqdm(
            asyncio.as_completed(tasks),
            total=len(tasks),
            desc="FCA Press Releases",
        ):
            item = await coro
            if item:
                results.append(item)

            if len(results) % 50 == 0:
                save()

        save()


def main():
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    max_urls = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--pages" and i + 1 < len(args):
            val = args[i + 1]
            if val.lower() == "all" or val == "0":
                max_urls = None
            else:
                max_urls = int(val)

    asyncio.run(scrape(max_urls=max_urls))


if __name__ == "__main__":
    main()
