import { computed, reactive } from 'vue'
import { ASSIGNABLE_MODULE_KEYS, MODULE_KEYS, normalizeModuleKeys } from '@/config/permissions'

export const AUTH_UNAUTHORIZED_EVENT = 'dwti-auth-unauthorized'

const TOKEN_STORAGE_KEY = 'dwti-auth-token'
const USER_STORAGE_KEY = 'dwti-current-user'

const state = reactive({
  token: localStorage.getItem(TOKEN_STORAGE_KEY) || '',
  user: readStoredUser(),
  validated: false,
})

let fetchInstalled = false

function normalizeUser(user) {
  if (!user || typeof user !== 'object') return null
  const role = user.role === 'admin' || user.is_admin ? 'admin' : 'user'
  return {
    ...user,
    role,
    is_admin: role === 'admin',
    enabled: user.enabled !== false,
    modules: role === 'admin' ? [...ASSIGNABLE_MODULE_KEYS] : normalizeModuleKeys(user.modules),
  }
}

function readStoredUser() {
  try {
    const value = localStorage.getItem(USER_STORAGE_KEY)
    return value ? normalizeUser(JSON.parse(value)) : null
  } catch {
    localStorage.removeItem(USER_STORAGE_KEY)
    return null
  }
}

function setAuthSession(payload, validated = true) {
  const token = payload?.access_token || ''
  const user = normalizeUser(payload?.user)
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

export function isCurrentUserAdmin() {
  return state.user?.role === 'admin' || Boolean(state.user?.is_admin)
}

export function hasModuleAccess(moduleKey) {
  if (moduleKey === MODULE_KEYS.DASHBOARD) return true
  if (isCurrentUserAdmin()) return true
  return Boolean(state.user?.modules?.includes(moduleKey))
}

export function getAuthHeaders(headers = {}, token = getAuthToken()) {
  const nextHeaders = new Headers(headers)
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

function protectedApiTarget(url) {
  const target = new URL(url, window.location.origin)
  const isProtected = target.origin === window.location.origin
    && target.pathname.startsWith('/api/')
    && target.pathname !== '/api/auth/login'
  return isProtected ? target : null
}

async function isExpiredSessionResponse(response, target) {
  if (!target || response.status !== 401) return false
  if (target.pathname === '/api/auth/me') return true

  try {
    const payload = await response.clone().json()
    return payload?.detail === '未登录或登录已过期'
  } catch {
    return false
  }
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
    const target = protectedApiTarget(url)
    const requestToken = target ? getAuthToken() : ''
    const nextInit = target
      ? {
          ...init,
          headers: getAuthHeaders(init.headers || (input instanceof Request ? input.headers : {}), requestToken),
        }
      : init
    const response = await nativeFetch(input, nextInit)
    if (
      requestToken
      && requestToken === getAuthToken()
      && await isExpiredSessionResponse(response, target)
    ) {
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

export async function changePassword(currentPassword, newPassword) {
  const response = await fetch('/api/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  })
  if (!response.ok) {
    throw new Error((await readErrorMessage(response)) || '修改密码失败')
  }
  return response.json()
}

async function requestAuthJson(path, options = {}) {
  const response = await fetch(path, options)
  if (!response.ok) {
    throw new Error((await readErrorMessage(response)) || '账号操作失败')
  }
  return response.json()
}

export async function listAuthAccounts() {
  const payload = await requestAuthJson('/api/auth/accounts')
  return Array.isArray(payload?.items) ? payload.items.map(normalizeUser).filter(Boolean) : []
}

export async function createAuthAccount(account) {
  return requestAuthJson('/api/auth/accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username: account.username,
      display_name: account.displayName,
      password: account.password,
      modules: normalizeModuleKeys(account.modules),
    }),
  })
}

export async function updateAuthAccount(username, account) {
  return requestAuthJson(`/api/auth/accounts/${encodeURIComponent(username)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      display_name: account.displayName,
      modules: normalizeModuleKeys(account.modules),
      enabled: account.enabled !== false,
    }),
  })
}

export async function updateAuthAccountInfo(username, account) {
  return requestAuthJson(`/api/auth/accounts/${encodeURIComponent(username)}/profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username: account.username,
      display_name: account.displayName,
      new_password: account.newPassword || '',
    }),
  })
}

export async function deleteAuthAccount(username) {
  return requestAuthJson(`/api/auth/accounts/${encodeURIComponent(username)}`, {
    method: 'DELETE',
  })
}

export function useAuth() {
  return {
    state,
    isAuthenticated: computed(() => Boolean(state.token && state.validated)),
    isAdmin: computed(isCurrentUserAdmin),
    canAccessModule: hasModuleAccess,
    login: loginWithPassword,
    loadCurrentUser,
    changePassword,
    listAccounts: listAuthAccounts,
    createAccount: createAuthAccount,
    updateAccount: updateAuthAccount,
    updateAccountInfo: updateAuthAccountInfo,
    deleteAccount: deleteAuthAccount,
    logout,
  }
}
