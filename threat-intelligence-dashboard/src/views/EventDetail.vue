<template>
  <div class="event-detail-page ti-page">
    <div class="detail-actions">
      <el-button type="primary" plain @click="goBackToList">返回列表</el-button>
    </div>

    <section class="ti-panel ti-reveal-up">
      <div class="detail-hero" v-if="eventDetail">
        <div>
          <span class="ti-kicker">事件详情页</span>
          <h2>{{ eventDetail.title }}</h2>
        </div>
        <div class="detail-hero__meta">
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
            <span>攻击者</span>
            <strong>{{ eventDetail.attacker || '未知' }}</strong>
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
          <div>
            <span>披露时间</span>
            <strong>{{ eventDetail.disclosure_time || '未知' }}</strong>
          </div>
          <div>
            <span>攻击者</span>
            <strong>{{ eventDetail.attacker || '未知' }}</strong>
          </div>
          <div>
            <span>事件类型</span>
            <strong>{{ eventDetail.category || '未知' }}</strong>
          </div>
          <div>
            <span>来源</span>
            <strong>{{ eventDetail.source || '未知' }}</strong>
          </div>
          <div>
            <span>受害行业</span>
            <strong>{{ eventDetail.industry || '未知' }}</strong>
          </div>
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">披露链接与地域</div>
        </div>
        <div class="ti-card-body link-grid">
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
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">事件详情</div>
        </div>
        <div class="ti-card-body detail-text">
          <pre>{{ eventDetail.detail_text || '暂无事件详情。' }}</pre>
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">截图资源</div>
        </div>
        <div class="ti-card-body">
          <div v-if="eventDetail.screenshot_resources?.length" class="screenshot-grid">
            <a
              v-for="item in eventDetail.screenshot_resources"
              :key="item.url"
              :href="item.url"
              target="_blank"
              rel="noreferrer"
              class="screenshot-card"
            >
              <img :src="item.url" :alt="item.label" class="screenshot-image" />
              <span>{{ item.label }}</span>
            </a>
          </div>
          <p v-else class="resource-empty">暂无截图资源。</p>
        </div>
      </div>
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

function goBackToList() {
  const eventId = String(route.params.eventId || '')
  const backPath = sessionStorage.getItem(`event-back:${eventId}`) || '/data-leak'
  router.push(backPath)
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

.screenshot-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.screenshot-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: 18px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.72);
  color: var(--ti-text-secondary);
}

.screenshot-image {
  width: 100%;
  max-height: 360px;
  object-fit: cover;
  border-radius: 12px;
  border: 1px solid var(--ti-border-soft);
}

@media (max-width: 1100px) {
  .detail-hero,
  .key-grid,
  .link-grid,
  .screenshot-grid {
    grid-template-columns: 1fr;
  }
}
</style>
