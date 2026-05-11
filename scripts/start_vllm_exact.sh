#!/bin/bash
# 使用与原服务完全相同的配置，只改变端口

echo "正在启动 vllm 服务（端口 10009）..."
echo "使用 tensor-parallel-size 2"

# 设置环境变量以避免通信问题
export NCCL_DEBUG=INFO
export NCCL_IB_DISABLE=0
export NCCL_NET_GDR_LEVEL=2

# 使用与原服务相同的配置
cd /mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env

nohup ./.venv/bin/vllm serve \
  /mnt1/mnt2/data3/nlp/ws/model/Qwen3.5-35B-A3B \
  --host 0.0.0.0 \
  --port 10009 \
  --served-model-name qwen35-35b-a3b-judge \
  --tensor-parallel-size 2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.75 \
  --trust-remote-code \
  --reasoning-parser qwen3 \
  > /tmp/vllm_10009_exact.log 2>&1 &

PID=$!
echo "服务已启动，PID: $PID"
echo "日志文件: /tmp/vllm_10009_exact.log"

# 等待初始化
echo "等待服务初始化（这可能需要1-2分钟）..."
sleep 20

if ps -p $PID > /dev/null; then
   echo "✓ 服务进程运行中"
   
   # 继续等待
   sleep 40
   
   if ps -p $PID > /dev/null; then
       echo "✓ 服务仍在运行"
       
       # 检查日志
       if grep -qi "uvicorn running\|application startup complete" /tmp/vllm_10009_exact.log; then
           echo "✓ 服务启动成功！"
       elif grep -qi "error\|failed" /tmp/vllm_10009_exact.log; then
           echo "⚠ 发现错误，查看日志:"
           tail -50 /tmp/vllm_10009_exact.log | grep -i "error\|failed" | tail -10
       else
           echo "⚠ 服务仍在初始化..."
           echo "最后20行日志:"
           tail -20 /tmp/vllm_10009_exact.log
       fi
   else
       echo "✗ 服务已停止"
       echo "错误日志:"
       tail -50 /tmp/vllm_10009_exact.log
   fi
else
   echo "✗ 服务启动失败"
   echo "错误日志:"
   tail -50 /tmp/vllm_10009_exact.log
fi

echo ""
echo "查看完整日志: tail -f /tmp/vllm_10009_exact.log"
echo "查看进程: ps aux | grep $PID"
