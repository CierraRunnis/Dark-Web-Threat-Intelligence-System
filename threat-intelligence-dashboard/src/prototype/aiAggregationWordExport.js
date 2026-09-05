import MarkdownIt from 'markdown-it'
import {
  AlignmentType, BorderStyle, Document, ExternalHyperlink, HeadingLevel,
  LevelFormat, Packer, Paragraph, Table, TableCell, TableLayoutType, TableRow,
  TextRun, VerticalAlign, WidthType,
} from 'docx'

const FONT = { ascii: 'Calibri', hAnsi: 'Calibri', eastAsia: 'Microsoft YaHei' }
const CODE_FONT = { ...FONT, ascii: 'Consolas', hAnsi: 'Consolas' }
const HEADINGS = [1, 2, 3, 4, 5, 6].map((level) => HeadingLevel[`HEADING_${level}`])
const safeLink = (url) => /^(https?:\/\/|mailto:)/i.test(url)
const parser = new MarkdownIt({ html: false, linkify: true, typographer: false })
// This parser only produces tokens for OOXML, never HTML. Preserve unsafe link
// labels as plain text below; only safeLink destinations become active links.
parser.validateLink = () => true

function inlineText(tokens = []) {
  return tokens.map((token) => token.type === 'softbreak' || token.type === 'hardbreak'
    ? ' ' : token.type === 'image' ? inlineText(token.children) : token.content || '').join('')
}

function inlineRuns(tokens = [], baseFormat = {}) {
  const output = []
  const formats = [{ ...baseFormat }]
  let link = null
  const append = (run) => (link ? link.children : output).push(run)
  for (const token of tokens) {
    const format = formats[formats.length - 1]
    const flags = { strong_open: 'bold', em_open: 'italics', s_open: 'strike' }
    if (flags[token.type]) {
      formats.push({ ...format, [flags[token.type]]: true })
    } else if (['strong_close', 'em_close', 's_close'].includes(token.type)) {
      formats.pop()
    } else if (token.type === 'link_open') {
      link = { url: token.attrGet('href') || '', children: [] }
    } else if (token.type === 'link_close') {
      if (safeLink(link.url)) output.push(new ExternalHyperlink({ link: link.url, children: link.children }))
      else output.push(...link.children, new TextRun({ text: ` (${link.url})`, ...format }))
      link = null
    } else if (token.type === 'image') {
      const url = token.attrGet('src') || ''
      const label = inlineText(token.children) || '图片'
      const children = [new TextRun({ text: label, ...format, style: 'Hyperlink' })]
      append(safeLink(url) ? new ExternalHyperlink({ link: url, children }) : new TextRun({ text: `${label} (${url})`, ...format }))
    } else if (token.type === 'hardbreak') {
      append(new TextRun({ break: 1 }))
    } else if (token.type === 'softbreak') {
      append(new TextRun({ text: ' ', ...format }))
    } else {
      const content = token.content || ''
      if (content) append(new TextRun({
        text: content, ...format,
        ...(link && safeLink(link.url) ? { style: 'Hyperlink' } : {}),
        ...(token.type === 'code_inline' ? { font: CODE_FONT } : {}),
      }))
    }
  }
  return output
}

// Retain the parser's list/table nesting instead of guessing from whitespace.
function blockTree(tokens) {
  const root = { children: [] }
  const stack = [root]
  for (const token of tokens) {
    if (token.nesting === -1) { stack.pop(); continue }
    const node = { token, children: [] }
    stack[stack.length - 1].children.push(node)
    if (token.nesting === 1) stack.push(node)
  }
  return root.children
}

function descendants(node, type) {
  return node.children.flatMap((child) => child.token.type === type ? [child] : descendants(child, type))
}

