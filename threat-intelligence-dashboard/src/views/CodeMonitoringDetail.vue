<template>
  <div class="monitor-detail ti-page">
    <section class="detail-shell">
      <header class="detail-shell__header">
        <div>
          <el-button text class="back-button" @click="router.push('/document-exposure/code-monitoring')">返回代码监测</el-button>
          <div class="detail-shell__eyebrow">Code Monitoring</div>
          <h2 class="detail-shell__title">{{ detail.repositoryFullName || detail.repositoryName || '-' }}</h2>
          <div class="detail-shell__meta">
            <span>{{ detail.platformLabel || '-' }}</span>
            <span>{{ detail.filePath || '-' }}</span>
            <span>{{ formatDateTime(detail.lastSeenAt) || '-' }}</span>
          </div>
        </div>
        <div class="detail-shell__tags">
          <span :class="['layer-tag', `layer-tag--${detail.resultLayer || 'sensitive'}`]">{{ detail.resultLayerLabel || (detail.resultLayer === 'clue' ? '线索命中' : '敏感命中') }}</span>
          <span :class="['severity-tag', `severity-tag--${detail.severity || 'low'}`]">{{ formatSeverity(detail.severity) }}</span>
          <span class="neutral-tag">{{ detail.sensitiveLabel || detail.sensitiveType || '-' }}</span>
        </div>
      </header>

      <section class="detail-grid">
        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">基础</div>
              <h3>仓库与文件信息</h3>
            </div>
          </div>
          <dl class="info-grid">
            <template v-for="item in infoItems" :key="item.label">
              <dt>{{ item.label }}</dt>
              <dd v-if="item.highlight" v-html="item.value" />
              <dd v-else>{{ item.value }}</dd>
            </template>
          </dl>
          <div class="asset-links">
            <a
              v-for="item in detail.sourceLinks || []"
              :key="item.label"
              :href="item.url"
              target="_blank"
              rel="noreferrer"
              class="asset-link"
            >
              {{ item.label }}
            </a>
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
          </div>
        </article>

        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">证据</div>
              <h3>页面快照</h3>
            </div>
          </div>
          <div class="preview-stage">
            <a
              v-if="detail.latestSnapshot?.htmlUrl"
              :href="detail.latestSnapshot.htmlUrl"
              target="_blank"
              rel="noreferrer"
              class="preview-stage__link"
            >
              打开页面快照
            </a>
            <div v-else class="preview-stage__empty">当前命中没有可用页面快照</div>
          </div>
        </article>
      </section>

      <section class="detail-grid detail-grid--bottom">
        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">预览</div>
              <h3>掩码后的代码片段</h3>
            </div>
          </div>
          <pre class="code-preview" v-html="highlightedCodePreview" />
        </article>

        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">发现项</div>
              <h3>敏感信息检测</h3>
            </div>
          </div>
          <div class="finding-list">
            <div v-for="finding in detail.findings || []" :key="`${finding.ruleKey}-${finding.start}-${finding.end}`" class="finding-item">
              <strong>{{ finding.label }}</strong>
              <span v-html="highlightFindingExcerpt(finding)" />
            </div>
            <div v-if="detail.resultLayer === 'clue'" class="muted-text">当前为线索命中，未识别到明确敏感凭据。</div>
            <div v-else-if="!(detail.findings || []).length" class="muted-text">暂无结构化发现项</div>
          </div>
        </article>
      </section>

      <section class="detail-card">
        <div class="detail-card__header">
          <div>
            <div class="detail-card__eyebrow">检索</div>
            <h3>关键词命中位置 / 上下文</h3>
          </div>
        </div>
        <p class="panel-note">检索命中词用于定位目标代码，敏感规则用于识别当前展示的实际风险片段。</p>
        <div class="context-list">
          <article v-for="item in matchedTermContexts" :key="`${item.kind}-${item.label}-${item.lineStart}-${item.lineEnd}-${item.text}`" class="context-item">
            <div class="context-item__meta">
              <strong>{{ item.label }}</strong>
              <span v-if="item.lineStart">{{ formatContextRange(item) }}</span>
            </div>
            <pre v-if="item.kind === 'code'" class="context-item__code" v-html="highlightText(item.text, detail.matchedTerm)" />
            <p v-else class="context-item__text" v-html="highlightText(item.text, detail.matchedTerm)" />
          </article>
          <div v-if="!matchedTermContexts.length" class="muted-text">当前记录未提取到检索词上下文。</div>
        </div>
      </section>

      <section class="detail-grid detail-grid--bottom">
        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">风险</div>
              <h3>风险分析</h3>
            </div>
          </div>
          <div class="risk-panel">
            <div :class="['risk-level-badge', `risk-level-badge--${detail.riskAnalysis?.severity || detail.severity || 'low'}`]">
              {{ formatSeverity(detail.riskAnalysis?.severity || detail.severity) }}
            </div>
            <div class="risk-notes">
              <p v-for="reason in detail.riskAnalysis?.reasons || []" :key="reason">{{ reason }}</p>
              <p v-if="!(detail.riskAnalysis?.reasons || []).length">暂无风险说明</p>
            </div>
          </div>
        </article>

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
              <el-button type="danger" @click="submitReview('confirmed')">确认泄露</el-button>
              <el-button @click="submitReview('false_positive')">标记误报</el-button>
              <el-button plain @click="submitReview('closed')">关闭事件</el-button>
            </div>
          </div>
        </article>
      </section>

      <section class="detail-card">
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
      </section>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useCodeMonitoringApi } from '@/composables/useCodeMonitoringApi'
