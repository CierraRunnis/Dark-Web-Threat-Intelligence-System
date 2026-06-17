# 代码监测误报分类与压制策略手册

## 1. 目的与适用范围

本文档用于系统化整理当前项目“代码监测”模块中的误报类型、成因、压制策略、判定矩阵以及业界可借鉴方案，重点服务于“围绕企业进行代码泄露监测”的场景。

适用对象：

- 代码监测规则设计人员
- 平台运营与人工复核人员
- 需要优化企业相关代码泄露命中准确率的开发人员

本文聚焦的是：

- 如何区分“提到企业”和“企业泄露”
- 如何降低品牌词、邮箱、变量名、种子数据、股票/证券上下文带来的误报
- 如何引入行业成熟做法（有效性验证、allowlist、baseline、上下文压制、自动忽略）指导项目演进

---

## 2. 当前项目误报问题总览

当前项目的核心问题，不是“敏感规则不够多”，而是“企业相关性”和“泄露风险”混在一起计算。

现象主要表现为：

1. 命中企业名、品牌词、域名后，容易直接进入高风险评分路径。
2. 邮箱域名（如 `@catl.com`）经常被当成高风险信号，但很多场景只是联系人、供应商、测试数据或演示样本。
3. `token`、`password`、`api_key` 这类变量名、参数名、函数名会被误识别为真实凭据。
4. 股票、证券、研报、行情分析代码大量提到企业全称或品牌名，但本质上只是公开市场数据处理。
5. 种子数据、demo、sample、测试仓库中的企业名、企业邮箱、假密码、`localhost` 连接串，会被误判成真实泄露。
6. 同一类误报没有稳定的“压制分类”，导致人工复核经验无法沉淀。

从当前项目样例看，至少出现过以下典型误报：

- 证券代码映射：`宁德时代 -> 300750.SZ`
- 联系人/供应商邮箱：`ligang@catl.com`、`info@catl.com`
- 登录流程变量：`token = access_token`、`password = user_input`
- 种子数据：`seed_demo_data.py`
- 本地数据库串：`jdbc:postgresql://localhost:5432/...`
- 本地 Redis：`redis://localhost:6379/0`
- 正常配置流：`config_flow.py`
- 仓库名/路径名包含短品牌词：`catlink`、`scatl`

---

## 3. 分层判定原则

企业代码监测建议采用四层模型，而不是单层“检索词命中 + 敏感规则命中”模型。

### 3.1 第一层：企业相关性

先判断“这段代码是否真的和目标企业相关”。

企业锚点建议分级：

- A 类强锚点
  - 企业全称
  - 企业主域名
  - 企业邮箱域名
  - 企业子域名
- B 类中锚点
  - 人工维护品牌别名
  - 英文简称
- C 类弱锚点
  - 短品牌词
  - 高歧义缩写

判定原则：

- 只有 A/B/C 锚点成立，才进入企业风险评分。
- 短词（如 `catl`）不能单靠 substring 判企业命中。
- 弱锚点必须和强锚点、企业系统词、邮箱域名、子域名等共现才生效。

### 3.2 第二层：上下文意图

企业相关成立后，再判断代码出现企业名的语境。

建议把上下文分成：

- 泄露/接入语境
  - 登录
  - 连接
  - 调用
  - 鉴权
  - SDK/API 客户端
- 公开信息语境
  - 股票
  - ticker
  - symbol
  - 行情
  - 证券
  - 财报
  - 研报
  - 新闻
- 测试/演示语境
  - seed
  - demo
  - sample
  - faker
  - test
  - password123
  - hashedPassword

### 3.3 第三层：泄露证据

只有企业相关性成立且上下文不是明显“公开信息/测试样本”，才进一步判断是否有真实泄露证据：

- 硬编码 token / AK/SK / secret / 私钥
- 企业数据库连接串
- 内网地址
- Redis / MQ / VPN / SSO / Zabbix / 企业 API
- `login(...)`、`connect(...)`、`requests.post(...)`、`zapi.login(...)`

