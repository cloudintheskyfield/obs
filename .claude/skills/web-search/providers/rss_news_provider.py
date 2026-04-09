"""News provider using Google News RSS."""

from __future__ import annotations

from email.utils import parsedate_to_datetime
from typing import List
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import httpx

from provider_types import SearchItem, SearchProvider, SearchResponse


class GoogleNewsRssProvider(SearchProvider):
    name = "google_news_rss"
    supported_types = ("news",)
    priority = 20

    async def search(self, query: str, search_type: str, max_results: int) -> SearchResponse:
        rss_query = quote_plus(query)
        url = (
            "https://news.google.com/rss/search"
            f"?q={rss_query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        )
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()

        root = ET.fromstring(response.text)
        channel = root.find("channel")
        if channel is None:
            return SearchResponse(provider=self.name, search_type=search_type, error="RSS 响应格式异常")

        items: List[SearchItem] = []
        for item in channel.findall("item")[:max_results]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            source = ""
            source_tag = item.find("source")
            if source_tag is not None and source_tag.text:
                source = source_tag.text.strip()

            title_main = title
            if " - " in title and not source:
                parts = title.rsplit(" - ", 1)
                title_main = parts[0].strip()
                source = parts[1].strip()

            published_at = ""
            if pub_date:
                try:
                    published_at = parsedate_to_datetime(pub_date).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    published_at = pub_date

            items.append(
                SearchItem(
                    title=title_main,
                    url=link,
                    snippet="",
                    source=source or "Google News",
                    published_at=published_at,
                )
            )

        return SearchResponse(provider=self.name, search_type=search_type, items=items)


PROVIDER_CLASS = GoogleNewsRssProvider
