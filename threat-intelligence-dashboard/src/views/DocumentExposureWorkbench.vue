<template>
  <div class="monitoring-workbench ti-page">
    <section class="monitor-shell">
      <header class="monitor-shell__header">
        <div>
          <div class="monitor-shell__eyebrow">{{ currentConfig.eyebrow }}</div>
          <h2 class="monitor-shell__title">{{ currentConfig.title }}</h2>
          <p class="monitor-shell__summary">{{ currentConfig.summary }}</p>
        </div>
        <div class="monitor-shell__actions">
          <el-button plain @click="router.push('/document-exposure/settings')">监测配置</el-button>
          <el-button plain @click="router.push('/document-exposure/scans')">扫描历史</el-button>
          <el-button plain @click="router.push('/document-exposure/results')">辅助结果页</el-button>
          <el-button type="primary" :loading="loading" @click="loadData">刷新数据</el-button>
        </div>
      </header>

      <section class="metric-grid">
        <article v-for="card in metricCards" :key="card.label" class="metric-card">
          <span class="metric-card__label">{{ card.label }}</span>
          <strong class="metric-card__value">{{ formatNumber(card.value) }}</strong>
          <span class="metric-card__hint">{{ card.hint }}</span>
        </article>
      </section>

      <section class="chart-grid">
        <article class="monitor-panel">
          <div class="monitor-panel__header">
            <div>
              <div class="monitor-panel__eyebrow">趋势</div>
              <h3>{{ currentConfig.trendTitle }}</h3>
            </div>
            <span class="monitor-panel__meta">近 7 天</span>
          </div>
          <v-chart class="monitor-chart" :option="trendOption" autoresize />
        </article>

        <article class="monitor-panel">
          <div class="monitor-panel__header">
            <div>
              <div class="monitor-panel__eyebrow">分布</div>
              <h3>{{ currentConfig.distributionTitle }}</h3>
            </div>
            <span class="monitor-panel__meta">{{ distributionTotalLabel }}</span>
          </div>
          <v-chart class="monitor-chart monitor-chart--donut" :option="distributionOption" autoresize />
        </article>
      </section>

      <section class="monitor-panel">
        <div class="monitor-panel__header monitor-panel__header--table">
          <div>
            <div class="monitor-panel__eyebrow">列表</div>
            <h3>{{ currentConfig.tableTitle }}</h3>
          </div>
          <div class="monitor-panel__meta-group">
            <span>{{ filteredHits.length }} 条结果</span>
            <span>最后更新 {{ formatDateTime(summary.lastScanAt) || '-' }}</span>
          </div>
        </div>

        <div class="chip-row">
          <button
            v-for="item in sourceChips"
            :key="item.key"
            type="button"
            class="chip-button"
            :class="{ active: selectedSource === item.key }"
            @click="selectedSource = item.key"
          >
            {{ item.label }}
          </button>
        </div>

        <div class="filter-row">
          <el-select v-model="riskFilter" clearable placeholder="风险级别" class="filter-control">
            <el-option label="高危" value="high" />
            <el-option label="中危" value="medium" />
            <el-option label="低危" value="low" />
          </el-select>
          <el-select v-model="reviewFilter" clearable placeholder="处置状态" class="filter-control">
            <el-option label="未处理" value="new" />
            <el-option label="处理中" value="triaged" />
            <el-option label="已确认" value="confirmed" />
            <el-option label="误报" value="false_positive" />
            <el-option label="已关闭" value="closed" />
          </el-select>
          <el-input v-model="keyword" clearable placeholder="搜索标题、平台、文件名、关键词" class="filter-search">
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>

        <div class="table-shell">
          <el-table :data="pagedHits" table-layout="auto">
            <el-table-column
              v-for="column in currentConfig.columns"
              :key="column.key"
              :label="column.label"
              :min-width="column.minWidth"
              :width="column.width"
              show-overflow-tooltip
            >
              <template #default="{ row }">
                <span v-if="column.key === 'riskScore'" :class="['severity-pill', `severity-pill--${row.severity || 'low'}`]">
                  {{ formatNumber(row.riskScore) }}
                </span>
                <span v-else-if="column.key === 'matchedTerms'">{{ matchedTermsText(row) }}</span>
                <span v-else-if="column.key === 'lastSeenAt'">{{ formatDateTime(row.lastSeenAt) || '-' }}</span>
                <span v-else-if="column.key === 'reviewStatus'">{{ row.reviewStatusLabel || row.reviewStatus || '-' }}</span>
                <span v-else-if="column.key === 'accessState'">{{ row.accessStateLabel || row.accessState || '-' }}</span>
                <span v-else-if="column.key === 'shareType'">{{ row.shareType === 'password_share' ? '口令分享' : '公开分享' }}</span>
                <span v-else>{{ column.value(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <el-button type="primary" size="small" @click="viewDetail(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="table-footer">
          <span class="table-footer__note">{{ currentConfig.footerHint }}</span>
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50]"
            :total="filteredHits.length"
            layout="total, sizes, prev, pager, next"
            background
          />
        </div>
      </section>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import '@/lib/echarts'
import { useDocumentExposureApi } from '@/composables/useDocumentExposureApi'

const route = useRoute()
const router = useRouter()
const api = useDocumentExposureApi()

const FAMILY_CONFIG = {
  search_engine: {
    eyebrow: 'Search Engine',
    title: '搜索引擎监测',
    summary: '聚焦通过搜索引擎发现的敏感文档结果，列表页只保留摘要，详情能力下沉到独立详情页。',
    trendTitle: '新增命中文档趋势',
    distributionTitle: '搜索来源分布',
    tableTitle: '搜索引擎命中列表',
    footerHint: '详情页展示来源结果、证据快照、匹配词和处置记录。',
    columns: [
      { key: 'title', label: '页面标题 / 链接', minWidth: 260, value: (row) => row.title || row.canonicalUrl || '-' },
      { key: 'discoverySourceLabel', label: '来源', width: 140, value: (row) => row.discoverySourceLabel || '-' },
      { key: 'primaryFileType', label: '文件类型', width: 120, value: (row) => (row.primaryFileType || '-').toUpperCase() },
      { key: 'matchedTerms', label: '匹配关键词', minWidth: 200, value: () => '' },
      { key: 'riskScore', label: '风险级别', width: 110, value: () => '' },
      { key: 'lastSeenAt', label: '发现时间', minWidth: 160, value: () => '' },
      { key: 'reviewStatus', label: '处理状态', width: 120, value: () => '' },
    ],
    sourceLabel: (row) => row.discoverySourceLabel || row.discoverySource || '未知来源',
  },
  netdisk_aggregator: {
    eyebrow: 'Netdisk',
    title: '网盘监测',
    summary: '聚焦公开网盘分享页面，展示平台分布、访问状态、文件清单和风险处置情况。',
    trendTitle: '分享链接发现趋势',
    distributionTitle: '平台分布',
    tableTitle: '网盘命中列表',
    footerHint: '详情页展示分享信息、文件预览、风险分析和处置动作。',
    columns: [
      { key: 'primaryFileName', label: '文件名', minWidth: 240, value: (row) => row.primaryFileName || row.title || '-' },
      { key: 'platformLabel', label: '来源平台', width: 140, value: (row) => row.platformLabel || '-' },
      { key: 'shareType', label: '分享类型', width: 120, value: () => '' },
      { key: 'shareCode', label: '提取码 / 口令', width: 140, value: (row) => row.shareCode || '-' },
      { key: 'matchedTerms', label: '匹配企业关键词', minWidth: 200, value: () => '' },
      { key: 'riskScore', label: '风险级别', width: 110, value: () => '' },
      { key: 'lastSeenAt', label: '发现时间', minWidth: 160, value: () => '' },
      { key: 'accessState', label: '链接状态', width: 120, value: () => '' },
    ],
    sourceLabel: (row) => row.platformLabel || row.platform || '未知平台',
  },
  document_library: {
    eyebrow: 'Document Library',
    title: '文库监测',
    summary: '聚焦文库平台中的文档命中，突出来源平台、文档预览、匹配关键词和处理记录。',
    trendTitle: '文档发现趋势',
    distributionTitle: '平台分布',
    tableTitle: '文库命中列表',
    footerHint: '详情页展示文档截图、预览文本、文件信息和处置流转。',
    columns: [
      { key: 'title', label: '文档标题', minWidth: 260, value: (row) => row.title || '-' },
      { key: 'platformLabel', label: '来源站点', width: 150, value: (row) => row.platformLabel || '-' },
      { key: 'primaryFileType', label: '文档类型', width: 120, value: (row) => (row.primaryFileType || '-').toUpperCase() },
      { key: 'fileCount', label: '文件数', width: 100, value: (row) => formatNumber(row.fileCount) },
      { key: 'matchedTerms', label: '命中关键词', minWidth: 200, value: () => '' },
      { key: 'riskScore', label: '风险级别', width: 110, value: () => '' },
      { key: 'lastSeenAt', label: '发现时间', minWidth: 160, value: () => '' },
      { key: 'reviewStatus', label: '处理状态', width: 120, value: () => '' },
    ],
    sourceLabel: (row) => row.platformLabel || row.platform || '未知平台',
  },
}

const loading = ref(false)
const keyword = ref('')
const selectedSource = ref('all')
const riskFilter = ref('')
const reviewFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(10)
const summary = reactive({
  totalHits: 0,
  highRiskCount: 0,
  pendingReviewCount: 0,
  recentCount: 0,
  publicCount: 0,
  invalidCount: 0,
  trend: [],
  platformDistribution: [],
  discoveryDistribution: [],
  lastScanAt: '',
})
const hits = ref([])

const sourceFamily = computed(() => route.meta.sourceFamily || 'search_engine')
const currentConfig = computed(() => FAMILY_CONFIG[sourceFamily.value] || FAMILY_CONFIG.search_engine)

const metricCards = computed(() => {
  const base = [
    {
      label: sourceFamily.value === 'netdisk_aggregator' ? '分享链接数' : sourceFamily.value === 'document_library' ? '公开文档数' : '搜索结果总数',
      value: summary.totalHits,
      hint: `最近扫描命中 ${summary.totalHits || 0} 条`,
    },
    {
      label: sourceFamily.value === 'netdisk_aggregator' ? '有效链接' : '高风险命中',
      value: sourceFamily.value === 'netdisk_aggregator' ? summary.publicCount : summary.highRiskCount,
      hint: sourceFamily.value === 'netdisk_aggregator' ? '当前可访问公开结果' : '风险分 >= 75',
    },
    {
      label: sourceFamily.value === 'netdisk_aggregator' ? '失效链接' : '近 24h 新增',
      value: sourceFamily.value === 'netdisk_aggregator' ? summary.invalidCount : summary.recentCount,
      hint: sourceFamily.value === 'netdisk_aggregator' ? '失效或拒绝访问' : '最近 24 小时新增',
    },
    {
      label: '待处置',
      value: summary.pendingReviewCount,
      hint: '需要人工确认或关闭',
    },
  ]
  return base
})

const sourceChips = computed(() => {
  const rows = sourceFamily.value === 'search_engine' ? summary.discoveryDistribution : summary.platformDistribution
  return [
    { key: 'all', label: '全部' },
    ...rows.map((item) => ({ key: item.name, label: `${item.name} (${item.value})` })),
  ]
})

const filteredHits = computed(() => {
  const searchText = keyword.value.trim().toLowerCase()
  return hits.value.filter((row) => {
    const matchesSource = selectedSource.value === 'all' || currentConfig.value.sourceLabel(row) === selectedSource.value
    const matchesRisk = !riskFilter.value || row.severity === riskFilter.value
    const matchesReview = !reviewFilter.value || row.reviewStatus === reviewFilter.value
    const matchesKeyword =
      !searchText ||
      [
        row.title,
        row.primaryFileName,
        row.platformLabel,
        row.discoverySourceLabel,
        row.canonicalUrl,
        matchedTermsText(row),
      ]
        .join(' ')
        .toLowerCase()
        .includes(searchText)
    return matchesSource && matchesRisk && matchesReview && matchesKeyword
  })
})

const pagedHits = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredHits.value.slice(start, start + pageSize.value)
})

