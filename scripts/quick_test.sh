#!/bin/bash
# 快速测试多模态配置

echo "======================================"
echo "多模态配置快速测试"
echo "======================================"
echo ""

# 测试端口连接
echo "1. 测试端口 10009 连接..."
if curl -s --connect-timeout 5 http://223.109.239.14:10009/health > /dev/null 2>&1; then
    echo "✓ 端口 10009 可访问"
else
    echo "✗ 端口 10009 不可访问"
    echo "  请先在服务器上启动服务"
    echo "  查看: START_VLLM_SERVER.md"
    exit 1
fi

echo ""

# 测试模型列表
echo "2. 获取模型列表..."
response=$(curl -s http://223.109.239.14:10009/v1/models)
if echo "$response" | grep -q "qwen35-35b-a3b-judge"; then
    echo "✓ 模型服务正常"
    echo "  模型: qwen35-35b-a3b-judge"
else
    echo "⚠ 模型响应异常"
    echo "  响应: $response"
fi

echo ""

# 检查配置
echo "3. 检查本地配置..."
if grep -q "VISION_VLLM_BASE_URL.*10009" .env 2>/dev/null; then
    echo "✓ .env 配置正确"
else
    echo "✗ .env 配置错误或不存在"
fi

if grep -q "VISION_VLLM_ENABLED=true" .env 2>/dev/null; then
    echo "✓ 视觉模型已启用"
else
    echo "⚠ 视觉模型未启用"
fi

echo ""

# 运行 Python 测试
echo "4. 运行 Python 测试..."
if command -v python &> /dev/null; then
    if [ -f "scripts/test_multimodal_config.py" ]; then
        echo "执行: python scripts/test_multimodal_config.py"
        python scripts/test_multimodal_config.py
    else
        echo "⚠ 测试脚本不存在"
    fi
else
    echo "⚠ Python 不可用"
fi

echo ""
echo "======================================"
echo "测试完成"
echo "======================================"
