# Dark Web Threat Intelligence System

暗网威胁情报系统，用于采集、标准化、检索和分析公开暗网线索、论坛内容、泄露信息与网络安全风险数据。系统包含后端采集调度服务、前端分析工作台、任务队列、运行时数据库和 Tor 网桥控制能力。

## 功能概览

- 暗网与公开风险线索采集：支持站点配置、定时入队、列表页和详情页采集。
- 威胁情报标准化：将采集内容整理为可检索、可筛选、可追踪的数据记录。
- 前端分析工作台：提供数据浏览、任务状态、采集结果和风险线索查看能力。
- 后台任务调度：使用 Redis 和 Celery 处理采集、渲染、详情解析和同步任务。
- Tor 网桥控制：支持在系统内配置并启动 Snowflake / obfs4 等 Tor 网桥模式，为采集代理提供本地 SOCKS 入口。
- Windows / WSL 启动脚本：提供一键准备依赖、注册命令、启动服务和查看状态的脚本。

## 项目结构

```text
.
├── darkweb_collector/              # 后端 API、采集器、任务队列、运行脚本
│   ├── scripts/                    # Windows / WSL 启动脚本和采集辅助脚本
│   ├── src/darkweb_collector/      # 后端应用源码
│   ├── tests/                      # 后端测试
│   └── requirements.txt            # Python 依赖
├── threat-intelligence-dashboard/  # 前端工作台
│   ├── src/                        # 前端源码
│   ├── package.json
│   └── package-lock.json
└── README.md
```

## 环境要求

手动启动时需要：

- Python 3.10+
- Node.js 18+
- Redis 或兼容服务
- npm

使用 Windows / WSL 启动脚本时，脚本会尽量自动检测和补齐缺失依赖。

如需使用内置 Tor 网桥：

- Linux / WSL：需要 `tor`、`snowflake-client`、`obfs4proxy`。
- Windows：需要安装 Tor Browser 或 Tor Expert Bundle，并能检测到 `tor.exe` 和 `lyrebird.exe` / `snowflake-client.exe` / `obfs4proxy.exe`。

## 手动启动

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

## 一键启动

### WSL / Linux

```bash
bash darkweb_collector/scripts/start_all_services_wsl.sh start
```

常用命令：

```bash
bash darkweb_collector/scripts/start_all_services_wsl.sh start
bash darkweb_collector/scripts/start_all_services_wsl.sh status
bash darkweb_collector/scripts/start_all_services_wsl.sh attach
bash darkweb_collector/scripts/start_all_services_wsl.sh stop
```

WSL 脚本会准备后端虚拟环境、前端依赖、Redis、Playwright、运行时数据库和 Tor 网桥运行组件，并拉起 API、前端、worker、scheduler 等服务。

### Windows

首次运行：

```powershell
.\darkweb.cmd
```

也可以直接调用 PowerShell 脚本：

```powershell
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass -File .\darkweb_collector\scripts\start_all_services_windows.ps1 start
```

安装环境但不立即启动服务：

```powershell
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -ExecutionPolicy Bypass -File .\darkweb_collector\scripts\start_all_services_windows.ps1 install
```

安装完成后，重新打开 PowerShell 或 CMD，可以使用：

```powershell
darkweb
darkweb status
darkweb stop
```

Windows 脚本会优先复用本机已有环境。缺少 Python、Node.js 或 Redis 兼容服务且本机有 `winget` 时，会自动安装 Python 3.12、Node.js LTS 和 Memurai Developer；没有 `winget` 时，需要按错误提示手动安装缺失组件。

## Tor 网桥

前端提供 Tor 网桥配置页面。启用后，后端会生成独立 `torrc`，启动本地 Tor 进程，并提供本地 SOCKS 代理给采集逻辑使用。

默认 SOCKS 地址：

```text
socks5h://127.0.0.1:9050
```

Windows 脚本会自动检测 Tor Browser / Tor Expert Bundle 中的 `tor.exe` 和传输插件，并写入：

- `DARKWEB_TOR_EXECUTABLE`
- `DARKWEB_TOR_TRANSPORT_EXECUTABLE`

Windows 不会静默安装 Tor Browser。如需使用内置网桥，请先安装 Tor Browser，或在页面 / 环境变量中填写 Tor 可执行文件路径。

## 运行数据

Windows 默认运行数据位于：

- `%LOCALAPPDATA%\DarkWebThreatIntel\collector.db`
- `darkweb_collector/output/`
- `darkweb_collector/.runtime/windows/`

WSL / Linux 默认运行数据位于：

- `$HOME/.local/share/bishe/collector.db`
- `darkweb_collector/output/`
- `darkweb_collector/.runtime/wsl/`

## 访问地址

启动成功后，默认访问地址为：

- 前端：`http://localhost:5173`
- 后端健康检查：`http://127.0.0.1:8000/api/health`
