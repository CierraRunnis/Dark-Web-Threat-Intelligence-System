<template>
  <div class="ops-demo">
    <aside class="ops-sidebar">
      <router-link class="ops-brand" to="/ui-demo" aria-label="返回新版总览">
        <span class="ops-brand__mark"><el-icon><Aim /></el-icon></span>
        <span class="ops-brand__copy">
          <strong>DWTI</strong>
          <small>THREAT INTELLIGENCE</small>
        </span>
      </router-link>

      <nav class="ops-nav" aria-label="主要功能">
        <section v-for="section in navigation" :key="section.label" class="ops-nav__section">
          <span class="ops-nav__label">{{ section.label }}</span>
          <router-link
            v-for="item in section.items"
            :key="item.path"
            :to="item.path"
            class="ops-nav__item"
            :class="{
              'ops-nav__item--active': item.path === '/ui-demo',
              'ops-nav__item--mobile': item.mobile,
            }"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
            <small v-if="item.count !== undefined">{{ item.count }}</small>
          </router-link>
        </section>
      </nav>

      <div class="ops-sidebar__footer">
        <div class="ops-runtime">
          <span class="ops-runtime__dot" :class="{ 'ops-runtime__dot--warning': !jobsHealthy }" />
          <span>{{ jobsHealthy ? '采集链路在线' : jobsStatus }}</span>
        </div>
        <small>{{ versionLabel }}</small>
      </div>
    </aside>

    <section class="ops-workspace">
      <header class="ops-topbar">
        <div class="ops-topbar__title">
          <span>监测总览</span>
          <strong>情报运营工作台</strong>
        </div>

        <div class="ops-topbar__actions">
          <div class="ops-range" aria-label="趋势时间范围">
            <button
              v-for="range in ranges"
              :key="range.value"
              type="button"
              :class="{ active: selectedRange === range.value }"
              @click="selectedRange = range.value"
            >
              {{ range.label }}
            </button>
          </div>

          <el-tooltip content="刷新数据" placement="bottom">
            <button class="ops-icon-button" type="button" aria-label="刷新数据" :disabled="refreshing" @click="refreshAll">
              <el-icon :class="{ 'is-loading': refreshing }"><Refresh /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip content="返回现有界面" placement="bottom">
            <router-link class="ops-icon-button" to="/" aria-label="返回现有界面">
              <el-icon><House /></el-icon>
            </router-link>
          </el-tooltip>
          <div class="ops-account">
            <span class="ops-account__avatar">{{ userInitial }}</span>
            <span>{{ userName }}</span>
          </div>
        </div>
      </header>

      <main class="ops-content">
        <section class="ops-heading">
          <div>
            <span class="ops-eyebrow">REAL-TIME MONITORING</span>
            <h1>今日风险态势</h1>
            <p>过去 24 小时共纳入 {{ totalSignals }} 条公开线索，{{ highRiskSignals }} 条需要优先研判。</p>
          </div>
          <div class="ops-heading__status">
            <span>最近同步</span>
            <strong>{{ lastUpdatedLabel }}</strong>
          </div>
        </section>

        <section class="ops-metrics" aria-label="核心指标">
          <article v-for="(metric, index) in displayMetrics" :key="metric.label" class="ops-metric">
            <span class="ops-metric__icon" :class="`ops-metric__icon--${metric.tone}`">
              <el-icon><component :is="metric.icon || metricIcons[index]" /></el-icon>
            </span>
            <div>
              <span>{{ metric.label }}</span>
              <strong>{{ metric.value }}</strong>
            </div>
            <small>{{ metric.trend || metric.description || '较上一周期持平' }}</small>
          </article>
        </section>

        <div class="ops-dashboard-grid">
          <div class="ops-main-column">
            <section class="ops-panel ops-trend-panel">
              <header class="ops-panel__header">
                <div>
                  <span class="ops-panel__kicker">活动趋势</span>
                  <h2>跨模块风险变化</h2>
                </div>
                <span class="ops-panel__meta">{{ rangeLabel }}</span>
              </header>
              <v-chart class="ops-trend-chart" :option="trendOption" autoresize />
            </section>

            <section class="ops-panel ops-incidents">
              <header class="ops-panel__header">
                <div>
                  <span class="ops-panel__kicker">研判队列</span>
                  <h2>最新重点事件</h2>
                </div>
                <router-link class="ops-text-link" to="/threat-situation">
                  查看全部
                  <el-icon><ArrowRight /></el-icon>
                </router-link>
              </header>

              <div class="ops-incident-table">
                <div class="ops-incident-table__head" aria-hidden="true">
                  <span>风险</span>
                  <span>事件</span>
                  <span>模块</span>
                  <span>来源</span>
                  <span>时间</span>
                </div>
                <router-link
                  v-for="row in incidentRows"
                  :key="row.key"
                  :to="row.route"
                  class="ops-incident-row"
                >
                  <span class="ops-severity" :class="`ops-severity--${row.severity}`">{{ severityLabel(row.severity) }}</span>
                  <span class="ops-incident-row__title" :title="row.title">{{ row.title }}</span>
                  <span>{{ row.module }}</span>
                  <span class="ops-incident-row__source" :title="row.source">{{ row.source }}</span>
                  <time>{{ compactTime(row.time) }}</time>
                </router-link>
                <div v-if="!incidentRows.length" class="ops-empty">暂无待研判事件</div>
              </div>
            </section>
          </div>

          <aside class="ops-right-rail">
            <section class="ops-panel ops-distribution">
              <header class="ops-panel__header">
                <div>
                  <span class="ops-panel__kicker">风险构成</span>
                  <h2>情报类型分布</h2>
                </div>
              </header>
              <v-chart class="ops-distribution-chart" :option="distributionOption" autoresize />
            </section>

            <section class="ops-panel ops-collection">
              <header class="ops-panel__header">
                <div>
                  <span class="ops-panel__kicker">运行状态</span>
                  <h2>采集链路</h2>
                </div>
                <span class="ops-health" :class="{ 'ops-health--warning': !jobsHealthy }">{{ jobsStatus }}</span>
              </header>

              <div class="ops-job-stats">
                <div><span>运行中</span><strong>{{ jobs.running_jobs || 0 }}</strong></div>
                <div><span>异常挂起</span><strong>{{ jobs.stale_jobs || 0 }}</strong></div>
                <div><span>24h 失败</span><strong>{{ jobs.failed_jobs_24h || 0 }}</strong></div>
              </div>

              <div class="ops-site-list">
                <div v-for="site in siteHealth" :key="site.site_name" class="ops-site-row">
                  <span class="ops-site-row__dot" :class="siteTone(site)" />
                  <span>{{ site.site_name }}</span>
                  <small>{{ site.overall_status || '未知' }}</small>
                </div>
                <div v-if="!siteHealth.length" class="ops-empty ops-empty--compact">暂无站点状态</div>
              </div>

              <router-link class="ops-panel__action" to="/collector-control">
                进入采集控制
                <el-icon><ArrowRight /></el-icon>
              </router-link>
            </section>

            <section class="ops-panel ops-watchlist">
              <header class="ops-panel__header">
                <div>
                  <span class="ops-panel__kicker">人工跟踪</span>
                  <h2>重点线索</h2>
                </div>
                <span class="ops-panel__meta">{{ watchlist.length }}</span>
              </header>
              <div class="ops-watchlist__list">
                <article v-for="item in watchlist" :key="item.title">
                  <span :class="`ops-watchlist__marker ops-watchlist__marker--${item.tone || 'primary'}`" />
                  <div>
                    <small>{{ item.module }}</small>
                    <strong>{{ item.title }}</strong>
                  </div>
                </article>
              </div>
            </section>
          </aside>
        </div>
      </main>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import '@/lib/echarts'
