<template>
  <div class="dashboard-page ti-page">
    <section class="situation-toolbar ti-reveal-up">
      <div>
        <span class="situation-toolbar__eyebrow">实时威胁态势</span>
        <h1>威胁情报总览</h1>
      </div>
      <div class="situation-range" aria-label="趋势时间范围">
        <button
          v-for="range in dashboardRanges"
          :key="range.value"
          type="button"
          :class="{ active: dashboardRange === range.value }"
          @click="dashboardRange = range.value"
        >
          {{ range.label }}
        </button>
      </div>
    </section>

    <section class="situation-status ti-reveal-up">
      <p>基于现有情报库实时生成的威胁情报视图。</p>
      <div class="situation-status__metrics">
        <span>监测区域 <strong>{{ regionRankings.length }}</strong></span>
        <span>重点行业 <strong>{{ industryImpact.length }}</strong></span>
        <span>待研判线索 <strong>{{ pendingClueCount }}</strong></span>
        <el-button link type="primary" :loading="loading" @click="refresh">
          <el-icon><Refresh /></el-icon>
          刷新总览
        </el-button>
      </div>
    </section>

    <section class="situation-kpis">
      <article
        v-for="(card, index) in kpiCards"
        :key="card.label"
        class="situation-kpi ti-reveal-up"
      >
        <header>
          <span>{{ card.label }}</span>
          <em :class="`situation-kpi__tag--${card.tone || 'primary'}`">{{ card.change || card.trend || card.helper || '实时更新' }}</em>
        </header>
        <strong>{{ card.value }}</strong>
        <svg viewBox="0 0 180 34" preserveAspectRatio="none" aria-hidden="true">
          <polyline :points="sparklinePoints(card.series, index)" />
        </svg>
        <i aria-hidden="true"></i>
      </article>
    </section>

    <section class="situation-main">
      <article class="situation-panel situation-map-panel ti-reveal-up">
        <header class="situation-panel__header">
          <div>
            <small>威胁地理态势</small>
            <h2>{{ activeRangeLabel }}地域分布</h2>
          </div>
          <span class="situation-live"><i></i> 实时情报</span>
        </header>

        <div class="situation-map-layout">
          <div class="situation-map">
            <img src="/assets/world-map.svg" alt="世界区域分布图" />
            <span
              v-for="(region, index) in regionRankings.slice(0, 5)"
              :key="region.name"
              class="situation-map__marker"
              :style="markerPosition(index)"
            >
              <i></i>
              <b>{{ region.name }} · {{ region.value }}</b>
            </span>
          </div>

          <div class="region-ranking">
            <div class="region-ranking__head">
              <span>区域</span>
              <span>事件数</span>
            </div>
            <div v-for="region in regionRankings.slice(0, 6)" :key="region.name" class="region-ranking__row">
              <span>{{ region.name }}</span>
              <i><em :style="{ width: regionPercent(region.value) }"></em></i>
              <strong>{{ region.value }}</strong>
            </div>
          </div>
        </div>

        <footer class="situation-map-panel__foot">
          <span><i></i> 数据来自{{ activeRangeLabel }}跨模块情报</span>
          <span>综合风险指数 <strong>{{ riskIndex }}</strong></span>
        </footer>
      </article>

      <article class="situation-panel situation-focus ti-reveal-up">
        <header class="situation-panel__header">
          <div>
            <small>分析队列</small>
            <h2>当前关注点</h2>
          </div>
          <span class="situation-focus__count">{{ dashboardWatchlist.length }}</span>
        </header>

        <div class="situation-focus__list">
          <article v-for="item in dashboardWatchlist" :key="item.title">
            <span :class="`situation-focus__icon situation-focus__icon--${item.tone || 'danger'}`">
              <el-icon><DataAnalysis /></el-icon>
            </span>
            <div>
              <h3>{{ item.title }}</h3>
              <p>{{ item.module }} · {{ item.note }}</p>
            </div>
            <strong>{{ item.level }}</strong>
          </article>
        </div>

        <router-link class="situation-focus__action" to="/threat-situation">
          <span>进入威胁态势研判</span>
          <el-icon><Right /></el-icon>
        </router-link>
      </article>
    </section>

    <section class="situation-analysis">
      <article class="situation-panel situation-chart ti-reveal-up">
        <header class="situation-panel__header">
          <div>
            <small>趋势研判</small>
            <h2>跨模块趋势概览</h2>
          </div>
          <span>{{ activeRangeLabel }}</span>
        </header>
        <v-chart class="dashboard-chart" :option="overviewTrendOption" autoresize />
      </article>

      <article class="situation-panel situation-chart ti-reveal-up">
        <header class="situation-panel__header">
          <div>
            <small>情报构成</small>
            <h2>情报类型分布</h2>
          </div>
        </header>
        <v-chart class="dashboard-chart" :option="distributionOption" autoresize />
      </article>

      <article class="situation-panel situation-industry ti-reveal-up">
        <header class="situation-panel__header">
          <div>
            <small>行业暴露</small>
            <h2>重点行业排行</h2>
          </div>
        </header>
        <div class="situation-industry__list">
          <div v-for="(item, index) in industryImpact.slice(0, 6)" :key="item.name">
            <b>{{ String(index + 1).padStart(2, '0') }}</b>
            <span>{{ item.name }}</span>
            <i><em :style="{ width: industryPercent(item.value) }"></em></i>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
      </article>
    </section>

    <section class="module-preview">
      <SectionHeader eyebrow="模块重点" title="核心模块预览" />

      <div class="module-preview__grid">
        <router-link
          v-for="module in modulePreviewCards"
          :key="module.route"
          :to="module.route"
          :class="['module-preview__card', `module-preview__card--${module.tone}`, 'ti-reveal-up']"
        >
          <div class="module-preview__card-top">
            <span class="ti-kicker">{{ module.eyebrow }}</span>
            <StatusBadge :label="module.highlight" :tone="module.tone" :dot="false" />
          </div>
          <h3>{{ module.title }}</h3>
          <p>{{ module.summary }}</p>
          <div class="module-preview__stats">
            <div v-for="stat in module.stats" :key="stat.label">
              <span>{{ stat.label }}</span>
              <strong>{{ stat.value }}</strong>
            </div>
          </div>
          <div class="module-preview__footer">
            <span>进入模块页</span>
            <el-icon><Right /></el-icon>
          </div>
        </router-link>
      </div>
    </section>

    <section class="dashboard-bottom ti-page-grid">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">
            <el-icon><Connection /></el-icon>
            跨模块事件时间线
          </div>
          <StatusBadge :label="activeRangeLabel" tone="primary" :dot="false" />
        </div>
        <div class="ti-card-body">
          <div class="timeline-list">
            <article
              v-for="item in crossModuleTimeline"
              :key="`${item.time}-${item.title}`"
              class="timeline-list__item"
            >
              <div class="timeline-list__time">{{ item.time }}</div>
              <div class="timeline-list__content">
                <StatusBadge :label="item.module" :tone="item.tone" />
                <h3>{{ item.title }}</h3>
                <p>{{ item.detail }}</p>
              </div>
            </article>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { Connection, DataAnalysis, Refresh, Right } from '@element-plus/icons-vue'
