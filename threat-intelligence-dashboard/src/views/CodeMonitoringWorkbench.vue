<template>
  <div class="monitoring-workbench ti-page">
    <section class="monitor-shell">
      <header class="monitor-shell__header">
        <div>
          <div class="monitor-shell__eyebrow">Code Monitoring</div>
          <h2 class="monitor-shell__title">代码监测</h2>
          <p class="monitor-shell__summary">基于 GitHub / GitLab / Gitee 的公开代码搜索结果执行检索、敏感匹配、页面快照和处置闭环。</p>
        </div>
        <div class="monitor-shell__actions">
          <el-button plain @click="router.push('/document-exposure/code-monitoring/settings')">配置管理</el-button>
          <el-button plain @click="router.push('/document-exposure/code-monitoring/scans')">扫描历史</el-button>
          <el-button type="primary" :loading="scanLoading" @click="runQuickScan">立即扫描</el-button>
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
              <h3>新增代码泄露趋势</h3>
            </div>
            <span class="monitor-panel__meta">近 7 天</span>
          </div>
          <v-chart class="monitor-chart" :option="trendOption" autoresize />
        </article>

        <article class="monitor-panel">
          <div class="monitor-panel__header">
            <div>
              <div class="monitor-panel__eyebrow">平台</div>
              <h3>来源平台分布</h3>
            </div>
            <span class="monitor-panel__meta">{{ formatNumber(summary.totalHits) }} 条</span>
          </div>
          <v-chart class="monitor-chart monitor-chart--donut" :option="platformOption" autoresize />
        </article>
      </section>

      <section class="chart-grid">
        <article class="monitor-panel">
          <div class="monitor-panel__header">
            <div>
              <div class="monitor-panel__eyebrow">类型</div>
              <h3>敏感类型 TopN</h3>
            </div>
          </div>
          <v-chart class="monitor-chart" :option="typeOption" autoresize />
        </article>

        <article class="monitor-panel">
          <div class="monitor-panel__header">
            <div>
              <div class="monitor-panel__eyebrow">风险</div>
              <h3>风险等级分布</h3>
            </div>
          </div>
          <v-chart class="monitor-chart monitor-chart--donut" :option="riskOption" autoresize />
        </article>
      </section>

      <section class="monitor-panel">
        <div class="monitor-panel__header monitor-panel__header--table">
          <div>
            <div class="monitor-panel__eyebrow">列表</div>
            <h3>代码泄露监测列表</h3>
          </div>
          <div class="monitor-panel__meta-group">
            <span>{{ filteredHits.length }} 条结果</span>
            <span>最近扫描 {{ formatDateTime(summary.lastScanAt) || '-' }}</span>
          </div>
        </div>

        <div class="filter-row">
          <el-select v-model="watchlistFilter" clearable placeholder="监测对象" class="filter-control">
            <el-option v-for="item in watchlists" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
          <el-select v-model="platformFilter" clearable placeholder="来源平台" class="filter-control">
            <el-option v-for="item in platformOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="severityFilter" clearable placeholder="风险级别" class="filter-control">
            <el-option label="高危" value="high" />
            <el-option label="中危" value="medium" />
            <el-option label="低危" value="low" />
          </el-select>
          <el-select v-model="resultLayerFilter" clearable placeholder="命中层级" class="filter-control">
            <el-option label="敏感命中" value="sensitive" />
            <el-option label="线索命中" value="clue" />
          </el-select>
          <el-select v-model="sensitiveTypeFilter" clearable placeholder="敏感类型" class="filter-control">
            <el-option v-for="item in sensitiveTypeOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-input v-model="keyword" clearable placeholder="搜索仓库、路径、敏感词" class="filter-search">
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>

        <div class="table-shell">
          <el-table :data="pagedHits" table-layout="auto">
            <el-table-column label="仓库名称" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.repositoryFullName || row.repositoryName || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="来源平台" width="120">
              <template #default="{ row }">
                {{ row.platformLabel || row.platform || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="文件路径" min-width="240" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.filePath || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="敏感类型" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.sensitiveLabel || row.sensitiveType || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="检索命中词" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.matchedTerm || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="命中层级" width="120">
              <template #default="{ row }">
                <span :class="['layer-pill', `layer-pill--${row.resultLayer || 'sensitive'}`]">
                  {{ row.resultLayerLabel || (row.resultLayer === 'clue' ? '线索命中' : '敏感命中') }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="风险级别" width="110">
              <template #default="{ row }">
                <span :class="['severity-pill', `severity-pill--${row.severity || 'low'}`]">
                  {{ formatSeverity(row.severity) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="发现时间" min-width="160">
              <template #default="{ row }">
                {{ formatDateTime(row.lastSeenAt) || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="处理状态" width="120">
              <template #default="{ row }">
                {{ row.reviewStatus || '-' }}
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
          <span class="table-footer__note">详情页展示代码片段、敏感项列表、风险分析和处置记录，不在列表页展开。</span>
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
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import '@/lib/echarts'
import { useCodeMonitoringApi } from '@/composables/useCodeMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const router = useRouter()
const api = useCodeMonitoringApi()

const loading = ref(false)
const scanLoading = ref(false)
const keyword = ref('')
const watchlistFilter = ref('')
const platformFilter = ref('')
const severityFilter = ref('')
const resultLayerFilter = ref('')
const sensitiveTypeFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(10)
const hits = ref([])
const watchlists = ref([])
const summary = reactive({
  totalHits: 0,
  sensitiveSnippetCount: 0,
  clueHitCount: 0,
  secretLikeCount: 0,
  highRiskRepoCount: 0,
  recentCount: 0,
  trend: [],
  platformDistribution: [],
  sensitiveTypeTop: [],
  riskDistribution: [],
  lastScanAt: '',
})

const metricCards = computed(() => [
  { label: '公开仓库命中', value: summary.totalHits, hint: '命中代码结果总数' },
  { label: '敏感命中', value: summary.sensitiveSnippetCount, hint: '已识别到明确敏感规则的结果' },
  { label: '线索命中', value: summary.clueHitCount, hint: '与监测词强相关但未发现明确凭据' },
  { label: '高危仓库', value: summary.highRiskRepoCount, hint: '风险等级为高危的仓库' },
])

const platformOptions = computed(() => summary.platformDistribution.map((item) => ({
  value: item.name,
  label: item.name,
})))

const sensitiveTypeOptions = computed(() => summary.sensitiveTypeTop.map((item) => item.name))

const filteredHits = computed(() => {
  const searchText = keyword.value.trim().toLowerCase()
  return hits.value.filter((row) => {
    const matchesWatchlist = !watchlistFilter.value || row.watchlistId === watchlistFilter.value
    const matchesPlatform = !platformFilter.value || row.platformLabel === platformFilter.value || row.platform === platformFilter.value
    const matchesSeverity = !severityFilter.value || row.severity === severityFilter.value
    const matchesLayer = !resultLayerFilter.value || row.resultLayer === resultLayerFilter.value
    const matchesSensitiveType = !sensitiveTypeFilter.value || row.sensitiveLabel === sensitiveTypeFilter.value || row.sensitiveType === sensitiveTypeFilter.value
    const matchesKeyword =
      !searchText ||
      [
        row.repositoryFullName,
        row.repositoryName,
        row.filePath,
        row.sensitiveLabel,
        row.matchedTerm,
      ]
        .join(' ')
        .toLowerCase()
        .includes(searchText)
    return matchesWatchlist && matchesPlatform && matchesSeverity && matchesLayer && matchesSensitiveType && matchesKeyword
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

const platformOption = computed(() => ({
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
      data: summary.platformDistribution || [],
      itemStyle: {
        borderColor: '#08192f',
        borderWidth: 3,
      },
      label: { color: 'rgba(245, 250, 255, 0.92)' },
    },
  ],
}))

const typeOption = computed(() => ({
  grid: { left: 36, right: 16, top: 24, bottom: 18 },
  xAxis: { type: 'value', axisLabel: { color: 'rgba(216, 231, 255, 0.62)' }, splitLine: { lineStyle: { color: 'rgba(114, 149, 211, 0.14)' } } },
  yAxis: { type: 'category', data: (summary.sensitiveTypeTop || []).map((item) => item.name).reverse(), axisLabel: { color: 'rgba(216, 231, 255, 0.72)' } },
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  series: [
    {
      type: 'bar',
      data: (summary.sensitiveTypeTop || []).map((item) => item.value).reverse(),
      barWidth: 16,
      itemStyle: {
        borderRadius: [0, 10, 10, 0],
        color: '#3f93ff',
      },
    },
  ],
}))

const riskOption = computed(() => ({
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
      data: (summary.riskDistribution || []).map((item) => ({
        name: item.label || item.name,
        value: item.value,
      })),
      itemStyle: {
        borderColor: '#08192f',
        borderWidth: 3,
      },
      label: { color: 'rgba(245, 250, 255, 0.92)' },
    },
  ],
}))

function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
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

async function loadData() {
  loading.value = true
  try {
    const [summaryPayload, hitPayload, watchlistPayload] = await Promise.all([
      api.loadSummary(),
      api.loadHits({ limit: 300 }),
      api.loadWatchlists(),
    ])
    Object.assign(summary, summaryPayload || {})
    hits.value = Array.isArray(hitPayload) ? hitPayload : []
    watchlists.value = Array.isArray(watchlistPayload) ? watchlistPayload : []
  } catch (error) {
    ElMessage.error(error.message || '加载代码监测数据失败')
  } finally {
    loading.value = false
  }
}

async function runQuickScan() {
  const target = watchlists.value[0]
  if (!target?.id) {
    ElMessage.error('当前没有可用的代码监测对象')
    return
  }
  scanLoading.value = true
  try {
    await api.runScan(target.id, {
      platforms: target.platforms || [],
      file_extensions: target.file_extensions || [],
      search_page_limit: target.search_page_limit,
      max_results_per_term: target.max_results_per_term,
      detail_fetch: target.detail_fetch,
      enabled_rule_keys: target.enabled_rule_keys || [],
    })
    await loadData()
    ElMessage.success('代码扫描已执行')
  } catch (error) {
    ElMessage.error(error.message || '执行代码扫描失败')
  } finally {
    scanLoading.value = false
  }
}

function viewDetail(row) {
  router.push({
    name: 'CodeMonitoringDetail',
    params: { hitId: row.id },
  })
}

watch([filteredHits, pageSize], () => {
  const maxPage = Math.max(1, Math.ceil(filteredHits.value.length / pageSize.value))
  if (currentPage.value > maxPage) currentPage.value = maxPage
})

onMounted(loadData)
</script>

<style scoped lang="scss">
.monitor-shell {
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
  max-width: 760px;
  margin: 0;
  color: var(--ti-text-secondary);
}

.monitor-shell__actions,
.filter-row {
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
  grid-template-columns: 1fr 1fr;
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

.layer-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 72px;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.layer-pill--sensitive {
  background: rgba(229, 85, 87, 0.14);
  color: #d9363e;
}

.layer-pill--clue {
  background: rgba(38, 113, 220, 0.14);
  color: #1c6dd0;
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
