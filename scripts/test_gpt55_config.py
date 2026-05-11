#!/usr/bin/env python3
"""测试 GPT-5.5 配置和连接"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.config import load_config
from core.vllm_client import VLLMClient


async def test_gpt55_config():
    """测试 GPT-5.5 配置"""
    print("=" * 60)
    print("测试 GPT-5.5 配置")
    print("=" * 60)
    
    config = load_config()
    
    print("\n1. 配置信息:")
    print(f"  - Enabled: {config.gpt55.enabled}")
    print(f"  - Base URL: {config.gpt55.base_url}")
    print(f"  - Model: {config.gpt55.model}")
    print(f"  - API Key: {config.gpt55.api_key[:20]}..." if len(config.gpt55.api_key) > 20 else config.gpt55.api_key)
    print(f"  - Timeout: {config.gpt55.timeout}s")
    
    if not config.gpt55.enabled:
        print("\n❌ GPT-5.5 未启用，请在 .env 中设置 GPT55_ENABLED=true")
        return False
    
    print("\n2. 测试连接...")
    client = VLLMClient(config.vllm, config.vision_vllm, config.gpt55)
    
    try:
        async with client:
            # 测试纯文本消息（应该使用 GPT-5.5）
            messages = [
                {"role": "user", "content": "你好，请回复'GPT-5.5 连接成功'"}
            ]
            
            print("  发送测试消息...")
            response = await client.chat_completion(
                messages=messages,
                model="gpt-5.5",  # 明确指定使用 GPT-5.5
                stream=False,
                temperature=0.7,
                max_tokens=100
            )
            
            if "choices" in response and response["choices"]:
                content = response["choices"][0].get("message", {}).get("content", "")
                print(f"\n✅ GPT-5.5 响应: {content}")
                return True
            else:
                print(f"\n❌ 响应格式异常: {response}")
                return False
                
    except Exception as e:
        print(f"\n❌ 连接失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_model_routing():
    """测试模型路由逻辑"""
    print("\n" + "=" * 60)
    print("测试模型路由")
    print("=" * 60)
    
    config = load_config()
    client = VLLMClient(config.vllm, config.vision_vllm, config.gpt55)
    
    try:
        async with client:
            # 测试1: 明确指定 gpt-5.5
            print("\n1. 测试明确指定 gpt-5.5:")
            messages = [{"role": "user", "content": "测试"}]
            active_cfg = client._pick_config(messages, model="gpt-5.5")
            print(f"  路由到: {active_cfg.base_url}")
            print(f"  模型: {active_cfg.model}")
            assert active_cfg is config.gpt55, "应该路由到 GPT-5.5"
            print("  ✅ 正确路由到 GPT-5.5")
            
            # 测试2: 默认使用 MiniMax
            print("\n2. 测试默认使用 MiniMax:")
            active_cfg = client._pick_config(messages, model=None)
            print(f"  路由到: {active_cfg.base_url}")
            print(f"  模型: {active_cfg.model}")
            assert active_cfg is config.vllm, "应该路由到 MiniMax"
            print("  ✅ 正确路由到 MiniMax")
            
            # 测试3: 图片消息路由到视觉模型
            print("\n3. 测试图片消息路由:")
            image_messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这是什么？"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
                    ]
                }
            ]
            active_cfg = client._pick_config(image_messages, model=None)
            print(f"  路由到: {active_cfg.base_url}")
            print(f"  模型: {active_cfg.model}")
            if config.vision_vllm.enabled:
                assert active_cfg is config.vision_vllm, "应该路由到视觉模型"
                print("  ✅ 正确路由到视觉模型")
            else:
                print("  ⚠️  视觉模型未启用")
            
            print("\n✅ 所有路由测试通过")
            return True
            
    except Exception as e:
        print(f"\n❌ 路由测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("\n🚀 开始测试 GPT-5.5 配置\n")
    
    # 测试配置和连接
    config_ok = await test_gpt55_config()
    
    # 测试路由逻辑
    routing_ok = await test_model_routing()
    
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"配置测试: {'✅ 通过' if config_ok else '❌ 失败'}")
    print(f"路由测试: {'✅ 通过' if routing_ok else '❌ 失败'}")
    
    if config_ok and routing_ok:
        print("\n🎉 所有测试通过！GPT-5.5 配置正常")
        return 0
    else:
        print("\n❌ 部分测试失败，请检查配置")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
