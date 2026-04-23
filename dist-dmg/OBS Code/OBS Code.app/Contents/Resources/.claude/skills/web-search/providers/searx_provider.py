"""Generic search provider backed by SearX."""

from __future__ import annotations

from typing import List
from urllib.parse import urlencode

import httpx

from provider_types import SearchItem, SearchProvider, SearchResponse


class SearxProvider(SearchProvider):
    name = "searx"
    supported_types = ("general", "news", "finance")
    priority = 40

    async def search(self, query: str, search_type: str, max_results: int) -> SearchResponse:
        params = {
            "q": query,
            "format": "json",
            "engines": "google,bing,duckduckgo",
            "safesearch": "1",
        }
        if search_type == "news":
            params["categories"] = "news"
        url = f"https://searx.be/search?{urlencode(params)}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            payload = response.json()

        items: List[SearchItem] = []
        for item in (payload.get("results") or [])[:max_results]:
            items.append(
                SearchItem(
                    title=(item.get("title") or "").strip(),
                    url=(item.get("url") or "").strip(),
                    snippet=(item.get("content") or "").strip(),
                    source="SearX",
                )
            )

        return SearchResponse(provider=self.name, search_type=search_type, items=items)


PROVIDER_CLASS = SearxProvider
