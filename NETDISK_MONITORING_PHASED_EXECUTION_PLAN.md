# 网盘监测企业级能力分阶段执行计划

## 1. 执行原则

网盘监测只是整个项目的一个版块，实施企业级升级时必须遵守以下原则：

- 不影响暗网采集、代码监测、漏洞情报、数据泄露等其他模块。
- 不一次性重构 `document_exposure.py` 主流程。
- 新能力先追加、旁路、只读验证，再灰度切换。
- 每个阶段开工前先检查现有功能点，能复用现有表、API、前端页面和后台任务的，不得重复建设。
- 所有数据库改动只新增表、索引或兼容字段，不删除旧表、不改变旧字段语义。
- 现有 API 响应保持兼容，前端现有页面不因新能力上线而失效。
- 每个阶段都必须有验收标准和回退方式。

## 2. 总体阶段划分

| 阶段 | 目标 | 是否影响现有扫描 | 是否可回退 |
| --- | --- | --- | --- |
| M0 | 基线审计与保护 | 否 | 是 |
| M1 | 核验并补齐状态表和来源健康表 | 否 | 是 |
| M2 | 只读观测与对比 | 否 | 是 |
| M3 | 增量分页灰度启用 | 仅网盘模块 | 是 |
| M4 | 链接标准化与观察记录 | 仅网盘结果处理 | 是 |
| M5 | 关键词矩阵与查询预算 | 仅网盘监测配置 | 是 |
| M6 | 来源扩展与认证源管理 | 按来源逐个启用 | 是 |
| M7 | 风险评分、证据和告警 | 仅网盘命中流转 | 是 |
| M8 | 队列化、权限、运维企业化 | 部署层面渐进改造 | 是 |

## 3. M0：基线审计与保护

### 目标

在正式开发前固定当前行为，确保后续每一步都能判断是否破坏了现有能力。

### 改动范围

不改业务代码，只做审计、测试和基线记录。

### 具体任务

1. 记录当前网盘监测对象、关键词、来源和 `page_limit`。
2. 导出最近 10 次扫描记录，包括候选数、命中数、错误数、每个来源页数。
3. 建立现有能力盘点表，至少覆盖：
   - `netdisk_source_states`、`netdisk_source_health` 是否已在目标库创建。
   - `/api/document-exposures/netdisk/source-states`、`/api/document-exposures/netdisk/source-health` 是否可用。
   - `NETDISK_SCAN_MODE` 在 API 进程和定时任务进程中的实际值。
   - `useDocumentExposureApi.js`、网盘工作台、配置页、详情页是否已有可复用入口。
   - 平台会话、告警通知、队列 worker 是否已有共享能力。
4. 给每个计划能力标注 `已存在 / 需补齐 / 禁止重复建设`。
5. 补充现有行为测试：
   - 当前固定页扫描结果能正常生成。
   - `/api/exposure-watchlists` 响应结构不变。
   - `/api/exposure-scans` 响应结构不变。
   - `/api/document-exposures/summary` 响应结构不变。
6. 明确功能开关：
   - `NETDISK_SCAN_MODE=legacy`
   - `NETDISK_SCAN_MODE=incremental`

### 验收标准

- 可以用测试或脚本复现当前固定页扫描行为。
- 已产出现有能力盘点表，明确哪些能力已经存在、哪些确实缺失。
- 现有前端页面正常加载。
- 后续任何改动都能与 M0 基线对比。

### 回退方式

无业务改动，无需回退。

## 4. M1：核验并补齐状态表和来源健康表

### 目标

核验当前项目已经存在的网盘状态表、来源健康表、状态 API 和扫描接入逻辑；只补齐缺失字段、索引、迁移或前端展示，不改变现有扫描行为。

### 改动范围

后端数据库初始化、迁移核验、只读数据函数和已有 API 接入检查。

### 现有结构核验

目标结构为 `netdisk_source_states`。当前项目已存在该表时，不重复创建平行表，只核验字段和索引是否完整：

