#!/bin/bash

# UI 改进测试脚本

echo "=================================="
echo "🧪 UI 改进测试脚本"
echo "=================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试计数
PASSED=0
FAILED=0

# 测试函数
test_file_exists() {
    local file=$1
    local description=$2
    
    if [ -f "$file" ]; then
        echo -e "${GREEN}✅ PASS${NC}: $description"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}❌ FAIL${NC}: $description"
        echo -e "   文件不存在: $file"
        ((FAILED++))
        return 1
    fi
}

test_file_contains() {
    local file=$1
    local pattern=$2
    local description=$3
    
    if [ ! -f "$file" ]; then
        echo -e "${RED}❌ FAIL${NC}: $description"
        echo -e "   文件不存在: $file"
        ((FAILED++))
        return 1
    fi
    
    if grep -q "$pattern" "$file"; then
        echo -e "${GREEN}✅ PASS${NC}: $description"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}❌ FAIL${NC}: $description"
        echo -e "   未找到模式: $pattern"
        ((FAILED++))
        return 1
    fi
}

echo "📋 测试 1: 检查文件是否存在"
echo "--------------------------------"
test_file_exists "ui/src/improvements.css" "CSS 样式文件已创建"
test_file_exists "ui/src/main.jsx" "主入口文件存在"
test_file_exists "ui/src/App.jsx" "App 组件文件存在"
test_file_exists "src/main.py" "后端主文件存在"
echo ""

echo "📋 测试 2: 检查 CSS 是否被引入"
echo "--------------------------------"
test_file_contains "ui/src/main.jsx" "improvements.css" "main.jsx 引入了 improvements.css"
echo ""

echo "📋 测试 3: 检查当前步骤状态是否存在"
echo "--------------------------------"
test_file_contains "ui/src/App.jsx" "currentExecutingStep" "App.jsx 包含 currentExecutingStep 状态"
test_file_contains "ui/src/App.jsx" "current-step-banner" "App.jsx 包含步骤横幅渲染"
test_file_contains "ui/src/App.jsx" "setCurrentExecutingStep" "App.jsx 包含状态更新逻辑"
echo ""

echo "📋 测试 4: 检查 CSS 样式定义"
echo "--------------------------------"
test_file_contains "ui/src/improvements.css" "current-step-banner" "CSS 包含横幅样式"
test_file_contains "ui/src/improvements.css" "slideDown" "CSS 包含下滑动画"
test_file_contains "ui/src/improvements.css" "todo-strip" "CSS 包含任务列表样式"
echo ""

echo "📋 测试 5: 检查 Preview 自动打开逻辑"
echo "--------------------------------"
test_file_contains "ui/src/App.jsx" "detectedPreviewUrls" "App.jsx 包含 URL 检测"
test_file_contains "ui/src/App.jsx" "setPreviewOpen" "App.jsx 包含 Preview 打开逻辑"
echo ""

echo "📋 测试 6: 检查服务启动优化"
echo "--------------------------------"
test_file_contains "src/main.py" "本地访问" "main.py 包含启动信息输出"
test_file_contains "src/main.py" "actual_port" "main.py 包含端口变量"
echo ""

echo "=================================="
echo "📊 测试结果汇总"
echo "=================================="
echo -e "${GREEN}通过: $PASSED${NC}"
echo -e "${RED}失败: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 所有测试通过！${NC}"
    echo ""
    echo "✅ UI 改进已正确实施"
    echo ""
    echo "🚀 下一步："
    echo "   1. 启动服务: python -m main serve --reload"
    echo "   2. 访问: http://localhost:8000"
    echo "   3. 测试当前步骤显示功能"
    echo "   4. 测试 Preview 自动打开功能"
    echo ""
    exit 0
else
    echo -e "${RED}⚠️  有 $FAILED 个测试失败${NC}"
    echo ""
    echo "请检查上述失败的测试项"
    echo ""
    exit 1
fi
