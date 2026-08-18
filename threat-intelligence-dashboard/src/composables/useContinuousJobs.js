import { ref } from 'vue'

const continuousData = ref({
  enabled: false,
  started_at: '',
  last_tick_at: '',
  mode: 'queue'
})
const loading = ref(false)
const error = ref(null)

let pendingRequest = null
let initialized = false

async function loadContinuousStatus() {
  if (pendingRequest) {
    return pendingRequest
  }

  loading.value = true
  error.value = null

  pendingRequest = fetch('/api/jobs/continuous-status')
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`API request failed: ${response.status}`)
      }
      return response.json()
    })
    .then((payload) => {
      continuousData.value = payload
      initialized = true
      return continuousData.value
    })
    .catch((requestError) => {
      error.value = requestError
      return continuousData.value
    })
    .finally(() => {
      loading.value = false
      pendingRequest = null
    })

  return pendingRequest
}

export function useContinuousJobs() {
  if (!initialized && !loading.value) {
    loadContinuousStatus()
  }

  return {
    data: continuousData,
    loading,
    error,
    refresh: loadContinuousStatus,
  }
}