import '@/lib/echarts'
import SectionHeader from '@/components/common/SectionHeader.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useIntelligenceData } from '@/composables/useIntelligenceData'

const { data, loading, refresh } = useIntelligenceData()
const dashboardRange = ref('7d')
const dashboardRanges = [
  { label: '今日', value: 'today' },
  { label: '近7天', value: '7d' },
  { label: '近30天', value: '30d' },
]
const dashboardSummaryCards = computed(() => data.value.dashboardSummaryCards || [])
const baseModulePreviewCards = computed(() => data.value.modulePreviewCards || [])
const sourceRansomwareEvents = computed(() => data.value.ransomwareEvents || [])
const sourceDataLeakEvents = computed(() => data.value.dataLeakEvents || [])
const sourceVulnerabilityEvents = computed(() => data.value.vulnerabilityEvents || [])
const sourceDocumentEvents = computed(() => data.value.documentExposureEvents || [])

const DAY_MS = 24 * 60 * 60 * 1000
const SHANGHAI_OFFSET_MS = 8 * 60 * 60 * 1000

function eventDateValue(item) {
  return item?.updatedTimeRaw
    || item?.updated_time_raw
    || item?.lastSeenAt
    || item?.firstSeenAt
    || item?.disclosureTimeRaw
    || item?.disclosure_time_raw
    || item?.disclosureTime
    || item?.disclosure_time
    || item?.disclosureDate
    || ''
}

function eventTimestamp(item) {
  const timestamp = Date.parse(eventDateValue(item))
  return Number.isFinite(timestamp) ? timestamp : Number.NaN
}

function selectedRangeStart(days, now = Date.now()) {
  const shanghaiNow = new Date(now + SHANGHAI_OFFSET_MS)
  const todayStart = Date.UTC(
    shanghaiNow.getUTCFullYear(),
    shanghaiNow.getUTCMonth(),
    shanghaiNow.getUTCDate(),
  ) - SHANGHAI_OFFSET_MS
  return todayStart - (Math.max(1, Number(days) || 1) - 1) * DAY_MS
}

function filterEventsByDays(items, days, now = Date.now()) {
  const start = selectedRangeStart(days, now)
  return (items || []).filter((item) => {
    const timestamp = eventTimestamp(item)
    return Number.isFinite(timestamp) && timestamp >= start && timestamp <= now
  })
}

