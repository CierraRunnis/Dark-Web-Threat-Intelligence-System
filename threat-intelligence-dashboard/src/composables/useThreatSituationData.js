import { onScopeDispose, ref } from 'vue'
import * as fallbackModule from '@/mock/intelligence'

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === '1'
const data = ref(DEMO_MODE ? { ...fallbackModule } : {})
const loading = ref(false)
const error = ref(null)
let loadedAt = 0
let etag = ''
let pending = null
let generation = 0
const TTL_MS = 15_000

export function invalidateThreatSituationData() {
  loadedAt = 0
  etag = ''
  generation += 1
}

async function loadThreatSituation({ force = false, signal } = {}) {
  if (!force && loadedAt && Date.now() - loadedAt < TTL_MS) return data.value
  if (pending && !force) return pending
  const requestGeneration = generation
  const headers = new Headers()
  if (etag) headers.set('If-None-Match', etag)
  loading.value = true
  error.value = null
  const request = fetch('/api/threat-situation?days=30', { headers, signal })
    .then(async (response) => {
      if (response.status === 304) {
        loadedAt = Date.now()
        return data.value
      }
      if (!response.ok) throw new Error('API request failed: ' + response.status)
      const payload = await response.json()
      if (requestGeneration !== generation) return data.value
      etag = response.headers.get('etag') || ''
      loadedAt = Date.now()
      data.value = DEMO_MODE ? { ...fallbackModule, ...payload } : payload
      return data.value
    })
    .catch((requestError) => {
      if (requestError?.name === 'AbortError') throw requestError
      error.value = requestError
      if (!Object.keys(data.value || {}).length) data.value = { ...fallbackModule }
      return data.value
    })
    .finally(() => {
      if (pending === request) pending = null
      loading.value = false
    })
  pending = request
  return request
}

export function useThreatSituationData() {
  const controller = new AbortController()
  if (!loadedAt || Date.now() - loadedAt > TTL_MS) {
    loadThreatSituation({ signal: controller.signal }).catch(() => {})
  }
  onScopeDispose(() => controller.abort())
  return {
    data,
    loading,
    error,
    refresh: () => loadThreatSituation({ force: true, signal: controller.signal }),
  }
}
