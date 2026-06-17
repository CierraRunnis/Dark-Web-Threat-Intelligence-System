# bishe

毕业设计项目：暗网公开信息收集与威胁情报提取。

仓库包含两个主要子项目：

- `darkweb_collector`：后端采集、标准化、API 与调度逻辑
- `threat-intelligence-dashboard`：前端可视化仪表盘

## 克隆后快速启动

### 后端

```bash
cd darkweb_collector
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH="$PWD/src"
python -m uvicorn darkweb_collector.api_app:app --host 127.0.0.1 --port 8000
```

Windows PowerShell：

```powershell
cd darkweb_collector
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\\src"
python -m uvicorn darkweb_collector.api_app:app --host 127.0.0.1 --port 8000
```

### 前端

```bash
cd threat-intelligence-dashboard
npm install
npm run dev
```

默认前端端口为 `5173`，开发代理会转发到 `127.0.0.1:8000`。

## 一键启动脚本

如果你在 WSL 环境中运行整套项目，推荐直接使用一键启动脚本：

```bash
bash darkweb_collector/scripts/start_all_services_wsl.sh start
```

这个脚本会自动完成以下事情：

- 检查 `tmux`、`python3`、`python3-venv`、`python3-pip`、`npm`、`redis-server`、`redis-cli`、`curl` 是否可用
- 在 Debian/Ubuntu/WSL 环境下，缺失时自动通过 `apt-get` 安装这些系统依赖
- 自动创建后端虚拟环境并安装 `requirements.txt`
- 自动安装 Playwright Chromium 运行时
- 自动检查前端依赖，缺失时执行 `npm install`
- 自动准备 WSL 本地运行时数据库；如果没有历史数据库，会自动初始化一个空库
- 一次性拉起 Redis、后端 API、前端、采集 worker、scheduler 和漏洞同步任务

常用命令：

```bash
# 启动整套服务
bash darkweb_collector/scripts/start_all_services_wsl.sh start

# 查看运行状态
bash darkweb_collector/scripts/start_all_services_wsl.sh status

# 进入 tmux 会话查看各服务窗口日志
bash darkweb_collector/scripts/start_all_services_wsl.sh attach

# 停止整套服务
bash darkweb_collector/scripts/start_all_services_wsl.sh stop
```

Windows PowerShell 环境可以使用 Windows 原生启动脚本。首次运行会自动补齐 Python、Node.js、Redis 兼容服务、后端依赖、Playwright Chromium 和前端依赖，并注册用户命令 `darkweb`。脚本面向普通 Windows 10/11 机器设计，不依赖固定项目路径：

```powershell
# 首次安装并启动整套服务
.\darkweb.cmd
```

也可以直接调用 PowerShell 脚本：`%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass -File .\darkweb_collector\scripts\start_all_services_windows.ps1 start`。

首次脚本执行完成后，重新打开一个 PowerShell 或 CMD，就可以直接输入：

```powershell
# 启动整套服务
darkweb

# 查看运行状态
darkweb status

# 停止脚本拉起的服务
darkweb stop
```

如果只想先安装环境和注册命令，不立即启动服务：

```powershell
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass -File .\darkweb_collector\scripts\start_all_services_windows.ps1 install
```

Windows 脚本会优先复用本机已有环境。Python 会依次查找 `python`、常见安装目录和 `py -3` 启动器；Node.js 会查找 PATH 和常见安装目录；Redis 会优先复用已运行的 `127.0.0.1:6379`、本机 Redis/Memurai 服务或可执行文件，也可在 Docker 可用时自动启动 `redis:7-alpine` 容器。缺少 Python、Node.js 或 Redis 兼容服务且本机有 `winget` 时，会自动安装 Python 3.12、Node.js LTS 和 Memurai Developer；没有 `winget` 时，需要按错误提示手动安装缺失组件。

脚本会写入用户环境变量 `DARKWEB_HOME`、`DARKWEB_PROJECT_ROOT`、`DARKWEB_COLLECTOR_ROOT`、`DARKWEB_DASHBOARD_ROOT`、`DARKWEB_COLLECTOR_DB_PATH`、`DARKWEB_COLLECTOR_SITES_FILE`、`DARKWEB_COLLECTOR_OUTPUT_ROOT`、`REDIS_URL`，并把 `%LOCALAPPDATA%\DarkWebThreatIntel\bin` 加入用户 `Path`。

Windows 脚本的 PID 文件和日志位于：

- `darkweb_collector/.runtime/windows/services.json`
- `darkweb_collector/.runtime/windows/logs/`

Windows 默认运行数据位于：

- `%LOCALAPPDATA%\DarkWebThreatIntel\collector.db`
- `darkweb_collector/output/`

发布源码包时不要包含机器本地产物：`darkweb_collector/venv/`、`threat-intelligence-dashboard/node_modules/`、`darkweb_collector/.runtime/`、`darkweb_collector/data/`、`darkweb_collector/output/`。这些目录已在 `.gitignore` 中排除，Windows 启动脚本会在目标机器上重新创建。

启动成功后，默认访问地址为：

- 前端：`http://localhost:5173`
- 后端健康检查：`http://127.0.0.1:8000/api/health`

