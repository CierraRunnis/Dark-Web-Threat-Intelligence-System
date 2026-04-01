import { ref } from 'vue'

export function useEventDetail() {
  const detail = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const REQUEST_TIMEOUT_MS = 5000

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
      const response = await fetch(`/api/events/${encodeURIComponent(eventId)}`, {
        signal: controller.signal,
      })
      window.clearTimeout(timeoutId)
      if (response.ok) {
        detail.value = await response.json()
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