import { useAuth } from '@/composables/useAuth'
import { useIntelligenceData } from '@/composables/useIntelligenceData'
import { useJobsData } from '@/composables/useJobsData'
import {
  attackTypeShare as fallbackAttackTypeShare,
  dashboardSummaryCards as fallbackSummaryCards,
  dashboardTrendSeries as fallbackTrendSeries,
  dashboardWatchlist as fallbackWatchlist,
  dataLeakEvents as fallbackDataLeakEvents,
  ransomwareEvents as fallbackRansomwareEvents,
  vulnerabilityEvents as fallbackVulnerabilityEvents,
} from '@/mock/intelligence'

const { state: authState } = useAuth()
const { data: intelligence, refresh: refreshIntelligence } = useIntelligenceData()
const { data: jobsState, refresh: refreshJobs } = useJobsData()

const selectedRange = ref('7d')
const refreshing = ref(false)
const versionLabel = ref('v0.11.1')

const ranges = [
  { label: '24H', value: '24h' },
  { label: '7D', value: '7d' },
  { label: '30D', value: '30d' },
]

const navigation = [
  {
    label: '情报研判',
    items: [
      { label: '监测总览', path: '/ui-demo', icon: 'Grid', mobile: true },
      { label: '勒索情报', path: '/ransomware', icon: 'Lock', mobile: true },
      { label: '数据泄露', path: '/data-leak', icon: 'Document', mobile: true },
      { label: '漏洞预警', path: '/vulnerability-alerts', icon: 'WarningFilled', mobile: true },
      { label: '威胁态势', path: '/threat-situation', icon: 'TrendCharts' },
    ],
  },
  {
    label: '监测任务',
    items: [
      { label: '采集控制', path: '/collector-control', icon: 'VideoPlay' },
      { label: '网盘监测', path: '/document-exposure/netdisk', icon: 'Share', mobile: true },
      { label: '文库监测', path: '/document-exposure/document-library', icon: 'Files' },
      { label: '代码监测', path: '/document-exposure/code-monitoring', icon: 'Connection' },
    ],
  },
]