function formatDayLabel(timestamp) {
  const date = new Date(timestamp + SHANGHAI_OFFSET_MS)
  return `${String(date.getUTCMonth() + 1).padStart(2, '0')}-${String(date.getUTCDate()).padStart(2, '0')}`
}

function buildDailySeries(items, days, uniqueGetter = null) {
  const now = Date.now()
  const start = selectedRangeStart(days, now)
  const labels = Array.from({ length: days }, (_, index) => formatDayLabel(start + index * DAY_MS))
  const values = Array.from({ length: days }, () => 0)
  const uniqueBuckets = uniqueGetter ? Array.from({ length: days }, () => new Set()) : null

  for (const item of items || []) {
    const timestamp = eventTimestamp(item)
    const index = Math.floor((timestamp - start) / DAY_MS)
    if (!Number.isFinite(timestamp) || index < 0 || index >= days) continue
    if (!uniqueGetter) {
      values[index] += 1
      continue
    }
    const key = String(uniqueGetter(item) || '').trim()
    if (key) uniqueBuckets[index].add(key)
  }

  return {
    labels,
    values: uniqueBuckets ? uniqueBuckets.map((bucket) => bucket.size) : values,
  }
}

function usableDimension(value) {
  const text = String(value || '').trim()
  return text && !['未知', 'unknown', 'Unknown', '—'].includes(text) ? text : ''
}

function eventRegion(item) {
  return usableDimension(item?.country) || usableDimension(item?.region)
}

function eventIndustry(item) {
  return usableDimension(item?.industry)
}

function eventSeverity(item) {
  const raw = String(item?.severity || '').toLowerCase()
  if (['critical', '严重'].includes(raw)) return 'critical'
  if (['high', '高危'].includes(raw)) return 'high'
  if (['medium', '中危'].includes(raw)) return 'medium'
  if (['low', '低危'].includes(raw)) return 'low'
  const score = Number(item?.riskScore ?? item?.risk_score ?? 0)
  if (score >= 90) return 'critical'
  if (score >= 70) return 'high'
  if (score >= 40) return 'medium'
  return 'low'
}

function severityTone(item) {
  return { critical: 'danger', high: 'danger', medium: 'warning', low: 'primary' }[eventSeverity(item)]
}

function severityLabel(item) {
  return { critical: '严重', high: '高危', medium: '中危', low: '关注' }[eventSeverity(item)]
}

function countByName(items, getter) {
  const counts = new Map()
  for (const item of items || []) {
    const name = usableDimension(getter(item))
    if (!name) continue
    counts.set(name, (counts.get(name) || 0) + 1)
  }
  return [...counts]
    .map(([name, value]) => ({ name, value }))
    .sort((left, right) => right.value - left.value || left.name.localeCompare(right.name, 'zh-CN'))
}

function uniqueCount(items, getter) {
  return new Set((items || []).map(getter).map(usableDimension).filter(Boolean)).size
}

function eventNote(item) {
  return [
    eventRegion(item),
    eventIndustry(item),
    usableDimension(item?.category),
  ].filter(Boolean).join(' · ') || '本期新增情报'
}

