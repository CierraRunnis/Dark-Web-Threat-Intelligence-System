# Dark Web Threat Intelligence System

暗网威胁情报系统，用于采集、标准化、检索和分析公开暗网线索、论坛内容、泄露信息与网络安全风险数据。系统包含后端采集调度服务、前端分析工作台、任务队列、运行时数据库和 Tor 网桥控制能力。

## 功能概览

- 暗网与公开风险线索采集：支持站点配置、定时入队、列表页和详情页采集。
- 威胁情报标准化：将采集内容整理为可检索、可筛选、可追踪的数据记录。
- 前端分析工作台：提供数据浏览、任务状态、采集结果和风险线索查看能力。
- 后台任务调度：使用 Redis 和 Celery 处理采集、渲染、详情解析和同步任务。
- Tor 网桥控制：支持在系统内配置并启动 Snowflake / obfs4 等 Tor 网桥模式，为采集代理提供本地 SOCKS 入口。
- 一键在线更新：在版本信息区域直接更新当前 Git 分支，并自动同步依赖和重启服务。
- Windows / WSL 启动脚本：提供一键准备依赖、注册命令、启动服务和查看状态的脚本。

## 区域暗网监测

系统提供独立暗网监测工作台，默认纳管长安不夜城、XSS、BreachForums 和 Telegram 四类来源，并使用西藏、Tibet、Xizang、拉萨、日喀则等区域关键词建立监测范围。

每条命中线索进入监测台账后会生成 30 分钟初验截止时间。初验记录包括来源平台与网址、威胁类型、关联单位或行业、发现时间、截图合规状态、置信度、建议处置方向、研判人员、处置状态和情报编目号。存在原始截图但尚未标记合规时，系统会阻止对外报送。

关闭论坛和 Telegram 的登录状态由独立连接器维护，主系统不保存平台账号。连接器需提供一个受控 HTTP(S) JSON 接口，并通过以下环境变量接入：

```text
DARKWEB_CHANGAN_CONNECTOR_URL
DARKWEB_XSS_CONNECTOR_URL
DARKWEB_BREACHFORUMS_CONNECTOR_URL
DARKWEB_TELEGRAM_CONNECTOR_URL
```

如连接器启用 Bearer Token，可分别配置同名前缀的 `*_CONNECTOR_TOKEN`。接口返回格式：

```json
{
  "findings": [
    {
      "event_id": "source-stable-id",
      "title": "线索标题",
      "source_url": "https://source.example/thread/1",
      "threat_type": "数据售卖",
      "target_name": "关联单位",
      "target_industry": "关联行业",
      "discovered_at": "2026-07-10T10:00:00+00:00",
      "content_excerpt": "合规截取的原始内容摘要",
      "screenshot_url": "/collector-output/source/thread-1.png",
      "confidence_level": "medium"
    }
  ]
}
```

Windows 和 WSL 启动脚本中的调度器会定期轮询连接器、检查 30 分钟 SLA、生成已结束日期的日报，并在月初归档上月月报。默认连接器轮询间隔为 300 秒，可通过 `DARKWEB_CONNECTOR_POLL_INTERVAL_SECONDS` 调整。

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

## 一键更新

登录系统后，侧边栏的版本信息区域提供“一键更新”按钮。点击后系统会：

1. 获取当前分支在 GitHub 上的最新提交。
2. 仅在工作区没有未提交修改且可以 fast-forward 时更新代码。
3. 通过对应的 Windows 或 Linux 启动脚本同步依赖。
4. 重启 API、前端和后台任务服务。

更新完成后需要重新登录。在线更新要求项目通过 Git 克隆部署；源码压缩包、容器只读文件系统或存在本地未提交修改时，系统会停止更新并显示原因。默认更新当前检出的分支，也可以通过 `DARKWEB_UPDATE_BRANCH` 指定分支，通过 `DARKWEB_SELF_UPDATE_ENABLED=0` 禁用在线更新。

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
