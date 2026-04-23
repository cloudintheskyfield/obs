"""Weather provider using wttr.in."""

from __future__ import annotations

from datetime import datetime

import httpx

from provider_types import SearchProvider, SearchResponse


class WeatherProvider(SearchProvider):
    name = "wttr_weather"
    supported_types = ("weather",)
    priority = 10

    async def search(self, query: str, search_type: str, max_results: int) -> SearchResponse:
        city = self._extract_city(query)
        url = f"https://wttr.in/{city}?format=j1&lang=zh"

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            payload = response.json()

        current = (payload.get("current_condition") or [{}])[0]
        resolved_city = city or "当前位置"
        description = ((current.get("lang_zh") or current.get("weatherDesc") or [{}])[0]).get("value", "--")
        content = "\n".join(
            [
                f"## {resolved_city} 实时天气",
                f"- 温度: **{current.get('temp_C', '--')}°C**",
                f"- 体感温度: **{current.get('FeelsLikeC', '--')}°C**",
                f"- 天气: **{description}**",
                f"- 湿度: **{current.get('humidity', '--')}%**",
                f"- 风速: **{current.get('windspeedKmph', '--')} km/h**",
                f"- 观测时间: `{current.get('observation_time', '--')}`",
                f"- 更新时间: `{datetime.now().strftime('%Y-%m-%d %H:%M')}`",
            ]
        )
        return SearchResponse(provider=self.name, search_type=search_type, content=content)

    def _extract_city(self, query: str) -> str:
        candidates = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "重庆", "武汉", "西安"]
        for city in candidates:
            if city in query:
                return city

        stripped = query
        for token in ["天气", "气温", "温度", "怎么样", "weather", "forecast", "today", "today's"]:
            stripped = stripped.replace(token, " ")
        stripped = " ".join(stripped.split())
        return stripped or "beijing"


PROVIDER_CLASS = WeatherProvider

