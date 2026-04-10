import { ref } from 'vue'
import * as fallbackModule from '@/mock/intelligence'

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === '1'
const fallbackData = { ...fallbackModule }
const intelligenceData = ref(DEMO_MODE ? { ...fallbackData } : {})
const loading = ref(false)
const error = ref(null)
const RETRY_DELAY_MS = 3000
const AUTO_REFRESH_TTL_MS = 15000

let hasLoaded = false
let pendingRequest = null
let retryTimer = null
let lastLoadedAt = 0

function clearRetryTimer() {
  if (retryTimer) {
    window.clearTimeout(retryTimer)
    retryTimer = null
  }
}

function scheduleRetry() {
  if (hasLoaded || loading.value || pendingRequest || retryTimer) {
    return
  }
  retryTimer = window.setTimeout(() => {
    retryTimer = null
    loadIntelligenceData()
  }, RETRY_DELAY_MS)
}

async function loadIntelligenceData() {
  if (pendingRequest) {
    return pendingRequest
  }

  clearRetryTimer()

  loading.value = true
  error.value = null

  pendingRequest = fetch('/api/intelligence')
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`API request failed: ${response.status}`)
      }
      return response.json()
    })
    .then((payload) => {
      intelligenceData.value = DEMO_MODE
        ? {
            ...fallbackData,
            ...payload,
          }
        : { ...payload }
      hasLoaded = true
      lastLoadedAt = Date.now()
      clearRetryTimer()
      return intelligenceData.value
    })
    .catch((requestError) => {
      error.value = requestError
      scheduleRetry()
      return intelligenceData.value
    })
    .finally(() => {
      loading.value = false
      pendingRequest = null
    })

  return pendingRequest
}

export function useIntelligenceData() {
  if ((!hasLoaded || (Date.now() - lastLoadedAt) > AUTO_REFRESH_TTL_MS) && !loading.value) {
    loadIntelligenceData()
  }

  return {
    data: intelligenceData,
    loading,
    error,
    refresh: loadIntelligenceData,
  }
}
