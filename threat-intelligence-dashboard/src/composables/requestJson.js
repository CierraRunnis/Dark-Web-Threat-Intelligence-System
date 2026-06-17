export async function requestJson(url, options = {}) {
  const response = await fetch(url, options)
  if (!response.ok) {
    let detail = ''
    try {
      const contentType = response.headers.get('content-type') || ''
      if (contentType.includes('application/json')) {
        const payload = await response.json()
        detail = String(payload?.detail || payload?.message || '')
      } else {
        detail = (await response.text()).trim()
      }
    } catch {
      detail = ''
    }
    throw new Error(detail || `API request failed: ${response.status}`)
  }
  return response.json()
}