### 3.4 第四层：有效性与优先级

最后判断是否具备“真实可利用性”：

- 是字面量还是变量名？
- 是真实连接还是 `localhost`？
- 是演示样本还是真实业务系统？
- 是假值、测试值，还是高熵/格式符合真实凭据？

---

## 4. 误报分类表 + 压制策略表

下表给出项目内最常见的误报类型、触发成因、判定依据以及建议压制策略。

| 编号 | 误报类型 | 典型示例 | 误报成因 | 推荐压制策略 | 风险结论默认值 |
|---|---|---|---|---|---|
| 1 | 企业提及但非泄露 | 企业名出现在普通业务代码里 | 只说明“相关”，不说明“泄露” | 企业相关性和泄露风险解耦；企业名不直接提权 | 低危或仅线索 |
| 2 | 股票/证券/研报/行情类 | `宁德时代 -> 300750.SZ` | 企业名出现在公开证券语义中 | 命中 `stock/ticker/symbol/A-share/行情/证券/finance/news/研报` 时强制降权 | 低危 |
| 3 | 邮箱命中但无凭据 | `ligang@catl.com` | 只是联系人、供应商、目录信息 | 邮箱只作企业锚点；无凭据、无访问能力时不提到高危 | 中危以下 |
| 4 | 企业邮箱在种子数据中 | `seed_demo_data.py` 中 `info@catl.com` | 测试或初始化样本 | 命中 `seed/demo/sample/faker/test` 时整体降权；邮箱单独不提权 | 低危 |
| 5 | 变量名误报 | `token = access_token` | 只是变量传递，不是泄露值 | 区分变量名与字面量；右值是变量/函数调用时降权 | 低危 |
| 6 | 认证逻辑误报 | `password = user_input`、`create_access_token(...)` | 正常登录流程 | 无企业域名/企业系统 URL/真实凭据时，压到中低危 | 低危或中危 |
| 7 | 哈希/加密误报 | `hashedPassword`、`bcrypt.hash(...)` | 命中 password，但不是明文泄露 | 哈希/加密动作单独降权 | 低危 |
| 8 | 本地默认配置误报 | `redis://localhost:6379/0` | 开发默认值 | `localhost/127.0.0.1` 一律降权，不按真实基础设施算 | 低危 |
| 9 | 本地数据库串误报 | `jdbc:postgresql://localhost:5432/...` | 本地开发连接 | 非企业域名、非生产 IP、`localhost` 场景直接压制 | 低危 |
| 10 | README/教程/文档误报 | `.md`、安装说明 | 示例值、演示配置 | 文档类路径降权；需要真实字面量 + 企业锚点才升级 | 低危 |
| 11 | 日志/报错/注释误报 | `Incorrect Password`、`token expired` | 只是说明文本 | 提示语、注释语义不计入凭据命中 | 低危 |
| 12 | 仓库名/路径名子串误报 | `catlink`、`scatl` | 短品牌词 substring 命中 | 短品牌词必须采用单词边界匹配；仅路径命中不成立企业命中 | 低危 |
| 13 | 演示账号/假密码误报 | `password123`、`test@example.com` | 常见测试样例 | 建立测试值/示例值 stopword 集合 | 低危 |
| 14 | 公开客户/供应商名录误报 | `CATL supplierContact` | 是公开业务名录，不是泄露 | 联系方式/名录类仅保留为线索，不提高危 | 中危以下 |
| 15 | 公共 API 示例代码误报 | `api_key = get_api_key()` | API 封装代码，不是泄露值 | 函数返回值、环境变量读取降权 | 中危以下 |
| 16 | 通用高熵串误报 | 随机哈希、ID、签名串 | 长字符串看起来像 secret | 引入熵值 + 上下文 + 命名联合判断，单靠长度不成立 | 中危以下 |
| 17 | 临时云凭据但与目标企业无关 | AWS token 中碰巧有 `catl` 字符 | 凭据本身危险，但不是该企业泄露 | 企业监测池中压制；可另放“通用敏感泄露池” | 非企业事件 |
| 18 | Fork/镜像重复误报 | 同一段问题代码出现在多个 fork | 噪声放大 | 增加内容指纹与源头聚合 | 同源聚合 |
| 19 | 配置流/表单输入误报 | Home Assistant config flow | 命中 password 但只是用户输入字段 | 表单输入、配置流、schema 定义降权 | 低危 |
| 20 | 企业名 + 公开市场上下文 + 凭据样变量 | 股票查询代码里 `api_key`、企业名共现 | 企业相关成立，但并非企业内部泄露 | “公开市场/证券”上下文优先降权，覆盖普通敏感词加分 | 中危以下 |

