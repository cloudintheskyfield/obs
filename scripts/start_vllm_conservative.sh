#!/bin/bash
# 使用更保守的配置启动 vllm 服务

echo "正在启动 vllm 服务（端口 10009，保守配置）..."

# 使用更低的GPU内存利用率和更小的模型长度
nohup /mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env/.venv/bin/vllm serve \
  /mnt1/mnt2/data3/nlp/ws/model/Qwen3.5-35B-A3B \
  --host 0.0.0.0 \
  --port 10009 \
  --served-model-name qwen35-35b-a3b-judge \
  --tensor-parallel-size 2 \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.6 \
  --trust-remote-code \
  --reasoning-parser qwen3 \
  > /tmp/vllm_10009_conservative.log 2>&1 &

PID=$!
echo "服务已启动，PID: $PID"
echo "日志文件: /tmp/vllm_10009_conservative.log"

sleep 10

if ps -p $PID > /dev/null; then
   echo "✓ 服务进程运行中"
   echo "等待初始化..."
   sleep 30
   
   # 检查日志中是否有成功信息
   if grep -q "Uvicorn running" /tmp/vllm_10009_conservative.log; then
       echo "✓ 服务启动成功！"
   elif grep -q "Application startup complete" /tmp/vllm_10009_conservative.log; then
       echo "✓ 服务启动成功！"
   else
       echo "⚠ 服务仍在初始化中..."
       echo "最后20行日志:"
       tail -20 /tmp/vllm_10009_conservative.log
   fi
else
   echo "✗ 服务启动失败"
   echo "错误日志:"
   tail -50 /tmp/vllm_10009_conservative.log
fi
