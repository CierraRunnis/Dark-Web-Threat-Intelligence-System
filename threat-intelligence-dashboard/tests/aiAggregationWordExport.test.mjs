import test from 'node:test'
import assert from 'node:assert/strict'
import JSZip from 'jszip'
import { xml2js } from 'xml-js'
import { Packer } from 'docx'
import { createAiReportDocument, exportAiReportWord } from '../src/prototype/aiAggregationWordExport.js'

const list = (value) => value == null ? [] : Array.isArray(value) ? value : [value]
const attrs = (value) => value?._attributes || {}
const textOf = (value) => {
  if (!value || typeof value !== 'object') return ''
  return Object.entries(value).map(([key, child]) => key === '_text' ? child : key.startsWith('_') ? '' : list(child).map(textOf).join('')).join('')
}
async function unpack(markdown) {
  const bytes = await Packer.toBuffer(createAiReportDocument({ markdown, runId: 'run-test', keywords: ['能源', '制造业'], completedAt: '2026/9/5 12:00:00' }))
  const zip = await JSZip.loadAsync(bytes)
  const xml = async (path) => xml2js(await zip.file(path).async('string'), { compact: true, captureSpacesBetweenElements: true })
  return { zip, body: (await xml('word/document.xml'))['w:document']['w:body'], styles: (await xml('word/styles.xml'))['w:styles'], xml }
}

