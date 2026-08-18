<template>
  <div class="event-detail-page ti-page">
    <div class="detail-actions">
      <el-button type="primary" plain @click="goBackToList">返回列表</el-button>
    </div>

    <section class="ti-panel ti-reveal-up">
      <div :class="['detail-hero', { 'detail-hero--title-only': isVulnerability }]" v-if="eventDetail">
        <div>
          <span class="ti-kicker">事件详情页</span>
          <h2>{{ eventDetail.title }}</h2>
        </div>
        <div v-if="!isVulnerability" class="detail-hero__meta">
          <div>
            <span>事件类型</span>
            <strong>{{ eventDetail.category || '未知' }}</strong>
          </div>
          <div>
            <span>来源</span>
            <strong>{{ eventDetail.source || '未知' }}</strong>
          </div>
          <div>
            <span>披露时间</span>
            <strong>{{ eventDetail.disclosure_time || '未知' }}</strong>
          </div>
          <div>
            <span>{{ primarySubjectLabel }}</span>
            <strong>{{ primarySubjectValue }}</strong>
          </div>
        </div>
      </div>
      <div v-else-if="loading" class="detail-loading">
        <p>正在加载事件详情...</p>
      </div>
      <div v-else class="empty-state">
        <p>未找到该事件的详细信息。</p>
        <p v-if="error" class="empty-state__error">{{ error.message }}</p>
      </div>
    </section>

    <section v-if="eventDetail" class="detail-grid">
      <div v-if="refreshing" class="ti-card ti-reveal-up">
        <div class="ti-card-body loading-inline">
          <p>正在补充详细内容，请稍候...</p>
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">关键信息</div>
        </div>
        <div class="ti-card-body key-grid">
          <div>
            <span>标题</span>
            <strong>{{ eventDetail.title || '未知' }}</strong>
          </div>
          <div v-if="eventDetail.identifier || eventDetail.id">
            <span>识别号</span>
            <strong class="detail-identifier">{{ eventDetail.identifier || eventDetail.id }}</strong>
          </div>
          <div v-if="eventDetail.original_title && eventDetail.original_title !== eventDetail.title">
            <span>原始标题</span>
            <strong>{{ eventDetail.original_title }}</strong>
          </div>
          <div v-if="isVulnerability">
            <span>CVE</span>
            <strong>{{ eventDetail.cve_id || '未知' }}</strong>
          </div>
          <div>
            <span>披露时间</span>
            <strong>{{ eventDetail.disclosure_time || '未知' }}</strong>
          </div>
          <div>
            <span>{{ primarySubjectLabel }}</span>
            <strong>{{ primarySubjectValue }}</strong>
          </div>
          <div v-if="isVulnerability">
            <span>{{ secondarySubjectLabel }}</span>
            <strong>{{ secondarySubjectValue }}</strong>
          </div>
          <div>
            <span>{{ isVulnerability ? '漏洞类型' : '事件类型' }}</span>
            <strong>{{ eventDetail.category || '未知' }}</strong>
          </div>
          <div>
            <span>来源</span>
            <strong>{{ eventDetail.source || '未知' }}</strong>
          </div>
          <div v-if="!isVulnerability">
            <span>受害行业</span>
            <strong>{{ eventDetail.industry || '未知' }}</strong>
          </div>
          <div v-if="isVulnerability">
            <span>CVSS</span>
            <strong>{{ eventDetail.cvss ?? '未知' }}</strong>
          </div>
          <div v-if="isVulnerability">
            <span>利用状态</span>
            <strong>{{ eventDetail.is_exploited ? '已被利用' : '待观察' }}</strong>
          </div>
          <div v-if="isVulnerability">
            <span>补丁状态</span>
            <strong>{{ eventDetail.patch_available ? '已有补丁' : '待补丁 / 临时缓解' }}</strong>
          </div>
        </div>
      </div>

      <div v-if="monitoringMatches.length || hasSampleEvidence || sampleLinks.length" class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">监测与样本证据</div>
        </div>
        <div class="ti-card-body key-grid">
          <div>
            <span>监测优先级</span>
            <strong>{{ monitoringPriority || 'low' }}</strong>
          </div>
          <div>
            <span>监测权重</span>
            <strong>{{ monitoringWeight }}</strong>
          </div>
          <div>
            <span>样本证据</span>
            <strong>{{ hasSampleEvidence ? '检测到样本证据' : '未检测到' }}</strong>
          </div>
        </div>
        <div class="ti-card-body topic-panel">
          <div v-if="monitoringMatches.length" class="topic-panel__group">
            <span>命中监测规则</span>
            <div class="chip-list">
              <span v-for="item in monitoringMatches" :key="`${item.keyword}-${item.category}`" class="detail-chip detail-chip--topic">
                {{ item.keyword }} · {{ item.weight }}
              </span>
            </div>
          </div>
          <div v-if="sampleLinks.length" class="topic-panel__group">
            <span>样本链接</span>
            <div class="reference-list">
              <div v-for="item in sampleLinks" :key="item.url" class="reference-item">
                <span class="reference-source">类型：{{ item.kind || 'sample' }}</span>
                <a :href="item.url" target="_blank" rel="noreferrer" class="reference-link">{{ item.url }}</a>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="ruleRiskBreakdownSegments.length" class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">规则主评分构成</div>
        </div>
        <div class="ti-card-body risk-breakdown-list">
          <article v-for="segment in ruleRiskBreakdownSegments" :key="segment.key" class="risk-breakdown-item">
            <div class="risk-breakdown-item__header">
              <strong>{{ segment.label }}</strong>
              <span>{{ segment.score }} / {{ segment.max_score }}</span>
            </div>
            <p v-if="segment.reasons?.length">{{ segment.reasons.join('；') }}</p>
          </article>
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">{{ isVulnerability ? '来源与记录信息' : '披露链接与地域' }}</div>
        </div>
        <div class="ti-card-body link-grid">
          <template v-if="!isVulnerability">
            <div>
              <span>披露 URL</span>
              <a v-if="eventDetail.disclosure_url" :href="eventDetail.disclosure_url" target="_blank" rel="noreferrer">
                {{ eventDetail.disclosure_url }}
              </a>
              <strong v-else>暂无</strong>
            </div>
            <div>
              <span>受害地区</span>
              <strong>{{ eventDetail.region || '未知' }}</strong>
            </div>
            <div>
              <span>原始类型</span>
              <strong>{{ eventDetail.raw_source_type || '未知' }}</strong>
            </div>
          </template>

          <template v-else>
            <div>
              <span>数据来源</span>
              <strong>{{ vulnerabilitySourcesText }}</strong>
            </div>
            <div>
              <span>原始类型</span>
              <strong>{{ eventDetail.raw_source_type_label || '未知' }}</strong>
            </div>
            <div>
              <span>来源类别</span>
              <strong>{{ eventDetail.source_type_label || '未知' }}</strong>
            </div>
            <div>
              <span>参考链接数</span>
              <strong>{{ eventDetail.reference_urls?.length || 0 }}</strong>
            </div>
          </template>
        </div>
      </div>

      <div v-if="isVulnerability" class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">受影响版本</div>
        </div>
        <div class="ti-card-body">
          <p class="version-note">命中以下版本范围：</p>
          <div v-if="affectedVersionItems.length" class="version-list">
            <span
              v-for="item in affectedVersionItems"
              :key="item.raw"
              class="version-chip"
              :title="item.raw"
            >
              {{ item.display }}
            </span>
          </div>
          <p v-else class="resource-empty">暂未给出明确的受影响版本范围。</p>
        </div>
      </div>

      <div v-if="isVulnerability && referenceUrls.length" class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">参考链接</div>
        </div>
        <div class="ti-card-body">
          <div class="reference-list">
            <div
              v-for="item in referenceUrls"
              :key="item.url"
              class="reference-item"
            >
              <span class="reference-source">来源：{{ item.label || '参考链接' }}</span>
              <a
                :href="item.url"
                target="_blank"
                rel="noreferrer"
                class="reference-link"
                :title="item.url"
              >
                {{ item.url }}
              </a>
            </div>
          </div>
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">{{ isVulnerability ? '漏洞摘要与处置说明' : '事件详情' }}</div>
        </div>
        <div v-if="canTranslateDetail" class="detail-translate-action">
          <el-button
            size="small"
            plain
            :loading="translatingDetail"
            @click="toggleDetailTranslation"
          >
            {{ showTranslatedDetail ? '查看原文' : '翻译正文' }}
          </el-button>
        </div>
        <div class="ti-card-body detail-text">
          <div class="detail-copy">
            <p
              v-for="(paragraph, index) in detailParagraphs"
              :key="`${index}-${paragraph.slice(0, 24)}`"
            >
              {{ paragraph }}
            </p>
          </div>
        </div>
      </div>

      <template v-if="!isVulnerability">
        <div class="ti-card ti-reveal-up">
          <div class="ti-card-header">
            <div class="ti-card-title">截图资源</div>
          </div>
          <div class="ti-card-body">
            <div v-if="screenshotResources.length" class="screenshot-gallery screenshot-gallery--single">
              <a
                v-for="item in screenshotResources"
                :key="item.url"
                :href="item.url"
                target="_blank"
                rel="noreferrer"
                class="screenshot-card screenshot-card--large"
                :title="item.label || item.url"
              >
                <img
                  v-if="isImageResource(item.url)"
                  :src="item.url"
                  :alt="item.label || '截图资源'"
                  loading="lazy"
                />
                <div class="screenshot-card__meta">
                  <strong>{{ item.label || '截图资源' }}</strong>
                </div>
              </a>
            </div>
            <p v-else class="resource-empty">暂无截图资源。</p>
          </div>
        </div>
      </template>

    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useEventDetail } from '@/composables/useEventDetail'

