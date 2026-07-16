# 社交平台监测

## 运行边界

- 监测轮次固定每 30 分钟更新一次；启用任务时首轮立即到期。30 分钟不是初验 SLA。
- 现有 scheduler 每 60 秒运行一次 `scripts/crawl.py enqueue-due`，将到期的“任务 × 平台”投递到 `social_api` Celery 队列。
- 只采集 X/Facebook 主帖、YouTube 视频标题与简介、Telegram 公开广播频道主消息；不采集评论、字幕、语音和私密群。
- 平台 API 用于自动采集。Facebook 无 API 凭据但存在本地 storage-state 时，只读采集授权浏览器可见的公开搜索结果、页面和群组，并始终显示“覆盖受限”。已领取事件可使用授权浏览器保存 HTML 和原始截图，失败时人工上传 PNG/JPEG。
- 发布仅进入系统内通知中心，不调用企业微信、Webhook 或社交平台写操作。

## 第一阶段免费官方接口

当前新建任务默认只选择 YouTube 和 Telegram，X、Facebook 仍保留为后续可选平台。

管理员可以在“监测配置 → 免费平台接入配置”中直接填写凭据。页面采用只写方式，保存后只显示“已配置”和凭据来源，不会把原值返回浏览器。页面保存的值默认位于当前系统用户的 `~/.config/darkweb-threat-intel/social-platform-secrets.json`；Linux 下目录权限设为 `0700`、文件权限设为 `0600`，Windows 下继承用户配置目录 ACL。可以用 `SOCIAL_PLATFORM_SECRETS_FILE` 指定其他仓库外路径。环境变量和 Codespaces secrets 的优先级高于页面配置，且不能在页面中覆盖。

### YouTube Data API

1. 在 Google Cloud 项目中启用 YouTube Data API v3，并创建 API Key。
2. 将 Key 注入 `SOCIAL_YOUTUBE_API_KEY`。
3. 关键词监测每轮合并为一次 `search.list`；按 30 分钟周期每天执行 48 次，低于默认每日 100 次搜索调用配额。
4. 重点频道不使用搜索配额。系统先读取频道的 uploads 播放列表，再用 `playlistItems.list` 获取新视频。支持频道 ID、`/channel/UC...`、`/@handle` 和 `/user/name`。

YouTube 只保存视频标题、简介、发布时间、频道和缩略图地址，不采集评论、字幕或语音。

### Telegram MTProto API

1. 在 <https://my.telegram.org> 创建应用，取得 `api_id` 和 `api_hash`。
2. 在“监测配置 → 免费平台接入配置”保存 API ID 和 API Hash。
3. 在同一页面的“页面生成 StringSession”区域填写国际格式手机号，依次完成验证码和可选的两步验证。验证码和密码只保存在当前浏览器输入框及本次请求内；生成的 StringSession 由后端直接写入私有秘密文件，不返回浏览器。

可信终端命令仍作为备用方式：

   ```bash
   python darkweb_collector/scripts/create_telegram_session.py
   ```

命令行方式完成登录后，将输出保存为 Codespaces secret `SOCIAL_TELEGRAM_SESSION`，或粘贴到页面的“已有 StringSession”字段。

后台任务不会发起交互式登录。会话失效时轮次明确失败并保留上次游标，必须重新生成会话。系统只接收公开广播频道用户名、`@username` 或 `t.me/username`；邀请链接、私密频道、群组和超级群组不会采集。全局关键词逐词搜索，重点频道则读取游标之后的新主消息，最终仍由服务端的“地域或目标 + 威胁词”规则筛选。

## 秘密与证据

以下变量必须由 Codespaces secrets 或机器本地环境注入，不得写入 Git：

```text
SOCIAL_X_BEARER_TOKEN
SOCIAL_FACEBOOK_ACCESS_TOKEN
SOCIAL_FACEBOOK_API_VERSION
SOCIAL_YOUTUBE_API_KEY
SOCIAL_TELEGRAM_API_ID
SOCIAL_TELEGRAM_API_HASH
SOCIAL_TELEGRAM_SESSION
SOCIAL_PLATFORM_SECRETS_FILE
SOCIAL_X_STORAGE_STATE
SOCIAL_FACEBOOK_STORAGE_STATE
SOCIAL_YOUTUBE_STORAGE_STATE
SOCIAL_TELEGRAM_STORAGE_STATE
```

`*_STORAGE_STATE` 是 Playwright storage-state JSON 的机器本地绝对路径，文件本身不得提交。原始截图和 HTML 默认保存在用户私有数据目录，可以用 `SOCIAL_EVIDENCE_ROOT` 指向独立私有路径。该目录不应位于仓库或 `/collector-output`。

## 本地和 Codespace 验证

```bash
python -m pip install -r darkweb_collector/requirements.txt
python -m playwright install chromium
PYTHONPATH=darkweb_collector/src python -m unittest discover -s darkweb_collector/tests -p 'test_*.py' -v
cd threat-intelligence-dashboard
npm ci
npm run build
```

离线测试使用 `tests/fixtures/social_platform_payloads.json`，不依赖真实平台或账号。它覆盖 YouTube 搜索和频道 uploads 播放列表、Telegram 非交互式会话和公开频道边界、30 分钟锚点、重叠轮次、失败游标保留、匹配/排除、去重、编辑快照、删除留痕、领取竞争、原图权限、脱敏发布和报告数据。

实网烟雾测试只在已配置上述秘密时执行，每个平台只做一次低频、只读采集与授权截图。Facebook 无合规接口权限时不宣称全平台覆盖。

## 验收前检查

```bash
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
```

确认差异中不含 `.env`、数据库、截图、`storage_state`、日志、缓存、`node_modules` 和真实平台响应，再对 `origin/main...HEAD` 新增内容做秘密扫描。
