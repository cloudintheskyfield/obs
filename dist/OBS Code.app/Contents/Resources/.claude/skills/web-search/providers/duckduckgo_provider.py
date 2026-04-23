"""DuckDuckGo instant answer fallback provider."""

from __future__ import annotations

from typing import List
from urllib.parse import quote_plus

import httpx

from provider_types import SearchItem, SearchProvider, SearchResponse


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"
    supported_types = ("general", "finance")
    priority = 70

    async def search(self, query: str, search_type: str, max_results: int) -> SearchResponse:
        url = (
            "https://api.duckduckgo.com/"
            f"?q={quote_plus(query)}&format=json&no_redirect=1&skip_disambig=1"
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            payload = response.json()

        items: List[SearchItem] = []
        abstract = (payload.get("AbstractText") or "").strip()
        abstract_url = (payload.get("AbstractURL") or "").strip()
        heading = (payload.get("Heading") or "").strip()
        if abstract:
            items.append(
                SearchItem(
                    title=heading or query,
                    url=abstract_url,
                    snippet=abstract,
                    source="DuckDuckGo",
                )
            )

        for topic in payload.get("RelatedTopics") or []:
            if not isinstance(topic, dict) or "Text" not in topic:
                continue
            items.append(
                SearchItem(
                    title=(topic.get("Text") or "").strip()[:120],
                    url=(topic.get("FirstURL") or "").strip(),
                    snippet=(topic.get("Text") or "").strip(),
                    source="DuckDuckGo",
                )
            )
            if len(items) >= max_results:
                break

        return SearchResponse(provider=self.name, search_type=search_type, items=items[:max_results])


PROVIDER_CLASS = DuckDuckGoProvider
