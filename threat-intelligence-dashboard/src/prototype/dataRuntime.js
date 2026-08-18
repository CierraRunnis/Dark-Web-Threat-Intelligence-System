import countryCentroidsJson from 'world-countries-centroids/dist/countries.geojson?raw'
import { hydrateAiAggregationScreen } from './aiAggregationRuntime.js'
import { hydrateAiAggregationTemplatesScreen } from './aiAggregationTemplatesRuntime.js'

const COUNTRY_COORDINATES = JSON.parse(countryCentroidsJson).features.reduce((coordinates, feature) => {
  const code = feature.properties.ISO
  if (code && !coordinates[code]) coordinates[code] = feature.geometry.coordinates
  return coordinates
}, {})

const INCIDENT_FILES = new Set([
  'ransomware-detail.html',
  'data-leak-detail.html',
  'vulnerability-detail.html',
])

const DATA_FILES = new Set([
  'dashboard.html',
  'intelligence.html',
  'ai-aggregation.html',
  'ai-aggregation-templates.html',
  'ransomware.html',
  'data-leak.html',
  'vulnerabilities.html',
  ...INCIDENT_FILES,
])

function query(root, selector) {
  return root?.querySelector(selector) || null
}

function queryAll(root, selector) {
  return root ? [...root.querySelectorAll(selector)] : []
}

function showToast(message) {
  let toast = document.querySelector('.toast')
  if (!toast) return
  toast.textContent = message
  toast.classList.add('show')
  window.clearTimeout(showToast.timer)
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 2600)
}

const JSON_CACHE_TTL_MS = 15_000
const CACHEABLE_JSON_PATHS = new Set([
  '/api/dashboard/overview',
  '/api/intelligence',
  '/api/intelligence/ransomware',
  '/api/intelligence/data-leak',
  '/api/events',
])

function isCacheableJsonUrl(url) {
  try {
    return CACHEABLE_JSON_PATHS.has(new URL(url, window.location.origin).pathname)
  } catch {
    return false
  }
}
const jsonResponseCache = new Map()
const inFlightJsonRequests = new Map()

async function requestJson(url, options = {}) {
  const { preferCached = false, ...fetchOptions } = options
  const method = String(fetchOptions.method || 'GET').toUpperCase()
  const cacheable = method === 'GET' && isCacheableJsonUrl(url)
  if (cacheable) {
    const cached = jsonResponseCache.get(url)
    const fresh = cached && Date.now() - cached.storedAt < JSON_CACHE_TTL_MS
    if (cached && (fresh || preferCached)) {
      if (!fresh && !inFlightJsonRequests.has(url)) {
        const refresh = requestJsonUncached(url, fetchOptions)
          .then((payload) => {
            const refreshed = jsonResponseCache.get(url)
            jsonResponseCache.set(url, {
              storedAt: Date.now(),
              payload,
              etag: refreshed?.etag || cached.etag || '',
            })
            return payload
          })
          .catch(() => cached.payload)
          .finally(() => inFlightJsonRequests.delete(url))
        inFlightJsonRequests.set(url, refresh)
      }
      return cached.payload
    }
    const inFlight = inFlightJsonRequests.get(url)
    if (inFlight) return inFlight
  }

  const request = requestJsonUncached(url, fetchOptions)
  if (!cacheable) return request
  inFlightJsonRequests.set(url, request)
  try {
    const payload = await request
    const existing = jsonResponseCache.get(url)
    jsonResponseCache.set(url, { storedAt: Date.now(), payload, etag: existing?.etag || '' })
    return payload
  } finally {
    inFlightJsonRequests.delete(url)
  }
}

async function requestJsonUncached(url, options = {}) {
  const headers = new Headers(options.headers || {})
  const method = String(options.method || 'GET').toUpperCase()
  const cached = method === 'GET' ? jsonResponseCache.get(url) : null
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (cached?.etag && !headers.has('If-None-Match')) headers.set('If-None-Match', cached.etag)
  const response = await fetch(url, { ...options, headers })
  if (response.status === 304 && cached) {
    jsonResponseCache.set(url, { ...cached, storedAt: Date.now() })
    return cached.payload
  }
  if (!response.ok) {
    let detail = ''
    try {
      const payload = await response.json()
      detail = payload?.detail || payload?.message || ''
    } catch {
      detail = await response.text().catch(() => '')
    }
    throw new Error(detail || `请求失败（${response.status}）`)
  }
  if (response.status === 204) return null
  const payload = await response.json()
  if (method === 'GET' && isCacheableJsonUrl(url)) {
    jsonResponseCache.set(url, {
      storedAt: Date.now(),
      payload,
      etag: response.headers.get('etag') || cached?.etag || '',
    })
  }
  return payload
}

function number(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function parseTimestamp(value) {
  if (value instanceof Date) return value.getTime()
  if (typeof value === 'number') return Number.isFinite(value) ? value : Number.NaN
  const text = String(value || '').trim()
  if (!text) return Number.NaN
  const direct = Date.parse(text)
  if (Number.isFinite(direct)) return direct
  const slashDate = text.match(/^(\d{1,2})\/(\d{1,2})(?:\/(\d{4}))?(?:\s+(\d{1,2}):(\d{2}))?$/)
  if (!slashDate) return Number.NaN
  const first = Number(slashDate[1])
  const second = Number(slashDate[2])
  const hasYear = Boolean(slashDate[3])
  const year = hasYear ? Number(slashDate[3]) : new Date().getFullYear()
  const month = hasYear && first > 12 ? second : first
  const day = hasYear && first > 12 ? first : second
  const timestamp = new Date(year, month - 1, day, Number(slashDate[4] || 0), Number(slashDate[5] || 0)).getTime()
  return month >= 1 && month <= 12 && day >= 1 && day <= 31 ? timestamp : Number.NaN
}

function formatDate(value, withTime = true) {
  if (!value) return '—'
  const timestamp = parseTimestamp(value)
  if (!Number.isFinite(timestamp)) return String(value)
  const date = new Date(timestamp)
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
  }).format(date)
}

function usableText(value) {
  const text = String(value || '').trim()
  return /^"?QUERY LENGTH LIMIT EXCEEDED\b/i.test(text) ? '' : text
}

function excerpt(value, limit = 260) {
  const text = usableText(value).replace(/\s+/g, ' ')
  if (!text || text.length <= limit) return text
  return `${text.slice(0, limit).trimEnd()}…`
}

function relativeTime(value) {
  const timestamp = parseTimestamp(value)
  if (!Number.isFinite(timestamp)) return '时间未提供'
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000))
  if (minutes < 1) return '刚刚更新'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return formatDate(value, false)
}

function severityOf(item) {
  const raw = String(item?.severity || '').toLowerCase()
  if (['critical', 'high', 'medium', 'low'].includes(raw)) return raw
  const score = Number(item?.riskScore ?? item?.risk_score ?? 0)
  if (score >= 90) return 'critical'
  if (score >= 70) return 'high'
  if (score >= 40) return 'medium'
  return 'low'
}

function severityLabel(value) {
  return { critical: '严重', high: '高危', medium: '中危', low: '低危' }[value] || '未知'
}

function eventType(item) {
  const value = String(item?.normalized_event_type || item?.event_type || item?.raw_source_type || '').toLowerCase()
  if (item?.cveId || item?.cve_id || value.includes('vulnerab')) return 'vulnerability'
  if (value.includes('ransom') || value === 'victim') return 'ransomware'
  if (value.includes('leak') || value === 'forum') return 'data-leak'
  if (value.includes('document')) return 'document-exposure'
  return ''
}

function eventTypeLabel(type) {
  return { vulnerability: '漏洞', ransomware: '勒索', 'data-leak': '数据泄露', 'document-exposure': '文件监测' }[type] || '情报'
}

function detailHref(item) {
  const id = encodeURIComponent(String(item?.id || ''))
  const type = eventType(item)
  if (type === 'vulnerability') return `/vulnerability-alerts/${id}`
  if (type === 'ransomware') return `/ransomware/${id}`
  if (type === 'data-leak') return `/data-leak/${id}`
  return `/event/${id}`
}

function setText(root, selector, value) {
  const node = query(root, selector)
  if (node) node.textContent = value == null || value === '' ? '—' : String(value)
}

function setCounts(container, values) {
  queryAll(container, 'article').forEach((card, index) => {
    const target = query(card, 'strong[data-count], strong.num, strong')
    if (!target || index >= values.length) return
    const value = Number(values[index] || 0)
    target.textContent = number(value)
    if (target.hasAttribute('data-count')) target.dataset.count = String(value)
    const note = query(card, 'small')
    if (note) note.textContent = '实时数据'
  })
}

function setSummary(group, pairs) {
  queryAll(group, ':scope > div').forEach((item, index) => {
    if (!pairs[index]) return
    const [label, value] = pairs[index]
    const labelNode = query(item, 'span, dt')
    const valueNode = query(item, 'strong, dd')
    if (labelNode) labelNode.textContent = label
    if (valueNode) valueNode.textContent = value == null || value === '' ? '—' : String(value)
  })
}

function setCell(cell, main, sub = '') {
  if (!cell) return
  cell.replaceChildren()
  cell.append(document.createTextNode(main == null || main === '' ? '—' : String(main)))
  if (sub) {
    const secondary = document.createElement('span')
    secondary.textContent = String(sub)
    cell.appendChild(secondary)
  }
}

function setBadgeCell(cell, label, tone = '') {
  if (!cell) return
  cell.replaceChildren()
  const badge = document.createElement('span')
  badge.className = `badge${tone ? ` badge-${tone}` : ''}`
  badge.textContent = label
  cell.appendChild(badge)
}

function setActionCell(cell, label, href) {
  if (!cell) return
  cell.replaceChildren()
  const link = document.createElement('a')
  link.className = 'btn btn-ghost'
  link.href = href
  link.textContent = label
  cell.appendChild(link)
}

function documentTypeMeta(rawType) {
  const type = String(rawType || '').toLowerCase()
  if (type.includes('pdf')) return { label: 'PDF', className: 'pdf' }
  if (type.includes('xls') || type.includes('sheet')) return { label: 'XLS', className: 'xls' }
  if (type.includes('ppt') || type.includes('presentation')) return { label: 'PPT', className: 'ppt' }
  return { label: 'DOC', className: 'doc' }
}

function setDocumentTitleCell(cell, title, rawType) {
  if (!cell) return
  const meta = documentTypeMeta(rawType)
  const content = document.createElement('span')
  content.className = 'document-title-cell'
  const icon = document.createElement('span')
  icon.className = `inline-doc ${meta.className}`
  icon.textContent = meta.label
  const text = document.createElement('span')
  text.className = 'document-title-text'
  text.textContent = title || '—'
  content.append(icon, text)
  cell.replaceChildren(content)
  cell.title = title || ''
}

function setDocumentSourceCell(cell, platform, label) {
  if (!cell) return
  const marks = {
    baidu_wenku: 'baidu-doc',
    baidu_doc: 'baidu-doc',
    baidu: 'baidu-disk',
    baidu_netdisk: 'baidu-disk',
    baidupan_share: 'baidu-disk',
    aliyun: 'aliyun',
    alipan: 'aliyun',
    aliyundrive_share: 'aliyun',
    quark: 'quark',
    quark_share: 'quark',
    quark_doc: 'quark',
    onedrive: 'onedrive',
    onedrive_share: 'onedrive',
    doc88: 'doc88',
    docin: 'docin',
    csdn: 'csdn',
    csdn_wenku: 'csdn',
    csdn_download: 'csdn',
    tencent_wenku: 'tencent-doc',
    github: 'github',
    gitlab: 'gitlab',
    gitee: 'gitee',
  }
  const site = document.createElement('span')
  site.className = 'source-site'
  const mark = marks[String(platform || '').toLowerCase()]
  if (mark) {
    const logo = document.createElement('span')
    logo.className = `source-logo logo-${mark}`
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use')
    use.setAttribute('href', `#mark-${mark}`)
    svg.appendChild(use)
    logo.appendChild(svg)
    site.appendChild(logo)
  }
  const text = document.createElement('span')
  text.textContent = label || platform || '—'
  site.appendChild(text)
  cell.replaceChildren(site)
}

function setClassTextCell(cell, label, className) {
  if (!cell) return
  const value = document.createElement('span')
  value.className = className
  value.textContent = label || '—'
  cell.replaceChildren(value)
}

