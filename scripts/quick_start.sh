#!/bin/bash

# 快速启动脚本 - 用于测试 UI 改进

echo "=================================="
echo "🚀 OBS Agent 快速启动"
echo "=================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否在正确的目录
if [ ! -f "src/main.py" ]; then
    echo -e "${YELLOW}⚠️  请在项目根目录运行此脚本${NC}"
    exit 1
fi

echo -e "${BLUE}📋 启动前检查...${NC}"
echo ""

# 检查 Python
if ! command -v python &> /dev/null; then
    echo -e "${YELLOW}⚠️  未找到 Python${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python 已安装${NC}"

# 检查必要的文件
if [ ! -f "ui/src/improvements.css" ]; then
    echo -e "${YELLOW}⚠️  未找到 improvements.css${NC}"
    exit 1
fi
echo -e "${GREEN}✅ CSS 文件存在${NC}"

# 检查 CSS 是否被引入
if ! grep -q "improvements.css" "ui/src/main.jsx"; then
    echo -e "${YELLOW}⚠️  CSS 未被引入${NC}"
    exit 1
fi
echo -e "${GREEN}✅ CSS 已引入${NC}"

echo ""
echo -e "${BLUE}🎯 UI 改进功能：${NC}"
echo "  1. ✅ 当前执行步骤显示"
echo "  2. ✅ Live Preview 自动打开"
echo "  3. ✅ 服务启动信息优化"
echo "  4. ✅ 任务列表样式改进"
echo ""

echo -e "${BLUE}📝 测试建议：${NC}"
echo "  1. 发送创建网页的请求，观察步骤显示"
echo "  2. 查看 Preview 是否自动打开"
echo "  3. 发送复杂任务，查看任务列表"
echo ""

echo -e "${GREEN}🚀 正在启动服务...${NC}"
echo ""
echo "=================================="
echo ""

# 启动服务
python -m main serve --reload
