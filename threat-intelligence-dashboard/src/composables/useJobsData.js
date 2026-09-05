import { ref } from 'vue'

const jobsData = ref({
  overall_status: '未知',
  running_jobs: 0,
  stale_jobs: 0,
  failed_jobs_24h: 0,
  recent_failures: [],
  site_health: [],
  updated_at: '',
})
const loading = ref(false)
const error = ref(null)

let initialized = false
let pendingRequest = null

async function loadJobsData() {
  if (pendingRequest) {
    return pendingRequest
  }

  loading.value = true
  error.value = null

  pendingRequest = fetch('/api/jobs')
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`API request failed: ${response.status}`)
      }
      return response.json()
    })
    .then((payload) => {
      jobsData.value = payload
      initialized = true
      return jobsData.value
    })
    .catch((requestError) => {
      error.value = requestError
      return jobsData.value
    })
    .finally(() => {
      loading.value = false
      pendingRequest = null
    })

  return pendingRequest
}

export function useJobsData() {
  if (!initialized && !loading.value) {
    loadJobsData()
  }

  return {
    data: jobsData,
    loading,
    error,
    refresh: loadJobsData,
  }
}