function setResultStatusCell(cell, label) {
  if (!cell) return
  const status = document.createElement('span')
  const value = label || '未处理'
  const tone = value.includes('确认') ? 'confirmed'
    : value.includes('处理') && !value.includes('未处理') ? 'processing'
      : value.includes('无效') || value.includes('失效') ? 'expired' : 'pending'
  status.className = `result-status ${tone}`
  status.textContent = value
  cell.replaceChildren(status)
}

function replaceFilterOptions(root, selector, placeholder, entries) {
  const select = query(root, selector)
  if (!select) return
  const unique = new Map()
  for (const entry of entries) {
    const value = String(entry?.value ?? entry ?? '').trim()
    const label = String(entry?.label ?? entry ?? '').trim()
    if (value && label && !unique.has(value)) unique.set(value, label)
  }
  const options = [new Option(placeholder, '')]
  for (const [value, label] of unique) options.push(new Option(label, value))
  select.replaceChildren(...options)
}

function formatFullDate(value, withTime = false) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
  }).format(date).replaceAll('/', '-')
}

function itemDateValue(item) {
  return item?.updatedTimeRaw
    || item?.updated_time_raw
    || item?.lastSeenAt
    || item?.firstSeenAt
    || item?.disclosureTimeRaw
    || item?.disclosure_time_raw
    || item?.disclosureTime
    || item?.disclosure_time
    || item?.disclosureDate
    || ''
}

function filterByDays(items, days, referenceTime = Date.now()) {
  if (!days) return [...items]
  const cutoff = referenceTime - Number(days) * 24 * 60 * 60 * 1000
  return items.filter((item) => {
    const timestamp = parseTimestamp(itemDateValue(item))
    return Number.isFinite(timestamp) && timestamp >= cutoff && timestamp <= referenceTime + 60 * 60 * 1000
  })
}

function buildDailyTrend(items, days = 7, referenceTime = Date.now()) {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  const buckets = []
  const indexByDate = new Map()
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const date = new Date(referenceTime - offset * 24 * 60 * 60 * 1000)
    const key = formatter.format(date)
    indexByDate.set(key, buckets.length)
    buckets.push({ date: key, value: 0 })
  }
  for (const item of items) {
    const timestamp = parseTimestamp(itemDateValue(item))
    if (!Number.isFinite(timestamp)) continue
    const key = formatter.format(new Date(timestamp))
    const index = indexByDate.get(key)
    if (index !== undefined) buckets[index].value += 1
  }
  return buckets
}

function chartPoints(values, { xStart, xEnd, yTop, yBottom }) {
  const safeValues = values.length ? values.map((value) => Math.max(0, Number(value || 0))) : [0]
  const maximum = Math.max(1, ...safeValues)
  return safeValues.map((value, index) => ({
    x: safeValues.length === 1 ? (xStart + xEnd) / 2 : xStart + (xEnd - xStart) * index / (safeValues.length - 1),
    y: yBottom - (yBottom - yTop) * value / maximum,
    value,
  }))
}

function evenlySample(items, count) {
  if (items.length <= count) return [...items]
  return Array.from({ length: count }, (_, index) => items[Math.round(index * (items.length - 1) / Math.max(1, count - 1))])
}

function linePath(points) {
  return points.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ')
}

function areaPath(points, yBottom) {
  if (!points.length) return ''
  return `${linePath(points)} L${points.at(-1).x.toFixed(1)} ${yBottom} L${points[0].x.toFixed(1)} ${yBottom} Z`
}

function setConicChart(node, values, colors, customProperty = '') {
  if (!node) return
  const safeValues = values.map((value) => Math.max(0, Number(value || 0)))
  const total = safeValues.reduce((sum, value) => sum + value, 0)
  let gradient = 'conic-gradient(var(--border) 0 100%)'
  if (total > 0) {
    let start = 0
    const stops = safeValues.map((value, index) => {
      const end = start + value / total * 100
      const stop = `${colors[index % colors.length]} ${start.toFixed(2)}% ${end.toFixed(2)}%`
      start = end
      return stop
    })
    gradient = `conic-gradient(${stops.join(', ')})`
  }
  if (customProperty) node.style.setProperty(customProperty, gradient)
  else node.style.background = gradient
}

function setChartMarkers(group, selector, points, update) {
  if (!group) return
  const nodes = queryAll(group, selector)
  nodes.forEach((node, index) => {
    const point = points[index]
    node.hidden = !point
    node.style.opacity = point ? '1' : '0'
    if (point) update(node, point, index)
  })
}

function sourceLogoKey(value) {
  const label = String(value || '').toLowerCase()
  if (/github/.test(label)) return 'github'
  if (/gitlab/.test(label)) return 'gitlab'
  if (/gitee|码云/.test(label)) return 'gitee'
  if (/百度.*文库|baidu.*wenku|baidu_doc/.test(label)) return 'baidu-doc'
  if (/百度.*网盘|baidupan|baidu_netdisk/.test(label)) return 'baidu-disk'
  if (/阿里|aliyun|alipan/.test(label)) return 'aliyun'
  if (/夸克|quark/.test(label)) return 'quark'
  if (/onedrive/.test(label)) return 'onedrive'
  if (/道客|doc88/.test(label)) return 'doc88'
  if (/豆丁|docin/.test(label)) return 'docin'
  if (/csdn/.test(label)) return 'csdn'
  if (/腾讯.*(?:文库|文档)|tencent_(?:wenku|docs?)/.test(label)) return 'tencent-doc'
  return ''
}

function setSourceLogo(logo, value) {
  if (!logo) return
  const key = sourceLogoKey(value)
  ;[...logo.classList].filter((name) => name.startsWith('logo-')).forEach((name) => logo.classList.remove(name))
  if (key) logo.classList.add(`logo-${key}`)
  const use = query(logo, 'use')
  if (use) use.setAttribute('href', key ? `#mark-${key}` : '')
  logo.hidden = !key
}

function fillSourceDistribution(container, items, total, percentage = false) {
  if (!container) return
  container.__runtimeRowTemplate ||= container.firstElementChild?.cloneNode(true)
  while (container.children.length < items.length && container.__runtimeRowTemplate) {
    container.appendChild(container.__runtimeRowTemplate.cloneNode(true))
  }
  const rows = [...container.children]
  rows.forEach((row, index) => {
    const item = items[index]
    row.hidden = !item
    if (!item) return
    const name = item.name || item.label || item.key || '未知来源'
    const share = Math.round(Number(item.value || 0) / Math.max(1, total) * 100)
    setSourceLogo(query(row, '.source-logo'), name)
    const nestedName = query(row, ':scope > span > strong')
    const nameNode = nestedName || query(row, ':scope > span:not(.source-logo)')
    if (nameNode) nameNode.textContent = name
    const valueNode = nestedName ? query(row, ':scope > span > small') : query(row, ':scope > b')
    if (valueNode) {
      if (valueNode.matches('small')) {
        valueNode.replaceChildren()
        const count = document.createElement('b')
        count.textContent = number(item.value)
        valueNode.append(count, document.createTextNode(` · ${share}%`))
      } else {
        valueNode.textContent = percentage ? `${share}%` : number(item.value)
      }
    }
    row.style.setProperty('--share', `${share}%`)
  })
}

function reviewStatusLabel(value) {
  return {
    new: '待处理',
    triaged: '处理中',
    confirmed: '已确认',
    false_positive: '误报',
    closed: '已关闭',
    suppressed: '已压制',
  }[String(value || '').toLowerCase()] || value || '—'
}

function setLabeledValues(container, values) {
  if (!container) return
  queryAll(container, ':scope > div').forEach((item) => {
    const labelNode = query(item, ':scope > span, :scope > dt')
    const valueNode = query(item, ':scope > strong, :scope > dd')
    if (!labelNode || !valueNode) return
    const label = labelNode.textContent.trim()
    const value = Object.prototype.hasOwnProperty.call(values, label) ? values[label] : '—'
    valueNode.textContent = value == null || value === '' ? '—' : String(value)
  })
}

function ensureDataState(root) {
  let node = query(root, '.runtime-data-state')
  if (node) return node
  const main = query(root, 'main')
  if (!main) return null
  node = document.createElement('div')
  node.className = 'runtime-data-state'
  node.setAttribute('role', 'status')
  main.prepend(node)
  return node
}

function setDataState(root, state, message = '') {
  const node = ensureDataState(root)
  if (!node) return
  node.dataset.state = state
  node.hidden = state === 'ready'
  node.textContent = message || (state === 'loading' ? '正在加载真实数据…' : '')
}

function setActionAvailable(element, available, title = '') {
  if (!element) return
  if ('disabled' in element) element.disabled = !available
  element.classList.toggle('runtime-disabled', !available)
  element.setAttribute('aria-disabled', String(!available))
  if (title) element.title = title
}

function prepareDataPage(root, file) {
  setDataState(root, 'loading', '正在加载真实数据…')
  queryAll(root, '[data-count]').forEach((node) => {
    node.textContent = '—'
    node.dataset.count = ''
  })
  queryAll(root, 'table[data-table]').forEach((table) => clearTable(root, `#${table.id}`))
  queryAll(root, '[data-table-count]').forEach((node) => { node.textContent = '0' })
  queryAll(root, '.actor-rank, .timeline-feed li, .situation-watch-list a, .situation-region-rank .compact-bar, .industry-heat-list > div, .rank-card .bar-row-v2, .vendor-bars > div, .industry-block, .product-bubble, .code-secret-rank > div').forEach((node) => { node.hidden = true })
  queryAll(root, '.source-row').forEach((row) => {
    setText(row, 'small', '0 条 · 可信 0')
    setText(row, 'b', '0%')
  })
  queryAll(root, '.monitor-donut-legend > div, .code-source-grid > div, .code-risk-legend > div, .severity-legend > div, .signal-source-list > div').forEach((node) => { node.hidden = true })
  queryAll(root, '.trend-area, .trend-line, .vuln-area-path, .vuln-line-path, .monitor-area, .monitor-line, .code-line, .situation-spark path').forEach((path) => path.setAttribute('d', ''))
  queryAll(root, '.vuln-points circle, .monitor-points circle, .monitor-columns rect, .monitor-peak-ring, .code-dots circle').forEach((node) => { node.style.opacity = '0' })
  queryAll(root, '.monitor-chart-values text, .monitor-chart-dates text, .code-chart-values text, .code-chart-dates text, .vuln-chart-values text, .chart-labels text, .trend-axis-labels span').forEach((node) => { node.textContent = '—' })
  queryAll(root, '.monitor-trend-summary strong, .trend-summary strong').forEach((node) => { node.textContent = '—' })
  queryAll(root, '[data-pagination-for]').forEach((pagination) => {
    pagination.hidden = true
    setText(pagination, '.table-pagination-summary', '')
    setText(pagination, '.table-pagination-current', '')
  })
  setConicChart(query(root, '.situation-donut'), [], ['var(--danger)'], '--runtime-donut')
  queryAll(root, '.severity-donut, .monitor-donut, .code-risk-donut, .signal-ring').forEach((node) => setConicChart(node, [], ['var(--border)']))

  if (file === 'monitoring.html') {
    queryAll(root, '.monitor-kpi-grid small, .code-kpi-layout small').forEach((node) => { node.textContent = '等待真实接口' })
    queryAll(root, '.monitor-donut-card .meta, .code-risk-card .meta').forEach((node) => { node.textContent = '等待真实接口' })
  }

  if (file === 'dashboard.html') {
    queryAll(root, '.situation-status-strip strong').forEach((node) => { node.textContent = '—' })
    setText(root, '.situation-status-strip > div:first-child small', '等待真实接口')
    queryAll(root, '.situation-kpi-head b').forEach((node) => { node.textContent = '加载中' })
    queryAll(root, '.situation-world .map-point, .situation-map-label').forEach((node) => { node.hidden = true })
    setText(root, '.situation-map-foot > b strong', '—')
    setText(root, '.situation-watch-card .panel-header .badge', '—')
    queryAll(root, '.situation-donut-legend .legend-item b').forEach((node) => { node.textContent = '—' })
    queryAll(root, '.rank-card .rank-badge').forEach((node) => { node.textContent = '—' })
    queryAll(root, '.rank-card .rank-hero strong').forEach((node) => { node.textContent = '正在加载' })
    queryAll(root, '.rank-card .rank-hero span:last-child').forEach((node) => { node.textContent = '等待真实接口' })
  }

  if (file === 'intelligence.html') {
    const list = query(root, '#intel-results')
    if (list) {
      list.__runtimeItemTemplate ||= query(list, '.intel-result-item')?.cloneNode(true)
      list.replaceChildren()
    }
    queryAll(root, '.intel-result-tabs b, [data-table-count="intel-results"]').forEach((node) => { node.textContent = '0' })
  }

  if (INCIDENT_FILES.has(file)) {
    setText(root, 'main h1', '正在加载记录…')
    queryAll(root, '.detail-summary strong, .detail-kpi strong, .definition-grid strong').forEach((node) => { node.textContent = '—' })
    queryAll(root, '.detail-list, .detail-matrix, .timeline').forEach((container) => replaceRecordContainer(container, []))
    queryAll(root, '.detail-code, .detail-log, .detail-proof').forEach((node) => { node.textContent = '—' })
    queryAll(root, '.source-link-line a').forEach((link) => {
      link.removeAttribute('href')
      link.textContent = '—'
    })
    queryAll(root, '.mirror-frame figcaption > *, .mirror-frame-bar time').forEach((node) => { node.textContent = '—' })
    queryAll(root, '.evidence-actions a, .source-link-line a').forEach((link) => {
      link.removeAttribute('href')
      link.hidden = true
    })
    queryAll(root, '[data-copy]').forEach((button) => {
      button.dataset.copy = ''
      delete button.dataset.runtimeCopy
      setActionAvailable(button, false, '等待真实接口数据')
    })
    queryAll(root, '[data-runtime-open], [data-runtime-download]').forEach((button) => {
      delete button.dataset.runtimeOpen
      delete button.dataset.runtimeDownload
      setActionAvailable(button, false, '等待真实接口数据')
    })
  }

  queryAll(root, 'button[data-toast], button[data-disposition]').forEach((button) => {
    setActionAvailable(button, false, '等待真实接口状态')
  })
}