const trendOption = computed(() => ({
  grid: { left: 32, right: 16, top: 32, bottom: 28 },
  xAxis: {
    type: 'category',
    data: (summary.trend || []).map((item) => item.date.slice(5)),
    axisLine: { lineStyle: { color: 'rgba(114, 149, 211, 0.3)' } },
    axisLabel: { color: 'rgba(216, 231, 255, 0.72)' },
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: 'rgba(114, 149, 211, 0.14)' } },
    axisLabel: { color: 'rgba(216, 231, 255, 0.62)' },
  },
  tooltip: { trigger: 'axis' },
  series: [
    {
      type: 'line',
      smooth: true,
      data: (summary.trend || []).map((item) => item.value),
      symbolSize: 8,
      lineStyle: { width: 3, color: '#4ca5ff' },
      itemStyle: { color: '#7ad0ff' },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(76, 165, 255, 0.32)' },
            { offset: 1, color: 'rgba(76, 165, 255, 0.02)' },
          ],
        },
      },
    },
  ],
}))

const distributionSeries = computed(() => (
  (sourceFamily.value === 'search_engine' ? summary.discoveryDistribution : summary.platformDistribution) || []
))

const distributionTotalLabel = computed(() => `${formatNumber(summary.totalHits)} 条`)

const distributionOption = computed(() => ({
  tooltip: { trigger: 'item' },
  legend: {
    bottom: 0,
    textStyle: { color: 'rgba(216, 231, 255, 0.72)' },
  },
  series: [
    {
      type: 'pie',
      radius: ['46%', '72%'],
      center: ['50%', '42%'],
      data: distributionSeries.value,
      label: {
        color: 'rgba(245, 250, 255, 0.92)',
        formatter: '{b}',
      },
      itemStyle: {
        borderColor: '#08192f',
        borderWidth: 3,
      },
    },
  ],
}))

