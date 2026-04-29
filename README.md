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

启动成功后，默认访问地址为：

- 前端：`http://localhost:5173`
- 后端健康检查：`http://127.0.0.1:8000/api/health`

## 迁移说明

- 运行脚本已改为优先基于脚本所在目录解析项目路径，不再依赖固定的 `D:\bishe` 或 `/mnt/d/bishe`。
- 虚拟环境、前端依赖、采集输出和运行时数据库都不需要随仓库一起迁移。
- 若需 `.onion` 采集，还需要单独准备 Tor/代理环境，详见 [darkweb_collector/README.md](/D:/bishe/darkweb_collector/README.md)。
