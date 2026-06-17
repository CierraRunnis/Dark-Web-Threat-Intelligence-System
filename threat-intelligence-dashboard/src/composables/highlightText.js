function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function normalizeKeywords(keywords) {
  const items = Array.isArray(keywords) ? keywords : [keywords]
  return [...new Set(items.map((item) => String(item || '').trim()).filter(Boolean))]
}

export function maskSensitivePreview(value) {
  const rawValue = String(value || '')
  if (!rawValue) return ''
  if (rawValue.length <= 8) return '*'.repeat(rawValue.length)
  return `${rawValue.slice(0, 4)}***${rawValue.slice(-4)}`
}

export function highlightKeywordsHtml(text, keywords, className = 'keyword-highlight') {
  const rawText = String(text || '')
  if (!rawText) return ''
  const normalizedKeywords = normalizeKeywords(keywords).sort((left, right) => right.length - left.length)
  if (!normalizedKeywords.length) return escapeHtml(rawText)

  const pattern = new RegExp(normalizedKeywords.map((item) => escapeRegExp(item)).join('|'), 'gi')
  const parts = rawText.split(pattern)
  const matches = rawText.match(pattern) || []

  if (!matches.length) {
    return escapeHtml(rawText)
  }

  let html = ''
  for (let index = 0; index < parts.length; index += 1) {
    html += escapeHtml(parts[index] || '')
    if (index < matches.length) {
      html += `<span class="${className}">${escapeHtml(matches[index])}</span>`
    }
  }
  return html
}

export function highlightKeywordHtml(text, keyword, className = 'keyword-highlight') {
  return highlightKeywordsHtml(text, [keyword], className)
}
