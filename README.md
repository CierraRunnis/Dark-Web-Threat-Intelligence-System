# Dark Web Threat Intelligence System

暗网威胁情报系统，用于采集、标准化、检索和分析公开暗网线索、论坛内容、泄露信息与网络安全风险数据。系统包含后端采集调度服务、前端分析工作台、Tor 网桥控制能力，以及面向 Windows / WSL / Codespaces 的启动脚本。

仓库包含两个主要子项目：

- `darkweb_collector`：后端采集、标准化、API、调度、Tor 网桥控制与运行时脚本。
- `threat-intelligence-dashboard`：前端可视化工作台。

## 快速启动

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
$env:PYTHONPATH = "$PWD\src"
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

### WSL / Linux

在 WSL、Debian 或 Ubuntu 环境中运行整套服务时，推荐使用：

```bash
bash darkweb_collector/scripts/start_all_services_wsl.sh start
```

脚本会自动完成：

- 检查并补齐 `tmux`、`python3`、`python3-venv`、`python3-pip`、`npm`、`redis-server`、`redis-cli`、`curl`。
- 安装 Tor 网桥运行组件 `tor`、`snowflake-client`、`obfs4proxy`。
- 创建后端虚拟环境并安装 `requirements.txt`。
- 安装 Playwright Chromium 运行时。
- 检查并安装前端依赖。
- 准备运行时数据库和输出目录。
- 拉起 Redis、后端 API、前端、采集 worker、scheduler 和漏洞同步任务。

常用命令：

```bash
bash darkweb_collector/scripts/start_all_services_wsl.sh start
bash darkweb_collector/scripts/start_all_services_wsl.sh status
bash darkweb_collector/scripts/start_all_services_wsl.sh attach
bash darkweb_collector/scripts/start_all_services_wsl.sh stop
```

### Windows

Windows PowerShell 环境可以使用原生启动脚本。首次运行会自动补齐 Python、Node.js、Redis 兼容服务、后端依赖、Playwright Chromium 和前端依赖，并注册用户命令 `darkweb`。脚本面向普通 Windows 10/11 机器设计，不依赖固定项目路径。

```powershell
.\darkweb.cmd
```

也可以直接调用 PowerShell 脚本：

```powershell
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass -File .\darkweb_collector\scripts\start_all_services_windows.ps1 start
```

首次安装完成后，重新打开 PowerShell 或 CMD，可以直接使用：

```powershell
darkweb
darkweb status
darkweb stop
```

如果只想安装环境和注册命令，不立即启动服务：

```powershell
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass -File .\darkweb_collector\scripts\start_all_services_windows.ps1 install
```

Windows 脚本会优先复用本机已有环境。缺少 Python、Node.js 或 Redis 兼容服务且本机有 `winget` 时，会自动安装 Python 3.12、Node.js LTS 和 Memurai Developer；没有 `winget` 时，需要按错误提示手动安装缺失组件。

Tor 网桥功能会自动检测 Tor Browser / Tor Expert Bundle 中的 `tor.exe` 和 `snowflake-client.exe` / `lyrebird.exe` / `obfs4proxy.exe`，并写入 `DARKWEB_TOR_EXECUTABLE`、`DARKWEB_TOR_TRANSPORT_EXECUTABLE` 供后台 API 使用。Windows 不会静默安装 Tor Browser；如需使用内置网桥，请先安装 Tor Browser，或在页面 / 环境变量中填写 Tor 可执行文件路径。

脚本会写入用户环境变量 `DARKWEB_HOME`、`DARKWEB_PROJECT_ROOT`、`DARKWEB_COLLECTOR_ROOT`、`DARKWEB_DASHBOARD_ROOT`、`DARKWEB_COLLECTOR_DB_PATH`、`DARKWEB_COLLECTOR_SITES_FILE`、`DARKWEB_COLLECTOR_OUTPUT_ROOT`、`REDIS_URL`，并把 `%LOCALAPPDATA%\DarkWebThreatIntel\bin` 加入用户 `Path`。

Windows 脚本的 PID 文件和日志位于：

- `darkweb_collector/.runtime/windows/services.json`
- `darkweb_collector/.runtime/windows/logs/`

Windows 默认运行数据位于：

- `%LOCALAPPDATA%\DarkWebThreatIntel\collector.db`
- `darkweb_collector/output/`

## Tor 网桥验证

系统提供内置 Tor 网桥控制功能，可以在前端页面配置并启动 Snowflake / obfs4 等网桥模式。后端会生成独立 `torrc`、启动本地 Tor 进程，并把可用 SOCKS 端点暴露给采集逻辑。

已验证的运行方式：

- Codespaces / Linux：通过 `tor` + `snowflake-client` 启动 Snowflake 网桥，`check.torproject.org` 返回 `IsTor: true`。
- Windows self-hosted GitHub Actions runner：通过 Tor Browser 自带 `tor.exe` + `lyrebird.exe` 启动网桥，`check.torproject.org` 返回 `IsTor: true`。

## GitHub Actions

仓库包含两个 Windows 相关 workflow：

- `Windows startup smoke`：运行在 GitHub 托管的 `windows-latest`，验证 Windows 启动脚本语法、Tor Browser 路径探测、环境变量写入和后端 Tor 网桥单测。
- `Windows Tor bridge live`：运行在带 `tor-bridge` 标签的 self-hosted Windows runner，真实启动 Tor 网桥并验证 SOCKS 访问 `https://check.torproject.org/api/ip` 返回 `IsTor: true`。

self-hosted runner 需要满足：

- 标签包含 `self-hosted`、`Windows`、`tor-bridge`。
- 当前 runner 用户可访问 Tor Browser 或 Tor Expert Bundle。
- 已安装或可被脚本检测到 `tor.exe` 和 `lyrebird.exe` / `snowflake-client.exe`。

## 访问地址

启动成功后，默认访问地址为：

- 前端：`http://localhost:5173`
- 后端健康检查：`http://127.0.0.1:8000/api/health`

## 发布注意事项

发布源码包时不要包含机器本地产物：

- `darkweb_collector/venv/`
- `threat-intelligence-dashboard/node_modules/`
- `darkweb_collector/.runtime/`
- `darkweb_collector/data/`
- `darkweb_collector/output/`

这些目录已在 `.gitignore` 中排除，启动脚本会在目标机器上重新创建。