function replaceRows(table, items, fillRow) {
  const body = query(table, 'tbody')
  if (!body) return
  const template = table.__runtimeRowTemplate?.cloneNode(true)
    || query(body, 'tr')?.cloneNode(true)
    || document.createElement('tr')
  const rows = items.map((item) => {
    const row = template.cloneNode(true)
    row.hidden = false
    fillRow(row, item)
    return row
  })
  body.replaceChildren(...rows)
  const count = table.id ? document.querySelector(`[data-table-count="${table.id}"]`) : null
  if (count) count.textContent = String(items.length)
  const empty = table.id ? document.querySelector(`[data-table-empty="${table.id}"]`) : null
  if (empty) empty.style.display = items.length ? 'none' : 'block'
  table.dispatchEvent(new CustomEvent('prototype:rows-updated'))
}

function clearTable(root, selector) {
  const table = query(root, selector)
  const body = query(table, 'tbody')
  if (body) {
    table.__runtimeRowTemplate ||= query(body, 'tr')?.cloneNode(true)
    body.replaceChildren()
  }
  return table
}

function countBy(items, getter) {
  const counts = new Map()
  for (const item of items) {
    const key = String(getter(item) || '未知')
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value)
}

function fillNamedRows(container, items) {
  if (!container) return
  const rows = [...container.children]
  const max = Math.max(1, Number(items[0]?.value || 0))
  rows.forEach((row, index) => {
    const item = items[index]
    row.hidden = !item
    if (!item) return
    const labels = queryAll(row, 'span')
    const name = labels.find((node) => !node.classList.contains('source-logo')) || query(row, 'strong')
    const value = query(row, 'b, strong:last-child')
    if (name) name.textContent = item.name
    if (value && value !== name) value.textContent = number(item.value)
    const bar = query(row, 'i, .bar-fill-v2')
    if (bar) {
      const percentage = `${Math.round(Number(item.value || 0) / max * 100)}%`
      bar.style.setProperty('--bar', percentage)
      bar.style.setProperty('--value', percentage)
      bar.style.setProperty('--score', percentage)
    }
  })
}

function fillRankCard(card, items, subtitle) {
  if (!card) return
  const first = items[0] || { name: '暂无数据', value: 0 }
  setText(card, '.rank-badge', number(first.value))
  setText(card, '.rank-hero strong', first.name)
  setText(card, '.rank-hero span:last-child', subtitle)
  fillNamedRows(query(card, '.bar-list-v2'), items)
}

function markExports(root, state, tableSelectors, serverUrl = '') {
  queryAll(root, 'button[data-toast]').forEach((button) => {
    if (!button.textContent.includes('导出')) return
    const panel = button.closest('article, section')
    const table = tableSelectors.map((selector) => query(panel || root, selector) || query(root, selector)).find(Boolean)
    if (!table) return
    button.dataset.runtimeExport = table.id || tableSelectors[0]
    state.tables.set(button.dataset.runtimeExport, table)
    if (serverUrl) state.exportUrls.set(button.dataset.runtimeExport, serverUrl)
    setActionAvailable(button, true)
  })
}

function downloadServerExport(url) {
  if (!url) return
  const link = document.createElement('a')
  link.href = url
  link.download = ''
  document.body.appendChild(link)
  link.click()
  link.remove()
  showToast('已开始流式导出完整筛选结果')
}

function exportTable(table, filename = '玄鉴数据.csv') {
  if (!table) return
  const lines = queryAll(table, 'tr')
    .filter((row) => !row.hidden)
    .map((row) => queryAll(row, 'th, td').map((cell) => `"${cell.textContent.trim().replaceAll('"', '""')}"`).join(','))
  const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
  showToast('已导出当前真实数据')
}

function installActionGuard(root, state) {
  root.__dataRuntimeAbort?.abort()
  const controller = new AbortController()
  root.__dataRuntimeAbort = controller
  root.addEventListener('click', async (event) => {
    const target = event.target.closest('button, a')
    if (!target || !root.contains(target)) return

    const handled = target.dataset.runtimeExport
      || target.dataset.runtimeRefresh
      || target.dataset.runtimeFilter
      || target.dataset.runtimeReviewStatus
      || target.dataset.runtimeReviewSave
      || target.dataset.runtimeCopy
      || target.dataset.runtimeScroll
      || target.dataset.runtimeTranslate
      || target.dataset.runtimeSource
      || target.dataset.runtimeOpen
      || target.dataset.runtimeDownload
      || target.dataset.runtimePage
    const unsupported = target.matches('[data-toast], [data-disposition]') && !handled
    if (!handled && !unsupported) return

    event.preventDefault()
    event.stopImmediatePropagation()
    if (unsupported) {
      showToast('当前操作暂无后端接口，暂不支持')
      return
    }
    try {
      if (target.dataset.runtimePage) {
        const table = query(root, `#${CSS.escape(target.dataset.runtimePageTarget || '')}`)
        if (!table) return
        const currentPage = Math.max(1, Number(table.dataset.serverPage || 1))
        table.dataset.serverPage = String(target.dataset.runtimePage === 'previous' ? currentPage - 1 : currentPage + 1)
        await state.refresh?.()
      } else if (target.dataset.runtimeExport) {
        const serverUrl = state.exportUrls.get(target.dataset.runtimeExport)
        if (serverUrl) downloadServerExport(serverUrl)
        else exportTable(state.tables.get(target.dataset.runtimeExport))
      } else if (target.dataset.runtimeRefresh) {
        await state.refresh?.()
        showToast('实时数据已刷新')
      } else if (target.dataset.runtimeFilter) {
        const input = query(root, target.dataset.runtimeFilter)
        if (input) {
          input.value = target.dataset.runtimeFilterValue || ''
          input.dispatchEvent(new Event('input', { bubbles: true }))
        }
      } else if (target.dataset.runtimeReviewStatus) {
        state.pendingReviewStatus = target.dataset.runtimeReviewStatus
        queryAll(root, '[data-runtime-review-status]').forEach((button) => button.classList.toggle('btn-primary', button === target))
        const status = query(root, '[data-review-state]')
        if (status) status.textContent = target.dataset.disposition || target.textContent.trim()
        showToast('已选择复核结论，请保存')
      } else if (target.dataset.runtimeReviewSave) {
        await state.saveReview?.()
      } else if (target.dataset.runtimeCopy) {
        await navigator.clipboard.writeText(target.dataset.runtimeCopy || state.copyText || '')
        showToast('已复制到剪贴板')
      } else if (target.dataset.runtimeScroll) {
        query(root, target.dataset.runtimeScroll)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      } else if (target.dataset.runtimeTranslate) {
        await state.toggleTranslation?.()
      } else if (target.dataset.runtimeSource) {
        const source = target.dataset.runtimeSource
        if (state.sourceTable) {
          const selectedSource = state.sourceTable.dataset.serverSource === source ? '' : source
          state.sourceTable.dataset.serverSource = selectedSource
          state.sourceTable.dataset.serverPage = '1'
          queryAll(root, '[data-runtime-source]').forEach((button) => {
            button.classList.toggle('active', button.dataset.runtimeSource === selectedSource)
          })
          await state.refresh?.()
        }
      } else if (target.dataset.runtimeOpen) {
        window.open(target.dataset.runtimeOpen, '_blank', 'noopener,noreferrer')
      } else if (target.dataset.runtimeDownload) {
        const link = document.createElement('a')
        link.href = target.dataset.runtimeDownload
        link.download = ''
        link.target = '_blank'
        link.rel = 'noopener noreferrer'
        link.click()
      }
    } catch (error) {
      showToast(error.message || '操作失败')
    }
  }, { capture: true, signal: controller.signal })
}

function showLoadError(root, error) {
  const message = error?.message || '数据加载失败'
  setDataState(root, 'error', `真实数据加载失败：${message}`)
  const title = query(root, '.detail-hero h1')
  if (title) title.textContent = '记录加载失败'
  showToast(message)
}

function serverStateKey(tableId) {
  return `dwti-server-list:${window.location.pathname}:${tableId}`
}

function restoreServerState(root, table) {
  if (!table || table.dataset.serverStateRestored) return
  table.dataset.serverStateRestored = '1'
  let saved = null
  try {
    saved = JSON.parse(sessionStorage.getItem(serverStateKey(table.id)) || 'null')
  } catch {
    sessionStorage.removeItem(serverStateKey(table.id))
  }
  if (!saved) return
  table.dataset.serverPage = String(Math.max(1, Number(saved.page || 1)))
  const search = query(root, `[data-table-search="${table.id}"]`)
  if (search) search.value = saved.query || ''
  queryAll(root, `[data-filter-target="${table.id}"]`).forEach((control) => {
    const value = String(saved.filters?.[control.dataset.filterKey || ''] || '')
    if (!value) return
    control.dataset.pendingValue = value
    if (queryAll(control, 'option').some((option) => option.value === value)) control.value = value
  })
  const date = query(root, `[data-date-filter-target="${table.id}"]`)
  if (date && saved.days) date.value = String(saved.days)
  const tabs = query(root, `.tabs[data-target="${table.id}"]`)
  if (tabs && saved.tab) {
    queryAll(tabs, '.tab').forEach((tab) => {
      const active = tab.dataset.tab === saved.tab
      tab.classList.toggle('active', active)
      tab.setAttribute('aria-selected', String(active))
    })
  }
  const sort = query(root, '[data-intel-sort]')
  if (sort && saved.sort) sort.value = saved.sort
  table.dataset.serverSource = saved.source || ''
}

function serverControlValue(control) {
  return String(control?.value || control?.dataset.pendingValue || '').trim()
}

function serverQueryState(root, table) {
  restoreServerState(root, table)
  const filters = Object.fromEntries(
    queryAll(root, `[data-filter-target="${table.id}"]`).map((control) => [
      control.dataset.filterKey || '',
      serverControlValue(control),
    ]),
  )
  return {
    page: Math.max(1, Number(table.dataset.serverPage || 1)),
    pageSize: Math.min(100, Math.max(1, Number(table.dataset.serverPageSize || 20))),
    query: String(query(root, `[data-table-search="${table.id}"]`)?.value || '').trim(),
    tab: query(root, `.tabs[data-target="${table.id}"] .tab.active`)?.dataset.tab || 'all',
    filters,
    days: Number(query(root, `[data-date-filter-target="${table.id}"]`)?.value || 0) || null,
    source: String(table.dataset.serverSource || ''),
    sort: query(root, '[data-intel-sort]')?.value || 'latest',
  }
}

function restoreFilterValue(select, value) {
  if (!select || !value) return
  if (!queryAll(select, 'option').some((option) => option.value === value)) {
    select.append(new Option(value, value))
  }
  select.value = value
  select.dataset.pendingValue = value
}

