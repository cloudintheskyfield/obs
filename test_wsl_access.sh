#!/bin/bash
# WSL访问测试脚本

echo "=== Omni Agent API访问测试 ==="

# 尝试不同的主机地址
HOSTS=("localhost" "127.0.0.1" "$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}' | head -1)")

PORT=8003

for HOST in "${HOSTS[@]}"; do
    echo "尝试连接: $HOST:$PORT"
    
    if curl -s --connect-timeout 3 "http://$HOST:$PORT/health" > /dev/null; then
        echo "✅ 成功连接到 $HOST:$PORT"
        echo "健康检查:"
        curl -s "http://$HOST:$PORT/health"
        echo
        echo "可用技能:"
        curl -s "http://$HOST:$PORT/skills" | jq '.skills[].name' 2>/dev/null || curl -s "http://$HOST:$PORT/skills"
        echo
        echo "🎉 使用以下地址访问API: http://$HOST:$PORT"
        break
    else
        echo "❌ 无法连接到 $HOST:$PORT"
    fi
done