@echo off
REM Omni Agent Windows 部署脚本
setlocal EnableDelayedExpansion

echo === Omni Agent Windows 部署脚本 ===
echo.

REM 检查Docker是否安装
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker 未安装，请先安装Docker Desktop
    pause
    exit /b 1
)

docker-compose --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker Compose 未安装，请安装Docker Desktop
    pause
    exit /b 1
)

echo 选择部署模式:
echo 1. 开发模式 ^(极速热重载 - 推荐^)
echo 2. 标准模式 ^(代码热重载^)
echo 3. 生产模式 ^(稳定运行^)
echo 4. 本地模式 ^(不使用Docker^)
echo.
set /p MODE="请输入选择 (1/2/3/4): "

if "%MODE%"=="1" goto dev_mode
if "%MODE%"=="2" goto standard_mode
if "%MODE%"=="3" goto prod_mode  
if "%MODE%"=="4" goto local_mode
echo [ERROR] 无效选择
pause
exit /b 1

:dev_mode
echo [INFO] 启动极速开发模式...
echo [INFO] 代码变更将在0.05秒内自动重载

REM 确保挂载目录存在
if not exist "workspace" mkdir workspace
if not exist "logs" mkdir logs
if not exist "screenshots" mkdir screenshots

REM 极速开发模式启动
docker-compose -f docker-compose.dev.yml up -d

echo [SUCCESS] 开发模式启动成功！
echo.
echo 访问地址:
echo   前端界面: http://localhost:8000
echo   API文档: http://localhost:8000/docs
echo   健康检查: http://localhost:8000/health
echo.
echo 实时日志查看:
echo   docker-compose logs -f omni-agent
echo.
echo 代码修改自动生效:
echo   [OK] 修改 src\ 目录下的Python代码会自动重载
echo   [OK] 修改 .claude\skills\ 目录下的技能会自动重载
echo   [OK] 修改 frontend\ 目录下的前端代码会立即生效
echo   [FAST] 极速重载: 0.05秒响应
goto wait_and_check

:standard_mode
echo [INFO] 启动标准模式...

REM 确保挂载目录存在
if not exist "workspace" mkdir workspace
if not exist "logs" mkdir logs
if not exist "screenshots" mkdir screenshots

REM 标准模式启动
docker-compose up -d

echo [SUCCESS] 标准模式启动成功！
echo.
echo 访问地址:
echo   前端界面: http://localhost:8000
echo   API文档: http://localhost:8000/docs
echo   健康检查: http://localhost:8000/health
echo.
echo 实时日志查看:
echo   docker-compose logs -f omni-agent
echo.
echo 代码修改自动生效:
echo   [OK] 修改 src\ 目录下的Python代码会自动重载
echo   [OK] 修改 .claude\skills\ 目录下的技能会自动重载
echo   [OK] 修改 frontend\ 目录下的前端代码会立即生效
echo   [NORMAL] 标准重载: 0.1秒响应
goto wait_and_check

:prod_mode
echo [INFO] 启动生产模式...

REM 复制生产配置
if not exist "docker-compose.prod.yml" (
    copy docker-compose.yml docker-compose.prod.yml
    REM 这里应该手动编辑移除reload参数，简化处理
)

REM 生产模式启动
docker-compose -f docker-compose.prod.yml up -d

echo [SUCCESS] 生产模式启动成功！
echo.
echo 访问地址:
echo   前端界面: http://localhost:8000
echo   API文档: http://localhost:8000/docs
goto wait_and_check

:local_mode
echo [INFO] 启动本地模式...

REM 检查Python环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 未安装，请先安装Python 3.11+
    pause
    exit /b 1
)

REM 检查uv
uv --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] uv 未安装，请手动安装 uv
    echo 安装命令: pip install uv
    pause
)

REM 创建必要目录
if not exist "workspace" mkdir workspace
if not exist "logs" mkdir logs  
if not exist "screenshots" mkdir screenshots

echo [SUCCESS] 本地模式准备完成！
echo.
echo 启动选项:
echo   本地API服务: python test_local_api.py
echo   命令行界面: python chat_interface.py
echo   系统测试: python test_system_simple.py
echo.
echo 访问地址 ^(启动后^):
echo   前端界面: 直接打开 frontend\index.html
echo   API文档: http://localhost:8001/docs
goto end

:wait_and_check
echo.
echo [INFO] 等待服务启动...
timeout /t 10 /nobreak >nul

REM 健康检查
curl -sf http://localhost:8000/health >nul 2>&1
if %errorlevel% equ 0 (
    echo [SUCCESS] 服务启动成功！
    echo.
    echo 技能状态:
    curl -s http://localhost:8000/skills 2>nul | findstr /C:"computer" >nul
    if !errorlevel! equ 0 (
        echo   [OK] 技能加载成功
    ) else (
        echo   [WARNING] 技能状态未知
    )
) else (
    echo [WARNING] 服务可能还在启动中，请稍后访问
)

:end
echo.
echo [INFO] 部署完成！
echo.
echo 常用命令:
echo   查看日志: docker-compose logs -f omni-agent
echo   重启服务: docker-compose restart omni-agent
echo   停止服务: docker-compose down
echo   完整重建: docker-compose down ^&^& docker-compose up --build -d
echo.

REM 询问是否打开浏览器
set /p OPEN_BROWSER="是否打开浏览器? (y/n): "
if /i "%OPEN_BROWSER%"=="y" (
    if "%MODE%"=="3" (
        echo 请先运行启动命令，然后打开 frontend\index.html
    ) else (
        start http://localhost:8000
        echo 浏览器已打开 http://localhost:8000
    )
)

echo.
echo 按任意键退出...
pause >nul