FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    unzip \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装Docker CLI（用于terminal skills）
RUN curl -fsSL https://get.docker.com -o get-docker.sh && \
    sh get-docker.sh && \
    rm get-docker.sh

# 安装Chrome浏览器依赖
RUN apt-get update && apt-get install -y \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# 安装uv包管理器
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

# 复制项目配置文件
COPY pyproject.toml uv.lock* ./

# 安装Python依赖
RUN uv sync --frozen

# 安装Playwright和浏览器
RUN uv run playwright install chromium
RUN uv run playwright install-deps

# 复制源代码
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/

# 创建必要目录
RUN mkdir -p /app/workspace /app/logs /app/screenshots

# 设置权限
RUN chmod +x /app/scripts/*.py

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 暴露端口
EXPOSE 8000 8080

# 启动命令
CMD ["uv", "run", "python", "-m", "omni_agent.main", "serve"]