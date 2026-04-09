"""HTML search provider backed by Brave Search."""

from __future__ import annotations

from typing import List
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from provider_types import SearchItem, SearchProvider, SearchResponse


class BraveHtmlProvider(SearchProvider):
    name = "brave_html"
    supported_types = ("general", "news", "finance")
    priority = 12

    async def search(self, query: str, search_type: str, max_results: int) -> SearchResponse:
        source = "news" if search_type == "news" else "web"
        url = f"https://search.brave.com/search?q={quote_plus(query)}&source={source}"

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        nodes = soup.select('[data-type="web"]')
        items: List[SearchItem] = []

        for node in nodes:
            anchor = node.select_one("a[href^='http']")
            title_node = node.select_one(".title") or anchor
            snippet_node = node.select_one(".generic-snippet .content")
            source_node = node.select_one(".site-name-content .desktop-small-semibold")
            url_node = node.select_one("cite")

            title = title_node.get_text(" ", strip=True) if title_node else ""
            link = (anchor.get("href") or "").strip() if anchor else ""
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            source_label = source_node.get_text(" ", strip=True) if source_node else ""
            shown_url = url_node.get_text(" ", strip=True) if url_node else ""

            if not title or not link:
                continue

            items.append(
                SearchItem(
                    title=title,
                    url=link,
                    snippet=snippet,
                    source=source_label or shown_url or "Brave Search",
                )
            )
            if len(items) >= max_results:
                break

        return SearchResponse(provider=self.name, search_type=search_type, items=items)


PROVIDER_CLASS = BraveHtmlProvider
