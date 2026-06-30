<template>
  <div class="monitor-detail ti-page">
    <section class="detail-shell">
      <header class="detail-shell__header">
        <div>
          <el-button text class="back-button" @click="goBack">返回列表</el-button>
          <div class="detail-shell__eyebrow">{{ detail.sourceFamilyLabel || currentConfig.title }}</div>
          <h2 class="detail-shell__title">{{ detail.title || '-' }}</h2>
          <div class="detail-shell__meta">
            <span>{{ detail.platformLabel || '-' }}</span>
            <span>{{ detail.discoverySourceLabel || '-' }}</span>
            <span>{{ formatDateTime(detail.lastSeenAt) || '-' }}</span>
          </div>
        </div>
        <div class="detail-shell__tags">
          <span v-if="!isNetdiskDetail" :class="['severity-tag', `severity-tag--${detail.severity || 'low'}`]">{{ detail.riskScore || 0 }} 分</span>
          <span class="neutral-tag">{{ detail.reviewStatus || 'new' }}</span>
        </div>
      </header>

      <section v-if="isNetdiskDetail" class="detail-grid detail-grid--files">
        <article class="detail-card detail-card--preview detail-card--netdisk-summary">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">预览</div>
              <h3>分享链接信息</h3>
            </div>
          </div>
          <div class="preview-stage preview-stage--share">
            <dl class="share-preview-list share-preview-list--merged">
              <template v-for="item in sharePreviewItems" :key="item.label">
                <dt>{{ item.label }}</dt>
                <dd>
                  <div v-if="item.kind === 'keywords'" class="share-keyword-tags">
                    <span v-for="term in detail.matchedTerms || []" :key="`${term.term}-${term.term_type}`" class="keyword-tag">
                      {{ term.term }}
                    </span>
                    <span v-if="!(detail.matchedTerms || []).length" class="muted-text">暂无命中关键词</span>
                  </div>
                  <span v-else-if="item.kind === 'platform'" class="share-platform-value">
                    <img
                      v-if="platformIconUrl"
                      class="share-platform-logo"
                      :src="platformIconUrl"
                      :alt="detail.platformLabel || detail.platform || 'platform'"
                      loading="lazy"
                    >
                    <span v-else :class="['share-platform-icon', `share-platform-icon--${platformIconClass}`]">{{ platformIconText }}</span>
                    <span>{{ item.value }}</span>
                  </span>
                  <a
                    v-else-if="item.kind === 'link' && item.value !== '-'"
                    :href="item.value"
                    target="_blank"
                    rel="noreferrer"
                    class="share-preview-link"
                  >
                    {{ item.value }}
                  </a>
                  <span v-else-if="item.kind === 'status'" :class="['link-status-pill', `link-status-pill--${linkValidityType(detail)}`]">
                    <span class="link-status-dot"></span>
                    {{ item.value }}
                  </span>
                  <span v-else>{{ item.value }}</span>
                  <button
                    v-if="item.copyValue"
                    type="button"
                    class="share-copy-button"
                    :title="`复制${item.label}`"
                    @click="copyShareValue(item.copyValue)"
                  >
                    ⧉
                  </button>
                </dd>
              </template>
            </dl>
          </div>
        </article>
      </section>

      <section v-else class="detail-grid">
        <article class="detail-card detail-card--preview">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">预览</div>
              <h3>证据截图 / 页面快照</h3>
            </div>
          </div>
          <div class="preview-stage">
            <img
              v-if="detail.latestSnapshot?.screenshotUrl"
              :src="detail.latestSnapshot.screenshotUrl"
              alt="preview"
              class="preview-stage__image"
            >
            <div v-else class="preview-stage__empty">当前命中没有可用截图</div>
          </div>
          <div class="asset-links">
            <a
              v-for="asset in detail.previewAssets || []"
              :key="asset.url"
              :href="asset.url"
              target="_blank"
              rel="noreferrer"
              class="asset-link"
            >
              {{ asset.label }}
            </a>
            <a
              v-if="detail.canonicalUrl"
              :href="detail.canonicalUrl"
              target="_blank"
              rel="noreferrer"
              class="asset-link"
            >
              打开原始页面
            </a>
          </div>
        </article>

        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">概览</div>
              <h3>{{ currentConfig.infoTitle }}</h3>
            </div>
          </div>
          <dl class="info-grid">
            <template v-for="item in infoItems" :key="item.label">
              <dt>{{ item.label }}</dt>
              <dd>{{ item.value }}</dd>
            </template>
          </dl>
        </article>
      </section>

      <section v-if="!isNetdiskDetail" class="detail-grid detail-grid--bottom">
        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">命中</div>
              <h3>敏感关键词</h3>
            </div>
          </div>
          <div class="tag-list">
            <span v-for="term in detail.matchedTerms || []" :key="`${term.term}-${term.term_type}`" class="keyword-tag">
              {{ term.term }}
            </span>
            <span v-if="!(detail.matchedTerms || []).length" class="muted-text">暂无命中关键词</span>
          </div>
        </article>

        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">风险</div>
              <h3>风险分析</h3>
            </div>
          </div>
          <div class="risk-panel">
            <div class="risk-score">{{ detail.riskAnalysis?.score || 0 }}</div>
            <div class="risk-notes">
              <p v-for="reason in detail.riskAnalysis?.reasons || []" :key="reason">{{ reason }}</p>
              <p v-if="!(detail.riskAnalysis?.reasons || []).length">暂无风险说明</p>
            </div>
          </div>
        </article>
      </section>

      <section class="detail-grid detail-grid--bottom detail-grid--files">
        <article class="detail-card detail-card--files">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">文件</div>
              <h3>文件清单</h3>
            </div>
            <span class="file-tree-count">{{ fileTreeBadgeText }}</span>
          </div>
          <div class="file-tree-toolbar">
            <button type="button" class="file-tree-tool" @click="expandFileTree(2)">▾ 全部展开到第 2 层</button>
            <button type="button" :class="['file-tree-tool', { 'file-tree-tool--active': onlyFiles }]" @click="onlyFiles = !onlyFiles">
              {{ onlyFiles ? '显示目录和文件' : '仅看文件' }}
            </button>
            <el-input
              v-model="fileTreeSearch"
              clearable
              class="file-tree-search"
              placeholder="搜索文件名 / 目录"
            />
          </div>
          <div class="file-tree">
            <template v-if="fileTreeRows.length">
              <div
                v-for="row in fileTreeRows"
                :key="row.key"
                :class="['file-tree-row', { 'file-tree-row--root': row.depth === 0, 'file-tree-row--folder': row.isDir }]"
              >
                <div class="file-tree-row__name" :style="{ '--depth': row.depth }">
                  <span v-if="row.depth > 0" class="file-tree-branch" />
                  <button
                    v-if="row.isDir"
                    type="button"
                    class="file-tree-caret"
                    @click="toggleFileNode(row.key)"
                  >
                    {{ expandedFilePaths.has(row.key) ? '▾' : '▸' }}
                  </button>
                  <span v-else class="file-tree-caret file-tree-caret--leaf">•</span>
                  <span :class="['file-tree-icon', `file-tree-icon--${fileTreeIconClass(row)}`]">
                    {{ fileTreeIconLabel(row) }}
                  </span>
                  <span class="file-tree-name" :title="row.path || row.name">{{ row.name }}</span>
                </div>
                <span :class="['file-tree-meta', { 'file-tree-meta--folder': row.isDir }]">
                  {{ fileTreeMeta(row) }}
                </span>
              </div>
            </template>
            <div v-else class="muted-text">暂无解析到的文件清单</div>
          </div>
        </article>
      </section>

      <section class="detail-grid detail-grid--bottom">
        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">处置</div>
              <h3>处理动作</h3>
            </div>
          </div>
          <div class="review-form">
            <el-input v-model="reviewer" placeholder="处理人" />
            <el-input v-model="note" type="textarea" :rows="3" placeholder="补充说明" />
            <div class="review-actions">
              <el-button type="danger" @click="submitReview('confirmed')">确认命中</el-button>
              <el-button @click="submitReview('false_positive')">标记误报</el-button>
              <el-button plain @click="submitReview('closed')">关闭事件</el-button>
            </div>
          </div>
        </article>

        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">记录</div>
              <h3>处理记录</h3>
            </div>
          </div>
          <div class="review-history">
            <div v-for="item in detail.reviews || []" :key="`${item.created_at}-${item.status}`" class="review-history__item">
              <strong>{{ item.status }}</strong>
              <span>{{ item.reviewer || 'system' }}</span>
              <span>{{ formatDateTime(item.created_at) || '-' }}</span>
              <p>{{ item.note || '无备注' }}</p>
            </div>
            <div v-if="!(detail.reviews || []).length" class="muted-text">暂无处理记录</div>
          </div>
        </article>
      </section>
    </section>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useDocumentExposureApi } from '@/composables/useDocumentExposureApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const route = useRoute()