const route = useRoute()
const router = useRouter()
const { detail, loading, refreshing, error, load } = useEventDetail()
const eventDetail = computed(() => detail.value)
const isVulnerability = computed(() => eventDetail.value?.normalized_event_type === 'vulnerability' || !!eventDetail.value?.cve_id)
const primarySubjectLabel = computed(() => isVulnerability.value ? '厂商' : '攻击者')
const primarySubjectValue = computed(() => isVulnerability.value ? (eventDetail.value?.vendor || '未知') : (eventDetail.value?.attacker || '未知'))
const secondarySubjectLabel = computed(() => isVulnerability.value ? '产品' : '受害实体')
const secondarySubjectValue = computed(() => isVulnerability.value ? (eventDetail.value?.product || '未知') : (eventDetail.value?.victim || '未知'))
const affectedVersionItems = computed(() => eventDetail.value?.affected_version_items || [])
const screenshotResources = computed(() => eventDetail.value?.screenshot_resources || [])
const referenceUrls = computed(() => eventDetail.value?.reference_urls || [])
const riskBreakdown = computed(() => eventDetail.value?.risk_breakdown || {})
const riskBreakdownSegments = computed(() => riskBreakdown.value?.segments || [])
const ruleRiskBreakdown = computed(() => eventDetail.value?.rule_risk_breakdown || {})
const ruleRiskBreakdownSegments = computed(() => ruleRiskBreakdown.value?.segments || riskBreakdownSegments.value || [])
const monitoringMatches = computed(() => eventDetail.value?.monitoring_matches || [])
const monitoringWeight = computed(() => Number(eventDetail.value?.monitoring_weight || 0))
const monitoringPriority = computed(() => eventDetail.value?.monitoring_priority || 'low')
const sampleLinks = computed(() => eventDetail.value?.sample_links || [])
const hasSampleEvidence = computed(() => Boolean(eventDetail.value?.has_sample_evidence))
const translatedDetailText = ref('')
const showTranslatedDetail = ref(false)
const translatingDetail = ref(false)
const canTranslateDetail = computed(() => !isVulnerability.value && !!eventDetail.value?.detail_text)
const vulnerabilitySourcesText = computed(() => {
  const labels = eventDetail.value?.source_labels || []
  if (labels.length) {
    return labels.join(' / ')
  }
  return eventDetail.value?.source || '未知'
})
const detailBody = computed(() => {
  if (!eventDetail.value) return '暂无事件详情。'
  if (!isVulnerability.value) return eventDetail.value.detail_text || '暂无事件详情。'
  const lines = [
    eventDetail.value.summary || eventDetail.value.detail_text || '暂无漏洞摘要。',
    '',
    `利用状态：${eventDetail.value.is_exploited ? '已被利用' : '待观察'}`,
    `补丁状态：${eventDetail.value.patch_available ? '已有补丁' : '待补丁 / 临时缓解'}`,
    `PoC 状态：${eventDetail.value.has_poc ? '已公开' : '未公开'}`,
  ]
  return lines.join('\n')
})
const renderedDetailBody = computed(() => {
  if (!isVulnerability.value && showTranslatedDetail.value && translatedDetailText.value) {
    return translatedDetailText.value
  }
  return detailBody.value
})
const detailParagraphs = computed(() => {
  const raw = String(renderedDetailBody.value || '').trim()
  if (!raw) return ['暂无事件详情。']

  const blocks = raw
    .split(/\n\s*\n+/)
    .map((item) => item.trim())
    .filter(Boolean)

  if (blocks.length > 1) {
    return blocks.flatMap((block) =>
      block
        .split(/\n+/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  }

  if (raw.length <= 160) {
    return [raw]
  }

  const sentences = raw
    .split(/(?<=[。！？.!?])\s+/)
    .map((item) => item.trim())
    .filter(Boolean)

  if (sentences.length <= 2) {
    return [raw]
  }

  const paragraphs = []
  for (let index = 0; index < sentences.length; index += 2) {
    paragraphs.push(sentences.slice(index, index + 2).join(' '))
  }
  return paragraphs
})

async function toggleDetailTranslation() {
  if (!eventDetail.value || isVulnerability.value) return
  if (showTranslatedDetail.value) {
    showTranslatedDetail.value = false
    return
  }
  if (translatedDetailText.value) {
    showTranslatedDetail.value = true
    return
  }

  translatingDetail.value = true
  try {
    const eventId = String(route.params.eventId || '')
    const response = await fetch(`/api/events/${encodeURIComponent(eventId)}?translate_detail=true`)
    if (!response.ok) {
      throw new Error(`translate detail failed: ${response.status}`)
    }
    const payload = await response.json()
    translatedDetailText.value = String(payload?.detail_text || '')
    showTranslatedDetail.value = !!translatedDetailText.value
  } catch (translateError) {
    console.error(translateError)
  } finally {
    translatingDetail.value = false
  }
}

function goBackToList() {
  const eventId = String(route.params.eventId || '')
  const backPath = sessionStorage.getItem(`event-back:${eventId}`) || (String(eventId).startsWith('vuln:') ? '/vulnerability-alerts' : '/data-leak')
  router.push(backPath)
}

function isImageResource(url) {
  return /\.(png|jpe?g|webp|gif|bmp|svg)(\?.*)?$/i.test(String(url || ''))
}

watch(
  () => route.params.eventId,
  (eventId) => {
    translatedDetailText.value = ''
    showTranslatedDetail.value = false
    translatingDetail.value = false
    load(String(eventId || ''))
  },
  { immediate: true }
)
</script>

<style scoped lang="scss">
.detail-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 18px;
}

.detail-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(320px, 1fr);
  gap: 24px;
  margin-top: 22px;
  padding: 22px;
  border-radius: 22px;
  border: 1px solid var(--ti-border-default);
  background: rgba(255, 255, 255, 0.68);
}