function updateServerPagination(root, table, payload) {
  if (!table) return
  const page = Math.max(1, Number(payload.page || 1))
  const pageSize = Math.max(1, Number(payload.pageSize || 20))
  const total = Math.max(0, Number(payload.total || 0))
  const totalPages = Math.max(0, Number(payload.totalPages || 0))
  table.dataset.serverPage = String(page)
  table.dataset.serverPageSize = String(pageSize)
  table.dataset.serverTotal = String(total)
  let footer = query(root, `[data-server-pagination-for="${table.id}"]`)
  if (!footer) {
    footer = document.createElement('footer')
    footer.className = 'pagination table-pagination server-table-pagination'
    footer.dataset.serverPaginationFor = table.id
    footer.innerHTML = `
      <span class="table-pagination-summary" aria-live="polite"></span>
      <div class="table-pagination-actions">
        <button type="button" data-runtime-page="previous" data-runtime-page-target="${table.id}" aria-label="上一页">‹</button>
        <span class="table-pagination-current" aria-live="polite"></span>
        <button type="button" data-runtime-page="next" data-runtime-page-target="${table.id}" aria-label="下一页">›</button>
      </div>`
    const empty = query(root, `[data-table-empty="${table.id}"]`)
    if (empty) empty.insertAdjacentElement('afterend', footer)
    else table.insertAdjacentElement('afterend', footer)
  }
  footer.hidden = total === 0
  setText(footer, '.table-pagination-summary', total ? `第 ${(page - 1) * pageSize + 1}–${Math.min(total, page * pageSize)} 条，共 ${number(total)} 条` : '共 0 条')
  setText(footer, '.table-pagination-current', `${page} / ${Math.max(1, totalPages)} 页`)
  const previous = query(footer, '[data-runtime-page="previous"]')
  const next = query(footer, '[data-runtime-page="next"]')
  if (previous) previous.disabled = page <= 1
  if (next) next.disabled = totalPages === 0 || page >= totalPages
  queryAll(root, `[data-table-count="${table.id}"]`).forEach((node) => { node.textContent = number(total) })

  const state = serverQueryState(root, table)
  sessionStorage.setItem(serverStateKey(table.id), JSON.stringify({ ...state, page }))
}

function queryParameters(state) {
  const params = new URLSearchParams({ page: String(state.page), page_size: String(state.pageSize) })
  if (state.query) params.set('keyword', state.query)
  if (state.days) params.set('days', String(state.days))
  if (state.sort) params.set('sort', state.sort)
  return params
}

function exportParameters(state) {
  const params = queryParameters(state)
  params.delete('page')
  params.delete('page_size')
  return params
}

function beginStateRequest(root, state) {
  state.requestController?.abort()
  const controller = new AbortController()
  state.requestController = controller
  if (root.__dataRuntimeAbort?.signal.aborted) controller.abort()
  else root.__dataRuntimeAbort?.signal.addEventListener('abort', () => controller.abort(), { once: true })
  return { signal: controller.signal }
}

function renderIntelligenceItems(root, events) {
  const list = query(root, '#intel-results')
  if (!list) return
  const template = list.__runtimeItemTemplate?.cloneNode(true)
    || query(list, '.intel-result-item')?.cloneNode(true)
  if (!template) return
  const rows = events.map((item) => {
    const row = template.cloneNode(true)
    const type = eventType(item)
    const severity = severityOf(item)
    const eventTime = item.updatedTimeRaw || item.updated_time_raw || item.disclosureTimeRaw || item.disclosure_time_raw || item.disclosure_time || ''
    row.hidden = false
    row.dataset.category = type
    row.dataset.severity = severity
    row.dataset.industry = item.industry || ''
    row.dataset.status = item.is_exploited || item.isExploited ? 'exploited' : 'new'
    row.dataset.date = String(Date.parse(eventTime) || 0)
    row.dataset.severityRank = String({ critical: 4, high: 3, medium: 2, low: 1 }[severity] || 0)
    const thumb = query(row, '.intel-result-thumb')
    if (thumb) {
      const thumbType = type === 'data-leak' ? 'leak' : type
      thumb.className = `intel-result-thumb thumb-${thumbType}`
      thumb.innerHTML = type === 'vulnerability'
        ? '<svg viewBox="0 0 24 24" fill="none"><rect x="7" y="6" width="10" height="13" rx="4"/><path d="M9 6V4m6 2V4M4 10h3m10 0h3M4 15h3m10 0h3M9 12h6m-6 3h6"/></svg>'
        : type === 'ransomware'
          ? '<svg viewBox="0 0 24 24" fill="none"><path d="M6.5 3.5h7l4 4V20h-11Z"/><path d="M13.5 3.5V8h4"/><rect x="9" y="12" width="6.5" height="5.5" rx="1.2"/><path d="M10.6 12v-1a1.65 1.65 0 0 1 3.3 0v1M12.25 14.2v1.2"/></svg>'
          : '<svg viewBox="0 0 24 24" fill="none"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>'
    }
    const time = query(row, 'time')
    if (time) {
      time.textContent = formatDate(eventTime)
      if (eventTime) time.dateTime = new Date(eventTime).toISOString()
      else time.removeAttribute('datetime')
    }
    const relative = queryAll(row, '.intel-result-meta > span').find((node) => !node.classList.contains('badge'))
    if (relative) relative.textContent = relativeTime(eventTime)
    const badges = queryAll(row, '.intel-result-meta .badge')
    if (badges[0]) badges[0].textContent = severityLabel(severity)
    if (badges[1]) badges[1].textContent = eventTypeLabel(type)
    const title = query(row, 'h2 a')
    if (title) {
      title.textContent = item.title || '未命名事件'
      title.href = detailHref(item)
    }
    setText(row, 'p', excerpt(item.summary || item.detail_text, 260) || '暂无摘要')
    const context = queryAll(row, '.intel-result-context > *')
    const values = [item.attacker || item.vendor || item.source, item.cveId || item.cve_id || item.category, item.industry, item.region || item.country]
    context.forEach((node, index) => { node.textContent = values[index] || '—' })
    return row
  })
  list.replaceChildren(...rows)
  list.dispatchEvent(new CustomEvent('prototype:rows-updated'))
  for (const type of ['all', 'ransomware', 'data-leak', 'vulnerability']) {
    const count = type === 'all' ? rows.length : rows.filter((row) => row.dataset.category === type).length
    setText(root, `.intel-result-tabs [data-tab="${type}"] b`, count)
  }
}

const DASHBOARD_DAY_MS = 24 * 60 * 60 * 1000
const SHANGHAI_OFFSET_MS = 8 * 60 * 60 * 1000

function dashboardRangeStart(days, now = Date.now()) {
  const shanghaiNow = new Date(now + SHANGHAI_OFFSET_MS)
  const todayStart = Date.UTC(
    shanghaiNow.getUTCFullYear(),
    shanghaiNow.getUTCMonth(),
    shanghaiNow.getUTCDate(),
  ) - SHANGHAI_OFFSET_MS
  return todayStart - (Math.max(1, Number(days) || 1) - 1) * DASHBOARD_DAY_MS
}

function filterDashboardEventsByDays(items, days, now = Date.now()) {
  const start = dashboardRangeStart(days, now)
  return (items || []).filter((item) => {
    const timestamp = parseTimestamp(itemDateValue(item))
    return Number.isFinite(timestamp) && timestamp >= start && timestamp <= now
  })
}

function dashboardDayLabel(timestamp) {
  const date = new Date(timestamp + SHANGHAI_OFFSET_MS)
  return `${String(date.getUTCMonth() + 1).padStart(2, '0')}-${String(date.getUTCDate()).padStart(2, '0')}`
}

function buildDashboardDailySeries(items, days, now = Date.now()) {
  const start = dashboardRangeStart(days, now)
  const buckets = Array.from({ length: days }, (_, index) => ({
    date: dashboardDayLabel(start + index * DASHBOARD_DAY_MS),
    value: 0,
  }))
  for (const item of items || []) {
    const timestamp = parseTimestamp(itemDateValue(item))
    const index = Math.floor((timestamp - start) / DASHBOARD_DAY_MS)
    if (Number.isFinite(timestamp) && index >= 0 && index < buckets.length) buckets[index].value += 1
  }
  return buckets
}

function dashboardEventSearchText(item) {
  return [
    item?.title,
    item?.summary,
    item?.region,
    item?.country,
    item?.industry,
    item?.vendor,
    item?.product,
    item?.victim,
    item?.attacker,
    item?.cveId,
    item?.cve_id,
  ].filter(Boolean).join(' ').toLocaleLowerCase()
}