function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatDateTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 16)
}

function matchedTermsText(row) {
  if (!Array.isArray(row?.matchedTerms) || !row.matchedTerms.length) return '-'
  return row.matchedTerms
    .map((item) => item.term)
    .filter(Boolean)
    .join('、')
}

async function loadData() {
  loading.value = true
  try {
    const [summaryPayload, hitPayload] = await Promise.all([
      api.loadSummary({ sourceFamily: sourceFamily.value }),
      api.loadHits({ sourceFamily: sourceFamily.value, limit: 300 }),
    ])
    Object.assign(summary, summaryPayload || {})
    hits.value = Array.isArray(hitPayload) ? hitPayload : []
  } catch (error) {
    ElMessage.error(error.message || '加载文件监测数据失败')
  } finally {
    loading.value = false
  }
}

function viewDetail(row) {
  router.push({
    name: 'DocumentExposureDetail',
    params: {
      sourceFamily: sourceFamily.value,
      hitId: row.id,
    },
  })
}

watch([filteredHits, pageSize], () => {
  const maxPage = Math.max(1, Math.ceil(filteredHits.value.length / pageSize.value))
  if (currentPage.value > maxPage) currentPage.value = maxPage
})

watch(
  () => sourceFamily.value,
  () => {
    selectedSource.value = 'all'
    riskFilter.value = ''
    reviewFilter.value = ''
    keyword.value = ''
    currentPage.value = 1
    loadData()
  },
)

