# 数据库与镜像文件一体化迁移

该功能不依赖 AI。外部命令行工具把旧 SQLite 数据库和镜像目录打包为一个 `.dwti` 文件；管理员在项目的“数据迁移”页面上传后，后端完成预检、PostgreSQL 隔离导入、数据校验和受控切换。

## 1. 准备目标 PostgreSQL

先创建一个持久化 PostgreSQL 数据库和专用账号。该账号需要连接目标数据库并创建 schema、表、索引、外键和函数的权限。导入器不会使用或覆盖 `public` schema，而是为每个迁移包创建独立的 `dwti_<批次编号>` schema。

Windows 首次启动时，如果尚未配置目标 PostgreSQL，启动脚本会调用项目内置的 `scripts\setup_postgresql_windows.ps1` 自动安装或复用 PostgreSQL 16，并创建项目数据库和账号。已有目标配置或已激活 PostgreSQL 时不会重复安装或重置密码。该步骤只准备迁移目标，不会自动切换或覆盖已有 SQLite 数据。可以用 `plan` 和 `status` 子命令分别预览或检查，不执行导入：

```powershell
.\scripts\setup_postgresql_windows.ps1 plan
.\scripts\setup_postgresql_windows.ps1 status
```

Debian / Ubuntu / WSL / Codespaces 使用 `scripts/setup_postgresql_linux.sh` 完成同样的首次安装和幂等检查。脚本从 PostgreSQL 官方 PGDG 仓库安装 PostgreSQL 16，校验官方签名指纹，使用本机 `postgres` 系统账号创建项目角色和数据库，并把应用口令保存到当前用户私有的 `postgresql-target.json`（权限 `600`）：

```bash
bash ./scripts/setup_postgresql_linux.sh plan
bash ./scripts/setup_postgresql_linux.sh status
```

使用外部 PostgreSQL 时，在启动项目前显式设置目标连接；此时启动脚本不会安装本机 PostgreSQL。连接串属于服务端机密，不要写入源码、前端或 Git：

Windows PowerShell：

```powershell
$env:DARKWEB_MIGRATION_TARGET_DATABASE_URL = 'postgresql://<user>:<password>@127.0.0.1:5432/<database>'
.\scripts\start_all_services_windows.ps1 start
```

WSL / Linux：

```bash
export DARKWEB_MIGRATION_TARGET_DATABASE_URL='postgresql://<user>:<password>@127.0.0.1:5432/<database>'
./scripts/start_all_services_wsl.sh start
```

自动安装仅支持 Windows 以及使用 `apt-get` 的 Debian / Ubuntu / WSL / Codespaces；其他 Linux 发行版必须显式提供外部目标。设置 `DARKWEB_POSTGRESQL_AUTO_INSTALL=0` 可以关闭 Linux 自动安装。所有自动安装的都是本机单节点 PostgreSQL，不会形成跨主机高可用；目标服务必须在项目重启后仍可访问。

## 2. 在旧系统生成迁移包

停止会产生大量新写入的采集任务后执行：

```bat
D:\path\to\database-migration-kit\tools\migration-export.cmd pack ^
  --database "C:\path\to\collector.db" ^
  --artifacts "C:\path\to\output" ^
  --output "D:\backup\darkweb-20260812.dwti"
```

Windows 图形工具可以直接选择 `\\wsl.localhost\<发行版>\...\collector.db` 和同一 WSL 发行版内的 `output` 目录。工具会把数据库及稳定的 `-wal`、`-shm`、`-journal` 侧文件复制到 Windows 临时目录，再通过 SQLite Backup API 创建快照；复制前后文件大小或修改时间发生变化时会中止，因此仍必须先停止 WSL 中的 API、worker、scheduler 和其他写库进程。

也可以先把数据库快照和完整 `output` 目录复制到 Windows 再打包，但必须保留 `output` 下全部相对目录和文件名，不能只复制单个站点、拍平目录或形成额外的 `output/output` 层级。

导出器执行以下固定流程：

1. 通过 SQLite Backup API 创建一致性快照，源数据库保持不变。
2. 只在快照上补齐当前版本的数据库结构，并执行 `PRAGMA quick_check`。
3. 将每张表导出为数据库无关的 JSONL 数据。
4. 把 `html_path`、`screenshot_path`、`raw_artifact_path` 中的 WSL/Linux/Windows 绝对路径转换为 `dwti-artifact://` 可移植相对路径；任一非空路径在所选镜像目录中找不到对应文件都会中止打包。
5. 将镜像目录写入同一个 ZIP64 容器，并逐条核对数据库路径引用确实存在于包内。代码/文库镜像遇到 Windows 保留设备名、非法字符、末尾点或空格、Unicode 等价名、超长组件及大小写冲突时，会迁入稳定哈希命名的兼容目录并同步数据库引用；没有显式路径字段的暗网核心镜像遇到这些情况时会拒绝打包。
6. 记录每张表的行数、空值计数、XOR256 和 SUM256 摘要，并为每个载荷生成 SHA-256。

SQLite 索引的列顺序、唯一性、部分索引条件以及每列 `ASC` / `DESC` 方向会写入结构清单，并在 PostgreSQL 中按相同方向创建。表达式索引和非 `BINARY` 自定义排序规则仍会安全阻断，避免静默改变查询语义。

平台会话、Cookie、令牌、凭据目录不会打包；`platform_sessions` 中的会话路径、会话元数据和错误文本会被清空。迁移后需要重新登录这些外部平台。

## 3. 在项目中导入

登录管理员账号，打开：

```text
系统设置 -> 数据迁移
```

选择 `.dwti` 文件并点击“上传并开始校验”。后端依次执行：