import { highlightKeywordsHtml, maskSensitivePreview } from '@/composables/highlightText'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const route = useRoute()
const router = useRouter()
const api = useCodeMonitoringApi()

const detail = reactive({
  latestSnapshot: {},
  findings: [],
  matchedTermContexts: [],
  reviews: [],
  previewAssets: [],
  sourceLinks: [],
  riskAnalysis: {},
})
const reviewer = ref('ui')
const note = ref('')

const infoItems = computed(() => [
  { label: '监测对象', value: detail.watchlistName || '-' },
  { label: '所属机构', value: detail.organizationName || '-' },
  { label: '来源平台', value: detail.platformLabel || '-' },
  { label: '仓库地址', value: detail.repositoryUrl || '-' },
  { label: '文件路径', value: detail.filePath || '-' },
  { label: '分支', value: detail.branch || '-' },
  { label: '检索命中词', value: highlightText(detail.matchedTerm || '-', detail.matchedTerm), highlight: true },
  { label: '敏感类型', value: detail.sensitiveLabel || detail.sensitiveType || '-' },
])

const matchedTermContexts = computed(() => (Array.isArray(detail.matchedTermContexts) ? detail.matchedTermContexts : []))

const previewHighlightTerms = computed(() => {
  const keywords = [detail.matchedTerm]
  for (const finding of detail.findings || []) {
    const value = String(finding?.value || '').trim()
    const excerpt = String(finding?.excerpt || '').trim()
    if (value) {
      keywords.push(value)
      keywords.push(maskSensitivePreview(value))
    }
    if (excerpt && excerpt !== value) {
      keywords.push(excerpt)
      keywords.push(maskSensitivePreview(excerpt))
    }
  }
  return keywords
})

const highlightedCodePreview = computed(() => highlightText(detail.codePreview || '暂无代码预览', previewHighlightTerms.value))

function highlightText(text, keywords) {
  return highlightKeywordsHtml(text, keywords)
}

function highlightFindingExcerpt(finding) {
  const excerpt = String(finding?.excerpt || '-')
  return highlightText(excerpt, [
    detail.matchedTerm,
    finding?.value,
    finding?.excerpt,
    maskSensitivePreview(finding?.value),
    maskSensitivePreview(finding?.excerpt),
  ])
}

function formatContextRange(item) {
  const start = Number(item?.lineStart || 0)
  const end = Number(item?.lineEnd || 0)
  if (!start) return ''
  if (!end || end === start) return `第 ${start} 行`
  return `第 ${start}-${end} 行`
}

