import test from 'node:test'
import assert from 'node:assert/strict'
import { createAiAggregationApi } from '../src/prototype/aiAggregationApi.js'

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } })
}

test('运行已保存模板只发送一次空JSON对象', async () => {
  const calls = []
  const api = createAiAggregationApi({ fetchImpl: async (url, options) => { calls.push({ url, options }); return jsonResponse({ run_id: 'run-1', status: 'queued' }, 202) } })
  await api.runProfile('profile / 1')
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/ai-aggregation/profiles/profile%20%2F%201/run')
  assert.equal(calls[0].options.method, 'POST')
  assert.equal(calls[0].options.body, '{}')
  assert.equal(calls[0].options.body.includes('keywords'), false)
  assert.equal(calls[0].options.body.includes('search_window_days'), false)
})

test('共享client覆盖Profile CRUD、历史和投递重试', async () => {
  const calls = []
  const api = createAiAggregationApi({ fetchImpl: async (url, options = {}) => { calls.push([url, options.method || 'GET']); return jsonResponse({}) } })
  await api.listProfiles(); await api.createProfile({ name: 'A' }); await api.updateProfile('p1', { name: 'B' }); await api.deleteProfile('p1'); await api.listRuns(); await api.getRun('r1'); await api.retryDeliveries('r1')
  assert.deepEqual(calls.map(([url, method]) => [url.replace(/\?.*$/, ''), method]), [
    ['/api/ai-aggregation/profiles', 'GET'], ['/api/ai-aggregation/profiles', 'POST'], ['/api/ai-aggregation/profiles/p1', 'PUT'], ['/api/ai-aggregation/profiles/p1', 'DELETE'], ['/api/ai-aggregation/runs', 'GET'], ['/api/ai-aggregation/runs/r1', 'GET'], ['/api/ai-aggregation/runs/r1/retry-deliveries', 'POST'],
  ])
})

test('AbortSignal传入所有请求', async () => {
  const controller = new AbortController()
  let observed
  const api = createAiAggregationApi({ signal: controller.signal, fetchImpl: async (_url, options) => { observed = options.signal; return jsonResponse({ items: [] }) } })
  await api.listProfiles()
  assert.equal(observed, controller.signal)
})