async function hydrateDashboard(root, state) {
  const table = clearTable(root, '#dashboard-events-table')
  const range = state.dashboardRange || query(root, '.situation-range .tab.active')?.dataset.tab || '7d'
  const days = { today: 1, '7d': 7, '30d': 30 }[range] || 7
  state.dashboardRange = range
  const selectedType = query(root, '.situation-table-toolbar .tabs .tab.active')?.dataset.tab || 'all'
  const selectedSeverity = query(root, '[data-filter-target="dashboard-events-table"][data-filter-key="severity"]')?.value || ''
  const searchText = String(query(root, '[data-table-search="dashboard-events-table"]')?.value || '').trim()
  const params = new URLSearchParams({ days: String(days) })
  params.set('event_type', selectedType === 'leak' ? 'data_leak' : selectedType)
  if (selectedSeverity) params.set('severity', selectedSeverity)
  if (searchText) params.set('keyword', searchText)
  const payload = await requestJson(`/api/dashboard/overview?${params.toString()}`, beginStateRequest(root, state))
  const kpis = payload.kpis || {}
  const highlights = payload.highlights || {}
  const trend = payload.dailyTrend || {}
  const events = payload.events || []
  setCounts(query(root, '.situation-kpi-grid'), [
    kpis.dataLeak || 0,
    kpis.ransomware || 0,
    kpis.vulnerability || 0,
    kpis.highRisk || 0,
  ])
  const dashboardCards = queryAll(root, '.situation-kpi-grid .situation-kpi')
  const leakTop = highlights.dataLeakTop
  const kpiHighlights = [
    leakTop ? `${leakTop.name} ${number(leakTop.value)} 条` : '本期无新增',
    `${number(highlights.activeRansomwareActors)} 个活跃团伙`,
    `${number(highlights.exploitedVulnerabilities)} 项已利用`,
    `${number(highlights.highRisk)} 条需优先研判`,
  ]
  dashboardCards.forEach((card, index) => {
    setText(card, '.situation-kpi-head b', kpiHighlights[index])
  })
  ;[
    trend.dataLeak || [],
    trend.ransomware || [],
    trend.vulnerability || [],
    trend.highRisk || [],
  ].forEach((values, index) => {
    const path = query(dashboardCards[index], '.situation-spark path')
    if (!path) return
    const points = chartPoints(values, { xStart: 2, xEnd: 118, yTop: 4, yBottom: 24 })
    path.setAttribute('d', linePath(points))
  })

  replaceRows(table, events, (row, item) => {
    const cells = queryAll(row, 'td')
    const type = eventType(item)
    row.dataset.category = type === 'data-leak' ? 'leak' : type
    row.dataset.severity = severityOf(item)
    setCell(cells[0], formatDate(item.updatedTimeRaw || item.disclosureTimeRaw || item.disclosureDate))
    setCell(cells[1], item.title, excerpt(item.summary, 120) || item.category || '暂无摘要')
    setCell(cells[2], eventTypeLabel(type))
    setCell(cells[3], item.region || item.country)
    setCell(cells[4], item.industry, item.vendor || item.product || item.victim)
    setBadgeCell(cells[5], severityLabel(severityOf(item)), severityOf(item))
    setCell(cells[6], item.monitoringPriority || (item.isExploited ? '已利用' : '—'))
    setActionCell(cells[7], '查看', detailHref(item))
  })

  const countries = payload.countries || []
  const maxCountryValue = Math.max(1, ...countries.map((item) => Number(item.value || 0)))
  queryAll(root, '.situation-region-rank .compact-bar').forEach((row, index) => {
    const item = countries[index]
    row.hidden = !item
    if (!item) return
    setText(row, ':scope > span', item.name)
    setText(row, ':scope > b', number(item.value))
    query(row, '.bar-fill-v2')?.style.setProperty('--bar', `${Math.round(Number(item.value || 0) / maxCountryValue * 100)}%`)
  })
  const positionedCountries = countries.filter((item) => COUNTRY_COORDINATES[String(item.code || '').toUpperCase()]).slice(0, 5)
  const mapPoints = queryAll(root, '.situation-world .map-point')
  const mapLabels = queryAll(root, '.situation-map-label')
  mapPoints.forEach((point, index) => {
    const item = positionedCountries[index]
    point.hidden = !item
    if (!item) return
    point.title = `${item.name}：${number(item.count)} 条，风险指数 ${number(item.risk)}`
  })
  mapLabels.forEach((label, index) => {
    const item = positionedCountries[index]
    label.hidden = !item
    if (!item) return
    label.style.right = 'auto'
    label.textContent = `${item.name} · ${number(item.count)}`
  })
  const mapWorld = query(root, '.situation-world')
  const mapImage = query(root, '.situation-world-map')
  const positionMapAnnotations = () => {
    if (!mapWorld || !mapImage) return
    const boxWidth = mapImage.clientWidth
    const boxHeight = mapImage.clientHeight
    const imageRatio = (mapImage.naturalWidth || 1200) / (mapImage.naturalHeight || 540)
    const boxRatio = boxWidth / Math.max(1, boxHeight)
    const renderedWidth = boxRatio > imageRatio ? boxHeight * imageRatio : boxWidth
    const renderedHeight = boxRatio > imageRatio ? boxHeight : boxWidth / imageRatio
    const originLeft = mapImage.offsetLeft + (boxWidth - renderedWidth) / 2
    const originTop = mapImage.offsetTop + (boxHeight - renderedHeight) / 2
    mapPoints.forEach((point, index) => {
      const item = positionedCountries[index]
      if (!item) return
      const [longitude, latitude] = COUNTRY_COORDINATES[String(item.code).toUpperCase()]
      point.style.left = `${originLeft + (longitude + 180) / 360 * renderedWidth}px`
      point.style.top = `${originTop + (90 - latitude) / 180 * renderedHeight}px`
      point.style.transform = 'translate(-50%, -50%)'
    })
    mapLabels.forEach((label, index) => {
      const item = positionedCountries[index]
      if (!item) return
      const [longitude, latitude] = COUNTRY_COORDINATES[String(item.code).toUpperCase()]
      const pointLeft = originLeft + (longitude + 180) / 360 * renderedWidth
      const pointTop = originTop + (90 - latitude) / 180 * renderedHeight
      const code = String(item.code).toUpperCase()
      let desiredLeft = pointLeft - label.offsetWidth / 2
      let desiredTop = pointTop - label.offsetHeight - 12
      if (code === 'CA') {
        desiredLeft = pointLeft - label.offsetWidth - 10
        desiredTop = pointTop - label.offsetHeight - 4
      } else if (code === 'US') {
        desiredLeft = pointLeft + 10
        desiredTop = pointTop + 4
      }
      const left = Math.max(4, Math.min(mapWorld.clientWidth - label.offsetWidth - 4, desiredLeft))
      const top = Math.max(4, Math.min(mapWorld.clientHeight - label.offsetHeight - 4, desiredTop))
      label.style.left = `${left}px`
      label.style.top = `${top}px`
    })
  }
  root.__situationMapObserver?.disconnect()
  if (typeof ResizeObserver !== 'undefined' && mapWorld) {
    root.__situationMapObserver = new ResizeObserver(positionMapAnnotations)
    root.__situationMapObserver.observe(mapWorld)
    root.__dataRuntimeAbort?.signal.addEventListener('abort', () => root.__situationMapObserver?.disconnect(), { once: true })
  }
  if (mapImage?.complete) positionMapAnnotations()
  else mapImage?.addEventListener('load', positionMapAnnotations, { once: true })
  queryAll(root, '.situation-route').forEach((routeNode) => { routeNode.hidden = true })
  const averageRisk = countries.length
    ? Math.round(countries.reduce((sum, item) => sum + Number(item.risk || 0), 0) / countries.length)
    : 0
  setText(root, '.situation-map-foot > b strong', number(averageRisk))
  const industries = payload.industries || []
  queryAll(root, '.industry-heat-list > div').forEach((row, index) => {
    const item = industries[index]
    row.hidden = !item
    if (!item) return
    setText(row, 'b', String(index + 1).padStart(2, '0'))
    setText(row, 'strong', item.name)
    setText(row, 'small', `${number(item.count)} 条真实事件`)
    setText(row, 'em', number(item.value))
  })
  queryAll(root, '.situation-watch-list a').forEach((link, index) => {
    const item = events[index]
    link.hidden = !item
    if (!item) return
    const type = eventType(item)
    link.href = detailHref(item)
    const kind = query(link, '.watch-kind')
    if (kind) kind.dataset.kind = type || 'intelligence'
    setText(link, '.watch-kind', eventTypeLabel(type))
    setText(link, 'div strong', item.title || '未命名事件')
    setText(link, 'div small', [item.region || item.country, item.industry].filter(Boolean).join(' · ') || '实时情报')
    setText(link, ':scope > b', severityLabel(severityOf(item)))
  })
  setText(root, '.situation-watch-card .panel-header .badge', number(Math.min(4, events.length)))
  const distributionState = payload.distribution || {}
  const distribution = [
    distributionState.ransomware || 0,
    distributionState.dataLeak || 0,
    distributionState.vulnerability || 0,
    distributionState.documentExposure || 0,
  ]
  const periodLabel = { today: '今日', '7d': '近 7 天', '30d': '近 30 天' }[range] || '近 7 天'
  queryAll(root, '.situation-donut-legend .legend-item b').forEach((node, index) => {
    node.textContent = number(distribution[index] ?? 0)
  })
  setText(root, '.situation-donut-card .meta', periodLabel)
  setText(root, '.situation-donut-legend .legend-item:nth-child(4) span', '文件监测')
  const distributionTotal = distribution.reduce((sum, value) => sum + value, 0)
  setText(root, '.situation-donut .donut-core strong', number(distributionTotal))
  const donut = query(root, '.situation-donut')
  if (donut) {
    donut.setAttribute('aria-label', `${periodLabel}情报类型分布：勒索 ${distribution[0]}，数据泄露 ${distribution[1]}，漏洞 ${distribution[2]}，文件监测 ${distribution[3]}`)
    setConicChart(donut, distribution, ['var(--danger)', 'var(--warning)', 'var(--accent)', 'var(--secondary)'], '--runtime-donut')
  }
  const labels = trend.labels || []
  const totalTrend = trend.total || []
  const highTrend = trend.highRisk || []
  const totalPoints = chartPoints(totalTrend, { xStart: 36, xEnd: 602, yTop: 28, yBottom: 160 })
  const highPoints = chartPoints(highTrend, { xStart: 36, xEnd: 602, yTop: 28, yBottom: 160 })
  query(root, '.situation-trend-chart .trend-line.total')?.setAttribute('d', linePath(totalPoints))
  query(root, '.situation-trend-chart .trend-line.critical')?.setAttribute('d', linePath(highPoints))
  query(root, '.situation-trend-chart .trend-area')?.setAttribute('d', areaPath(highPoints, 160))
  const severityDistribution = payload.severityDistribution || {}
  const trendTotals = [
    severityDistribution.critical || 0,
    severityDistribution.high || 0,
    severityDistribution.mediumLow || 0,
  ]
  queryAll(root, '.trend-summary > div strong').forEach((node, index) => { node.textContent = number(trendTotals[index] || 0) })
  const trendLabels = ['严重', '高危', '中低危']
  queryAll(root, '.trend-summary > div span').forEach((node, index) => { node.textContent = trendLabels[index] || node.textContent })
  const axisNodes = queryAll(root, '.trend-axis-labels span')
  axisNodes.forEach((node, index) => {
    if (!labels.length) {
      node.textContent = '—'
      return
    }
    const labelIndex = axisNodes.length === 1 ? labels.length - 1 : Math.round(index * (labels.length - 1) / (axisNodes.length - 1))
    node.textContent = labels[labelIndex] || '—'
  })
  const monitoring = payload.monitoringStatus || {}
  setText(root, '.situation-status-strip > div:first-child strong', monitoring.statusLabel || monitoring.statusValue || '监测状态未提供')
  setText(root, '.situation-status-strip > div:first-child small', monitoring.subtitle || monitoring.refreshedValue || '实时接口数据')
  const pendingCount = Number(kpis.highRisk || 0)
  const statusValues = [countries.length, industries.length, pendingCount]
  queryAll(root, '.situation-status-strip > div').slice(1).forEach((item, index) => {
    setText(item, 'strong', number(statusValues[index] || 0))
  })

  const cards = queryAll(root, '.rank-card')
  const rankings = payload.rankings || {}
  fillRankCard(cards[0], rankings.ransomwareActors || [], '当前周期最活跃')
  fillRankCard(cards[1], rankings.dataLeakTypes || [], '当前周期占比最高')
  fillRankCard(cards[2], rankings.vulnerabilityVendors || [], '当前周期重点厂商')
  const refresh = queryAll(root, 'button[data-toast]').find((button) => button.textContent.includes('刷新总览'))
  if (refresh) {
    refresh.dataset.runtimeRefresh = 'dashboard'
    setActionAvailable(refresh, true)
  }
  queryAll(root, '.situation-range .tab').forEach((button) => {
    if (button.dataset.runtimeRangeBound) return
    button.dataset.runtimeRangeBound = '1'
    button.addEventListener('click', async () => {
      state.dashboardRange = button.dataset.tab || '7d'
      queryAll(root, '.situation-range .tab').forEach((candidate) => {
        const active = candidate === button
        candidate.classList.toggle('active', active)
        candidate.setAttribute('aria-selected', String(active))
      })
      setDataState(root, 'loading', '正在按统计周期刷新真实数据…')
      try {
        await hydrateDashboard(root, state)
        setDataState(root, 'ready')
      } catch (error) {
        showLoadError(root, error)
      }
    })
  })
  state.refresh = () => hydrateDashboard(root, state)
}

async function hydrateIntelligence(root, state) {
  const list = query(root, '#intel-results')
  if (!list) return
  list.__runtimeItemTemplate ||= query(list, '.intel-result-item')?.cloneNode(true)
  restoreServerState(root, list)
  const listState = serverQueryState(root, list)
  const params = queryParameters(listState)
  if (listState.tab !== 'all') params.set('types', listState.tab)
  const payload = await requestJson(`/api/intelligence/search?${params.toString()}`, beginStateRequest(root, state))
  const events = payload.items || []
  renderIntelligenceItems(root, events)
  const typeCounts = payload.typeCounts || {}
  for (const type of ['all', 'ransomware', 'data-leak', 'vulnerability']) {
    const count = type === 'all'
      ? Number(payload.total || 0)
      : Number(typeCounts[type.replace('-', '_')] || 0)
    setText(root, `.intel-result-tabs [data-tab="${type}"] b`, number(count))
  }
  const recent = payload.recent24hByType || {}
  const values = [
    recent.ransomware || 0,
    recent.data_leak || 0,
    recent.vulnerability || 0,
    payload.recent24h || 0,
  ]
  queryAll(root, '.intel-corpus-item b').forEach((node, index) => { node.textContent = number(values[index]) })
  updateServerPagination(root, list, payload)
  state.refresh = () => hydrateIntelligence(root, state)
  const exportParams = exportParameters(listState)
  if (listState.tab !== 'all') exportParams.set('types', listState.tab)
  markExports(root, state, ['#intel-results'], `/api/intelligence/export?dataset=search&${exportParams.toString()}`)
}

