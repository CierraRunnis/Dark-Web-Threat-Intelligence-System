import { ref } from 'vue'

const DETAIL_CACHE_VERSION = '2026-04-09-rich-detail-v4'

export function useEventDetail() {
  const detail = ref(null)
  const loading = ref(false)
  const refreshing = ref(false)
  const error = ref(null)
  const REQUEST_TIMEOUT_MS = 8000

  function hasRichResources(payload) {
    if (!payload || typeof payload !== 'object') return false
    return Boolean(
      payload.detail_text ||
      (payload.screenshot_resources && payload.screenshot_resources.length) ||
      (payload.mirror_resources && payload.mirror_resources.length) ||
      payload.json_preview_url
    )
  }

  function loadFromSession(eventId) {
    try {
      const raw = sessionStorage.getItem(`event-detail:${eventId}`)
      if (!raw) return null
      const parsed = JSON.parse(raw)
      if (!parsed || parsed.__cacheVersion !== DETAIL_CACHE_VERSION) {
        sessionStorage.removeItem(`event-detail:${eventId}`)
        return null
      }
      return parsed
    } catch {
      return null
    }
  }

  async function load(eventId) {
    if (!eventId) {
      detail.value = null
      loading.value = false
      refreshing.value = false
      return null
    }

    const allowSessionPrefill = String(eventId).startsWith('vuln:')
    const sessionDetail = allowSessionPrefill ? loadFromSession(eventId) : null
    const hasSessionDetail = !!sessionDetail
    if (sessionDetail) {
      detail.value = sessionDetail
    } else if (!allowSessionPrefill) {
      detail.value = null
    }

    loading.value = !hasSessionDetail
    refreshing.value = hasSessionDetail
    error.value = null
    try {
      const controller = new AbortController()
      const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
      const detailEndpoint = String(eventId).startsWith('vuln:')
        ? `/api/vulnerabilities/${encodeURIComponent(eventId)}`
        : `/api/events/${encodeURIComponent(eventId)}`
      const response = await fetch(detailEndpoint, {
        signal: controller.signal,
      })
      window.clearTimeout(timeoutId)
      if (response.ok) {
        detail.value = await response.json()
        try {
          sessionStorage.setItem(
            `event-detail:${eventId}`,
            JSON.stringify({
              ...detail.value,
              __cacheVersion: DETAIL_CACHE_VERSION,
            }),
          )
        } catch {}
        return detail.value
      }
      if (response.status === 404 && !hasSessionDetail) {
        detail.value = null
        return null
      }
      throw new Error(`详情请求失败：${response.status}`)
    } catch (requestError) {
      error.value =
        requestError?.name === 'AbortError'
          ? new Error('详情请求超时，当前先显示摘要数据。')
          : requestError
      if (!hasSessionDetail) {
        detail.value = null
      }
      return detail.value
    } finally {
      loading.value = false
      refreshing.value = false
    }
  }

  return {
    detail,
    loading,
    refreshing,
    error,
    load,
  }
}
