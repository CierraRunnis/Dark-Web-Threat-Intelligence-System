# 威胁情报多 Agent 系统说明文档

本文档说明 `threat_intel_search_pipeline` 在 Flocks 框架中的实际实现方式，覆盖系统定位、Agent 分工、工作流结构、数据契约、关键机制、扩展方式和落地入口。

适用对象：

- 需要理解整条威胁情报检索链路的开发同学
- 需要做交付、定时任务、渠道接入的实施同学
- 需要基于当前方案继续扩展新情报源或新报告能力的维护者

## 1. 系统定位

这个系统的目标，是把原本需要人工完成的多源威胁情报检索过程，收敛为一条固定、可重复、可降级的自动化链路：

1. 识别用户是不是在做威胁情报搜索。
2. 从用户目标中扩展多语种关键词。
3. 并发搜索暗网、Telegram、公开 Web 三类情报源。
4. 对结果做时间窗过滤、去重、降噪、风险分级。
5. 输出最终 Markdown 情报报告。

它不是一个“自由发挥的多 Agent 对话系统”，而是一个“由固定 Workflow 编排的多 Agent 检索系统”。也就是说：

- Agent 负责语义判断、轻量推理和文本生成。
- Workflow 负责固定顺序、并发、汇聚、超时和降级。
- Python 工具负责真实搜索、协议适配、结构化归一和确定性处理。

## 2. 设计原则

### 2.1 确定性优先

并发、join、超时、去重、结果合并等关键行为不依赖提示词自律，而是固化在 `workflow.json` 和 Python 节点里。

### 2.2 职责分层

- `search-supervisor` 负责识别意图并启动工作流。
- 各 `search-agent` 只负责本源搜索，不跨源调用。
- `noise-reduction-agent` 只返回噪声 ID，不负责去重和合并。
- `report-agent` 只负责把规范化结果写成报告。

### 2.3 Schema First

上下游都通过固定 JSON 结构通信，避免单个 Agent 的表达风格影响整条链路。

### 2.4 失败可降级

任何单点失败都不应该让整个系统“无结果退出”。即使某一路超时或失败，也要返回报告，并在 `source_coverage` 中显式标注状态。

## 3. 总体架构

```text
用户 / WebUI / CLI / 渠道消息
          |
          v
search-supervisor
  -> run_workflow(threat_intel_search_pipeline)
          |
          v
prepare_input
  -> expand_keywords
  -> search_darkweb   \
  -> search_telegram   > 三路并发
  -> search_web       /
  -> join_search_results
  -> reduce_noise
  -> generate_report
          |
          v
最终 Markdown 报告
```

如果走定时推送场景，则会使用 `threat_intel_search_push_pipeline`，在上述链路后追加：

```text
generate_report
  -> send_report_file
```

该节点会把报告写入文件，并通过 `send_wecom_report_file` 推送到指定会话。

## 4. 主要组件

### 4.1 主入口 Agent

文件：

- `plugins/agents/search-supervisor/agent.yaml`
- `plugins/agents/search-supervisor/prompt.md`

职责：

- 识别“搜索 xxx 相关情报”“查 xxx 泄露”“查 xxx 暗网 / TG / 威胁情报”等意图
- 从自然语言中推断时间范围、来源范围、输出语言和搜索深度
- 调用 `run_workflow(threat_intel_search_pipeline)`
- 将工作流输出的最终报告原样返回

注意：

- supervisor 不直接手工调度各子 Agent
- supervisor 不直接调用暗网、TG、Web 搜索工具
- supervisor 的职责是“入站路由 + 工作流启动”

### 4.2 六个功能 Agent

| Agent | 作用 | 工具特征 |
| --- | --- | --- |
| `multilingual-keyword-agent` | 生成目标相关关键词、别名和多语种扩展 | 只读推理，不执行搜索 |
| `darkweb-search-agent` | 执行暗网情报搜索 | 仅暴露 `darkweb_batch_search` |
| `telegram-search-agent` | 执行 Telegram 情报搜索 | 仅暴露 `telegram_batch_search` |
| `web-search-agent` | 执行公开 Web 情报搜索 | 仅暴露 `web_batch_search` / `webfetch` |
| `noise-reduction-agent` | 判断哪些候选结果是噪声 | 只返回 `noise_ids` |
| `report-agent` | 将标准化情报结果写成 Markdown 报告 | 不执行搜索 |