const metricIcons = ['Bell', 'Lock', 'Document', 'WarningFilled']
const jobs = computed(() => jobsState.value || {})
const jobsStatus = computed(() => String(jobs.value.overall_status || '未知'))
const jobsHealthy = computed(() => ['正常', '运行中', '采集中', 'healthy', 'running'].some((status) => jobsStatus.value.toLowerCase().includes(status.toLowerCase())))
const userName = computed(() => authState.user?.display_name || authState.user?.username || '个人用户')
const userInitial = computed(() => userName.value.slice(0, 1))

const displayMetrics = computed(() => {
  const source = intelligence.value.dashboardSummaryCards?.length
    ? intelligence.value.dashboardSummaryCards
    : fallbackSummaryCards
  return source.filter((item) => item?.label !== '爬虫任务').slice(0, 4)
})

const trendSeries = computed(() => (
  intelligence.value.dashboardTrendSeries?.labels?.length
    ? intelligence.value.dashboardTrendSeries
    : fallbackTrendSeries
))

const vulnerabilityEvents = computed(() => (
  intelligence.value.vulnerabilityEvents?.length
    ? intelligence.value.vulnerabilityEvents
    : fallbackVulnerabilityEvents
))

const ransomwareEvents = computed(() => (
  intelligence.value.ransomwareEvents?.length
    ? intelligence.value.ransomwareEvents
    : fallbackRansomwareEvents
))

const dataLeakEvents = computed(() => (
  intelligence.value.dataLeakEvents?.length
    ? intelligence.value.dataLeakEvents
    : fallbackDataLeakEvents
))

const totalSignals = computed(() => (
  vulnerabilityEvents.value.length + ransomwareEvents.value.length + dataLeakEvents.value.length
))

const highRiskSignals = computed(() => incidentRows.value.filter((row) => ['critical', 'high'].includes(row.severity)).length)
const lastUpdatedLabel = computed(() => compactTime(jobs.value.updated_at) || '刚刚')
const rangeLabel = computed(() => ranges.find((range) => range.value === selectedRange.value)?.label || '7D')

