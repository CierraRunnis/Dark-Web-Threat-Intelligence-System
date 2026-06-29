import { computed, reactive } from 'vue'

export const AUTH_UNAUTHORIZED_EVENT = 'dwti-auth-unauthorized'

const TOKEN_STORAGE_KEY = 'dwti-auth-token'
const USER_STORAGE_KEY = 'dwti-current-user'

const state = reactive({
  token: localStorage.getItem(TOKEN_STORAGE_KEY) || '',
  user: readStoredUser(),
  validated: false,
})

let fetchInstalled = false

function readStoredUser() {
  try {
    const value = localStorage.getItem(USER_STORAGE_KEY)
    return value ? JSON.parse(value) : null
  } catch {
    localStorage.removeItem(USER_STORAGE_KEY)
    return null
  }
}

function setAuthSession(payload, validated = true) {
  const token = payload?.access_token || ''
  const user = payload?.user || null
  state.token = token
  state.user = user
  state.validated = Boolean(token && validated)
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  }
  if (user) {
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user))
  } else {
    localStorage.removeItem(USER_STORAGE_KEY)
  }
}

export function clearAuthSession() {
  setAuthSession({ access_token: '', user: null })
}

export function getAuthToken() {
  return state.token || localStorage.getItem(TOKEN_STORAGE_KEY) || ''
}

export function hasAuthSession() {
  return Boolean(getAuthToken())
}

export function isAuthSessionValidated() {
  return Boolean(state.token && state.validated)
}

export function getAuthHeaders(headers = {}) {
  const nextHeaders = new Headers(headers)
  const token = getAuthToken()
  if (token) {
    nextHeaders.set('Authorization', `Bearer ${token}`)
  }
  return nextHeaders
}

async function readErrorMessage(response) {
  try {
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      const payload = await response.json()
      return String(payload?.detail || payload?.message || '')
    }
    return (await response.text()).trim()
  } catch {
    return ''
  }
}

function isProtectedApiRequest(url) {
  const target = new URL(url, window.location.origin)
  return target.origin === window.location.origin && target.pathname.startsWith('/api/') && target.pathname !== '/api/auth/login'
}

function notifyUnauthorized() {
  window.dispatchEvent(new CustomEvent(AUTH_UNAUTHORIZED_EVENT))
}

export function installAuthFetch() {
  if (fetchInstalled) return
  fetchInstalled = true

  const nativeFetch = window.fetch.bind(window)
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' || input instanceof URL ? String(input) : input.url
    const shouldAuthorize = isProtectedApiRequest(url)
    const nextInit = shouldAuthorize
      ? {
          ...init,
          headers: getAuthHeaders(init.headers || (input instanceof Request ? input.headers : {})),
        }
      : init
    const response = await nativeFetch(input, nextInit)
    if (response.status === 401 && shouldAuthorize) {
      clearAuthSession()
      notifyUnauthorized()
    }
    return response
  }
}

export async function loginWithPassword(account, password) {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: account, password }),
  })
  if (!response.ok) {
    throw new Error((await readErrorMessage(response)) || '登录失败')
  }
  const payload = await response.json()
  setAuthSession(payload)
  return payload.user
}

export async function loadCurrentUser() {
  if (!hasAuthSession()) return null
  const response = await fetch('/api/auth/me')
  if (!response.ok) {
    clearAuthSession()
    return null
  }
  const user = await response.json()
  setAuthSession({ access_token: getAuthToken(), user })
  return user
}

export async function logout() {
  const token = getAuthToken()
  try {
    if (token) {
      await fetch('/api/auth/logout', { method: 'POST' })
    }
  } finally {
    clearAuthSession()
  }
}

export function useAuth() {
  return {
    state,
    isAuthenticated: computed(() => Boolean(state.token && state.validated)),
    login: loginWithPassword,
    loadCurrentUser,
    logout,
  }
}
