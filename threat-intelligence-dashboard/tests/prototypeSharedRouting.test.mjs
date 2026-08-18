import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const root = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, root), 'utf8')

test('共享路由隐藏挂载 AI 模板页并沿用 AI 模块权限', async () => {
  const router = await read('src/router/index.js')
  assert.match(
    router,
    /prototypeScreen\(\s*['"]\/ai-aggregation\/templates['"],\s*['"]AiAggregationTemplates['"],\s*['"]ai-aggregation-templates\.html['"],\s*\{[\s\S]*?hidden:\s*true/,
  )
  assert.match(router, /\[['"]\/ai-aggregation['"],\s*MODULE_KEYS\.AI_AGGREGATION\]/)
  assert.match(router, /to\.path\.startsWith\(`\$\{path\}\/[`]\)/)
})

test('PrototypeScreen 改写模板链接并在路由切换前调用页面守卫', async () => {
  const view = await read('src/views/PrototypeScreen.vue')
  assert.match(view, /['"]ai-aggregation-templates\.html['"]:\s*['"]\/ai-aggregation\/templates['"]/)
  assert.match(view, /onBeforeRouteLeave\(invokePrototypeBeforeLeave\)/)
  assert.match(view, /onBeforeRouteUpdate\(invokePrototypeBeforeLeave\)/)
  assert.match(view, /screenRoot\.value\?\.__prototypeBeforeLeave/)
  assert.match(view, /return result === false \? false : true/)
  assert.match(view, /delete screenRoot\.value\.__prototypeBeforeLeave/)
})

test('dataRuntime 分别分派 AI 运行页和模板设置页并传递 route 与 AbortSignal', async () => {
  const runtime = await read('src/prototype/dataRuntime.js')
  assert.match(
    runtime,
    /import\s*\{\s*hydrateAiAggregationTemplatesScreen\s*\}\s*from\s*['"]\.\/aiAggregationTemplatesRuntime\.js['"]/,
  )
  assert.match(runtime, /['"]ai-aggregation\.html['"]/)
  assert.match(runtime, /['"]ai-aggregation-templates\.html['"]/)
  assert.match(
    runtime,
    /hydrateAiAggregationScreen\(\{\s*root,\s*signal:\s*root\.__dataRuntimeAbort\.signal,\s*route\s*\}\)/,
  )
  assert.match(
    runtime,
    /hydrateAiAggregationTemplatesScreen\(\{\s*root,\s*signal:\s*root\.__dataRuntimeAbort\.signal,\s*route\s*\}\)/,
  )
})
