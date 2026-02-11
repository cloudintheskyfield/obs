# 🤖 Omni Agent - 全能AI助手

一个基于Claude Skills的全能AI Agent，支持多模态网页浏览、文件处理、终端执行和智能任务调度。

## ✨ 主要特性

### 🌐 多模态网页浏览
- **智能网页分析**: 使用多模态AI理解网页内容
- **自动化交互**: 支持点击、输入、滚动等操作
- **截图记录**: 自动保存操作过程截图
- **任务执行**: 根据自然语言描述执行复杂网页任务

### 📁 安全文件操作
- **文件读写**: 安全的文件读取和写入操作
- **目录管理**: 创建、列出、搜索目录和文件
- **文件操作**: 复制、移动、删除文件
- **安全限制**: 工作目录隔离和文件类型限制

### 💻 终端执行
- **命令执行**: 支持同步和异步命令执行
- **后台进程**: 启动和管理后台进程
- **实时输出**: 流式输出显示
- **进程管理**: 进程列表、停止和清理

### 🧠 Claude Skills集成
- **多种技能**: 网页搜索、代码分析、数据处理等
- **双引擎**: 支持Claude API和本地VLLM
- **智能路由**: 根据任务类型自动选择合适的AI引擎

### 📊 实时监控
- **实时日志**: 彩色实时日志显示
- **任务追踪**: 完整的任务执行历史
- **状态监控**: 系统状态和组件状态监控
- **性能统计**: 执行时间和成功率统计

## 🚀 快速开始

### 环境要求
- Python 3.11+
- uv (包管理器)

### 安装

```bash
# 克隆项目
git clone <repository-url>
cd omni-agent

# 使用uv安装依赖
uv sync

# 安装Playwright浏览器
playwright install chromium
```

### 配置

设置环境变量：

```bash
# VLLM服务配置
export VLLM_BASE_URL="http://223.109.239.14:10002/v1/chat/completions"
export VLLM_MODEL="multimodal_model"

# Claude API密钥（可选）
export CLAUDE_API_KEY="your-claude-api-key"

# 工作目录
export WORK_DIR="workspace"
```

### 启动

```bash
# 启动交互式会话
uv run omni-agent start

# 启用实时日志显示
uv run omni-agent start --live-logs

# 测试VLLM连接
uv run omni-agent test
```

## 📖 使用指南

### 命令格式

#### 网页浏览
```bash
# 简单格式
web:https://example.com

# JSON格式
{"type": "web_browsing", "url": "https://example.com", "task": "分析网页内容"}
```

#### 文件操作
```bash
# 读取文件
file:read example.txt

# 列出目录
file:list /path/to/directory

# JSON格式
{"type": "file_operation", "operation": "write", "file_path": "test.txt", "content": "Hello World"}
```

#### 终端执行
```bash
# 执行命令
terminal:ls -la

# JSON格式
{"type": "terminal_execution", "operation": "execute", "command": "python script.py"}
```

#### Claude Skills
```bash
# 代码分析
skill:code_analysis {"code": "def hello(): print('world')", "language": "python"}

# 网页搜索
skill:web_search {"query": "AI news"}

# 规划任务
skill:planning {"goal": "创建一个网站", "timeline": "一周"}
```

#### 多模态分析
```bash
# JSON格式
{"type": "multimodal_analysis", "prompt": "分析这张图片", "images": ["path/to/image.jpg"]}
```

### 复杂任务

Agent支持复杂的多步骤任务：

```json
{
  "type": "complex_task",
  "description": "创建一个简单的网站并部署",
  "steps": [
    {
      "type": "file_operation",
      "operation": "write",
      "file_path": "index.html",
      "content": "<html>...</html>"
    },
    {
      "type": "terminal_execution",
      "operation": "execute",
      "command": "python -m http.server 8000"
    }
  ]
}
```

## 🏗️ 项目架构

```
omni-agent/
├── src/omni_agent/
│   ├── core/                 # 核心组件
│   │   ├── agent.py         # 主Agent调度器
│   │   ├── vllm_client.py   # VLLM多模态客户端
│   │   └── logger.py        # 实时日志系统
│   ├── agents/              # 专用Agent
│   │   └── web_agent.py     # 网页浏览Agent
│   ├── tools/               # 工具集
│   │   ├── file_tool.py     # 文件处理工具
│   │   ├── terminal_tool.py # 终端执行工具
│   │   └── claude_skills.py # Claude Skills集成
│   ├── config/              # 配置管理
│   │   └── config.py        # 配置模型
│   └── main.py              # CLI入口
├── config/                  # 配置文件
├── logs/                    # 日志文件
├── screenshots/             # 网页截图
├── workspace/               # 工作目录
└── tests/                   # 测试文件
```

## 🔧 配置选项

### VLLM配置
- `base_url`: VLLM服务地址
- `model`: 模型名称
- `timeout`: 请求超时时间
- `max_retries`: 最大重试次数

### 网页浏览配置
- `headless`: 是否无头模式
- `timeout`: 页面超时时间
- `screenshot_dir`: 截图保存目录
- `user_agent`: 用户代理

### 安全配置
- `allow_file_operations`: 是否允许文件操作
- `allow_terminal_execution`: 是否允许终端执行
- `work_dir`: 工作目录限制

## 🔒 安全特性

### 文件操作安全
- ✅ 工作目录隔离
- ✅ 文件类型白名单
- ✅ 危险路径检测
- ✅ 权限控制

### 终端执行安全
- ✅ 命令白名单
- ✅ 危险命令黑名单
- ✅ 工作目录限制
- ✅ 进程管理

### 网络安全
- ✅ 域名白名单（可配置）
- ✅ 用户代理控制
- ✅ 超时保护

## 🚧 开发计划

- [ ] Web API接口
- [ ] 插件系统
- [ ] 任务队列
- [ ] 分布式部署
- [ ] 更多Claude Skills
- [ ] 图形化界面

## 🤝 贡献指南

欢迎贡献代码、报告bug或提出功能建议！

1. Fork项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建Pull Request

## 📄 许可证

[MIT License](LICENSE)

## 📞 支持

如有问题或建议，请通过以下方式联系：
- 提交Issue
- 发送邮件
- 加入讨论群

---

**⚡ Omni Agent - 让AI为你完成一切复杂任务！**