const router = useRouter()
const api = useDocumentExposureApi()

const detail = reactive({
  matchedTerms: [],
  reviews: [],
  previewAssets: [],
  fileList: [],
  fileListMeta: {},
  latestSnapshot: {},
  riskAnalysis: {},
  rawPayload: {},
})
const reviewer = ref('ui')
const note = ref('')
const fileTreeSearch = ref('')
const onlyFiles = ref(false)
const expandedFilePaths = ref(new Set())

const DETAIL_CONFIG = {
  search_engine: { title: '搜索引擎监测', infoTitle: '来源结果信息' },
  netdisk_aggregator: { title: '网盘监测' },
  document_library: { title: '文库监测', infoTitle: '文档元信息' },
}

const sourceFamily = computed(() => route.params.sourceFamily || 'search_engine')
const hitId = computed(() => route.params.hitId)
const currentConfig = computed(() => DETAIL_CONFIG[sourceFamily.value] || DETAIL_CONFIG.search_engine)
const isNetdiskDetail = computed(() => sourceFamily.value === 'netdisk_aggregator')

const PLATFORM_ICON_META = {
  baidupan_share: { text: '百', className: 'baidu', url: 'https://nd-static.bdstatic.com/m-static/wp-brand/favicon.ico' },
  aliyundrive_share: { text: '阿', className: 'aliyun', url: 'https://img.alicdn.com/imgextra/i1/O1CN01JDQCi21Dc8EfbRwvF_!!6000000000236-73-tps-64-64.ico' },
  quark_share: { text: '夸', className: 'quark', url: 'https://image.quark.cn/s/uae/g/3o/broccoli/resource/202602/f6439020-13b4-11f1-9342-3944993de2f6.png' },
  tianyi_share: { text: '天', className: 'tianyi' },
  pan123_share: { text: '123', className: 'pan123' },
  onedrive_share: { text: '1D', className: 'onedrive' },
  xunlei_share: { text: '迅', className: 'xunlei' },
  uc_share: { text: 'UC', className: 'uc', url: 'https://drive.uc.cn/favicon.ico' },
  mobile_share: { text: '移', className: 'mobile' },
  pan115_share: { text: '115', className: 'pan115', url: 'https://115.com/favicon.ico' },
  pikpak_share: { text: 'PK', className: 'pikpak', url: 'https://mypikpak.com/favicon.ico' },
}

