#!/bin/bash
# 使用 tmux 启动 vllm 服务

SESSION="vllm_10009"

# 检查并删除已存在的会话
tmux has-session -t $SESSION 2>/dev/null
if [ $? -eq 0 ]; then
    echo "删除已存在的 tmux 会话: $SESSION"
    tmux kill-session -t $SESSION
    sleep 2
fi

# 创建新的 tmux 会话并启动服务
echo "创建 tmux 会话: $SESSION"
tmux new-session -d -s $SESSION

# 在 tmux 会话中执行命令
tmux send-keys -t $SESSION "cd /mnt1/mnt2/data3/nlp/ws/qwen35_vllm_env" C-m
sleep 1

tmux send-keys -t $SESSION "./.venv/bin/python ./.venv/bin/vllm serve /mnt1/mnt2/data3/nlp/ws/model/Qwen3.5-35B-A3B --host 0.0.0.0 --port 10009 --served-model-name qwen35-35b-a3b-judge --tensor-parallel-size 2 --max-model-len 8192 --gpu-memory-utilization 0.75 --trust-remote-code --reasoning-parser qwen3" C-m

echo "✓ tmux 会话已创建"
echo ""
echo "查看会话: tmux attach -t $SESSION"
echo "分离会话: Ctrl+B, 然后按 D"
echo "查看所有会话: tmux ls"
echo ""
echo "等待服务启动（约90秒）..."

sleep 90

# 检查服务
if tmux has-session -t $SESSION 2>/dev/null; then
    echo "✓ tmux 会话仍在运行"
    
    # 检查进程
    PID=$(ps aux | grep "vllm serve" | grep "10009" | grep -v grep | awk '{print $2}' | head -1)
    if [ -n "$PID" ]; then
        echo "✓ vllm 服务运行中，PID: $PID"
        echo ""
        echo "测试连接:"
        echo "  curl http://localhost:10009/v1/models"
    else
        echo "⚠ 未找到 vllm 进程"
        echo "查看 tmux 会话: tmux attach -t $SESSION"
    fi
else
    echo "✗ tmux 会话已退出"
fi
