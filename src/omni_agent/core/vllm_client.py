"""VLLM客户端"""
import base64
import json
import asyncio
from typing import List, Dict, Any, Optional, Union

import httpx
from loguru import logger

from ..config.config import VLLMConfig


class VLLMClient:
    """VLLM多模态客户端"""
    
    def __init__(self, config: VLLMConfig):
        self.config = config
        self.client: Optional[httpx.AsyncClient] = None
    
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
            **kwargs: 其他参数（temperature, max_tokens, stream等）
        
        Returns:
            API响应结果或异步生成器（如果stream=True）
        """
        if not self.client:
            raise RuntimeError("Client not initialized. Use async context manager.")
        
        stream = kwargs.get("stream", False)
        
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4000),
            "stream": stream
        }
        
        if tools:
            payload["tools"] = self._normalize_tools_for_provider(tools)
            payload["tool_choice"] = kwargs.get("tool_choice", "auto")
            logger.debug(f"Including {len(tools)} tools in request")
        
        try:
            logger.debug(f"Sending request to VLLM: {self.config.base_url}")
            
            if stream:
                # 流式请求
                async def stream_generator():
                    headers = {
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json"
                    }
                    retries = max(1, int(self.config.max_retries))
                    for attempt in range(1, retries + 1):
                        try:
                            async with self.client.stream(
                                "POST",
                                self.config.base_url,
                                json=payload,
                                headers=headers
                            ) as response:
                                if response.is_error:
                                    error_text = await response.aread()
                                    logger.error(f"VLLM stream request failed: {response.status_code} {error_text.decode(errors='ignore')[:2000]}")
                                    if self._is_retryable_status(response.status_code) and attempt < retries:
                                        await asyncio.sleep(min(1.5 * attempt, 5))
                                        continue
                                    response.raise_for_status()
                                async for line in response.aiter_lines():
                                    if line.startswith("data: "):
                                        data_str = line[6:]
                                        if data_str == "[DONE]":
                                            return
                                        try:
                                            data = json.loads(data_str)
                                            yield data
                                        except json.JSONDecodeError:
                                            continue
                                return
                        except httpx.HTTPError as exc:
                            if attempt < retries and self._is_retryable_exception(exc):
                                logger.warning(f"Retrying VLLM stream request after error: {exc}")
                                await asyncio.sleep(min(1.5 * attempt, 5))
                                continue
                            raise

                return stream_generator()
            else:
                # 非流式请求
                headers = {
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json"
                }
                retries = max(1, int(self.config.max_retries))
                last_error: Optional[Exception] = None
                for attempt in range(1, retries + 1):
                    try:
                        response = await self.client.post(
                            self.config.base_url,
                            json=payload,
                            headers=headers
                        )
                        
                        if response.is_error:
                            logger.error(f"VLLM request failed: {response.status_code} {response.text[:2000]}")
                            if self._is_retryable_status(response.status_code) and attempt < retries:
                                await asyncio.sleep(min(1.5 * attempt, 5))
                                continue
                        response.raise_for_status()
                        result = response.json()
                        
                        logger.debug("VLLM request successful")
                        return result
                    except httpx.HTTPError as exc:
                        last_error = exc
                        if attempt < retries and self._is_retryable_exception(exc):
                            logger.warning(f"Retrying VLLM request after error: {exc}")
                            await asyncio.sleep(min(1.5 * attempt, 5))
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