```sql
CREATE TABLE IF NOT EXISTS netdisk_source_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watchlist_id INTEGER NOT NULL,
    source_key TEXT NOT NULL,
    term TEXT NOT NULL,
    source_family TEXT NOT NULL DEFAULT 'netdisk_aggregator',
    next_page INTEGER NOT NULL DEFAULT 1,
    last_scanned_page INTEGER NOT NULL DEFAULT 0,
    page_window_size INTEGER NOT NULL DEFAULT 4,
    consecutive_empty_pages INTEGER NOT NULL DEFAULT 0,
    consecutive_repeated_pages INTEGER NOT NULL DEFAULT 0,
    last_candidate_signature TEXT NOT NULL DEFAULT '',
    last_success_at TEXT NOT NULL DEFAULT '',
    last_error_at TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    backoff_until TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(watchlist_id, source_key, term, source_family)
);
```

目标结构为 `netdisk_source_health`。当前项目已存在该表时，不重复创建平行表，只核验字段和索引是否完整：

```sql
CREATE TABLE IF NOT EXISTS netdisk_source_health (
    source_key TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'healthy',
    success_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    login_required_count INTEGER NOT NULL DEFAULT 0,
    captcha_count INTEGER NOT NULL DEFAULT 0,
    rate_limited_count INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT NOT NULL DEFAULT '',
    last_error_at TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    backoff_until TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
```

### 具体任务

1. 核验 `darkweb_collector/src/darkweb_collector/db.py` 中是否已有 `netdisk_source_states`、`netdisk_source_health` 及对应索引。
2. 核验 `list_netdisk_source_states_payload`、`reset_netdisk_source_states_payload`、`list_netdisk_source_health_payload` 是否已通过 API 暴露。
3. 核验扫描结束后是否写回 `next_page`、`last_scanned_page`、连续空页、连续重复页和最近错误。
4. 核验 `NETDISK_SCAN_MODE=legacy` 时是否只记录状态、不改变当前页码行为。
5. 核验 `NETDISK_SCAN_MODE=incremental` 时是否读取状态推进深页窗口。
6. 只有缺字段、缺索引、缺 API 或缺测试时才新增补丁。
7. 启动服务时自动补齐默认来源健康记录。

### 验收标准

- 旧数据库启动后能自动创建或补齐缺失结构。
- 空数据库启动后能正常创建所有表。
- 已存在 `netdisk_source_states`、`netdisk_source_health` 时不会出现重复表、重复 API 或重复前端入口。
- 现有扫描结果不变。
- 现有前端页面不变。

### 回退方式

关闭新代码路径即可。已存在或补齐的兼容结构不影响旧逻辑，可以保留。

## 5. M2：只读观测与对比

### 目标

在不改变扫描行为的前提下，旁路计算“如果启用增量分页，下次应该扫哪些页”。

### 改动范围

后端复用或补齐只读 API，前端复用现有文件监测页面增加状态展示。

### 复用或补齐 API

- `GET /api/document-exposures/netdisk/source-states`
- `GET /api/document-exposures/netdisk/source-health`
- `POST /api/document-exposures/netdisk/source-states/reset`

### 具体任务

1. 当前扫描仍按 legacy 模式运行。
2. 扫描结束后根据实际结果更新 `netdisk_source_states`，但不影响下一轮扫描。
3. 在现有文件监测/网盘监测页面增加“来源健康/分页游标”只读区域，不另建独立前端应用。
4. 展示每个来源和关键词：
   - 当前页窗口。
   - 建议下次页码。
   - 最近错误。
   - 连续空页。
   - 连续重复页。
   - 健康状态。

### 验收标准

- 现有扫描页码仍保持原逻辑。
- 新状态数据能正确记录。
- 连续 3 轮后能看到建议页码推进。
- 前端老表格不受影响。

### 回退方式

隐藏新增前端区域，后端不调用新 API 即可。

## 6. M3：增量分页灰度启用

### 目标

只在网盘模块内启用增量分页，让深页窗口按游标推进，同时保留回退到 legacy 的能力。

### 改动范围

仅限 `source_family=netdisk_aggregator` 的扫描路径。

### 功能开关

```text
NETDISK_SCAN_MODE=legacy
NETDISK_SCAN_MODE=incremental
```

默认先保持 `legacy`。验证通过后，对单个监测对象启用 `incremental`。

### 扫描策略

```text
每轮扫描 = 首页复扫 + 深页窗口

首页复扫：
  page 1，每轮都扫

深页窗口：
  从 next_page 开始
  默认窗口大小 4
  扫描成功后推进 next_page

退避：
  login_required / captcha / rate_limited 时暂停该来源
```

