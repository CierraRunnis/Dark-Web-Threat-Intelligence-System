<template>
  <div class="threat-situation-page ti-page">
    <section class="ti-panel ti-reveal-up executive-hero">
      <div class="executive-hero__copy">
        <span class="ti-kicker">领导汇报视图</span>
        <h2>近 30 天威胁态势总览</h2>
        <p>{{ executiveSummary }}</p>
      </div>
      <div class="executive-hero__metrics">
        <div class="executive-hero__metric">
          <span>国家覆盖率</span>
          <strong :class="{ 'is-warning': coverage.countryCoverageRate < 80 }">{{ coverage.countryCoverageRate }}%</strong>
        </div>
        <div class="executive-hero__metric">
          <span>地区覆盖率</span>
          <strong :class="{ 'is-warning': coverage.regionCoverageRate < 80 }">{{ coverage.regionCoverageRate }}%</strong>
        </div>
        <div class="executive-hero__metric">
          <span>行业覆盖率</span>
          <strong :class="{ 'is-warning': coverage.industryCoverageRate < 80 }">{{ coverage.industryCoverageRate }}%</strong>
        </div>
      </div>
    </section>

    <section class="cards-grid">
      <article class="ti-card executive-card ti-reveal-up">
        <span class="executive-card__label">近 30 天攻击事件总量</span>
        <strong class="executive-card__value">{{ cards.totalEvents30d }}</strong>
        <p :class="deltaTone(cards.totalEventsDeltaPct)">
          {{ deltaLabel(cards.totalEventsDeltaPct, '较前 30 天') }}
        </p>
      </article>

      <article class="ti-card executive-card ti-reveal-up">
        <span class="executive-card__label">近 30 天高风险事件</span>
        <strong class="executive-card__value">{{ cards.highRisk30d }}</strong>
        <p :class="deltaTone(cards.highRiskDeltaPct)">
          {{ deltaLabel(cards.highRiskDeltaPct, '较前 30 天') }}
        </p>
      </article>

      <article class="ti-card executive-card ti-reveal-up">
        <span class="executive-card__label">受害最多国家</span>
        <strong class="executive-card__value">{{ cards.topCountry || '未知' }}</strong>
        <p>当前事件量 {{ cards.topCountryEventCount || 0 }}</p>
      </article>
    </section>

    <section class="charts-grid">
      <ChartPanel
        eyebrow="趋势判断"
        title="30 天攻击态势趋势"
        description="直接判断近期攻击总量与高风险事件是上升还是下降。"
        icon="TrendCharts"
        height="360px"
      >
        <v-chart class="chart" :option="trendOption" autoresize />
      </ChartPanel>

      <ChartPanel
        eyebrow="重点国家"
        title="受害国家 Top 10"
        description="按事件数量排序，辅助识别当前最需要汇报的重点国家。"
        icon="Histogram"
        height="360px"
      >
        <v-chart class="chart" :option="countriesOption" autoresize />
      </ChartPanel>

      <ChartPanel
        eyebrow="受害行业"
        title="重点受害行业分布"
        description="展示当前统计样本中的全部已识别行业，并按占比展开。"
        icon="PieChart"
        height="420px"
      >
        <v-chart v-if="hasIndustryDistribution" class="chart" :option="industryDistributionOption" autoresize />
        <div v-else class="chart-empty">暂无足够样本。</div>
      </ChartPanel>

      <ChartPanel
        eyebrow="活跃组织"
        title="活跃泄露组织 Top 10"
        description="按出现次数从高到低排序，辅助识别近期最活跃的泄露主体。"
        icon="Histogram"
        height="420px"
      >
        <v-chart v-if="hasActiveActors" class="chart" :option="activeActorsOption" autoresize />
        <div v-else class="chart-empty">暂无足够样本。</div>
      </ChartPanel>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">重点事件表</div>
      </div>
      <div class="ti-card-body">
        <div class="ti-table-shell">
          <el-table :data="priorityEvents" table-layout="auto" style="width: 100%">
            <el-table-column prop="disclosureDate" label="披露日期" width="140" />
            <el-table-column prop="title" label="事件标题" min-width="360" show-overflow-tooltip />
            <el-table-column prop="attacker" label="攻击者" min-width="140" show-overflow-tooltip />
            <el-table-column prop="country" label="国家" width="120" />
            <el-table-column prop="industry" label="行业" width="120" />
            <el-table-column prop="riskScore" label="风险分" width="100" />
            <el-table-column label="详情" width="100" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" @click="viewEventDetail(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import '@/lib/echarts'
import * as fallbackModule from '@/mock/intelligence'
import ChartPanel from '@/components/common/ChartPanel.vue'
import { useIntelligenceData } from '@/composables/useIntelligenceData'

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === '1'
const router = useRouter()
const { data } = useIntelligenceData()

const chartPalette = ['#2d5dff', '#43a06e', '#e88030', '#cf4432', '#5d74d6', '#7e8ca3', '#a855f7', '#14b8a6', '#f59e0b', '#ef4444']

function resolveObjectSection(key, fallbackValue) {
  const value = data.value[key]
  if (value && !Array.isArray(value) && Object.keys(value).length) {
    return value
  }
  return fallbackValue
}

function resolveArraySection(key, fallbackValue = []) {
  const value = data.value[key]
  if (Array.isArray(value) && value.length) {
    return value
  }
  return fallbackValue
}

function normalizeText(value) {
  return String(value || '').trim()
}

function truncateLabel(value, max = 24) {
  const text = normalizeText(value)
  if (text.length <= max) return text
  return `${text.slice(0, max - 1)}…`
}

function percentage(value, total) {
  if (!total) return 0
  return Number(((value / total) * 100).toFixed(2))
}

const cards = computed(() => resolveObjectSection('threatExecutiveCards', {
  totalEvents30d: 0,
  totalEventsDeltaPct: 0,
  highRisk30d: 0,
  highRiskDeltaPct: 0,
  topCountry: '未知',
  topCountryEventCount: 0,
}))

const coverage = computed(() => resolveObjectSection('threatExecutiveCoverage', {
  countryCoverageRate: 0,
  regionCoverageRate: 0,
  industryCoverageRate: 0,
}))

const trend = computed(() => resolveObjectSection('threatExecutiveTrend', {
  labels: [],
  total: [],
  highRisk: [],
}))

const countries = computed(() => resolveArraySection('threatExecutiveCountries'))
const priorityEvents = computed(() => resolveArraySection('threatExecutivePriorityEvents'))
const dataLeakEvents = computed(() => resolveArraySection('dataLeakEvents', DEMO_MODE ? (fallbackModule.dataLeakEvents || []) : []))
const ransomwareEvents = computed(() => resolveArraySection('ransomwareEvents', DEMO_MODE ? (fallbackModule.ransomwareEvents || []) : []))
const threatEvents = computed(() => [...dataLeakEvents.value, ...ransomwareEvents.value])

const executiveSummary = computed(() => {
  const totalTrend = cards.value.totalEventsDeltaPct >= 0 ? '上升' : '下降'
  const riskTrend = cards.value.highRiskDeltaPct >= 0 ? '增加' : '下降'
  return `攻击事件总体呈${totalTrend}趋势，高风险事件持续${riskTrend}，当前受害最多国家为 ${cards.value.topCountry || '未知'}。`
})

const industryDistribution = computed(() => {
  const grouped = new Map()
  let total = 0
  for (const event of threatEvents.value) {
    const industry = normalizeText(event.industry)
    if (!industry || industry === '未知') continue
    total += 1
    grouped.set(industry, (grouped.get(industry) || 0) + 1)
  }
  return [...grouped.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0], 'zh-Hans-CN'))
    .map(([name, value], index) => ({
      name,
      value,
      percent: percentage(value, total),
      color: chartPalette[index % chartPalette.length],
    }))
})