const platformIconMeta = computed(() => {
  const fallback = String(detail.platformLabel || detail.platform || '-').slice(0, 2).toUpperCase()
  return PLATFORM_ICON_META[detail.platform] || { text: fallback, className: 'generic' }
})
const platformIconUrl = computed(() => platformIconMeta.value.url || '')
const platformIconClass = computed(() => platformIconMeta.value.className || 'generic')
const platformIconText = computed(() => platformIconMeta.value.text || '-')

const shareTypeText = computed(() => {
  const value = detail.shareMeta?.shareType || detail.shareMeta?.share_type || detail.shareType
  if (value === 'password_share') return '口令分享'
  if (value === 'public_share') return '公开分享'
  return value || '-'
})

const sharePreviewItems = computed(() => [
  { label: '监测对象', value: detail.watchlistName || '-' },
  { label: '所属机构', value: detail.organizationName || '-' },
  { label: '来源平台', value: detail.platformLabel || '-', kind: 'platform' },
  { label: '发现来源', value: detail.discoverySourceLabel || '-' },
  { label: '分享类型', value: shareTypeText.value },
  { label: '分享链接', value: detail.canonicalUrl || '-', kind: 'link', copyValue: detail.canonicalUrl || '' },
  { label: '提取码/口令', value: detail.shareMeta?.shareCode || '-', copyValue: detail.shareMeta?.shareCode || '' },
  { label: '发现时间', value: formatDateTime(detail.rawPayload?.source_datetime || detail.lastSeenAt) || '-' },
  { label: '链接状态', value: linkValidityLabel(detail), kind: 'status' },
  { label: '命中关键词', kind: 'keywords' },
])