### 具体任务

1. 修改网盘扫描路径读取 `NETDISK_SCAN_MODE`。
2. `legacy` 模式完全保持当前行为。
3. `incremental` 模式读取 `netdisk_source_states`。
4. 首页每轮复扫。
5. 深页按 `next_page` 扫描。
6. 扫描结束后更新状态。
7. 错误时更新来源健康和退避时间。

### 验收标准

- `legacy` 模式下扫描结果与 M0 基线一致。
- `incremental` 模式下连续 3 轮深页窗口不重复固定在 1-4 页。
- 来源异常时进入退避，不再每轮重复打同一错误。
- 关闭开关后立即恢复 legacy 行为。

### 回退方式

设置 `NETDISK_SCAN_MODE=legacy`，无需回滚数据库。

## 7. M4：链接标准化与观察记录

### 目标

把候选链接变成可去重、可追踪、可复查的主命中和观察记录。

### 改动范围

仅限网盘候选结果处理，不影响扫描页码。

### 复用和补齐能力

- 复用 `document_hits.canonical_url` 做主命中去重。
- 如现有 canonical 规则不足，再补 `link_fingerprint`。
- `document_link_observations`
- 短链展开。
- 跳转链接解析。
- 正文网盘链接抽取。

### 具体任务

1. 先核验 `document_exposure.py` 中现有 canonical URL、访问状态、文件清单和命中详情能力。
2. 如现有逻辑不足，再新增 `netdisk_link_normalize.py` 或等价小模块。
3. 支持百度网盘、阿里云盘、夸克、123、迅雷、OneDrive、115、UC。
4. 只有现有 `document_hits` 无法表达传播来源时，才新增 `document_link_observations` 表。
5. 同一 canonical URL 或 `link_fingerprint` 只生成一个主命中。
6. 每次发现写入观察记录。
7. 复用现有详情页展示“传播来源”。

### 验收标准

- 同一链接被多个来源发现时不重复生成主命中。
- 可以看到该链接被哪些来源、关键词、页码发现。
- 旧的命中列表字段保持兼容。

### 回退方式

关闭观察记录写入，只保留旧命中逻辑。

## 8. M5：关键词矩阵与查询预算

### 目标

扩大企业敏感信息发现面，但避免无限制增加请求量。

### 改动范围

现有监测对象配置和查询生成逻辑。

### 补齐能力

- 企业资产画像。
- 查询模板。
- 关键词质量统计。
- 查询预算。
- 白名单和误报反馈。

### 具体任务

1. 在现有监测对象配置上补齐企业资产画像字段，避免新建一套企业资产主数据：
   - 中文名。
   - 英文名。
   - 简称。
   - 域名。
   - 邮箱后缀。
   - 子公司。
   - 项目名。
   - 系统名。
   - 供应商。
   - 高敏词。
2. 新增查询模板管理能力，模板由管理员在前端维护，或通过 CSV/Excel/JSON 导入，不能写死在代码中。
3. 准备可导入的示例模板文件，例如：
   - `{company} 通讯录`
   - `{company} 合同`
   - `{company} 财务`
   - `{company} 报价单`
   - `{domain} xlsx`
   - `{project_name} 网盘`
4. 每个模板支持启停、优先级、来源适用范围和每日预算。
5. 设置全局每日查询预算和全局每小时请求预算，作为所有企业共享的硬上限。
6. 每个监测对象设置每日查询预算，但只能在全局预算和来源预算内分配。
7. 每个来源设置每小时请求预算、并发数、最小请求间隔和退避时间。
8. 企业数量增加时按优先级和权重公平分配预算，不能让请求量按企业数量线性放大。
9. 来源出现登录拦截、验证码、限流、429、403 或连接失败时，自动扣减可用预算并进入退避。
10. 低命中、高误报关键词自动降频。
11. 人工导入线索、历史复查、本地结果去重不消耗外部请求预算。

### 验收标准

- 单个企业对象可生成 50 个以上候选查询。
- 查询模板可人工导入、编辑、禁用和导出。
- 查询生成受全局预算、来源预算、企业预算和模板预算共同控制。
- 企业数量增加后，同一来源的请求量不会线性增长。
- 来源触发限流或验证码后能自动退避，不继续高频请求。
- 低质量关键词可禁用或降频。
- 扩关键词后扫描任务不会无限增长。