const incidentRows = computed(() => {
  return [
    ...vulnerabilityEvents.value.map((item, index) => ({
      key: item.id || `vulnerability-${index}`,
      title: item.title || item.cveId || '漏洞预警',
      module: '漏洞预警',
      source: item.vendor || item.product || '公开漏洞源',
      severity: item.severity || (item.isExploited ? 'critical' : 'high'),
      time: item.disclosureTime || item.disclosure_time || '',
      route: '/vulnerability-alerts',
    })),
    ...ransomwareEvents.value.map((item, index) => ({
      key: item.id || `ransomware-${index}`,
      title: item.title || item.victim || '勒索事件',
      module: '勒索情报',
      source: item.attacker || item.sourceSite || '勒索站点',
      severity: item.severity || (Number(item.riskScore || 0) >= 75 ? 'critical' : 'high'),
      time: item.disclosureTime || item.disclosure_time || '',
      route: '/ransomware',
    })),
    ...dataLeakEvents.value.map((item, index) => ({
      key: item.id || `data-leak-${index}`,
      title: item.title || '数据泄露事件',
      module: '数据泄露',
      source: item.attacker || item.sourceSite || '公开论坛',
      severity: item.severity || (Number(item.riskScore || 0) >= 75 ? 'critical' : 'high'),
      time: item.disclosureTime || item.disclosure_time || '',
      route: '/data-leak',
    })),
  ]
    .sort((left, right) => String(right.time).localeCompare(String(left.time)))
    .slice(0, 8)
})

const watchlist = computed(() => {
  const source = intelligence.value.dashboardWatchlist?.length
    ? intelligence.value.dashboardWatchlist
    : fallbackWatchlist
  return source.slice(0, 4)
})

const siteHealth = computed(() => (jobs.value.site_health || []).slice(0, 5))

const trendOption = computed(() => {
  const source = trendSeries.value
  const start = selectedRange.value === '24h' ? Math.max(source.labels.length - 5, 0) : 0
  const labels = source.labels.slice(start)
  return {
    animationDuration: 500,
    color: ['#2563eb', '#f97316', '#dc2626', '#0f766e'],
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#111827',
      borderWidth: 0,
      textStyle: { color: '#ffffff', fontSize: 12 },
    },
    legend: {
      top: 0,
      right: 0,
      itemWidth: 10,
      itemHeight: 3,
      textStyle: { color: '#64748b', fontSize: 11 },
    },
    grid: { left: 8, right: 10, top: 42, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: true,
      data: labels,
      axisLine: { lineStyle: { color: '#d8dee8' } },
      axisTick: { show: false },
      axisLabel: { color: '#8491a3', fontSize: 11, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#8491a3', fontSize: 11 },
      splitLine: { lineStyle: { color: '#edf0f4' } },
    },
    series: [
      lineSeries('勒索披露', source.ransomware?.slice(start) || []),
      lineSeries('数据泄露', source.dataLeak?.slice(start) || []),
      lineSeries('漏洞预警', source.vulnerability?.slice(start) || []),
      {
        ...lineSeries('总体告警', source.threatAlerts?.slice(start) || []),
        areaStyle: { color: 'rgba(15, 118, 110, 0.08)' },
      },
    ],
  }
})

const distributionOption = computed(() => {
  const values = intelligence.value.attackTypeShare?.length
    ? intelligence.value.attackTypeShare
    : fallbackAttackTypeShare
  const rows = values.slice(0, 5).reverse()
  return {
    animationDuration: 500,
    grid: { left: 0, right: 18, top: 6, bottom: 0, containLabel: true },
    xAxis: {
      type: 'value',
      show: false,
      max: (value) => Math.ceil(value.max * 1.18),
    },
    yAxis: {
      type: 'category',
      data: rows.map((item) => item.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#536274', fontSize: 11 },
    },
    series: [{
      type: 'bar',
      data: rows.map((item, index) => ({
        value: item.value,
        itemStyle: { color: ['#64748b', '#0f766e', '#2563eb', '#f97316', '#dc2626'][index] },
      })),
      barWidth: 8,
      label: { show: true, position: 'right', color: '#334155', fontSize: 11 },
    }],
  }
})

function lineSeries(name, data) {
  return {
    name,
    type: 'line',
    data,
    smooth: 0.3,
    showSymbol: false,
    symbolSize: 6,
    lineStyle: { width: 2 },
    emphasis: { focus: 'series' },
  }
}

function severityLabel(severity) {
  return { critical: '严重', high: '高危', medium: '中危', low: '低危' }[severity] || '关注'
}

function compactTime(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  const matched = text.match(/(\d{2}:\d{2})(?::\d{2})?$/)
  if (matched) return matched[1]
  const dateMatched = text.match(/^\d{4}-(\d{2})-(\d{2})$/)
  if (dateMatched) return `${dateMatched[1]}-${dateMatched[2]}`
  return text.length > 16 ? text.slice(11, 16) : text
}

function siteTone(site) {
  const status = String(site.overall_status || '').toLowerCase()
  if (status.includes('正常') || status === 'healthy') return 'ops-site-row__dot--healthy'
  if (status.includes('运行')) return 'ops-site-row__dot--running'
  return 'ops-site-row__dot--warning'
}

async function refreshAll() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.all([refreshIntelligence(), refreshJobs()])
    ElMessage.success('数据已刷新')
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  try {
    const response = await fetch('/api/system/version')
    if (!response.ok) return
    const payload = await response.json()
    versionLabel.value = payload.current?.version || payload.current?.short_commit || versionLabel.value
  } catch {
    // Version metadata is secondary to the dashboard data.
  }
})
</script>