function formatTimelineTime(item, days) {
  const timestamp = eventTimestamp(item)
  if (!Number.isFinite(timestamp)) return '--:--'
  return new Intl.DateTimeFormat('zh-CN', days === 1
    ? { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }
    : { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' }
  ).format(new Date(timestamp)).replace('/', '-')
}

function withPeriodStats(card, highlight, stats) {
  return {
    ...card,
    highlight,
    stats: stats.map(([label, value]) => ({ label, value: String(value) })),
  }
}

const selectedDays = computed(() => ({ today: 1, '7d': 7, '30d': 30 }[dashboardRange.value] || 7))
const activeRangeLabel = computed(() => dashboardRanges.find((item) => item.value === dashboardRange.value)?.label || '近7天')

const periodEventGroups = computed(() => {
  const days = selectedDays.value
  return {
    ransomware: filterEventsByDays(sourceRansomwareEvents.value, days),
    dataLeak: filterEventsByDays(sourceDataLeakEvents.value, days),
    vulnerability: filterEventsByDays(sourceVulnerabilityEvents.value, days),
    document: filterEventsByDays(sourceDocumentEvents.value, days),
  }
})

const periodEventEntries = computed(() => {
  const groups = periodEventGroups.value
  return [
    ...groups.dataLeak.map((event) => ({ event, module: '数据泄露' })),
    ...groups.ransomware.map((event) => ({ event, module: '勒索情报' })),
    ...groups.vulnerability.map((event) => ({ event, module: '漏洞预警' })),
    ...groups.document.map((event) => ({ event, module: '文件监测' })),
  ]
})

const periodEvents = computed(() => periodEventEntries.value.map((item) => item.event))

const rangedTrend = computed(() => {
  const groups = periodEventGroups.value
  const days = selectedDays.value
  const dataLeak = buildDailySeries(groups.dataLeak, days)
  const ransomware = buildDailySeries(groups.ransomware, days)
  const vulnerability = buildDailySeries(groups.vulnerability, days)
  const document = buildDailySeries(groups.document, days)
  const affectedEntities = buildDailySeries(
    [...groups.dataLeak, ...groups.ransomware],
    days,
    (item) => item.victim || item.title,
  )
  return {
    labels: dataLeak.labels,
    ransomware: ransomware.values,
    dataLeak: dataLeak.values,
    vulnerability: vulnerability.values,
    affectedEntities: affectedEntities.values,
    threatAlerts: dataLeak.values.map((value, index) => (
      value + ransomware.values[index] + vulnerability.values[index] + document.values[index]
    )),
  }
})

const visibleDashboardSummaryCards = computed(() =>
  dashboardSummaryCards.value.filter((card) => card?.label !== '爬虫任务').slice(0, 4)
)

const kpiCards = computed(() => {
  const groups = periodEventGroups.value
  const topLeakType = countByName(groups.dataLeak, (item) => item.category)[0]
  const actorCount = uniqueCount(groups.ransomware, (item) => item.attacker)
  const impactedCount = uniqueCount(
    [...groups.dataLeak, ...groups.ransomware],
    (item) => item.victim || item.title,
  )
  const exploitedCount = groups.vulnerability.filter((item) => item.isExploited || item.is_exploited).length
  const metrics = [
    {
      value: groups.dataLeak.length,
      change: topLeakType ? `${topLeakType.name} ${topLeakType.value} 条` : '本期无新增',
      series: rangedTrend.value.dataLeak,
    },
    {
      value: groups.ransomware.length,
      change: `${actorCount} 个活跃团伙`,
      series: rangedTrend.value.ransomware,
    },
    {
      value: impactedCount,
      change: `${uniqueCount(periodEvents.value, eventRegion)} 个涉及地区`,
      series: rangedTrend.value.affectedEntities,
    },
    {
      value: groups.vulnerability.length,
      change: `${exploitedCount} 条已被利用`,
      series: rangedTrend.value.vulnerability,
    },
  ]
  return visibleDashboardSummaryCards.value.map((card, index) => ({
    ...card,
    value: String(metrics[index]?.value || 0),
    change: metrics[index]?.change || '本期无新增',
    series: metrics[index]?.series || [],
  }))
})

const regionRankings = computed(() => countByName(periodEvents.value, eventRegion).slice(0, 6))
const industryImpact = computed(() => countByName(periodEvents.value, eventIndustry).slice(0, 6))
const sensitiveTypeShare = computed(() => {
  const groups = periodEventGroups.value
  return [
    { name: '数据泄露', value: groups.dataLeak.length },
    { name: '勒索情报', value: groups.ransomware.length },
    { name: '漏洞预警', value: groups.vulnerability.length },
    { name: '文件监测', value: groups.document.length },
  ]
})
const pendingClueCount = computed(() => periodEvents.value.filter((item) => ['critical', 'high'].includes(eventSeverity(item))).length)

const dashboardWatchlist = computed(() => [...periodEventEntries.value]
  .sort((left, right) => (
    Number(right.event.priorityScore ?? right.event.riskScore ?? 0)
      - Number(left.event.priorityScore ?? left.event.riskScore ?? 0)
    || eventTimestamp(right.event) - eventTimestamp(left.event)
  ))
  .slice(0, 4)
  .map(({ event, module }) => ({
    module,
    title: event.title || event.cveId || event.victim || '未命名情报',
    note: eventNote(event),
    tone: severityTone(event),
    level: severityLabel(event),
  })))

const crossModuleTimeline = computed(() => [...periodEventEntries.value]
  .sort((left, right) => eventTimestamp(right.event) - eventTimestamp(left.event))
  .slice(0, 8)
  .map(({ event, module }) => ({
    time: formatTimelineTime(event, selectedDays.value),
    module,
    title: event.title || event.cveId || event.victim || '未命名情报',
    detail: eventNote(event),
    tone: severityTone(event),
  })))

const modulePreviewCards = computed(() => {
  const groups = periodEventGroups.value
  const all = periodEvents.value
  const periodLabel = activeRangeLabel.value
  return baseModulePreviewCards.value.map((card) => {
    if (card.route === '/ransomware') {
      const actorCount = uniqueCount(groups.ransomware, (item) => item.attacker)
      const publishedCount = groups.ransomware.filter((item) => item.category === '已公开').length
      return withPeriodStats(card, `${periodLabel} ${groups.ransomware.length} 条受害者记录`, [
        ['受害者', groups.ransomware.length],
        ['来源数', actorCount],
        ['已公开', publishedCount],
      ])
    }
    if (card.route === '/data-leak') {
      return withPeriodStats(card, `${periodLabel} ${groups.dataLeak.length} 条泄露事件`, [
        ['事件数', groups.dataLeak.length],
        ['类型数', uniqueCount(groups.dataLeak, (item) => item.category)],
        ['地区数', uniqueCount(groups.dataLeak, eventRegion)],
      ])
    }
    if (card.route?.startsWith('/document-exposure')) {
      const highRiskCount = groups.document.filter((item) => ['critical', 'high'].includes(eventSeverity(item))).length
      return withPeriodStats(card, `${periodLabel} ${highRiskCount} 条高风险命中`, [
        ['命中数', groups.document.length],
        ['高风险', highRiskCount],
        ['平台数', uniqueCount(groups.document, (item) => item.platform || item.sourceSite || item.source_kind)],
      ])
    }
    if (card.route === '/vulnerability-alerts') {
      const exploitedCount = groups.vulnerability.filter((item) => item.isExploited || item.is_exploited).length
      return withPeriodStats(card, `${periodLabel} ${exploitedCount} 条已被利用`, [
        ['漏洞数', groups.vulnerability.length],
        ['厂商数', uniqueCount(groups.vulnerability, (item) => item.vendor)],
        ['已利用', exploitedCount],
      ])
    }
    if (card.route === '/threat-situation') {
      const highRiskCount = all.filter((item) => ['critical', 'high'].includes(eventSeverity(item))).length
      return withPeriodStats(card, `${periodLabel} ${highRiskCount} 条高风险情报`, [
        ['事件数', all.length],
        ['高风险', highRiskCount],
        ['地域数', uniqueCount(all, eventRegion)],
      ])
    }
    return withPeriodStats(card, `${periodLabel} 暂无周期数据`, (card.stats || []).map((item) => [item.label, 0]))
  })
})

const maxRegionValue = computed(() => Math.max(1, ...regionRankings.value.map((item) => Number(item.value) || 0)))
const maxIndustryValue = computed(() => Math.max(1, ...industryImpact.value.map((item) => Number(item.value) || 0)))
const riskIndex = computed(() => {
  const scores = periodEvents.value.map((item) => Number(item.riskScore ?? item.risk_score ?? 0))
  if (!scores.length) return 0
  return Math.min(99, Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length))
})
const overviewTrendOption = computed(() => ({
  color: ['#2d5dff', '#e88030', '#8a3ffc', '#0f766e'],
  tooltip: {
    trigger: 'axis',
    backgroundColor: 'rgba(255, 253, 250, 0.96)',
    borderColor: 'rgba(63, 80, 104, 0.12)',
    textStyle: { color: '#1e2735' },
  },
  legend: {
    bottom: 0,
    textStyle: { color: '#536074' },
  },
  grid: { left: 10, right: 16, top: 16, bottom: 38, containLabel: true },
  xAxis: {
    type: 'category',
    data: rangedTrend.value.labels,
    axisLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.16)' } },
    axisLabel: { color: '#7f8898' },
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } },
    axisLabel: { color: '#7f8898' },
  },
  series: [
    {
      name: '勒索披露',
      type: 'line',
      smooth: true,
      symbolSize: 8,
      data: rangedTrend.value.ransomware,
    },
    {
      name: '数据泄露',
      type: 'line',
      smooth: true,
      symbolSize: 8,
      data: rangedTrend.value.dataLeak,
    },
    {
      name: '漏洞预警',
      type: 'line',
      smooth: true,
      symbolSize: 8,
      data: rangedTrend.value.vulnerability,
      lineStyle: { color: '#8a3ffc' },
      itemStyle: { color: '#8a3ffc' },
    },
    {
      name: '总体告警',
      type: 'line',
      smooth: true,
      symbolSize: 8,
      data: rangedTrend.value.threatAlerts,
      lineStyle: { color: '#0f766e' },
      itemStyle: { color: '#0f766e' },
      areaStyle: { color: 'rgba(15, 118, 110, 0.08)' },
    },
  ],
}))