---

## 5. 为什么“同样命中邮箱，等级还不一样”

同样命中企业邮箱域名，之所以有些是高危、有些是中危，通常是因为邮箱只是企业锚点的一种，最终等级还会叠加以下因素：

1. 企业锚点强度
   - `@catl.com`
   - `*.catl.com`
   - 企业全称
   - 企业系统词（如 `zabbix`、`eicc`）

2. 是否有真实敏感规则命中
   - `token`
   - `AK/SK`
   - `db_url`
   - `private_key`

3. 是否有系统访问能力
   - `login(...)`
   - `api_token`
   - `requests.post(...)`
   - `connect(...)`

4. 文件类型
   - `.env`、配置文件比普通源码更高

5. 是否被识别成演示/测试/本地化上下文
   - `seed`
   - `demo`
   - `localhost`
   - `password123`

因此：

- `邮箱 + 无凭据 + 演示数据` 更适合中低危
- `邮箱/域名 + 硬编码凭据 + 系统访问调用` 才应该高危

---

## 6. 项目建议的压制优先级

如果要按收益最大化排序，建议先做以下四类压制：

### 第一优先级：短品牌词误报压制

适用：

- `catl`
- `dbs`
- 其他长度短、歧义高的品牌词/简称

策略：

- 默认不按 substring 直接算企业命中
- 要求：
  - 单词边界匹配，或
  - 与企业域名、邮箱域名、子域名、系统词共现

### 第二优先级：公开证券/金融信息压制

适用：

- 股票代码映射
- 行情分析
- 财经新闻
- 研报解析

策略：

- 识别并压制这些上下文词：
  - `stock`
  - `ticker`
  - `symbol`
  - `A-share`
  - `finance`
  - `market`
  - `news`
  - `research`
  - `研报`
  - `证券`
  - `行情`

### 第三优先级：种子/演示/测试数据压制

适用：

- `seed_demo_data.py`
- `db_init.py`
- `sample`
- `faker`
- `test`

策略：

- 文件名、目录名、代码上下文出现这些词时整体降权
- `password123`、`hashedPassword`、`localhost` 作为强负面信号

### 第四优先级：变量名 vs 字面量凭据区分

适用：

- `token = access_token`
- `api_key = _get_api_key()`
- `password = user_input`

策略：

- 变量传递、函数返回、环境变量读取不应按真实凭据提权
- 真正要提权的是：
  - 硬编码字面量
  - 看起来可直接使用的连接串、秘钥、token

---

## 7. 高危提权矩阵（企业中心化）

### 7.1 直接高危的推荐条件

满足以下任一组合，可直接高危：

1. 企业域名/子域名/邮箱域名 + 硬编码 token/secret/AK/SK/私钥
2. 企业系统 URL + 凭据 + 登录/连接/调用动作
3. 企业锚点 + 非本地数据库连接串 + 明显接入代码
4. 企业锚点 + 凭据字面量 + 监控/运维/SSO/VPN/内部 API 调用

### 7.2 只应中危的推荐条件

1. 企业邮箱/域名命中，但没有真实凭据
2. 企业锚点成立，但只是联系人、供应商、目录数据
3. 企业锚点 + 函数式/变量式 token/password，不是字面量
4. 企业锚点 + `localhost`、本地 Redis、本地数据库