const infoItems = computed(() => {
  const base = [
    { label: '监测对象', value: detail.watchlistName || '-' },
    { label: '所属机构', value: detail.organizationName || '-' },
    { label: '来源平台', value: detail.platformLabel || '-' },
    { label: '发现来源', value: detail.discoverySourceLabel || '-' },
    { label: '访问状态', value: detail.accessStateLabel || detail.accessState || '-' },
    { label: '最近发现', value: formatDateTime(detail.lastSeenAt) || '-' },
  ]

  if (sourceFamily.value === 'document_library') {
    base.splice(4, 0, { label: '主文件类型', value: detail.documentMeta?.primaryFileType || '-' })
  }

  if (sourceFamily.value === 'search_engine') {
    base.splice(4, 0, { label: '检索关键词', value: detail.sourceResult?.query || '-' })
  }

  return base
})

const fileTreeRoots = computed(() => buildFileTree(detail.fileList || []))

const fileTreeBadgeText = computed(() => {
  const qualityLabels = {
    share_listing: '真实目录',
    aggregator_preview: '摘要提取',
    matched_preview: '命中证据',
    title_fallback: '标题推断',
    file_names: '文件清单',
    none: '未解析',
  }
  const label = qualityLabels[detail.fileListMeta?.quality] || detail.fileListMeta?.label || '文件清单'
  return `${label} · ${detail.fileList?.length || 0} 项`
})

const fileTreeRows = computed(() => {
  const query = fileTreeSearch.value.trim().toLowerCase()
  const rows = []

  function matches(node) {
    if (!query) return true
    return `${node.name} ${node.path}`.toLowerCase().includes(query)
  }

  function childMatches(node) {
    return node.children.some((child) => matches(child) || childMatches(child))
  }

  function visit(node) {
    const includeByMode = !onlyFiles.value || !node.isDir || childMatches(node)
    const includeBySearch = !query || matches(node) || childMatches(node)
    if (!includeByMode || !includeBySearch) return
    if (!onlyFiles.value || !node.isDir || childMatches(node)) {
      rows.push(node)
    }
    const shouldOpen = query || expandedFilePaths.value.has(node.key)
    if (node.isDir && shouldOpen) {
      node.children.forEach(visit)
    }
  }

  fileTreeRoots.value.forEach(visit)
  return rows
})

watch(
  () => detail.fileList,
  () => expandFileTree(2),
  { deep: true },
)

function normalizeTreePath(value) {
  return String(value || '').replace(/\\/g, '/').replace(/\/+/g, '/').replace(/\/$/, '')
}

function fileNameFromPath(path) {
  const normalized = normalizeTreePath(path)
  return normalized.split('/').filter(Boolean).pop() || normalized || '-'
}

function parentTreePath(path) {
  const normalized = normalizeTreePath(path)
  const index = normalized.lastIndexOf('/')
  return index > 0 ? normalized.slice(0, index) : ''
}

function isTechnicalShareRoot(path) {
  return /^\/?sharelink\d+(?:-|$)/i.test(normalizeTreePath(path))
}