const distributionOption = computed(() => ({
  color: ['#ef3846', '#f19a00', '#078eea', '#22a977', '#805ad5', '#64748b'],
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} ({d}%)' },
  legend: {
    orient: 'vertical',
    right: 4,
    top: 'middle',
    itemWidth: 9,
    itemHeight: 9,
    textStyle: { color: '#526273', fontSize: 11 },
  },
  series: [
    {
      type: 'pie',
      radius: ['48%', '70%'],
      center: ['35%', '52%'],
      avoidLabelOverlap: true,
      label: { show: false },
      itemStyle: { borderColor: '#ffffff', borderWidth: 3 },
      data: sensitiveTypeShare.value.map((item) => ({
        name: item.name,
        value: Number(item.value) || 0,
      })),
    },
  ],
}))

function sparklinePoints(series) {
  const values = (series || []).map((value) => Number(value) || 0)
  if (values.length < 2) return '0,24 180,24'
  const minimum = Math.min(...values)
  const spread = Math.max(1, Math.max(...values) - minimum)
  return values.map((value, index) => {
    const x = (index / (values.length - 1)) * 180
    const y = 30 - ((value - minimum) / spread) * 24
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

function regionPercent(value) {
  return `${Math.max(7, ((Number(value) || 0) / maxRegionValue.value) * 100)}%`
}

function industryPercent(value) {
  return `${Math.max(7, ((Number(value) || 0) / maxIndustryValue.value) * 100)}%`
}

function markerPosition(index) {
  const positions = [
    { left: '22%', top: '32%' },
    { left: '31%', top: '49%' },
    { left: '50%', top: '31%' },
    { left: '57%', top: '38%' },
    { left: '75%', top: '58%' },
  ]
  return positions[index] || positions[positions.length - 1]
}

</script>

<style scoped lang="scss">

.dashboard-chart {
  height: 100%;
}


.module-preview__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.module-preview__card {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 22px;
  border-radius: 22px;
  border: 1px solid var(--ti-border-default);
  background: rgba(255, 252, 247, 0.92);
  box-shadow: var(--ti-shadow-card);
  transition:
    transform 0.24s ease,
    box-shadow 0.24s ease;
}

.module-preview__card:hover {
  transform: translateY(-4px);
  box-shadow: var(--ti-shadow-card-hover);
}

.module-preview__card-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.module-preview__card h3 {
  margin: 0;
  font-size: 22px;
  color: var(--ti-text-primary);
}

.module-preview__card p {
  margin: 0;
  color: var(--ti-text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

.module-preview__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding-top: 6px;
}

.module-preview__stats div {
  padding-top: 12px;
  border-top: 1px solid var(--ti-border-soft);
}

.module-preview__stats span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.module-preview__stats strong {
  display: block;
  margin-top: 6px;
  color: var(--ti-text-primary);
  font-size: 22px;
}

.module-preview__footer {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--ti-accent-strong);
  font-size: 13px;
  font-weight: 700;
}

.dashboard-bottom {
  grid-template-columns: 1fr;
  align-items: start;
}

.timeline-list {
  display: grid;
  gap: 16px;
}

.timeline-list__item {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 16px;
}

.timeline-list__time {
  color: var(--ti-text-muted);
  font-family: var(--ti-font-mono);
  font-size: 12px;
  padding-top: 6px;
}

.timeline-list__content {
  padding: 16px;
  border-radius: 18px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.66);
}

.timeline-list__content h3 {
  margin: 10px 0 6px;
  color: var(--ti-text-primary);
  font-size: 15px;
}

.timeline-list__content p {
  color: var(--ti-text-secondary);
  font-size: 13px;
}

@media (max-width: 1440px) {
  .module-preview__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1024px) {
  .dashboard-bottom {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 767px) {
  .module-preview__grid,
  .module-preview__stats {
    grid-template-columns: 1fr;
  }

  .timeline-list__item {
    grid-template-columns: 1fr;
    gap: 8px;
  }
}


.dashboard-page {
  gap: 10px;
}

.situation-toolbar,
.situation-status,
.situation-panel,
.situation-kpi {
  border: 1px solid #ccd7e0;
  border-radius: 5px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(16, 31, 46, 0.03);
}

.situation-toolbar {
  display: flex;
  min-height: 64px;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
}

.situation-toolbar__eyebrow {
  color: #687889;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.situation-toolbar h1 {
  margin: 3px 0 0;
  color: #121d28;
  font-size: 20px;
  line-height: 1.15;
}

.situation-range {
  display: flex;
  overflow: hidden;
  border: 1px solid #ccd7e0;
  border-radius: 4px;
}

.situation-range button {
  min-height: 36px;
  padding: 0 13px;
  border: 0;
  border-right: 1px solid #ccd7e0;
  background: #ffffff;
  color: #566779;
  cursor: pointer;
  font-weight: 700;
}

.situation-range button:last-child {
  border-right: 0;
}

.situation-range button.active {
  background: #17232f;
  color: #ffffff;
}

.situation-status {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
}

.situation-status p {
  margin: 0;
  color: #526579;
  font-size: 12px;
}

.situation-status__metrics {
  display: flex;
  align-items: center;
}

.situation-status__metrics > span {
  min-width: 150px;
  padding: 4px 16px;
  border-left: 1px solid #d7e0e7;
  color: #596a7b;
  font-size: 12px;
}

.situation-status__metrics strong {
  float: right;
  color: #101a25;
  font-size: 20px;
  line-height: 1;
}

.situation-status__metrics :deep(.el-button) {
  margin-left: 10px;
}

.situation-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.situation-kpi {
  position: relative;
  min-width: 0;
  min-height: 154px;
  overflow: hidden;
  padding: 15px 16px;
}

.situation-kpi header {
  position: relative;
  z-index: 2;
  display: flex;
  min-height: 22px;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  color: #607080;
  font-size: 12px;
}

.situation-kpi header em {
  max-width: 58%;
  overflow: hidden;
  padding: 4px 7px;
  border-radius: 3px;
  background: #fff1df;
  color: #e18100;
  font-size: 10px;
  font-style: normal;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.situation-kpi header .situation-kpi__tag--danger,
.situation-kpi header .situation-kpi__tag--error {
  background: #ffeaec;
  color: #ec3343;
}

.situation-kpi > strong {
  position: relative;
  z-index: 2;
  display: block;
  margin-top: 6px;
  color: #111c27;
  font-size: 34px;
  line-height: 1.1;
}

.situation-kpi svg {
  position: absolute;
  z-index: 1;
  right: 25%;
  bottom: 14px;
  width: 40%;
  height: 36px;
  overflow: visible;
}

.situation-kpi polyline {
  fill: none;
  stroke: #ec8c00;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.4;
  vector-effect: non-scaling-stroke;
}

.situation-kpi:nth-child(2) polyline {
  stroke: #ef3542;
}

.situation-kpi:nth-child(3) polyline {
  stroke: #078eea;
}

.situation-kpi:nth-child(4) polyline {
  stroke: #805ad5;
}

.situation-kpi > i {
  position: absolute;
  right: -23px;
  bottom: -37px;
  width: 92px;
  height: 92px;
  border: 1px solid rgba(235, 71, 80, 0.17);
  border-radius: 50%;
}


.situation-main {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(330px, 0.85fr);
  gap: 10px;
}

.situation-panel {
  min-width: 0;
  overflow: hidden;
}

.situation-panel__header {
  display: flex;
  min-height: 68px;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid #d5dfe7;
}

.situation-panel__header small {
  display: block;
  margin-bottom: 3px;
  color: #718090;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.situation-panel__header h2 {
  margin: 0;
  color: #17222e;
  font-size: 18px;
  line-height: 1.15;
}

.situation-panel__header > span {
  color: #607181;
  font-size: 11px;
}

.situation-live {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #20a760 !important;
  font-weight: 700;
}

.situation-live i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #31b872;
}

.situation-map-layout {
  display: grid;
  min-height: 320px;
  grid-template-columns: minmax(0, 1.9fr) minmax(230px, 0.7fr);
}

.situation-map {
  position: relative;
  min-height: 320px;
  overflow: hidden;
  border-right: 1px solid #d5dfe7;
  background:
    linear-gradient(rgba(80, 125, 157, 0.13) 1px, transparent 1px),
    linear-gradient(90deg, rgba(80, 125, 157, 0.13) 1px, transparent 1px),
    #e9f3fb;
  background-size: 36px 36px;
}

.situation-map > img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  opacity: 0.72;
  filter: saturate(0.55) contrast(0.88);
}

.situation-map__marker {
  position: absolute;
  z-index: 2;
  transform: translate(-50%, -50%);
}

.situation-map__marker i {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 9px;
  height: 9px;
  border: 2px solid #ffffff;
  border-radius: 50%;
  background: #ef3945;
  box-shadow: 0 0 0 5px rgba(239, 57, 69, 0.14);
  transform: translate(-50%, -50%);
}

.situation-map__marker b {
  position: absolute;
  bottom: 9px;
  left: 7px;
  padding: 4px 7px;
  border: 1px solid rgba(176, 194, 208, 0.8);
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.92);
  color: #263747;
  font-size: 9px;
  white-space: nowrap;
}

.region-ranking {
  padding: 11px 14px;
}

.region-ranking__head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 11px;
  padding-bottom: 9px;
  border-bottom: 1px solid #d9e2e9;
  color: #68798a;
  font-size: 10px;
}

