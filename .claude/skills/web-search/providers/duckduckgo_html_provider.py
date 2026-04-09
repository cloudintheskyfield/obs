"""HTML search provider backed by DuckDuckGo."""

from __future__ import annotations

from typing import List
from urllib.parse import parse_qs, quote_plus, urlparse, unquote

import httpx
from bs4 import BeautifulSoup

from provider_types import SearchItem, SearchProvider, SearchResponse


class DuckDuckGoHtmlProvider(SearchProvider):
    name = "duckduckgo_html"
    supported_types = ("general", "news", "finance")
    priority = 24

    async def search(self, query: str, search_type: str, max_results: int) -> SearchResponse:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        items: List[SearchItem] = []

        for node in soup.select(".result"):
            title_node = node.select_one(".result__title .result__a")
            snippet_node = node.select_one(".result__snippet")
            source_node = node.select_one(".result__url")

            title = title_node.get_text(" ", strip=True) if title_node else ""
            raw_link = (title_node.get("href") or "").strip() if title_node else ""
            source = source_node.get_text(" ", strip=True) if source_node else ""
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            link = self._unwrap_duckduckgo_redirect(raw_link)

            if not title or not link:
                continue

            items.append(
                SearchItem(
                    title=title,
                    url=link,
                    snippet=snippet,
                    source=source or "DuckDuckGo",
                )
            )
            if len(items) >= max_results:
                break

        return SearchResponse(provider=self.name, search_type=search_type, items=items)

    def _unwrap_duckduckgo_redirect(self, raw_link: str) -> str:
        if raw_link.startswith("//"):
            raw_link = f"https:{raw_link}"
        parsed = urlparse(raw_link)
        if "duckduckgo.com" not in parsed.netloc:
            return raw_link
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target) if target else raw_link


PROVIDER_CLASS = DuckDuckGoHtmlProvider
