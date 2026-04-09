"""Shared provider types for pluggable search skill."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class SearchItem:
    title: str
    url: str = ""
    snippet: str = ""
    source: str = ""
    published_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResponse:
    provider: str
    search_type: str
    items: List[SearchItem] = field(default_factory=list)
    content: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_meaningful(self) -> bool:
        if self.content and len(self.content.strip()) >= 40:
            return True
        return len(self.items) >= 2

    def quality_score(self) -> int:
        if self.error:
            return 0

        score = 0
        if self.content:
            score += min(len(self.content.strip()) // 40, 25)

        non_empty_titles = sum(1 for item in self.items if item.title.strip())
        snippet_rich_items = sum(1 for item in self.items if len(item.snippet.strip()) >= 40)
        source_count = len({item.source.strip().lower() for item in self.items if item.source.strip()})
        dated_items = sum(1 for item in self.items if item.published_at.strip())
        linked_items = sum(1 for item in self.items if item.url.strip())

        score += min(non_empty_titles * 8, 40)
        score += min(snippet_rich_items * 6, 18)
        score += min(source_count * 4, 12)
        score += min(dated_items * 3, 9)
        score += min(linked_items * 2, 8)

        return score


class SearchProvider:
    name = "provider"
    supported_types: Sequence[str] = ("general",)
    priority = 100

    def supports(self, search_type: str) -> bool:
        return search_type in self.supported_types

    async def search(self, query: str, search_type: str, max_results: int) -> SearchResponse:
        raise NotImplementedError
