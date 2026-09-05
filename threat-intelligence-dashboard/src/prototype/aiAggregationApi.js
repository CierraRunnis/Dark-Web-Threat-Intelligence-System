export const AI_AGGREGATION_API_BASE = '/api/ai-aggregation'

function unwrap(payload) {
  if (payload && typeof payload === 'object' && !Array.isArray(payload) && 'data' in payload) return payload.data
  return payload
}

function responseMessage(payload, fallback) {
  const detail = payload?.detail ?? payload?.error ?? payload?.message
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || String(item)).join('；')
  if (detail && typeof detail === 'object') return detail.message || JSON.stringify(detail)
  return detail ? String(detail) : fallback
}

export function listFrom(payload, keys = []) {
  const value = unwrap(payload)
  if (Array.isArray(value)) return value
  for (const key of keys) if (Array.isArray(value?.[key])) return value[key]
  return []
}

export function createAiAggregationApi({ signal, fetchImpl = globalThis.fetch } = {}) {
  if (typeof fetchImpl !== 'function') throw new TypeError('fetchImpl must be a function')

  const request = async (path, options = {}) => {
    const headers = new Headers(options.headers || {})
    if (options.body != null && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    headers.set('Accept', 'application/json')
    let response
    try {
      response = await fetchImpl(`${AI_AGGREGATION_API_BASE}${path}`, { ...options, headers, signal: options.signal || signal })
    } catch (error) {
      if (error?.name === 'AbortError') throw error
      throw new Error('无法连接 AI聚合服务。')
    }
    const raw = await response.text()
    let payload = null
    if (raw) {
      try { payload = JSON.parse(raw) } catch { payload = { message: raw } }
    }
    if (!response.ok) throw new Error(responseMessage(payload, `请求失败（HTTP ${response.status}）`))
    return unwrap(payload)
  }

  return Object.freeze({
    health: () => request('/health'),
    listProfiles: () => request('/profiles'),
    getProfile: (id) => request(`/profiles/${encodeURIComponent(id)}`),
    createProfile: (payload) => request('/profiles', { method: 'POST', body: JSON.stringify(payload) }),
    updateProfile: (id, payload) => request(`/profiles/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(payload) }),
    deleteProfile: (id) => request(`/profiles/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    enableProfile: (id) => request(`/profiles/${encodeURIComponent(id)}/enable`, { method: 'POST' }),
    disableProfile: (id) => request(`/profiles/${encodeURIComponent(id)}/disable`, { method: 'POST' }),
    runProfile: (id) => request(`/profiles/${encodeURIComponent(id)}/run`, { method: 'POST', body: JSON.stringify({}) }),
    listRuns: ({ limit = 50, offset = 0 } = {}) => request(`/runs?limit=${limit}&offset=${offset}`),
    getRun: (id) => request(`/runs/${encodeURIComponent(id)}`),
    retryDeliveries: (id) => request(`/runs/${encodeURIComponent(id)}/retry-deliveries`, { method: 'POST' }),
  })
}
