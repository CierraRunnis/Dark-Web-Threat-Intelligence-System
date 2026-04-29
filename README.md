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

## 迁移说明

- 运行脚本已改为优先基于脚本所在目录解析项目路径，不再依赖固定的 `D:\bishe` 或 `/mnt/d/bishe`。
- 虚拟环境、前端依赖、采集输出和运行时数据库都不需要随仓库一起迁移。
- 若需 `.onion` 采集，还需要单独准备 Tor/代理环境，详见 [darkweb_collector/README.md](/D:/bishe/darkweb_collector/README.md)。