.detail-hero--title-only {
  grid-template-columns: 1fr;
}

.detail-loading,
.empty-state {
  margin-top: 22px;
  padding: 22px;
  border-radius: 22px;
  border: 1px solid var(--ti-border-default);
  background: rgba(255, 255, 255, 0.68);
  color: var(--ti-text-secondary);
}

.empty-state__error {
  margin-top: 8px;
  color: var(--ti-danger-strong);
}

.loading-inline {
  color: var(--ti-text-secondary);
}

.detail-hero h2 {
  margin: 10px 0 8px;
  font-size: 30px;
  color: var(--ti-text-primary);
}

.detail-hero__meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.detail-hero__meta div,
.key-grid div,
.link-grid div {
  padding: 16px;
  border-radius: 18px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.72);
}

.detail-hero__meta span,
.key-grid span,
.link-grid span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.detail-hero__meta strong,
.key-grid strong,
.link-grid strong {
  display: block;
  margin-top: 6px;
  color: var(--ti-text-primary);
  font-size: 18px;
}

.detail-identifier {
  font-size: 14px;
  line-height: 1.5;
  word-break: break-all;
}

.detail-grid {
  display: grid;
  gap: 22px;
}

.key-grid,
.link-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.detail-copy {
  display: grid;
  gap: 14px;
}

