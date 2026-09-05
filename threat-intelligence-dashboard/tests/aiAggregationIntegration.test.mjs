import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const root = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')

test('两个AI screen都使用同一Prototype壳', async () => {
  for (const path of ['src/prototype/screens/ai-aggregation.html', 'src/prototype/screens/ai-aggregation-templates.html']) {
    const screen = await read(path)
    assert.match(screen, /class="app-shell sidebar-collapsed"/)
    assert.match(screen, /class="app-sidebar"/)
    assert.match(screen, /class="app-stage"/)
    assert.match(screen, /class="app-header"/)
    assert.match(screen, /class="app-main" id="content"/)
  }
})

test('dataRuntime独立分派run/templates hydrator并传route', async () => {
  const runtime = await read('src/prototype/dataRuntime.js')
  assert.match(runtime, /import\s*\{\s*hydrateAiAggregationScreen\s*\}\s*from\s*['"]\.\/aiAggregationRuntime\.js['"]/)
  assert.match(runtime, /import\s*\{\s*hydrateAiAggregationTemplatesScreen\s*\}\s*from\s*['"]\.\/aiAggregationTemplatesRuntime\.js['"]/)
  assert.match(runtime, /hydrateAiAggregationScreen\(\{\s*root,\s*signal:[^}]+route/s)
  assert.match(runtime, /hydrateAiAggregationTemplatesScreen\(\{\s*root,\s*signal:[^}]+route/s)
})

test('路由、PrototypeScreen映射、权限与导航保持同一AI模块', async () => {
  const [view, router, navigation, permissions] = await Promise.all([
    read('src/views/PrototypeScreen.vue'), read('src/router/index.js'), read('src/prototype/runtime.js'), read('src/config/permissions.js'),
  ])
  assert.match(view, /['"]ai-aggregation\.html['"]:\s*['"]\/ai-aggregation['"]/)
  assert.match(view, /['"]ai-aggregation-templates\.html['"]:\s*['"]\/ai-aggregation\/templates['"]/)
  assert.match(router, /\/ai-aggregation\/templates/)
  assert.match(router, /MODULE_KEYS\.AI_AGGREGATION/)
  assert.match(navigation, /hasModuleAccess\(MODULE_KEYS\.AI_AGGREGATION\)/)
  assert.match(permissions, /AI_AGGREGATION:\s*['"]ai_aggregation['"]/)
})

test('PrototypeScreen在route leave/update前调用AI dirty guard', async () => {
  const view = await read('src/views/PrototypeScreen.vue')
  assert.match(view, /__prototypeBeforeLeave/)
  assert.match(view, /onBeforeRouteLeave/)
  assert.match(view, /onBeforeRouteUpdate/)
})
