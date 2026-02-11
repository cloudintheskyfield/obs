"""VLLM客户端"""
import base64
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
        **kwargs
    ) -> Dict[str, Any]:
        """聊天完成请求"""
        if not self.client:
            raise RuntimeError("Client not initialized. Use async context manager.")
        
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4000),
            "stream": kwargs.get("stream", False)
        }
        
        try:
            logger.debug(f"Sending request to VLLM: {self.config.base_url}")
            
            response = await self.client.post(
                self.config.base_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json"
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            logger.debug("VLLM request successful")
            return result
            
        except httpx.HTTPError as e:
            logger.error(f"VLLM request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in VLLM request: {e}")
            raise
    
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