### 4.3 主 Workflow

文件：

- `plugins/workflows/threat_intel_search_pipeline/workflow.json`

关键配置：

- `default_max_parallel_workers = 3`
- `node_timeout_s = 1200`
- `entry_agent = search-supervisor`

主工作流固定为 8 个节点：

1. `prepare_input`
2. `expand_keywords`
3. `search_darkweb`
4. `search_telegram`
5. `search_web`
6. `join_search_results`
7. `reduce_noise`
8. `generate_report`

说明：

- `search_darkweb`、`search_telegram`、`search_web` 为并发执行
- 三路并发完成后，统一在 `join_search_results` 汇聚
- 报告一定在降噪之后生成，不允许跳过中间阶段

### 4.4 三个 Source 子 Workflow

文件：

- `plugins/workflows/darkweb_source_search/workflow.json`
- `plugins/workflows/telegram_source_search/workflow.json`
- `plugins/workflows/web_source_search/workflow.json`

子工作流结构相同：

```text
prepare_source_keywords
  -> run_source_agent
  -> normalize_source_result
```

关键配置：

- `default_max_parallel_workers = 1`
- `dispatch_mode = subagent_dedicated_python_batch`
- `source_parallel_limit = 1`

这意味着：

- 主工作流是跨源并发
- 单个源内部是串行批处理
- 不会为每个关键词再额外 spawn 一个新的搜索 Agent

### 4.5 三个底层批量工具

文件：

- `plugins/tools/api/darkweb_batch_search.handler.py`
- `plugins/tools/api/telegram_batch_search.handler.py`
- `plugins/tools/api/web_batch_search.handler.py`

职责分别为：

- `darkweb_batch_search`：调用本地暗网情报接口，按时间窗过滤并做字段归一
- `telegram_batch_search`：通过常驻 tg-search MCP 做全局搜索，由该服务独占 Telethon session，并做频道级与消息级噪声过滤
- `web_batch_search`：基于 Exa 风格的公开 Web 语义搜索，做双语查询、重试、时间窗与域名过滤

## 5. 端到端执行流程

### 5.1 输入归一化：`prepare_input`

该节点负责把自然语言搜索请求转成结构化参数。

默认输出包括：

```json
{
  "query": "搜索能源行业相关情报，近一周，只查暗网和 TG",
  "search_window_days": 7,
  "report_language": "zh-CN",
  "keyword_languages": ["zh-CN", "en", "ru", "fa-IR"],
  "timeout_seconds": 1200,
  "include_sources": ["darkweb", "telegram"],
  "limit": 50,
  "web_limit": 50,
  "darkweb_limit": 50,
  "inferred_depth": "normal"
}
```

它会自动推断：

- 时间范围：如“今天”“近两天”“最近一周”“近半月”“今年”
- 来源范围：如“只查暗网”“暗网和 TG”“公开 Web”“全网综合”
- 报告语言：如“用英文输出”
- 关键词语种：默认 `zh-CN / en / ru / fa-IR`
- 搜索深度：如“快速”“深入”

### 5.2 关键词扩展：`expand_keywords`

该节点同步调用 `multilingual-keyword-agent`，输出目标相关的多语种关键词集合。

关键词要求不是简单翻译，而是围绕目标做扩展，例如：

- 公司：别名、品牌、子公司、产品名、域名
- 行业：细分子领域
- 国家：国家名本身及常见表达
- 漏洞 / 攻击组织 / 恶意软件：原文保留 + 常见别称

如果关键词扩展失败，系统会回退到保守兜底：

- 只使用原始 `query`
- 所有语种字段填同一字符串
- 整体流程继续执行

### 5.3 三路搜索：`search_darkweb` / `search_telegram` / `search_web`

三路在主工作流中并发运行，每一路都先通过子工作流做：

1. 关键词整理与去重
2. 优先级截断，最多保留 30 个关键词
3. 调用对应 source agent
4. 规范化结构
5. 二次时间窗复核

其中：

- 主查询词始终作为最高优先级关键词保留
- `search_intent` 不匹配当前源的关键词会被过滤掉
- 未启用的情报源会直接返回 `not_provided`

### 5.4 汇聚：`join_search_results`

这个节点把三路结果统一整理为 `results_by_source`。

如果某一路在预期范围内却没有按时返回，系统不会抛出整体错误，而是构造一个标准 fallback：

