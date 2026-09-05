import './aiAggregation.css'
import './aiAggregationTemplate.css'
import './aiAggregationSplit.css'
import { createAiAggregationApi, listFrom } from './aiAggregationApi.js'
import { normalizeSearchWindowDays, normalizeTemplateKeyword, renderTemplatePreview } from './aiAggregationTemplate.js'
import { escapeAiHtml, getAiDeliveryMeta, getAiStatusMeta, renderAiMarkdown } from './aiAggregationPresentation.js'
import {
  getAiAggregationPollDelay,
  getAiAggregationRunStatus as runStatus,
  mergeAiAggregationRun,
  shouldRefreshAiAggregationRunDetail,
} from './aiAggregationPolling.js'

const ACTIVE_POLL_MS = 2500
const profileId = (profile) => String(profile?.profile_id ?? profile?.id ?? '')
const runId = (run) => String(run?.run_id ?? run?.id ?? '')
const profileKeywords = (profile) => Array.isArray(profile?.keywords) && profile.keywords.length ? profile.keywords.map(normalizeTemplateKeyword).filter(Boolean) : (normalizeTemplateKeyword(profile?.keyword) ? [normalizeTemplateKeyword(profile.keyword)] : [])
const runKeywords = (run) => Array.isArray(run?.keywords) && run.keywords.length ? run.keywords.map(normalizeTemplateKeyword).filter(Boolean) : (normalizeTemplateKeyword(run?.keyword) ? [normalizeTemplateKeyword(run.keyword)] : [])
const keywordLabel = (value) => (value ? runKeywords(value) : []).join('、') || '—'
const markdownOf = (run) => typeof run?.report === 'string' ? run.report : String(run?.report?.markdown ?? run?.report_markdown ?? '')
const createdAt = (run) => run?.created_at ?? run?.queued_at ?? run?.requested_at
const completedAt = (run) => run?.completed_at ?? run?.finished_at ?? run?.updated_at
const formatDate = (value) => { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date) }
const canRetry = (run) => ['partial', 'failed'].includes(getAiDeliveryMeta(run?.delivery_status).key) || (run?.deliveries || []).some((item) => item.status === 'failed')