const hasIndustryDistribution = computed(() => industryDistribution.value.length > 0)

const activeActors = computed(() => {
  const grouped = new Map()
  for (const event of threatEvents.value) {
    const actor = normalizeText(event.attacker)
    if (!actor || actor === '未知') continue
    const current = grouped.get(actor) || { actor, value: 0, riskTotal: 0 }
    current.value += 1
    current.riskTotal += Number(event.riskScore || 0)
    grouped.set(actor, current)
  }
  return [...grouped.values()]
    .map((item) => ({
      actor: item.actor,
      value: item.value,
      averageRiskScore: item.value ? Math.round(item.riskTotal / item.value) : 0,
    }))
    .sort((left, right) =>
      right.value - left.value ||
      right.averageRiskScore - left.averageRiskScore ||
      left.actor.localeCompare(right.actor, 'en')
    )
    .slice(0, 10)
})

const hasActiveActors = computed(() => activeActors.value.length > 0)
const activeActorMax = computed(() => {
  const maxValue = Math.max(...activeActors.value.map((item) => item.value), 0)
  return maxValue > 0 ? Math.ceil(maxValue * 1.12) : 1
})

const trendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: {
    bottom: 0,
    textStyle: { color: '#6b7280' },
  },
  grid: {
    top: 20,
    right: 16,
    bottom: 42,
    left: 44,
  },
  xAxis: {
    type: 'category',
    data: trend.value.labels,
    boundaryGap: false,
    axisLine: { lineStyle: { color: '#d1d5db' } },
    axisLabel: { color: '#6b7280' },
  },
  yAxis: {
    type: 'value',
    axisLine: { show: false },
    splitLine: { lineStyle: { color: '#eef2f7' } },
    axisLabel: { color: '#6b7280' },
  },
  series: [
    {
      name: '总事件量',
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      data: trend.value.total,
      lineStyle: { width: 3, color: '#ea580c' },
      itemStyle: { color: '#ea580c' },
      areaStyle: { color: 'rgba(234, 88, 12, 0.10)' },
    },
    {
      name: '高风险事件',
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 8,
      data: trend.value.highRisk,
      lineStyle: { width: 3, color: '#2563eb' },
      itemStyle: { color: '#2563eb' },
      areaStyle: { color: 'rgba(37, 99, 235, 0.08)' },
    },
  ],
}))

const countriesOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: {
    top: 20,
    right: 16,
    bottom: 20,
    left: 72,
  },
  xAxis: {
    type: 'value',
    axisLine: { show: false },
    splitLine: { lineStyle: { color: '#eef2f7' } },
    axisLabel: { color: '#6b7280' },
  },
  yAxis: {
    type: 'category',
    data: [...countries.value].reverse().map((item) => item.name),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: '#334155' },
  },
  series: [
    {
      name: '事件量',
      type: 'bar',
      data: [...countries.value].reverse().map((item) => item.eventCount),
      barWidth: 18,
      itemStyle: {
        borderRadius: [0, 8, 8, 0],
        color: '#0f766e',
      },
    },
  ],
}))

const industryDistributionOption = computed(() => ({
  color: industryDistribution.value.map((item) => item.color),
  tooltip: {
    trigger: 'item',
    formatter: ({ name, value, percent }) => `${name}<br/>事件数：${value}<br/>占比：${percent}%`,
  },
  series: [
    {
      name: '受害行业',
      type: 'pie',
      radius: ['44%', '64%'],
      center: ['50%', '58%'],
      minShowLabelAngle: 1,
      avoidLabelOverlap: true,
      labelLayout: {
        hideOverlap: false,
        moveOverlap: 'shiftY',
      },
      labelLine: {
        show: true,
        length: 16,
        length2: 18,
        maxSurfaceAngle: 80,
        lineStyle: {
          color: '#cbd5e1',
          width: 1.5,
        },
      },
      label: {
        show: true,
        position: 'outside',
        alignTo: 'edge',
        edgeDistance: 18,
        bleedMargin: 4,
        distanceToLabelLine: 4,
        padding: [0, 0, 0, 0],
        width: 88,
        overflow: 'truncate',
        color: '#475569',
        fontSize: 12,
        lineHeight: 14,
        formatter: ({ name }) => truncateLabel(name, 12),
      },
      itemStyle: {
        borderColor: '#ffffff',
        borderWidth: 3,
        borderRadius: 6,
      },
      data: industryDistribution.value.map((item) => ({
        name: item.name,
        value: item.value,
        itemStyle: { color: item.color },
      })),
    },
  ],
  graphic: [
    {
      type: 'text',
      left: 'center',
      top: '40%',
      style: {
        text: '行业数',
        textAlign: 'center',
        fill: '#94a3b8',
        fontSize: 12,
        fontWeight: 600,
      },
    },
    {
      type: 'text',
      left: 'center',
      top: '46%',
      style: {
        text: String(industryDistribution.value.length),
        textAlign: 'center',
        fill: '#0f172a',
        fontSize: 28,
        fontWeight: 700,
      },
    },
    {
      type: 'text',
      left: 'center',
      top: '57%',
      style: {
        text: '全部行业',
        textAlign: 'center',
        fill: '#94a3b8',
        fontSize: 12,
      },
    },
  ],
}))

