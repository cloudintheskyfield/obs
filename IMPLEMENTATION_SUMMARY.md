# 模型选择和 Thinking 合并实现总结

## 需求
将模型选择下拉框和 Thinking 开关合并为一个下拉框，提供三个选项：
1. MiniMax-M2 (thinking)
2. MiniMax-M2 (非thinking)
3. GPT-5.5 (新增的 AceData API)

## 实现的修改

### 1. 前端修改 (ui/src/components/Composer.jsx)
- **移除**: 独立的 Thinking 按钮
- **修改**: 模型选择下拉框，合并了模型和 thinking 状态
- **新增**: 三个选项的组合逻辑
  - `minimax-m2-thinking`: MiniMax-M2 + thinking 开启
  - `minimax-m2`: MiniMax-M2 + thinking 关闭
  - `gpt-5.5`: GPT-5.5 模型（不支持 thinking）

### 2. 配置文件修改 (src/omni_agent/config/config.py)
- **新增**: `GPT55Config` 类，定义 GPT-5.5 配置
  - `base_url`: https://api.acedata.cloud/openai/chat/completions
  - `api_key`: 587473ccbe934b3fa700adb9ec442955
  - `model`: gpt-5.5
  - `timeout`: 60秒
  - `max_retries`: 3次

- **修改**: `AgentConfig` 类，添加 `gpt55` 字段
- **修改**: `from_env` 方法，支持从环境变量加载 GPT-5.5 配置
  - `GPT55_ENABLED`
  - `GPT55_BASE_URL`
  - `GPT55_API_KEY`
  - `GPT55_MODEL`

### 3. VLLM 客户端修改 (src/omni_agent/core/vllm_client.py)
- **修改**: `__init__` 方法，接受 `gpt55_config` 参数
- **修改**: `_pick_config` 方法，支持 GPT-5.5 路由
  - 优先级1: 如果指定 `model="gpt-5.5"`，使用 GPT-5.5 配置
  - 优先级2: 如果消息包含图片，使用视觉模型配置
  - 优先级3: 默认使用 MiniMax-M2 配置

- **修改**: `chat_completion` 方法
  - 支持通过 `model` 参数指定使用的模型
  - GPT-5.5 和视觉模型不发送工具参数（可能不支持）
  - 添加详细的日志记录

### 4. 初始化代码修改
- **src/omni_agent/core/agent.py**: 传递 `gpt55_config` 到 VLLMClient
- **src/omni_agent/api.py**: 传递 `gpt55_config` 到 VLLMClient

### 5. 环境变量配置
- **.env**: 添加 GPT-5.5 配置
  ```env
  GPT55_ENABLED=true
  GPT55_BASE_URL=https://api.acedata.cloud/openai/chat/completions
  GPT55_API_KEY=587473ccbe934b3fa700adb9ec442955
  GPT55_MODEL=gpt-5.5
  ```

- **.env.example**: 添加 GPT-5.5 配置示例

### 6. 任务列表自动完成修复 (src/omni_agent/agents/streaming_agent.py)
- **新增**: 在工具执行成功后自动调用 `_auto_advance_pinned_plan_todo_round`
- **位置**: 在 `for tool_call in tool_calls:` 循环结束后
- **逻辑**: 如果本轮有任何工具执行成功，自动标记当前任务为完成

## 模型路由逻辑

```python
def _pick_config(messages, model):
    # 1. 检查是否明确指定 GPT-5.5
    if model == "gpt-5.5" and gpt55_config.enabled:
        return gpt55_config
    
    # 2. 检查是否包含图片（需要视觉模型）
    if vision_config.enabled and has_images(messages):
        return vision_config
    
    # 3. 默认使用 MiniMax-M2
    return default_config
```

## 前端交互逻辑

```javascript
// 用户选择 "MiniMax-M2 (thinking)"
handleOptionChange("minimax-m2-thinking") {
    onModelChange("minimax-m2")
    if (!thinkingMode) onThinkingToggle()  // 开启 thinking
}

// 用户选择 "MiniMax-M2"
handleOptionChange("minimax-m2") {
    onModelChange("minimax-m2")
    if (thinkingMode) onThinkingToggle()  // 关闭 thinking
}

// 用户选择 "GPT-5.5"
handleOptionChange("gpt-5.5") {
    onModelChange("gpt-5.5")
    if (thinkingMode) onThinkingToggle()  // 关闭 thinking（GPT-5.5 不支持）
}
```

## 测试

创建了测试脚本 `scripts/test_gpt55_config.py`，用于验证：
1. GPT-5.5 配置是否正确加载
2. GPT-5.5 API 连接是否正常
3. 模型路由逻辑是否正确
   - 明确指定 gpt-5.5 → GPT-5.5
   - 默认 → MiniMax-M2
   - 包含图片 → 视觉模型

运行测试：
```bash
python scripts/test_gpt55_config.py
```

## 使用方式

### 前端
1. 打开应用
2. 在顶部选择模型下拉框
3. 选择以下之一：
   - **MiniMax-M2 (thinking)**: 使用 MiniMax-M2，显示思考过程
   - **MiniMax-M2**: 使用 MiniMax-M2，不显示思考过程
   - **GPT-5.5**: 使用 GPT-5.5 模型

### 后端
模型会根据以下规则自动路由：
- 用户选择 GPT-5.5 → 使用 AceData API
- 消息包含图片 → 使用视觉模型（端口 10009）
- 其他情况 → 使用用户选择的模型（MiniMax-M2）

## 注意事项

1. **GPT-5.5 不支持工具调用**: 当使用 GPT-5.5 时，不会发送工具参数
2. **视觉模型优先级**: 即使选择了 GPT-5.5，如果消息包含图片，仍会路由到视觉模型
3. **Thinking 模式**: GPT-5.5 不支持 thinking 模式，选择 GPT-5.5 时会自动关闭
4. **API Key 安全**: 生产环境中应该通过环境变量配置，不要硬编码在代码中

## 后续优化建议

1. **前端状态持久化**: 保存用户的模型选择偏好
2. **模型能力检测**: 动态检测模型是否支持工具调用、thinking 等功能
3. **错误处理**: 添加更详细的错误提示和降级策略
4. **性能监控**: 记录不同模型的响应时间和成功率
5. **成本追踪**: 记录不同模型的使用量和成本
