import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createBasicAuthCookieMiddleware,
  resolveBasicAuthCookieConfig,
} from '../build/basicAuthCookieGate.js'


function invoke(config, { authorization = '', cookie = '', now = 1_700_000_000_000 } = {}) {
  const headers = {}
  const response = {
    headers,
    statusCode: 200,
    setHeader(name, value) { headers[name] = value },
    end(value = '') { this.body = value },
  }
  let nextCalled = false
  createBasicAuthCookieMiddleware(config, () => now)(
    {
      url: '/api/auth/me',
      headers: { authorization, cookie, host: 'example.test' },
      socket: {},
    },
    response,
    () => { nextCalled = true },
  )
  return { response, nextCalled }
}


const config = resolveBasicAuthCookieConfig({
  DARKWEB_BASIC_AUTH_ENABLED: '1',
  DARKWEB_BASIC_AUTH_USERNAME: 'outer-user',
  DARKWEB_BASIC_AUTH_PASSWORD: 'outer-secret',
  DARKWEB_BASIC_AUTH_TTL_SECONDS: '600',
})


test('valid Basic credentials issue a signed HttpOnly gate cookie', () => {
  const authorization = `Basic ${Buffer.from('outer-user:outer-secret').toString('base64')}`
  const result = invoke(config, { authorization })

  assert.equal(result.nextCalled, true)
  assert.match(result.response.headers['Set-Cookie'], /^dwti_basic_gate=/)
  assert.match(result.response.headers['Set-Cookie'], /HttpOnly/)
  assert.match(result.response.headers['Set-Cookie'], /SameSite=Strict/)
})


test('signed gate cookie allows a later Bearer request to pass', () => {
  const authorization = `Basic ${Buffer.from('outer-user:outer-secret').toString('base64')}`
  const first = invoke(config, { authorization })
  const cookie = first.response.headers['Set-Cookie'].split(';', 1)[0]
  const second = invoke(config, { authorization: 'Bearer application-token', cookie })

  assert.equal(second.nextCalled, true)
  assert.equal(second.response.statusCode, 200)
})


test('missing or tampered gate cookie is challenged when Bearer occupies Authorization', () => {
  const missing = invoke(config, { authorization: 'Bearer application-token' })
  const tampered = invoke(config, {
    authorization: 'Bearer application-token',
    cookie: 'dwti_basic_gate=9999999999.invalid',
  })

  assert.equal(missing.response.statusCode, 401)
  assert.equal(tampered.response.statusCode, 401)
  assert.match(missing.response.headers['WWW-Authenticate'], /^Basic realm=/)
})
