import test from 'node:test'
import assert from 'node:assert/strict'
import {
  DEFAULT_AI_PROMPT_TEMPLATE, MAX_SEARCH_WINDOW_DAYS, MAX_TEMPLATE_KEYWORDS,
  hasRequiredPlaceholders, keywordsToTextarea, normalizeSearchWindowDays,
  parseKeywordLines, renderTemplatePreview,
} from '../src/prototype/aiAggregationTemplate.js'

test('模板契约使用双占位符、30关键词和3650天上限', () => {
  assert.equal(DEFAULT_AI_PROMPT_TEMPLATE, '搜索 {{keywords}} {{time_range}} 的威胁情报')
  assert.equal(MAX_TEMPLATE_KEYWORDS, 30)
  assert.equal(MAX_SEARCH_WINDOW_DAYS, 3650)
  assert.equal(hasRequiredPlaceholders(DEFAULT_AI_PROMPT_TEMPLATE), true)
  assert.equal(hasRequiredPlaceholders('搜索 {{keywords}}'), false)
  assert.equal(hasRequiredPlaceholders('搜索 {{keyword}} {{time_range}}'), false)
})

test('LF/CRLF多行关键词去空、保序去重并回写textarea', () => {
  assert.deepEqual(parseKeywordLines(' 能源 \r\n制造业\n能源\nENERGY\nenergy'), ['能源', '制造业', 'ENERGY'])
  assert.equal(keywordsToTextarea(['能源', '制造业']), '能源\n制造业')
})

test('预览以顿号合并关键词并渲染时间', () => {
  assert.equal(renderTemplatePreview(DEFAULT_AI_PROMPT_TEMPLATE, ['能源', '制造业', 'LockBit'], 2), '搜索 能源、制造业、LockBit 最近2天 的威胁情报')
  assert.equal(normalizeSearchWindowDays(9000), 3650)
})

