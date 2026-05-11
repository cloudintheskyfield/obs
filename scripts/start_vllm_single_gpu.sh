#!/bin/bash
# 使用单GPU配置启动 vllm 服务（避免分布式通信问题）

echo "正在启动 vllm 服务（端口 10009，单GPU配置）..."

# 不使用 tensor-parallel，使用单GPU
CUDA_VISIBLE_DEVICES=0 nohup /mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env/.venv/bin/vllm serve \
  /mnt1/mnt2/data3/nlp/ws/model/Qwen3.5-35B-A3B \
  --host 0.0.0.0 \
  --port 10009 \
  --served-model-name qwen35-35b-a3b-judge \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.9 \
  --trust-remote-code \
  --reasoning-parser qwen3 \
  > /tmp/vllm_10009_single.log 2>&1 &

PID=$!
echo "服务已启动，PID: $PID"
echo "日志文件: /tmp/vllm_10009_single.log"

sleep 15

if ps -p $PID > /dev/null; then
   echo "✓ 服务进程运行中"
   echo "等待模型加载..."
   sleep 45
   
   # 检查日志
   if grep -qi "uvicorn running\|application startup complete\|listening" /tmp/vllm_10009_single.log; then
       echo "✓ 服务启动成功！"
       echo "测试连接: curl http://localhost:10009/v1/models"
   else
       echo "⚠ 服务仍在初始化中..."
       echo "最后30行日志:"
       tail -30 /tmp/vllm_10009_single.log
   fi
else
   echo "✗ 服务启动失败"
   echo "错误日志:"
   tail -50 /tmp/vllm_10009_single.log
fi
