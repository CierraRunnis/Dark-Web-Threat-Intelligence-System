const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'

function toDate(value) {
  if (!value) return null
  const text = String(value).trim()
  if (!text) return null
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(text) ? text : `${text}Z`
  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function formatParts(date, options = {}) {
  const formatter = new Intl.DateTimeFormat('zh-CN', {
    timeZone: SHANGHAI_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour12: false,
    ...options,
  })
  return Object.fromEntries(
    formatter
      .formatToParts(date)
      .filter((item) => item.type !== 'literal')
      .map((item) => [item.type, item.value]),
  )
}

export function formatShanghaiDateTime(value, { includeSeconds = false } = {}) {
  const date = toDate(value)
  if (!date) return ''
  const parts = formatParts(date, includeSeconds ? { hour: '2-digit', minute: '2-digit', second: '2-digit' } : { hour: '2-digit', minute: '2-digit' })
  const base = `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`
  return includeSeconds ? `${base}:${parts.second}` : base
}

export function formatShanghaiDate(value) {
  const date = toDate(value)
  if (!date) return ''
  const parts = formatParts(date)
  return `${parts.year}-${parts.month}-${parts.day}`
}

export { SHANGHAI_TIME_ZONE }