<style scoped lang="scss">
.ops-demo {
  --ops-bg: #f3f5f7;
  --ops-surface: #ffffff;
  --ops-sidebar: #15191f;
  --ops-border: #dfe4ea;
  --ops-border-soft: #edf0f3;
  --ops-text: #18212d;
  --ops-muted: #657284;
  --ops-blue: #2563eb;
  --ops-red: #dc2626;
  --ops-orange: #f97316;
  --ops-green: #0f766e;
  display: grid;
  grid-template-columns: 226px minmax(0, 1fr);
  width: 100%;
  height: 100vh;
  min-width: 0;
  overflow: hidden;
  background: var(--ops-bg);
  color: var(--ops-text);
  letter-spacing: 0;
}

.ops-sidebar {
  display: flex;
  min-width: 0;
  flex-direction: column;
  padding: 18px 12px 14px;
  overflow: hidden;
  background: var(--ops-sidebar);
  color: #d9e0e8;
}

.ops-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  height: 54px;
  padding: 0 9px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.ops-brand__mark {
  display: inline-flex;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  background: #f1f5f9;
  color: #111827;
  font-size: 19px;
}

.ops-brand__copy {
  display: grid;
  min-width: 0;
  line-height: 1.15;
}

.ops-brand__copy strong {
  color: #ffffff;
  font-size: 16px;
}

.ops-brand__copy small {
  margin-top: 4px;
  overflow: hidden;
  color: #8e99a8;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops-nav {
  flex: 1;
  min-height: 0;
  margin-top: 18px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.ops-nav__section + .ops-nav__section {
  margin-top: 22px;
}

.ops-nav__label {
  display: block;
  padding: 0 10px 7px;
  color: #737f8f;
  font-size: 10px;
  font-weight: 700;
}

.ops-nav__item {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  min-height: 40px;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border-radius: 6px;
  color: #aeb8c5;
  font-size: 13px;
  transition: background 0.18s ease, color 0.18s ease;
}

.ops-nav__item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #ffffff;
}

.ops-nav__item--active {
  background: #27303b;
  color: #ffffff;
  box-shadow: inset 3px 0 0 var(--ops-orange);
}

.ops-nav__item .el-icon {
  font-size: 16px;
}

.ops-nav__item small {
  color: #7f8b9a;
  font-family: var(--ti-font-mono);
  font-size: 10px;
}

.ops-sidebar__footer {
  display: grid;
  gap: 5px;
  padding: 14px 10px 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.ops-sidebar__footer > small {
  color: #737f8f;
  font-size: 10px;
}

.ops-runtime {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #c7d0da;
  font-size: 11px;
}

.ops-runtime__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.12);
}

.ops-runtime__dot--warning {
  background: var(--ops-orange);
  box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.14);
}

.ops-workspace {
  display: grid;
  min-width: 0;
  grid-template-rows: 66px minmax(0, 1fr);
  overflow: hidden;
}

.ops-topbar {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 24px;
  border-bottom: 1px solid var(--ops-border);
  background: rgba(255, 255, 255, 0.98);
}

.ops-topbar__title {
  display: grid;
  min-width: 0;
  line-height: 1.2;
}

.ops-topbar__title span {
  color: var(--ops-muted);
  font-size: 10px;
}

