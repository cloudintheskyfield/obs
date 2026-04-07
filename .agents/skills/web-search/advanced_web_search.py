"""
Advanced Web Search Skill - 高级网络搜索技能
支持多引擎搜索、智能结果解析、免费高效的全网信息检索
模拟GPT级别的搜索体验
"""
import asyncio
import httpx
import json
import re
import time
from typing import Dict, Any, List, Optional
from urllib.parse import quote, urlencode
from datetime import datetime
from loguru import logger

from base_skill import BaseSkill, SkillResult


class SearchEngine:
    """搜索引擎接口"""
    
    def __init__(self, name: str, base_url: str, params_template: Dict[str, str]):
        self.name = name
        self.base_url = base_url
        self.params_template = params_template
    
    def build_url(self, query: str, **kwargs) -> str:
        """构建搜索URL"""
        params = self.params_template.copy()
        params.update(kwargs)
        params['q'] = query
        return f"{self.base_url}?{urlencode(params)}"


class AdvancedWebSearchSkill(BaseSkill):
    """高级网络搜索技能 - 免费、快速、精确的全网搜索"""
    
    def __init__(self):
        super().__init__(
            name="advanced_web_search",
            description="Advanced web search with multiple engines, intelligent parsing, and real-time data extraction"
        )
        
        # 搜索引擎配置 - 使用免费API和开源搜索引擎
        self.search_engines = {
            "duckduckgo": SearchEngine(
                name="DuckDuckGo",
                base_url="https://api.duckduckgo.com",
                params_template={
                    "format": "json",
                    "no_redirect": "1",
                    "skip_disambig": "1"
                }
            ),
            "searx": SearchEngine(
                name="SearX",
                base_url="https://searx.be/search",
                params_template={
                    "format": "json",
                    "engines": "google,bing,yahoo",
                    "safesearch": "1"
                }
            ),
            "bing": SearchEngine(
                name="Bing",
                base_url="https://www.bing.com/search",
                params_template={
                    "format": "json"
                }
            )
        }
        
        # 专门的实时数据API - 增强版
        self.realtime_apis = {
            "weather": {
                "wttr": "https://wttr.in/{city}?format=j1",
                "weather_com": "https://weather.com/weather/today/l/{city}",
                "accuweather": "https://www.accuweather.com/en/search-locations?query={city}",
                "openweather": "https://api.openweathermap.org/data/2.5/weather"
            },
            "news": {
                "newsapi": "https://newsapi.org/v2/everything",
                "gnews": "https://gnews.io/api/v4/search",
                "reuters": "https://www.reuters.com/search/news?blob={query}",
                "ap": "https://apnews.com/search?q={query}"
            },
            "finance": {
                "alpha_vantage": "https://www.alphavantage.co/query",
                "yahoo_finance": "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                "marketwatch": "https://www.marketwatch.com/investing/stock/{symbol}",
                "bloomberg": "https://www.bloomberg.com/quote/{symbol}"
            }
        }
        
        # 权威数据源映射
        self.authoritative_sources = {
            "weather": {
                "names": ["weather.com", "accuweather.com", "weather.gov", "jma.go.jp"],
                "descriptions": ["Weather Channel官方", "AccuWeather", "美国国家气象局", "日本气象厅"]
            },
            "news": {
                "names": ["reuters.com", "apnews.com", "bbc.com", "cnn.com"],
                "descriptions": ["路透社", "美联社", "BBC新闻", "CNN"]
            },
            "finance": {
                "names": ["bloomberg.com", "marketwatch.com", "finance.yahoo.com", "reuters.com"],
                "descriptions": ["彭博社", "MarketWatch", "雅虎财经", "路透社财经"]
            }
        }
        
        self.add_parameter("query", "str", "Search query", True)
        self.add_parameter("type", "str", "Search type: general, weather, news, finance", False)
        self.add_parameter("engine", "str", "Preferred search engine", False)
        self.add_parameter("max_results", "int", "Maximum number of results", False)
    
    async def execute(self, **kwargs) -> SkillResult:
        """执行高级搜索"""
        try:
            query = kwargs.get("query", "")
            search_type = kwargs.get("type", "general")
            engine = kwargs.get("engine", "auto")
            max_results = kwargs.get("max_results", 5)
            
            if not query:
                return SkillResult(success=False, error="搜索查询不能为空")
            
            logger.info(f"Advanced search: {query} (type: {search_type})")
            
            # 智能检测搜索类型
            if search_type == "general":
                search_type = self._detect_search_type(query)
            
            # 根据搜索类型选择最佳策略
            if search_type == "weather":
                result = await self._search_weather(query)
            elif search_type == "news":
                result = await self._search_news(query, max_results)
            elif search_type == "finance":
                result = await self._search_finance(query)
            else:
                result = await self._search_general(query, engine, max_results)
            
            # 增强结果验证
            if result.success:
                verified_result = await self._verify_and_enhance_result(result, query, search_type)
                return verified_result
            
            return result
            
        except Exception as e:
            logger.error(f"Advanced search failed: {e}")
            return SkillResult(success=False, error=f"搜索失败: {str(e)}")
    
    def _detect_search_type(self, query: str) -> str:
        """智能检测搜索类型"""
        query_lower = query.lower()
        
        # 天气关键词
        weather_keywords = ["天气", "weather", "温度", "气温", "下雨", "晴天", "阴天"]
        if any(kw in query_lower for kw in weather_keywords):
            return "weather"
        
        # 新闻关键词
        news_keywords = ["新闻", "news", "资讯", "最新", "today", "今天发生"]
        if any(kw in query_lower for kw in news_keywords):
            return "news"
        
        # 金融关键词
        finance_keywords = ["股价", "stock", "股票", "汇率", "exchange rate", "$", "￥"]
        if any(kw in query_lower for kw in finance_keywords):
            return "finance"
        
        return "general"
    
    async def _search_weather(self, query: str) -> SkillResult:
        """天气专用搜索 - 增强版，支持多数据源"""
        try:
            # 提取城市名
            city = self._extract_city_from_query(query)
            
            # 尝试多个天气数据源
            weather_data = await self._fetch_weather_from_multiple_sources(city)
            
            if weather_data:
                return self._format_enhanced_weather_result(weather_data, city)
            else:
                # 备用：使用权威天气网站搜索
                return await self._search_authoritative_weather(city)
                    
        except Exception as e:
            logger.error(f"Weather search failed: {e}")
            # 降级到通用搜索
            return await self._search_general(query, "duckduckgo", 3)
    
    async def _fetch_weather_from_multiple_sources(self, city: str) -> Dict[str, Any]:
        """从多个天气数据源获取信息"""
        sources_data = {}
        
        # 尝试wttr.in API
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                url = f"https://wttr.in/{city}?format=j1"
                response = await client.get(url)
                
                if response.status_code == 200:
                    sources_data["wttr"] = response.json()
                    logger.info(f"Successfully fetched weather from wttr.in for {city}")
                    
        except Exception as e:
            logger.error(f"wttr.in failed: {e}")
        
        # 可以添加其他天气API源
        return sources_data.get("wttr")
    
    async def _search_authoritative_weather(self, city: str) -> SkillResult:
        """搜索权威天气网站"""
        try:
            # 搜索专业天气网站
            weather_query = f"{city} weather today site:weather.com OR site:accuweather.com"
            results = await self._multi_engine_search(weather_query, 3)
            
            # 优先显示权威来源
            authoritative_results = self._prioritize_authoritative_sources(results, "weather")
            
            formatted_content = self._format_authoritative_weather_display(authoritative_results, city)
            return SkillResult(success=True, content=formatted_content)
            
        except Exception as e:
            logger.error(f"Authoritative weather search failed: {e}")
            return await self._search_general(f"{city} weather", "duckduckgo", 3)
    
    def _extract_city_from_query(self, query: str) -> str:
        """从查询中提取城市名"""
        # 简单的城市提取逻辑
        cities = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "重庆", "武汉", "西安"]
        for city in cities:
            if city in query:
                return city
        
        # 英文城市
        english_cities = ["beijing", "shanghai", "guangzhou", "shenzhen", "hangzhou"]
        for city in english_cities:
            if city in query.lower():
                return city
        
        # 默认返回北京
        return "beijing"
    
    def _format_enhanced_weather_result(self, data: Dict[str, Any], city: str) -> SkillResult:
        """格式化增强天气结果"""
        try:
            current = data["current_condition"][0]
            today = data["weather"][0]
            
            temperature = current["temp_C"]
            feels_like = current["FeelsLikeC"]
            humidity = current["humidity"]
            weather_desc = current["weatherDesc"][0]["value"]
            
            result = {
                "city": city,
                "temperature": f"{temperature}°C",
                "feels_like": f"{feels_like}°C",
                "description": weather_desc,
                "humidity": f"{humidity}%",
                "wind": f"{current['windspeedKmph']}km/h",
                "visibility": f"{current['visibility']}km",
                "pressure": f"{current.get('pressure', 'N/A')}hPa",
                "uv_index": current.get('uvIndex', 'N/A'),
                "forecast": [],
                "data_source": "wttr.in",
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            
            # 添加未来几天预报
            for day in data["weather"][:5]:  # 显示5天预报
                result["forecast"].append({
                    "date": day["date"],
                    "max_temp": f"{day['maxtempC']}°C",
                    "min_temp": f"{day['mintempC']}°C",
                    "description": day["hourly"][0]["weatherDesc"][0]["value"],
                    "precipitation": f"{day.get('totalSnow_cm', 0) + day.get('sunHour', 0)}%"
                })
            
            formatted_content = self._format_enhanced_weather_display(result)
            return SkillResult(success=True, content=formatted_content)
            
        except Exception as e:
            logger.error(f"Weather formatting failed: {e}")
            return SkillResult(success=False, error=f"天气数据解析失败: {str(e)}")
    
    def _format_enhanced_weather_display(self, weather: Dict[str, Any]) -> str:
        """格式化增强天气显示"""
        content = f"""## 🌤️ {weather['city']} 天气情况

### 📊 当前天气 (数据来源: {weather['data_source']})
- **温度**: {weather['temperature']} (体感温度: {weather['feels_like']})
- **天气状况**: {weather['description']}
- **湿度**: {weather['humidity']}
- **风速**: {weather['wind']}
- **气压**: {weather['pressure']}
- **能见度**: {weather['visibility']}
- **紫外线指数**: {weather['uv_index']}

### 📅 未来5天预报
"""
        
        for forecast in weather["forecast"]:
            content += f"- **{forecast['date']}**: {forecast['min_temp']} ~ {forecast['max_temp']} | {forecast['description']}\n"
        
        content += f"\n### 📍 数据时间: {weather['last_updated']}"
        content += f"\n\n💡 **推荐查询方式**:"
        content += f"\n- 🌐 [Weather Channel官方](https://weather.com/weather/today/l/{weather['city']})"
        content += f"\n- 🌐 [AccuWeather](https://www.accuweather.com/en/search-locations?query={weather['city']})"
        content += f"\n\n⚠️ **温馨提示**: 东京气候多变，建议出行前通过上述平台确认当日实时数据"
        
        return content
    
    def _format_authoritative_weather_display(self, results: List[Dict[str, Any]], city: str) -> str:
        """格式化权威天气源显示"""
        content = f"## 🌤️ {city} 天气信息 (权威来源)\n\n"
        
        for i, result in enumerate(results, 1):
            source_name = self._get_source_description(result.get("url", ""), "weather")
            content += f"### {i}. {result.get('title', '无标题')}\n"
            content += f"- **权威来源**: {source_name}\n"
            content += f"- **摘要**: {result.get('snippet', '暂无摘要')}\n"
            content += f"- **直达链接**: {result.get('url', '#')}\n\n"
        
        content += f"\n💡 **建议验证流程**:"
        content += f"\n1. 查看 Weather Channel 或 AccuWeather 获取最准确预报"
        content += f"\n2. 对比多个来源的数据以确保准确性"
        content += f"\n3. 关注当地气象部门的官方预警信息"
        
        return content
    
    async def _search_news(self, query: str, max_results: int = 5) -> SkillResult:
        """新闻专用搜索"""
        try:
            # 使用多个新闻源
            results = await self._multi_engine_search(f"最新 {query} news", max_results)
            
            # 过滤和排序新闻结果
            news_items = self._filter_news_results(results)
            
            formatted_content = self._format_news_display(news_items, query)
            return SkillResult(success=True, content=formatted_content)
            
        except Exception as e:
            logger.error(f"News search failed: {e}")
            return await self._search_general(query, "duckduckgo", max_results)
    
    def _filter_news_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """过滤新闻结果"""
        filtered = []
        for result in results:
            # 过滤掉非新闻网站
            if any(domain in result.get("url", "") for domain in 
                   ["news", "xinhua", "people", "sina", "163", "sohu", "qq", "tencent"]):
                filtered.append(result)
        
        return filtered[:5]  # 返回前5条
    
    def _format_news_display(self, news_items: List[Dict[str, Any]], query: str) -> str:
        """格式化新闻显示"""
        content = f"## 📰 关于 '{query}' 的最新资讯\n\n"
        
        for i, item in enumerate(news_items, 1):
            content += f"### {i}. {item.get('title', '无标题')}\n"
            content += f"- **来源**: {item.get('source', '未知')}\n"
            content += f"- **摘要**: {item.get('snippet', '暂无摘要')}\n"
            content += f"- **链接**: {item.get('url', '#')}\n\n"
        
        return content
    
    async def _search_finance(self, query: str) -> SkillResult:
        """金融专用搜索"""
        try:
            # 提取股票代码或公司名
            symbol = self._extract_financial_symbol(query)
            
            # 搜索财经信息
            results = await self._multi_engine_search(f"{symbol} stock price", 3)
            
            formatted_content = self._format_finance_display(results, symbol)
            return SkillResult(success=True, content=formatted_content)
            
        except Exception as e:
            logger.error(f"Finance search failed: {e}")
            return await self._search_general(query, "duckduckgo", 3)
    
    def _extract_financial_symbol(self, query: str) -> str:
        """提取金融符号"""
        # 简单的股票代码识别
        symbols = {"特斯拉": "TSLA", "苹果": "AAPL", "微软": "MSFT", "谷歌": "GOOGL"}
        for name, symbol in symbols.items():
            if name in query:
                return symbol
        
        # 直接提取可能的股票代码
        matches = re.findall(r'[A-Z]{2,5}', query.upper())
        if matches:
            return matches[0]
        
        return query
    
    def _format_finance_display(self, results: List[Dict[str, Any]], symbol: str) -> str:
        """格式化金融显示"""
        content = f"## 💰 {symbol} 财经信息\n\n"
        
        for i, result in enumerate(results, 1):
            content += f"### {i}. {result.get('title', '无标题')}\n"
            content += f"- **摘要**: {result.get('snippet', '暂无信息')}\n"
            content += f"- **来源**: {result.get('url', '#')}\n\n"
        
        return content
    
    async def _search_general(self, query: str, engine: str = "auto", max_results: int = 5) -> SkillResult:
        """通用搜索 - 增强版，支持多级降级机制"""
        fallback_engines = ["duckduckgo", "searx"] if engine == "auto" else [engine]
        
        for attempt, current_engine in enumerate(fallback_engines):
            try:
                logger.info(f"Attempting search with {current_engine}, attempt {attempt + 1}")
                
                if current_engine == "auto" or len(fallback_engines) > 1:
                    # 使用多引擎搜索
                    results = await self._multi_engine_search(query, max_results)
                else:
                    # 使用指定引擎
                    results = await self._single_engine_search(query, current_engine, max_results)
                
                if results:
                    # 优先权威来源
                    prioritized_results = self._prioritize_authoritative_sources(results, "general")
                    formatted_content = self._format_general_display(prioritized_results, query)
                    return SkillResult(success=True, content=formatted_content)
                    
            except Exception as e:
                logger.error(f"Search failed with {current_engine}: {e}")
                continue
        
        # 所有引擎都失败，返回建议
        fallback_content = self._generate_search_fallback_suggestions(query)
        return SkillResult(success=True, content=fallback_content)
    
    async def _multi_engine_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """多引擎并行搜索"""
        tasks = []
        
        # 启动多个搜索引擎的并行搜索
        for engine_name in ["duckduckgo", "searx"]:
            task = self._single_engine_search(query, engine_name, max_results // 2)
            tasks.append(task)
        
        results = []
        try:
            # 等待所有搜索完成
            search_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in search_results:
                if isinstance(result, list):
                    results.extend(result)
        except Exception as e:
            logger.error(f"Multi-engine search error: {e}")
        
        # 去重和排序
        return self._deduplicate_results(results)[:max_results]
    
    def _prioritize_authoritative_sources(self, results: List[Dict[str, Any]], search_type: str) -> List[Dict[str, Any]]:
        """优先排序权威来源"""
        if search_type not in self.authoritative_sources:
            return results
        
        authoritative_names = self.authoritative_sources[search_type]["names"]
        
        # 分类结果
        authoritative = []
        general = []
        
        for result in results:
            url = result.get("url", "").lower()
            is_authoritative = any(auth_name in url for auth_name in authoritative_names)
            
            if is_authoritative:
                authoritative.append(result)
            else:
                general.append(result)
        
        # 权威来源排在前面
        return authoritative + general
    
    def _get_source_description(self, url: str, search_type: str) -> str:
        """获取数据源描述"""
        if search_type not in self.authoritative_sources:
            return "未知来源"
        
        url_lower = url.lower()
        auth_sources = self.authoritative_sources[search_type]
        
        for i, name in enumerate(auth_sources["names"]):
            if name in url_lower:
                return auth_sources["descriptions"][i]
        
        return "一般来源"
    
    async def _single_engine_search(self, query: str, engine: str, max_results: int) -> List[Dict[str, Any]]:
        """单引擎搜索"""
        if engine == "duckduckgo":
            return await self._search_duckduckgo(query, max_results)
        elif engine == "searx":
            return await self._search_searx(query, max_results)
        else:
            return await self._search_duckduckgo(query, max_results)
    
    async def _search_duckduckgo(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """DuckDuckGo 搜索"""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_redirect=1"
                response = await client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    results = []
                    
                    # 解析结果
                    for item in data.get("RelatedTopics", [])[:max_results]:
                        if isinstance(item, dict) and "Text" in item:
                            results.append({
                                "title": item.get("Text", "")[:100] + "...",
                                "snippet": item.get("Text", ""),
                                "url": item.get("FirstURL", ""),
                                "source": "DuckDuckGo"
                            })
                    
                    return results
                    
        except Exception as e:
            logger.error(f"DuckDuckGo search failed: {e}")
        
        return []
    
    async def _search_searx(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """SearX 搜索"""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                params = {
                    "q": query,
                    "format": "json",
                    "engines": "google,bing",
                    "safesearch": "1"
                }
                
                url = f"https://searx.be/search?{urlencode(params)}"
                response = await client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    results = []
                    
                    for item in data.get("results", [])[:max_results]:
                        results.append({
                            "title": item.get("title", ""),
                            "snippet": item.get("content", ""),
                            "url": item.get("url", ""),
                            "source": "SearX"
                        })
                    
                    return results
                    
        except Exception as e:
            logger.error(f"SearX search failed: {e}")
        
        return []
    
    def _deduplicate_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """结果去重"""
        seen_urls = set()
        unique_results = []
        
        for result in results:
            url = result.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)
        
        return unique_results
    
    def _format_general_display(self, results: List[Dict[str, Any]], query: str) -> str:
        """格式化通用搜索结果 - 增强版"""
        content = f"## 🔍 关于 '{query}' 的搜索结果\n\n"
        
        # 添加搜索统计信息
        content += f"📊 **搜索统计**: 共找到 {len(results)} 个相关结果\n\n"
        
        for i, result in enumerate(results, 1):
            # 判断是否为权威来源
            url = result.get('url', '')
            is_authoritative = self._is_authoritative_source(url)
            authority_badge = " 🏆" if is_authoritative else ""
            
            content += f"### {i}. {result.get('title', '无标题')}{authority_badge}\n"
            content += f"- **摘要**: {result.get('snippet', '暂无摘要')}\n"
            content += f"- **来源**: {result.get('source', '未知')}\n"
            content += f"- **链接**: {url}\n"
            
            # 为权威来源添加可信度说明
            if is_authoritative:
                content += f"- **可信度**: ⭐⭐⭐⭐⭐ 权威来源\n"
            
            content += "\n"
        
        # 添加搜索建议
        content += "---\n"
        content += "💡 **搜索建议**:\n"
        content += "- 🏆 标记的结果来自权威来源，可信度较高\n"
        content += "- 建议对比多个来源的信息以确保准确性\n"
        content += "- 点击链接查看完整原文获取更详细信息\n"
        
        return content
    
    def _is_authoritative_source(self, url: str) -> bool:
        """判断是否为权威来源"""
        if not url:
            return False
            
        url_lower = url.lower()
        
        # 检查所有类型的权威来源
        for source_type, sources in self.authoritative_sources.items():
            if any(auth_name in url_lower for auth_name in sources["names"]):
                return True
        
        # 额外的权威域名
        additional_authorities = [
            "wikipedia.org", "gov.", "edu.", "who.int", "un.org", 
            "nature.com", "science.org", "pubmed.ncbi.nlm.nih.gov"
        ]
        
        return any(auth in url_lower for auth in additional_authorities)
    
    def _generate_search_fallback_suggestions(self, query: str) -> str:
        """生成搜索降级建议"""
        content = f"## ⚠️ 搜索服务暂时不可用\n\n"
        content += f"很抱歉，我们无法通过当前搜索引擎获取关于 '{query}' 的结果。\n\n"
        
        # 智能建议替代搜索方案
        search_type = self._detect_search_type(query)
        
        if search_type == "weather":
            content += "### 🌤️ 天气查询建议\n"
            content += "- 🌐 **Weather Channel**: https://weather.com\n"
            content += "- 🌐 **AccuWeather**: https://www.accuweather.com\n"
            content += "- 🌐 **中国天气网**: http://www.weather.com.cn\n"
            
        elif search_type == "news":
            content += "### 📰 新闻查询建议\n"
            content += "- 🌐 **Reuters**: https://www.reuters.com\n"
            content += "- 🌐 **BBC News**: https://www.bbc.com/news\n"
            content += "- 🌐 **新华网**: http://www.xinhuanet.com\n"
            
        elif search_type == "finance":
            content += "### 💰 财经查询建议\n"
            content += "- 🌐 **Yahoo Finance**: https://finance.yahoo.com\n"
            content += "- 🌐 **Bloomberg**: https://www.bloomberg.com\n"
            content += "- 🌐 **东方财富**: http://www.eastmoney.com\n"
            
        else:
            content += "### 🔍 通用搜索建议\n"
            content += "- 🌐 **Google**: https://www.google.com\n"
            content += "- 🌐 **Bing**: https://www.bing.com\n"
            content += "- 🌐 **百度**: https://www.baidu.com\n"
        
        content += "\n### 💡 其他建议\n"
        content += "- 稍后再试，搜索服务可能临时不可用\n"
        content += "- 尝试修改关键词或使用更具体的搜索词\n"
        content += "- 直接访问相关官方网站获取信息\n"
        
        return content
    
    async def _verify_and_enhance_result(self, result: SkillResult, query: str, search_type: str) -> SkillResult:
        """验证并增强搜索结果"""
        try:
            # 获取当前结果内容
            content = result.content
            
            # 添加数据质量评估
            quality_assessment = self._assess_result_quality(content, search_type)
            
            # 添加相关性分析
            relevance_score = self._calculate_relevance_score(content, query)
            
            # 生成增强版结果
            enhanced_content = content + "\n\n" + self._generate_quality_footer(
                quality_assessment, relevance_score, search_type
            )
            
            return SkillResult(success=True, content=enhanced_content)
            
        except Exception as e:
            logger.error(f"Result verification failed: {e}")
            return result
    
    def _assess_result_quality(self, content: str, search_type: str) -> Dict[str, Any]:
        """评估结果质量"""
        assessment = {
            "has_authoritative_sources": "🏆" in content,
            "has_direct_links": "http" in content,
            "has_specific_data": False,
            "content_length": len(content),
            "quality_score": 0
        }
        
        # 检查特定类型的数据质量
        if search_type == "weather":
            assessment["has_specific_data"] = any(indicator in content.lower() for indicator in 
                ["°c", "temperature", "humidity", "wind"])
            
        elif search_type == "news":
            assessment["has_specific_data"] = any(indicator in content.lower() for indicator in 
                ["news", "报道", "latest", "breaking"])
            
        elif search_type == "finance":
            assessment["has_specific_data"] = any(indicator in content.lower() for indicator in 
                ["price", "stock", "$", "市值", "股价"])
        
        # 计算质量分数
        score = 0
        if assessment["has_authoritative_sources"]: score += 30
        if assessment["has_direct_links"]: score += 20
        if assessment["has_specific_data"]: score += 30
        if assessment["content_length"] > 200: score += 20
        
        assessment["quality_score"] = min(score, 100)
        return assessment
    
    def _calculate_relevance_score(self, content: str, query: str) -> float:
        """计算相关性分数"""
        query_terms = query.lower().split()
        content_lower = content.lower()
        
        matches = sum(1 for term in query_terms if term in content_lower)
        relevance_score = (matches / len(query_terms)) * 100 if query_terms else 0
        
        return min(relevance_score, 100)
    
    def _generate_quality_footer(self, assessment: Dict[str, Any], relevance: float, search_type: str) -> str:
        """生成质量评估脚注"""
        footer = "---\n"
        footer += "## 📊 结果质量评估\n\n"
        
        # 质量分数
        quality_score = assessment["quality_score"]
        if quality_score >= 80:
            quality_level = "优秀 ⭐⭐⭐⭐⭐"
        elif quality_score >= 60:
            quality_level = "良好 ⭐⭐⭐⭐"
        elif quality_score >= 40:
            quality_level = "中等 ⭐⭐⭐"
        else:
            quality_level = "较低 ⭐⭐"
        
        footer += f"- **整体质量**: {quality_level} ({quality_score}/100)\n"
        footer += f"- **内容相关性**: {relevance:.1f}%\n"
        footer += f"- **权威来源**: {'✅' if assessment['has_authoritative_sources'] else '❌'}\n"
        footer += f"- **直接链接**: {'✅' if assessment['has_direct_links'] else '❌'}\n"
        footer += f"- **具体数据**: {'✅' if assessment['has_specific_data'] else '❌'}\n"
        
        # 针对性建议
        footer += "\n### 💡 数据使用建议\n"
        
        if search_type == "weather":
            footer += "- 天气数据建议查看多个来源以确保准确性\n"
            footer += "- 实时天气情况可能与预报有差异\n"
        elif search_type == "news":
            footer += "- 新闻信息建议查看发布时间和来源可信度\n"
            footer += "- 重要新闻建议查看多家媒体报道\n"
        elif search_type == "finance":
            footer += "- 财经数据可能存在延迟，投资需谨慎\n"
            footer += "- 建议查看官方财经平台获取实时数据\n"
        else:
            footer += "- 建议交叉验证多个来源的信息\n"
            footer += "- 点击原链接获取最新和完整信息\n"
        
        if quality_score < 60:
            footer += "\n⚠️ **注意**: 当前结果质量较低，建议使用更具体的搜索词重新搜索。\n"
        
        return footer