### 回退方式

关闭自动扩展，仅使用人工配置关键词。

## 9. M6：来源扩展与认证源管理

### 目标

扩展公开论坛、博客、贴吧、问答、Telegram、搜索引擎等来源，同时明确哪些不需要登录，哪些需要企业授权。

### 改动范围

新增来源适配器和来源配置，不影响已有来源；需要登录的来源统一复用现有平台会话体系，不新建账号、Cookie 或 Token 管理模块。

### 来源分层

公开源：

- 不需要登录即可访问。
- 优先接入。
- 不绕过访问限制。

认证源：

- 需要 Cookie、Token、API Key 或专用账号。
- 必须使用企业专用监测账号。
- 凭据管理优先复用 `platform_sessions`、`document_exposure_sessions.py` 和 `/api/platform-sessions`。
- 失效后只停该来源，不影响全局扫描。

### 接入顺序

第一批：

- Bing dork。
- PanSou / PanHub。
- 人工导入。
- Telegram 公开频道页面。

第二批：

- 百度/360 dork。
- 贴吧公开页。
- 论坛公开页。
- 问答公开页。

第三批：

- 企业授权认证源。
- 商业情报源。
- Telegram API 客户端。

### 每个来源必须有适配器设计卡片

字段：

- 来源名称。
- 是否需要登录。
- 查询 URL 模板。
- 分页规则。
- 限流表现。
- 登录拦截表现。
- 验证码表现。
- HTML 样本。
- 候选链接解析规则。
- 单元测试样本。
- 复用组件：是否复用平台会话、浏览器取证、现有 API、现有前端配置页。

### 验收标准

- 新来源可独立启停。
- 新来源故障不影响旧来源。
- 认证源失效只进入该来源退避。
- 公开源和认证源在界面上明确区分。

### 回退方式

禁用具体来源适配器即可。

## 10. M7：泄露判定策略、风险评分、证据和告警

### 目标

让网盘命中具备企业可配置的泄露判定标准、风险优先级、证据链和处置闭环。

### 改动范围

网盘命中后处理和现有前端处置页面。命中主表、详情页、复核记录和通知出口优先复用现有文件监测能力。

### 补齐能力

- 企业泄露判定策略。
- 行业模板规则。
- 企业白名单和例外规则。
- 风险评分。
- 评分原因。
- 证据文件哈希。
- 证据访问审计。
- 告警去重。
- 告警升级。
- 处置 SLA。

### 具体任务

1. 新增 `netdisk_leakage_policies` 表。
2. 新增 `netdisk_leakage_policy_rules` 表。
3. 监测对象关联 `leakage_policy_id`。
4. 先核验现有 `_score_document_hit` 能否扩展；如固定规则难以维护，再新增 `netdisk_risk_scoring.py`。
5. 风险评分读取企业策略，而不是只使用固定规则。
6. 给每条命中计算风险等级：
   - high
   - medium
   - low
7. 记录评分原因和命中的策略规则。
8. 优先复用现有命中快照、HTML/截图和详情页证据结构；只有访问审计或保留策略无法表达时，才新增证据资产表。
9. 复用现有详情页展示证据截图、文件清单、传播来源。
10. 高危公开链接通过现有 `monitoring_notifications.py`、`bot_assistant.py` 通知出口触发告警。
11. 同一链接在去重窗口内只告警一次。
12. 已下架链接重新公开时重新告警。

### 验收标准

- 高危命中能按评分原因解释。
- 同一条命中在不同企业策略下可以得到不同风险等级。
- 企业白名单和例外规则可以覆盖默认基线规则。
- 告警不重复刷屏。
- 证据查看和下载有审计记录。
- 处置状态可追踪。

### 回退方式

关闭告警发送，保留风险评分和证据记录；必要时隐藏新增前端入口。

## 11. M8：队列化、权限、运维企业化

### 目标

当来源、关键词和任务量增长后，系统仍能稳定运行，并具备企业级权限和运维能力。

### 改动范围

部署和调度层面渐进改造。优先复用现有 Celery、queueing、后台任务状态和同步扫描入口，避免为网盘监测单独维护一套 worker 框架。

### 任务拆分

- `query_discovery`
- `link_normalize`
- `access_probe`
- `file_listing`
- `alert_dispatch`

