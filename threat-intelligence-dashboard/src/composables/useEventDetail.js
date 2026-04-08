import { ref } from 'vue'

export function useEventDetail() {
  const detail = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const REQUEST_TIMEOUT_MS = 15000
  const RETRY_DELAY_MS = 2500
  let retryTimer = null

  function clearRetryTimer() {
    if (retryTimer) {
      window.clearTimeout(retryTimer)
      retryTimer = null
    }
  }

  function hasRichResources(payload) {
    if (!payload || typeof payload !== 'object') return false
    return Boolean(
      payload.detail_text ||
      (payload.screenshot_resources && payload.screenshot_resources.length) ||
      (payload.mirror_resources && payload.mirror_resources.length) ||
      payload.json_preview_url
    )
  }

  function scheduleRetry(eventId) {
    if (!eventId || retryTimer) return
    retryTimer = window.setTimeout(() => {
      retryTimer = null
      load(eventId)
    }, RETRY_DELAY_MS)
  }

  function loadFromSession(eventId) {
    try {
      const raw = sessionStorage.getItem(`event-detail:${eventId}`)
      if (!raw) return null
      return JSON.parse(raw)
    } catch {
      return null
    }
  }

  async function load(eventId) {
    if (!eventId) {
      detail.value = null
      return null
    }

    clearRetryTimer()

    const sessionDetail = loadFromSession(eventId)
    const hasSessionDetail = !!sessionDetail
    if (sessionDetail) {
      detail.value = sessionDetail
    }

    loading.value = true
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
        clearRetryTimer()
        try {
          sessionStorage.setItem(`event-detail:${eventId}`, JSON.stringify(detail.value))
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
      } else if (!hasRichResources(sessionDetail)) {
        scheduleRetry(eventId)
      }
      return detail.value
    } finally {
      loading.value = false
    }
  }

  return {
    detail,
    loading,
    error,
    load,
  }
}
