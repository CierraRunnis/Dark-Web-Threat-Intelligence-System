import { ref } from 'vue'
import * as fallbackModule from '@/mock/intelligence'

const fallbackData = { ...fallbackModule }
const intelligenceData = ref({ ...fallbackData })
const loading = ref(false)
const error = ref(null)

let hasLoaded = false
let pendingRequest = null

async function loadIntelligenceData() {
  if (pendingRequest) {
    return pendingRequest
  }

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
      intelligenceData.value = {
        ...fallbackData,
        ...payload,
      }
      hasLoaded = true
      return intelligenceData.value
    })
    .catch((requestError) => {
      error.value = requestError
      return intelligenceData.value
    })
    .finally(() => {
      loading.value = false
      pendingRequest = null
    })

  return pendingRequest
}

export function useIntelligenceData() {
  if (!hasLoaded && !loading.value) {
    loadIntelligenceData()
  }

  return {
    data: intelligenceData,
    loading,
    error,
    refresh: loadIntelligenceData,
  }
}
