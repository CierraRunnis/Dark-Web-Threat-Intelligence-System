import { requestJson } from '@/composables/requestJson'
import { getAuthHeaders } from '@/composables/useAuth'

function toCamelKey(key) {
  return String(key).replace(/_([a-z0-9])/g, (_match, letter) => letter.toUpperCase())
}

function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [toCamelKey(key), normalize(item)]))
}

function buildQuery(params = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) query.append(key, String(item))
      continue
    }
    query.set(key, String(value))
  }
  const text = query.toString()
  return text ? `?${text}` : ''
}

async function json(url, options) {
  return normalize(await requestJson(url, options))
}

function jsonOptions(method, payload) {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }
}

export function useSocialMonitoringApi() {
  return {
    loadSummary() {
      return json('/api/social-monitoring/summary')
    },
    loadPlatforms() {
      return json('/api/social-monitoring/platforms')
    },
    loadPlatformConfig() {
      return json('/api/social-monitoring/platform-config')
    },
    savePlatformConfig(platform, payload) {
      return json(
        `/api/social-monitoring/platform-config/${encodeURIComponent(platform)}`,
        jsonOptions('PUT', payload),
      )
    },
    clearPlatformConfig(platform) {
      return json(`/api/social-monitoring/platform-config/${encodeURIComponent(platform)}`, { method: 'DELETE' })
    },
    loadCampaigns() {
      return json('/api/social-monitoring/campaigns')
    },
    createCampaign(payload) {
      return json('/api/social-monitoring/campaigns', jsonOptions('POST', payload))
    },
    updateCampaign(campaignId, payload) {
      return json(`/api/social-monitoring/campaigns/${encodeURIComponent(campaignId)}`, jsonOptions('PATCH', payload))
    },
    deleteCampaign(campaignId) {
      return json(`/api/social-monitoring/campaigns/${encodeURIComponent(campaignId)}`, { method: 'DELETE' })
    },
    loadScans(params = {}) {
      return json(`/api/social-monitoring/scans${buildQuery({ campaignId: params.campaignId, limit: params.limit })}`)
    },
    loadEvents(params = {}) {
      return json(`/api/social-monitoring/events${buildQuery({
        platform: params.platform,
        status: params.verificationStatus,
        limit: params.limit || 1000,
      })}`)
    },
    loadEvent(eventId) {
      return json(`/api/social-monitoring/events/${encodeURIComponent(eventId)}`)
    },
    claimEvent(eventId) {
      return json(`/api/social-monitoring/events/${encodeURIComponent(eventId)}/claim`, { method: 'POST' })
    },
    verifyEvent(eventId, payload) {
      return json(`/api/social-monitoring/events/${encodeURIComponent(eventId)}/verify`, jsonOptions('POST', payload))
    },
    closeEvent(eventId) {
      return json(`/api/social-monitoring/events/${encodeURIComponent(eventId)}/close`, { method: 'POST' })
    },
    uploadEvidence(eventId, file) {
      const form = new FormData()
      form.append('file', file)
      return json(`/api/social-monitoring/events/${encodeURIComponent(eventId)}/evidence/upload`, {
        method: 'POST',
        body: form,
      })
    },
    captureEvidence(eventId) {
      return json(`/api/social-monitoring/events/${encodeURIComponent(eventId)}/evidence/capture`, { method: 'POST' })
    },
    async loadEvidenceBlob(evidenceId) {
      const response = await fetch(`/api/social-monitoring/evidence/${encodeURIComponent(evidenceId)}/content`, {
        headers: getAuthHeaders(),
      })
      if (!response.ok) throw new Error(`读取证据失败：${response.status}`)
      return response.blob()
    },
    redactEvidence(eventId, evidenceId, rectangles, approve = true) {
      return json(
        `/api/social-monitoring/events/${encodeURIComponent(eventId)}/evidence/${encodeURIComponent(evidenceId)}/redact`,
        jsonOptions('POST', { rectangles, approve }),
      )
    },
    publishEvent(eventId) {
      return json(`/api/social-monitoring/events/${encodeURIComponent(eventId)}/publish`, { method: 'POST' })
    },
    loadReportData(eventId) {
      return json(`/api/social-monitoring/events/${encodeURIComponent(eventId)}/report-data`)
    },
    recordReport(eventId, fileName, sha256) {
      return json(
        `/api/social-monitoring/events/${encodeURIComponent(eventId)}/report-generated`,
        jsonOptions('POST', { fileName, sha256 }),
      )
    },
    loadNotifications(params = {}) {
      return json(`/api/social-monitoring/notifications${buildQuery({ unreadOnly: params.unreadOnly, limit: params.limit })}`)
    },
    markNotificationRead(notificationId) {
      return json(`/api/social-monitoring/notifications/${encodeURIComponent(notificationId)}/read`, { method: 'POST' })
    },
    loadUsers() {
      return json('/api/users')
    },
    createUser(payload) {
      return json('/api/users', jsonOptions('POST', payload))
    },
    updateUser(userId, payload) {
      return json(`/api/users/${encodeURIComponent(userId)}`, jsonOptions('PATCH', payload))
    },
    deleteUser(userId) {
      return json(`/api/users/${encodeURIComponent(userId)}`, { method: 'DELETE' })
    },
    resetUserPassword(userId, newPassword) {
      return json(`/api/users/${encodeURIComponent(userId)}/password`, jsonOptions('POST', { newPassword }))
    },
  }
}

export function listFromResponse(payload, keys = []) {
  if (Array.isArray(payload)) return payload
  for (const key of [...keys, 'items', 'results', 'data']) {
    if (Array.isArray(payload?.[key])) return payload[key]
  }
  return []
}
