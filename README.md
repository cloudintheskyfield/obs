# 🤖 Omni Agent - 全能AI智能助手

基于Claude Skills三级架构的全能AI Agent，支持文件操作、终端执行、网页浏览等多种功能。

## ✨ 特性

- 🎯 **Claude Skills三级架构** - 完全按照[Claude官方Skills文档](https://code.claude.com/docs/en/skills)实现
- 🌐 **现代化Web界面** - 实时聊天、会话管理、主题切换
- 🖥️ **计算机视觉操作** - 屏幕截图、鼠标键盘控制、网页浏览
- 📁 **文件管理** - 查看、编辑、创建各种格式文件  
- 🔧 **终端执行** - 安全的命令行操作
- 🚀 **高性能部署** - Docker容器化，代码热重载
- 💾 **会话记忆** - 持久化对话历史和上下文管理

## 🚀 快速开始

### 方式1：本地开发模式 (推荐)

```bash
# 1. 进入项目目录
cd omni-agent

# 2. 启动服务 (自动安装依赖)
python quick_start.py

# 3. 浏览器访问
# 前端界面: http://127.0.0.1:8002
# API文档: http://127.0.0.1:8002/docs
```

### 方式2：Docker部署

```bash
# Windows用户
deploy.bat

# 或手动部署
docker-compose up -d

# 访问: http://localhost:8000
```

### 方式3：命令行交互

```bash
# 启动交互式聊天
python chat_demo.py
```

## 🎮 使用指南

### Web界面操作

1. **新建对话** - 点击左侧"新建对话"开始
2. **输入命令** - 支持多种格式：
   - `file:view README.md` - 查看文件
   - `cmd:ls -la` - 执行命令
   - `screenshot` - 截取屏幕
   - 普通对话 - 自然语言交互

3. **快捷操作** - 使用底部快捷按钮
4. **会话管理** - 左侧自动保存所有对话
5. **主题切换** - 右上角设置按钮

### 命令格式详解

#### 🖼️ 屏幕操作
```
screenshot                    # 获取屏幕截图
click:100,200                # 点击坐标(100,200)
type:Hello World             # 输入文字
```

#### 📁 文件操作
```
file:view path/to/file.txt   # 查看文件内容
file:create test.py "print('hello')"  # 创建文件
file:edit path line "new content"     # 编辑文件
```

#### 🔧 终端命令
```
cmd:ls -la                   # 列出目录
cmd:python --version         # 检查Python版本
cmd:git status               # Git操作
cmd:npm install              # 包管理
```

## 🏗️ 架构设计

### Claude Skills三级架构

项目严格按照Claude官方Skills架构设计：

```
.claude/skills/
├── computer-use/           # 计算机视觉操作技能
│   ├── SKILL.md           # Level 1: 元数据 + Level 2: 指令
│   ├── computer_use.py    # Level 3: Python实现
│   └── examples/          # 使用示例
├── file-operations/        # 文件操作技能  
│   ├── SKILL.md
│   ├── text_editor.py
│   └── examples/
└── terminal/              # 终端执行技能
    ├── SKILL.md
    ├── bash.py
    └── examples/
```

#### Level 1: 元数据 (始终加载)
```yaml
---
name: computer-use
description: Use mouse and keyboard to interact with computer
---
```

#### Level 2: 指令 (触发时加载)
```markdown
# Computer Use Skill

使用此技能通过视觉界面与计算机交互...

## Quick Start
## Available Actions  
## Workflows
## Best Practices
```

#### Level 3: 代码 (按需加载)
```python
class ComputerUseSkill(BaseSkill):
    async def execute(self, **kwargs):
        # 具体实现逻辑
        pass
```

## 🔧 技能详解

### 1. 计算机视觉技能 (computer-use)

**功能**: 屏幕截图、鼠标键盘操作、网页浏览

**可用操作**:
- `screenshot` - 截取屏幕
- `left_click` - 左键点击
- `right_click` - 右键点击  
- `type` - 文字输入
- `key` - 特殊按键

**示例**:
```python
# 截图查看当前状态
result = await execute_skill("computer", action="screenshot")

# 点击指定坐标
result = await execute_skill("computer", 
    action="left_click", 
    coordinate=[100, 200]
)
```

### 2. 文件操作技能 (file-operations)

**功能**: 文本文件的查看、创建、编辑、管理

**支持格式**: `.py`, `.js`, `.html`, `.json`, `.md`, `.txt` 等

**可用命令**:
- `view` - 查看文件内容
- `create` - 创建新文件
- `str_replace` - 字符串替换
- `insert` - 插入文本
- `undo_edit` - 撤销编辑

**示例**:
```python
# 查看文件
result = await execute_skill("str_replace_editor",
    command="view",
    path="src/main.py"
)

# 创建文件
result = await execute_skill("str_replace_editor",
    command="create", 
    path="test.py",
    file_text="print('Hello World')"
)
```

### 3. 终端执行技能 (terminal)

**功能**: 安全的命令行操作，支持多种开发工具

**允许的命令类型**:
- 文件操作: `ls`, `cat`, `mkdir`, `cp`, `mv`
- 开发工具: `python`, `node`, `git`, `npm`, `pip`
- 系统工具: `curl`, `wget`, `ps`, `top`

**安全机制**:
- 命令白名单验证
- 危险操作拦截
- 超时保护
- 工作目录隔离

**示例**:
```python
# 执行Python脚本
result = await execute_skill("bash",
    command="python script.py",
    timeout=30
)

# Git操作
result = await execute_skill("bash",
    command="git status"
)
```

## 🛠️ 开发指南

### 添加新技能

1. **创建技能目录**:
```bash
mkdir .claude/skills/my-skill
```

2. **编写SKILL.md**:
```yaml
---
name: my-skill
description: My custom skill description
---

# My Skill

详细说明和使用指南...
```

3. **实现Python类**:
```python
class MySkill(BaseSkill):
    def __init__(self):
        super().__init__(
            name="my-skill",
            description="My skill description"
        )
    
    async def execute(self, **kwargs):
        # 实现逻辑
        return SkillResult(success=True, content="结果")
```

### 配置环境变量

创建 `.env` 文件：
```bash
# VLLM多模态模型配置
VLLM_BASE_URL=http://223.109.239.14:10002/v1/chat/completions
VLLM_API_KEY=your_api_key
VLLM_MODEL=multimodal_model

# 工作目录
WORK_DIR=./workspace

# 功能开关
ENABLE_COMPUTER_USE=true
ENABLE_TEXT_EDITOR=true  
ENABLE_BASH=true

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=./logs/omni_agent.log
```

## 🐳 Docker部署

### 开发模式 (极速重载)
```bash
# 0.05秒内检测代码变更并重启
docker-compose -f docker-compose.dev.yml up -d
```

### 生产模式  
```bash
# 稳定运行，适合生产环境
docker-compose up -d
```

### 容器管理
```bash
# 查看日志
docker-compose logs -f omni-agent

# 重启服务  
docker-compose restart

# 停止服务
docker-compose down
```

## 📋 API接口

### 核心端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/skills` | GET | 获取技能列表 |  
| `/execute` | POST | 执行技能 |
| `/` | GET | Web前端界面 |

### 执行技能
```bash
curl -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "computer",
    "parameters": {
      "action": "screenshot"
    }
  }'
```

## 🔒 安全机制

- **命令白名单** - 只允许安全的系统命令
- **路径验证** - 文件操作限制在工作目录内
- **超时保护** - 防止命令无限执行
- **权限隔离** - 容器化运行环境
- **输入验证** - 严格的参数检查

## 🐛 故障排除

### 常见问题

**1. 服务启动失败**
```bash
# 检查端口占用
netstat -an | findstr 8002

# 查看详细日志
python quick_start.py
```

**2. 技能加载失败**
```bash
# 检查.claude/skills目录结构
ls -la .claude/skills/

# 验证SKILL.md格式
```

**3. Docker构建失败**
```bash
# 使用本地模式
python quick_start.py

# 或配置Docker镜像加速器
docker_setup.bat
```

**4. 前端访问问题**
```bash
# 确认服务运行状态
curl http://127.0.0.1:8002/health

# 检查防火墙设置
```

## 🎯 路线图

- [ ] 集成VLLM多模态推理
- [ ] 支持更多文件格式
- [ ] 增强网页爬虫能力
- [ ] 添加数据库操作技能
- [ ] 支持插件市场
- [ ] 移动端适配
- [ ] 多用户支持

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 🤝 贡献

欢迎提交Issue和Pull Request！

1. Fork 项目
2. 创建功能分支
3. 提交更改  
4. 推送到分支
5. 创建Pull Request

## 📞 支持

- 📧 邮箱: support@omni-agent.com
- 💬 问题反馈: [GitHub Issues](https://github.com/your-repo/omni-agent/issues)
- 📚 文档: [在线文档](https://docs.omni-agent.com)

---

⭐ 如果这个项目对你有帮助，请给个Star！

**Made with ❤️ by Omni Agent Team**