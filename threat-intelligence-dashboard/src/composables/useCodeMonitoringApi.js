import { requestJson } from '@/composables/requestJson'

function buildQuery(params = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === '') continue
    query.set(key, String(value))
  }
  const text = query.toString()
  return text ? `?${text}` : ''
}

export function useCodeMonitoringApi() {
  return {
    loadSummary() {
      return requestJson('/api/code-monitoring/summary')
    },
    loadSessions() {
      return requestJson('/api/platform-sessions?module=code_monitoring')
    },
    launchLogin(platform) {
      return requestJson(`/api/platform-sessions/${encodeURIComponent(platform)}/launch-login`, {
        method: 'POST',
      })
    },
    saveSession(platform, accountLabel) {
      return requestJson(`/api/platform-sessions/${encodeURIComponent(platform)}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_label: accountLabel || '' }),
      })
    },
    verifySession(platform) {
      return requestJson(`/api/platform-sessions/${encodeURIComponent(platform)}/verify`, {
        method: 'POST',
      })
    },
    deleteSession(platform) {
      return requestJson(`/api/platform-sessions/${encodeURIComponent(platform)}`, {
        method: 'DELETE',
      })
    },
    loadWatchlists() {
      return requestJson('/api/code-monitoring/watchlists')
    },
    saveWatchlist(payload) {
      return requestJson('/api/code-monitoring/watchlists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
    },
    runScan(watchlistId, payload) {
      return requestJson(`/api/code-monitoring/watchlists/${watchlistId}/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
    },
    loadScans(params = {}) {
      return requestJson(`/api/code-monitoring/scans${buildQuery({
        watchlist_id: params.watchlistId,
        limit: params.limit,
      })}`)
    },
    loadHits(params = {}) {
      return requestJson(`/api/code-monitoring/hits${buildQuery({
        watchlist_id: params.watchlistId,
        review_status: params.reviewStatus,
        platform: params.platform,
        sensitive_type: params.sensitiveType,
        limit: params.limit,
      })}`)
    },
    loadHitDetail(hitId) {
      return requestJson(`/api/code-monitoring/hits/${hitId}`)
    },
    reviewHit(hitId, payload) {
      return requestJson(`/api/code-monitoring/hits/${hitId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
    },
  }
}