const activeActorsOption = computed(() => ({
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    formatter: (params) => {
      const item = Array.isArray(params) ? params[0] : params
      const row = activeActors.value[item?.dataIndex ?? 0]
      return [
        row?.actor || '',
        `事件数：${row?.value || 0}`,
        `平均风险：${row?.averageRiskScore || 0}`,
      ].join('<br/>')
    },
  },
  grid: {
    top: 14,
    right: 52,
    bottom: 32,
    left: 12,
    containLabel: true,
  },
  xAxis: {
    type: 'value',
    minInterval: 1,
    max: activeActorMax.value,
    axisLine: { show: false },
    splitLine: { lineStyle: { color: '#eef2f7' } },
    axisLabel: {
      color: '#64748b',
      fontSize: 12,
      margin: 12,
      showMinLabel: true,
      showMaxLabel: true,
    },
  },
  yAxis: {
    type: 'category',
    inverse: true,
    data: activeActors.value.map((item) => truncateLabel(item.actor, 22)),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: '#334155',
      width: 156,
      overflow: 'truncate',
    },
  },
  series: [
    {
      name: '事件数',
      type: 'bar',
      data: activeActors.value.map((item) => item.value),
      barWidth: 16,
      label: {
        show: true,
        position: 'right',
        distance: 8,
        color: '#475569',
        fontSize: 12,
        fontWeight: 600,
        formatter: ({ value }) => value,
      },
      itemStyle: {
        borderRadius: [0, 8, 8, 0],
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 1,
          y2: 0,
          colorStops: [
            { offset: 0, color: '#f3a5b8' },
            { offset: 1, color: '#cf4432' },
          ],
        },
      },
    },
  ],
}))

function deltaTone(value) {
  if (value > 0) return 'executive-card__delta executive-card__delta--danger'
  if (value < 0) return 'executive-card__delta executive-card__delta--success'
  return 'executive-card__delta'
}

function deltaLabel(value, prefix) {
  if (value > 0) return `${prefix} 上升 ${value}%`
  if (value < 0) return `${prefix} 下降 ${Math.abs(value)}%`
  return `${prefix} 持平`
}

function viewEventDetail(row) {
  if (!row?.id) return
  sessionStorage.setItem(`event-back:${row.id}`, '/threat-situation')
  router.push({ name: 'EventDetail', params: { eventId: row.id } })
}
</script>

<style scoped lang="scss">
.executive-hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-start;
}

.executive-hero__copy h2 {
  margin: 10px 0 0;
  font-size: 36px;
  line-height: 1.15;
  color: var(--ti-text-primary);
}

.executive-hero__copy p {
  margin: 12px 0 0;
  color: var(--ti-text-secondary);
  font-size: 15px;
  line-height: 1.7;
}

.executive-hero__metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  min-width: 360px;
}

.executive-hero__metric {
  padding: 16px 18px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
}

.executive-hero__metric span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.executive-hero__metric strong {
  display: block;
  margin-top: 8px;
  color: var(--ti-text-primary);
  font-size: 28px;
}

.executive-hero__metric strong.is-warning {
  color: #dc2626;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin-top: 22px;
}

.executive-card {
  padding: 28px;
}

.executive-card__label {
  display: block;
  color: var(--ti-text-muted);
  font-size: 13px;
}

.executive-card__value {
  display: block;
  margin-top: 18px;
  color: var(--ti-text-primary);
  font-size: 42px;
  line-height: 1;
}

.executive-card p {
  margin: 16px 0 0;
  color: var(--ti-text-secondary);
  font-size: 14px;
}

.executive-card__delta--danger {
  color: #dc2626;
}

.executive-card__delta--success {
  color: #0f766e;
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  margin-top: 22px;
}

.chart {
  width: 100%;
  height: 100%;
}

.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--ti-text-secondary);
  font-size: 14px;
}

@media (max-width: 1280px) {
  .executive-hero {
    flex-direction: column;
  }

  .executive-hero__metrics,
  .cards-grid,
  .charts-grid {
    grid-template-columns: 1fr;
  }
}
</style>
