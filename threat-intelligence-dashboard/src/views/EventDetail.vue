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
      <div v-if="loading" class="ti-card ti-reveal-up">
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

      <div v-if="isVulnerability && eventDetail.reference_urls?.length" class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">参考链接</div>
        </div>
        <div class="ti-card-body">
          <div class="reference-list">
            <a
              v-for="item in eventDetail.reference_urls"
              :key="item.url"
              :href="item.url"
              target="_blank"
              rel="noreferrer"
              class="reference-item"
              :title="item.url"
            >
              <span class="reference-source">来源：{{ item.label || '参考链接' }}</span>
              <strong>{{ item.url }}</strong>
            </a>
          </div>
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">{{ isVulnerability ? '漏洞摘要与处置说明' : '事件详情' }}</div>
        </div>
        <div class="ti-card-body detail-text">
          <pre>{{ detailBody }}</pre>
        </div>
      </div>

      <template v-if="!isVulnerability">
        <div class="resource-grid">
          <div class="ti-card ti-reveal-up">
            <div class="ti-card-header">
              <div class="ti-card-title">截图资源</div>
            </div>
            <div class="ti-card-body">
              <div v-if="screenshotResources.length" class="screenshot-gallery">
                <a
                  v-for="item in screenshotResources"
                  :key="item.url"
                  :href="item.url"
                  target="_blank"
                  rel="noreferrer"
                  class="screenshot-card"
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
                    <span>{{ item.url }}</span>
                  </div>
                </a>
              </div>
              <p v-else class="resource-empty">暂无截图资源。</p>
            </div>
          </div>

          <div class="ti-card ti-reveal-up">
            <div class="ti-card-header">
              <div class="ti-card-title">镜像与预览资源</div>
            </div>
            <div class="ti-card-body">
              <div v-if="previewResources.length" class="reference-list">
                <a
                  v-for="item in previewResources"
                  :key="item.url"
                  :href="item.url"
                  target="_blank"
                  rel="noreferrer"
                  class="reference-item"
                  :title="item.url"
                >
                  <span class="reference-source">资源：{{ item.label || '镜像资源' }}</span>
                  <strong>{{ item.url }}</strong>
                </a>
              </div>
              <p v-else class="resource-empty">暂无镜像或预览资源。</p>
            </div>
          </div>
        </div>
      </template>

    </section>
  </div>
</template>

<script setup>
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useEventDetail } from '@/composables/useEventDetail'

const route = useRoute()
const router = useRouter()
const { detail, loading, error, load } = useEventDetail()
const eventDetail = computed(() => detail.value)
const isVulnerability = computed(() => eventDetail.value?.normalized_event_type === 'vulnerability' || !!eventDetail.value?.cve_id)
const primarySubjectLabel = computed(() => isVulnerability.value ? '厂商' : '攻击者')
const primarySubjectValue = computed(() => isVulnerability.value ? (eventDetail.value?.vendor || '未知') : (eventDetail.value?.attacker || '未知'))
const secondarySubjectLabel = computed(() => isVulnerability.value ? '产品' : '受害实体')
const secondarySubjectValue = computed(() => isVulnerability.value ? (eventDetail.value?.product || '未知') : (eventDetail.value?.victim || '未知'))
const affectedVersionItems = computed(() => eventDetail.value?.affected_version_items || [])
const screenshotResources = computed(() => eventDetail.value?.screenshot_resources || [])
const previewResources = computed(() => {
  const resources = []
  const seen = new Set()

  if (eventDetail.value?.json_preview_url) {
    const previewUrl = String(eventDetail.value.json_preview_url)
    resources.push({ label: 'JSON 预览', url: previewUrl })
    seen.add(previewUrl)
  }

  for (const item of eventDetail.value?.mirror_resources || []) {
    if (!item?.url) continue
    const url = String(item.url)
    if (seen.has(url)) continue
    seen.add(url)
    resources.push(item)
  }

  return resources
})
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

.detail-grid {
  display: grid;
  gap: 22px;
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px;
}

.key-grid,
.link-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.detail-text pre {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--ti-text-secondary);
  font-family: inherit;
  line-height: 1.8;
  margin: 0;
}

.link-grid a {
  color: var(--ti-primary);
  word-break: break-all;
}

.resource-empty,
.empty-state {
  color: var(--ti-text-secondary);
}

.reference-list {
  display: grid;
  gap: 12px;
}

.screenshot-gallery {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
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

.reference-item {
  display: grid;
  gap: 6px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.72);
}

.reference-item strong {
  color: var(--ti-text-primary);
  word-break: break-all;
}

.reference-item span {
  color: var(--ti-text-secondary);
  word-break: break-all;
}

.reference-source {
  font-size: 12px;
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

@media (max-width: 1100px) {
  .detail-hero,
  .resource-grid,
  .key-grid,
  .link-grid {
    grid-template-columns: 1fr;
  }

  .screenshot-gallery {
    grid-template-columns: 1fr;
  }
}
</style>