function formatSeverity(value) {
  if (value === 'high') return '高危'
  if (value === 'medium') return '中危'
  if (value === 'low') return '低危'
  return value || '-'
}

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

async function loadDetail() {
  try {
    const payload = await api.loadHitDetail(route.params.hitId)
    Object.assign(detail, payload || {})
  } catch (error) {
    ElMessage.error(error.message || '加载代码监测详情失败')
  }
}

async function submitReview(status) {
  try {
    await api.reviewHit(route.params.hitId, {
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

onMounted(loadDetail)
</script>

<style scoped lang="scss">
.detail-shell {
  display: grid;
  gap: 20px;
  padding: 24px;
  border-radius: 28px;
  background:
    radial-gradient(circle at top right, rgba(45, 93, 255, 0.14), transparent 28%),
    linear-gradient(180deg, #fbfdff 0%, #f3f8ff 100%);
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
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.detail-grid--bottom {
  grid-template-columns: 1fr 1fr;
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

.asset-links,
.review-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.asset-links {
  margin-top: 16px;
}

.asset-link,
.layer-tag,
.neutral-tag,
.severity-tag {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 999px;
}

.asset-link,
.layer-tag,
.neutral-tag {
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid rgba(116, 142, 184, 0.18);
  color: var(--ti-text-primary);
}

.layer-tag--sensitive {
  background: rgba(229, 85, 87, 0.14);
  color: #d9363e;
}

.layer-tag--clue {
  background: rgba(38, 113, 220, 0.14);
  color: #1c6dd0;
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
  grid-template-columns: 120px 1fr;
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

.preview-stage {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 320px;
  margin-top: 16px;
  border-radius: 18px;
  background: rgba(244, 248, 255, 0.9);
  overflow: hidden;
}

.preview-stage__link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 180px;
  min-height: 44px;
  padding: 0 18px;
  border-radius: 999px;
  background: rgba(38, 113, 220, 0.1);
  border: 1px solid rgba(38, 113, 220, 0.18);
  color: var(--ti-primary);
  font-weight: 700;
}

.code-preview {
  min-height: 260px;
  max-height: 520px;
  margin: 16px 0 0;
  padding: 16px;
  border-radius: 16px;
  background: rgba(247, 250, 255, 0.96);
  border: 1px solid rgba(116, 142, 184, 0.14);
  color: var(--ti-text-primary);
  white-space: pre-wrap;
  overflow-y: auto;
  overflow-x: hidden;
}

.panel-note {
  margin: 16px 0 0;
  color: var(--ti-text-secondary);
}

:deep(.keyword-highlight) {
  color: #d9363e;
  font-weight: 700;
}

.context-list,
.finding-list,
.review-history {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.context-item,
.finding-item,
.review-history__item {
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(247, 250, 255, 0.96);
  border: 1px solid rgba(116, 142, 184, 0.14);
}

.context-item__meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 10px;
  color: var(--ti-text-secondary);
}

.context-item__code,
.context-item__text {
  margin: 10px 0 0;
  color: var(--ti-text-primary);
}

.context-item__code {
  white-space: pre-wrap;
  word-break: break-word;
}

.context-item__text {
  word-break: break-all;
}

.risk-panel {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 16px;
  align-items: center;
  margin-top: 16px;
}

.risk-level-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 120px;
  min-height: 120px;
  padding: 12px;
  border-radius: 28px;
  border: 1px solid rgba(97, 145, 222, 0.18);
  background: rgba(247, 250, 255, 0.96);
  font-size: 30px;
  font-weight: 700;
  text-align: center;
}

.risk-level-badge--high {
  color: #d9363e;
  background: rgba(229, 85, 87, 0.14);
}

.risk-level-badge--medium {
  color: #d48806;
  background: rgba(255, 173, 76, 0.16);
}

.risk-level-badge--low {
  color: #389e0d;
  background: rgba(70, 192, 138, 0.14);
}

.risk-notes {
  display: grid;
  gap: 10px;
}

.review-form {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.muted-text {
  color: var(--ti-text-muted);
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
}
</style>