.detail-translate-action {
  padding: 0 22px 12px;
}

.detail-copy p {
  margin: 0;
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--ti-border-soft);
  color: var(--ti-text-secondary);
  line-height: 1.9;
  white-space: pre-wrap;
  word-break: break-word;
}

.link-grid a {
  color: var(--ti-primary);
  word-break: break-all;
}

.reference-list {
  display: grid;
  gap: 12px;
}

.reference-item {
  display: block;
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(47, 107, 255, 0.14);
  background: rgba(47, 107, 255, 0.05);
}

.reference-link {
  display: block;
  margin-top: 8px;
  color: #2f6bff;
  font-weight: 600;
  word-break: break-all;
  text-decoration: none;
}

.reference-item:hover .reference-link {
  text-decoration: underline;
}

.reference-source {
  display: block;
  color: var(--ti-text-secondary);
  font-size: 12px;
}

.resource-empty,
.empty-state {
  color: var(--ti-text-secondary);
}

.screenshot-gallery {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.screenshot-gallery--single {
  grid-template-columns: 1fr;
}

.screenshot-card {
  display: block;
  overflow: hidden;
  border-radius: 18px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.76);
}

.screenshot-card img {
  display: block;
  width: 100%;
  height: 240px;
  object-fit: cover;
  background: #eef2f7;
}

