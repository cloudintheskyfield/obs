"""Web Search Skill - 实时信息搜索"""
import asyncio
import httpx
import json
import re
from typing import Dict, Any
from loguru import logger

from base_skill import BaseSkill, SkillResult


class WebSearchSkill(BaseSkill):
    """网络搜索技能 - 用于获取实时信息"""
    
    def __init__(self):
        super().__init__(
            name="web_search",
            description="搜索互联网获取实时信息，如天气、新闻、股票、最新资讯等。当需要实时数据或最新信息时使用此工具。"
        )
        
        self.add_parameter(
            name="query",
            param_type="str",
            description="搜索查询内容，例如：'北京今天天气'、'最新科技新闻'、'特斯拉股价'",
            required=True
        )

        self.add_parameter(
            name="lat",
            param_type="float",
            description="可选：当前位置纬度（用于天气等需要地理位置的问题）",
            required=False
        )
        self.add_parameter(
            name="lon",
            param_type="float",
            description="可选：当前位置经度（用于天气等需要地理位置的问题）",
            required=False
        )
        self.add_parameter(
            name="city",
            param_type="str",
            description="可选：城市名（如果已知，可辅助天气查询）",
            required=False
        )
        self.add_parameter(
            name="region",
            param_type="str",
            description="可选：地区/省份（IP定位兜底时可能提供）",
            required=False
        )
        self.add_parameter(
            name="country_name",
            param_type="str",
            description="可选：国家名（IP定位兜底时可能提供）",
            required=False
        )
        self.add_parameter(
            name="location_source",
            param_type="str",
            description="可选：定位来源（geolocation/ip）",
            required=False
        )
        self.add_parameter(
            name="accuracy_m",
            param_type="float",
            description="可选：定位精度（米）",
            required=False
        )
        
        # 使用多个搜索源
        self.search_engines = [
            {"name": "SerpAPI", "url": "https://serpapi.com/search"},
            {"name": "DuckDuckGo", "url": "https://api.duckduckgo.com/"},
            {"name": "Bing", "url": "https://api.bing.microsoft.com/v7.0/search"}
        ]
    
    async def execute(self, **kwargs) -> SkillResult:
        """执行网络搜索"""
        query = kwargs.get("query", "")
        lat = kwargs.get("lat")
        lon = kwargs.get("lon")
        city = kwargs.get("city")
        
        if not query:
            return SkillResult(
                success=False,
                error="搜索查询不能为空"
            )
        
        try:
            logger.info(f"Performing web search: {query}")
            
            result_text = await self._perform_search(query, lat=lat, lon=lon, city=city)
            
            return SkillResult(
                success=True,
                content=result_text,
                metadata={
                    "query": query,
                    "source": "web_search"
                }
            )
            
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return SkillResult(
                success=False,
                error=f"搜索失败: {str(e)}",
                metadata={"query": query}
            )
    
    async def _perform_search(self, query: str, lat: Any = None, lon: Any = None, city: Any = None) -> str:
        """执行搜索并返回格式化结果"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 优先检查天气查询
            if any(word in query for word in ["天气", "气温", "降雨", "下雨", "下雪", "weather"]):
                try:
                    weather_result = await self._search_weather(client, query, lat=lat, lon=lon, city=city)
                    if weather_result:
                        return weather_result
                except Exception as e:
                    logger.warning(f"Weather search failed: {e}")

            # 方法1: 尝试DuckDuckGo HTML搜索（更可靠）
            try:
                result = await self._search_ddg_html(client, query)
                if result and not result.startswith("我目前无法"):
                    return result
            except Exception as e:
                logger.warning(f"DDG HTML search failed: {e}")
            
            # 方法2: DuckDuckGo Instant Answer API
            try:
                response = await client.get(
                    "https://api.duckduckgo.com/",
                    params={
                        "q": query,
                        "format": "json",
                        "no_html": 1,
                        "skip_disambig": 1
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    result = self._parse_ddg_response(data, query)
                    if result and not result.startswith("我目前无法"):
                        return result
            except Exception as e:
                logger.warning(f"DDG API search failed: {e}")
            
            # 如果所有方法都失败，返回智能fallback
            return self._create_helpful_fallback(query)
    
    async def _search_weather(self, client: httpx.AsyncClient, query: str, lat: Any = None, lon: Any = None, city: Any = None) -> str:
        """使用wttr.in获取天气信息"""
        # 0. 优先使用经纬度
        if lat is not None and lon is not None:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                search_term = f"{lat_f},{lon_f}"
                is_chinese = any(u'\u4e00' <= char <= u'\u9fff' for char in query)
                params = {"format": "3"}
                if is_chinese:
                    params["lang"] = "zh"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                }
                async with httpx.AsyncClient(timeout=60.0) as weather_client:
                    response = await weather_client.get(
                        f"https://wttr.in/{search_term}",
                        params=params,
                        headers=headers
                    )
                    if response.status_code == 200:
                        text = response.text.strip()
                        if text and "Unknown location" not in text and "404" not in text and "<html" not in text.lower():
                            return f"**实时天气**: {text}\n(数据来源: wttr.in)"
            except Exception as e:
                logger.debug(f"Weather fetch by lat/lon failed: {e}")

        # 0.5 若提供了city且query未包含具体地点，优先用city
        if city and isinstance(city, str) and city.strip() and city not in query:
            query = f"{city} {query}"

        # 尝试提取城市
        city = ""
        # 1. 尝试匹配常用城市
        common_cities = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "重庆", "武汉", "西安", "天津", "香港", "澳门", "台北"]
        for c in common_cities:
            if c in query:
                city = c
                break
        
        search_term = query
        is_chinese = any(u'\u4e00' <= char <= u'\u9fff' for char in query)
        
        # 2. 如果没找到，尝试清理查询词
        if not city:
            cleaned = query
            # 移除常见干扰词
            keywords = [
                "天气", "气温", "降雨", "下雨", "下雪", "weather", 
                "今天", "明天", "后天", "怎么样", "查询", "多少度", "概况", "预报",
                "current", "forecast", "now", "temperature"
            ]
            for word in keywords:
                cleaned = cleaned.replace(word, "")
            cleaned = cleaned.strip()
            
            # 如果清理后为空，说明用户只输入了关键词，使用自动定位
            if not cleaned:
                search_term = ""
            # 如果剩余词较短，假设是地名
            elif len(cleaned) < 20:
                search_term = cleaned
            # 否则保留原查询（虽然可能失败）
        else:
            search_term = city
        
        try:
            # format=3: simple output (City: Condition Temp)
            # Add lang=zh for Chinese queries
            params = {"format": "3"}
            if is_chinese:
                params["lang"] = "zh"
                
            # Use browser UA to avoid being blocked and increase timeout
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            
            # Create a new client with longer timeout just for weather
            async with httpx.AsyncClient(timeout=60.0) as weather_client:
                response = await weather_client.get(
                    f"https://wttr.in/{search_term}",
                    params=params,
                    headers=headers
                )
                
                if response.status_code == 200:
                    text = response.text.strip()
                    # 检查是否返回了有效结果
                    # wttr.in 有时会返回 "Unknown location; please try..." 或者 HTML 页面
                    if text and "Unknown location" not in text and "404" not in text and "<html" not in text.lower():
                        return f"**实时天气**: {text}\n(数据来源: wttr.in)"
        except Exception as e:
            logger.warning(f"Weather fetch failed: {e}")
            pass
            
        return ""

    async def _search_ddg_html(self, client: httpx.AsyncClient, query: str) -> str:
        """使用DuckDuckGo HTML搜索（模拟浏览器请求）"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers=headers,
                follow_redirects=True
            )
            
            if response.status_code == 200:
                # 简单解析HTML获取搜索结果
                html = response.text
                
                # 提取片段信息（这是一个简化版本）
                import re
                
                # 查找结果片段
                snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
                
                if snippets:
                    results_text = []
                    for i, snippet in enumerate(snippets[:3], 1):
                        # 清理HTML标签
                        clean_snippet = re.sub(r'<[^>]+>', '', snippet)
                        clean_snippet = clean_snippet.strip()
                        if clean_snippet:
                            results_text.append(f"{i}. {clean_snippet}")
                    
                    if results_text:
                        return f"**搜索结果**: {query}\n\n" + "\n\n".join(results_text)
        except Exception as e:
            logger.debug(f"HTML search error: {e}")
        
        return ""
    
    def _parse_ddg_response(self, data: Dict, query: str) -> str:
        """解析DuckDuckGo API响应"""
        result_parts = []
        
        # 获取摘要
        abstract = data.get("Abstract", "")
        if abstract:
            result_parts.append(f"**摘要**：{abstract}")
        
        # 获取相关主题
        related = data.get("RelatedTopics", [])
        if related:
            result_parts.append("\n**相关信息**：")
            count = 0
            for topic in related[:5]:
                if isinstance(topic, dict):
                    text = topic.get("Text", "")
                    if text:
                        count += 1
                        result_parts.append(f"{count}. {text}")
        
        # 获取答案（Answer字段）
        answer = data.get("Answer", "")
        if answer:
            result_parts.insert(0, f"**答案**：{answer}")
        
        if result_parts:
            return "\n".join(result_parts)
        else:
            return self._create_helpful_fallback(query)
    
    def _create_helpful_fallback(self, query: str) -> str:
        """创建有帮助的fallback信息 - 提供实用建议而非搜索结果"""
        # 根据查询类型提供针对性建议
        if any(word in query for word in ["天气", "气温", "降雨", "下雨", "下雪", "weather"]):
            # 提取城市名称（简单版本）
            city = self._extract_city(query)
            return f"""**天气查询指南** 🌤️

要获取{city}的实时天气信息，您可以：

**推荐网站**：
1. 中国天气网: https://www.weather.com.cn
   - 官方权威，数据最准确
   - 提供小时级预报和预警信息

2. 中央气象台: http://www.nmc.cn  
   - 权威发布，实时更新
   - 包含灾害性天气预警

**推荐APP**：
- 墨迹天气：实时降雨预报精确
- 中国天气：官方应用，权威可靠
- 彩云天气：分钟级降雨预报

**快速查询方式**：
- 微信小程序搜索"天气"即可查看
- 支付宝首页天气卡片
- Siri/小爱同学语音查询"""
            
        elif any(word in query for word in ["新闻", "最新", "资讯", "消息"]):
            return f"""**新闻资讯指南** 📰

要获取"{query}"的最新信息，推荐：

**新闻网站**：
1. 新华网: http://www.xinhuanet.com - 权威官方
2. 人民网: http://www.people.com.cn - 时政新闻
3. 澎湃新闻: https://www.thepaper.cn - 深度报道
4. 财经: https://www.caijing.com.cn - 财经资讯

**新闻APP**：
- 今日头条：个性化推荐
- 腾讯新闻：全面及时
- 网易新闻：深度评论
- 央视新闻：权威播报

**快速获取**：
- 微博热搜榜实时热点
- 知乎热榜深度讨论
- 百度资讯聚合查看"""
            
        elif any(word in query for word in ["股票", "股价", "涨跌", "行情"]):
            return f"""**股票行情查询** 📈

查看实时股票信息，推荐：

**财经网站**：
1. 东方财富: http://www.eastmoney.com
2. 雪球: https://xueqiu.com
3. 新浪财经: http://finance.sina.com.cn

**交易软件**：
- 同花顺、大智慧、东方财富
- 券商官方APP

**提示**：股市有风险，投资需谨慎"""
        else:
            return f"""**搜索建议** 🔍

对于"{query}"的查询，推荐：

**搜索引擎**：
- 百度: https://www.baidu.com
- Google: https://www.google.com
- 必应: https://cn.bing.com

**专业网站**：
- 知乎：专业问答
- 百度百科：知识查询
- 维基百科：详细资料

**技巧**：
1. 使用引号精确搜索
2. 添加时间限制获取最新信息
3. 查看多个来源交叉验证"""
    
    def _extract_city(self, query: str) -> str:
        """从查询中提取城市名称"""
        cities = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "重庆", "武汉", "西安", "天津"]
        for city in cities:
            if city in query:
                return city
        return "您所在地区"
    
    def _format_results(self, results: Any, query: str) -> str:
        """格式化搜索结果"""
        if not results:
            return f"未找到关于'{query}'的信息"
        
        formatted = [f"搜索结果: {query}\n"]
        
        if isinstance(results, list):
            for i, result in enumerate(results[:5], 1):
                if isinstance(result, dict):
                    title = result.get("title", "")
                    snippet = result.get("snippet", result.get("description", ""))
                    url = result.get("url", result.get("link", ""))
                    
                    if title:
                        formatted.append(f"{i}. **{title}**")
                    if snippet:
                        formatted.append(f"   {snippet}")
                    if url:
                        formatted.append(f"   来源: {url}")
                    formatted.append("")
        
        return "\n".join(formatted) if len(formatted) > 1 else f"未找到关于'{query}'的详细信息"