async function hydrateRansomware(root, state) {
  const table = clearTable(root, '#ransomware-table')
  if (!table) return
  restoreServerState(root, table)
  const listState = serverQueryState(root, table)
  const params = queryParameters(listState)
  if (listState.tab !== 'all') params.set('stage', listState.tab)
  if (listState.filters.industry) params.set('industry', listState.filters.industry)
  const payload = await requestJson(`/api/intelligence/ransomware?${params.toString()}`, beginStateRequest(root, state))
  const items = payload.items || payload.ransomwareEvents || []
  const industrySelect = query(root, '[data-filter-target="ransomware-table"][data-filter-key="industry"]')
  replaceFilterOptions(
    root,
    '[data-filter-target="ransomware-table"][data-filter-key="industry"]',
    '全部行业',
    (payload.ransomwareIndustryImpact || []).map((item) => item.name),
  )
  restoreFilterValue(industrySelect, listState.filters.industry)
  const stageOf = (item) => {
    const stage = String(`${item.category || ''} ${item.title || ''}`).toLowerCase()
    if (/发布|公开|published|released|leak/.test(stage)) return { key: 'published', label: item.category || '已发布', tone: 'critical' }
    if (/倒计时|谈判|countdown|negotiat/.test(stage)) return { key: 'countdown', label: item.category || '倒计时', tone: 'high' }
    return { key: 'disclosed', label: item.category || '新披露', tone: '' }
  }
  replaceRows(table, items, (row, item) => {
    const cells = queryAll(row, 'td')
    const stage = stageOf(item)
    row.dataset.category = stage.key
    row.dataset.industry = item.industry || ''
    setCell(cells[0], formatDate(item.disclosureTimeRaw || item.disclosureDate))
    setCell(cells[1], item.victim || item.title, item.title)
    setCell(cells[2], item.attacker || item.sourceSite)
    setBadgeCell(cells[3], stage.label, stage.tone)
    setCell(cells[4], item.industry)
    setCell(cells[5], item.region || item.country)
    setActionCell(cells[6], '查看', detailHref(item))
  })
  const actors = (payload.ransomwareActorRanking || []).slice(0, 4)
  const actorRows = queryAll(root, '.actor-rank')
  setText(root, '.actor-focus .panel-header .meta', `累计 ${number(payload.total)} 条`)
  actorRows.forEach((row, index) => {
    const item = actors[index]
    row.hidden = !item
    if (!item) return
    setText(row, 'b', String(index + 1).padStart(2, '0'))
    setText(row, 'strong', item.name)
    setText(row, 'span', `${number(item.value)} 起 · 占比 ${Math.round(item.value / Math.max(1, payload.total) * 100)}%`)
    const score = `${Math.round(item.value / Math.max(1, actors[0]?.value || 1) * 100)}%`
    const scoreBar = query(row, 'i')
    scoreBar?.style.setProperty('--score', score)
    if (scoreBar) scoreBar.style.width = score
  })
  const timeline = payload.timeline || []
  queryAll(root, '.timeline-feed li').forEach((row, index) => {
    const item = timeline[timeline.length - 1 - index]
    row.hidden = !item
    if (!item) return
    setText(row, 'time', item.date)
    setText(row, 'strong', `${number(item.value)} 起事件`)
    setText(row, 'span', '数据库聚合')
  })
  setText(root, '.action-feed .pulse-label', '接口数据')
  updateServerPagination(root, table, payload)
  state.refresh = () => hydrateRansomware(root, state)
  const exportParams = exportParameters(listState)
  if (listState.tab !== 'all') exportParams.set('stage', listState.tab)
  if (listState.filters.industry) exportParams.set('industry', listState.filters.industry)
  markExports(root, state, ['#ransomware-table'], `/api/intelligence/export?dataset=ransomware&${exportParams.toString()}`)
}


function leakSource(item) {
  const raw = String(item.raw_source_type || item.event_type || item.sourceSite || '').toLowerCase()
  if (/telegram|chat|即时/.test(raw)) return 'chat'
  if (/victim|ransom|勒索/.test(raw)) return 'ransom'
  if (/forum|论坛/.test(raw)) return 'forum'
  return 'public'
}

async function hydrateDataLeak(root, state) {
  const table = clearTable(root, '#data-leak-table')
  if (!table) return
  restoreServerState(root, table)
  const listState = serverQueryState(root, table)
  const params = queryParameters(listState)
  if (listState.filters.classification) params.set('category', listState.filters.classification)
  if (listState.filters.attacker) params.set('attacker', listState.filters.attacker)
  if (listState.filters.industry) params.set('industry', listState.filters.industry)
  if (listState.source) params.set('source', listState.source)
  const payload = await requestJson(`/api/intelligence/data-leak?${params.toString()}`, beginStateRequest(root, state))
  const items = payload.items || payload.dataLeakEvents || []
  const classificationSelect = query(root, '[data-filter-target="data-leak-table"][data-filter-key="classification"]')
  const attackerSelect = query(root, '[data-filter-target="data-leak-table"][data-filter-key="attacker"]')
  const industrySelect = query(root, '[data-filter-target="data-leak-table"][data-filter-key="industry"]')
  replaceFilterOptions(root, '[data-filter-target="data-leak-table"][data-filter-key="classification"]', '全部事件分类', payload.categories || [])
  replaceFilterOptions(root, '[data-filter-target="data-leak-table"][data-filter-key="attacker"]', '全部攻击者', (payload.attackers || items.map((item) => item.attacker || item.sourceSite)).filter(Boolean))
  replaceFilterOptions(root, '[data-filter-target="data-leak-table"][data-filter-key="industry"]', '全部行业', (payload.industries || items.map((item) => item.industry)).filter(Boolean))
  restoreFilterValue(classificationSelect, listState.filters.classification)
  restoreFilterValue(attackerSelect, listState.filters.attacker)
  restoreFilterValue(industrySelect, listState.filters.industry)
  replaceRows(table, items, (row, item) => {
    const cells = queryAll(row, 'td')
    const disclosedAt = item.disclosureTimeRaw || item.disclosureDate
    const updatedAt = item.updatedTimeRaw || item.updated_time_raw || disclosedAt
    const classification = item.category || '未分类'
    const attacker = item.attacker || item.sourceSite || '未披露'
    row.dataset.discoveredAt = disclosedAt || updatedAt || ''
    row.dataset.classification = classification
    row.dataset.attacker = attacker
    row.dataset.industry = item.industry || ''
    row.dataset.source = leakSource(item)
    setCell(cells[0], formatFullDate(disclosedAt))
    setCell(cells[1], formatFullDate(updatedAt, true))
    setCell(cells[2], item.title || item.victim || '未命名事件')
    setCell(cells[3], classification)
    setCell(cells[4], attacker)
    setCell(cells[5], item.industry || '—')
    setActionCell(cells[6], '查看', detailHref(item))
  })
  const sourceRows = queryAll(root, '.source-row')
  const sourceKeys = ['forum', 'chat', 'ransom', 'public']
  const sourceCounts = payload.sourceCounts || {}
  const sourceTotal = Object.values(sourceCounts).reduce((sum, value) => sum + Number(value || 0), 0)
  sourceRows.forEach((button, index) => {
    const sourceKey = sourceKeys[index]
    const sourceCount = Number(sourceCounts[sourceKey] || 0)
    setText(button, 'small', `${number(sourceCount)} 条`)
    setText(button, 'b', `${Math.round(sourceCount / Math.max(1, sourceTotal) * 100)}%`)
    button.dataset.runtimeSource = sourceKey
    button.classList.toggle('active', sourceKey === listState.source)
    setActionAvailable(button, true)
  })
  state.sourceTable = table
  updateServerPagination(root, table, payload)
  state.refresh = () => hydrateDataLeak(root, state)
  const exportParams = exportParameters(listState)
  if (listState.filters.classification) exportParams.set('category', listState.filters.classification)
  if (listState.filters.attacker) exportParams.set('attacker', listState.filters.attacker)
  if (listState.filters.industry) exportParams.set('industry', listState.filters.industry)
  if (listState.source) exportParams.set('source', listState.source)
  markExports(root, state, ['#data-leak-table'], `/api/intelligence/export?dataset=data_leak&${exportParams.toString()}`)
}

async function hydrateVulnerabilities(root, state) {
  const table = clearTable(root, '#vulnerability-table')
  if (!table) return
  restoreServerState(root, table)
  const listState = serverQueryState(root, table)
  const days = Number(state.vulnerabilityDays || listState.days || 7)
  state.vulnerabilityDays = days
  const params = queryParameters({ ...listState, days })
  if (listState.tab !== 'all') params.set('severity', listState.tab)
  if (listState.filters.industry) params.set('industry', listState.filters.industry)
  const payload = await requestJson(`/api/vulnerabilities?${params.toString()}`, beginStateRequest(root, state))
  const items = payload.items || []
  const summary = payload.summary || {}
  const industrySelect = query(root, '[data-filter-target="vulnerability-table"][data-filter-key="industry"]')
  replaceFilterOptions(root, '[data-filter-target="vulnerability-table"][data-filter-key="industry"]', '全部行业', ['基础设施软件'])
  restoreFilterValue(industrySelect, listState.filters.industry)
  setCounts(query(root, '.vuln-intel-kpis'), [summary.total || payload.total, summary.criticalCvss, summary.exploited, summary.patched])
  replaceRows(table, items, (row, item) => {
    const cells = queryAll(row, 'td')
    const severity = severityOf(item)
    row.dataset.category = severity
    row.dataset.severity = severity
    row.dataset.industry = item.industry || ''
    setCell(cells[0], formatDate(item.disclosureTimeRaw || item.disclosure_time_raw || item.disclosureDate, false))
    setCell(cells[1], item.cveId || item.cve_id || item.id, item.title)
    setCell(cells[2], item.vendor, item.product)
    setCell(cells[3], item.industry)
    setCell(cells[4], item.cvss ?? '—')
    setBadgeCell(cells[5], item.isExploited || item.is_exploited ? '已利用' : '未确认', item.isExploited || item.is_exploited ? 'critical' : '')
    setCell(cells[6], item.patchAvailable || item.patch_available ? '可用' : '暂无')
    setActionCell(cells[7], '查看', detailHref(item))
  })
  const severityCounts = ['critical', 'high', 'medium', 'low'].map((key) => ({ name: severityLabel(key), value: Number(payload.severityCounts?.[key] || 0) }))
  setText(root, '.severity-donut strong', number(payload.total))
  setText(root, '.severity-donut-card .meta', `${number(payload.total)} 条`)
  fillNamedRows(query(root, '.severity-legend'), severityCounts)
  setConicChart(query(root, '.severity-donut'), severityCounts.map((item) => item.value), ['var(--danger)', 'var(--warning)', 'var(--accent)', 'var(--secondary)'])
  fillNamedRows(query(root, '.vendor-bars'), payload.vendorRanking || [])
  queryAll(root, '.industry-block').forEach((button, index) => {
    const item = index === 0 ? { name: '基础设施软件', value: payload.total } : null
    button.hidden = !item
    if (!item) return
    setText(button, 'strong', item.name)
    setText(button, 'span', number(item.value))
    button.dataset.runtimeFilter = '[data-table-search="vulnerability-table"]'
    button.dataset.runtimeFilterValue = item.name
    button.removeAttribute('data-toast')
    setActionAvailable(button, true)
  })
  queryAll(root, '.product-bubble').forEach((button, index) => {
    const item = (payload.productRanking || [])[index]
    button.hidden = !item
    if (!item) return
    setText(button, 'strong', item.name)
    setText(button, 'span', number(item.value))
    button.dataset.runtimeFilter = '[data-table-search="vulnerability-table"]'
    button.dataset.runtimeFilterValue = item.name
    button.removeAttribute('data-toast')
    setActionAvailable(button, true)
  })
  const exploited = Number(summary.exploited || 0)
  const patched = Number(summary.patched || 0)
  setText(root, '.ring-kev strong', exploited)
  setConicChart(query(root, '.ring-kev'), [exploited, Math.max(0, payload.total - exploited)], ['var(--danger)', 'var(--bg)'])
  setText(root, '.ring-poc strong', '—')
  setConicChart(query(root, '.ring-poc'), [], ['var(--warning)'])
  const signalValues = [['已确认利用', number(exploited)], ['补丁可用', number(patched)], ['PoC 数据', '—']]
  queryAll(root, '.signal-source-list > div').forEach((row, index) => {
    setText(row, 'span', signalValues[index]?.[0] || '—')
    setText(row, 'b', signalValues[index]?.[1] || '—')
  })
  const trend = (payload.timeline || []).map((item) => ({ date: item.date, value: Number(item.value || 0) }))
  const values = trend.map((item) => item.value)
  const points = chartPoints(values, { xStart: 34, xEnd: 700, yTop: 35, yBottom: 185 })
  query(root, '.vuln-line-path')?.setAttribute('d', linePath(points))
  query(root, '.vuln-area-path')?.setAttribute('d', areaPath(points, 205))
  const markerPoints = evenlySample(points, queryAll(root, '.vuln-points circle').length)
  setChartMarkers(query(root, '.vuln-points'), 'circle', markerPoints, (circle, point) => {
    circle.setAttribute('cx', point.x.toFixed(1)); circle.setAttribute('cy', point.y.toFixed(1))
  })
  setChartMarkers(query(root, '.vuln-chart-values'), 'text', markerPoints, (node, point) => {
    node.textContent = number(point.value); node.setAttribute('x', point.x.toFixed(1)); node.setAttribute('y', Math.max(20, point.y - 10).toFixed(1))
  })
  const sampledTrend = evenlySample(trend, queryAll(root, '.chart-labels text').length)
  queryAll(root, '.chart-labels text').forEach((node, index) => {
    const point = markerPoints[index]; const item = sampledTrend[index]
    node.hidden = !item
    if (!item || !point) return
    node.textContent = item.date.slice(5); node.setAttribute('x', point.x.toFixed(1))
  })
  setText(root, '.vuln-trend-card .trend-summary strong', number(payload.total))
  setText(root, '.vuln-trend-card .panel-header .meta', `近 ${days} 天`)
  const periodButtons = queryAll(root, '[data-od-id="vulnerability-action-section"] .page-actions button')
  periodButtons.forEach((button) => {
    const buttonDays = button.textContent.includes('今日') ? 1 : button.textContent.includes('30') ? 30 : 7
    button.classList.toggle('btn-primary', buttonDays === days)
    button.classList.toggle('btn-secondary', buttonDays !== days)
    if (button.dataset.runtimePeriodBound) return
    button.dataset.runtimePeriodBound = '1'
    button.addEventListener('click', async () => {
      state.vulnerabilityDays = buttonDays
      table.dataset.serverPage = '1'
      await hydrateVulnerabilities(root, state)
    })
  })
  updateServerPagination(root, table, payload)
  state.refresh = () => hydrateVulnerabilities(root, state)
  const exportParams = exportParameters({ ...listState, days })
  if (listState.tab !== 'all') exportParams.set('severity', listState.tab)
  if (listState.filters.industry) exportParams.set('industry', listState.filters.industry)
  markExports(root, state, ['#vulnerability-table'], `/api/vulnerabilities/export?${exportParams.toString()}`)
}


