export const AI_AGGREGATION_FILE = 'ai-aggregation.html'

const STATUS_META = Object.freeze({
  queued: Object.freeze({ key: 'queued', label: '排队中', tone: 'warning', description: '任务已接收，正在等待可用执行槽位。' }),
  running: Object.freeze({ key: 'running', label: '分析中', tone: 'info', description: '暗网、Telegram 与公开 Web 情报正在聚合。' }),
  succeeded: Object.freeze({ key: 'succeeded', label: '已完成', tone: 'success', description: '威胁情报报告已生成。' }),
  failed: Object.freeze({ key: 'failed', label: '已失败', tone: 'danger', description: '分析未完成，请查看错误详情。' }),
})
const DELIVERY_META = Object.freeze({
  pending: Object.freeze({ key: 'pending', label: '待投递', tone: 'warning' }), sending: Object.freeze({ key: 'sending', label: '投递中', tone: 'info' }),
  succeeded: Object.freeze({ key: 'succeeded', label: '已送达', tone: 'success' }), partial: Object.freeze({ key: 'partial', label: '部分失败', tone: 'warning' }),
  failed: Object.freeze({ key: 'failed', label: '投递失败', tone: 'danger' }), skipped: Object.freeze({ key: 'skipped', label: '已跳过', tone: 'neutral' }),
  not_configured: Object.freeze({ key: 'not_configured', label: '未配置', tone: 'neutral' }), not_attempted: Object.freeze({ key: 'not_attempted', label: '未开始', tone: 'neutral' }),
})
const UNKNOWN = Object.freeze({ key: 'unknown', label: '未知', tone: 'neutral', description: '后端返回了未识别的状态。' })

export const getAiStatusMeta = (status) => STATUS_META[String(status ?? '').trim().toLowerCase()] || UNKNOWN
export const getAiDeliveryMeta = (status) => DELIVERY_META[String(status ?? '').trim().toLowerCase()] || UNKNOWN
export const isFivePartCron = (value) => String(value ?? '').trim().split(/\s+/).filter(Boolean).length === 5

export function escapeAiHtml(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;')
}

const inline = (value) => value.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
export function renderAiMarkdown(markdown) {
  const source = String(markdown ?? '').replace(/\r\n?/g, '\n').trim()
  if (!source) return ''
  const out = []
  let list = ''
  let code = false
  let codeLines = []
  const close = () => { if (list) { out.push(`</${list}>`); list = '' } }
  for (const raw of source.split('\n')) {
    if (/^```/.test(raw.trim())) { close(); if (code) { out.push(`<pre><code>${codeLines.join('\n')}</code></pre>`); codeLines = [] } code = !code; continue }
    const line = escapeAiHtml(raw)
    if (code) { codeLines.push(line); continue }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line)
    if (heading) { close(); out.push(`<h${heading[1].length + 1}>${inline(heading[2])}</h${heading[1].length + 1}>`); continue }
    const bullet = /^\s*[-*]\s+(.+)$/.exec(line)
    if (bullet) { if (list !== 'ul') { close(); list = 'ul'; out.push('<ul>') } out.push(`<li>${inline(bullet[1])}</li>`); continue }
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line)
    if (ordered) { if (list !== 'ol') { close(); list = 'ol'; out.push('<ol>') } out.push(`<li>${inline(ordered[1])}</li>`); continue }
    close()
    if (!line.trim()) out.push('<div class="ai-markdown-spacer" aria-hidden="true"></div>')
    else if (/^&gt;\s?/.test(line)) out.push(`<blockquote>${inline(line.replace(/^&gt;\s?/, ''))}</blockquote>`)
    else out.push(`<p>${inline(line)}</p>`)
  }
  close()
  if (code) out.push(`<pre><code>${codeLines.join('\n')}</code></pre>`)
  return out.join('')
}