onMounted(loadData)
</script>

<style scoped lang="scss">
.monitor-shell {
  display: grid;
  gap: 20px;
  padding: 24px;
  border-radius: 28px;
  background: #ffffff;
  color: var(--ti-text-primary);
  border: 1px solid rgba(116, 142, 184, 0.14);
  box-shadow: 0 24px 50px rgba(32, 57, 96, 0.08);
}

.monitor-shell__header,
.monitor-panel__header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.monitor-shell__eyebrow,
.monitor-panel__eyebrow {
  color: var(--ti-primary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.monitor-shell__title {
  margin: 8px 0 10px;
  font-size: 28px;
  color: var(--ti-text-primary);
}

.monitor-shell__summary {
  max-width: 720px;
  margin: 0;
  color: var(--ti-text-secondary);
}

.monitor-shell__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.metric-grid,
.chart-grid {
  display: grid;
  gap: 16px;
}

.metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.chart-grid {
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
}

.metric-card,
.monitor-panel {
  border: 1px solid rgba(116, 142, 184, 0.14);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 14px 30px rgba(32, 57, 96, 0.06);
}

.metric-card {
  display: grid;
  gap: 8px;
  padding: 18px 20px;
}

.metric-card__label {
  color: var(--ti-text-secondary);
  font-size: 13px;
}

.metric-card__value {
  font-size: 30px;
  color: var(--ti-text-primary);
}

.metric-card__hint {
  color: var(--ti-primary);
  font-size: 12px;
}

.monitor-panel {
  padding: 18px;
}

.monitor-panel h3 {
  margin: 6px 0 0;
  font-size: 18px;
  color: var(--ti-text-primary);
}

.monitor-panel__meta,
.monitor-panel__meta-group {
  color: var(--ti-text-muted);
  font-size: 12px;
}

.monitor-panel__meta-group {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.monitor-chart {
  height: 260px;
  margin-top: 14px;
}

.monitor-chart--donut {
  height: 280px;
}

.chip-row,
.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.chip-row {
  margin: 18px 0 14px;
}

.chip-button {
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid rgba(116, 142, 184, 0.18);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.96);
  color: var(--ti-text-secondary);
  cursor: pointer;
}

.chip-button.active {
  border-color: rgba(45, 93, 255, 0.34);
  background: rgba(45, 93, 255, 0.1);
  color: var(--ti-text-primary);
}

.filter-control {
  width: 180px;
}

.filter-search {
  flex: 1;
  min-width: 240px;
}

.table-shell {
  margin-top: 16px;
}

.table-footer {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-top: 18px;
}

.table-footer__note {
  color: var(--ti-text-muted);
  font-size: 12px;
}

.severity-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 62px;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.severity-pill--high {
  background: rgba(229, 85, 87, 0.2);
  color: #ff9b9d;
}

.severity-pill--medium {
  background: rgba(255, 173, 76, 0.2);
  color: #ffcb7d;
}

.severity-pill--low {
  background: rgba(70, 192, 138, 0.2);
  color: #7ce2b0;
}

:deep(.el-button--default) {
  background: rgba(255, 255, 255, 0.96);
  border-color: rgba(116, 142, 184, 0.18);
  color: var(--ti-text-primary);
}

:deep(.el-button--primary) {
  background: linear-gradient(135deg, #2c8dff, #1c6dd0);
  border-color: transparent;
}

:deep(.el-input__wrapper),
:deep(.el-select__wrapper) {
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid rgba(116, 142, 184, 0.16);
}

:deep(.el-input__inner),
:deep(.el-select__selected-item) {
  color: var(--ti-text-primary);
}

:deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-border-color: rgba(116, 142, 184, 0.12);
  --el-table-header-bg-color: rgba(245, 249, 255, 0.96);
  --el-table-header-text-color: var(--ti-text-secondary);
  --el-table-text-color: var(--ti-text-primary);
}

:deep(.el-table th.el-table__cell),
:deep(.el-table td.el-table__cell) {
  background: transparent;
}

@media (max-width: 1280px) {
  .metric-grid,
  .chart-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 960px) {
  .metric-grid,
  .chart-grid,
  .table-footer {
    grid-template-columns: 1fr;
    flex-direction: column;
    align-items: flex-start;
  }

  .monitor-shell__header,
  .monitor-panel__header {
    flex-direction: column;
  }
}
</style>
