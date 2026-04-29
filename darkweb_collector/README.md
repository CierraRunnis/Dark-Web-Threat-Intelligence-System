# Darkweb Collector

统一管理暗网公开信息采集和威胁情报提取的爬虫框架。

当前项目已经从“每个站点一个独立脚本”演进为“统一 CLI + 站点适配器 + SQLite + 可选 Celery/Redis 队列”的结构，适合持续增加新站点并复用现有抓取、去重、入库和输出逻辑。

## 当前能力

- 统一站点接入方式：`parser + adapter + sites.yaml`
- 统一运行入口：`scripts/crawl.py`
- 支持单次运行和持续轮询
- 支持 SQLite 结果落库和 `crawl_jobs` 审计
- 支持列表页增量判断和详情页按变化抓取
- 支持浏览器抓取与非浏览器抓取两种模式
- 按目标 URL 主机名自动区分 Tor 路径和普通代理路径

## 当前已接入站点

- `dragonforce`
- `darkforums`
- `chaos`

站点配置在 [sites.yaml](/D:/bishe/darkweb_collector/sites.yaml)。

## 抓取路由规则

当前代理选择规则不是按 `http://` / `https://` 协议判断，而是按目标 URL 的主机名判断：

- 主机名以 `.onion` 结尾：走 Tor
- 主机名不以 `.onion` 结尾：走普通 HTTP/HTTPS 代理；未配置代理时允许直连

因此：

- `http://abc.onion/...` 走 Tor
- `https://abc.onion/...` 也走 Tor
- `https://darkforums.su/...` 走普通代理或直连

`sites.yaml` 中的：

- `seed_fetch_mode`
- `detail_fetch_mode`

只表示抓取方式：

- `tor_http`：非浏览器直取
- `browser`：浏览器渲染

是否走 Tor 由目标 URL 自动决定。

## 运行前提

### 1. Python 环境

推荐先进入虚拟环境：

