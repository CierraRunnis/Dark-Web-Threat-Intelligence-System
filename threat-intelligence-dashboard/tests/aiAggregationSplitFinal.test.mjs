import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { escapeAiHtml, renderAiMarkdown } from '../src/prototype/aiAggregationPresentation.js'

const root = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')
const [runScreen, settingsScreen, runRuntime, settingsRuntime, apiClient, splitCss, dataRuntime, router, view] = await Promise.all([
  read('src/prototype/screens/ai-aggregation.html'), read('src/prototype/screens/ai-aggregation-templates.html'), read('src/prototype/aiAggregationRuntime.js'), read('src/prototype/aiAggregationTemplatesRuntime.js'), read('src/prototype/aiAggregationApi.js'), read('src/prototype/aiAggregationSplit.css'), read('src/prototype/dataRuntime.js'), read('src/router/index.js'), read('src/views/PrototypeScreen.vue'),
])

test('运行页只选择已保存模板并显示完整只读摘要', () => {
  for (const anchor of ['data-ai-template-settings-link', 'data-ai-run-profile', 'data-ai-run-keywords-summary', 'data-ai-run-days-summary', 'data-ai-run-schedule-summary', 'data-ai-run-preview']) assert.match(runScreen, new RegExp(anchor))
  assert.doesNotMatch(runScreen, /data-ai-profile-form|data-ai-profile-keywords|data-ai-profile-prompt/)
  assert.doesNotMatch(runScreen, /<(?:textarea|input)[^>]+data-ai-run-(?:keywords|days)(?:[\s=>])/)
  assert.match(runRuntime, /data-ai-run-schedule-summary/)
  assert.match(runRuntime, /schedule\.enabled[\s\S]*schedule\.cron[\s\S]*未启用/)
  assert.match(runRuntime, /api\.runProfile\(profileId\(profile\)\)/)
  assert.doesNotMatch(runRuntime, /api\.(?:createProfile|updateProfile|deleteProfile)\(/)
})

test('配置页独占Profile CRUD、enabled、textarea、cron和投递', () => {
  for (const anchor of ['data-ai-templates-return', 'data-ai-profile-select', 'data-ai-new-profile', 'data-ai-delete-profile', 'data-ai-save-profile', 'data-ai-profile-enabled', 'data-ai-profile-prompt', 'data-ai-profile-keywords', 'data-ai-profile-days', 'data-ai-schedule-enabled', 'data-ai-callback-url', 'data-ai-wecom-list']) assert.match(settingsScreen, new RegExp(anchor))
  assert.match(settingsScreen, /textarea[^>]+data-ai-profile-keywords/)
  assert.doesNotMatch(settingsScreen, /data-ai-toggle-profile/)
  assert.match(settingsRuntime, /enabled:\s*Boolean\(\$\('\[data-ai-profile-enabled\]'\)/)
})

test('Run POST严格发送空JSON对象且无override', () => {
  assert.match(apiClient, /runProfile:\s*\(id\).*body:\s*JSON\.stringify\(\{\}\)/)
  assert.doesNotMatch(apiClient, /runProfile:[^\n]+keywords|runProfile:[^\n]+search_window_days/)
})

test('双向profile链接使用Vue canonical routes而非原型HTML路径', () => {
  assert.match(runRuntime, /\/ai-aggregation\/templates.*profile=/s)
  assert.match(settingsRuntime, /\/ai-aggregation.*profile=/s)
  assert.doesNotMatch(runRuntime, /ai-aggregation-templates\.html/)
  assert.doesNotMatch(settingsRuntime, /ai-aggregation\.html/)
})

test('无效profile回退enabled首项，刷新保留当前模板，删除选相邻项', () => {
  assert.match(runRuntime, /find\(\(item\) => item\.enabled !== false\)/)
  assert.match(settingsRuntime, /find\(\(item\) => item\.enabled !== false\)/)
  assert.match(runRuntime, /loadProfiles\(currentId\)/)
  assert.match(settingsRuntime, /index \+ 1|index - 1/)
  assert.match(settingsRuntime, /loadProfiles\(profileId\(next\)\)/)
})

test('空Profile库直接进入明确的未保存新建态', () => {
  assert.match(settingsRuntime, /if \(!state\.profiles\.length\)/)
  assert.match(settingsRuntime, /state\.isNew = true/)
  assert.match(settingsRuntime, /新建模板|尚未保存/)
})

test('配置页dirty guard覆盖Vue route leave并随Abort清理', () => {
  assert.match(settingsRuntime, /root\.__prototypeBeforeLeave = confirmDiscard/)
  assert.match(settingsRuntime, /delete root\.__prototypeBeforeLeave/)
  assert.match(settingsRuntime, /parentSignal\.addEventListener\('abort', dispose/)
  assert.match(view, /__prototypeBeforeLeave/)
})

test('共享hydration分派两screen、传AbortSignal和route', () => {
  assert.match(dataRuntime, /hydrateAiAggregationScreen\(\{\s*root,\s*signal:[^}]+route/s)
  assert.match(dataRuntime, /hydrateAiAggregationTemplatesScreen\(\{\s*root,\s*signal:[^}]+route/s)
  assert.match(router, /\/ai-aggregation\/templates/)
})

test('API基址唯一且样式严格scoped', () => {
  assert.match(apiClient, /AI_AGGREGATION_API_BASE = '\/api\/ai-aggregation'/)
  assert.doesNotMatch(apiClient, /\/api\/v1|8766/)
  assert.match(runRuntime, /import '\.\/aiAggregationSplit\.css'/)
  assert.match(splitCss, /\.page-heading\s*\{[\s\S]*justify-content:\s*space-between/)
  assert.match(splitCss, /\.page-heading\s*>\s*\.actions\s*\{[\s\S]*justify-content:\s*flex-end[\s\S]*margin-left:\s*auto/)
  assert.match(splitCss, /\.page-ai-aggregation-templates\s+\.ai-template-toolbar\s*\{[\s\S]*display:\s*grid/)
  assert.match(settingsScreen, /class="page-ai-aggregation page-ai-aggregation-templates"/)
  assert.match(settingsRuntime, /import '\.\/aiAggregationSplit\.css'/)
  const selectors = splitCss.match(/^[^{@]+\{/gm) || []
  assert.ok(selectors.length > 0)
  assert.equal(selectors.every((selector) => selector.includes('.prototype-screen.page-ai-aggregation')), true)
})

test('Markdown内容安全转义', () => {
  assert.equal(escapeAiHtml('<script>'), '&lt;script&gt;')
  assert.doesNotMatch(renderAiMarkdown('<script>alert(1)</script>'), /<script>/)
})
