#!/bin/bash
# 快速检查多模态配置脚本

echo "======================================"
echo "多模态配置检查"
echo "======================================"
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查 .env 文件
echo "1. 检查 .env 文件..."
if [ -f ".env" ]; then
    echo -e "${GREEN}✓${NC} .env 文件存在"
    
    # 检查视觉模型配置
    if grep -q "VISION_VLLM_ENABLED=true" .env; then
        echo -e "${GREEN}✓${NC} 视觉模型已启用"
    else
        echo -e "${YELLOW}⚠${NC} 视觉模型未启用"
    fi
    
    if grep -q "VISION_VLLM_BASE_URL.*10009" .env; then
        echo -e "${GREEN}✓${NC} 视觉模型端口配置正确 (10009)"
    else
        echo -e "${RED}✗${NC} 视觉模型端口配置错误"
        echo "   当前配置: $(grep VISION_VLLM_BASE_URL .env)"
        echo "   应该是: VISION_VLLM_BASE_URL=http://223.109.239.14:10009/v1/chat/completions"
    fi
    
    # 检查主模型配置
    if grep -q "VLLM_BASE_URL" .env; then
        echo -e "${GREEN}✓${NC} 主模型配置存在"
        echo "   $(grep VLLM_BASE_URL .env)"
    fi
else
    echo -e "${RED}✗${NC} .env 文件不存在"
    echo "   请从 .env.example 复制并配置"
fi

echo ""

# 检查网络连接
echo "2. 检查网络连接..."
if ping -c 1 223.109.239.14 &> /dev/null; then
    echo -e "${GREEN}✓${NC} 服务器可达 (223.109.239.14)"
else
    echo -e "${RED}✗${NC} 服务器不可达"
fi

echo ""

# 检查端口
echo "3. 检查端口连接..."
if command -v nc &> /dev/null; then
    if nc -z -w 2 223.109.239.14 10009 2>/dev/null; then
        echo -e "${GREEN}✓${NC} 端口 10009 可访问"
    else
        echo -e "${RED}✗${NC} 端口 10009 不可访问"
        echo "   请确认服务器上的服务已启动"
    fi
else
    echo -e "${YELLOW}⚠${NC} nc 命令不可用，跳过端口检查"
fi

echo ""

# 检查服务健康
echo "4. 检查服务健康..."
if command -v curl &> /dev/null; then
    response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://223.109.239.14:10009/health 2>/dev/null)
    if [ "$response" = "200" ]; then
        echo -e "${GREEN}✓${NC} 视觉模型服务正常"
    else
        echo -e "${YELLOW}⚠${NC} 视觉模型服务响应异常 (HTTP $response)"
    fi
    
    # 检查模型列表
    models=$(curl -s --connect-timeout 5 http://223.109.239.14:10009/v1/models 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} 可以获取模型列表"
    else
        echo -e "${YELLOW}⚠${NC} 无法获取模型列表"
    fi
else
    echo -e "${YELLOW}⚠${NC} curl 命令不可用，跳过服务检查"
fi

echo ""

# 检查 Python 环境
echo "5. 检查 Python 环境..."
if command -v python &> /dev/null; then
    echo -e "${GREEN}✓${NC} Python 可用"
    python_version=$(python --version 2>&1)
    echo "   版本: $python_version"
    
    # 检查必要的包
    if python -c "import httpx" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} httpx 已安装"
    else
        echo -e "${RED}✗${NC} httpx 未安装"
    fi
    
    if python -c "from omni_agent.config.config import load_config" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} omni_agent 模块可导入"
    else
        echo -e "${RED}✗${NC} omni_agent 模块无法导入"
    fi
else
    echo -e "${RED}✗${NC} Python 不可用"
fi

echo ""

# 检查日志目录
echo "6. 检查日志目录..."
if [ -d "logs" ]; then
    echo -e "${GREEN}✓${NC} 日志目录存在"
    if [ -f "logs/omni_agent.log" ]; then
        echo -e "${GREEN}✓${NC} 日志文件存在"
        echo "   最近的错误:"
        tail -5 logs/omni_agent.log | grep -i error || echo "   (无错误)"
    fi
else
    echo -e "${YELLOW}⚠${NC} 日志目录不存在"
fi

echo ""

# 总结
echo "======================================"
echo "检查完成"
echo "======================================"
echo ""
echo "下一步:"
echo "1. 如果所有检查都通过，运行: python scripts/test_multimodal_config.py"
echo "2. 如果有错误，请参考: docs/QUICK_REFERENCE.md"
echo "3. 查看详细配置: docs/MULTIMODAL_CONFIG.md"
echo ""