.region-ranking__row {
  display: grid;
  grid-template-columns: 58px minmax(70px, 1fr) 30px;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  color: #2f4050;
  font-size: 12px;
}

.region-ranking__row > i {
  height: 7px;
  overflow: hidden;
  border-radius: 99px;
  background: #edf2f6;
}

.region-ranking__row > i em {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #ef9c00, #ec3d42);
}

.region-ranking__row strong {
  color: #23313e;
  text-align: right;
}

.situation-map-panel__foot {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  border-top: 1px solid #d5dfe7;
  background: #f2f6f9;
  color: #697989;
  font-size: 10px;
}

.situation-map-panel__foot > span:first-child {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.situation-map-panel__foot i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #078eea;
}

.situation-map-panel__foot strong {
  margin-left: 7px;
  color: #1f2c38;
  font-size: 16px;
}


.situation-focus {
  display: flex;
  flex-direction: column;
}

.situation-focus__count {
  display: grid;
  width: 34px;
  height: 28px;
  place-items: center;
  border: 1px solid #d4dee6;
  border-radius: 5px;
  background: #f7fafc;
  color: #e83b47 !important;
  font-size: 14px !important;
  font-weight: 800;
}

.situation-focus__list {
  flex: 1;
  padding: 0 14px;
}

.situation-focus__list > article {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) auto;
  align-items: center;
  gap: 11px;
  min-height: 72px;
  border-bottom: 1px solid #d6e0e7;
}

