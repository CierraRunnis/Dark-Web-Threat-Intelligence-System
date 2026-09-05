import './aiAggregation.css'
import './aiAggregationTemplate.css'
import './aiAggregationSplit.css'
import { createAiAggregationApi, listFrom } from './aiAggregationApi.js'
import {
  DEFAULT_AI_PROMPT_TEMPLATE, DEFAULT_SEARCH_WINDOW_DAYS, MAX_SEARCH_WINDOW_DAYS,
  MAX_TEMPLATE_KEYWORDS, hasRequiredPlaceholders, keywordsToTextarea,
  normalizeSearchWindowDays, normalizeTemplateKeyword, parseKeywordLines, renderTemplatePreview,
} from './aiAggregationTemplate.js'
import { escapeAiHtml, isFivePartCron } from './aiAggregationPresentation.js'

const profileId = (profile) => String(profile?.profile_id ?? profile?.id ?? '')
const profileKeywords = (profile) => Array.isArray(profile?.keywords) && profile.keywords.length ? profile.keywords.map(normalizeTemplateKeyword).filter(Boolean) : (normalizeTemplateKeyword(profile?.keyword) ? [normalizeTemplateKeyword(profile.keyword)] : [])

export async function hydrateAiAggregationTemplatesScreen({ root, signal: parentSignal, route } = {}) {
  if (!root) return () => {}
  root.__aiAggregationTemplatesDispose?.()
  const controller = new AbortController()
  const { signal } = controller
  const api = createAiAggregationApi({ signal })
  const state = { profiles: [], activeProfile: null, isNew: false, dirty: false, disposed: false }
  const $ = (selector, scope = root) => scope?.querySelector(selector) || null
  const $$ = (selector, scope = root) => [...(scope?.querySelectorAll(selector) || [])]
  const text = (selector, value) => { const node = $(selector); if (node) node.textContent = value == null ? '' : String(value) }
  const on = (node, event, handler, options = {}) => node?.addEventListener(event, handler, { ...options, signal })
  const dispose = () => { if (state.disposed) return; state.disposed = true; controller.abort(); delete root.__prototypeBeforeLeave; if (root.__aiAggregationTemplatesDispose === dispose) delete root.__aiAggregationTemplatesDispose }
  root.__aiAggregationTemplatesDispose = dispose
  if (parentSignal) { if (parentSignal.aborted) { dispose(); return dispose } parentSignal.addEventListener('abort', dispose, { once: true }) }

  const toast = (message, tone = 'success') => { const node = $('[data-ai-toast]'); if (!node) return; node.className = `toast ${tone} show`; node.textContent = message; node.hidden = false; window.setTimeout(() => { if (!signal.aborted) { node.hidden = true; node.classList.remove('show') } }, 3000) }
  const showError = (reason) => { if (reason?.name === 'AbortError' || signal.aborted) return; const message = reason?.message || '未知错误'; text('[data-ai-error-message]', message); const node = $('[data-ai-error]'); if (node) node.hidden = false; toast(message, 'error') }
  const markDirty = () => { state.dirty = true; text('[data-ai-save-state]', '有未保存的修改') }
  const confirmDiscard = () => { if (!state.dirty) return true; if (!window.confirm('当前模板有未保存的修改，确定放弃吗？')) return false; state.dirty = false; return true }
  root.__prototypeBeforeLeave = confirmDiscard
  on(window, 'beforeunload', (event) => { if (!state.dirty) return; event.preventDefault(); event.returnValue = '' })
  on(root, 'click', (event) => { const link = event.target.closest('a[href]'); if (link && !confirmDiscard()) { event.preventDefault(); event.stopImmediatePropagation() } }, { capture: true })

  const queryProfile = () => String(route?.query?.profile || new URLSearchParams(window.location.search).get('profile') || '')
  const currentValue = () => state.isNew ? '__new__' : profileId(state.activeProfile)
  const updateReturnLink = () => { const link = $('[data-ai-templates-return]'); const id = profileId(state.activeProfile); if (link) link.href = `/ai-aggregation${id ? `?profile=${encodeURIComponent(id)}` : ''}` }
  const requireDays = (value) => { const days = Number(value); if (!Number.isInteger(days) || days < 1 || days > MAX_SEARCH_WINDOW_DAYS) throw new Error(`默认时间必须是1–${MAX_SEARCH_WINDOW_DAYS}的整数。`); return days }
  const requireKeywords = (value) => { const keywords = parseKeywordLines(value, { maxItems: MAX_TEMPLATE_KEYWORDS + 1 }); if (!keywords.length) throw new Error('至少填写一个关键词。'); if (keywords.length > MAX_TEMPLATE_KEYWORDS) throw new Error(`关键词最多${MAX_TEMPLATE_KEYWORDS}个。`); if (keywords.some((item) => item.length > 128)) throw new Error('每个关键词最多128个字符。'); return keywords }
  const toggleSchedule = (enabled) => $$('[data-ai-cron], [data-ai-timezone]').forEach((node) => { node.disabled = !enabled })
  const toggleCallback = (enabled) => { const node = $('[data-ai-callback-url]'); if (node) node.disabled = !enabled }
  const updatePreview = () => text('[data-ai-profile-preview]', renderTemplatePreview($('[data-ai-profile-prompt]')?.value, parseKeywordLines($('[data-ai-profile-keywords]')?.value), normalizeSearchWindowDays($('[data-ai-profile-days]')?.value)))

  const renderWecom = (targets = []) => {
    const node = $('[data-ai-wecom-list]'); if (!node) return
    const items = targets.filter((item) => item.type === 'wecom' || item.session_id || item.target?.session_id)
    if (!items.length) { node.innerHTML = '<div class="empty-state"><p>暂无企微推送目标。</p></div>'; return }
    node.innerHTML = items.map((item) => `<div class="grid-2 ai-wecom-target" data-ai-wecom-target><label class="field"><span>显示名称</span><input class="input" value="${escapeAiHtml(item.display_name || '')}" data-ai-wecom-name /></label><label class="field"><span>session_id</span><input class="input" value="${escapeAiHtml(item.session_id || item.target?.session_id || '')}" data-ai-wecom-session required /></label><button class="btn btn-secondary" type="button" data-ai-remove-wecom>移除</button></div>`).join('')
  }
  const populate = (profile) => {
    const source = profile || { name: '', enabled: true, prompt_template: DEFAULT_AI_PROMPT_TEMPLATE, keywords: [], search_window_days: DEFAULT_SEARCH_WINDOW_DAYS, schedule: {}, deliveries: [] }
    $('[data-ai-profile-name]').value = source.name || ''; $('[data-ai-profile-enabled]').checked = source.enabled !== false; $('[data-ai-profile-prompt]').value = source.prompt_template || DEFAULT_AI_PROMPT_TEMPLATE; $('[data-ai-profile-keywords]').value = keywordsToTextarea(profileKeywords(source)); $('[data-ai-profile-days]').value = normalizeSearchWindowDays(source.search_window_days)
    const schedule = source.schedule || {}; $('[data-ai-schedule-enabled]').checked = Boolean(schedule.enabled); $('[data-ai-cron]').value = schedule.cron || '0 9 * * *'; toggleSchedule(Boolean(schedule.enabled))
    const deliveries = source.deliveries || []; const callback = deliveries.find((item) => item.type === 'callback'); $('[data-ai-callback-enabled]').checked = Boolean(callback); $('[data-ai-callback-url]').value = callback?.url || callback?.target?.url || ''; toggleCallback(Boolean(callback)); renderWecom(deliveries)
    $('[data-ai-delete-profile]').disabled = !profileId(profile)
    const badge = $('[data-ai-template-state]'); if (badge) { badge.className = `badge ${source.enabled !== false ? 'success' : 'warning'}`; badge.textContent = source.enabled !== false ? '已启用' : '已停用' }
    state.dirty = false; text('[data-ai-save-state]', ''); updatePreview(); updateReturnLink()
  }
  const renderSelector = (selectedId = '') => {
    const select = $('[data-ai-profile-select]'); if (!select) return; select.replaceChildren()
    if (state.isNew) { const option = new Option('新建模板（未保存）', '__new__', true, true); select.add(option) }
    state.profiles.forEach((profile) => select.add(new Option(`${profile.name}${profile.enabled === false ? '（已停用）' : ''}`, profileId(profile), false, profileId(profile) === selectedId)))
    if (!select.options.length) select.add(new Option('暂无模板', ''))
  }
  const selectProfile = (id) => { const profile = state.profiles.find((item) => profileId(item) === id) || state.profiles.find((item) => item.enabled !== false) || state.profiles[0] || null; state.activeProfile = profile; state.isNew = false; renderSelector(profileId(profile)); populate(profile) }
  const loadProfiles = async (selectedId = '') => { state.profiles = listFrom(await api.listProfiles(), ['profiles', 'items', 'results']); if (!state.profiles.length) { state.activeProfile = null; state.isNew = true; renderSelector('__new__'); populate(null); state.isNew = true; const select = $('[data-ai-profile-select]'); if (select) select.value = '__new__'; const badge = $('[data-ai-template-state]'); if (badge) { badge.className = 'badge'; badge.textContent = '新建模板' } text('[data-ai-save-state]', '尚未保存'); return } selectProfile(selectedId || queryProfile()) }
  const deliveriesPayload = () => { const result = []; if ($('[data-ai-callback-enabled]')?.checked) { const url = $('[data-ai-callback-url]')?.value.trim(); if (url) result.push({ type: 'callback', url }) } $$('[data-ai-wecom-target]').forEach((row) => { const session_id = $('[data-ai-wecom-session]', row)?.value.trim(); const display_name = $('[data-ai-wecom-name]', row)?.value.trim(); if (session_id) result.push({ type: 'wecom', session_id, display_name: display_name || undefined }) }); return result }
  const payload = () => {
    const name = $('[data-ai-profile-name]')?.value.trim(); if (!name) throw new Error('请填写模板名称。')
    const prompt = $('[data-ai-profile-prompt]')?.value.trim(); if (!hasRequiredPlaceholders(prompt)) throw new Error('提示词必须同时包含 {{keywords}} 和 {{time_range}}。')
    const keywords = requireKeywords($('[data-ai-profile-keywords]')?.value); const days = requireDays($('[data-ai-profile-days]')?.value); const scheduleEnabled = Boolean($('[data-ai-schedule-enabled]')?.checked); const cronValue = $('[data-ai-cron]')?.value.trim() || ''
    if (scheduleEnabled && !isFivePartCron(cronValue)) throw new Error('Cron必须是标准五段格式。')
    return { name, enabled: Boolean($('[data-ai-profile-enabled]')?.checked), prompt_template: prompt, keywords, search_window_days: days, sources: ['darkweb', 'telegram', 'web'], language: 'zh-CN', schedule: { enabled: scheduleEnabled, cron: scheduleEnabled ? cronValue : null, timezone: 'Asia/Shanghai' }, deliveries: deliveriesPayload() }
  }

  on($('[data-ai-profile-select]'), 'change', (event) => { if (!confirmDiscard()) { event.target.value = currentValue(); return } if (event.target.value !== '__new__') selectProfile(event.target.value) })
  on($('[data-ai-new-profile]'), 'click', () => { if (!confirmDiscard()) return; state.activeProfile = null; state.isNew = true; renderSelector('__new__'); populate(null); state.isNew = true; $('[data-ai-profile-select]').value = '__new__'; text('[data-ai-save-state]', '新建模板尚未保存'); $('[data-ai-profile-name]')?.focus() })
  on($('[data-ai-delete-profile]'), 'click', async () => { const id = profileId(state.activeProfile); if (!id || !window.confirm(`确定删除模板“${state.activeProfile.name}”吗？`)) return; const index = state.profiles.findIndex((item) => profileId(item) === id); const next = state.profiles[index + 1] || state.profiles[index - 1] || null; try { await api.deleteProfile(id); state.dirty = false; await loadProfiles(profileId(next)); toast('模板已删除') } catch (reason) { showError(reason) } })
  on($('[data-ai-profile-form]'), 'submit', async (event) => { event.preventDefault(); const button = $('[data-ai-save-profile]'); button.disabled = true; try { const body = payload(); const id = state.isNew ? '' : profileId(state.activeProfile); const saved = id ? await api.updateProfile(id, body) : await api.createProfile(body); await loadProfiles(profileId(saved)); toast('模板已保存') } catch (reason) { showError(reason) } finally { button.disabled = false } })
  ;['[data-ai-profile-name]', '[data-ai-profile-enabled]', '[data-ai-profile-prompt]', '[data-ai-profile-keywords]', '[data-ai-profile-days]', '[data-ai-schedule-enabled]', '[data-ai-cron]', '[data-ai-callback-enabled]', '[data-ai-callback-url]'].forEach((selector) => on($(selector), 'input', () => { markDirty(); updatePreview() }))
  on($('[data-ai-schedule-enabled]'), 'change', (event) => toggleSchedule(event.target.checked)); on($('[data-ai-callback-enabled]'), 'change', (event) => toggleCallback(event.target.checked))
  on($('[data-ai-wecom-list]'), 'input', markDirty); on($('[data-ai-wecom-list]'), 'click', (event) => { const button = event.target.closest('[data-ai-remove-wecom]'); if (!button) return; button.closest('[data-ai-wecom-target]')?.remove(); markDirty(); if (!$$('[data-ai-wecom-target]').length) renderWecom([]) })
  on($('[data-ai-add-wecom]'), 'click', () => { const current = deliveriesPayload().filter((item) => item.type === 'wecom'); renderWecom([...current, { type: 'wecom' }]); markDirty() })
  on($('[data-ai-dismiss-error]'), 'click', () => { const node = $('[data-ai-error]'); if (node) node.hidden = true })

  try { await loadProfiles() } catch (reason) { showError(reason) } finally { const loading = $('[data-ai-runtime-state]'); if (loading) loading.hidden = true }
  return dispose
}