function buildFileTree(files) {
  const nodes = new Map()
  ;(files || []).forEach((file, index) => {
    const path = normalizeTreePath(file.path || file.name || `file-${index}`)
    const name = String(file.name || fileNameFromPath(path) || '-')
    const key = path || `${name}-${index}`
    nodes.set(key, {
      key,
      name,
      path,
      size: file.size || '',
      type: file.type || '',
      isDir: Boolean(file.isDir || file.is_dir || file.type === 'folder' || file.type === 'dir'),
      children: [],
      depth: 0,
      childCount: 0,
    })
  })

  Array.from(nodes.values()).forEach((node) => {
    let parentPath = parentTreePath(node.path)
    while (parentPath && !nodes.has(parentPath)) {
      if (isTechnicalShareRoot(parentPath)) break
      nodes.set(parentPath, {
        key: parentPath,
        name: fileNameFromPath(parentPath),
        path: parentPath,
        size: '',
        type: 'folder',
        isDir: true,
        children: [],
        depth: 0,
        childCount: 0,
      })
      parentPath = parentTreePath(parentPath)
    }
  })

  const roots = []
  nodes.forEach((node) => {
    const parent = nodes.get(parentTreePath(node.path))
    if (parent && parent.key !== node.key) {
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  })

  nodes.forEach((node) => {
    if (node.children.length) {
      node.isDir = true
      node.type = 'folder'
    }
  })

  function sortAndAnnotate(node, depth = 0) {
    node.depth = depth
    let descendants = 0
    node.children.forEach((child) => {
      descendants += 1 + sortAndAnnotate(child, depth + 1)
    })
    node.childCount = descendants
    return descendants
  }

  roots.forEach((node) => sortAndAnnotate(node))
  return roots
}

function flattenFileTree(nodes) {
  const rows = []
  function visit(node) {
    rows.push(node)
    node.children.forEach(visit)
  }
  nodes.forEach(visit)
  return rows
}

function expandFileTree(depth = 2) {
  const next = new Set()
  flattenFileTree(fileTreeRoots.value).forEach((node) => {
    if (node.isDir && node.depth <= depth) {
      next.add(node.key)
    }
  })
  expandedFilePaths.value = next
}

function toggleFileNode(key) {
  const next = new Set(expandedFilePaths.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedFilePaths.value = next
}

function fileTreeMeta(row) {
  if (row.isDir) {
    if (row.depth === 0 && fileTreeRoots.value.length === 1 && detail.fileList?.length) {
      return `${detail.fileList.length} 项`
    }
    return row.childCount ? `${row.childCount} 项` : '目录'
  }
  return row.size || row.type || '-'
}

function fileTreeIconClass(row) {
  if (row.isDir) return 'folder'
  const type = String(row.type || fileNameFromPath(row.name).split('.').pop() || '').toLowerCase()
  if (['pdf'].includes(type)) return 'pdf'
  if (['doc', 'docx'].includes(type)) return 'docx'
  if (['xls', 'xlsx', 'csv'].includes(type)) return 'sheet'
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'].includes(type)) return 'image'
  if (['mp4', 'mov', 'm4v', 'avi', 'mkv'].includes(type)) return 'video'
  if (['zip', 'rar', '7z'].includes(type)) return 'archive'
  return 'file'
}

function fileTreeIconLabel(row) {
  if (row.isDir) return '📁'
  return {
    pdf: 'PDF',
    docx: 'DOC',
    sheet: 'XLS',
    image: 'IMG',
    video: 'VID',
    archive: 'ZIP',
  }[fileTreeIconClass(row)] || 'FILE'
}

function linkValidityType(row) {
  const state = row?.accessState || ''
  if (['public', 'login_required'].includes(state)) return 'valid'
  if (['removed', 'forbidden'].includes(state)) return 'invalid'
  if (state === 'captcha') return 'gated'
  return 'pending'
}

function linkValidityLabel(row) {
  return {
    valid: '有效',
    invalid: '已失效',
    gated: '需验证',
    pending: '待校验',
  }[linkValidityType(row)]
}

async function copyShareValue(value) {
  const text = String(value || '').trim()
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

async function loadDetail() {
  if (!hitId.value) return
  Object.assign(detail, {
    matchedTerms: [],
    reviews: [],
    previewAssets: [],
    fileList: [],
    fileListMeta: {},
    latestSnapshot: {},
    riskAnalysis: {},
    rawPayload: {},
  })
  try {
    const payload = await api.loadHitDetail(hitId.value)
    Object.assign(detail, payload || {})
  } catch (error) {
    ElMessage.error(error.message || '加载文件监测详情失败')
  }
}

async function submitReview(status) {
  try {
    await api.reviewHit(hitId.value, {
      status,
      reviewer: reviewer.value || 'ui',
      note: note.value,
    })
    note.value = ''
    await loadDetail()
    ElMessage.success('处理状态已更新')
  } catch (error) {
    ElMessage.error(error.message || '更新处理状态失败')
  }
}

function goBack() {
  router.push({
    name:
      sourceFamily.value === 'netdisk_aggregator'
        ? 'DocumentExposureNetdisk'
        : sourceFamily.value === 'document_library'
          ? 'DocumentExposureDocumentLibrary'
          : 'DocumentExposureSearchEngine',
  })
}

watch(hitId, loadDetail, { immediate: true })
</script>

<style scoped lang="scss">
.detail-shell {
  display: grid;
  gap: 20px;
  padding: 24px;
  border-radius: 28px;
  background: #ffffff;
  color: var(--ti-text-primary);
  border: 1px solid rgba(116, 142, 184, 0.14);
  box-shadow: 0 24px 50px rgba(32, 57, 96, 0.08);
}

.detail-shell__header,
.detail-card__header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.back-button {
  padding-left: 0;
  color: var(--ti-primary);
}

.detail-shell__eyebrow,
.detail-card__eyebrow {
  color: var(--ti-primary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.detail-shell__title {
  margin: 8px 0;
  font-size: 28px;
}

.detail-shell__meta,
.detail-shell__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: var(--ti-text-muted);
}

.detail-grid {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 16px;
}

.detail-grid--bottom {
  grid-template-columns: 1fr 1fr;
}

.detail-grid--files {
  grid-template-columns: 1fr;
}

.detail-card {
  padding: 18px;
  border: 1px solid rgba(116, 142, 184, 0.14);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 14px 30px rgba(32, 57, 96, 0.06);
}

.detail-card h3 {
  margin: 6px 0 0;
  font-size: 18px;
}

.preview-stage {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 360px;
  margin-top: 16px;
  border-radius: 18px;
  background: rgba(244, 248, 255, 0.9);
  overflow: hidden;
}

.preview-stage__image {
  width: 100%;
  object-fit: contain;
}

.preview-stage__empty,
.muted-text {
  color: var(--ti-text-muted);
}

.preview-stage--share {
  align-items: flex-start;
  justify-content: flex-start;
  min-height: 0;
  padding: 16px 18px;
}

.share-preview-list {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  gap: 12px 18px;
  width: 100%;
  margin: 0;
}

.share-preview-list--merged {
  grid-template-columns: 112px minmax(0, 1fr) 112px minmax(0, 1fr);
}

.share-preview-list dt {
  color: var(--ti-text-secondary);
}

.share-preview-list dd {
  display: flex;
  align-items: center;
  min-height: 28px;
  min-width: 0;
  gap: 8px;
  margin: 0;
  color: var(--ti-text-primary);
  font-weight: 600;
}

.share-platform-value {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
}

.share-platform-logo,
.share-platform-icon {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  border-radius: 6px;
}

.share-platform-logo {
  object-fit: contain;
}

.share-platform-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: #3178ff;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}

.share-platform-icon--aliyun {
  background: #ff6a00;
}

.share-platform-icon--quark {
  background: #00a3ff;
}

.share-platform-icon--baidu {
  background: #2458ff;
}

.share-platform-icon--generic {
  background: #64748b;
}

.share-keyword-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.share-preview-link {
  min-width: 0;
  color: var(--ti-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.share-copy-button {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid rgba(116, 142, 184, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.92);
  color: var(--ti-text-secondary);
  cursor: pointer;
}

.link-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(34, 197, 94, 0.12);
  color: #15803d;
}

.link-status-pill--invalid {
  background: rgba(239, 68, 68, 0.12);
  color: #b91c1c;
}

.link-status-pill--gated,
.link-status-pill--pending {
  background: rgba(245, 158, 11, 0.14);
  color: #a16207;
}

.link-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.asset-links,
.tag-list,
.review-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.asset-links {
  margin-top: 16px;
}

.asset-link,
.keyword-tag,
.neutral-tag,
.severity-tag {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 999px;
}

.asset-link,
.keyword-tag,
.neutral-tag {
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid rgba(116, 142, 184, 0.18);
  color: var(--ti-text-primary);
}

.severity-tag {
  font-weight: 700;
}

.severity-tag--high {
  background: rgba(229, 85, 87, 0.2);
  color: #ff9b9d;
}

.severity-tag--medium {
  background: rgba(255, 173, 76, 0.2);
  color: #ffcb7d;
}

.severity-tag--low {
  background: rgba(70, 192, 138, 0.2);
  color: #7ce2b0;
}

.info-grid {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 12px 16px;
  margin-top: 18px;
}

.info-grid dt {
  color: var(--ti-text-secondary);
}

.info-grid dd {
  margin: 0;
  color: var(--ti-text-primary);
  word-break: break-all;
}

.risk-panel {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 16px;
  align-items: center;
  margin-top: 16px;
}

.risk-score {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(38, 113, 220, 0.18), rgba(38, 113, 220, 0.04));
  border: 1px solid rgba(97, 145, 222, 0.18);
  font-size: 34px;
  font-weight: 700;
}

.risk-notes {
  display: grid;
  gap: 10px;
}

.review-history {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.review-history__item {
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(247, 250, 255, 0.96);
  border: 1px solid rgba(116, 142, 184, 0.14);
}

.file-tree-count {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(59, 130, 246, 0.22);
  background: rgba(239, 246, 255, 0.94);
  color: var(--ti-primary);
  font-size: 13px;
  font-weight: 700;
}

.file-tree-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 46px;
  margin-top: 16px;
  padding: 8px 14px;
  border: 1px solid rgba(116, 142, 184, 0.14);
  border-radius: 12px;
  background: rgba(248, 251, 255, 0.96);
}

.file-tree-tool {
  appearance: none;
  border: 0;
  background: transparent;
  color: #23405f;
  font-size: 14px;
  cursor: pointer;
  padding: 4px 2px;
}

.file-tree-tool--active {
  color: var(--ti-primary);
  font-weight: 700;
}

.file-tree-search {
  width: 240px;
  margin-left: auto;
}

.file-tree {
  position: relative;
  min-height: 280px;
  max-height: 620px;
  overflow: auto;
  margin-top: 14px;
  padding: 14px 12px 18px;
  border: 1px solid rgba(116, 142, 184, 0.14);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.98);
}

.file-tree-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  min-height: 32px;
  padding-right: 24px;
  border-radius: 8px;
}

.file-tree-row:nth-child(odd) {
  background: rgba(252, 253, 255, 0.92);
}

.file-tree-row--root {
  background: rgba(244, 248, 255, 0.96);
  font-weight: 700;
}

.file-tree-row__name {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding-left: calc(12px + var(--depth) * 28px);
}

.file-tree-row__name::before {
  content: "";
  position: absolute;
  left: calc(25px + (var(--depth) - 1) * 28px);
  top: -8px;
  bottom: -8px;
  display: none;
  border-left: 1px solid rgba(116, 142, 184, 0.24);
}

.file-tree-row__name:has(.file-tree-branch)::before {
  display: block;
}

.file-tree-branch {
  position: absolute;
  left: calc(25px + (var(--depth) - 1) * 28px);
  width: 18px;
  border-top: 1px solid rgba(116, 142, 184, 0.24);
}

.file-tree-caret {
  position: relative;
  z-index: 1;
  flex: 0 0 16px;
  width: 16px;
  height: 20px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #51677f;
  font-size: 12px;
  line-height: 20px;
  cursor: pointer;
}

.file-tree-caret--leaf {
  cursor: default;
  color: #8da0b8;
}

.file-tree-icon {
  position: relative;
  z-index: 1;
  flex: 0 0 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  color: #fff;
  font-size: 8px;
  font-weight: 800;
  letter-spacing: 0;
}

.file-tree-icon--folder {
  border: 1px solid #f2c763;
  background: #fff4d6;
  color: #c78200;
  font-size: 12px;
}

.file-tree-icon--pdf {
  background: #ef4444;
}

.file-tree-icon--docx {
  background: #3b82f6;
}

.file-tree-icon--sheet {
  background: #20a868;
}

.file-tree-icon--image {
  background: #10b981;
}

.file-tree-icon--video {
  background: #8b5cf6;
}

.file-tree-icon--archive {
  background: #f59e0b;
}

.file-tree-icon--file {
  background: #64748b;
}

.file-tree-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ti-text-primary);
}

.file-tree-meta {
  margin-left: 16px;
  color: var(--ti-text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.file-tree-meta--folder {
  min-width: 46px;
  padding: 2px 10px;
  border: 1px solid rgba(116, 142, 184, 0.18);
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.9);
  text-align: center;
}

.review-form {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

:deep(.el-button--default) {
  background: rgba(255, 255, 255, 0.98);
  border-color: rgba(116, 142, 184, 0.18);
  color: var(--ti-text-primary);
}

:deep(.el-input__wrapper),
:deep(.el-textarea__inner) {
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid rgba(116, 142, 184, 0.16);
  color: var(--ti-text-primary);
}

@media (max-width: 1080px) {
  .detail-grid,
  .detail-grid--bottom,
  .risk-panel,
  .detail-shell__header,
  .detail-card__header {
    grid-template-columns: 1fr;
    flex-direction: column;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }

  .share-preview-list {
    grid-template-columns: 1fr;
  }

  .share-preview-list dd {
    flex-wrap: wrap;
  }
}
</style>