function reportTable(node) {
  const rows = descendants(node, 'tr_open')
  const cells = rows.map((row) => row.children.filter((cell) => ['th_open', 'td_open'].includes(cell.token.type)))
  const count = cells[0].length
  const cellTokens = (cell) => cell?.children.find((child) => child.token.type === 'inline')?.token.children || []
  const weights = cells[0].map((_, col) => cells.reduce((weight, row) => Math.max(weight, Math.min(36, Array.from(inlineText(cellTokens(row[col]))).length)), 8))
  const total = weights.reduce((sum, value) => sum + value, 0)
  const widths = weights.map((weight) => Math.floor(9360 * weight / total))
  widths[count - 1] += 9360 - widths.reduce((sum, value) => sum + value, 0)
  const border = { style: BorderStyle.SINGLE, color: 'D9D9D9', size: 4 }
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    layout: TableLayoutType.FIXED,
    columnWidths: widths,
    borders: { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border },
    rows: cells.map((row, index) => new TableRow({
      tableHeader: index === 0,
      children: Array.from({ length: count }, (_, col) => {
        const align = row[col]?.token.attrGet('style') || ''
        return new TableCell({
          width: { size: widths[col], type: WidthType.DXA },
          margins: { top: 100, bottom: 100, left: 120, right: 120 },
          verticalAlign: VerticalAlign.CENTER,
          shading: index === 0 ? { fill: 'EAF0F6' } : undefined,
          children: [new Paragraph({
            alignment: align.includes('center') ? AlignmentType.CENTER : align.includes('right') ? AlignmentType.RIGHT : AlignmentType.LEFT,
            spacing: { after: 0, line: 280 },
            children: inlineRuns(cellTokens(row[col]), { bold: index === 0, size: 21 }),
          })],
        })
      }),
    })),
  })
}

function markdownDocument(markdown) {
  let tokens = parser.parse(markdown.replace(/\r\n?/g, '\n'), {})
  // Some AI responses wrap the entire report in a Markdown code fence.
  if (tokens.length === 1 && tokens[0].type === 'fence' && /^(md|markdown)$/i.test(tokens[0].info.trim())) {
    tokens = parser.parse(tokens[0].content, {})
  }
  const nodes = blockTree(tokens)
  const firstHeading = nodes[0]?.token.type === 'heading_open' && nodes[0].token.tag === 'h1'
  const hasReportTitle = firstHeading && nodes.filter((node) => node.token.type === 'heading_open' && node.token.tag === 'h1').length === 1
  const titleNode = hasReportTitle ? nodes.shift() : null
  const titleTokens = titleNode?.children[0]?.token.children
  const numbering = []
  const children = []

  function render(nodes, context = { depth: 0, quoteDepth: 0, sectionLevel: 0 }) {
    const paragraph = (runs, options = {}) => {
      const marker = context.item && !context.item.used
      if (context.item) context.item.used = true
      const left = 360 * (context.depth + context.quoteDepth)
      children.push(new Paragraph({
        ...(left ? { indent: { left } } : {}),
        ...(marker ? { numbering: { reference: context.item.reference, level: Math.min(8, context.depth - 1) } } : {}),
        ...options, children: runs,
      }))
    }
    for (const node of nodes) {
      const { token } = node
      if (['ordered_list_open', 'bullet_list_open'].includes(token.type)) {
        const ordered = token.type === 'ordered_list_open'
        const reference = `report-list-${numbering.length}`
        const level = Math.min(8, context.depth)
        numbering.push({ reference, levels: Array.from({ length: 9 }, (_, index) => ({
          level: index,
          format: ordered ? LevelFormat.DECIMAL : LevelFormat.BULLET,
          text: ordered ? `%${index + 1}.` : ['•', '◦', '▪'][index % 3],
          start: ordered && index === level ? Number(token.attrGet('start') || 1) : 1,
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 360 * (index + 1 + context.quoteDepth), hanging: 240 } } },
        })) })
        for (const item of node.children) {
          const first = item.children[0]?.children[0]?.token.children || []
          const significant = first.filter((part) => part.type !== 'text' || part.content.trim())
          const hasDetails = item.children.some((part) => /^(ordered|bullet)_list_open$/.test(part.token.type))
          const itemHeading = ordered && context.depth === 0 && hasDetails
            && significant[0]?.type === 'strong_open' && significant.at(-1)?.type === 'strong_close'
          render(item.children, {
            ...context, depth: context.depth + 1,
            item: { reference, used: false, heading: itemHeading },
          })
        }
      } else if (token.type === 'blockquote_open') {
        render(node.children, { ...context, quoteDepth: context.quoteDepth + 1 })
      } else if (token.type === 'table_open') {
        children.push(reportTable(node), new Paragraph({ spacing: { after: 100 } }))
      } else if (token.type === 'heading_open') {
        const level = Math.max(1, Number(token.tag.slice(1)) - (hasReportTitle ? 1 : 0))
        context.sectionLevel = level
        paragraph(inlineRuns(node.children[0]?.token.children), { heading: HEADINGS[level - 1] })
      } else if (token.type === 'paragraph_open') {
        const parts = node.children[0]?.token.children || []
        const itemHeading = context.item?.heading && !context.item.used
        const taskParts = context.item && !context.item.used ? parts.map((part, index) => index === 0 && part.type === 'text'
          ? { ...part, content: part.content.replace(/^\[([ xX])\]\s+/, (_, checked) => checked === ' ' ? '☐ ' : '☑ ') } : part) : parts
        paragraph(inlineRuns(taskParts, context.quoteDepth ? { italics: true } : {}), itemHeading ? {
          heading: HEADINGS[Math.min(5, context.sectionLevel)],
          run: { size: 22 }, spacing: { before: 160, after: 120 },
        } : {})
      } else if (token.type === 'fence' || token.type === 'code_block') {
        const lines = token.content.replace(/\n$/, '').split('\n')
        for (const line of lines) paragraph([new TextRun({ text: line, font: CODE_FONT, size: 20 })], { spacing: { after: 0, line: 260 } })
        children.push(new Paragraph({ spacing: { after: 100 } }))
      } else if (token.type === 'hr') {
        children.push(new Paragraph({ spacing: { after: 120 } }))
      }
    }
  }
  render(nodes)
  return { children, numbering, titleTokens }
}

