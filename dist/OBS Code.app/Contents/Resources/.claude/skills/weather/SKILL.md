---
name: weather
description: Get current weather for a city or coordinates, including temperature, feels-like, humidity, and wind
---

# Weather Skill

Use this skill when the user explicitly asks for current weather, temperature, rain conditions, or short-term local weather status.

## Parameters

- `city` (optional): City name, e.g. `Beijing`, `Shanghai`
- `lat` (optional): Latitude for precise local weather
- `lon` (optional): Longitude for precise local weather

## Examples

```python
await execute_skill("weather", city="Beijing")
await execute_skill("weather", lat=39.9042, lon=116.4074)
```