export async function hydrateAiAggregationScreen({ root, signal: parentSignal, route } = {}) {
  if (!root) return () => {}
  root.__aiAggregationDispose?.()
  const controller = new AbortController()
  const { signal } = controller
  const api = createAiAggregationApi({ signal })
  const state = { health: null, profiles: [], runs: [], currentRun: null, timer: null, pollMs: 0, polling: false, disposed: false }
  const $ = (selector, scope = root) => scope?.querySelector(selector) || null
  const text = (selector, value, scope = root) => { const node = $(selector, scope); if (node) node.textContent = value == null ? '' : String(value) }
  const on = (node, event, handler, options = {}) => node?.addEventListener(event, handler, { ...options, signal })
  const dispose = () => { if (state.disposed) return; state.disposed = true; if (state.timer) window.clearInterval(state.timer); controller.abort(); if (root.__aiAggregationDispose === dispose) delete root.__aiAggregationDispose }
  root.__aiAggregationDispose = dispose
  if (parentSignal) { if (parentSignal.aborted) { dispose(); return dispose } parentSignal.addEventListener('abort', dispose, { once: true }) }

  const toast = (message, tone = 'success') => { const node = $('[data-ai-toast]'); if (!node) return; node.className = `toast ${tone} show`; node.textContent = message; node.hidden = false; window.setTimeout(() => { if (!signal.aborted) { node.hidden = true; node.classList.remove('show') } }, 3000) }
  const showError = (reason) => { if (reason?.name === 'AbortError' || signal.aborted) return; text('[data-ai-error-message]', reason?.message || '未知错误'); const node = $('[data-ai-error]'); if (node) node.hidden = false; toast(reason?.message || '未知错误', 'error') }
  const selectedProfile = () => state.profiles.find((profile) => profileId(profile) === $('[data-ai-run-profile]')?.value) || null
  const queryProfile = () => String(route?.query?.profile || new URLSearchParams(window.location.search).get('profile') || '')
  const settingsHref = (id) => `/ai-aggregation/templates${id ? `?profile=${encodeURIComponent(id)}` : ''}`

  const updateHealth = () => {
    const status = String(state.health?.status || '').toLowerCase(); const degraded = status === 'degraded'; const offline = state.health?.ok === false || ['failed', 'error', 'unhealthy'].includes(status); const tone = offline ? 'danger' : degraded ? 'warning' : 'success'
    const badge = $('[data-ai-service-status]'); if (badge) { badge.className = `badge ${tone}`; badge.innerHTML = `<span class="status-dot ${tone}"></span>${offline ? '服务离线' : degraded ? '服务降级' : '服务正常'}`; badge.title = String(state.health?.adapter?.error || '') }
    const mode = String(state.health?.adapter?.mode || 'mock').toUpperCase(); text('[data-ai-adapter-mode]', ['LIVE', 'MOCK'].includes(mode) ? mode : '—')
  }
  const renderConcurrency = () => {
    const counts = { queued: 0, running: 0, succeeded: 0, failed: 0 }
    state.runs.forEach((run) => { const key = runStatus(run); if (key in counts) counts[key] += 1 })
    if (state.health?.runs) Object.keys(counts).forEach((key) => { const value = Number(state.health.runs[key]); if (Number.isFinite(value)) counts[key] = value })
    const limit = Math.max(1, Number(state.health?.queue?.max_concurrent_runs || 2))
    text('[data-ai-running-count]', counts.running); text('[data-ai-running-count-secondary]', counts.running); text('[data-ai-queued-count]', counts.queued); text('[data-ai-succeeded-count]', counts.succeeded); text('[data-ai-failed-count]', counts.failed); text('[data-ai-concurrency-limit]', limit)
    const meter = $('[data-ai-concurrency-meter]'); if (meter) meter.style.width = `${Math.min(100, counts.running / limit * 100)}%`
  }
  const selectProfile = (id) => {
    const profile = state.profiles.find((item) => profileId(item) === id) || state.profiles.find((item) => item.enabled !== false) || state.profiles[0] || null
    const select = $('[data-ai-run-profile]'); if (select) select.value = profileId(profile)
    const keywords = profileKeywords(profile); const days = normalizeSearchWindowDays(profile?.search_window_days); const enabled = Boolean(profile && profile.enabled !== false)
    const schedule = profile?.schedule || {}
    text('[data-ai-run-keywords-summary]', keywords.join('、') || '—'); text('[data-ai-run-days-summary]', profile ? `最近${days}天` : '—'); text('[data-ai-run-schedule-summary]', profile ? (schedule.enabled ? schedule.cron || '已启用' : '未启用') : '—'); text('[data-ai-run-preview]', profile ? renderTemplatePreview(profile.prompt_template, keywords, days) : '请先选择模板')
    const badge = $('[data-ai-run-profile-status]'); if (badge) { badge.className = `badge ${enabled ? 'success' : profile ? 'warning' : ''}`; badge.textContent = enabled ? '已启用' : profile ? '已停用' : '未选择' }
    const button = $('[data-ai-run-button]'); if (button) button.disabled = !enabled
    const link = $('[data-ai-template-settings-link]'); if (link) link.href = settingsHref(profileId(profile))
  }
  const loadProfiles = async (preferredId = queryProfile()) => {
    state.profiles = listFrom(await api.listProfiles(), ['profiles', 'items', 'results'])
    const select = $('[data-ai-run-profile]'); select?.replaceChildren()
    state.profiles.forEach((profile) => { const option = document.createElement('option'); option.value = profileId(profile); option.textContent = `${profile.name}${profile.enabled === false ? '（已停用）' : ''}`; select?.append(option) })
    if (!state.profiles.length && select) select.add(new Option('暂无可用模板', ''))
    selectProfile(preferredId)
  }
  const renderHistory = () => {
    const body = $('[data-ai-history-body]'); const table = $('[data-ai-history-table-wrap]'); const empty = $('[data-ai-history-empty]'); if (!body || !table || !empty) return
    const filter = $('[data-ai-history-filter]')?.value || ''; const rows = filter ? state.runs.filter((run) => runStatus(run) === filter) : state.runs
    body.innerHTML = rows.map((run) => { const status = getAiStatusMeta(runStatus(run)); return `<tr><td><strong>${escapeAiHtml(keywordLabel(run))}</strong><br><code>${escapeAiHtml(runId(run))}</code></td><td><span class="badge ${status.tone}">${status.label}</span></td><td>${escapeAiHtml(formatDate(createdAt(run)))}</td><td><button class="btn btn-secondary" type="button" data-ai-open-run="${escapeAiHtml(runId(run))}">查看</button></td></tr>` }).join('')
    table.hidden = !rows.length; empty.hidden = Boolean(rows.length)
  }
  const renderDeliveries = (run) => {
    const section = $('[data-ai-delivery-section]'); const list = $('[data-ai-delivery-list]'); const badge = $('[data-ai-delivery-status]'); const retry = $('[data-ai-retry-deliveries]'); if (!section || !list || !badge || !retry) return
    const items = Array.isArray(run?.deliveries) ? run.deliveries : []; const overall = getAiDeliveryMeta(run?.delivery_status); badge.className = `badge ${overall.tone}`; badge.textContent = overall.label; section.hidden = !(run?.delivery_status || items.length); retry.hidden = !canRetry(run)
    list.innerHTML = items.length ? items.map((item) => { const status = getAiDeliveryMeta(item.status); return `<div class="ai-delivery-item"><div><strong>${escapeAiHtml(item.display_name || item.target?.url || item.target?.session_id || item.type)}</strong><small>${item.type === 'wecom' ? '企业微信' : 'Callback'}</small></div><span class="badge ${status.tone}">${status.label}</span><small>${escapeAiHtml(item.last_error || '无错误记录')}</small></div>` }).join('') : '<div class="empty-state"><p>本次运行未配置投递目标。</p></div>'
  }
  const renderReport = () => {
    const run = state.currentRun; const empty = $('[data-ai-report-empty]'); const progress = $('[data-ai-report-progress]'); const failure = $('[data-ai-report-failure]'); const documentNode = $('[data-ai-report-document]'); const actions = $('[data-ai-report-actions]'); const badge = $('[data-ai-current-status]'); if (!empty || !progress || !failure || !documentNode || !actions || !badge) return
    empty.hidden = Boolean(run); progress.hidden = true; failure.hidden = true; documentNode.hidden = true; actions.hidden = true
    if (!run) { badge.textContent = '暂无任务'; return }
    const status = getAiStatusMeta(runStatus(run)); badge.className = `badge ${status.tone}`; badge.textContent = status.label
    if (['queued', 'running'].includes(status.key)) { progress.hidden = false; text('[data-ai-progress-title]', status.label); text('[data-ai-progress-description]', status.description); text('[data-ai-progress-run-id]', runId(run)); return }
    if (status.key !== 'succeeded') { failure.hidden = false; text('[data-ai-report-error]', run.error || run.error_message || '后端未返回具体错误。'); text('[data-ai-failed-run-id]', runId(run)); return }
    const markdown = markdownOf(run); if (!markdown) { failure.hidden = false; text('[data-ai-report-error]', '后端未返回报告内容。'); return }
    documentNode.hidden = false; actions.hidden = false; text('[data-ai-report-keyword]', keywordLabel(run)); text('[data-ai-report-completed-at]', formatDate(completedAt(run))); text('[data-ai-report-run-id]', runId(run)); $('[data-ai-report-markdown]').innerHTML = renderAiMarkdown(markdown); renderDeliveries(run)
  }
  const managePoll = () => { const next = getAiAggregationPollDelay(state.currentRun, ACTIVE_POLL_MS); if (!next) { if (state.timer) window.clearInterval(state.timer); state.timer = null; state.pollMs = 0; return } if (state.timer && state.pollMs === next) return; if (state.timer) window.clearInterval(state.timer); state.pollMs = next; state.timer = window.setInterval(poll, next) }
  const renderRuns = () => { state.runs.sort((a, b) => new Date(createdAt(b) || 0) - new Date(createdAt(a) || 0)); renderConcurrency(); renderHistory(); renderReport(); managePoll() }
  const loadRuns = async () => { state.runs = listFrom(await api.listRuns(), ['runs', 'items', 'results']); if (state.currentRun) state.currentRun = mergeAiAggregationRun(state.currentRun, state.runs.find((run) => runId(run) === runId(state.currentRun))); else state.currentRun = state.runs[0] || null; renderRuns() }
  const openRun = async (id, scroll = true) => { try { const detail = await api.getRun(id); const index = state.runs.findIndex((run) => runId(run) === id); if (index >= 0) state.runs[index] = mergeAiAggregationRun(state.runs[index], detail); else state.runs.unshift(detail); state.currentRun = state.runs.find((run) => runId(run) === id) || detail; renderRuns(); if (scroll) $('[data-ai-report-section]')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) } catch (reason) { showError(reason) } }
  async function poll() { if (state.polling || state.disposed) return; state.polling = true; const previousRun = state.currentRun; try { const [health] = await Promise.allSettled([api.health(), loadRuns()]); if (health.status === 'fulfilled') { state.health = health.value; updateHealth() }; if (shouldRefreshAiAggregationRunDetail(previousRun, state.currentRun)) await openRun(runId(previousRun), false) } finally { state.polling = false } }

  on($('[data-ai-run-profile]'), 'change', (event) => selectProfile(event.target.value))
  on($('[data-ai-run-form]'), 'submit', async (event) => { event.preventDefault(); const profile = selectedProfile(); if (!profile) return showError(new Error('请先选择模板。')); if (profile.enabled === false) return showError(new Error('该模板已停用。')); const button = $('[data-ai-run-button]'); button.disabled = true; text('[data-ai-run-button-label]', '正在提交…'); try { const accepted = await api.runProfile(profileId(profile)); const queued = { ...accepted, run_id: runId(accepted), keywords: profileKeywords(profile), rendered_prompt: renderTemplatePreview(profile.prompt_template, profileKeywords(profile), profile.search_window_days), analysis_status: accepted.analysis_status || accepted.status || 'queued', created_at: accepted.created_at || new Date().toISOString() }; state.runs.unshift(queued); state.currentRun = queued; renderRuns(); toast('模板任务已提交') } catch (reason) { showError(reason) } finally { button.disabled = profile.enabled === false; text('[data-ai-run-button-label]', '立即生成') } })
  on($('[data-ai-history-filter]'), 'change', renderHistory); on($('[data-ai-history-body]'), 'click', (event) => { const button = event.target.closest('[data-ai-open-run]'); if (button) void openRun(button.dataset.aiOpenRun) })
  on($('[data-ai-retry-deliveries]'), 'click', async () => { if (!canRetry(state.currentRun)) return; try { await api.retryDeliveries(runId(state.currentRun)); await openRun(runId(state.currentRun), false); toast('已重试失败投递') } catch (reason) { showError(reason) } })
  on($('[data-ai-copy-report]'), 'click', async () => { const markdown = markdownOf(state.currentRun); if (markdown) try { await navigator.clipboard.writeText(markdown); toast('报告已复制') } catch { showError(new Error('剪贴板不可用。')) } })
  on($('[data-ai-download-report]'), 'click', () => { const markdown = markdownOf(state.currentRun); if (!markdown) return; const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = `ai-intelligence-${runId(state.currentRun)}.md`; link.click(); URL.revokeObjectURL(url) })
  on($('[data-ai-download-word]'), 'click', async (event) => {
    const run = state.currentRun
    const markdown = markdownOf(run)
    const button = event.currentTarget
    if (!markdown || button.disabled) return
    button.disabled = true
    button.textContent = '正在导出…'
    try {
      const { exportAiReportWord } = await import('./aiAggregationWordExport.js')
      if (signal.aborted) return
      const date = new Date(completedAt(run))
      await exportAiReportWord({
        markdown, runId: runId(run), keywords: runKeywords(run),
        completedAt: Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }),
      })
      if (!signal.aborted) toast('Word 已导出，可在“视图 → 导航窗格”中按标题跳转')
    } catch (reason) { showError(reason) } finally {
      button.disabled = false
      button.textContent = '导出 Word'
    }
  })
  on($('[data-ai-dismiss-error]'), 'click', () => { const node = $('[data-ai-error]'); if (node) node.hidden = true }); on($('[data-ai-refresh]'), 'click', async () => { try { const currentId = profileId(selectedProfile()); const [health] = await Promise.all([api.health(), loadProfiles(currentId), loadRuns()]); state.health = health; updateHealth(); toast('数据已刷新') } catch (reason) { showError(reason) } })

  try { const [health] = await Promise.all([api.health(), loadProfiles(), loadRuns()]); state.health = health; updateHealth() } catch (reason) { showError(reason) } finally { const loading = $('[data-ai-runtime-state]'); if (loading) loading.hidden = true; if (!signal.aborted) managePoll() }
  return dispose
}
