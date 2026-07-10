import { requestJson } from '@/composables/requestJson'

const API_BASE = '/api/darkweb-monitoring'

function reportQuery(key, value) {
  const query = new URLSearchParams({ [key]: value })
  return query.toString()
}

export function useDarkWebMonitoringApi() {
  return {
    loadOverview() {
      return requestJson(`${API_BASE}/overview`)
    },
    reviewCase(caseId, payload) {
      return requestJson(`${API_BASE}/cases/${encodeURIComponent(caseId)}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
    },
    pushCase(caseId) {
      return requestJson(`${API_BASE}/cases/${encodeURIComponent(caseId)}/push`, {
        method: 'POST',
      })
    },
    runMonitoring() {
      return requestJson(`${API_BASE}/run`, {
        method: 'POST',
      })
    },
    loadMonthlyReport(month) {
      return requestJson(`${API_BASE}/reports/monthly?${reportQuery('month', month)}`)
    },
    loadDailyReport(date) {
      return requestJson(`${API_BASE}/reports/daily?${reportQuery('date', date)}`)
    },
  }
}