test('Word report chapters have native Heading styles and matching outline levels for navigation', async () => {
  const { body, styles } = await unpack([
    '# 报告总览', '正文包含 **高风险** 与 `CVE-2026-0001`。',
    '## 重点事件', '### 来源核实', '#### 证据', '##### 记录', '###### 附注',
    '```text', '# 这是代码，不是章节', '```',
    '后续建议', '========', '补充材料', '--------',
  ].join('\n'))
  const paragraphs = list(body['w:p'])
  const headings = paragraphs.filter((p) => /^Heading/.test(attrs(p['w:pPr']?.['w:pStyle'])['w:val']))
  assert.deepEqual(headings.map((p) => [attrs(p['w:pPr']['w:pStyle'])['w:val'], textOf(p)]), [
    ['Heading1', '报告总览'], ['Heading2', '重点事件'], ['Heading3', '来源核实'],
    ['Heading4', '证据'], ['Heading5', '记录'], ['Heading6', '附注'],
    ['Heading1', '后续建议'], ['Heading2', '补充材料'],
  ])
  for (let level = 1; level <= 6; level += 1) {
    const style = list(styles['w:style']).find((style) => attrs(style)['w:styleId'] === `Heading${level}`)
    assert.equal(attrs(style['w:pPr']['w:outlineLvl'])['w:val'], String(level - 1))
    assert.ok('w:keepNext' in style['w:pPr'])
  }
  assert.match(textOf(body), /关键词：能源、制造业/)
  assert.match(textOf(body), /正文包含 高风险 与 CVE-2026-0001/)
  assert.match(textOf(body), /# 这是代码，不是章节/)
})

test('Word report preserves native tables, lists, escaped text and safe clickable source links', async () => {
  const { body, xml } = await unpack([
    '# 威胁摘要', '- 第一项', '  - 子项', '1. 检查', '2. 修复', '',
    '| 事件 | 级别 |', '| :--- | ---: |', '| 数据泄露 | 高 |', '| A \\| B | 中 |', '',
    '[来源](https://example.com/report?q=1&lang=zh)',
    '[拒绝执行](javascript:alert)', '<script>text only</script>',
    'incident_id_123 https://example.com/source_file_name __加粗__ _斜体_',
  ].join('\n'))
  const rows = list(list(body['w:tbl'])[0]['w:tr'])
  assert.equal(rows.length, 3)
  assert.ok('w:tblHeader' in rows[0]['w:trPr'])
  assert.equal(textOf(list(rows[2]['w:tc'])[0]), 'A | B')
  assert.equal(list(body['w:p']).filter((p) => p['w:pPr']?.['w:numPr']).length, 4)
  const relations = list((await xml('word/_rels/document.xml.rels')).Relationships.Relationship)
  const links = relations.filter((r) => attrs(r).Type.endsWith('/hyperlink'))
  assert.deepEqual(links.map((r) => attrs(r).Target), ['https://example.com/report?q=1&lang=zh', 'https://example.com/source_file_name'])
  assert.match(textOf(body), /拒绝执行 \(javascript:alert\)/)
  assert.match(textOf(body), /<script>text only<\/script>/)
  assert.match(textOf(body), /incident_id_123/)
  assert.match(textOf(body), /加粗 斜体/)
})

test('empty reports fail explicitly instead of downloading a blank file', () => {
  assert.throws(() => createAiReportDocument({ markdown: ' \n' }), /报告内容为空/)
})

test('a real report structure uses its own Word title and navigable numbered event headings', async () => {
  const { body, xml } = await unpack([
    '# 能源威胁情报报告', '', '## 关键发现', '',
    '9. **事件九**', '   - 类型：数据泄露', '   - 样本链接：', '     - https://example.com/nine', '',
    '10. **事件十**', '    - 类型：漏洞', '    - 样本链接：', '      - https://example.com/ten', '',
    '## 处置建议', '', '1. 验证影响', '2. 记录结论',
  ].join('\n'))
  const paragraphs = list(body['w:p'])
  assert.equal(attrs(paragraphs[0]['w:pPr']['w:pStyle'])['w:val'], 'Title')
  assert.equal(textOf(paragraphs[0]), '能源威胁情报报告')
  assert.doesNotMatch(textOf(body), /AI 聚合威胁情报报告|\*\*|##/)
  const events = paragraphs.filter((p) => /^事件[九十]$/.test(textOf(p)))
  assert.equal(events.length, 2)
  const numberIds = events.map((p) => attrs(p['w:pPr']['w:numPr']['w:numId'])['w:val'])
  assert.equal(numberIds[0], numberIds[1], 'nested bullet lists must not restart the parent numbering')
  for (const p of events) {
    assert.equal(attrs(p['w:pPr']['w:pStyle'])['w:val'], 'Heading2')
    assert.equal(attrs(p['w:pPr']['w:numPr']['w:ilvl'])['w:val'], '0')
  }
  for (const p of paragraphs.filter((p) => textOf(p).startsWith('类型：'))) {
    assert.equal(attrs(p['w:pPr']['w:numPr']['w:ilvl'])['w:val'], '1')
  }
  const numbering = (await xml('word/numbering.xml'))['w:numbering']
  assert.ok(list(numbering['w:abstractNum']).some((num) => list(num['w:lvl']).some((level) => attrs(level['w:start'])['w:val'] === '9')))
})

test('nested Markdown emphasis, reference links and line breaks become Word formatting without visible markers', async () => {
  const { body, xml } = await unpack([
    '# 报告', '', '## 结论', '', '***重要*** 与 ~~过期~~，&amp; 表示与。', '',
    '[参考][source]', '', '[说明](https://example.com/wiki/Topic_(detail))', '',
    '同一段落的第一行', '第二行  ', '强制换行', '',
    '| 字段 | 详情 |', '| --- | --- |', '| **状态** | [来源][source] |', '',
    '[source]: https://example.com/reference "来源说明"',
  ].join('\n'))
  assert.doesNotMatch(textOf(body), /\*\*|~~|\[source\]|\[参考\]|\[说明\]|&amp;|---/)
  const paragraphs = list(body['w:p'])
  const important = paragraphs.flatMap((p) => list(p['w:r'])).find((run) => textOf(run) === '重要')
  assert.ok('w:b' in important['w:rPr'] && 'w:i' in important['w:rPr'])
  const expired = paragraphs.flatMap((p) => list(p['w:r'])).find((run) => textOf(run) === '过期')
  assert.ok('w:strike' in expired['w:rPr'])
  const paragraph = paragraphs.find((p) => textOf(p).includes('同一段落'))
  assert.match(textOf(paragraph), /同一段落的第一行 第二行/)
  assert.ok(list(paragraph['w:r']).some((run) => 'w:br' in run))
  const rels = list((await xml('word/_rels/document.xml.rels')).Relationships.Relationship)
  assert.ok(rels.some((r) => attrs(r).Target === 'https://example.com/wiki/Topic_(detail)'))
  const table = list(body['w:tbl'])[0]
  assert.match(textOf(table), /字段详情状态来源/)
})

test('an AI Markdown wrapper is converted to a document while genuine source code stays literal', async () => {
  const { body } = await unpack('```markdown\n# 报告\n\n## 结论\n\n**高风险**\n```')
  assert.equal(attrs(list(body['w:p'])[0]['w:pPr']['w:pStyle'])['w:val'], 'Title')
  assert.doesNotMatch(textOf(body), /```|##|\*\*/)
  const code = await unpack('# 报告\n\n```python\n# keep code comment\nvalue = 2 ** 3\n```')
  assert.match(textOf(code.body), /# keep code commentvalue = 2 \*\* 3/)
})

test('Word download produces a DOCX, names the selected report and cleans up its browser resources', async (t) => {
  let downloaded = false
  let removed = false
  let appended = false
  let revoked = false
  let pendingCleanup
  const link = { click: () => { downloaded = true }, remove: () => { removed = true } }
  t.mock.method(URL, 'createObjectURL', (blob) => {
    assert.match(blob.type, /wordprocessingml/)
    return 'blob:word-report'
  })
  t.mock.method(URL, 'revokeObjectURL', (url) => { assert.equal(url, 'blob:word-report'); revoked = true })
  t.mock.method(globalThis, 'setTimeout', (callback) => { pendingCleanup = callback })
  const previousDocument = globalThis.document
  globalThis.document = {
    createElement: (name) => { assert.equal(name, 'a'); return link },
    body: { append: (node) => { assert.equal(node, link); appended = true } },
  }
  t.after(() => { if (previousDocument === undefined) delete globalThis.document; else globalThis.document = previousDocument })
  await exportAiReportWord({ markdown: '# 报告\n正文', runId: 'selected-run' })
  assert.equal(link.download, 'ai-intelligence-selected-run.docx')
  assert.ok(appended && downloaded && removed)
  assert.equal(revoked, false)
  pendingCleanup()
  assert.equal(revoked, true)
})
