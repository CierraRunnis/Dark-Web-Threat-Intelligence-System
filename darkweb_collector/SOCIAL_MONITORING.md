# 社交平台监测

## 运行边界

- 监测轮次固定每 30 分钟更新一次；启用任务时首轮立即到期。30 分钟不是初验 SLA。
- 现有 scheduler 每 60 秒运行一次 `scripts/crawl.py enqueue-due`，将到期的“任务 × 平台”投递到 `social_api` Celery 队列。
- 只采集 X/Facebook 主帖、YouTube 视频标题与简介、Telegram 公开广播频道主消息；不采集评论、字幕、语音和私密群。
- 平台 API 用于自动采集。Facebook 无 API 凭据但存在本地 storage-state 时，只读采集授权浏览器可见的公开搜索结果、页面和群组，并始终显示“覆盖受限”。已领取事件可使用授权浏览器保存 HTML 和原始截图，失败时人工上传 PNG/JPEG。
- 发布仅进入系统内通知中心，不调用企业微信、Webhook 或社交平台写操作。

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

离线测试使用 `tests/fixtures/social_platform_payloads.json`，不依赖真实平台或账号。它覆盖 30 分钟锚点、重叠轮次、四平台投递、失败游标保留、匹配/排除、去重、编辑快照、删除留痕、领取竞争、原图权限、脱敏发布和报告数据。

实网烟雾测试只在已配置上述秘密时执行，每个平台只做一次低频、只读采集与授权截图。Facebook 无合规接口权限时不宣称全平台覆盖。

## 验收前检查

```bash
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
```

确认差异中不含 `.env`、数据库、截图、`storage_state`、日志、缓存、`node_modules` 和真实平台响应，再对 `origin/main...HEAD` 新增内容做秘密扫描。
