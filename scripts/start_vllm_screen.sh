#!/bin/bash
# 使用 screen 启动 vllm 服务

SESSION_NAME="vllm_10009"

# 检查 screen 会话是否已存在
if screen -list | grep -q "$SESSION_NAME"; then
    echo "Screen 会话 $SESSION_NAME 已存在，先删除..."
    screen -S "$SESSION_NAME" -X quit
    sleep 2
fi

# 创建新的 screen 会话并启动服务
echo "创建 screen 会话: $SESSION_NAME"
screen -dmS "$SESSION_NAME" bash -c "
cd /mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env && \
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
"

sleep 3

# 检查 screen 会话
if screen -list | grep -q "$SESSION_NAME"; then
    echo "✓ Screen 会话已创建"
    echo "查看会话: screen -r $SESSION_NAME"
    echo "分离会话: Ctrl+A, D"
    echo "查看日志: screen -S $SESSION_NAME -X hardcopy /tmp/vllm_screen.log && cat /tmp/vllm_screen.log"
else
    echo "✗ Screen 会话创建失败"
fi