### Worker 建议

如果现有 `celery_app.py`、`tasks.py`、`queueing.py` 已能承载，下面只是逻辑队列拆分建议，不代表必须新建独立服务：

```text
api_server: 1
query_worker: 2
probe_worker: 2
file_listing_worker: 1
alert_worker: 1
scheduler: 1
```

### 权限角色

- `admin`
- `analyst`
- `operator`
- `auditor`

### 运维能力

- 队列积压。
- 死信任务。
- 来源错误率。
- 告警发送成功率。
- 证据目录大小。
- 数据库大小。
- 最近备份时间。

### 验收标准

- API 重启后任务和游标可恢复。
- 单个 Worker 异常不影响 API 页面。
- 权限不足用户无法查看或下载证据。
- 可以从备份恢复数据库和证据文件。

### 回退方式

保留同步扫描入口。队列异常时切回同步扫描或 legacy 模式。

## 12. 推荐实施顺序

最稳妥的顺序：

1. M0：基线审计与保护。
2. M1：核验并补齐状态表和来源健康表。
3. M2：只读观测与对比。
4. M3：增量分页灰度启用。
5. M4：链接标准化与观察记录。
6. M5：关键词矩阵与查询预算。
7. M6：来源扩展与认证源管理。
8. M7：风险评分、证据和告警。
9. M8：队列化、权限、运维企业化。

不建议跳过 M0-M3。原因是当前最确定的问题是固定页重复扫描，如果不先解决这个基础问题，后续扩来源、扩关键词会放大重复扫描和重复告警。

## 13. 每阶段上线门槛

每个阶段上线前必须满足：

- 单元测试通过。
- 相关 API 测试通过。
- 现有网盘页面可正常加载。
- 其他模块页面可正常加载。
- 有明确开关或回退手段。
- 有一轮真实扫描验证。
- 有变更记录。

## 14. 项目其他模块保护清单

实施期间不得无关修改：

- 暗网采集适配器。
- 代码监测扫描逻辑。
- 漏洞情报同步逻辑。
- 数据泄露模块页面。
- 通用路由和全局布局。
- 非网盘相关数据库表结构。

如确实需要改共享函数，必须先确认调用方，并补充回归测试。

### 已有功能点复用清单

以下能力当前项目已经具备或已有入口，实施时不得重复建设：

| 已有能力 | 复用方式 | 禁止事项 |
| --- | --- | --- |
| `netdisk_source_states` | 作为网盘分页游标和状态记录主表 | 禁止再建平行状态表 |
| `netdisk_source_health` | 作为来源健康、退避和可用性统计主表 | 禁止再建平行来源健康表 |
| `NETDISK_SCAN_MODE` | 作为 legacy/incremental 灰度开关 | 禁止新增含义重复的扫描模式开关 |
| `document_hits` | 作为网盘命中主表 | 禁止新增独立网盘命中主表 |
| `document_hit_reviews` | 作为命中复核和处置记录 | 禁止新增独立复核流转表，除非现有状态无法表达 |
| `platform_sessions` | 作为登录态、Cookie、Token 管理入口 | 禁止另写认证源账号系统 |
| `useDocumentExposureApi.js` 和文件监测页面 | 作为网盘前端扩展入口 | 禁止另建独立网盘前端应用 |
| `monitoring_notifications.py`、`bot_assistant.py` | 作为告警通知出口 | 禁止重复配置 webhook 和机器人 |
| `celery_app.py`、`tasks.py`、`queueing.py` | 作为队列和 worker 基础设施 | 禁止另建独立队列框架 |

每个阶段的开发任务单必须写明：复用哪些已有能力、补齐哪些缺口、哪些共享模块需要回归测试。

## 15. 最小可行落地版本

如果只先做一个低风险但能明显改善当前问题的版本，建议范围限定为：

- M0。
- M1。
- M2。
- M3。

即只实现：

- 基线保护。
- 核验并补齐状态表。
- 核验并补齐来源健康表。
- 只读状态展示。
- 网盘增量分页灰度启用。
- legacy 回退开关。

如果当前生产环境仍处于 legacy 或状态未生效，这个版本完成后，网盘监测会从“每小时重复扫同几页”升级为“首页复扫 + 深页轮转”，同时不影响项目其他版块。
