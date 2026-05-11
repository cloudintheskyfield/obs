# 多模态模型配置说明

## 概述

本项目支持多模型路由架构，可以根据请求类型自动选择合适的模型：

- **文本模型**：用于普通对话和文本处理（默认使用 MiniMax-M2）
- **视觉模型**：用于图片分析、网页截图理解等多模态任务（使用 Qwen2.5-VL-72B）

## 配置方式

### 1. 环境变量配置（推荐）

在 `.env` 文件中配置：

```bash
# 主模型配置（文本任务）
VLLM_BASE_URL=https://api.minimaxi.com/v1/chat/completions
VLLM_API_KEY=your_api_key_here
VLLM_MODEL=MiniMax-M2

# 视觉多模态模型配置
VISION_VLLM_ENABLED=true
VISION_VLLM_BASE_URL=http://223.109.239.14:10009/v1/chat/completions
VISION_VLLM_API_KEY=dummy_key
VISION_VLLM_MODEL=Qwen/Qwen2.5-VL-72B-Instruct
```

### 2. 代码配置

在 `src/config/config.py` 中：

```python
class VLLMConfig(BaseModel):
    """主模型配置"""
    base_url: str = "https://api.minimaxi.com/v1/chat/completions"
    api_key: str = "dummy_key"
    model: str = "MiniMax-M2"
    timeout: int = 35
    max_retries: int = 2

class VisionVLLMConfig(BaseModel):
    """视觉模型配置"""
    enabled: bool = False
    base_url: str = "http://223.109.239.14:10009/v1/chat/completions"
    api_key: str = "dummy_key"
    model: str = "Qwen/Qwen2.5-VL-72B-Instruct"
    timeout: int = 60
    max_retries: int = 2
```

## 自动路由机制

系统会自动检测请求中是否包含图片：

1. **包含图片** → 自动路由到视觉模型（端口 10009）
2. **纯文本** → 使用主模型（MiniMax API）

路由逻辑在 `src/core/vllm_client.py` 中实现：

```python
def _pick_config(self, messages: List[Dict[str, Any]]) -> VLLMConfig:
    """如果消息含图片且视觉路由已启用，返回视觉配置；否则返回主配置。"""
    if (
        self.vision_config is not None
        and self.vision_config.enabled
        and self._has_images(messages)
    ):
        logger.debug(f"Routing to vision model: {self.vision_config.model}")
        return self.vision_config
    return self.config
```

## 服务器信息

### 视觉模型服务器

- **地址**: `223.109.239.14`
- **端口**: `10009`（已从 8001 更改）
- **模型**: Qwen2.5-VL-72B-Instruct
- **连接方式**: `ssh maintain@223.109.239.14 -i .ssh/A100/id_rsa -p 32200`

### 服务进程信息

原始进程（端口 8001）：
```bash
ps -ww -fp 2623064
# /mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env/.venv/bin/python 
# /mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env/.venv/bin/vllm serve 
# /mnt1/mnt2/data3/nlp/ws/model/Qwen3.5-35B-A3B 
# --host 0.0.0.0 --port 8001 
# --served-model-name qwen35-35b-a3b-judge 
# --tensor-parallel-size 2 --max-model-len 8192 
# --gpu-memory-utilization 0.75 --trust-remote-code --reasoning-parser qwen3
```

**注意**: 需要在服务器上将此服务的端口改为 10009，或启动新的服务实例。

## 使用场景

### 自动使用视觉模型的场景

1. **网页浏览**: 分析网页截图
2. **图片理解**: 处理用户上传的图片
3. **多模态对话**: 包含图片的对话请求

### 使用主模型的场景

1. **纯文本对话**
2. **代码生成**
3. **文本分析**
4. **任务规划**

## 测试配置

使用以下命令测试连接：

```bash
# 测试主模型
PYTHONPATH=src python -m main test --vllm-url https://api.minimaxi.com/v1/chat/completions

# 测试视觉模型
PYTHONPATH=src python -m main test --vllm-url http://223.109.239.14:10009/v1/chat/completions
```

## 故障排查

### 视觉模型无法连接

1. 检查服务器是否可达：
   ```bash
   curl http://223.109.239.14:10009/v1/models
   ```

2. 检查环境变量是否正确设置：
   ```bash
   echo $VISION_VLLM_ENABLED
   echo $VISION_VLLM_BASE_URL
   ```

3. 查看日志：
   ```bash
   tail -f logs/log | grep -i vision
   ```

### 路由未生效

1. 确认 `VISION_VLLM_ENABLED=true`
2. 检查请求中是否包含图片内容
3. 查看调试日志中的路由信息

## 更新历史

- **2024-05-08**: 将视觉模型端口从 8001 更改为 10009
- **2024-05-08**: 添加环境变量配置支持
- **2024-05-08**: 完善配置文档