```json
{
  "source": "telegram",
  "status": "timeout",
  "results": [],
  "source_coverage": {
    "telegram": "timeout"
  }
}
```

### 5.5 降噪与去重：`reduce_noise`

这是整条链路里最关键的治理节点，采用“Python 确定性处理 + LLM 轻判定”的混合模式。

处理顺序如下：

1. 把三路结果摊平成统一事件列表
2. 先用 Python 基于 URL 做跨源去重
3. 只把精简后的候选项交给 `noise-reduction-agent`
4. `noise-reduction-agent` 只返回 `noise_ids`
5. Python 再负责事件重建、证据合并、风险级别推断、置信度说明

这里的职责边界非常明确：

- LLM 不负责 dedup
- LLM 不负责事件合并
- LLM 不负责风险聚合
- LLM 只做“这条是不是噪声”的轻判断

这样能显著降低幻觉对结果结构的破坏。

### 5.6 报告生成：`generate_report`

该节点把 `noise_result` 序列化后同步交给 `report-agent`，输出最终 Markdown 报告。

如果 `report-agent` 未返回可用 Markdown，系统会返回一个兜底报告，而不是空结果。

## 6. 数据契约

### 6.1 主 Workflow 输入

```json
{
  "workflow": "threat_intel_search_pipeline",
  "inputs": {
    "query": "搜索某公司相关情报",
    "search_window_days": 30,
    "report_language": "zh-CN",
    "keyword_languages": ["zh-CN", "en", "ru", "fa-IR"],
    "timeout_seconds": 1200,
    "include_sources": ["darkweb", "telegram", "web"],
    "limit_per_source": 50
  }
}
```

### 6.2 关键词扩展输出

```json
{
  "target": "某公司",
  "target_type": "company",
  "keywords": [
    {
      "canonical": "CompanyName",
      "type": "target",
      "languages": {
        "zh-CN": ["某公司"],
        "en": ["CompanyName"],
        "ru": ["Компания"],
        "fa-IR": ["نام شرکت"]
      },
      "search_intent": "all",
      "priority": "high",
      "reason": "目标主体主关键词"
    }
  ]
}
```

### 6.3 单源结果输出

```json
{
  "source": "darkweb",
  "status": "completed",
  "results": [
    {
      "source": "darkweb",
      "keyword": "CompanyName",
      "title": "Leaked data related to CompanyName",
      "url": "https://example.com",
      "time": "2026-06-01",
      "summary": "short summary",
      "evidence": "category=data_leak; severity=high",
      "confidence": "high",
      "raw": {}
    }
  ],
  "source_coverage": {
    "darkweb": "completed"
  }
}
```

支持的状态值：

- `completed`
- `no_results`
- `partial`
- `timeout`
- `failed`
- `not_provided`

### 6.4 降噪输出

```json
{
  "deduped_events": [],
  "source_coverage": {
    "darkweb": "completed",
    "telegram": "partial",
    "web": "completed"
  },
  "risk_level": "high",
  "confidence_reason": "共 5 条事件经噪音过滤与 URL 去重后保留",
  "discarded_items": [],
  "notes": []
}
```

### 6.5 最终报告输出

最终输出为 Markdown，主要包含以下部分：

1. 摘要
2. 关键发现
3. 时间线
4. 来源分布
5. 高风险线索
6. 待验证项

## 7. 关键机制

### 7.1 并发模型

- 主工作流三路并发，整体耗时近似取三路最大值
- 单源内部串行，避免同一后端被并发打爆
- Telegram 工具内部还额外有全局锁，防止同一会话并发导致 session 失效

### 7.2 时间窗双重约束

时间窗不是只在提示词里说一下，而是有两层约束：

1. 搜索工具本身按 `search_window_days` 限制结果
2. `normalize_source_result` 再次根据时间字段和文本内容复核

没有可解析日期的结果会被丢弃，以降低陈旧情报和幻觉数据混入的概率。

### 7.3 去重与降噪

- URL 相同的结果优先视为同一事件
- 同一事件在多个源命中时会合并证据
- LLM 只判定是否噪声，不参与确定性合并
- Telegram 和 Web 路各自还有独立噪声过滤策略

### 7.4 容错与降级

当前链路重点保障的是“有状态返回”，而不是“全成功才返回”。

典型降级场景：

