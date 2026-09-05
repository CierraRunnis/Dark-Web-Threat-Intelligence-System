# SQLite → PostgreSQL 16 数据迁移

本项目采用离线全量迁移：把活动 collector.db 和完整 output 证据目录打成一个 .dwti，导入 PostgreSQL 独立 Schema，完成数据、文件、功能和性能验收后再激活。auth_accounts.db、样本库和遗留库不在迁移范围内。

迁移不会删除 SQLite、原证据目录、.dwti、旧 PostgreSQL Schema 或旧 release。系统不做双写、CDC、增量同步或两个数据库之间的数据合并。

## 1. 准备 PostgreSQL 16

Ubuntu、Debian 和 WSL 使用：

~~~bash
bash ./scripts/setup_postgresql_linux.sh plan
bash ./scripts/setup_postgresql_linux.sh install
bash ./scripts/setup_postgresql_linux.sh status
~~~

安装脚本固定 PostgreSQL 16，并创建两个不同角色：

- darkweb_migrator：创建每批次 dwti_<bundle-id> Schema、表、函数、索引和授权。
- darkweb_app：只获得活动 Schema 的 USAGE、表 DML 和序列权限；没有 Schema DDL 权限。

脚本撤销 PUBLIC 在 public Schema 上的 CREATE 权限。私有配置默认写入：

~~~text
$HOME/.local/share/darkweb-threat-intel/postgresql-target.json
~~~

配置格式为 2，权限为 0600，包含 migration_database_url 与 runtime_database_url。前者只用于导入和清理新 Schema，后者才写入 active-release.json。口令不得进入源码、前端、日志或工单。

外部 PostgreSQL 需要分别提供：

~~~bash
export DARKWEB_MIGRATION_TARGET_DATABASE_URL='postgresql://migrator:...@host:5432/database'
export DARKWEB_MIGRATION_RUNTIME_DATABASE_URL='postgresql://runtime:...@host:5432/database'
~~~

两个 URL 的用户名必须不同。运行角色还需要目标数据库的 CONNECT、TEMPORARY 权限；迁移角色需要 CONNECT、CREATE 和 TEMPORARY。

## 2. 停机导出 .dwti

必须先停止 API、Celery worker、scheduler 和 normalizer，然后执行：

~~~bash
PYTHONPATH=src ./venv/bin/python scripts/export_migration_bundle.py \
  --database "$HOME/.local/share/bishe/collector.db" \
  --artifacts "/absolute/path/to/darkweb_collector/output" \
  --output "/absolute/backup/darkweb-final.dwti"
~~~

CLI 没有跳过停机检查的参数。它会枚举已知写库进程，并尝试取得 SQLite 独占事务；检测到服务或数据库锁后直接拒绝导出。

导出固定执行：

1. 使用 SQLite Backup API 创建一致性快照，而不是直接复制 WAL 数据库文件。
2. 只在快照中执行当前 _ensure_schema，并补齐 site_connectivity_probes；本地 38 张源表因此形成 39 张目标业务表。
3. 执行 PRAGMA quick_check，枚举字段、PK/FK、唯一约束、部分索引和排序方向。
4. 每张表写入独立 JSONL，记录行数、空值数、XOR256 和 SUM256。
5. 将完整证据目录写入 ZIP64，并为每个载荷记录 SHA-256。
6. 把代码监测、文库监测和 ai_aggregation_reports.file_path 改写为 dwti-artifact:// 可移植路径。
7. 排除会话、Cookie、凭据和敏感目录；清空平台会话。
8. 清空 AI 投递目标及历史尝试的配置 JSON、禁用全部 AI 投递目标，并清除相关错误文本。迁移后必须重新录入 callback/企业微信等投递配置。

任一数据库文件路径找不到对应证据、存在越界路径、符号链接、不可安全改名的跨平台文件名或大小写冲突时，导出会失败且不会留下半成品。

## 3. 上传、导入与任务状态

管理员迁移 API：

~~~text
GET  /api/migrations/config
GET  /api/migrations
POST /api/migrations/upload
GET  /api/migrations/{job_id}
POST /api/migrations/{job_id}/performance
POST /api/migrations/{job_id}/activate
~~~

上传接口接收原始请求体，文件名放在 X-DWTI-Filename。只有 request.state.current_user.role == "admin" 可以调用；不能用固定用户名代替角色鉴权。

导入由脱离 API 生命周期的独立子进程执行，状态原子写入磁盘。系统级文件锁与 PostgreSQL advisory lock 阻止并发导入或激活。

~~~text
queued → preflight → importing → verifying → analyzing → ready
                                                    ↘ failed
