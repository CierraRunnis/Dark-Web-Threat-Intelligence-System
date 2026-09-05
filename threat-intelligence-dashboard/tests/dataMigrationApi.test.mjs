import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  MIGRATION_STATUS_KEYS,
  createDataMigrationApi,
  isMigrationPollingStatus,
  migrationStatusKey,
  migrationStatusMeta,
} from '../src/composables/useDataMigrationApi.js'

const root = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('迁移 API 使用完整 REST 合约并以原始请求体上传文件', async () => {
  const calls = []
  const api = createDataMigrationApi({
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, options })
      return jsonResponse({ items: [] })
    },
  })
  const file = new Blob(['dwti'])
  Object.defineProperty(file, 'name', { value: '迁移 包.dwti' })

  await api.getConfig()
  await api.listJobs()
  await api.getJob('job / 1')
  await api.uploadBundle(file)
  await api.submitPerformance('job / 1', { p95_ms: 120 })
  await api.activate('job / 1')

  assert.deepEqual(calls.map(({ url, options }) => [url, options.method || 'GET']), [
    ['/api/migrations/config', 'GET'],
    ['/api/migrations', 'GET'],
    ['/api/migrations/job%20%2F%201', 'GET'],
    ['/api/migrations/upload', 'POST'],
    ['/api/migrations/job%20%2F%201/performance', 'POST'],
    ['/api/migrations/job%20%2F%201/activate', 'POST'],
  ])
  assert.equal(calls[3].options.body, file)
  assert.equal(calls[3].options.headers['Content-Type'], 'application/octet-stream')
  assert.equal(calls[3].options.headers['x-dwti-filename'], encodeURIComponent('迁移 包.dwti'))
  assert.equal(calls[4].options.headers['Content-Type'], 'application/json')
  assert.equal(calls[4].options.body, JSON.stringify({ p95_ms: 120 }))
})

test('迁移状态机覆盖导入、激活、失败和回退状态', () => {
  const required = [
    'queued',
    'preflight',
    'importing',
    'verifying',
    'analyzing',
    'ready',
    'activating',
    'active',
    'failed',
    'rolled_back',
    'rollback_failed',
  ]
  assert.deepEqual(MIGRATION_STATUS_KEYS, required)
  assert.equal(migrationStatusKey({ status: 'preparing', phase: 'preflight' }), 'preflight')
  assert.equal(migrationStatusKey({ status: 'preparing', phase: 'database' }), 'importing')
  assert.equal(migrationStatusKey({ status: 'preparing', phase: 'verify' }), 'verifying')
  assert.equal(migrationStatusKey({ status: 'restart_required' }), 'activating')
  assert.equal(migrationStatusMeta({ status: 'importing', progress: 151 }).progress, 100)
  assert.equal(isMigrationPollingStatus({ status: 'activating' }), true)
  assert.equal(isMigrationPollingStatus({ status: 'restart_required' }), false)
  assert.equal(isMigrationPollingStatus({ status: 'ready' }), false)
})

test('路由和两套导航都只向管理员暴露数据迁移页面', async () => {
  const [router, sidebar, runtime, view] = await Promise.all([
    read('src/router/index.js'),
    read('src/components/layout/Sidebar.vue'),
    read('src/prototype/runtime.js'),
    read('src/views/DataMigration.vue'),
  ])
  assert.match(router, /const DataMigration = \(\) => import\(['"]@\/views\/DataMigration\.vue['"]\)/)
  assert.match(router, /path:\s*['"]\/settings\/data-migration['"][\s\S]*?name:\s*['"]DataMigration['"][\s\S]*?adminOnly:\s*true[\s\S]*?layout:\s*['"]prototype-vue['"]/)
  assert.match(sidebar, /adminOnly:\s*true,\s*path:\s*['"]\/settings\/data-migration['"]/)
  assert.match(runtime, /isCurrentUserAdmin\(\)\s*&&\s*\{\s*path:\s*['"]\/settings\/data-migration['"]/)
  assert.match(view, /uploadBundle\(selectedFile\.value\)/)
  assert.match(view, /confirmActivate/)
  assert.match(view, /pollCurrentJob/)
})

test('迁移 API 优先展示后端错误详情', async () => {
  const api = createDataMigrationApi({
    fetchImpl: async () => jsonResponse({ detail: 'Schema 指纹不匹配' }, 409),
  })
  await assert.rejects(api.getConfig(), /Schema 指纹不匹配/)
})
