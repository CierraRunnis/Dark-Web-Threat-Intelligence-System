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

const COUNTRY_NAME_OVERRIDES = {
  HK: '香港',
  MO: '澳门',
  TW: '台湾',
  GB: '英国',
  US: '美国',
}

const countryNameFormatter =
  typeof Intl !== 'undefined' && typeof Intl.DisplayNames === 'function'
    ? new Intl.DisplayNames(['zh-Hans'], { type: 'region' })
    : null

function toChineseCountryName(countryCode, fallbackName = '') {
  const code = String(countryCode || '').trim().toUpperCase()
  if (!code) return String(fallbackName || '').trim()
  if (COUNTRY_NAME_OVERRIDES[code]) return COUNTRY_NAME_OVERRIDES[code]
  try {
    return countryNameFormatter?.of(code) || String(fallbackName || '').trim() || code
  } catch {
    return String(fallbackName || '').trim() || code
  }
}

function normalizeCountryItem(item) {
  if (!item || typeof item !== 'object') return item
  const countryCode = String(item.countryCode || item.country_code || '').trim().toUpperCase()
  if (!countryCode) return item
  const chineseCountry = toChineseCountryName(countryCode, item.country || item.region)
  return {
    ...item,
    country: chineseCountry,
    region: chineseCountry,
  }
}

function rebuildExecutiveCountries(dataLeakEvents, ransomwareEvents) {
  const grouped = new Map()
  for (const item of [...dataLeakEvents, ...ransomwareEvents]) {
    const name = String(item.country || item.region || '').trim()
    if (!name || name === '未知') continue
    const current = grouped.get(name) || { name, eventCount: 0, highRiskCount: 0, riskTotal: 0 }
    current.eventCount += 1
    current.riskTotal += Number(item.riskScore || 0)
    if (Number(item.riskScore || 0) >= 60) {
      current.highRiskCount += 1
    }
    grouped.set(name, current)
  }
  return [...grouped.values()]
    .map((item) => ({
      name: item.name,
      eventCount: item.eventCount,
      highRiskCount: item.highRiskCount,
      averageRiskScore: item.eventCount ? Math.round(item.riskTotal / item.eventCount) : 0,
    }))
    .sort((left, right) => right.eventCount - left.eventCount || right.highRiskCount - left.highRiskCount || right.averageRiskScore - left.averageRiskScore)
    .slice(0, 10)
}

function normalizePayloadCountries(payload) {
  if (!payload || typeof payload !== 'object') return payload

  const dataLeakEvents = Array.isArray(payload.dataLeakEvents) ? payload.dataLeakEvents.map(normalizeCountryItem) : payload.dataLeakEvents || []
  const ransomwareEvents = Array.isArray(payload.ransomwareEvents) ? payload.ransomwareEvents.map(normalizeCountryItem) : payload.ransomwareEvents || []
  const threatExecutivePriorityEvents = Array.isArray(payload.threatExecutivePriorityEvents)
    ? payload.threatExecutivePriorityEvents.map(normalizeCountryItem)
    : payload.threatExecutivePriorityEvents || []
  const threatExecutiveCountries = rebuildExecutiveCountries(dataLeakEvents, ransomwareEvents)
  const topCountry = threatExecutiveCountries[0]?.name || payload.threatExecutiveCards?.topCountry || '未知'
  const topCountryEventCount = threatExecutiveCountries[0]?.eventCount || payload.threatExecutiveCards?.topCountryEventCount || 0

  return {
    ...payload,
    dataLeakEvents,
    ransomwareEvents,
    threatExecutivePriorityEvents,
    threatExecutiveCountries,
    threatExecutiveCards: payload.threatExecutiveCards
      ? {
          ...payload.threatExecutiveCards,
          topCountry,
          topCountryEventCount,
        }
      : payload.threatExecutiveCards,
  }
}

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
      const normalizedPayload = normalizePayloadCountries(payload)
      intelligenceData.value = DEMO_MODE
        ? {
            ...fallbackData,
            ...normalizedPayload,
          }
        : { ...normalizedPayload }
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
