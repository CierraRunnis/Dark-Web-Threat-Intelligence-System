import { createHmac, timingSafeEqual } from 'node:crypto'

import { resolveBasicAuthConfig } from './basicAuthGate.js'


const COOKIE_NAME = 'dwti_basic_gate'


function equalText(left, right) {
  const leftBuffer = Buffer.from(String(left), 'utf8')
  const rightBuffer = Buffer.from(String(right), 'utf8')
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer)
}


function decodeBasicCredentials(authorization) {
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


function parseCookies(header) {
  return Object.fromEntries(
    String(header || '')
      .split(';')
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => {
        const separator = item.indexOf('=')
        return separator < 0
          ? [item, '']
          : [item.slice(0, separator), item.slice(separator + 1)]
      }),
  )
}


function signature(config, expiresAt) {
  return createHmac('sha256', config.password)
    .update(`v1:${config.username}:${expiresAt}:${config.realm}`, 'utf8')
    .digest('hex')
}


function validCookie(config, value, nowSeconds) {
  const [expiresText, providedSignature, ...rest] = String(value || '').split('.')
  if (rest.length || !/^\d+$/.test(expiresText || '') || !providedSignature) return false
  const expiresAt = Number(expiresText)
  return expiresAt >= nowSeconds && equalText(providedSignature, signature(config, expiresAt))
}


function ttlSeconds(environments) {
  const raw = environments
    .map((environment) => String(environment?.DARKWEB_BASIC_AUTH_TTL_SECONDS || '').trim())
    .find(Boolean)
  const parsed = Number(raw || 43200)
  return Number.isFinite(parsed) ? Math.min(604800, Math.max(60, Math.trunc(parsed))) : 43200
}


export function resolveBasicAuthCookieConfig(...environments) {
  return {
    ...resolveBasicAuthConfig(...environments),
    ttlSeconds: ttlSeconds(environments),
  }
}


export function createBasicAuthCookieMiddleware(config, clock = () => Date.now()) {
  return (request, response, next) => {
    if (!config.enabled) {
      next()
      return
    }

    // start_all_services_wsl.sh probes the frontend root with curl. Return an
    // empty success response without exposing page content or assets.
    const loopbackProbe = request.url === '/'
      && /^(127\.0\.0\.1|localhost)(?::\d+)?$/i.test(String(request.headers.host || ''))
      && /^curl\//i.test(String(request.headers['user-agent'] || ''))
    if (loopbackProbe) {
      response.statusCode = 204
      response.end()
      return
    }

    const authorization = String(request.headers.authorization || '')
    const basicAttempted = authorization.split(/\s+/, 1)[0].toLowerCase() === 'basic'
    const credentials = basicAttempted ? decodeBasicCredentials(authorization) : null
    const basicValid = credentials
      && equalText(credentials[0], config.username)
      && equalText(credentials[1], config.password)
    const nowSeconds = Math.trunc(clock() / 1000)
    const cookieValid = validCookie(
      config,
      parseCookies(request.headers.cookie)[COOKIE_NAME],
      nowSeconds,
    )

    if (!basicValid && (basicAttempted || !cookieValid)) {
      response.statusCode = 401
      response.setHeader('WWW-Authenticate', `Basic realm="${config.realm}", charset="UTF-8"`)
      response.setHeader('Cache-Control', 'no-store')
      response.setHeader('Content-Type', 'text/plain; charset=utf-8')
      response.end('Authentication required')
      return
    }

    if (basicValid) {
      const expiresAt = nowSeconds + config.ttlSeconds
      const secure = request.socket?.encrypted
        || String(request.headers['x-forwarded-proto'] || '').toLowerCase() === 'https'
      response.setHeader(
        'Set-Cookie',
        `${COOKIE_NAME}=${expiresAt}.${signature(config, expiresAt)}; Max-Age=${config.ttlSeconds}; Path=/; HttpOnly; SameSite=Strict${secure ? '; Secure' : ''}`,
      )
    }
    next()
  }
}
