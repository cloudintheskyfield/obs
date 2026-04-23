---
name: web-search
description: Search the internet for real-time information like weather, news, stock prices, and latest updates
---

# Web Search Skill

This skill enables searching the internet to retrieve real-time information when current data or latest updates are needed.

## Quick Start

Use this skill to search for:
- Current weather conditions
- Latest news and updates
- Stock prices and market data
- Real-time information that's not in the knowledge base

## Available Actions

- **search**: Execute a web search query to get current information
- **weather**: Get weather information for specific locations
- **news**: Search for latest news on specific topics

## Parameters

- `query` (required): Search query content, e.g., "Beijing weather today", "latest tech news", "Tesla stock price"
- `lat` (optional): Current latitude for location-based queries like weather
- `lon` (optional): Current longitude for location-based queries like weather

## Best Practices

1. Use specific, targeted queries for better results
2. Include location information when relevant (weather, local news)
3. Use this skill only when real-time or current information is needed
4. Combine with other skills for comprehensive responses

## Examples

```python
# Get current weather
await execute_skill("web_search", query="Beijing weather today")

# Search latest news
await execute_skill("web_search", query="latest AI technology news")

# Get stock information
await execute_skill("web_search", query="Tesla stock price today")
```