- 关键词扩展失败：回退为原查询词继续执行
- 某一路搜索超时：该源返回 `timeout`，其余源继续
- 降噪 Agent 失败：保留全部非重复事件
- 报告 Agent 失败：返回最小可用兜底报告

### 7.5 推送扩展

如果需要用于定时任务或群消息分发，可以直接使用：

- `plugins/workflows/threat_intel_search_push_pipeline/workflow.json`
- `plugins/agents/search-supervisor-push/agent.yaml`

这套变体会复用原搜索链路，只在最后多一步发送报告文件，不需要复制整套搜索逻辑。

## 8. 目录映射

| 类型 | 路径 |
| --- | --- |
| 主工作流 | `plugins/workflows/threat_intel_search_pipeline/workflow.json` |
| 推送工作流 | `plugins/workflows/threat_intel_search_push_pipeline/workflow.json` |
| 暗网子工作流 | `plugins/workflows/darkweb_source_search/workflow.json` |
| Telegram 子工作流 | `plugins/workflows/telegram_source_search/workflow.json` |
| Web 子工作流 | `plugins/workflows/web_source_search/workflow.json` |
| 搜索主管 | `plugins/agents/search-supervisor/` |
| 推送主管 | `plugins/agents/search-supervisor-push/` |
| 关键词 Agent | `plugins/agents/multilingual-keyword-agent/` |
| 暗网 Agent | `plugins/agents/darkweb-search-agent/` |
| Telegram Agent | `plugins/agents/telegram-search-agent/` |
| Web Agent | `plugins/agents/web-search-agent/` |
| 降噪 Agent | `plugins/agents/noise-reduction-agent/` |
| 报告 Agent | `plugins/agents/report-agent/` |
| 暗网工具 | `plugins/tools/api/darkweb_batch_search.handler.py` |
| Telegram 工具 | `plugins/tools/api/telegram_batch_search.handler.py` |
| Web 工具 | `plugins/tools/api/web_batch_search.handler.py` |

## 9. 典型调用方式

### 9.1 用户自然语言触发

```text
搜索某制造业企业最近一周的相关情报，只查暗网和 TG，快速输出中文报告
```

### 9.2 程序化调用

```json
{
  "workflow": "threat_intel_search_pipeline",
  "inputs": {
    "query": "搜索某制造业企业最近一周的相关情报，只查暗网和 TG",
    "search_window_days": 7,
    "report_language": "zh-CN",
    "keyword_languages": ["zh-CN", "en", "ru", "fa-IR"],
    "timeout_seconds": 600,
    "include_sources": ["darkweb", "telegram"],
    "limit_per_source": 20
  }
}
```

## 10. 扩展建议

当前架构非常适合按“新增一个源 = 新增一套固定组件”的方式扩展。

扩展一个新情报源时，建议按以下顺序进行：

1. 新增 `<source>_batch_search.handler.py`
2. 新增 `<source>-search-agent`
3. 新增 `<source>_source_search/workflow.json`
4. 在主工作流中增加 `search_<source>` 节点
5. 在 `prepare_input` 中补充来源别名映射
6. 在 `join_search_results` 和报告模板中补充新源状态展示

## 11. 当前已知限制

### 11.1 单进程调度

当前系统仍以单进程内 Workflow 调度为主。如果未来需要横向扩展，后台任务状态和 Session 状态需要进一步外置。

### 11.2 Web 多语种覆盖有限

Web 路更偏中文和英文语义搜索，俄语和波斯语覆盖相对弱，因此这两类语言更多依赖暗网和 Telegram 路补齐。

### 11.3 关键词扩展规模需要持续治理

行业类目标天然容易膨胀出很多子关键词，虽然当前有 `MAX_KEYWORDS = 30` 的限制，但后续仍建议做更细的优先级配额控制。

### 11.4 Telegram 会话稳定性依赖外部环境

Telegram 搜索依赖常驻 `tg-search` MCP（默认 `http://127.0.0.1:3333/mcp`）及其独占的 Telethon 会话；若授权失效，应先停止该服务，再通过 `relogin.bat` 重新登录后重启。

## 12. 总结

这套威胁情报多 Agent 系统的核心价值，不在于“Agent 数量多”，而在于把多 Agent 能力装进了一条固定、可观测、可降级、可扩展的工作流里。

如果把它看成一句话，可以概括为：

**Supervisor 负责入口，Workflow 负责编排，Search Agent 负责取数，Python 负责确定性治理，Report Agent 负责最终表达。**
