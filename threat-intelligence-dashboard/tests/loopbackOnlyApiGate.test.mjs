import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createLoopbackOnlyApiProxyBlocker,
} from '../build/loopbackOnlyApiGate.js'


function invoke(url) {
  const result = { statusCode: 200, headers: {}, body: '', nextCalled: false }
  const response = {
    setHeader(name, value) {
      result.headers[String(name).toLowerCase()] = value
    },
    end(body) {
      result.body = body
    },
  }
  const middleware = createLoopbackOnlyApiProxyBlocker()
  middleware({ url }, response, () => {
    result.nextCalled = true
  })
  result.statusCode = response.statusCode || result.statusCode
  return result
}


test('blocks the machine-only intelligence API before the Vite proxy', () => {
  const result = invoke('/api/ai/intelligence')

  assert.equal(result.statusCode, 403)
  assert.equal(result.nextCalled, false)
  assert.equal(result.headers['cache-control'], 'no-store')
  assert.deepEqual(JSON.parse(result.body), {
    detail: '该接口仅允许直接通过 127.0.0.1:8000 本地访问',
  })
})


test('blocks query, trailing-slash, and encoded forms of the path', () => {
  for (const url of [
    '/api/ai/intelligence?keyword=energy',
    '/api/ai/intelligence/',
    '/%61pi/ai/intelligence?limit=1',
  ]) {
    const result = invoke(url)
    assert.equal(result.statusCode, 403, url)
    assert.equal(result.nextCalled, false, url)
  }
})


test('passes unrelated API paths to the existing proxy', () => {
  for (const url of [
    '/api/health',
    '/api/ai/intelligence-search',
    '/api/ai-aggregation/runs',
  ]) {
    const result = invoke(url)
    assert.equal(result.statusCode, 200, url)
    assert.equal(result.nextCalled, true, url)
  }
})
