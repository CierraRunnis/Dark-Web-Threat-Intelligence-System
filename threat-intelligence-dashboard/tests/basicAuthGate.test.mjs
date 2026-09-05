import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createBasicAuthMiddleware,
  resolveBasicAuthConfig,
} from '../build/basicAuthGate.js'


function invoke(config, authorization = '') {
  const headers = {}
  const response = {
    headers,
    statusCode: 200,
    body: '',
    setHeader(name, value) {
      headers[name] = value
    },
    end(value = '') {
      this.body = value
    },
  }
  let nextCalled = false
  createBasicAuthMiddleware(config)(
    { headers: { authorization } },
    response,
    () => { nextCalled = true },
  )
  return { response, nextCalled }
}


test('disabled gate passes requests through', () => {
  const result = invoke(resolveBasicAuthConfig({}))
  assert.equal(result.nextCalled, true)
})


test('enabled gate refuses to start without a password', () => {
  assert.throws(
    () => resolveBasicAuthConfig({ DARKWEB_BASIC_AUTH_ENABLED: '1' }),
    /requires DARKWEB_BASIC_AUTH_PASSWORD/,
  )
})


test('enabled gate challenges missing or invalid credentials', () => {
  const config = resolveBasicAuthConfig({
    DARKWEB_BASIC_AUTH_ENABLED: 'true',
    DARKWEB_BASIC_AUTH_USERNAME: 'site-user',
    DARKWEB_BASIC_AUTH_PASSWORD: 'site:password',
  })
  const missing = invoke(config)
  const invalid = invoke(config, `Basic ${Buffer.from('site-user:wrong').toString('base64')}`)

  assert.equal(missing.response.statusCode, 401)
  assert.match(missing.response.headers['WWW-Authenticate'], /^Basic realm=/)
  assert.equal(invalid.nextCalled, false)
})


test('enabled gate accepts the configured credentials including a colon in the password', () => {
  const config = resolveBasicAuthConfig({
    DARKWEB_BASIC_AUTH_ENABLED: 'yes',
    DARKWEB_BASIC_AUTH_USERNAME: 'site-user',
    DARKWEB_BASIC_AUTH_PASSWORD: 'site:password',
  })
  const authorization = `Basic ${Buffer.from('site-user:site:password').toString('base64')}`
  const result = invoke(config, authorization)

  assert.equal(result.nextCalled, true)
  assert.equal(result.response.statusCode, 200)
})