.situation-focus__icon {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border: 3px solid #ffffff;
  border-radius: 50%;
  background: #ef3542;
  box-shadow: 0 0 0 2px rgba(239, 53, 66, 0.36);
  color: #ffffff;
  font-size: 19px;
}

.situation-focus__icon--warning {
  background: #ee9500;
  box-shadow: 0 0 0 2px rgba(238, 149, 0, 0.38);
}

.situation-focus__icon--primary {
  background: #078eea;
  box-shadow: 0 0 0 2px rgba(7, 142, 234, 0.32);
}

.situation-focus__list h3 {
  display: -webkit-box;
  overflow: hidden;
  margin: 0 0 5px;
  color: #1d2a35;
  font-size: 12px;
  line-height: 1.3;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
}

.situation-focus__list p {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  color: #738291;
  font-size: 10px;
  line-height: 1.3;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
}

.situation-focus__list > article > strong {
  color: #ec3744;
  font-size: 10px;
}

.situation-focus__action {
  display: flex;
  min-height: 44px;
  align-items: center;
  justify-content: space-between;
  margin: 10px 14px 14px;
  padding: 0 12px;
  background: #17232f;
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
}

.situation-analysis {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(260px, 0.68fr) minmax(280px, 0.82fr);
  gap: 10px;
}

