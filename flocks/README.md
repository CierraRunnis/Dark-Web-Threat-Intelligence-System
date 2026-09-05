# AI 聚合所需的 Flocks 文件

这个目录是本项目 AI 聚合模块的 Flocks 依赖包。文件来自当前使用的用户级插件目录；4 个工作流已通过运行中的 Flocks API 比对，节点、边和入口与文件一致。这里不包含完整的 Flocks 安装目录或用户数据。

为便于在其他机器安装，`search-supervisor/prompt.md` 中的一处本机绝对路径已替换为 `~/.flocks/` 用户目录形式；原运行文件未修改。清单同时记录该文件的原始哈希和导出哈希。

## 必需文件

| 内容 | 路径 | 作用 |
| --- | --- | --- |
| 主工作流 | `plugins/workflows/threat_intel_search_pipeline/` | 关键词扩展、三源并发、去重降噪、生成报告 |
| 3 个子工作流 | `plugins/workflows/*_source_search/` | 暗网、Telegram、Web 各来源搜索与归一化 |
| 7 个智能体 | `plugins/agents/` | supervisor、关键词、3 个搜索、降噪、报告；每个包含 YAML 与提示词 |
| 3 套批量工具 | `plugins/tools/api/` | 每套包含工具 YAML 和 Python handler |
| 引擎兼容补丁 | `runtime/flocks-v2026.7.23-ai-aggregation.patch` | 对齐当前 Flocks 的工作流、任务执行和 Exa 搜索行为，含相关测试 |
| 版本与文件清单 | `runtime/version.json`、`manifest.json` | 固定基础提交并记录插件哈希、运行中比对结果 |
| 配置示例 | `config/integration.env.example` | 只列出本模块需要的配置与空凭据 |

Flocks 内置的 `delegate_task`、`run_workflow`、`read`、`grep`、`glob`、`webfetch` 和 `websearch` 由框架提供，不重复复制。Web 批量工具实际调用 `websearch`，当前版本走 Exa API。

## 准备兼容的 Flocks 运行时

当前运行版本基于上游 `v2026.7.23`，但不是未经修改的发行版：

- 上游地址：<https://gitee.com/flocks/flocks.git>
- 基础提交：`a4d1830031004ca5397071d304b71be7a21d9e62`
- 本机运行提交：`0515eaa9f247af68ba28604a8efa21243d031f61`
- Python 要求：`>=3.12,<3.13`

兼容补丁包含 8 个框架源码文件和 7 个相关测试文件的差异，其中包括完整保留子工作流结果、保留终态报告，以及当前 Exa 搜索实现。已验证补丁可应用到上述基础提交，应用后所有 15 个文件与运行提交中的 Git 对象一致。

建议在新的 Flocks 源码副本中切换到上述基础提交。将本目录中补丁的绝对路径作为参数，先检查，再应用：

```bash
git apply --check /path/to/this-repository/flocks/runtime/flocks-v2026.7.23-ai-aggregation.patch
git apply /path/to/this-repository/flocks/runtime/flocks-v2026.7.23-ai-aggregation.patch
uv sync --frozen
```

不同版本不要直接覆盖引擎文件；应先确认补丁是否适用。Flocks 的原始许可证随包保留在 `runtime/LICENSE-Flocks.txt`；补丁属于该框架文件的修改。

## 安装插件

在本目录运行，先检查内容和安装位置：

```bash
python -m pip install -r requirements.txt
python scripts/verify_bundle.py
python scripts/install_plugins.py --dry-run
python scripts/install_plugins.py
```

默认目标为当前用户的 `~/.flocks/plugins/`，也可用 `--flocks-home` 指定另一套 Flocks 用户目录。安装器只复制清单里的插件文件，不复制配置或引擎补丁；已有文件相同时跳过，不同时停止，显式传入 `--overwrite` 才替换。安装后重启该套 Flocks 服务以重新加载插件。

## 必须单独配置的服务

| 服务 | 当前连接方式 | 需要配置的内容 |
| --- | --- | --- |
| Flocks Task Center | `http://127.0.0.1:5175` | 启用任务调度；项目后端配置 `FLOCKS_API_KEY`，或通过 `FLOCKS_SECRET_FILE` 读取 `server_api_token` |
| LLM | Flocks 默认模型/提供商 | 在目标 Flocks 中配置可用模型及对应密钥；智能体 YAML 未固定某个私有提供商 |
| 项目暗网情报 API | `http://127.0.0.1:8000/api/ai/intelligence` | 由本仓库后端提供；需要已经采集的目标数据，接口限定回环访问 |
| Telegram MCP | `http://127.0.0.1:3333/mcp` | 单独运行 `tg-search`，具备 `search_global` 工具；由该服务独占已登录的 Telegram session |
| Exa | `https://api.exa.ai/search` | Flocks 密钥存储中的 `exa_api_key`，或 Flocks 进程的 `EXA_API_KEY` 环境变量 |

Telegram 地址可用 `FLOCKS_TG_MCP_URL` 覆盖。该 handler 调用 `search_global`，参数为 `query`、`limit`、`use_default_excludes=false`，有时间窗时另传 ISO 格式 `min_date`。Telegram 服务实现及授权会话不属于这个 Flocks 插件包，需要独立部署。

项目后端调用 Task Center 的请求结构见 `examples/task-center-request.json`。创建任务后还会查询执行状态，并停用临时调度任务；本包安装和验证脚本不会提交真实任务或调用模型。

`config/integration.env.example` 是配置参考，不能假定 Flocks 会自动读取它。应把相应环境变量设置到项目后端或 Flocks 进程，密钥在目标机器本地填写。默认地址适用于同机部署；跨机器部署需要另外设计连通性与鉴权，不能直接把本机接口暴露到外网。

## 有意排除

- `.secret.json`、实际 `flocks.json`、`mcp_list.json`、模型/Exa/Telegram/渠道密钥。
- Telethon `.session`、聊天记录、任务数据库、定时任务实例、执行历史、生成报告和备份文件。
- `threat_intel_search_push_pipeline`、`search-supervisor-push` 和企业微信文件推送工具：它们是另一套主动推送变体，当前 AI 聚合适配器调用的是主搜索工作流。
- 无关的 MCP、技能库、其他智能体、完整虚拟环境和 Flocks WebUI 构建。

报告仍由工作流以 Markdown 数据返回；本项目的前端负责将其转换成原生 Word 标题、列表、表格与链接。无需在 Flocks 中再维护一套 Word 导出。