function replaceRecordContainer(container, lines) {
  if (!container) return
  const values = lines.length ? lines : ['当前记录未提供结构化数据']
  const template = container.firstElementChild?.cloneNode(true)
  if (!template) {
    container.textContent = values.join('；')
    return
  }
  const rows = values.map((line, index) => {
    const row = template.cloneNode(true)
    const children = [...row.children]
    if (children[0]) children[0].textContent = index === 0 ? '实时证据' : `证据 ${index + 1}`
    if (children[1]) children[1].textContent = String(line)
    if (children[2]) children[2].textContent = ''
    if (!children.length) row.textContent = String(line)
    return row
  })
  container.replaceChildren(...rows)
}

function replaceStructuredRows(container, rows) {
  if (!container) return
  const values = (rows || []).filter((item) => item && item.value != null && item.value !== '')
  if (!values.length) {
    container.replaceChildren()
    return
  }
  const template = container.firstElementChild?.cloneNode(true) || document.createElement('div')
  container.replaceChildren(...values.map((item) => {
    const row = template.cloneNode(true)
    row.hidden = false
    const children = [...row.children]
    if (children[0]) children[0].textContent = item.label || '实时数据'
    if (children[1]) children[1].textContent = String(item.value)
    if (children[2]) children[2].textContent = item.note || ''
    if (!children.length) row.textContent = `${item.label ? `${item.label}：` : ''}${item.value}`
    return row
  }))
}

function setDefinitionPairs(container, pairs) {
  if (!container) return
  const rows = queryAll(container, ':scope > div')
  rows.forEach((row, index) => {
    const pair = pairs[index]
    const value = pair?.value
    const available = value != null && value !== '' && (!Array.isArray(value) || value.length > 0)
    row.hidden = !pair || !available
    if (!pair || !available) return
    const labelNode = query(row, ':scope > span, :scope > dt')
    const valueNode = query(row, ':scope > strong, :scope > a, :scope > dd')
    if (labelNode) labelNode.textContent = pair.label
    if (!valueNode) return
    if (pair.url) {
      const link = document.createElement('a')
      link.className = valueNode.className
      link.href = pair.url
      link.target = '_blank'
      link.rel = 'noopener noreferrer'
      link.textContent = String(value)
      valueNode.replaceWith(link)
    } else {
      valueNode.textContent = Array.isArray(value) ? value.join(' / ') : String(value)
    }
  })
}

function setDetailSection(root, id, visible) {
  const section = query(root, `[data-od-id="${id}"]`)
  if (section) section.hidden = !visible
  return section
}

function hideDetailRail(root, id) {
  const rail = setDetailSection(root, id, false)
  rail?.parentElement?.classList.add('runtime-single-column')
}

