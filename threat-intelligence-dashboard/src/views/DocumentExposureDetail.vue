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
          <span :class="['severity-tag', `severity-tag--${detail.severity || 'low'}`]">{{ detail.riskScore || 0 }} 分</span>
          <span class="neutral-tag">{{ detail.reviewStatus || 'new' }}</span>
        </div>
      </header>

      <section class="detail-grid">
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

      <section class="detail-grid detail-grid--bottom">
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

      <section class="detail-grid detail-grid--bottom">
        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">文件</div>
              <h3>文件清单</h3>
            </div>
          </div>
          <div class="file-list">
            <div v-for="file in detail.fileList || []" :key="`${file.name}-${file.path}`" class="file-item">
              <strong>{{ file.name }}</strong>
              <span>{{ file.type || '-' }}</span>
            </div>
            <div v-if="!(detail.fileList || []).length" class="muted-text">暂无解析到的文件清单</div>
          </div>
        </article>

        <article class="detail-card">
          <div class="detail-card__header">
            <div>
              <div class="detail-card__eyebrow">文本</div>
              <h3>页面预览文本</h3>
            </div>
          </div>
          <pre class="preview-text">{{ detail.latestSnapshot?.previewText || detail.latestSnapshot?.ocrText || detail.rawPayload?.preview_text || '暂无文本预览' }}</pre>
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
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useDocumentExposureApi } from '@/composables/useDocumentExposureApi'

const route = useRoute()
const router = useRouter()
const api = useDocumentExposureApi()

const detail = reactive({
  matchedTerms: [],
  reviews: [],
  previewAssets: [],
  fileList: [],
  latestSnapshot: {},
  riskAnalysis: {},
  rawPayload: {},
})
const reviewer = ref('ui')
const note = ref('')

const DETAIL_CONFIG = {
  search_engine: { title: '搜索引擎监测', infoTitle: '来源结果信息' },
  netdisk_aggregator: { title: '网盘监测', infoTitle: '分享链接信息' },
  document_library: { title: '文库监测', infoTitle: '文档元信息' },
}

const sourceFamily = computed(() => route.params.sourceFamily || 'search_engine')
const hitId = computed(() => route.params.hitId)
const currentConfig = computed(() => DETAIL_CONFIG[sourceFamily.value] || DETAIL_CONFIG.search_engine)

const infoItems = computed(() => {
  const base = [
    { label: '监测对象', value: detail.watchlistName || '-' },
    { label: '所属机构', value: detail.organizationName || '-' },
    { label: '来源平台', value: detail.platformLabel || '-' },
    { label: '发现来源', value: detail.discoverySourceLabel || '-' },
    { label: '访问状态', value: detail.accessStateLabel || detail.accessState || '-' },
    { label: '最近发现', value: formatDateTime(detail.lastSeenAt) || '-' },
  ]

  if (sourceFamily.value === 'netdisk_aggregator') {
    base.splice(4, 0, { label: '提取码 / 口令', value: detail.shareMeta?.shareCode || '-' })
  }

  if (sourceFamily.value === 'document_library') {
    base.splice(4, 0, { label: '主文件类型', value: detail.documentMeta?.primaryFileType || '-' })
  }

  if (sourceFamily.value === 'search_engine') {
    base.splice(4, 0, { label: '检索关键词', value: detail.sourceResult?.query || '-' })
  }

  return base
})

function formatDateTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 16)
}

async function loadDetail() {
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
  grid-template-columns: 1.3fr 1fr;
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

.file-list,
.review-history {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.file-item,
.review-history__item {
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(247, 250, 255, 0.96);
  border: 1px solid rgba(116, 142, 184, 0.14);
}

.file-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.preview-text {
  min-height: 220px;
  margin: 16px 0 0;
  padding: 16px;
  border-radius: 16px;
  background: rgba(247, 250, 255, 0.96);
  border: 1px solid rgba(116, 142, 184, 0.14);
  color: var(--ti-text-primary);
  white-space: pre-wrap;
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
}
</style>