- 文件名、路径穿越、符号链接、重复路径、数量、体积和压缩炸弹检查；
- 全部载荷 SHA-256 校验；
- 数据库镜像路径与包内文件逐项对应校验；
- PostgreSQL 独立 schema 建表和分批导入；
- 可移植镜像路径重写为当前迁移批次的新镜像根目录；
- 数据库逐表联合摘要复核；
- 镜像文件释放到独立批次目录。

只有数据库和镜像文件全部校验一致，任务才会进入“等待切换”状态。导入失败不会修改当前活动数据库，也不会覆盖当前镜像目录。

## 4. 确认切换与回退

确认切换后，项目写入新的活动版本配置，并调用现有启动脚本停止和重启服务。重启后会检查 PostgreSQL schema 指纹、迁移版本、数据库可查询性和 API 健康状态；任一步失败都会恢复旧活动版本并再次启动。

活动版本配置默认位于：

- Windows：`%LOCALAPPDATA%\DarkWebThreatIntel\active-release.json`
- WSL / Linux：`$HOME/.local/share/darkweb-threat-intel/active-release.json`

Linux PostgreSQL 目标配置默认位于 `$HOME/.local/share/darkweb-threat-intel/postgresql-target.json`，目录权限为 `700`、文件权限为 `600`；其中包含应用数据库口令，不要复制到源码仓库、日志或工单。

迁移批次、导入报告和镜像目录保存在同一用户数据根目录下的 `migrations` 目录。第一次从 SQLite 切换时，原 SQLite 文件不会删除；后续迁移时，上一活动 PostgreSQL schema 和镜像目录也会保留。

如果新 PostgreSQL 已产生业务写入，回退到旧 SQLite 或旧 schema 会丢失这部分新写入，不能把自动启动回退当作长期双写或数据库合并方案。

## 5. 配置项与边界

- `DARKWEB_MIGRATION_AUTO_RESTART=0`：导入后只写活动配置，不自动调用启动脚本。
- `DARKWEB_MIGRATION_MAX_BUNDLE_BYTES`：上传文件上限，默认 20 GiB。
- `DARKWEB_MIGRATION_MAX_UNCOMPRESSED_BYTES`：解压后总量上限，默认 100 GiB。
- `DARKWEB_MIGRATION_MAX_ENTRIES`：迁移包条目上限，默认 250,000。
- `DARKWEB_MIGRATION_MAX_ROW_BYTES`：单条数据库记录的 JSONL 上限，默认 64 MiB。
- Windows 最终镜像路径按传统运行时兼容边界限制为 259 个 UTF-16 单元；目录过深会在释放文件前中止并清理批次，请缩短 `DARKWEB_MIGRATION_ROOT` 或用户数据目录。
- 当前是完整替换迁移，不做两个数据库之间的数据合并或增量同步。
- 旧版工具生成且不含 `portable_path_fields` 元数据的迁移包仍可校验和导入，但不会自动重写既有绝对路径；涉及代码监测或文库监测镜像时应使用新版工具重新生成迁移包。
- SHA-256 用于发现损坏和篡改，不代表发布者身份认证；只导入来源可信的迁移包。

## 已完成验证

2026-08-12 在隔离 PostgreSQL 环境中使用当前真实数据完成全量验证：33 张业务表、25,197 行记录和 6,937 个镜像文件全部导入，镜像总量为 897,376,770 字节，最长 Windows 路径为 294 字符；另有 416 个会话或敏感文件按规则排除。逐表行数、空值计数、XOR256 和 SUM256 全部一致，释放后的镜像数量和字节数也与清单一致。项目数据库适配层能够读取主要 API 数据，并完成一次带 `lastrowid` 的写入及事务回滚。前端生产构建、迁移 API 鉴权、Windows 启动脚本解析和 WSL Shell 语法检查均通过。

2026-08-18 追加验证 Windows 通过 `\\wsl.localhost\Ubuntu\...` 对 WSL SQLite 执行本地暂存和只读快照；使用包含 5 个 WSL 绝对镜像路径字段的小型迁移包完成导出、包内路径核对、真实 PostgreSQL 导入、目标根目录重写和逐表摘要复核，缺失镜像文件会在导出阶段被拒绝。验证创建的临时 PostgreSQL Schema 和镜像释放目录已清理。

2026-08-19 使用 WSL ext4 中两个仅大小写不同且内容不同的 `code_monitoring` HTML 镜像完成回归：迁移包为两个文件生成不同的稳定归档名，数据库路径同步更新；在 Windows 释放并导入 PostgreSQL 后两份内容均保留、路径均位于新镜像根目录，摘要复核通过。随后追加 Windows 文件名兼容回归，覆盖保留设备名、冒号、末尾点或空格、Unicode NFC 等价冲突及超长组件；可显式重写的代码/文库路径全部转为安全归档名，暗网核心不兼容路径按安全边界拒绝打包。

2026-08-19 使用用户提供的真实 SQLite 与 `output.zip` 完成最终回归：源库 `quick_check=ok`、外键错误为 0，共 38 张原始表和 222,642 行；快照升级后生成 39 张表，两个 `ai_aggregation_runs` 降序索引在 PostgreSQL 中保留为 `DESC`。ZIP 的 29,556 个文件和 2,830,679,096 字节通过 CRC，排除 9 个会话或敏感文件后，29,547 个镜像、2,830,630,704 字节进入迁移包；两组 Windows 路径冲突涉及的 4 个文件完成安全重命名。PostgreSQL 逐表摘要、29,547 个释放文件的全量 SHA-256、各 30 个 JSON/HTML/PNG 样本、DragonForce/Lynx 列表详情镜像及重命名代码详情全部通过。深目录测试会在释放文件前明确拒绝并清理，短的默认运行目录完成导入。