.ops-topbar__title strong {
  margin-top: 3px;
  overflow: hidden;
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops-topbar__actions {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.ops-range {
  display: inline-grid;
  grid-template-columns: repeat(3, 42px);
  height: 32px;
  padding: 2px;
  border: 1px solid var(--ops-border);
  border-radius: 6px;
  background: #f7f8fa;
}

.ops-range button {
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--ops-muted);
  cursor: pointer;
  font-size: 10px;
  font-weight: 700;
}

.ops-range button.active {
  background: #ffffff;
  color: var(--ops-text);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
}

.ops-icon-button {
  display: inline-flex;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--ops-border);
  border-radius: 6px;
  background: #ffffff;
  color: #475569;
  cursor: pointer;
}

.ops-icon-button:hover {
  border-color: #b8c1cc;
  color: var(--ops-blue);
}

.ops-icon-button:disabled {
  cursor: wait;
  opacity: 0.6;
}

.ops-icon-button .is-loading {
  animation: ops-spin 0.8s linear infinite;
}

.ops-account {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: 4px;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.ops-account__avatar {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #dbeafe;
  color: #1d4ed8;
}

.ops-content {
  min-width: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 24px;
}

.ops-heading {
  display: flex;
  min-width: 0;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
}

.ops-heading h1 {
  margin-top: 4px;
  font-size: 24px;
  line-height: 1.25;
}

.ops-heading p {
  margin-top: 6px;
  color: var(--ops-muted);
  font-size: 12px;
}

.ops-eyebrow,
.ops-panel__kicker {
  color: var(--ops-orange);
  font-size: 9px;
  font-weight: 800;
}

.ops-heading__status {
  display: grid;
  flex: 0 0 auto;
  justify-items: end;
  color: var(--ops-muted);
  font-size: 10px;
}

.ops-heading__status strong {
  margin-top: 3px;
  color: #334155;
  font-family: var(--ti-font-mono);
  font-size: 11px;
}

.ops-metrics {
  display: grid;
  min-width: 0;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 16px;
  border: 1px solid var(--ops-border);
  border-radius: 8px;
  background: var(--ops-surface);
}

.ops-metric {
  display: grid;
  min-width: 0;
  grid-template-columns: 34px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
}

.ops-metric + .ops-metric {
  border-left: 1px solid var(--ops-border-soft);
}

.ops-metric__icon {
  display: inline-flex;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: #e8eefc;
  color: var(--ops-blue);
}

.ops-metric__icon--danger {
  background: #fee2e2;
  color: var(--ops-red);
}

.ops-metric__icon--warning {
  background: #ffedd5;
  color: var(--ops-orange);
}

.ops-metric__icon--success {
  background: #ccfbf1;
  color: var(--ops-green);
}

.ops-metric div {
  display: grid;
  min-width: 0;
}

.ops-metric div span {
  overflow: hidden;
  color: var(--ops-muted);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops-metric strong {
  margin-top: 2px;
  font-family: var(--ti-font-mono);
  font-size: 22px;
  line-height: 1.2;
}

.ops-metric > small {
  grid-column: 2;
  overflow: hidden;
  color: #7b8797;
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops-dashboard-grid {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) 306px;
  align-items: start;
  gap: 16px;
}

.ops-main-column,
.ops-right-rail {
  display: grid;
  min-width: 0;
  align-content: start;
  gap: 16px;
}

.ops-panel {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--ops-border);
  border-radius: 8px;
  background: var(--ops-surface);
}

.ops-panel__header {
  display: flex;
  min-width: 0;
  min-height: 56px;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 11px 15px;
  border-bottom: 1px solid var(--ops-border-soft);
}

.ops-panel__header > div {
  min-width: 0;
}

.ops-panel__header h2 {
  margin-top: 2px;
  overflow: hidden;
  font-size: 14px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops-panel__meta {
  flex: 0 0 auto;
  color: var(--ops-muted);
  font-family: var(--ti-font-mono);
  font-size: 10px;
}

.ops-trend-chart {
  width: 100%;
  height: 264px;
  padding: 8px 12px 12px;
}

.ops-distribution-chart {
  width: 100%;
  height: 180px;
  padding: 10px 12px 14px;
}

.ops-text-link,
.ops-panel__action {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;
  color: var(--ops-blue);
  font-size: 10px;
  font-weight: 700;
}

.ops-incident-table {
  min-width: 0;
}

.ops-incident-table__head,
.ops-incident-row {
  display: grid;
  min-width: 0;
  grid-template-columns: 58px minmax(180px, 1.7fr) 82px minmax(82px, 0.7fr) 54px;
  align-items: center;
  gap: 10px;
}

.ops-incident-table__head {
  min-height: 34px;
  padding: 0 15px;
  background: #f8f9fb;
  color: #8491a3;
  font-size: 9px;
  font-weight: 700;
}

.ops-incident-row {
  min-height: 48px;
  padding: 7px 15px;
  border-top: 1px solid var(--ops-border-soft);
  color: #536274;
  font-size: 10px;
  transition: background 0.16s ease;
}

.ops-incident-table__head + .ops-incident-row {
  border-top: 0;
}

.ops-incident-row:hover {
  background: #f8fafc;
}

.ops-incident-row__title,
.ops-incident-row__source {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops-incident-row__title {
  color: #263445;
  font-size: 11px;
  font-weight: 650;
}

.ops-incident-row time {
  color: #8491a3;
  font-family: var(--ti-font-mono);
}

.ops-severity {
  display: inline-flex;
  width: 42px;
  height: 20px;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  font-size: 9px;
  font-weight: 700;
}

.ops-severity--critical {
  background: #fee2e2;
  color: #b91c1c;
}

.ops-severity--high {
  background: #ffedd5;
  color: #c2410c;
}

.ops-severity--medium {
  background: #fef3c7;
  color: #a16207;
}

.ops-severity--low {
  background: #d1fae5;
  color: #047857;
}

.ops-health {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  color: var(--ops-green);
  font-size: 10px;
  font-weight: 700;
}

.ops-health::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.ops-health--warning {
  color: var(--ops-orange);
}

.ops-job-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  padding: 12px 14px;
  border-bottom: 1px solid var(--ops-border-soft);
}

.ops-job-stats div {
  display: grid;
  gap: 3px;
  text-align: center;
}

.ops-job-stats div + div {
  border-left: 1px solid var(--ops-border-soft);
}

.ops-job-stats span {
  color: var(--ops-muted);
  font-size: 9px;
}

.ops-job-stats strong {
  font-family: var(--ti-font-mono);
  font-size: 16px;
}

.ops-site-list {
  padding: 7px 14px;
}

.ops-site-row {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  min-height: 30px;
  align-items: center;
  gap: 7px;
  color: #405064;
  font-size: 10px;
}

.ops-site-row + .ops-site-row {
  border-top: 1px solid var(--ops-border-soft);
}

.ops-site-row__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.ops-site-row__dot--healthy {
  background: #16a34a;
}

.ops-site-row__dot--running {
  background: var(--ops-blue);
}

.ops-site-row__dot--warning {
  background: var(--ops-orange);
}

.ops-site-row small {
  color: #8491a3;
  font-size: 9px;
}

.ops-panel__action {
  width: 100%;
  min-height: 38px;
  justify-content: center;
  border-top: 1px solid var(--ops-border-soft);
}

.ops-watchlist__list {
  padding: 5px 14px 9px;
}

.ops-watchlist article {
  display: grid;
  grid-template-columns: 4px minmax(0, 1fr);
  align-items: stretch;
  gap: 9px;
  padding: 8px 0;
}

.ops-watchlist article + article {
  border-top: 1px solid var(--ops-border-soft);
}

.ops-watchlist__marker {
  width: 3px;
  min-height: 30px;
  border-radius: 2px;
  background: var(--ops-blue);
}

.ops-watchlist__marker--danger {
  background: var(--ops-red);
}

.ops-watchlist__marker--warning {
  background: var(--ops-orange);
}

.ops-watchlist__marker--success {
  background: var(--ops-green);
}

.ops-watchlist article div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.ops-watchlist article small {
  color: var(--ops-muted);
  font-size: 9px;
}

.ops-watchlist article strong {
  display: -webkit-box;
  overflow: hidden;
  color: #334155;
  font-size: 10px;
  font-weight: 650;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.ops-empty {
  display: grid;
  min-height: 90px;
  place-items: center;
  color: #94a3b8;
  font-size: 11px;
}

.ops-empty--compact {
  min-height: 48px;
}

@keyframes ops-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1240px) {
  .ops-dashboard-grid {
    grid-template-columns: minmax(0, 1fr) 280px;
  }

  .ops-incident-table__head,
  .ops-incident-row {
    grid-template-columns: 58px minmax(170px, 1fr) 76px 48px;
  }

  .ops-incident-table__head span:nth-child(4),
  .ops-incident-row__source {
    display: none;
  }
}

@media (max-width: 1024px) {
  .ops-demo {
    grid-template-columns: 74px minmax(0, 1fr);
  }

  .ops-sidebar {
    padding-left: 8px;
    padding-right: 8px;
  }

  .ops-brand {
    justify-content: center;
    padding: 0;
  }

  .ops-brand__copy,
  .ops-nav__label,
  .ops-nav__item span,
  .ops-nav__item small,
  .ops-sidebar__footer span:not(.ops-runtime__dot),
  .ops-sidebar__footer > small {
    display: none;
  }

  .ops-nav__item {
    display: flex;
    width: 42px;
    min-height: 40px;
    justify-content: center;
    margin: 0 auto;
    padding: 8px;
  }

  .ops-nav__section + .ops-nav__section {
    margin-top: 14px;
  }

  .ops-sidebar__footer {
    justify-items: center;
    padding-left: 0;
    padding-right: 0;
  }

  .ops-dashboard-grid {
    grid-template-columns: 1fr;
  }

  .ops-right-rail {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .ops-demo {
    display: block;
    height: 100vh;
    padding-bottom: 64px;
  }

  .ops-sidebar {
    position: fixed;
    z-index: 50;
    right: 0;
    bottom: 0;
    left: 0;
    display: block;
    height: 64px;
    padding: 6px 8px;
    border-top: 1px solid #2b3139;
  }

  .ops-brand,
  .ops-nav__label,
  .ops-sidebar__footer,
  .ops-nav__item:not(.ops-nav__item--mobile) {
    display: none;
  }

  .ops-nav {
    display: flex;
    height: 100%;
    margin: 0;
    overflow: hidden;
  }

  .ops-nav__section {
    display: contents;
  }

  .ops-nav__item--mobile {
    display: flex;
    width: auto;
    min-width: 0;
    height: 52px;
    flex: 1 1 0;
    flex-direction: column;
    justify-content: center;
    gap: 3px;
    margin: 0;
    padding: 4px 2px;
    font-size: 8px;
  }

  .ops-nav__item--mobile span {
    display: block;
    width: 100%;
    overflow: hidden;
    text-align: center;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ops-nav__item--mobile .el-icon {
    font-size: 17px;
  }

  .ops-workspace {
    height: calc(100vh - 64px);
    grid-template-rows: 58px minmax(0, 1fr);
  }

  .ops-topbar {
    padding: 0 12px;
  }

  .ops-range,
  .ops-account span:last-child,
  .ops-topbar__title span {
    display: none;
  }

  .ops-content {
    padding: 14px;
  }

  .ops-heading {
    align-items: flex-start;
  }

  .ops-heading h1 {
    font-size: 20px;
  }

  .ops-heading p {
    max-width: 34ch;
  }

  .ops-heading__status {
    display: none;
  }

  .ops-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .ops-metric:nth-child(3) {
    border-left: 0;
  }

  .ops-metric:nth-child(n + 3) {
    border-top: 1px solid var(--ops-border-soft);
  }

  .ops-right-rail {
    grid-template-columns: 1fr;
  }

  .ops-incident-table__head {
    display: none;
  }

  .ops-incident-row {
    grid-template-columns: 48px minmax(0, 1fr) 44px;
    min-height: 54px;
  }

  .ops-incident-row > span:nth-child(3),
  .ops-incident-row__source {
    display: none;
  }
}

@media (max-width: 420px) {
  .ops-metric {
    padding: 12px 10px;
  }

  .ops-metric__icon {
    width: 28px;
    height: 28px;
  }

  .ops-metric strong {
    font-size: 18px;
  }
}
</style>
