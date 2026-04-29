<template>
  <div class="threat-situation-page ti-page">
    <section class="ti-panel ti-reveal-up executive-hero">
      <div class="executive-hero__copy">
        <h2>近 30 天威胁态势总览</h2>
        <p>{{ executiveSummary }}</p>
      </div>
      <div class="executive-hero__actions">
        <el-button type="primary" plain @click="exportSituationReport">导出报告</el-button>
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
        <v-chart ref="trendChartRef" class="chart" :option="trendOption" autoresize />
      </ChartPanel>

      <ChartPanel
        eyebrow="重点国家"
        title="受害国家 Top 10"
        description="按事件数量排序，辅助识别当前最需要汇报的重点国家。"
        icon="Histogram"
        height="360px"
      >
        <v-chart ref="countriesChartRef" class="chart" :option="countriesOption" autoresize />
      </ChartPanel>

      <ChartPanel
        eyebrow="受害行业"
        title="重点受害行业分布"
        description="仅展示数量前 10 的行业，其余统一归入其他。"
        icon="PieChart"
        height="420px"
      >
        <v-chart v-if="hasIndustryDistribution" ref="industryChartRef" class="chart" :option="industryDistributionOption" autoresize />
        <div v-else class="chart-empty">暂无足够样本。</div>
      </ChartPanel>

      <ChartPanel
        eyebrow="活跃组织"
        title="活跃泄露组织 Top 10"
        description="按出现次数从高到低排序，辅助识别近期最活跃的泄露主体。"
        icon="Histogram"
        height="420px"
      >
        <v-chart v-if="hasActiveActors" ref="activeActorsChartRef" class="chart" :option="activeActorsOption" autoresize />
        <div v-else class="chart-empty">暂无足够样本。</div>
      </ChartPanel>
    </section>

    <section class="ti-panel ti-reveal-up monitoring-section">
      <div class="monitoring-section__header">
        <div>
          <span class="ti-kicker">新增监测视图</span>
          <h3>重点监测与样本证据补充面板</h3>
        </div>
        <StatusBadge label="已保留新增内容" tone="success" :dot="false" />
      </div>
      <div class="monitoring-summary-grid">
        <article class="monitoring-card">
          <span class="monitoring-card__label">高优先事件</span>
          <strong class="monitoring-card__value">{{ monitoringSummary.highPriorityCount || 0 }}</strong>
          <p>当前规则命中的重点监测事件数量</p>
        </article>
        <article class="monitoring-card">
          <span class="monitoring-card__label">样本证据事件</span>
          <strong class="monitoring-card__value">{{ monitoringSummary.sampleEvidenceCount || 0 }}</strong>
          <p>含样本链接或样本证据的事件数量</p>
        </article>
        <article class="monitoring-card">
          <span class="monitoring-card__label">启用规则数</span>
          <strong class="monitoring-card__value">{{ monitoringSummary.enabledKeywordCount || 0 }}</strong>
          <p>当前已启用的重点监测关键词规则</p>
        </article>
      </div>
    </section>

    <section class="content-grid">
      <div class="ti-card ti-reveal-up monitoring-panel monitoring-panel--sample">
        <div class="ti-card-header">
          <div class="ti-card-title">样本证据面板</div>
          <StatusBadge label="人工复核" tone="warning" :dot="false" />
        </div>
        <div class="ti-card-body">
          <div v-if="sampleEvidenceAlerts.length" class="sample-alert-list">
            <article v-for="item in sampleEvidenceAlerts" :key="item.id" class="sample-alert-item">
              <div class="sample-alert-item__header">
                <strong>{{ item.title }}</strong>
                <span>风险 {{ item.riskScore }}</span>
              </div>
              <p>{{ item.sourceSite }} · 样本链接 {{ item.sampleLinkCount }}</p>
              <div class="sample-links">
                <a v-for="link in item.sampleLinks.slice(0, 2)" :key="link.url" :href="link.url" target="_blank" rel="noreferrer">
                  {{ link.kind }}: {{ truncateLink(link.url) }}
                </a>
              </div>
            </article>
          </div>
          <div v-else class="chart-empty">暂无样本证据事件。</div>
        </div>
      </div>

      <ChartPanel
        eyebrow="规则命中"
        title="重点监测规则命中统计"
        description="按关键词展示当前监测命中次数，用于解释为什么这些事件被前置。"
        icon="Histogram"
        height="360px"
      >
        <v-chart v-if="hasKeywordStats" ref="keywordStatsChartRef" class="chart" :option="keywordStatsOption" autoresize />
        <div v-else class="chart-empty">暂无监测规则命中数据。</div>
      </ChartPanel>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">重点事件表</div>
      </div>
      <div class="ti-card-body">
        <div class="ti-table-shell">
          <el-table :data="focusEvents" table-layout="auto" style="width: 100%">
            <el-table-column prop="disclosureDate" label="披露日期" width="140" />
            <el-table-column prop="title" label="事件标题" min-width="360" show-overflow-tooltip />
            <el-table-column prop="sourceSite" label="来源站点" width="140" />
            <el-table-column prop="country" label="国家" width="120" />
            <el-table-column prop="industry" label="行业" width="120" />
            <el-table-column prop="riskScore" label="风险分" width="100" />
            <el-table-column prop="monitoringWeight" label="监测权重" width="100" />
            <el-table-column label="命中关键词" min-width="220">
              <template #default="{ row }">
                <span>{{ formatMatches(row.monitoringMatches) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="样本证据" width="100">
              <template #default="{ row }">
                <StatusBadge :label="row.hasSampleEvidence ? '有' : '无'" :tone="row.hasSampleEvidence ? 'danger' : 'muted'" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" type="primary" @click="viewEventDetail(row)">详情</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { init as initECharts } from 'echarts/core'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import '@/lib/echarts'
import * as fallbackModule from '@/mock/intelligence'
import ChartPanel from '@/components/common/ChartPanel.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useIntelligenceData } from '@/composables/useIntelligenceData'

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === '1'
const router = useRouter()
const { data } = useIntelligenceData()
const trendChartRef = ref(null)
const countriesChartRef = ref(null)
const industryChartRef = ref(null)
const activeActorsChartRef = ref(null)
const keywordStatsChartRef = ref(null)
const REPORT_CHART_RENDER_WIDTH = 605
const REPORT_CHART_RENDER_HEIGHT = 376

const chartPalette = ['#2d5dff', '#43a06e', '#e88030', '#cf4432', '#5d74d6', '#7e8ca3', '#a855f7', '#14b8a6', '#f59e0b', '#ef4444']
const industryLabelOverrides = {
  other: '其他',
  unknown: '未知',
  'business services': '其他',
  'consumer services': '零售',
  'financial services': '金融',
  manufacturing: '制造业',
  construction: '制造业',
  'public sector': '政府',
  'agriculture and food production': '农业',
  telecommunication: '通信',
  telecommunications: '通信',
  'transportation/logistics': '交通',
  'hospitality and tourism': '文娱',
  '鍒堕€犱笟': '制造业',
  '闆跺敭': '零售',
  '鍏朵粬': '其他',
  '鏀垮簻': '政府',
  '閲戣瀺': '金融',
  '鍖荤枟': '医疗',
  '绉戞妧': '科技',
  '鍐涗簨': '军事',
  '鍐滀笟': '农业',
  '鏁欒偛': '教育',
  '閫氫俊': '通信',
  '鑳芥簮': '能源',
  '浜ら€?': '交通',
  '鏂囧ū': '文娱',
}

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

function normalizeIndustryLabel(value) {
  const text = normalizeText(value)
  if (!text) return text
  return industryLabelOverrides[text] || industryLabelOverrides[text.toLowerCase()] || text
}

const titleReplacementPairs = [
  ['PARTIALLY', '部分'],
  ['Household Registration Data', '户籍数据'],
  ['Household Registration', '户籍'],
  ['Cloud Network', '云网络'],
  ['Network', '网络'],
  ['Design Platform', '设计平台'],
  ['Design', '设计'],
  ['Platform', '平台'],
  ['Users', '用户'],
  ['User', '用户'],
  ['Database', '数据库'],
  ['Data', '数据'],
  ['ID Cards', '身份证卡'],
  ['passport', '护照'],
  ['passports', '护照'],
  ['Credit Cards', '信用卡'],
  ['Business Information', '商业信息'],
  ['Identity Cards', '身份卡'],
  ['Leaked, Download!', '泄露，下载！'],
  ['Leaked Download!', '泄露下载！'],
  ['Leaked Download', '泄露下载'],
  ['Leaked', '泄露'],
  ['Download', '下载'],
  ['Data Collection Leak', '数据采集泄露'],
  ['Household', '户籍'],
  ['Government', '政府'],
  ['China', '中国'],
  ['Taiwan', '台湾'],
]

function localizeFocusTitle(value) {
  let text = normalizeText(value)
  if (!text) return text
  for (const [source, target] of titleReplacementPairs) {
    text = text.replaceAll(source, target)
  }
  return text
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

const trend = computed(() => resolveObjectSection('threatExecutiveTrend', {
  labels: [],
  total: [],
  highRisk: [],
}))

const countries = computed(() => resolveArraySection('threatExecutiveCountries'))
const priorityEvents = computed(() => resolveArraySection('threatExecutivePriorityEvents'))
const dataLeakEvents = computed(() => resolveArraySection('dataLeakEvents', DEMO_MODE ? (fallbackModule.dataLeakEvents || []) : []))
const ransomwareEvents = computed(() => resolveArraySection('ransomwareEvents', DEMO_MODE ? (fallbackModule.ransomwareEvents || []) : []))
const vulnerabilityEvents = computed(() => resolveArraySection('vulnerabilityEvents', DEMO_MODE ? (fallbackModule.vulnerabilityEvents || []) : []))
const threatEvents = computed(() => [...dataLeakEvents.value, ...ransomwareEvents.value, ...vulnerabilityEvents.value])
const activeActorEvents = computed(() => ransomwareEvents.value)
const monitoringSummary = computed(() => data.value.monitoringConfigurationSummary || {})
const monitoringQueue = computed(() => data.value.monitoringPriorityQueue || [])
const monitoringKeywordStats = computed(() => data.value.monitoringKeywordStats || { keywords: [], categories: [] })
const sampleEvidenceAlerts = computed(() => data.value.sampleEvidenceAlerts || [])
const priorityAlertStream = computed(() => data.value.priorityAlertStream || [])
const hasKeywordStats = computed(() => (monitoringKeywordStats.value.keywords || []).length > 0)

const eventCatalog = computed(() => {
  const catalog = new Map()
  for (const item of [...dataLeakEvents.value, ...ransomwareEvents.value, ...vulnerabilityEvents.value]) {
    const id = normalizeText(item?.id)
    if (!id) continue
    catalog.set(id, {
      ...item,
      industry: normalizeIndustryLabel(item?.industry),
    })
  }
  return catalog
})

const focusEvents = computed(() => {
  const merged = new Map()

  function mergeMonitoringMatches(existingMatches = [], nextMatches = []) {
    const matchMap = new Map()
    for (const item of [...existingMatches, ...nextMatches]) {
      const keyword = normalizeText(item?.keyword)
      const category = normalizeText(item?.category)
      if (!keyword) continue
      const key = `${keyword}|${category}`
      const current = matchMap.get(key) || { ...item, keyword, category }
      current.weight = Math.max(Number(current.weight || 0), Number(item?.weight || 0))
      matchMap.set(key, current)
    }
    return [...matchMap.values()]
  }

  function upsert(item) {
    if (!item) return

    const itemId = normalizeText(item.id)
    const lookup = eventCatalog.value.get(itemId) || {}
    const title = normalizeText(item.title || lookup.title)
    const sourceSite = normalizeText(item.sourceSite || lookup.sourceSite || item.rawSourceTypeLabel || lookup.rawSourceTypeLabel)
    const disclosureDate = normalizeText(item.disclosureDate || item.date || lookup.disclosureDate || lookup.updatedTime)
    const key = itemId || `${title}|${sourceSite}|${disclosureDate}`
    if (!key) return

    const current = merged.get(key) || {
      id: item.id || key,
      disclosureDate: '',
      title: '',
      sourceSite: '',
      country: '',
      industry: '',
      riskScore: 0,
      monitoringWeight: 0,
      monitoringMatches: [],
      hasSampleEvidence: false,
    }

    merged.set(key, {
      ...current,
      id: current.id || item.id || key,
      disclosureDate: current.disclosureDate || disclosureDate,
      title: current.title || localizeFocusTitle(title),
      sourceSite: current.sourceSite || sourceSite,
      country: current.country || normalizeText(item.country || lookup.country),
      industry: current.industry || normalizeIndustryLabel(item.industry || lookup.industry),
      riskScore: Math.max(Number(current.riskScore || 0), Number(item.riskScore || 0), Number(lookup.riskScore || 0)),
      monitoringWeight: Math.max(Number(current.monitoringWeight || 0), Number(item.monitoringWeight || 0), Number(lookup.monitoringWeight || 0)),
      monitoringMatches: mergeMonitoringMatches(current.monitoringMatches, [...(lookup.monitoringMatches || []), ...(item.monitoringMatches || [])]),
      hasSampleEvidence: Boolean(current.hasSampleEvidence || item.hasSampleEvidence || lookup.hasSampleEvidence),
    })
  }

  priorityEvents.value.forEach(upsert)
  monitoringQueue.value.forEach(upsert)
  priorityAlertStream.value.forEach(upsert)

  return [...merged.values()].sort((left, right) =>
    Number(right.monitoringWeight || 0) - Number(left.monitoringWeight || 0) ||
    Number(right.riskScore || 0) - Number(left.riskScore || 0) ||
    Number(right.hasSampleEvidence) - Number(left.hasSampleEvidence) ||
    String(right.disclosureDate || '').localeCompare(String(left.disclosureDate || ''))
  )
})

const executiveSummary = computed(() => {
  const totalTrend = cards.value.totalEventsDeltaPct >= 0 ? '上升' : '下降'
  const riskTrend = cards.value.highRiskDeltaPct >= 0 ? '增加' : '下降'
  return `攻击事件总体呈${totalTrend}趋势，高风险事件持续${riskTrend}，当前受害最多国家为 ${cards.value.topCountry || '未知'}。`
})

const industryDistribution = computed(() => {
  const grouped = new Map()
  let total = 0
  for (const event of threatEvents.value) {
    const industry = normalizeIndustryLabel(event.industry)
    if (!industry || industry === '未知') continue
    total += 1
    grouped.set(industry, (grouped.get(industry) || 0) + 1)
  }

  const ranked = [...grouped.entries()].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0], 'zh-Hans-CN'))
  const top = ranked.slice(0, 10)
  const otherValue = ranked.slice(10).reduce((sum, [, value]) => sum + value, 0)
  const finalRows = [...top]
  if (otherValue > 0) {
    const otherIndex = finalRows.findIndex(([name]) => name === '其他')
    if (otherIndex >= 0) {
      finalRows[otherIndex] = ['其他', Number(finalRows[otherIndex][1] || 0) + otherValue]
    } else {
      finalRows.push(['其他', otherValue])
    }
  }

  return finalRows.map(([name, value], index) => ({
    name,
    value,
    percent: percentage(value, total),
    color: chartPalette[index % chartPalette.length],
  }))
})

