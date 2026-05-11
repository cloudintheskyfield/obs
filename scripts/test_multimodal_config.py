#!/usr/bin/env python3
"""测试多模态配置脚本"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from config.config import load_config
from core.vllm_client import VLLMClient


async def test_text_model():
    """测试文本模型"""
    print("\n" + "="*60)
    print("测试文本模型（MiniMax）")
    print("="*60)
    
    config = load_config()
    
    print(f"✓ 主模型配置:")
    print(f"  - URL: {config.vllm.base_url}")
    print(f"  - Model: {config.vllm.model}")
    print(f"  - Timeout: {config.vllm.timeout}s")
    
    client = VLLMClient(config.vllm, config.vision_vllm)
    
    try:
        messages = [{"role": "user", "content": "你好，请回复'文本模型连接成功'"}]
        response = await client.chat_completion(messages, temperature=0.7)
        
        if response and "choices" in response:
            content = response["choices"][0]["message"]["content"]
            print(f"\n✓ 响应: {content}")
            print("✓ 文本模型测试成功！")
            return True
        else:
            print("✗ 响应格式错误")
            return False
            
    except Exception as e:
        print(f"✗ 文本模型测试失败: {e}")
        return False


async def test_vision_model():
    """测试视觉模型"""
    print("\n" + "="*60)
    print("测试视觉模型（Qwen2.5-VL）")
    print("="*60)
    
    config = load_config()
    
    print(f"✓ 视觉模型配置:")
    print(f"  - Enabled: {config.vision_vllm.enabled}")
    print(f"  - URL: {config.vision_vllm.base_url}")
    print(f"  - Model: {config.vision_vllm.model}")
    print(f"  - Timeout: {config.vision_vllm.timeout}s")
    
    if not config.vision_vllm.enabled:
        print("\n⚠ 视觉模型未启用，请在 .env 中设置 VISION_VLLM_ENABLED=true")
        return False
    
    client = VLLMClient(config.vllm, config.vision_vllm)
    
    try:
        # 创建一个包含图片的消息（使用占位符）
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "这是一个测试请求，请回复'视觉模型连接成功'"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                    }
                }
            ]
        }]
        
        # 验证路由逻辑
        picked_config = client._pick_config(messages)
        if picked_config == client.vision_config:
            print("\n✓ 路由逻辑正确：检测到图片，使用视觉模型")
        else:
            print("\n✗ 路由逻辑错误：应该使用视觉模型但使用了主模型")
            return False
        
        response = await client.chat_completion(messages, temperature=0.7)
        
        if response and "choices" in response:
            content = response["choices"][0]["message"]["content"]
            print(f"\n✓ 响应: {content}")
            print("✓ 视觉模型测试成功！")
            return True
        else:
            print("✗ 响应格式错误")
            return False
            
    except Exception as e:
        print(f"✗ 视觉模型测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_routing_logic():
    """测试路由逻辑"""
    print("\n" + "="*60)
    print("测试路由逻辑")
    print("="*60)
    
    config = load_config()
    client = VLLMClient(config.vllm, config.vision_vllm)
    
    # 测试1: 纯文本消息
    text_messages = [{"role": "user", "content": "Hello"}]
    picked = client._pick_config(text_messages)
    
    if picked == client.config:
        print("✓ 纯文本消息 → 主模型")
    else:
        print("✗ 纯文本消息路由错误")
        return False
    
    # 测试2: 包含图片的消息
    image_messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "描述这张图片"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ]
    }]
    picked = client._pick_config(image_messages)
    
    if config.vision_vllm.enabled:
        if picked == client.vision_config:
            print("✓ 图片消息 → 视觉模型")
        else:
            print("✗ 图片消息路由错误")
            return False
    else:
        print("⚠ 视觉模型未启用，跳过图片路由测试")
    
    print("\n✓ 路由逻辑测试通过！")
    return True


async def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("多模态配置测试")
    print("="*60)
    
    results = []
    
    # 测试路由逻辑
    results.append(("路由逻辑", await test_routing_logic()))
    
    # 测试文本模型
    results.append(("文本模型", await test_text_model()))
    
    # 测试视觉模型
    results.append(("视觉模型", await test_vision_model()))
    
    # 汇总结果
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    
    for name, success in results:
        status = "✓ 通过" if success else "✗ 失败"
        print(f"{name}: {status}")
    
    all_passed = all(success for _, success in results)
    
    if all_passed:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print("\n⚠ 部分测试失败，请检查配置")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