function normalizedResourceList(...groups) {
  const resources = []
  const seen = new Set()
  groups.flat(Infinity).forEach((item) => {
    const url = typeof item === 'string' ? item : item?.url || item?.href || ''
    if (!url || (!/^https?:\/\//i.test(url) && !String(url).startsWith('/')) || seen.has(url)) return
    seen.add(url)
    resources.push({
      url: String(url),
      label: typeof item === 'object' ? (item.label || item.kind || item.name || '证据资源') : '证据资源',
      kind: typeof item === 'object' ? (item.kind || '') : '',
    })
  })
  return resources
}

function detailRiskLines(detail) {
  const monitoring = (detail.monitoring_matches || detail.monitoringMatches || []).map((item) =>
    typeof item === 'string' ? item : item?.reason || item?.label || item?.name,
  )
  return [
    ...(detail.risk_reasons || detail.riskReasons || []),
    ...(detail.riskAnalysis?.reasons || []),
    ...monitoring,
  ].filter(Boolean)
}

function setHeroSourceLogo(root, platform) {
  const image = query(root, '.detail-source-logo img')
  if (!image) return
  const key = sourceLogoKey(platform)
  const assets = {
    github: '/assets/logos/github.png',
    gitlab: '/assets/logos/gitlab.png',
    gitee: '/assets/logos/gitee.png',
    'baidu-doc': '/assets/logos/baidu-wenku.svg',
    'baidu-disk': '/assets/logos/baidu-netdisk.png',
    aliyun: '/assets/logos/alipan.png',
    quark: '/assets/logos/quark.png',
    onedrive: '/assets/logos/onedrive.png',
    doc88: '/assets/logos/doc88.png',
    docin: '/assets/logos/docin.png',
    csdn: '/assets/logos/csdn.png',
  }
  const asset = assets[key]
  image.hidden = !asset
  if (asset) {
    image.src = asset
    image.alt = `${platform || '来源平台'}标志`
  }
}

function configureSourceAccess(root, config) {
  const {
    sectionId,
    openId,
    viewId,
    downloadId,
    sourceUrl = '',
    resources = [],
    fetchedAt = '',
  } = config
  const section = query(root, `[data-od-id="${sectionId}"]`)
  if (!section) return
  const normalized = normalizedResourceList(resources)
  const directSource = /^https?:\/\//i.test(sourceUrl) || String(sourceUrl).startsWith('/') ? sourceUrl : ''
  const source = directSource || normalized.find((item) => /原始|通告|仓库|文件/.test(item.label))?.url || ''
  const mirror = normalized.find((item) => /screenshot|image/i.test(item.kind))
    || normalized.find((item) => /截图|image/i.test(item.label))
    || normalized.find((item) => /mirror/i.test(item.kind))
    || normalized.find((item) => /镜像/.test(item.label))
  const downloadable = normalized.find((item) => /artifact|html|json/i.test(item.kind))
    || normalized.find((item) => /镜像|原始抓取|JSON/i.test(item.label))

  const open = query(root, `[data-od-id="${openId}"]`)
  if (open) {
    open.hidden = !source
    if (source) open.href = source
    else open.removeAttribute('href')
  }
  const sourceLine = query(section, '.source-link-line')
  const sourceLink = query(sourceLine, 'a')
  const copy = query(sourceLine, 'button')
  if (sourceLine) sourceLine.hidden = !source
  if (sourceLink) {
    sourceLink.hidden = !source
    if (source) {
      sourceLink.href = source
      sourceLink.textContent = source
    }
  }
  if (copy) {
    copy.dataset.runtimeCopy = source
    setActionAvailable(copy, Boolean(source), source ? '' : '接口未提供原始链接')
  }

  const view = query(root, `[data-od-id="${viewId}"]`)
  if (view) {
    delete view.dataset.toast
    view.dataset.runtimeOpen = mirror?.url || ''
    setActionAvailable(view, Boolean(mirror), mirror ? '' : '接口未提供镜像资源')
  }
  const download = query(root, `[data-od-id="${downloadId}"]`)
  if (download) {
    delete download.dataset.toast
    download.dataset.runtimeDownload = downloadable?.url || ''
    setActionAvailable(download, Boolean(downloadable), downloadable ? '' : '接口未提供可下载镜像')
  }

  const figure = query(section, '.mirror-frame')
  if (figure) {
    figure.hidden = !mirror
    const slot = query(figure, '.mirror-image-slot')
    if (slot && mirror) {
      slot.replaceChildren()
      if (mirror.kind === 'screenshot' || /截图|image/i.test(mirror.label)) {
        const image = document.createElement('img')
        image.className = 'runtime-mirror-image'
        image.src = mirror.url
        image.alt = mirror.label
        slot.appendChild(image)
      } else {
        const label = document.createElement('strong')
        label.textContent = mirror.label
        slot.appendChild(label)
      }
    }
    setText(figure, 'figcaption strong', mirror?.label || '—')
    setText(figure, 'figcaption span', normalized.length ? `${normalized.length} 个真实资源` : '—')
    setText(figure, 'figcaption code', '')
    setText(figure, '.mirror-frame-bar time', formatDate(fetchedAt))
  }
  section.hidden = !source && !normalized.length
}

function bindDetailBase(root, detail, summaryPairs, kpiPairs) {
  setText(root, 'main h1', detail.title || detail.repositoryFullName || detail.repositoryName || '未命名记录')
  setText(root, '[data-detail-record-id]', detail.identifier || detail.id)
  setText(root, '.lead', usableText(detail.summary) || usableText(detail.detail_text) || usableText(detail.codePreview) || '暂无摘要')
  setSummary(query(root, '.detail-summary'), summaryPairs)
  const kpis = queryAll(root, '.detail-kpi')
  kpis.forEach((card, index) => {
    if (!kpiPairs[index]) return
    const [label, value, note] = kpiPairs[index]
    setText(card, 'span', label)
    setText(card, 'strong', value)
    setText(card, 'small', note || '实时数据')
  })
  const badge = query(root, '.detail-hero .badge')
  if (badge) badge.textContent = severityLabel(severityOf(detail))
}

function reviewerName() {
  try {
    const user = JSON.parse(localStorage.getItem('dwti-current-user') || 'null')
    return user?.display_name || user?.username || ''
  } catch {
    return ''
  }
}

function hydrateAccount(root) {
  try {
    const user = JSON.parse(localStorage.getItem('dwti-current-user') || 'null')
    const label = user?.display_name || user?.username || '个人'
    queryAll(root, '.avatar').forEach((node) => { node.textContent = label })
  } catch {
    queryAll(root, '.avatar').forEach((node) => { node.textContent = '个人' })
  }
}

async function hydrateIncidentDetail(root, state, file, id) {
  const vulnerability = file === 'vulnerability-detail.html'
  const endpoint = vulnerability ? `/api/vulnerabilities/${encodeURIComponent(id)}` : `/api/events/${encodeURIComponent(id)}`
  const detail = await requestJson(endpoint)
  state.incidentDetail = detail
  const riskLines = [...new Set(detailRiskLines(detail))]
  const referenceResources = normalizedResourceList(
    detail.reference_urls,
    detail.mirror_resources,
    detail.screenshot_resources,
    detail.sample_links,
    detail.json_preview_url ? [{ label: 'JSON 记录', url: detail.json_preview_url, kind: 'artifact' }] : [],
  )
  const sourceUrl = detail.disclosure_url || detail.source_url || detail.advisory_url || referenceResources[0]?.url || ''
  const affectedVersions = (detail.affected_version_items || detail.affected_versions || [])
    .map((item) => typeof item === 'string' ? item : item?.display || item?.raw || item?.version || item?.label || item?.value)
    .filter(Boolean)

  if (file === 'event-detail.html') {
    bindDetailBase(root, detail, [
      ['风险等级', severityLabel(severityOf(detail))],
      ['来源', detail.source || detail.raw_source_type_label || '—'],
      ['披露时间', formatDate(detail.disclosure_time)],
      ['风险评分', detail.risk_score != null ? `${number(detail.risk_score)} / 100` : '—'],
    ], [])
    setDefinitionPairs(query(root, '[data-od-id="detail-key-information"] .definition-grid'), [
      { label: '事件类型', value: eventTypeLabel(eventType(detail)) },
      { label: '来源', value: detail.source || detail.raw_source_type_label },
      { label: '披露时间', value: formatFullDate(detail.disclosure_time) },
      { label: '地区', value: detail.region || detail.country },
      { label: '所属行业', value: detail.industry },
      { label: '关联对象', value: detail.victim || detail.vendor || detail.product || detail.attacker },
    ])
    const riskSection = setDetailSection(root, 'detail-risk-reasoning', riskLines.length > 0)
    replaceStructuredRows(query(riskSection, '.queue-list'), riskLines.slice(0, 6).map((line, index) => ({
      label: `判断依据 ${index + 1}`,
      value: line,
      note: '接口返回的风险依据',
    })))
    const evidence = query(root, '[data-od-id="detail-evidence"]')
    const evidenceText = usableText(detail.detail_text) || usableText(detail.summary) || '当前接口未提供正文证据'
    setText(evidence, 'pre', evidenceText)
    setDefinitionPairs(query(evidence, '.definition-grid'), [
      { label: '来源类别', value: detail.raw_source_type_label || detail.source || '未标注' },
      { label: '参考链接', value: referenceResources[0]?.label || sourceUrl, url: referenceResources[0]?.url || sourceUrl },
      { label: '样本证据', value: detail.has_sample_evidence ? `${number(detail.sample_link_count || detail.sample_links?.length)} 个` : '未提供' },
    ])
    hideDetailRail(root, 'detail-action-rail')
    const translate = queryAll(evidence, 'button[data-toast]').find((button) => button.textContent.includes('切换原文'))
    if (translate && usableText(detail.detail_text)) {
      delete translate.dataset.toast
      translate.dataset.runtimeTranslate = '1'
      setActionAvailable(translate, true)
      const original = usableText(detail.detail_text)
      let translated = ''
      let showingTranslated = false
      state.toggleTranslation = async () => {
        if (!translated) {
          const payload = await requestJson(`/api/events/${encodeURIComponent(id)}?translate_detail=true`)
          translated = usableText(payload.detail_text) || original
          if (payload.translation_applied === false || translated === original) {
            throw new Error(payload.translation_error === 'rate_limited' ? '翻译服务请求过于频繁，请稍后重试' : '翻译服务暂时不可用，请稍后重试')
          }
        }
        showingTranslated = !showingTranslated
        setText(evidence, 'pre', showingTranslated ? translated : original)
        translate.textContent = showingTranslated ? '显示原文' : '显示译文'
      }
    } else if (translate) {
      setActionAvailable(translate, false, '当前记录没有可切换正文')
    }
    return
  }

  if (vulnerability) {
    bindDetailBase(root, detail, [
      ['行动优先级', ['critical', 'high'].includes(severityOf(detail)) ? '优先核查' : '持续跟踪'],
      ['CVSS', detail.cvss ?? '—'],
      ['补丁状态', detail.patch_available ? '已有补丁' : '未确认有补丁'],
      ['利用状态', detail.is_exploited ? '已确认在野利用' : '未确认在野利用'],
    ], [
      ['风险评分', detail.risk_score != null ? `${number(detail.risk_score)} / 100` : '—', '接口评分'],
      ['在野利用', detail.is_exploited ? '已确认' : '未确认', '公开情报记录'],
      ['受影响版本', affectedVersions.length ? `${affectedVersions.length} 项` : '未提供', ''],
      ['披露时间', formatDate(detail.disclosure_time), detail.source || '公开源'],
    ])
    setDefinitionPairs(query(root, '[data-od-id="vulnerability-affected-scope"] .definition-grid'), [
      { label: '厂商', value: detail.vendor },
      { label: '产品', value: detail.product },
      { label: '影响版本', value: affectedVersions },
      { label: '在野利用', value: detail.is_exploited ? '已确认' : '未确认' },
      { label: '补丁状态', value: detail.patch_available ? '已有补丁' : '未确认有补丁' },
      { label: 'PoC 状态', value: Object.prototype.hasOwnProperty.call(detail, 'has_poc') ? (detail.has_poc ? '已记录' : '未记录') : '' },
    ])
    const evidenceSection = setDetailSection(root, 'vulnerability-exploit-evidence', riskLines.length > 0)
    replaceStructuredRows(query(evidenceSection, '.detail-list'), riskLines.slice(0, 6).map((line, index) => ({
      label: `利用依据 ${index + 1}`,
      value: line,
      note: detail.source || '公开源',
    })))
    setDetailSection(root, 'vulnerability-asset-plan', false)
    const remediation = setDetailSection(root, 'vulnerability-remediation', Boolean(detail.patch_available))
    replaceStructuredRows(query(remediation, '.timeline'), detail.patch_available ? [{
      label: '补丁状态',
      value: '接口记录已有补丁',
      note: sourceUrl ? '具体版本与操作步骤请核对原始通告' : '接口未提供补丁链接',
    }] : [])
    const sourceSection = setDetailSection(root, 'vulnerability-sources', Boolean(sourceUrl || referenceResources.length))
    replaceStructuredRows(query(sourceSection, '.detail-list'), referenceResources.slice(0, 6).map((item) => ({
      label: item.label,
      value: item.url,
      note: '真实接口资源',
    })))
    configureSourceAccess(root, {
      sectionId: 'vulnerability-sources', openId: 'vulnerability-open-source', viewId: 'vulnerability-view-mirror', downloadId: 'vulnerability-download-mirror',
      sourceUrl, resources: referenceResources, fetchedAt: detail.updated_time || detail.disclosure_time,
    })
    hideDetailRail(root, 'vulnerability-action-rail')
    return
  }

  if (file === 'ransomware-detail.html') {
    bindDetailBase(root, detail, [
      ['行动阶段', detail.category || detail.leak_type || '已披露'],
      ['团伙', detail.attacker || '未标注'],
      ['可信度', detail.confidence_score != null ? `${number(detail.confidence_score)} / 100` : '未提供'],
      ['披露时间', formatDate(detail.disclosure_time)],
    ], [
      ['受害地区', detail.region || detail.country || '—', detail.industry || '—'],
      ['样本证据', number(detail.sample_link_count || detail.sample_links?.length || 0), detail.has_sample_evidence ? '已记录' : '未记录'],
      ['首次披露', formatDate(detail.disclosure_time), detail.source || '泄露站点'],
      ['风险评分', detail.risk_score != null ? `${number(detail.risk_score)} / 100` : '—', '接口评分'],
    ])
    setDefinitionPairs(query(root, '[data-od-id="ransomware-victim-profile"] .definition-grid'), [
      { label: '受害组织', value: detail.victim },
      { label: '所属行业', value: detail.industry },
      { label: '勒索团伙', value: detail.attacker },
      { label: '披露来源', value: detail.source || detail.raw_source_type_label },
      { label: '披露时间', value: formatFullDate(detail.disclosure_time) },
      { label: '公开状态', value: detail.category || detail.leak_type },
    ])
    setDetailSection(root, 'ransomware-attack-chain', false)
    setDetailSection(root, 'ransomware-artifacts', false)
    configureSourceAccess(root, {
      sectionId: 'ransomware-evidence', openId: 'ransomware-open-source', viewId: 'ransomware-view-mirror', downloadId: 'ransomware-download-mirror',
      sourceUrl, resources: referenceResources, fetchedAt: detail.updated_time || detail.disclosure_time,
    })
    hideDetailRail(root, 'ransomware-action-rail')
    return
  }

  bindDetailBase(root, detail, [
    ['核验评分', detail.confidence_score != null ? `${number(detail.confidence_score)} / 100` : '未提供'],
    ['样本证据', number(detail.sample_link_count || detail.sample_links?.length || 0)],
    ['泄露类型', detail.leak_type || detail.category || '未标注'],
    ['风险等级', severityLabel(severityOf(detail))],
  ], [
    ['来源可信度', detail.confidence_score != null ? `${number(detail.confidence_score)} / 100` : '—', '接口评分'],
    ['风险依据', number(riskLines.length), '结构化依据'],
    ['披露时间', formatDate(detail.disclosure_time), detail.source || '公开源'],
    ['影响实体', detail.victim || '未确认', detail.industry || '—'],
  ])
  setDefinitionPairs(query(root, '[data-od-id="data-leak-source-chain"] .definition-grid'), [
    { label: '来源通道', value: detail.source || detail.raw_source_type_label },
    { label: '发布者', value: detail.attacker },
    { label: '泄露类型', value: detail.leak_type || detail.category },
    { label: '采集时间', value: formatFullDate(detail.updated_time || detail.disclosure_time) },
    { label: '影响对象', value: detail.victim },
    { label: '样本证据', value: detail.has_sample_evidence ? `${number(detail.sample_link_count || detail.sample_links?.length)} 个` : '未提供' },
  ])
  setDetailSection(root, 'data-leak-field-matrix', false)
  setDetailSection(root, 'data-leak-sample-preview', false)
  setDetailSection(root, 'data-leak-dedup', false)
  const eventDetailText = usableText(detail.detail_text) || usableText(detail.summary)
  const eventDetailSection = setDetailSection(root, 'data-leak-event-detail', Boolean(eventDetailText))
  setText(eventDetailSection, 'pre', eventDetailText)
  const translate = query(eventDetailSection, 'button[data-toast]')
  if (translate && usableText(detail.detail_text)) {
    delete translate.dataset.toast
    translate.dataset.runtimeTranslate = '1'
    setActionAvailable(translate, true)
    const original = usableText(detail.detail_text)
    let translated = ''
    let showingTranslated = false
    state.toggleTranslation = async () => {
      if (!translated) {
        const payload = await requestJson(`/api/events/${encodeURIComponent(id)}?translate_detail=true`)
        translated = usableText(payload.detail_text) || original
        if (payload.translation_applied === false || translated === original) {
          throw new Error(payload.translation_error === 'rate_limited' ? '翻译服务请求过于频繁，请稍后重试' : '翻译服务暂时不可用，请稍后重试')
        }
      }
      showingTranslated = !showingTranslated
      setText(eventDetailSection, 'pre', showingTranslated ? translated : original)
      translate.textContent = showingTranslated ? '显示原文' : '显示译文'
    }
  } else if (translate) {
    setActionAvailable(translate, false, '当前记录没有可翻译正文')
  }
  configureSourceAccess(root, {
    sectionId: 'data-leak-mirror-evidence', openId: 'data-leak-open-source', viewId: 'data-leak-view-mirror', downloadId: 'data-leak-download-mirror',
    sourceUrl, resources: referenceResources, fetchedAt: detail.updated_time || detail.disclosure_time,
  })
  hideDetailRail(root, 'data-leak-action-rail')
}

export async function hydratePrototypeScreen({ root, route, file }) {
  if (!root) return
  hydrateAccount(root)
  if (!DATA_FILES.has(file)) return
  prepareDataPage(root, file)
  const state = { tables: new Map(), exportUrls: new Map(), requestController: null, refresh: null }
  installActionGuard(root, state)
  root.addEventListener('prototype:query-change', async () => {
    if (!state.refresh) return
    setDataState(root, 'loading', '正在加载筛选结果…')
    try {
      await state.refresh()
      setDataState(root, 'ready')
    } catch (error) {
      if (error?.name !== 'AbortError') showLoadError(root, error)
    }
  }, { signal: root.__dataRuntimeAbort.signal })
  const id = String(route?.params?.eventId || route?.params?.hitId || document.body.dataset.prototypeRecordId || '')

  try {
    if (file === 'dashboard.html') await hydrateDashboard(root, state)
    else if (file === 'intelligence.html') await hydrateIntelligence(root, state)
    else if (file === 'ai-aggregation.html') await hydrateAiAggregationScreen({ root, signal: root.__dataRuntimeAbort.signal, route })
    else if (file === 'ai-aggregation-templates.html') await hydrateAiAggregationTemplatesScreen({ root, signal: root.__dataRuntimeAbort.signal, route })
    else if (file === 'ransomware.html') await hydrateRansomware(root, state)
    else if (file === 'data-leak.html') await hydrateDataLeak(root, state)
    else if (file === 'vulnerabilities.html') await hydrateVulnerabilities(root, state)
    else if (INCIDENT_FILES.has(file)) await hydrateIncidentDetail(root, state, file, id)
    setDataState(root, 'ready')
  } catch (error) {
    if (error?.name !== 'AbortError') showLoadError(root, error)
  }
}
