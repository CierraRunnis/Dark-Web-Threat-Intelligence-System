<template>
  <div class="document-exposure-home ti-page">
    <section class="module-grid">
      <router-link
        v-for="item in moduleCards"
        :key="item.route"
        :to="item.route"
        class="module-card ti-card ti-reveal-up"
      >
        <div class="module-card__eyebrow">{{ item.eyebrow }}</div>
        <h3 class="module-card__title">{{ item.title }}</h3>
        <p class="module-card__summary">{{ item.summary }}</p>
        <div class="module-card__stats">
          <div v-for="stat in item.stats" :key="stat.label" class="module-card__stat">
            <span>{{ stat.label }}</span>
            <strong>{{ stat.value }}</strong>
          </div>
        </div>
        <div class="module-card__action">进入模块</div>
      </router-link>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useDocumentExposureApi } from '@/composables/useDocumentExposureApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const api = useDocumentExposureApi()
const summary = ref(null)

const moduleCards = computed(() => {
  const data = summary.value || {}
  return [
    {
      route: '/document-exposure/settings',
      eyebrow: '监测配置',
      title: '会话与监测配置',
      summary: '统一管理平台会话、监测对象、关键词、来源家族、文件类型与启停策略。',
      stats: [
        { label: '监测对象', value: String(data.watchlistCount || 0) },
        { label: '启用词数', value: String(data.enabledTermCount || 0) },
        { label: '已配会话', value: String(data.configuredSessionCount || 0) },
        { label: '失效会话', value: String(data.invalidSessionCount || 0) },
      ],
    },
    {
      route: '/document-exposure/scans',
      eyebrow: '扫描任务',
      title: '扫描执行与历史',
      summary: '执行文件监测扫描，查看最近扫描记录、候选数、命中数与错误数。',
      stats: [
        { label: '最近扫描', value: formatLastScanAt(data.lastScanAt) },
        { label: '最近候选', value: String(data.lastCandidateCount || 0) },
        { label: '最近命中', value: String(data.lastHitCount || 0) },
        { label: '最近错误', value: String(data.lastErrorCount || 0) },
      ],
    },
    {
      route: '/document-exposure/results',
      eyebrow: '命中结果',
      title: '命中结果与核验',
      summary: '筛选查看命中结果，执行人工核验，并跳转统一事件详情页查看证据。',
      stats: [
        { label: '总命中', value: String(data.totalHits || 0) },
        { label: '高风险', value: String(data.highRiskCount || 0) },
        { label: '待复核', value: String(data.pendingReviewCount || 0) },
      ],
    },
  ]
})

function formatLastScanAt(value) {
  if (!value) return '未执行'
  return formatShanghaiDateTime(value)
}

async function loadSummary() {
  try {
    summary.value = await api.loadSummary()
  } catch (error) {
    ElMessage.error(error.message || '加载文件监测总览失败')
  }
}

onMounted(loadSummary)
</script>

<style scoped lang="scss">
.module-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 22px;
}

.module-card {
  display: grid;
  gap: 14px;
  padding: 22px;
  color: inherit;
}

.module-card__eyebrow {
  color: var(--ti-accent-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.module-card__title {
  margin: 0;
  color: var(--ti-text-primary);
  font-size: 22px;
}

.module-card__summary {
  margin: 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
}

.module-card__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  align-content: start;
}

.module-card__stat {
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.72);
}

.module-card__stat span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.module-card__stat strong {
  display: block;
  margin-top: 6px;
  color: var(--ti-text-primary);
  font-size: 20px;
}

.module-card__action {
  color: var(--ti-primary);
  font-weight: 700;
}

@media (max-width: 1200px) {
  .module-grid {
    grid-template-columns: 1fr;
  }
}
</style>