const hasIndustryDistribution = computed(() => industryDistribution.value.length > 0)

const activeActors = computed(() => {
  const grouped = new Map()
  for (const event of activeActorEvents.value) {
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
        text: '前十行业',
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

const keywordZoomEnd = computed(() => Math.max(0, Math.min((monitoringKeywordStats.value.keywords || []).length - 1, 5)))

const keywordStatsOption = computed(() => ({
  dataZoom: [
    {
      type: 'inside',
      yAxisIndex: 0,
      zoomOnMouseWheel: true,
      moveOnMouseWheel: true,
      moveOnMouseMove: true,
      startValue: 0,
      endValue: keywordZoomEnd.value,
    },
    {
      type: 'slider',
      yAxisIndex: 0,
      width: 10,
      right: 0,
      startValue: 0,
      endValue: keywordZoomEnd.value,
      brushSelect: false,
    },
  ],
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    formatter: (params) => {
      const item = Array.isArray(params) ? params[0] : params
      const row = (monitoringKeywordStats.value.keywords || [])[item?.dataIndex ?? 0]
      return [
        row?.keyword || '',
        `命中次数：${row?.hits || 0}`,
        `高风险命中：${row?.highRiskHits || 0}`,
      ].join('<br/>')
    },
  },
  grid: { top: 14, right: 24, bottom: 32, left: 12, containLabel: true },
  xAxis: {
    type: 'value',
    axisLine: { show: false },
    splitLine: { lineStyle: { color: '#eef2f7' } },
    axisLabel: { color: '#64748b' },
  },
  yAxis: {
    type: 'category',
    inverse: true,
    data: (monitoringKeywordStats.value.keywords || []).map((item) => item.keyword),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: '#334155', width: 160, overflow: 'truncate' },
  },
  series: [
    {
      type: 'bar',
      data: (monitoringKeywordStats.value.keywords || []).map((item) => item.hits),
      barWidth: 16,
      itemStyle: {
        borderRadius: [0, 8, 8, 0],
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 1,
          y2: 0,
          colorStops: [
            { offset: 0, color: '#c7d2fe' },
            { offset: 1, color: '#4338ca' },
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

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function exportSituationReportLegacy() {
  const generatedAt = new Date().toLocaleString('zh-CN', { hour12: false })
  const topCountries = countries.value.slice(0, 10)
  const topActors = activeActors.value.slice(0, 10)
  const keyEvents = focusEvents.value.slice(0, 10)
  const monitoring = monitoringSummary.value || {}

  const metricCards = [
    ['近 30 天攻击事件总量', cards.value.totalEvents30d],
    ['近 30 天高风险事件', cards.value.highRisk30d],
    ['受害最多国家', cards.value.topCountry || '未知'],
    ['规则命中高优先事件', monitoring.highPriorityCount || 0],
  ]

  const html = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>威胁态势报告</title>
  <style>
    body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif; margin: 40px; color: #172033; background: #f7f8fc; }
    h1, h2 { margin: 0 0 14px; color: #172033; }
    p { margin: 0 0 12px; color: #52607a; line-height: 1.7; }
    .meta { margin-bottom: 28px; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 18px 0 28px; }
    .card { background: #fff; border: 1px solid #e7ebf3; border-radius: 16px; padding: 18px; }
    .card span { display: block; font-size: 12px; color: #7a8599; margin-bottom: 10px; }
    .card strong { display: block; font-size: 30px; color: #172033; }
    .section { margin-top: 28px; }
    table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 16px; overflow: hidden; }
    th, td { padding: 12px 14px; border-bottom: 1px solid #edf1f7; text-align: left; font-size: 13px; vertical-align: top; }
    th { background: #f8f9fc; color: #52607a; }
  </style>
</head>
<body>
  <h1>威胁态势报告</h1>
  <div class="meta">
    <p>生成时间：${escapeHtml(generatedAt)}</p>
    <p>${escapeHtml(executiveSummary.value)}</p>
  </div>
  <div class="grid">
    ${metricCards.map(([label, value]) => `<div class="card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join('')}
  </div>
  <div class="section">
    <h2>重点国家</h2>
    <table>
      <thead><tr><th>国家</th><th>事件量</th><th>高风险事件</th><th>平均风险分</th></tr></thead>
      <tbody>${topCountries.map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.eventCount)}</td><td>${escapeHtml(item.highRiskCount)}</td><td>${escapeHtml(item.averageRiskScore)}</td></tr>`).join('')}</tbody>
    </table>
  </div>
  <div class="section">
    <h2>活跃勒索组织</h2>
    <table>
      <thead><tr><th>组织</th><th>事件量</th><th>平均风险分</th></tr></thead>
      <tbody>${topActors.map((item) => `<tr><td>${escapeHtml(item.actor)}</td><td>${escapeHtml(item.value)}</td><td>${escapeHtml(item.averageRiskScore)}</td></tr>`).join('')}</tbody>
    </table>
  </div>
  <div class="section">
    <h2>重点事件</h2>
    <table>
      <thead><tr><th>日期</th><th>标题</th><th>来源</th><th>国家</th><th>行业</th><th>风险分</th></tr></thead>
      <tbody>${keyEvents.map((item) => `<tr><td>${escapeHtml(item.disclosureDate)}</td><td>${escapeHtml(item.title)}</td><td>${escapeHtml(item.sourceSite)}</td><td>${escapeHtml(item.country)}</td><td>${escapeHtml(item.industry)}</td><td>${escapeHtml(item.riskScore)}</td></tr>`).join('')}</tbody>
    </table>
  </div>
</body>
</html>`

  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `threat-situation-report-${new Date().toISOString().slice(0, 10)}.html`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

function renderWordTable(headers, rows) {
  return `
    <table>
      <thead>
        <tr>${headers.map((item) => `<th>${escapeHtml(item)}</th>`).join('')}</tr>
      </thead>
      <tbody>
        ${rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}
      </tbody>
    </table>
  `
}

function renderChartSection(title, imageUrl) {
  if (!imageUrl) return ''
  return `
    <div class="section chart-section">
      <h3 class="chart-section__title">${escapeHtml(title)}</h3>
      <div class="chart-box">
        <img src="${imageUrl}" alt="${escapeHtml(title)}" />
      </div>
    </div>
  `
}

async function renderReportChartImage(option, width, height) {
  const host = document.createElement('div')
  host.style.cssText = [
    'position: fixed',
    'left: -10000px',
    'top: -10000px',
    `width: ${width}px`,
    `height: ${height}px`,
    'background: #ffffff',
    'z-index: -1',
  ].join(';')
  document.body.appendChild(host)

  const chart = initECharts(host, null, { renderer: 'canvas', width, height })
  try {
    chart.setOption(option, true)
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
    return chart.getDataURL({
      type: 'png',
      pixelRatio: 2,
      backgroundColor: '#ffffff',
      excludeComponents: ['toolbox'],
    })
  } finally {
    chart.dispose()
    document.body.removeChild(host)
  }
}

function buildReportTrendOption() {
  return {
    animation: false,
    color: ['#ea580c', '#2563eb'],
    grid: { left: 42, right: 14, top: 16, bottom: 30 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: trend.value.labels,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#d1d5db' } },
      axisLabel: { color: '#6b7280', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#eef2f7' } },
      axisLabel: { color: '#6b7280', fontSize: 10 },
    },
    series: [
      {
        name: '总事件量',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        data: trend.value.total,
        lineStyle: { width: 2.5, color: '#ea580c' },
        itemStyle: { color: '#ea580c' },
        areaStyle: { color: 'rgba(234, 88, 12, 0.10)' },
      },
      {
        name: '高风险事件',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        data: trend.value.highRisk,
        lineStyle: { width: 2.5, color: '#2563eb' },
        itemStyle: { color: '#2563eb' },
        areaStyle: { color: 'rgba(37, 99, 235, 0.08)' },
      },
    ],
  }
}

function buildReportCountriesOption() {
  return {
    animation: false,
    grid: { left: 72, right: 16, top: 10, bottom: 14 },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#eef2f7' } },
      axisLabel: { color: '#6b7280', fontSize: 10 },
    },
    yAxis: {
      type: 'category',
      data: [...countries.value].reverse().map((item) => item.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#334155', fontSize: 10 },
    },
    series: [
      {
        type: 'bar',
        data: [...countries.value].reverse().map((item) => item.eventCount),
        barWidth: 12,
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
          color: '#0f766e',
        },
      },
    ],
  }
}

function buildReportIndustryOption() {
  return {
    animation: false,
    color: industryDistribution.value.map((item) => item.color),
    legend: {
      orient: 'vertical',
      right: 8,
      top: 'middle',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: '#52607a', fontSize: 10, width: 92, overflow: 'truncate' },
    },
    series: [
      {
        type: 'pie',
        radius: ['38%', '58%'],
        center: ['28%', '50%'],
        avoidLabelOverlap: true,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: {
          borderColor: '#ffffff',
          borderWidth: 2,
          borderRadius: 4,
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
        left: 82,
        top: '43%',
        style: {
          text: String(industryDistribution.value.length),
          fill: '#0f172a',
          fontSize: 22,
          fontWeight: 700,
          textAlign: 'center',
        },
      },
      {
        type: 'text',
        left: 76,
        top: '54%',
        style: {
          text: '行业',
          fill: '#94a3b8',
          fontSize: 10,
          textAlign: 'center',
        },
      },
    ],
  }
}

function buildReportActorsOption() {
  return {
    animation: false,
    grid: { left: 12, right: 48, top: 10, bottom: 20, containLabel: true },
    xAxis: {
      type: 'value',
      minInterval: 1,
      max: activeActorMax.value,
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#eef2f7' } },
      axisLabel: { color: '#64748b', fontSize: 10 },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: activeActors.value.map((item) => truncateLabel(item.actor, 16)),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#334155', fontSize: 10, width: 110, overflow: 'truncate' },
    },
    series: [
      {
        type: 'bar',
        data: activeActors.value.map((item) => item.value),
        barWidth: 12,
        label: {
          show: true,
          position: 'right',
          distance: 6,
          color: '#475569',
          fontSize: 10,
          fontWeight: 600,
        },
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
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
  }
}

function buildReportKeywordOption() {
  const rows = (monitoringKeywordStats.value.keywords || []).slice(0, 8)
  return {
    animation: false,
    grid: { left: 12, right: 20, top: 10, bottom: 20, containLabel: true },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#eef2f7' } },
      axisLabel: { color: '#64748b', fontSize: 10 },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map((item) => truncateLabel(item.keyword, 14)),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#334155', fontSize: 10, width: 96, overflow: 'truncate' },
    },
    series: [
      {
        type: 'bar',
        data: rows.map((item) => item.hits),
        barWidth: 12,
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 1,
            y2: 0,
            colorStops: [
              { offset: 0, color: '#c7d2fe' },
              { offset: 1, color: '#4338ca' },
            ],
          },
        },
      },
    ],
  }
}

async function exportSituationReport() {
  await nextTick()
  const {
    AlignmentType,
    BorderStyle,
    Document,
    HeadingLevel,
    ImageRun,
    Packer,
    PageBreak,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
    WidthType,
  } = await import('docx')

  const generatedAt = new Date().toLocaleString('zh-CN', { hour12: false })
  const topCountries = countries.value.slice(0, 10)
  const topActors = activeActors.value.slice(0, 10)
  const keyEvents = focusEvents.value.slice(0, 8)
  const monitoring = monitoringSummary.value || {}
  const sampleAlerts = sampleEvidenceAlerts.value.slice(0, 10)
  const keywordRows = (monitoringKeywordStats.value.keywords || []).slice(0, 10)
  const chartSections = [
    ['30 天攻击态势趋势', await renderReportChartImage(buildReportTrendOption(), REPORT_CHART_RENDER_WIDTH, REPORT_CHART_RENDER_HEIGHT)],
    ['受害国家 Top 10', await renderReportChartImage(buildReportCountriesOption(), REPORT_CHART_RENDER_WIDTH, REPORT_CHART_RENDER_HEIGHT)],
    ['重点受害行业分布', await renderReportChartImage(buildReportIndustryOption(), REPORT_CHART_RENDER_WIDTH, REPORT_CHART_RENDER_HEIGHT)],
    ['活跃泄露组织 Top 10', await renderReportChartImage(buildReportActorsOption(), REPORT_CHART_RENDER_WIDTH, REPORT_CHART_RENDER_HEIGHT)],
    ['重点监测规则命中统计', await renderReportChartImage(buildReportKeywordOption(), REPORT_CHART_RENDER_WIDTH, REPORT_CHART_RENDER_HEIGHT)],
  ]

  const metricCards = [
    ['近 30 天攻击事件总量', cards.value.totalEvents30d],
    ['近 30 天高风险事件', cards.value.highRisk30d],
    ['受害最多国家', cards.value.topCountry || '未知'],
    ['规则命中高优先事件', monitoring.highPriorityCount || 0],
    ['样本证据事件', monitoring.sampleEvidenceCount || 0],
    ['启用规则数', monitoring.enabledKeywordCount || 0],
  ]

  async function loadEventDetailForReport(eventId) {
    if (!eventId) return null
    const endpoint = String(eventId).startsWith('vuln:')
      ? `/api/vulnerabilities/${encodeURIComponent(eventId)}`
      : `/api/events/${encodeURIComponent(eventId)}`
    try {
      const response = await fetch(endpoint)
      if (!response.ok) return null
      return await response.json()
    } catch {
      return null
    }
  }

  async function dataUrlToUint8Array(dataUrl) {
    const response = await fetch(dataUrl)
    return new Uint8Array(await response.arrayBuffer())
  }

  function createTable(headers, rows) {
    return new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      rows: [
        new TableRow({
          tableHeader: true,
          children: headers.map((header) =>
            new TableCell({
              children: [new Paragraph({ children: [new TextRun({ text: String(header), bold: true })] })],
              shading: { fill: 'F8F9FC' },
            }),
          ),
        }),
        ...rows.map((row) =>
          new TableRow({
            children: row.map((cell) =>
              new TableCell({
                children: [new Paragraph(String(cell ?? ''))],
              }),
            ),
          }),
        ),
      ],
    })
  }

  function sectionHeading(text, level = HeadingLevel.HEADING_2) {
    return new Paragraph({
      text,
      heading: level,
      spacing: { before: 220, after: 120 },
      border: {
        left: { color: '2F6BFF', space: 8, style: BorderStyle.SINGLE, size: 12 },
      },
    })
  }

  const eventDetails = await Promise.all(
    keyEvents.map(async (item) => ({
      summary: item,
      detail: await loadEventDetailForReport(item.id),
    })),
  )

  const children = [
    new Paragraph({
      text: '威胁态势报告',
      heading: HeadingLevel.TITLE,
      spacing: { after: 120 },
    }),
    new Paragraph(`生成时间：${generatedAt}`),
    new Paragraph({
      text: executiveSummary.value,
      spacing: { after: 220 },
    }),
    sectionHeading('一、核心指标'),
    createTable(
      metricCards.map(([label]) => label),
      [metricCards.map(([, value]) => String(value))],
    ),
    sectionHeading('二、趋势图表'),
  ]

  for (const [title, imageUrl] of chartSections) {
    if (!imageUrl) continue
    children.push(sectionHeading(title, HeadingLevel.HEADING_3))
    children.push(
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 160 },
        children: [
          new ImageRun({
            data: await dataUrlToUint8Array(imageUrl),
            transformation: { width: 581, height: 361 },
          }),
        ],
      }),
    )
  }

  children.push(sectionHeading('三、关键统计'))
  children.push(sectionHeading('3.1 重点国家', HeadingLevel.HEADING_3))
  children.push(createTable(
    ['国家', '事件量', '高风险事件', '平均风险分'],
    topCountries.map((item) => [item.name, item.eventCount, item.highRiskCount, item.averageRiskScore]),
  ))
  children.push(sectionHeading('3.2 活跃泄露组织', HeadingLevel.HEADING_3))
  children.push(createTable(
    ['组织', '事件量', '平均风险分'],
    topActors.map((item) => [item.actor, item.value, item.averageRiskScore]),
  ))
  children.push(sectionHeading('3.3 监测规则命中摘要', HeadingLevel.HEADING_3))
  children.push(createTable(
    ['关键词', '命中次数', '高风险命中'],
    keywordRows.map((item) => [item.keyword, item.hits, item.highRiskHits]),
  ))
  children.push(sectionHeading('3.4 样本证据事件', HeadingLevel.HEADING_3))
  children.push(createTable(
    ['标题', '来源站点', '风险分', '样本链接数'],
    sampleAlerts.map((item) => [item.title, item.sourceSite, item.riskScore, item.sampleLinkCount]),
  ))

  children.push(sectionHeading('四、重点事件详解'))
  for (let index = 0; index < eventDetails.length; index += 1) {
    const { summary, detail } = eventDetails[index]
    const effective = detail || summary || {}
    const reasons = (effective.risk_reasons || effective.riskReasons || []).slice(0, 6)
    const matches = (effective.monitoring_matches || effective.monitoringMatches || []).map((item) => item.keyword).filter(Boolean)
    const sampleLinks = (effective.sample_links || effective.sampleLinks || []).map((item) => item.url || item).filter(Boolean)
    const detailText = effective.detail_text || effective.summary || summary.summary || '暂无详细内容'
    children.push(sectionHeading(`${index + 1}. ${summary.title || effective.title || '未命名事件'}`, HeadingLevel.HEADING_3))
    children.push(new Paragraph(`日期：${summary.disclosureDate || effective.disclosure_time || ''}    来源：${summary.sourceSite || effective.source || ''}    风险分：${summary.riskScore || effective.risk_score || ''}`))
    children.push(new Paragraph({ children: [new TextRun({ text: '概要：', bold: true }), new TextRun(String(detailText))] }))
    if (reasons.length) {
      children.push(new Paragraph({ children: [new TextRun({ text: '风险原因：', bold: true }), new TextRun(reasons.join('；'))] }))
    }
    if (matches.length) {
      children.push(new Paragraph({ children: [new TextRun({ text: '命中规则：', bold: true }), new TextRun(matches.join(' / '))] }))
    }
    if (sampleLinks.length) {
      children.push(new Paragraph({ children: [new TextRun({ text: '样本链接：', bold: true }), new TextRun(sampleLinks.join(' | '))] }))
    }
  }

  const doc = new Document({
    sections: [
      {
        properties: {},
        children,
      },
    ],
  })

  const blob = await Packer.toBlob(doc)
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `threat-situation-report-${new Date().toISOString().slice(0, 10)}.docx`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

function viewEventDetail(row) {
  if (!row?.id) return
  sessionStorage.setItem(`event-back:${row.id}`, '/threat-situation')
  router.push({ name: 'EventDetail', params: { eventId: row.id } })
}

function formatMatches(matches) {
  const items = (matches || []).map((item) => item.keyword).filter(Boolean)
  return items.length ? items.join(' / ') : '未命中'
}

function truncateLink(value, max = 60) {
  const text = String(value || '')
  if (text.length <= max) return text
  return `${text.slice(0, max - 1)}…`
}
</script>

<style scoped lang="scss">
.executive-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
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

.executive-hero__actions {
  flex-shrink: 0;
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

.monitoring-section,
.content-grid {
  margin-top: 22px;
}

.monitoring-section__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 18px;
}

.monitoring-section__header h3 {
  margin: 10px 0 0;
  color: var(--ti-text-primary);
  font-size: 24px;
}

.monitoring-summary-grid,
.content-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  align-items: stretch;
}

.monitoring-summary-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.monitoring-card,
.sample-alert-item {
  padding: 16px 18px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.9);
}

.monitoring-card__label {
  display: block;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.monitoring-card__value {
  display: block;
  margin-top: 8px;
  color: var(--ti-text-primary);
  font-size: 28px;
}

.monitoring-card p,
.sample-alert-item p {
  margin: 10px 0 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
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

.sample-alert-list {
  display: grid;
  gap: 12px;
  max-height: 272px;
  overflow-y: auto;
  padding-right: 6px;
}

.monitoring-panel {
  min-height: 360px;
}

.monitoring-panel--sample .ti-card-body {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.sample-alert-item__header,
.row-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.row-actions {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.sample-links {
  display: grid;
  gap: 6px;
  margin-top: 10px;
  color: var(--ti-text-secondary);
  font-size: 13px;
}

.sample-links a {
  color: #2f6bff;
  word-break: break-all;
}

.sample-alert-item strong {
  color: var(--ti-text-primary);
}

@media (max-width: 1280px) {
  .executive-hero {
    flex-direction: column;
  }

  .cards-grid,
  .charts-grid,
  .monitoring-summary-grid,
  .content-grid {
    grid-template-columns: 1fr;
  }

  .monitoring-section__header {
    flex-direction: column;
  }
}
</style>