export function createAiReportDocument({ markdown, runId = '', keywords = '', completedAt = '' } = {}) {
  if (!String(markdown || '').trim()) throw new Error('报告内容为空，无法导出 Word。')
  const { children, numbering, titleTokens } = markdownDocument(String(markdown))
  const title = titleTokens ? inlineText(titleTokens) : 'AI 聚合威胁情报报告'
  return new Document({
    creator: '玄鉴', title,
    styles: {
      default: {
        document: { run: { font: FONT, size: 22, color: '000000' }, paragraph: { spacing: { after: 120, line: 320 } } },
        title: { run: { font: FONT, size: 36, bold: true, color: '000000' }, paragraph: { spacing: { after: 180 } } },
        ...Object.fromEntries(HEADINGS.map((_, index) => [`heading${index + 1}`, {
          run: { font: FONT, size: [32, 28, 25, 24, 23, 22][index], bold: true, color: '000000' },
          paragraph: { outlineLevel: index, keepNext: true, keepLines: true, spacing: { before: 240, after: 120 } },
        }])),
      },
    },
    numbering: { config: numbering },
    sections: [{
      properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
      children: [
        new Paragraph({ heading: HeadingLevel.TITLE, children: titleTokens ? inlineRuns(titleTokens) : [new TextRun(title)] }),
        ...[['关键词', Array.isArray(keywords) ? keywords.join('、') : keywords], ['完成时间', completedAt], ['报告编号', runId]]
          .filter(([, value]) => value).map(([label, value]) => new Paragraph({ children: [new TextRun({ text: `${label}：${value}`, size: 20 })] })),
        ...children,
      ],
    }],
  })
}

export async function exportAiReportWord(report) {
  const blob = await Packer.toBlob(createAiReportDocument(report))
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `ai-intelligence-${String(report.runId || 'report').replace(/[^a-zA-Z0-9_-]/g, '_')}.docx`
  document.body.append(link)
  try { link.click() } finally {
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
