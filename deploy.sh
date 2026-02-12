#!/bin/bash
# Omni Agent 部署脚本

set -e

echo "=== Omni Agent 部署脚本 ==="

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 检查Docker是否安装
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker 未安装，请先安装Docker${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose 未安装，请先安装Docker Compose${NC}"
    exit 1
fi

# 选择部署模式
echo -e "${YELLOW}选择部署模式:${NC}"
echo "1. 开发模式 (代码热重载)"
echo "2. 生产模式 (稳定运行)"
echo "3. 本地模式 (不使用Docker)"
read -p "请输入选择 (1/2/3): " MODE

case $MODE in
    1)
        echo -e "${GREEN}🔧 启动开发模式...${NC}"
        # 确保挂载目录存在
        mkdir -p workspace logs screenshots
        
        # 开发模式启动
        docker-compose up -d
        
        echo -e "${GREEN}✅ 开发模式启动成功！${NC}"
        echo -e "${YELLOW}访问地址:${NC}"
        echo "  🌐 前端界面: http://localhost:8000"
        echo "  📚 API文档: http://localhost:8000/docs"
        echo "  ❤️  健康检查: http://localhost:8000/health"
        echo ""
        echo -e "${YELLOW}实时日志查看:${NC}"
        echo "  docker-compose logs -f omni-agent"
        echo ""
        echo -e "${YELLOW}代码修改自动生效:${NC}"
        echo "  ✅ 修改 src/ 目录下的Python代码会自动重载"
        echo "  ✅ 修改 .claude/skills/ 目录下的技能会自动重载"
        echo "  ✅ 修改 frontend/ 目录下的前端代码会立即生效"
        ;;
        
    2)
        echo -e "${GREEN}🚀 启动生产模式...${NC}"
        # 复制生产配置
        if [ ! -f docker-compose.prod.yml ]; then
            cp docker-compose.yml docker-compose.prod.yml
            # 移除开发模式的reload参数
            sed -i 's/--reload[^"]*//g' docker-compose.prod.yml
        fi
        
        # 生产模式启动
        docker-compose -f docker-compose.prod.yml up -d
        
        echo -e "${GREEN}✅ 生产模式启动成功！${NC}"
        echo -e "${YELLOW}访问地址:${NC}"
        echo "  🌐 前端界面: http://localhost:8000"
        echo "  📚 API文档: http://localhost:8000/docs"
        ;;
        
    3)
        echo -e "${GREEN}💻 启动本地模式...${NC}"
        
        # 检查Python环境
        if ! command -v python &> /dev/null; then
            echo -e "${RED}❌ Python 未安装${NC}"
            exit 1
        fi
        
        # 检查uv
        if ! command -v uv &> /dev/null; then
            echo -e "${YELLOW}⚠️  uv 未安装，正在安装...${NC}"
            curl -LsSf https://astral.sh/uv/install.sh | sh
            source ~/.local/bin/env
        fi
        
        # 安装依赖
        echo -e "${YELLOW}📦 安装依赖...${NC}"
        uv sync
        
        # 创建必要目录
        mkdir -p workspace logs screenshots
        
        echo -e "${GREEN}✅ 本地模式准备完成！${NC}"
        echo -e "${YELLOW}启动选项:${NC}"
        echo "  🖥️  本地API服务: python test_local_api.py"
        echo "  💬 命令行界面: python chat_interface.py"
        echo "  🧪 系统测试: python test_system_simple.py"
        echo ""
        echo -e "${YELLOW}访问地址 (启动后):${NC}"
        echo "  🌐 前端界面: 直接打开 frontend/index.html"
        echo "  📚 API文档: http://localhost:8001/docs"
        ;;
        
    *)
        echo -e "${RED}❌ 无效选择${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}🎉 部署完成！${NC}"

# 等待服务启动
if [ "$MODE" = "1" ] || [ "$MODE" = "2" ]; then
    echo -e "${YELLOW}⏳ 等待服务启动...${NC}"
    sleep 10
    
    # 健康检查
    if curl -sf http://localhost:8000/health > /dev/null; then
        echo -e "${GREEN}✅ 服务启动成功！${NC}"
        
        # 显示技能状态
        echo -e "${YELLOW}📋 技能状态:${NC}"
        curl -s http://localhost:8000/skills | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    skills = data.get('skills', [])
    print(f'  ✅ 已加载 {len(skills)} 个技能')
    for skill in skills:
        print(f'    - {skill[\"name\"]}: {skill[\"description\"][:40]}...')
except:
    print('  ⚠️  技能信息获取失败')
"
    else
        echo -e "${YELLOW}⚠️  服务可能还在启动中，请稍后访问${NC}"
    fi
fi

echo ""
echo -e "${YELLOW}📋 常用命令:${NC}"
echo "  查看日志: docker-compose logs -f omni-agent"
echo "  重启服务: docker-compose restart omni-agent"  
echo "  停止服务: docker-compose down"
echo "  完整重建: docker-compose down && docker-compose up --build -d"