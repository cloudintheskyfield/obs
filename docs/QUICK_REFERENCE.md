# 快速参考 - 多模态配置

## 🚀 快速开始

### 1. 检查配置
```bash
cat .env | grep VISION
```

应该看到：
```bash
VISION_VLLM_ENABLED=true
VISION_VLLM_BASE_URL=http://223.109.239.14:10009/v1/chat/completions
VISION_VLLM_API_KEY=dummy_key
VISION_VLLM_MODEL=Qwen/Qwen2.5-VL-72B-Instruct
```

### 2. 测试连接
```bash
python scripts/test_multimodal_config.py
```

### 3. 查看日志
```bash
tail -f logs/omni_agent.log | grep -i "routing\|vision"
```

## 📊 模型路由表

| 请求类型 | 使用模型 | 端口/服务 |
|---------|---------|----------|
| 纯文本对话 | MiniMax-M2 | MiniMax API |
| 代码生成 | MiniMax-M2 | MiniMax API |
| 图片分析 | Qwen2.5-VL-72B | 10009 |
| 网页截图 | Qwen2.5-VL-72B | 10009 |
| 多模态对话 | Qwen2.5-VL-72B | 10009 |

## 🔧 常用命令

### 服务器连接
```bash
ssh maintain@223.109.239.14 -i .ssh/A100/id_rsa -p 32200
```

### 检查服务状态
```bash
# 本地测试连接
curl http://223.109.239.14:10009/v1/models

# 服务器上查看进程
ps aux | grep vllm | grep 10009
```

### 重启服务（在服务器上）
```bash
# 查找进程
ps aux | grep vllm

# 停止服务
kill <PID>

# 启动服务
/mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env/.venv/bin/vllm serve \
  /mnt1/mnt2/data3/nlp/ws/model/Qwen3.5-35B-A3B \
  --host 0.0.0.0 --port 10009 \
  --served-model-name qwen35-35b-a3b-judge \
  --tensor-parallel-size 2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.75 \
  --trust-remote-code \
  --reasoning-parser qwen3
```

## 🐛 故障排查

### 问题1: 视觉模型无响应
```bash
# 1. 检查服务是否运行
curl http://223.109.239.14:10009/health

# 2. 检查环境变量
echo $VISION_VLLM_ENABLED
echo $VISION_VLLM_BASE_URL

# 3. 查看详细日志
tail -100 logs/omni_agent.log
```

### 问题2: 路由未生效
```bash
# 1. 确认配置已加载
python -c "from omni_agent.config.config import load_config; c=load_config(); print(f'Enabled: {c.vision_vllm.enabled}, URL: {c.vision_vllm.base_url}')"

# 2. 运行路由测试
python scripts/test_multimodal_config.py
```

### 问题3: 连接超时
```bash
# 1. 测试网络连接
ping 223.109.239.14

# 2. 测试端口
nc -zv 223.109.239.14 10009

# 3. 增加超时时间（在 .env 中）
# VISION_VLLM_TIMEOUT=120
```

## 📝 配置文件位置

| 文件 | 路径 | 说明 |
|-----|------|------|
| 环境变量 | `.env` | 运行时配置 |
| 配置类 | `src/omni_agent/config/config.py` | 默认配置 |
| 客户端 | `src/omni_agent/core/vllm_client.py` | 路由逻辑 |
| 测试脚本 | `scripts/test_multimodal_config.py` | 配置测试 |

## 🔍 日志关键字

搜索这些关键字来调试问题：

```bash
# 路由信息
grep "Routing to vision model" logs/omni_agent.log

# 错误信息
grep -i "error\|failed" logs/omni_agent.log | grep -i vision

# 请求信息
grep "VLLM" logs/omni_agent.log | tail -20
```

## 💡 最佳实践

1. **启用视觉模型前先测试连接**
   ```bash
   curl http://223.109.239.14:10009/v1/models
   ```

2. **监控日志确认路由正确**
   ```bash
   tail -f logs/omni_agent.log | grep "Routing"
   ```

3. **定期检查服务状态**
   ```bash
   # 添加到 crontab
   */5 * * * * curl -s http://223.109.239.14:10009/health || echo "Vision model down"
   ```

4. **使用环境变量而非硬编码**
   - ✓ 使用 `.env` 文件
   - ✗ 直接修改代码

## 📞 支持

- **文档**: `docs/MULTIMODAL_CONFIG.md`
- **更新日志**: `docs/CHANGELOG_MULTIMODAL.md`
- **测试脚本**: `scripts/test_multimodal_config.py`
- **服务器**: maintain@223.109.239.14

## 🎯 快速检查清单

启动项目前检查：

- [ ] `.env` 文件存在且配置正确
- [ ] 视觉模型服务运行在端口 10009
- [ ] 网络连接正常
- [ ] 测试脚本通过

```bash
# 一键检查
python scripts/test_multimodal_config.py && echo "✓ 配置正确" || echo "✗ 配置有误"
```
