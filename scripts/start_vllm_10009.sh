#!/bin/bash
# 在服务器上启动 vllm 服务（端口 10009）

echo "正在启动 vllm 服务（端口 10009）..."

# 启动服务
nohup /mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env/.venv/bin/vllm serve \
  /mnt1/mnt2/data3/nlp/ws/model/Qwen3.5-35B-A3B \
  --host 0.0.0.0 \
  --port 10009 \
  --served-model-name qwen35-35b-a3b-judge \
  --tensor-parallel-size 2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.75 \
  --trust-remote-code \
  --reasoning-parser qwen3 \
  > /tmp/vllm_10009.log 2>&1 &

# 获取进程 ID
PID=$!
echo "服务已启动，PID: $PID"
echo "日志文件: /tmp/vllm_10009.log"

# 等待几秒
sleep 5

# 检查进程是否还在运行
if ps -p $PID > /dev/null; then
   echo "✓ 服务启动成功"
   echo "查看日志: tail -f /tmp/vllm_10009.log"
else
   echo "✗ 服务启动失败，请查看日志"
   tail -20 /tmp/vllm_10009.log
fi