ready → activating → active
                  ↘ rolled_back / rollback_failed
~~~

预检覆盖路径穿越、符号链接、重复路径、大小写冲突、条目数、体积、压缩炸弹、Schema 指纹、39 张必需表与关键字段、全部载荷 SHA-256，以及数据库文件路径与包内证据的一一对应。

导入覆盖：

- 每个 bundle 建立独立 dwti_<bundle-id> Schema。
- 500 行一批导入并重置 identity。
- 从 PostgreSQL 重读每张表，比较行数、空值数、XOR256 和 SUM256。
- 从释放目录重新计算全部证据 SHA-256。
- 安装 0001_baseline、0002_sqlite_compat、0003_local_postgres_compat、0004_performance_indexes。
- 安装受限兼容函数 datetime(text)、datetime(text,text)、json_extract(text,text)；无效输入返回 NULL。
- 建立情报、任务、文库、代码、漏洞和 AI 热路径索引，并执行 ANALYZE。
- 用运行账号检查 39 张表、关键字段、四个版本、Schema 指纹、代表性读取、identity 写入和强制回滚 canary。

## 4. 性能与语义门禁

默认 DARKWEB_MIGRATION_REQUIRE_BENCHMARK=1。导入完成后任务停在 analyzing，必须向 performance 接口提交报告才会转为 ready。

每个读取场景必须同时包含并发 1 和并发 8：

~~~text
dashboard_overview
intelligence_search
data_leak
ransomware_vulnerability
crawl_jobs
code_document_monitoring
ai_aggregation
~~~

报告格式：

~~~json
{
  "read_results": [
    {
      "scenario": "dashboard_overview",
      "concurrency": 1,
      "sqlite_p95_ms": 100.0,
      "postgres_p95_ms": 105.0,
      "errors": 0
    }
  ],
  "write_result": {
    "sqlite_tps": 100.0,
    "postgres_tps": 210.0,
    "transactions": 800,
    "errors": 0
  },
  "semantic_equivalence": {"passed": true, "mismatches": 0}
}
~~~

强制条件：

- 并发 8：每个场景 PostgreSQL P95 ≤ SQLite P95 的 80%。
- 并发 1：每个场景 PostgreSQL P95 ≤ SQLite P95 的 110%。
- 写入：至少 800 个复合事务，PostgreSQL 吞吐 ≥ SQLite 的 2 倍。
- 所有读写错误数为 0。
- 规范化结果、分页总数、排序、大小写、JSON 国家字段和上海时区语义一致。

仅自动化单元测试可以设置 DARKWEB_MIGRATION_REQUIRE_BENCHMARK=0。生产环境不应关闭门禁。

## 5. 激活与回退

激活接口只启动独立控制器，不会在仍运行的 API 进程内提前改连接。控制器顺序固定为：

~~~text
取得文件锁和 PostgreSQL advisory lock
→ 停止全部服务
→ 用运行账号执行 Schema/读取/写入回滚 canary
→ 原子写 active-release.json（仅 runtime URL）
→ 启动完整服务
→ 再次执行强数据库校验
→ 校验 /api/health 的 PostgreSQL engine、Schema、0004 版本和 database_ready
~~~

任一步失败：

- 若尚未写活动版本：直接重启原服务，配置不变。
- 若已写活动版本：恢复 previous-active-release.json，停止新服务并启动旧版本。
- 回退失败时任务进入 rollback_failed，需要人工检查。

原 SQLite 和证据目录始终保留。不过 PostgreSQL 激活后产生的新写入不会自动同步回旧库，因此回退会丢失切换后的新增数据。

## 6. 配置边界

- DARKWEB_MIGRATION_MAX_BUNDLE_BYTES：上传包上限，默认 20 GiB。
- DARKWEB_MIGRATION_MAX_UNCOMPRESSED_BYTES：解压后总量上限，默认 100 GiB。
- DARKWEB_MIGRATION_MAX_ENTRIES：包内条目上限，默认 250,000。
- DARKWEB_MIGRATION_MAX_ROW_BYTES：单条 JSONL 上限，默认 64 MiB。
- DARKWEB_POSTGRES_CONNECT_TIMEOUT_SECONDS：PostgreSQL 建连超时，默认 5 秒。
- DARKWEB_MIGRATION_ROOT：任务、release、锁和报告根目录。
- DARKWEB_MIGRATION_AUTO_RESTART=0：禁止激活；不会降级成先写配置再人工重启。
- Windows 释放路径按 259 个 UTF-16 单元的传统运行边界预检。
- SHA-256 用于发现损坏和篡改，不证明迁移包发布者身份；只导入可信来源的包。

