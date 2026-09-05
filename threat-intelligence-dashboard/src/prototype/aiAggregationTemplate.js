export const DEFAULT_AI_PROMPT_TEMPLATE = '搜索 {{keywords}} {{time_range}} 的威胁情报'
export const DEFAULT_SEARCH_WINDOW_DAYS = 30
export const MAX_TEMPLATE_KEYWORDS = 30
export const MAX_SEARCH_WINDOW_DAYS = 3650

export function normalizeTemplateKeyword(value) {
  return String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim()
}

export function parseKeywordLines(value, { maxItems = MAX_TEMPLATE_KEYWORDS } = {}) {
  const seen = new Set()
  const keywords = []
  for (const line of String(value ?? '').split(/\r?\n/)) {
    const keyword = normalizeTemplateKeyword(line)
    if (!keyword) continue
    const key = keyword.toLocaleLowerCase('zh-CN')
    if (seen.has(key)) continue
    seen.add(key)
    keywords.push(keyword)
    if (keywords.length >= maxItems) break
  }
  return keywords
}

export function keywordsToTextarea(keywords) {
  return (Array.isArray(keywords) ? keywords : []).map(normalizeTemplateKeyword).filter(Boolean).join('\n')
}

export function normalizeSearchWindowDays(value, fallback = DEFAULT_SEARCH_WINDOW_DAYS) {
  const parsed = Number.parseInt(String(value ?? ''), 10)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(MAX_SEARCH_WINDOW_DAYS, Math.max(1, parsed))
}

export function hasRequiredPlaceholders(template) {
  const source = String(template ?? '')
  return /{{\s*keywords\s*}}/.test(source) && /{{\s*time_range\s*}}/.test(source)
}

export function renderTemplatePreview(template, keywords, searchWindowDays = DEFAULT_SEARCH_WINDOW_DAYS) {
  const source = String(template ?? '').trim() || DEFAULT_AI_PROMPT_TEMPLATE
  const values = (Array.isArray(keywords) ? keywords : []).map(normalizeTemplateKeyword).filter(Boolean)
  const joined = values.length ? values.join('、') : '{{keywords}}'
  const days = normalizeSearchWindowDays(searchWindowDays)
  return source.replace(/{{\s*keywords\s*}}/g, joined).replace(/{{\s*time_range\s*}}/g, `最近${days}天`)
}