.situation-chart {
  height: 310px;
}

.situation-chart .situation-panel__header,
.situation-industry .situation-panel__header {
  min-height: 60px;
}

.situation-chart .dashboard-chart {
  width: 100%;
  height: 248px;
  padding: 4px 8px 7px;
}

.situation-industry__list {
  padding: 8px 14px 13px;
}

.situation-industry__list > div {
  display: grid;
  min-height: 39px;
  grid-template-columns: 26px 74px minmax(70px, 1fr) 34px;
  align-items: center;
  gap: 7px;
  color: #506173;
  font-size: 11px;
}

.situation-industry__list b {
  color: #9aa7b3;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.situation-industry__list i {
  height: 7px;
  overflow: hidden;
  border-radius: 99px;
  background: #edf2f6;
}

.situation-industry__list em {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #078eea, #ef3c48);
}

.situation-industry__list strong {
  color: #23313e;
  text-align: right;
}


@media (max-width: 1280px) {
  .situation-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .situation-status {
    align-items: flex-start;
    gap: 12px;
    padding-top: 12px;
    padding-bottom: 12px;
  }

  .situation-status__metrics {
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .situation-status__metrics > span {
    min-width: 130px;
  }

  .situation-main {
    grid-template-columns: 1fr;
  }

  .situation-analysis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .situation-industry {
    grid-column: 1 / -1;
  }
}

@media (max-width: 900px) {
  .situation-toolbar,
  .situation-status {
    align-items: stretch;
    flex-direction: column;
  }

  .situation-range {
    align-self: flex-start;
  }

  .situation-status__metrics {
    justify-content: flex-start;
  }

  .situation-status__metrics > span {
    border-left: 0;
    border-right: 1px solid #d7e0e7;
    padding-left: 0;
  }

  .situation-map-layout,
  .situation-analysis {
    grid-template-columns: 1fr;
  }

  .situation-map {
    border-right: 0;
    border-bottom: 1px solid #d5dfe7;
  }

  .situation-industry {
    grid-column: auto;
  }
}

@media (max-width: 640px) {
  .situation-kpis {
    grid-template-columns: 1fr;
  }

  .situation-toolbar {
    padding: 12px;
  }

  .situation-status__metrics {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .situation-status__metrics > span {
    min-width: 0;
    padding: 8px 10px 8px 0;
    border-right: 0;
  }

  .situation-map {
    min-height: 250px;
  }

  .situation-map-layout {
    min-height: 250px;
  }

  .situation-map__marker b {
    display: none;
  }

  .situation-focus__list > article {
    grid-template-columns: 42px minmax(0, 1fr);
  }

  .situation-focus__list > article > strong {
    display: none;
  }
}
</style>
