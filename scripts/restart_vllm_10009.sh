#!/bin/bash
# 重启 vllm 服务，端口改为 10009

echo "正在启动 vllm 服务（端口 10009）..."

# 使用与原服务完全相同的命令，只改端口
nohup /mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env/.venv/bin/python \
  /mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env/.venv/bin/vllm serve \
  /mnt1/mnt2/data3/nlp/ws/model/Qwen3.5-35B-A3B \
  --host 0.0.0.0 \
  --port 10009 \
  --served-model-name qwen35-35b-a3b-judge \
  --tensor-parallel-size 2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.75 \
  --trust-remote-code \
  --reasoning-parser qwen3 \
  > /tmp/vllm_10009_restart.log 2>&1 &

PID=$!
echo "✓ 服务已启动"
echo "PID: $PID"
echo "日志: /tmp/vllm_10009_restart.log"
echo ""
echo "等待服务初始化（约60-90秒）..."

sleep 60

if ps -p $PID > /dev/null; then
    echo "✓ 服务运行正常"
    echo ""
    echo "检查服务状态:"
    echo "  ps aux | grep $PID"
    echo ""
    echo "查看日志:"
    echo "  tail -f /tmp/vllm_10009_restart.log"
    echo ""
    echo "测试连接:"
    echo "  curl http://localhost:10009/v1/models"
else
    echo "✗ 服务已停止"
    echo "查看错误日志:"
    tail -100 /tmp/vllm_10009_restart.log
fi
