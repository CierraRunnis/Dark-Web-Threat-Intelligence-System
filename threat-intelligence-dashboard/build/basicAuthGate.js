import { timingSafeEqual } from 'node:crypto'


const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on'])


function firstValue(environments, key) {
  for (const environment of environments) {
    const value = String(environment?.[key] || '').trim()
    if (value) return value
  }
  return ''
}


function safeRealm(value) {
  return String(value || 'Dark Web Threat Intelligence')
    .replace(/["\\\r\n]/g, '')
    .trim() || 'Restricted'
}


export function resolveBasicAuthConfig(...environments) {
  const enabled = TRUE_VALUES.has(
    firstValue(environments, 'DARKWEB_BASIC_AUTH_ENABLED').toLowerCase(),
  )
  const username = firstValue(environments, 'DARKWEB_BASIC_AUTH_USERNAME')
    || firstValue(environments, 'DARKWEB_AUTH_USERNAME')
    || 'admin'
  const password = firstValue(environments, 'DARKWEB_BASIC_AUTH_PASSWORD')
    || firstValue(environments, 'DARKWEB_AUTH_PASSWORD')
  const realm = safeRealm(firstValue(environments, 'DARKWEB_BASIC_AUTH_REALM'))

  if (enabled && (!username || username.includes(':') || /[\r\n]/.test(username))) {
    throw new Error("DARKWEB_BASIC_AUTH_USERNAME must be a non-empty username without ':'")
  }
  if (enabled && !password) {
    throw new Error(
      'DARKWEB_BASIC_AUTH_ENABLED=1 requires DARKWEB_BASIC_AUTH_PASSWORD; '
      + 'no insecure default password is used',
    )
  }
  return { enabled, username, password, realm }
}


function equalText(left, right) {
  const leftBuffer = Buffer.from(String(left), 'utf8')
  const rightBuffer = Buffer.from(String(right), 'utf8')
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer)
}


function decodeCredentials(authorization) {
  const [scheme, encoded, ...rest] = String(authorization || '').trim().split(/\s+/)
  if (rest.length || String(scheme || '').toLowerCase() !== 'basic' || !encoded) return null
  try {
    const decoded = Buffer.from(encoded, 'base64').toString('utf8')
    const separator = decoded.indexOf(':')
    if (separator < 0) return null
    return [decoded.slice(0, separator), decoded.slice(separator + 1)]
  } catch {
    return null
  }
}


export function createBasicAuthMiddleware(config) {
  return (request, response, next) => {
    if (!config.enabled) {
      next()
      return
    }
    const credentials = decodeCredentials(request.headers.authorization)
    const authorized = credentials
      && equalText(credentials[0], config.username)
      && equalText(credentials[1], config.password)
    if (authorized) {
      next()
      return
    }
    response.statusCode = 401
    response.setHeader('WWW-Authenticate', `Basic realm="${config.realm}", charset="UTF-8"`)
    response.setHeader('Cache-Control', 'no-store')
    response.setHeader('Content-Type', 'text/plain; charset=utf-8')
    response.end('Authentication required')
  }
}
