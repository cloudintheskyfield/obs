"""VLLM客户端"""
import base64
import json
import asyncio
import random
from typing import List, Dict, Any, Optional, Union

import httpx
from loguru import logger

from config.config import VLLMConfig, VisionVLLMConfig, GPT55Config

# Max retries for rate-limit / server-overload errors (529 / 429).
# Each retry uses exponential backoff with jitter; see _retry_delay_for_status.
_RATE_LIMIT_MAX_RETRIES = 5

# Sent to the Harness runtime between HTTP retries so the UI can show progress
# (MiniMax 529 backoff can total minutes of silence otherwise).
def _rate_limit_wait_chunk(
    status: int,
    rate_attempt: int,
    rate_retries: int,
    delay: float,
    raw_excerpt: str,
) -> Dict[str, Any]:
    return {
        "__obs_phase": {
            "kind": "rate_limit_wait",
            "http_status": status,
            "attempt": rate_attempt,
            "max_attempts": rate_retries,
            "delay_sec": round(delay, 1),
            "excerpt": (raw_excerpt or "")[:220],
        }
    }


class VLLMClient:
    """VLLM多模态客户端（支持视觉模型和GPT-5.5自动路由）"""

    def __init__(self, config: VLLMConfig, vision_config: Optional[VisionVLLMConfig] = None, gpt55_config: Optional[GPT55Config] = None):
        self.config = config
        self.vision_config = vision_config
        self.gpt55_config = gpt55_config
        self.client: Optional[httpx.AsyncClient] = None

    @staticmethod
    def _has_images(messages: List[Dict[str, Any]]) -> bool:
        """检查消息列表中是否包含图片内容。
        
        检查规则：
        1. 检查最后一条用户消息是否包含图片
        2. 检查最后一条assistant消息之后的tool结果是否包含图片（截图等）
        """
        # 检查最后一条用户消息
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") in ("image_url", "image"):
                            return True
                break
        
        # 检查最近的tool结果中是否有图片（如computer工具的截图）
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                content = msg.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") in ("image_url", "image"):
                            return True
            # 如果遇到assistant消息，说明已经检查完最近的tool结果
            elif msg.get("role") == "assistant":
                break
        
        return False

    def _pick_config(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> VLLMConfig:
        """根据消息内容和指定模型选择配置。
        
        优先级：
        1. 如果指定了 gpt-5.5 模型，使用 GPT-5.5 配置
        2. 如果消息含图片且视觉路由已启用，使用视觉配置
        3. 否则使用主配置（MiniMax-M2）
        """
        # 检查是否指定了 GPT-5.5
        if model == "gpt-5.5" and self.gpt55_config is not None and self.gpt55_config.enabled:
            logger.debug(f"Routing to GPT-5.5: {self.gpt55_config.model} @ {self.gpt55_config.base_url}")
            return self.gpt55_config
        
        # 检查是否需要视觉模型
        if (
            self.vision_config is not None
            and self.vision_config.enabled
            and self._has_images(messages)
        ):
            logger.debug(f"Routing to vision model: {self.vision_config.model} @ {self.vision_config.base_url}")
            return self.vision_config
        
        return self.config

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        """Short delay for transient network / server errors."""
        return min(0.8 * attempt, 3.0)

    @staticmethod
    def _rate_limit_delay(attempt: int) -> float:
        """Exponential backoff with jitter for 429 / 529 rate-limit errors.

        attempt=1 → ~5s, attempt=2 → ~12s, attempt=3 → ~25s,
        attempt=4 → ~45s, attempt=5 → ~60s (cap).
        Jitter ±20 % prevents thundering-herd when multiple requests hit at once.
        """
        base = min(5.0 * (2 ** (attempt - 1)), 60.0)
        jitter = base * 0.2 * (random.random() * 2 - 1)  # ±20 %
        return max(1.0, base + jitter)
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.client = httpx.AsyncClient(
            timeout=self.config.timeout,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.client:
            await self.client.aclose()
            self.client = None
    
    async def chat_completion(
        self, 
        messages: List[Dict[str, Any]], 
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ):
        """聊天完成请求
        
        Args:
            messages: 消息列表
            tools: Anthropic格式的工具定义列表
            **kwargs: 其他参数（temperature, max_tokens, stream, model等）
        
        Returns:
            API响应结果或异步生成器（如果stream=True）
        """
        if not self.client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        # 获取指定的模型
        requested_model = kwargs.get("model")
        
        # 根据模型和消息内容选择配置
        active_cfg = self._pick_config(messages, requested_model)
        is_vision_request = active_cfg is self.vision_config
        is_gpt55_request = active_cfg is self.gpt55_config
        stream = kwargs.get("stream", False)

        # 确定最终使用的模型名称
        if is_gpt55_request:
            model = active_cfg.model
        elif is_vision_request:
            model = active_cfg.model
        else:
            model = requested_model or self.config.model
            
        payload = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4000),
            "stream": stream
        }
        
        # 只有非视觉请求且非GPT-5.5请求才添加工具（这些模型可能不支持工具调用）
        if tools and not is_vision_request and not is_gpt55_request:
            payload["tools"] = self._normalize_tools_for_provider(tools)
            payload["tool_choice"] = kwargs.get("tool_choice", "auto")
            logger.debug(f"Including {len(tools)} tools in request")
        
        # 记录请求信息
        if is_vision_request:
            logger.info(f"Vision request to {active_cfg.base_url}, model={model}, has_tools={bool(tools)}, tools_in_payload={'tools' in payload}")
        elif is_gpt55_request:
            logger.info(f"GPT-5.5 request to {active_cfg.base_url}, model={model}")
        
        try:
            logger.debug(f"Sending request to VLLM: {active_cfg.base_url}")
            
            headers = {
                "Authorization": f"Bearer {active_cfg.api_key}",
                "Content-Type": "application/json"
            }
            req_timeout = httpx.Timeout(active_cfg.timeout)

            if stream:
                # 流式请求
                async def stream_generator():
                    normal_retries = max(1, int(active_cfg.max_retries))
                    rate_retries = _RATE_LIMIT_MAX_RETRIES
                    rate_attempt = 0
                    attempt = 0
                    # Track the last rate-limit error message so we can surface it
                    # if retries exhaust.
                    last_rate_limit_msg: str | None = None
                    last_rate_limit_status: int | None = None
                    while attempt < normal_retries:
                        attempt += 1
                        try:
                            async with self.client.stream(
                                "POST",
                                active_cfg.base_url,
                                json=payload,
                                headers=headers,
                                timeout=req_timeout,
                            ) as response:
                                if response.is_error:
                                    error_text = await response.aread()
                                    status = response.status_code
                                    raw_msg = error_text.decode(errors='ignore')[:500]
                                    logger.error(f"VLLM stream request failed: {status} {raw_msg}")
                                    if status in (429, 529):
                                        last_rate_limit_msg = raw_msg
                                        last_rate_limit_status = status
                                        if rate_attempt < rate_retries:
                                            rate_attempt += 1
                                            attempt -= 1  # rate-limit retries don't count against normal quota
                                            delay = self._rate_limit_delay(rate_attempt)
                                            logger.warning(f"Rate-limited ({status}), waiting {delay:.1f}s before retry {rate_attempt}/{rate_retries}")
                                            yield _rate_limit_wait_chunk(
                                                status, rate_attempt, rate_retries, delay, raw_msg
                                            )
                                            await asyncio.sleep(delay)
                                            continue
                                        # Rate-limit retries exhausted — surface the original error
                                        raise RuntimeError(f"API Error: {status} {raw_msg}")
                                    if self._is_retryable_status(status) and attempt < normal_retries:
                                        await asyncio.sleep(self._retry_delay(attempt))
                                        continue
                                    response.raise_for_status()
                                chunks_yielded = 0
                                api_error_raw: str | None = None
                                async for line in response.aiter_lines():
                                    if line.startswith("data: "):
                                        data_str = line[6:]
                                        if data_str == "[DONE]":
                                            if api_error_raw:
                                                # API returned an error object inside the stream
                                                raise RuntimeError(
                                                    f"API Error: {api_error_raw}"
                                                )
                                            if last_rate_limit_msg and chunks_yielded == 0:
                                                # Rate-limited earlier, but the 200 reply was empty.
                                                raise RuntimeError(
                                                    f"服务器限流后返回了空响应 (HTTP 529): {last_rate_limit_msg}"
                                                )
                                            return
                                        try:
                                            data = json.loads(data_str)
                                            # Detect in-stream error objects (e.g. MiniMax 529 in SSE body)
                                            if data.get("type") == "error" or (
                                                isinstance(data.get("error"), dict)
                                                and not data.get("choices")
                                            ):
                                                api_error_raw = data_str
                                                logger.error(f"API returned in-stream error: {data_str[:500]}")
                                                continue  # wait for [DONE] then raise
                                            chunks_yielded += 1
                                            yield data
                                        except json.JSONDecodeError:
                                            continue
                                if api_error_raw:
                                    raise RuntimeError(f"API Error: {api_error_raw}")
                                if last_rate_limit_msg and chunks_yielded == 0:
                                    raise RuntimeError(
                                        f"服务器限流后返回了空响应 (HTTP 529): {last_rate_limit_msg}"
                                    )
                                return
                        except httpx.HTTPError as exc:
                            status_code = getattr(getattr(exc, "response", None), "status_code", None)
                            if status_code in (429, 529):
                                last_rate_limit_status = status_code
                                if rate_attempt < rate_retries:
                                    rate_attempt += 1
                                    attempt -= 1
                                    delay = self._rate_limit_delay(rate_attempt)
                                    logger.warning(f"Rate-limited ({status_code}), waiting {delay:.1f}s before retry {rate_attempt}/{rate_retries}")
                                    yield _rate_limit_wait_chunk(
                                        status_code,
                                        rate_attempt,
                                        rate_retries,
                                        delay,
                                        str(exc),
                                    )
                                    await asyncio.sleep(delay)
                                    continue
                                raise RuntimeError(f"API Error: {status_code} (rate-limit retries exhausted) {exc}")
                            if attempt < normal_retries and self._is_retryable_exception(exc):
                                logger.warning(f"Retrying VLLM stream request after error: {exc}")
                                await asyncio.sleep(self._retry_delay(attempt))
                                continue
                            raise
                    # Loop exited without yielding or raising — surface last rate-limit error
                    if last_rate_limit_msg:
                        raise RuntimeError(f"API Error: {last_rate_limit_status or 529} {last_rate_limit_msg}")

                return stream_generator()
            else:
                # 非流式请求
                normal_retries = max(1, int(active_cfg.max_retries))
                rate_retries = _RATE_LIMIT_MAX_RETRIES
                rate_attempt = 0
                last_error: Optional[Exception] = None
                attempt = 0
                while attempt < normal_retries:
                    attempt += 1
                    try:
                        response = await self.client.post(
                            active_cfg.base_url,
                            json=payload,
                            headers=headers,
                            timeout=req_timeout,
                        )
                        if response.is_error:
                            status = response.status_code
                            logger.error(f"VLLM request failed: {status} {response.text[:500]}")
                            if status in (429, 529) and rate_attempt < rate_retries:
                                rate_attempt += 1
                                delay = self._rate_limit_delay(rate_attempt)
                                logger.warning(f"Rate-limited ({status}), waiting {delay:.1f}s before retry {rate_attempt}/{rate_retries}")
                                await asyncio.sleep(delay)
                                attempt -= 1  # don't count rate-limit retries against normal quota
                                continue
                            if self._is_retryable_status(status) and attempt < normal_retries:
                                await asyncio.sleep(self._retry_delay(attempt))
                                continue
                        response.raise_for_status()
                        result = response.json()
                        # Detect in-body error objects (e.g. MiniMax returns HTTP 200 with error JSON)
                        if isinstance(result, dict) and (
                            result.get("type") == "error"
                            or (isinstance(result.get("error"), dict) and not result.get("choices"))
                        ):
                            raise RuntimeError(f"API Error: {json.dumps(result, ensure_ascii=False)}")
                        logger.debug("VLLM request successful")
                        return result
                    except httpx.HTTPError as exc:
                        last_error = exc
                        status_code = getattr(getattr(exc, "response", None), "status_code", None)
                        if status_code in (429, 529) and rate_attempt < rate_retries:
                            rate_attempt += 1
                            delay = self._rate_limit_delay(rate_attempt)
                            logger.warning(f"Rate-limited ({status_code}), waiting {delay:.1f}s before retry {rate_attempt}/{rate_retries}")
                            await asyncio.sleep(delay)
                            attempt -= 1
                            continue
                        if attempt < normal_retries and self._is_retryable_exception(exc):
                            logger.warning(f"Retrying VLLM request after error: {exc}")
                            await asyncio.sleep(self._retry_delay(attempt))
                            continue
                        raise
                if last_error:
                    raise last_error
            
        except httpx.HTTPError as e:
            logger.error(f"VLLM request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in VLLM request: {e}")
            raise

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code == 429 or status_code == 529 or 500 <= status_code < 600

    def _is_retryable_exception(self, exc: httpx.HTTPError) -> bool:
        if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError)):
            return True
        response = getattr(exc, "response", None)
        if response is not None:
            return self._is_retryable_status(response.status_code)
        return False

    def _normalize_tools_for_provider(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue

            if tool.get("type") == "function" and "function" in tool:
                normalized.append(tool)
                continue

            input_schema = tool.get("input_schema") or {
                "type": "object",
                "properties": {},
            }
            openai_tool = {
                "type": "function",
                "function": {
                    "name": tool.get("name", "tool"),
                    "description": tool.get("description", ""),
                    "parameters": input_schema,
                },
            }
            normalized.append(openai_tool)
        return normalized
    
    async def analyze_images(
        self, 
        images: List[str], 
        prompt: str = "请分析这些图片"
    ) -> str:
        """分析图片（多模态）"""
        content = [{"type": "text", "text": prompt}]
        
        # 添加图片到消息内容
        for i, image in enumerate(images):
            if isinstance(image, str):
                # 如果是base64字符串
                if image.startswith("data:image"):
                    image_data = image
                elif image.startswith("/") or "\\" in image:
                    # 如果是文件路径
                    try:
                        with open(image, "rb") as f:
                            image_bytes = f.read()
                            image_data = f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"
                    except Exception as e:
                        logger.warning(f"Failed to read image file {image}: {e}")
                        continue
                else:
                    # 假设是纯base64
                    image_data = f"data:image/png;base64,{image}"
                
                content.append({
                    "type": "image_url",
                    "image_url": {"url": image_data}
                })
        
        messages = [{"role": "user", "content": content}]
        
        response = await self.chat_completion(messages)
        
        if "choices" in response and response["choices"]:
            return response["choices"][0]["message"]["content"]
        else:
            raise ValueError("Invalid response from VLLM")
    
    async def generate_text(
        self, 
        prompt: str, 
        **kwargs
    ) -> str:
        """生成文本"""
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat_completion(messages, **kwargs)
        
        if "choices" in response and response["choices"]:
            return response["choices"][0]["message"]["content"]
        else:
            raise ValueError("Invalid response from VLLM")
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            await self.generate_text("Hello", max_tokens=10)
            return True
        except Exception as e:
            logger.error(f"VLLM health check failed: {e}")
            return False
