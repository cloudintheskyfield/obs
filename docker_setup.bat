@echo off
REM Docker镜像加速配置脚本

echo === Docker镜像加速配置 ===
echo.

REM 检查Docker是否运行
docker version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker未运行，请先启动Docker Desktop
    pause
    exit /b 1
)

echo [INFO] 当前Docker配置:
docker system info | findstr /C:"Registry Mirrors"

echo.
echo [INFO] 建议配置Docker镜像加速器:
echo 1. 打开Docker Desktop
echo 2. 进入 Settings ^> Docker Engine
echo 3. 添加以下配置到registry-mirrors:
echo.
echo     "registry-mirrors": [
echo         "https://docker.mirrors.ustc.edu.cn",
echo         "https://hub-mirror.c.163.com",
echo         "https://mirror.baidubce.com"
echo     ]
echo.

set /p CONTINUE="是否继续构建? (y/n): "
if /i not "%CONTINUE%"=="y" (
    echo 操作已取消
    exit /b 0
)

echo [INFO] 开始构建镜像...

REM 先尝试拉取基础镜像
echo [INFO] 尝试拉取Python基础镜像...
docker pull python:3.11-slim

if %errorlevel% equ 0 (
    echo [SUCCESS] 基础镜像拉取成功
    echo [INFO] 开始构建应用镜像...
    docker-compose build
) else (
    echo [ERROR] 基础镜像拉取失败，请配置镜像加速器
    echo.
    echo 解决方案:
    echo 1. 配置Docker镜像加速器 ^(如上所示^)
    echo 2. 或者检查网络连接
    echo 3. 或者直接使用Docker: docker-compose up -d
    pause
    exit /b 1
)

echo.
echo [INFO] 构建完成！
pause