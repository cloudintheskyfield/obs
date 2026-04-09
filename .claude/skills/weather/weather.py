"""Weather skill using wttr.in for current conditions."""

from __future__ import annotations

import httpx

from base_skill import BaseSkill, SkillResult


class WeatherSkill(BaseSkill):
    def __init__(self):
        super().__init__(
            name="weather",
            description="Get current weather for a city or coordinates.",
        )
        self.add_parameter(
            name="city",
            param_type="str",
            description="City name for the weather lookup.",
            required=False,
        )
        self.add_parameter(
            name="lat",
            param_type="float",
            description="Latitude for precise weather lookup.",
            required=False,
        )
        self.add_parameter(
            name="lon",
            param_type="float",
            description="Longitude for precise weather lookup.",
            required=False,
        )

    async def execute(self, **kwargs) -> SkillResult:
        city = (kwargs.get("city") or "").strip()
        lat = kwargs.get("lat")
        lon = kwargs.get("lon")

        if not city and (lat is None or lon is None):
            return SkillResult(success=False, error="Please provide either `city` or both `lat` and `lon`.")

        location = city or f"{float(lat)},{float(lon)}"
        params = {"format": "j1", "lang": "zh"}
        headers = {
            "User-Agent": "Mozilla/5.0",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"https://wttr.in/{location}", params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()

            current = (payload.get("current_condition") or [{}])[0]
            area = (payload.get("nearest_area") or [{}])[0]
            resolved_city = city or (area.get("areaName") or [{}])[0].get("value") or location

            content = "\n".join(
                [
                    f"## {resolved_city} 实时天气",
                    f"- 温度: **{current.get('temp_C', '--')}°C**",
                    f"- 体感温度: **{current.get('FeelsLikeC', '--')}°C**",
                    f"- 天气: **{((current.get('lang_zh') or current.get('weatherDesc') or [{}])[0]).get('value', '--')}**",
                    f"- 湿度: **{current.get('humidity', '--')}%**",
                    f"- 风速: **{current.get('windspeedKmph', '--')} km/h**",
                    f"- 观测时间: `{current.get('observation_time', '--')}`",
                    "",
                    "数据来源: `wttr.in`",
                ]
            )

            return SkillResult(
                success=True,
                content=content,
                metadata={"location": resolved_city, "source": "wttr.in"},
            )
        except Exception as exc:
            return SkillResult(success=False, error=f"Weather lookup failed: {exc}")
