"""Pluggable web search skill with provider auto-discovery."""

from __future__ import annotations

import importlib.util
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from base_skill import BaseSkill, SkillResult


CURRENT_DIR = Path(__file__).resolve().parent
PROVIDERS_DIR = CURRENT_DIR / "providers"

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from provider_types import SearchProvider, SearchResponse  # noqa: E402


class AdvancedWebSearchSkill(BaseSkill):
    """Web search skill with plugin-like providers."""

    def __init__(self):
        super().__init__(
            name="advanced_web_search",
            description="Search the web for current information using pluggable providers.",
        )
        self.add_parameter("query", "str", "Search query", True)
        self.add_parameter("type", "str", "Search type: general, weather, news, finance", False)
        self.add_parameter("engine", "str", "Optional provider name override", False)
        self.add_parameter("max_results", "int", "Maximum number of results", False)
        self.add_parameter("current_date", "str", "Current date in YYYY-MM-DD format", False)
        self.add_parameter("current_time", "str", "Current time in HH:MM:SS format", False)
        self.add_parameter("timezone", "str", "Current timezone name", False)
        self.add_parameter("city", "str", "Approximate user city", False)
        self.add_parameter("region", "str", "Approximate user region", False)
        self.add_parameter("country_name", "str", "Approximate user country", False)
        self.providers = self._load_providers()

    async def execute(self, **kwargs) -> SkillResult:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return SkillResult(success=False, error="搜索查询不能为空")

        search_type = (kwargs.get("type") or "general").strip().lower()
        if search_type == "general":
            search_type = self._detect_search_type(query)

        engine = (kwargs.get("engine") or "").strip().lower() or None
        max_results = int(kwargs.get("max_results") or 5)
        runtime_context = {
            "current_date": (kwargs.get("current_date") or "").strip(),
            "current_time": (kwargs.get("current_time") or "").strip(),
            "timezone": (kwargs.get("timezone") or "").strip(),
            "city": (kwargs.get("city") or "").strip(),
            "region": (kwargs.get("region") or "").strip(),
            "country_name": (kwargs.get("country_name") or "").strip(),
        }
        query = self._rewrite_query_with_runtime_context(query, search_type, runtime_context)

        logger.info(f"Advanced search: query={query!r}, type={search_type}, engine={engine or 'auto'}")

        providers = self._select_providers(search_type, engine)
        if not providers:
            return SkillResult(
                success=True,
                content=self._build_unavailable_message(query, search_type, []),
                metadata={"query": query, "search_type": search_type, "providers_tried": []},
            )

        warnings: List[str] = []
        attempted: List[str] = []
        best_response: Optional[SearchResponse] = None
        best_score = -1

        for provider in providers:
            attempted.append(provider.name)
            try:
                response = await provider.search(
                    query=query,
                    search_type=search_type,
                    max_results=max_results,
                )
            except Exception as exc:
                logger.exception(f"Search provider {provider.name} crashed")
                warnings.append(f"{provider.name}: {exc}")
                continue

            if response.error:
                warnings.append(f"{provider.name}: {response.error}")
                continue

            if response.content or response.items:
                score = response.quality_score()
                if score > best_score:
                    best_response = response
                    best_score = score
                if response.is_meaningful() and score >= 48:
                    break

        if best_response is None:
            return SkillResult(
                success=True,
                content=self._build_unavailable_message(query, search_type, warnings),
                metadata={"query": query, "search_type": search_type, "providers_tried": attempted},
            )

        content = best_response.content or self._format_items(best_response, query, search_type)
        content = self._append_footer(content, best_response, attempted, warnings)
        return SkillResult(
            success=True,
            content=content,
            metadata={
                "query": query,
                "search_type": search_type,
                "provider": best_response.provider,
                "providers_tried": attempted,
                "result_count": len(best_response.items),
                "quality_score": best_score,
            },
        )

    def _detect_search_type(self, query: str) -> str:
        lowered = query.lower()
        if any(token in lowered for token in ["天气", "weather", "气温", "温度", "下雨", "forecast"]):
            return "weather"
        if any(token in lowered for token in ["新闻", "news", "热点", "头条", "breaking", "latest"]):
            return "news"
        if any(token in lowered for token in ["股价", "股票", "汇率", "finance", "stock", "$"]):
            return "finance"
        return "general"

    def _load_providers(self) -> List[SearchProvider]:
        providers: List[SearchProvider] = []
        if not PROVIDERS_DIR.exists():
            logger.warning(f"Providers directory not found: {PROVIDERS_DIR}")
            return providers

        for path in sorted(PROVIDERS_DIR.glob("*.py")):
            if path.name.startswith("_"):
                continue
            provider = self._load_provider_from_file(path)
            if provider is not None:
                providers.append(provider)

        providers.sort(key=lambda item: (item.priority, item.name))
        logger.info(f"Loaded search providers: {[provider.name for provider in providers]}")
        return providers

    def _load_provider_from_file(self, path: Path) -> Optional[SearchProvider]:
        spec = importlib.util.spec_from_file_location(f"search_provider_{path.stem}", path)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        if hasattr(module, "get_provider"):
            provider = module.get_provider()
            if isinstance(provider, SearchProvider):
                return provider

        provider_class = getattr(module, "PROVIDER_CLASS", None)
        if provider_class is not None:
            provider = provider_class()
            if isinstance(provider, SearchProvider):
                return provider

        return None

    def _rewrite_query_with_runtime_context(
        self,
        query: str,
        search_type: str,
        runtime_context: Dict[str, str],
    ) -> str:
        rewritten = query.strip()
        if not rewritten:
            return rewritten

        current_date = runtime_context.get("current_date") or ""
        city = runtime_context.get("city") or ""
        country_name = runtime_context.get("country_name") or ""
        has_explicit_date = bool(re.search(r"\b20\d{2}[-/年]\d{1,2}([-/月]\d{1,2}日?)?\b", rewritten))
        has_relative_today = bool(re.search(r"(今日|今天|today|latest|current|recent|hot news|头条|热点)", rewritten, re.IGNORECASE))

        if search_type == "news":
            qualifiers: List[str] = []
            if current_date and (has_relative_today or not has_explicit_date):
                qualifiers.append(current_date)
            if city:
                qualifiers.append(city)
            elif country_name:
                qualifiers.append(country_name)
            if qualifiers:
                rewritten = " ".join(dict.fromkeys([*qualifiers, rewritten]))

        return rewritten

    def _select_providers(self, search_type: str, engine: Optional[str]) -> List[SearchProvider]:
        selected = [
            provider for provider in self.providers
            if provider.supports(search_type) and (engine is None or provider.name == engine)
        ]
        return selected

    def _format_items(self, response: SearchResponse, query: str, search_type: str) -> str:
        if search_type == "news":
            lines = [f"## 今日新闻结果", ""]
            for index, item in enumerate(response.items, start=1):
                lines.append(f"### {index}. {item.title}")
                if item.source:
                    lines.append(f"- 来源: {item.source}")
                if item.published_at:
                    lines.append(f"- 时间: {item.published_at}")
                if item.snippet:
                    lines.append(f"- 摘要: {item.snippet}")
                if item.url:
                    lines.append(f"- 链接: {item.url}")
                lines.append("")
            return "\n".join(lines).strip()

        if search_type == "finance":
            title = f"## 财经搜索结果"
        else:
            title = f"## 搜索结果"

        lines = [title, ""]
        for index, item in enumerate(response.items, start=1):
            lines.append(f"### {index}. {item.title}")
            if item.snippet:
                lines.append(f"- 摘要: {item.snippet}")
            if item.source:
                lines.append(f"- 来源: {item.source}")
            if item.url:
                lines.append(f"- 链接: {item.url}")
            lines.append("")
        return "\n".join(lines).strip()

    def _append_footer(
        self,
        content: str,
        response: SearchResponse,
        attempted: List[str],
        warnings: List[str],
    ) -> str:
        lines = [content, "", "---", f"数据提供方: `{response.provider}`"]
        if attempted:
            lines.append(f"已尝试 provider: `{', '.join(attempted)}`")
        if warnings:
            lines.append(f"降级记录: `{'; '.join(warnings[:3])}`")
        return "\n".join(lines).strip()

    def _build_unavailable_message(self, query: str, search_type: str, warnings: List[str]) -> str:
        lines = [
            f"我暂时没有拿到关于“{query}”的可靠实时结果。",
            "",
            "建议直接查看这些来源：",
        ]
        if search_type == "news":
            lines.extend([
                "- 新华网: https://www.news.cn",
                "- 人民网: https://www.people.com.cn",
                "- Google News: https://news.google.com",
            ])
        elif search_type == "weather":
            lines.extend([
                "- 中国天气网: https://www.weather.com.cn",
                "- Weather.com: https://weather.com",
            ])
        else:
            lines.extend([
                "- Google: https://www.google.com",
                "- Bing: https://www.bing.com",
            ])
        if warnings:
            lines.extend(["", f"错误摘要: {'; '.join(warnings[:3])}"])
        return "\n".join(lines)