```bash
cd /path/to/bishe/darkweb_collector
source venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

### 2. Tor 环境

如果要抓取 `.onion` 站点，需要先确保 Windows 侧 Tor Browser 已启动，并且 WSL 可以访问：

```bash
export TOR_SOCKS_HOST=127.0.0.1
export TOR_SOCKS_PORT=9150
```

快速检查：

```bash
curl --socks5-hostname 127.0.0.1:9150 https://check.torproject.org/api/ip
```

### 3. 明网 HTTP/HTTPS 代理

如果要让明网站点走普通代理，可设置：

```bash
export PROXY_HOST=127.0.0.1
export PROXY_PORT=7890
```

如果不设置这两个变量，明网站点会尝试直连。

## 常用运行方式

先进入项目目录：

```bash
cd /path/to/bishe/darkweb_collector
```

### 查看当前站点

```bash
python scripts/crawl.py list-sites
```

### 单次运行一个站点

```bash
python scripts/crawl.py run-site --site dragonforce --once
python scripts/crawl.py run-site --site darkforums --once
python scripts/crawl.py run-site --site chaos --once
```

### 持续运行一个站点

持续轮询，按站点配置的默认间隔运行：

```bash
python scripts/crawl.py run-site --site darkforums --continuous
```

手动指定轮询间隔：

```bash
python scripts/crawl.py run-site --site darkforums --continuous --interval-seconds 120
```

### 查看最近运行记录

```bash
python scripts/crawl.py show-runs --limit 20
```

### 启动 API

```bash
export PYTHONPATH="$PWD/src"
python -m uvicorn darkweb_collector.api_app:app --host 127.0.0.1 --port 8000
```

## 兼容脚本

项目里还保留了一些兼容或辅助脚本：

- [fetch_dragonforce.py](/D:/bishe/darkweb_collector/scripts/fetch_dragonforce.py)
- [fetch_darkforums.py](/D:/bishe/darkweb_collector/scripts/fetch_darkforums.py)
- [fetch_onion_playwright.py](/D:/bishe/darkweb_collector/scripts/fetch_onion_playwright.py)
- [fetch_onion_playwright_windows.py](/D:/bishe/darkweb_collector/scripts/fetch_onion_playwright_windows.py)

其中：

- `fetch_dragonforce.py` 和 `fetch_darkforums.py` 本质上只是对统一 CLI 的薄包装
- 推荐优先使用 `scripts/crawl.py`

## 队列模式

如果需要使用 Celery/Redis 进行任务队列化运行：

设置 Redis：

```bash
export REDIS_URL=redis://127.0.0.1:6379/0
```

启动 worker：

```bash
python scripts/crawl.py worker --queue seed_http
python scripts/crawl.py worker --queue detail_http
python scripts/crawl.py worker --queue browser_render
```

投递到期任务：

```bash
python scripts/crawl.py enqueue-due
```

详细说明可参考 [QUEUE_WORKFLOW.md](/D:/bishe/darkweb_collector/QUEUE_WORKFLOW.md)。

## 输出与数据

### 输出目录

各站点输出在：

- `output/<site_name>/`

例如：

- `output/dragonforce/`
- `output/darkforums/`
- `output/chao/`

常见输出包括：

- `latest.json`
- `latest.html`
- `details/*.json`
- `details/*.html`
- 分板块输出目录，例如 `output/darkforums/databases/`

### 数据库

SQLite 默认路径：

- `data/collector.db`

主要包含：

- 采集结果表
- forum topic/detail 表
- `crawl_jobs` 审计表

## darkforums 当前行为说明

`darkforums` 现在的运行策略是：

- 每轮都会抓取 `databases`、`other_leaks`、`sellers_place` 三个板块的列表页
- 每个板块每轮最多解析 `max_topics_per_run`
- 详情页总数受 `max_detail_pages_per_run` 限制
- detail 任务会按板块轮转分配，而不是永远只优先 `databases`
- 已抓取且未变化的帖子会跳过 detail，避免重复抓取

如果使用 `--continuous`，它不会无限无间隔请求，而是：

1. 跑一轮
2. 休眠
3. 再跑下一轮

默认间隔来自 `sites.yaml` 中该站点的 `effective_interval_seconds`。

## 新站点接入方式

新增一个站点时，必须接入当前统一架构，而不是新写一套独立脚本。

标准接入点：

1. 在 `src/darkweb_collector/sites/<site>.py` 中实现 parser
2. 在 `src/darkweb_collector/adapters/<site>.py` 中实现 `SiteAdapter`
3. 在 [registry.py](/D:/bishe/darkweb_collector/src/darkweb_collector/adapters/registry.py) 中注册
4. 在 [sites.yaml](/D:/bishe/darkweb_collector/sites.yaml) 中新增站点配置
5. 通过：

```bash
python scripts/crawl.py run-site --site <site_name> --once
```

验证接入是否成功

## 本地 HTML 导入与样本开发

如果你已经通过授权方式获取 HTML 样本，可以用本地样本开发 parser，而不是直接在线调试：

```bash
python scripts/import_html_sample.py \
  --site dragonforce \
  --input /mnt/d/bishe/darkweb_collector/output/dragonforce/latest.html \
  --source-url http://dragonforxxbp3awc7mzs5dkswrua3znqyx5roefmi4smjrsdi22xwqd.onion/ \
  --output-json /mnt/d/bishe/darkweb_collector/output/imported/dragonforce_from_sample.json
```

这个模式适合：

- 离线解析开发
- 字段抽取调试
- 回归测试样本沉淀

## 当前稳态策略

- 请求超时
- 有界重试
- SQLite 去重和增量更新
- 列表页每轮重抓，详情页按变化抓取
- 单个 detail 失败不阻断整轮 seed 任务
- 原始 HTML 与结构化 JSON 双落盘

## 已知边界

- 明网站点如果目标站限流、TLS 异常或代理不稳定，单个 detail 仍可能失败，但不会中断整轮任务
- `.onion` 站点依赖 Tor Browser SOCKS 可用性
- `browser` 模式资源开销高于非浏览器模式，应只在确实需要 JS 渲染时使用
- 当前持续运行模式是“轮询式持续运行”，不是无间隔高频抓取