.screenshot-card--large img {
  height: auto;
  max-height: none;
  object-fit: contain;
}

.screenshot-card__meta {
  display: grid;
  gap: 6px;
  padding: 14px;
}

.screenshot-card__meta strong {
  color: var(--ti-text-primary);
}

.screenshot-card__meta span {
  color: var(--ti-text-secondary);
  font-size: 12px;
  word-break: break-all;
}

.version-note {
  margin: 0 0 14px;
  color: var(--ti-text-secondary);
  font-size: 13px;
}

.version-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.version-chip {
  display: inline-flex;
  align-items: center;
  padding: 10px 14px;
  border-radius: 999px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.84);
  color: var(--ti-text-primary);
  font-size: 13px;
  font-weight: 600;
}

.topic-panel {
  display: grid;
  gap: 16px;
}

.topic-panel__group span {
  display: block;
  margin-bottom: 8px;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.topic-panel__group p,
.topic-panel__group strong {
  margin: 0;
  color: var(--ti-text-primary);
}

.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.detail-chip {
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.detail-chip--topic {
  background: rgba(37, 99, 235, 0.08);
  color: #1d4ed8;
}

.detail-chip--behavior {
  background: rgba(234, 88, 12, 0.08);
  color: #c2410c;
}

.detail-chip--keyword {
  background: rgba(15, 118, 110, 0.08);
  color: #0f766e;
}

.risk-breakdown-list {
  display: grid;
  gap: 12px;
}

.risk-breakdown-item {
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(47, 107, 255, 0.14);
  background: rgba(47, 107, 255, 0.05);
}

.risk-breakdown-item__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.risk-breakdown-item p {
  margin: 8px 0 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
}

@media (max-width: 1100px) {
  .detail-hero,
  .key-grid,
  .link-grid {
    grid-template-columns: 1fr;
  }

  .screenshot-gallery {
    grid-template-columns: 1fr;
  }
}
</style>
