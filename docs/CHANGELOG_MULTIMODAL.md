# 多模态配置更新日志

## 2024-05-08 - 视觉模型端口更新

### 变更内容

1. **端口变更**
   - 视觉模型端口从 `8001` 更改为 `10009`
   - 服务器地址保持不变：`223.109.239.14`

2. **配置文件更新**
   - `src/config/config.py`: 更新 `VisionVLLMConfig` 默认端口
   - `.env`: 添加视觉模型环境变量配置
   - `.env.example`: 添加配置示例和说明

3. **新增文档**
   - `docs/MULTIMODAL_CONFIG.md`: 多模态配置完整说明
   - `scripts/test_multimodal_config.py`: 配置测试脚本

### 配置说明

#### 主模型（文本任务）
- **服务**: MiniMax API
- **用途**: 普通对话、代码生成、文本分析
- **配置**:
  ```bash
  VLLM_BASE_URL=https://api.minimaxi.com/v1/chat/completions
  VLLM_MODEL=MiniMax-M2
  ```

#### 视觉模型（多模态任务）
- **服务**: Qwen2.5-VL-72B (自建服务)
- **端口**: 10009 (新)
- **用途**: 图片分析、网页截图理解
- **配置**:
  ```bash
  VISION_VLLM_ENABLED=true
  VISION_VLLM_BASE_URL=http://223.109.239.14:10009/v1/chat/completions
  VISION_VLLM_MODEL=Qwen/Qwen2.5-VL-72B-Instruct
  ```

### 自动路由机制

系统会自动检测请求类型并路由到合适的模型：

```
请求包含图片？
├─ 是 → 视觉模型 (端口 10009)
└─ 否 → 主模型 (MiniMax API)
```

### 服务器操作指南

#### 连接服务器
```bash
ssh maintain@223.109.239.14 -i .ssh/A100/id_rsa -p 32200
```

#### 查看当前服务
```bash
ps -ww -fp 2623064
```

#### 修改服务端口（需要在服务器上执行）

**方案1: 修改现有服务**
```bash
# 停止现有服务
kill 2623064

# 使用新端口启动
/mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env/.venv/bin/vllm serve \
  /mnt1/mnt2/data3/nlp/ws/model/Qwen3.5-35B-A3B \
  --host 0.0.0.0 \
  --port 10009 \
  --served-model-name qwen35-35b-a3b-judge \
  --tensor-parallel-size 2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.75 \
  --trust-remote-code \
  --reasoning-parser qwen3
```

**方案2: 启动新服务（保留旧服务）**
```bash
# 在新端口启动服务
/mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env/.venv/bin/vllm serve \
  /mnt1/mnt2/data3/nlp/ws/model/Qwen3.5-35B-A3B \
  --host 0.0.0.0 \
  --port 10009 \
  --served-model-name qwen35-35b-a3b-judge \
  --tensor-parallel-size 2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.75 \
  --trust-remote-code \
  --reasoning-parser qwen3 &

# 旧服务（端口 8001）可以保留或停止
```

### 测试配置

运行测试脚本验证配置：

```bash
# 运行完整测试
python scripts/test_multimodal_config.py

# 或使用项目内置测试命令
PYTHONPATH=src python -m main test --vllm-url http://223.109.239.14:10009/v1/chat/completions
```

### 影响范围

#### 受影响的组件
- ✓ `VLLMClient`: 自动路由逻辑
- ✓ `WebAgent`: 网页截图分析
- ✓ 所有包含图片的请求

#### 不受影响的组件
- ✓ 纯文本对话
- ✓ 代码生成
- ✓ 文件操作
- ✓ 终端执行

### 回滚方案

如需回滚到旧配置：

1. 修改 `.env`:
   ```bash
   VISION_VLLM_BASE_URL=http://223.109.239.14:8001/v1/chat/completions
   ```

2. 或修改 `src/config/config.py`:
   ```python
   class VisionVLLMConfig(BaseModel):
       base_url: str = "http://223.109.239.14:8001/v1/chat/completions"
   ```

### 验证清单

- [ ] 服务器端口已更改为 10009
- [ ] `.env` 文件已更新
- [ ] 运行测试脚本通过
- [ ] 文本请求正常工作
- [ ] 图片请求正常路由到视觉模型
- [ ] 日志中可以看到正确的路由信息

### 相关文档

- [多模态配置说明](./MULTIMODAL_CONFIG.md)
- [环境变量配置](./.env.example)
- [测试脚本](../scripts/test_multimodal_config.py)

### 联系方式

如有问题，请联系：
- 服务器管理员：maintain@223.109.239.14
- 项目维护者：[您的联系方式]
