---
name: code-sandbox
description: Execute code in isolated Docker containers for safe testing and debugging
---

# Code Sandbox Skill

在隔离的Docker容器中安全执行代码，支持多种编程语言。

## 功能特性

- **安全隔离**: 代码在独立Docker容器中运行
- **多语言支持**: Python, Node.js, Go, Rust, Java
- **资源限制**: 内存、CPU、超时控制
- **文件系统**: 独立的临时文件系统
- **网络隔离**: 可选的网络访问控制

## 使用方法

### Python代码执行

```python
result = await execute_skill("code_sandbox",
    language="python",
    code='''
def hello():
    print("Hello from sandbox!")
    return 42

result = hello()
print(f"Result: {result}")
''',
    timeout=30
)
```

### JavaScript执行

```python
result = await execute_skill("code_sandbox",
    language="javascript",
    code='''
function fibonacci(n) {
    if (n <= 1) return n;
    return fibonacci(n-1) + fibonacci(n-2);
}

console.log("Fib(10):", fibonacci(10));
''',
    timeout=30
)
```

### 带文件输入

```python
result = await execute_skill("code_sandbox",
    language="python",
    code='''
with open("/workspace/input.txt") as f:
    data = f.read()
    
print("Processing:", data)
''',
    files={
        "input.txt": "Hello World"
    },
    timeout=30
)
```

## 参数说明

- `language`: 编程语言 (python/javascript/go/rust/java)
- `code`: 要执行的代码
- `files`: 可选，输入文件字典 {filename: content}
- `timeout`: 超时时间（秒），默认30s
- `memory_limit`: 内存限制，默认256MB
- `cpu_limit`: CPU限制，默认1核

## 安全机制

- 容器运行在非特权模式
- 无网络访问（默认）
- 文件系统只读（除/workspace）
- 自动清理临时容器
- 资源限制防止滥用

## 返回值

```python
{
    "success": True,
    "stdout": "程序标准输出",
    "stderr": "错误输出",
    "exit_code": 0,
    "execution_time": 1.23,
    "output_files": {"result.txt": "..."}
}
```

## 最佳实践

1. 设置合理的超时时间
2. 检查exit_code确认执行成功
3. 处理stderr中的错误信息
4. 使用files参数传递大数据
5. 避免无限循环和递归

## 错误处理

```python
result = await execute_skill("code_sandbox",
    language="python",
    code="print(1/0)"  # 会产生异常
)

if result.exit_code != 0:
    print("执行失败:", result.stderr)
```