### 7.3 只应低危或剔除的推荐条件

1. 只有短品牌词 substring 命中
2. 股票/证券/行情上下文
3. 种子/测试/演示数据
4. 文档/教程/README 示例值

---

## 8. 业界相关方案与项目可借鉴点

下面是主流秘密扫描/泄露检测工具中，和误报抑制直接相关的成熟机制。

### 8.1 GitHub Secret Scanning

相关资料：

- [Supported secret scanning patterns](https://docs.github.com/en/code-security/reference/secret-security/supported-secret-scanning-patterns)
- [Secret scanning detection scope](https://docs.github.com/en/code-security/reference/secret-security/secret-scanning-detection-scope)
- [Defining custom patterns for secret scanning](https://docs.github.com/en/code-security/how-tos/secure-your-secrets/customize-leak-detection/defining-custom-patterns-for-secret-scanning)
- [Responsible detection of generic secrets with Copilot secret scanning](https://docs.github.com/code-security/secret-scanning/about-the-detection-of-generic-secrets-with-secret-scanning)

可借鉴点：

- GitHub 区分“已知 provider 模式”和“generic 模式”。
- 通用 generic secrets 的误报率更高，因此需要更慎重。
- GitHub 明确指出：**generic/non-provider 模式通常没有有效性校验**。
- GitHub 支持自定义 pattern，但前提是你自己承担 precision/recall 平衡。

对本项目的启发：

- 你的“企业词监测”本质上更像 generic matching，不应该天然高置信。
- 企业监测必须额外叠加“企业锚点 + 泄露证据 + 上下文”。

### 8.2 Yelp detect-secrets

相关资料：

- [Yelp/detect-secrets README](https://github.com/Yelp/detect-secrets)
- [detect-secrets design](https://github.com/Yelp/detect-secrets/blob/master/docs/design.md)
- [detect-secrets plugins](https://github.com/Yelp/detect-secrets/blob/master/docs/plugins.md)
- [detect-secrets filters](https://github.com/Yelp/detect-secrets/blob/master/docs/filters.md)

可借鉴点：

- detect-secrets 的核心思想是：**plugins 负责发现，filters 负责压制误报**。
- baseline 机制允许你记录和豁免已知误报/遗留结果。
- 工具本身就假设“高召回”之后需要大量过滤与人工审核。

对本项目的启发：

- 代码监测应明确拆成：
  - 发现规则
  - 压制过滤器
  - 人工复核回写
- 需要引入“误报基线”或“已知误报画像”，否则运营经验无法沉淀。

### 8.3 Gitleaks

相关资料：

- [Gitleaks README](https://github.com/gitleaks/gitleaks)
- [gitleaks allowlist implementation](https://github.com/gitleaks/gitleaks/blob/master/config/allowlist.go)
- [default gitleaks config](https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml)
- [detect engine allowlist and entropy behavior](https://github.com/gitleaks/gitleaks/blob/master/detect/detect.go)

可借鉴点：

- Gitleaks 支持：
  - global allowlist
  - per-rule allowlist
  - stopwords
  - path allowlists
  - entropy threshold
- 它明确支持“路径级别压制”和“关键词级别压制”。

对本项目的启发：

- 可以建立企业监测的：
  - 全局压制词
  - 规则级压制词
  - 文件路径压制
  - 误报 stopwords
- 尤其适合压制：
  - `seed`
  - `demo`
  - `sample`
  - `README`
  - `test`

### 8.4 TruffleHog

相关资料：

- [How TruffleHog Verifies Secrets](https://trufflesecurity.com/blog/how-trufflehog-verifies-secrets)
- [TruffleHog terminology](https://docs.trufflesecurity.com/terminology)
- [TruffleHog custom detectors](https://docs.trufflesecurity.com/custom-detectors)

可借鉴点：

- TruffleHog 的核心优势是 **verification**。
- 它把“live secret”与“invalid/false positive”严格区分。
- 自定义 detector 时也强调 entropy threshold 和验证逻辑的配合。

对本项目的启发：

- 对企业代码监测来说，真正高危的关键不是“长得像”，而是“像且可用”。
- `GPU_Monitor` 之所以高危，不只是 token，而是：
  - 企业子域名
  - token 字面量
  - `zapi.login(...)`
  - 这就接近“可利用能力”

### 8.5 GitGuardian

相关资料：

- [GitGuardian FAQ](https://docs.gitguardian.com/secrets-detection/secrets-detection-engine/frequently_asked_questions)
- [Pre-Validators and Post-Validators](https://docs.gitguardian.com/secrets-detection/secrets-detection-engine/validation)
- [Auto-ignore false positives](https://docs.gitguardian.com/platform/automate-with-playbooks/available-playbooks)
- [Investigate incidents](https://docs.gitguardian.com/internal-monitoring/remediate/investigate-incidents)
- [Public remediation overview](https://docs.gitguardian.com/public-monitoring/remediate/remediation-overview)

可借鉴点：

- GitGuardian 明确区分：
  - pre-validators
  - post-validators
  - validity checks
  - ML-based false positive remover
- 它还提供自动忽略 false positive 的 playbook。
- 公开材料里还有“在外部出现 10 次以上的秘密更可能是假阳性/公共样本”的思路。

对本项目的启发：

- 企业监测可引入：
  - 预过滤器：文件名、路径、上下文白名单
  - 后过滤器：企业相关性、演示/种子/证券语义压制
  - 自动忽略：人工确认为误报后进入本地基线
  - 聚合去重：同一内容在多个 fork 重复出现时不重复算高危

---

## 9. 推荐的项目实现策略（策略级，不限定代码细节）

### 9.1 必须保留的核心原则

- 企业相关性不是风险本身
- 企业邮箱不是高危本身
- 短品牌词不是强企业锚点
- 高危应更多由“可利用性”决定

### 9.2 必须新增的压制能力

1. 短词保护
2. 证券/金融上下文压制
3. 种子/测试/演示上下文压制
4. 变量名 vs 字面量凭据区分
5. 本地开发配置压制
6. 文档/README/教程压制
7. 同源内容聚合

### 9.3 必须新增的解释能力

详情页必须能解释：

- 为什么认定它和企业相关
- 为什么认为它高危/中危
- 为什么只是线索而不是泄露
- 为什么虽然命中邮箱，但仍然被压制

---

## 10. 建议的运营闭环

为了让误报压制长期有效，建议人工复核时必须打上误报标签。

推荐误报标签：

- `公开证券信息`
- `联系人/供应商邮箱`
- `变量名误命中`
- `登录流程/认证逻辑`
- `演示/种子数据`
- `本地开发配置`
- `README/文档示例`
- `第三方无关凭据`
- `重复镜像/Fork`

后续可据此生成：

- 路径白名单
- 上下文 stopwords
- 企业负例画像
- 自动忽略规则

---

## 11. 对当前项目最有价值的下一步

如果按收益排序，最值得优先落地的是：

1. `catl` 等短品牌词的单独 substring 命中一律降级
2. 股票/证券/研报类语境压制
3. 演示/种子/测试数据压制
4. 纯邮箱命中默认不高危
5. “企业锚点 + 凭据 + 系统访问能力”才直接高危

---

## 12. 结论

当前项目误报的根源，不是规则少，而是：

- 把企业提及误当成企业泄露
- 把敏感词误当成真实凭据
- 把相关性误当成可利用性

要想从根上提准确率，必须把判定流程稳定拆成：

1. 企业相关性
2. 上下文意图
3. 泄露证据
4. 可利用性
5. 误报基线与自动忽略

这也是 GitHub Secret Scanning、detect-secrets、Gitleaks、TruffleHog、GitGuardian 这类成熟方案的共同方向：  
**先发现，再过滤，再验证，再沉淀误报经验。**

