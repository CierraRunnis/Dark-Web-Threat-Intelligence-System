<template>
  <section class="module-view">
    <header class="module-heading">
      <div>
        <h1>{{ model.title }}</h1>
        <p>{{ model.description }}</p>
      </div>
      <router-link class="module-action" :to="model.legacyPath">
        打开完整功能
        <el-icon><ArrowRight /></el-icon>
      </router-link>
    </header>

    <section class="module-metrics" :aria-label="`${model.title}核心指标`">
      <article v-for="(metric, index) in model.metrics" :key="metric.label" class="module-metric">
        <span class="module-metric__icon" :class="`module-metric__icon--${metric.tone || 'primary'}`">
          <el-icon><component :is="metric.icon || defaultIcons[index]" /></el-icon>
        </span>
        <div>
          <span>{{ metric.label }}</span>
          <strong>{{ formatNumber(metric.value) }}</strong>
          <small>{{ metric.description || metric.trend || '持续监测' }}</small>
        </div>
      </article>
    </section>

    <div class="module-grid">
      <section class="module-panel module-panel--trend">
        <header class="module-panel__header">
          <h2>{{ model.trendTitle }}</h2>
          <span>{{ model.periodLabel }}</span>
        </header>
        <v-chart class="module-chart" :option="trendOption" autoresize />
      </section>

      <section class="module-panel module-panel--ranking">
        <header class="module-panel__header">
          <h2>{{ model.rankingTitle }}</h2>
          <span>TOP {{ Math.min(model.ranking.length, 6) }}</span>
        </header>
        <div class="module-ranking">
          <article v-for="(item, index) in model.ranking.slice(0, 6)" :key="`${item.name}-${index}`">
            <span class="module-ranking__index">{{ String(index + 1).padStart(2, '0') }}</span>
            <div>
              <strong :title="item.name">{{ item.name }}</strong>
              <span><i :style="{ width: rankingWidth(item.value) }" /></span>
            </div>
            <b>{{ formatNumber(item.value) }}</b>
          </article>
          <div v-if="!model.ranking.length" class="module-empty">暂无分布数据</div>
        </div>
      </section>

      <section class="module-panel module-panel--table">
        <header class="module-panel__header">
          <h2>{{ model.tableTitle }}</h2>
          <span>{{ model.rows.length }} 条</span>
        </header>
        <div class="module-table">
          <div class="module-table__head" aria-hidden="true">
            <span>风险</span>
            <span>{{ model.columns.title }}</span>
            <span>{{ model.columns.category }}</span>
            <span>{{ model.columns.source }}</span>
            <span>{{ model.columns.time }}</span>
          </div>
          <article v-for="row in model.rows.slice(0, 9)" :key="row.key" class="module-table__row">
            <span class="module-severity" :class="`module-severity--${row.severity}`">{{ severityLabel(row.severity) }}</span>
            <div class="module-table__title">
              <strong :title="row.title">{{ row.title }}</strong>
              <small v-if="row.detail" :title="row.detail">{{ row.detail }}</small>
            </div>
            <span :title="row.category">{{ row.category || '-' }}</span>
            <span :title="row.source">{{ row.source || '-' }}</span>
            <time>{{ compactTime(row.time) || '-' }}</time>
          </article>
          <div v-if="!model.rows.length" class="module-empty module-empty--table">当前没有命中记录</div>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import '@/lib/echarts'
import { useIntelligenceData } from '@/composables/useIntelligenceData'
import { useJobsData } from '@/composables/useJobsData'
import { useDocumentExposureApi } from '@/composables/useDocumentExposureApi'
import { useCodeMonitoringApi } from '@/composables/useCodeMonitoringApi'
import * as fallback from '@/mock/intelligence'

const props = defineProps({
  moduleId: { type: String, required: true },
})

const { data: intelligence } = useIntelligenceData()
const { data: jobsState } = useJobsData()
const documentApi = useDocumentExposureApi()
const codeApi = useCodeMonitoringApi()
const monitorSummary = reactive({})
const monitorHits = ref([])

const defaultIcons = ['Bell', 'TrendCharts', 'OfficeBuilding', 'CircleCheck']

const meta = {
  ransomware: {
    title: '勒索情报',
    description: '跟踪勒索组织披露、受害实体、重点行业和攻击活动变化。',
    legacyPath: '/ransomware',
    trendTitle: '勒索披露趋势',
    rankingTitle: '活跃组织排行',
    tableTitle: '最新勒索事件',
  },
  'data-leak': {
    title: '数据泄露',
    description: '汇总公开泄露事件、敏感数据类型、受影响实体和交易线索。',
    legacyPath: '/data-leak',
    trendTitle: '泄露事件趋势',
    rankingTitle: '行业与地区分布',
    tableTitle: '最新泄露事件',
  },
  vulnerabilities: {
    title: '漏洞预警',
    description: '集中研判高危漏洞、真实利用状态、影响厂商和补丁可用性。',
    legacyPath: '/vulnerability-alerts',
    trendTitle: '高危漏洞趋势',
    rankingTitle: '影响厂商排行',
    tableTitle: '重点漏洞列表',
  },
  situation: {
    title: '威胁态势',
    description: '从跨模块趋势、风险级别和区域分布观察整体威胁变化。',
    legacyPath: '/threat-situation',
    trendTitle: '威胁等级变化',
    rankingTitle: '重点区域风险',
    tableTitle: '优先告警',
  },
  collector: {
    title: '采集控制',
    description: '查看采集任务、站点健康、浏览器运行环境和最近失败情况。',
    legacyPath: '/collector-control',
    trendTitle: '站点运行概况',
    rankingTitle: '站点连续失败',
    tableTitle: '站点健康状态',
  },
  netdisk: {
    title: '网盘监测',
    description: '监测公开网盘分享中的敏感文件、访问状态和人工复核进度。',
    legacyPath: '/document-exposure/netdisk',
    trendTitle: '网盘命中趋势',
    rankingTitle: '来源平台分布',
    tableTitle: '网盘命中记录',
  },
  'document-library': {
    title: '文库监测',
    description: '发现文库平台中的公开敏感文档并保留匹配与来源证据。',
    legacyPath: '/document-exposure/document-library',
    trendTitle: '文库命中趋势',
    rankingTitle: '来源平台分布',
    tableTitle: '文库命中记录',
  },
  'code-monitoring': {
    title: '代码监测',
    description: '发现公开代码仓库中的凭证、配置、敏感片段和企业关联线索。',
    legacyPath: '/document-exposure/code-monitoring',
    trendTitle: '代码命中趋势',
    rankingTitle: '代码平台分布',
    tableTitle: '代码命中记录',
  },
}

const source = (key) => {
  const value = intelligence.value?.[key]
  if (Array.isArray(value)) return value.length ? value : fallback[key] || []
  return value && Object.keys(value).length ? value : fallback[key] || {}
}

const model = computed(() => {
  const base = meta[props.moduleId] || meta.ransomware
  if (props.moduleId === 'ransomware') {
    return buildIntelModel(base, source('ransomwareSummary'), source('ransomwareTrend'), source('ransomwareActorRanking'), source('ransomwareEvents'), mapIntelRow)
  }
  if (props.moduleId === 'data-leak') {
    return buildIntelModel(base, ensureFourMetrics(source('dataLeakSummary'), source('dataLeakEvents')), source('dataLeakEventTrend'), source('dataLeakRanking'), source('dataLeakEvents'), mapIntelRow)
  }
  if (props.moduleId === 'vulnerabilities') {
    return buildIntelModel(base, source('vulnerabilitySummary'), source('vulnerabilityTrend'), source('vulnerabilityVendorRanking'), source('vulnerabilityEvents'), mapVulnerabilityRow)
  }
  if (props.moduleId === 'situation') return buildSituationModel(base)
  if (props.moduleId === 'collector') return buildCollectorModel(base)
  return buildMonitorModel(base, props.moduleId)
})

const trendOption = computed(() => {
  const trend = model.value.trend
  const series = Array.isArray(trend.series) && trend.series.length
    ? trend.series
    : [{ name: model.value.title, data: trend.values || [] }]
  return {
    animationDuration: 450,
    color: ['#2563eb', '#dc2626', '#f97316', '#0f766e'],
    tooltip: { trigger: 'axis', backgroundColor: '#111827', borderWidth: 0, textStyle: { color: '#fff', fontSize: 12 } },
    legend: { show: series.length > 1, top: 2, right: 8, itemWidth: 10, itemHeight: 3, textStyle: { color: '#64748b', fontSize: 10 } },
    grid: { left: 12, right: 14, top: series.length > 1 ? 38 : 22, bottom: 10, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: trend.labels || [], axisTick: { show: false }, axisLine: { lineStyle: { color: '#d8dee8' } }, axisLabel: { color: '#8491a3', fontSize: 10, hideOverlap: true } },
    yAxis: { type: 'value', axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#8491a3', fontSize: 10 }, splitLine: { lineStyle: { color: '#edf0f4' } } },
    series: series.map((item, index) => ({
      name: item.name,
      type: 'line',
      data: item.data || [],
      smooth: 0.28,
      showSymbol: false,
      lineStyle: { width: 2 },
      areaStyle: index === 0 ? { opacity: 0.06 } : undefined,
    })),
  }
})

function buildIntelModel(base, metrics, trend, ranking, rows, mapper) {
  return {
    ...base,
    periodLabel: '近 7 日',
    metrics: metrics.slice(0, 4),
    trend,
    ranking,
    rows: rows.map(mapper),
    columns: { title: '事件', category: '类型', source: '来源 / 主体', time: '披露时间' },
  }
}

function buildSituationModel(base) {
  const summary = source('threatSituationSummary')
  const behavior = source('threatSituationBehavior')
  const trend = source('threatLevelTrend')
  const metrics = (behavior.summaryCards || summary.stats || []).slice(0, 4)
  return {
    ...base,
    periodLabel: '近 7 日',
    metrics,
    trend: {
      labels: trend.labels || [],
      series: [
        { name: '高危', data: trend.high || [] },
        { name: '中危', data: trend.medium || [] },
        { name: '低危', data: trend.low || [] },
      ],
    },
    ranking: source('regionalThreatComparison'),
    rows: source('situationAlerts').map((item, index) => ({
      key: `alert-${index}`,
      title: item.title,
      detail: item.description,
      category: item.source,
      source: item.source,
      time: item.time,
      severity: item.level,
    })),
    columns: { title: '告警', category: '监测模块', source: '情报来源', time: '时间' },
  }
}

function buildCollectorModel(base) {
  const jobs = jobsState.value || {}
  const sites = Array.isArray(jobs.site_health) ? jobs.site_health : []
  const recentFailures = Array.isArray(jobs.recent_failures) ? jobs.recent_failures : []
  const browserWorkers = Number(jobs.browser_runtime?.browser_worker_count || 0)
  const metrics = [
    { label: '运行任务', value: jobs.running_jobs || 0, description: '当前执行中的采集任务', tone: 'primary', icon: 'VideoPlay' },
    { label: '站点总数', value: sites.length, description: '已配置采集站点', tone: 'success', icon: 'Connection' },
    { label: '24h 失败', value: jobs.failed_jobs_24h || 0, description: '最近 24 小时失败任务', tone: 'danger', icon: 'WarningFilled' },
    { label: '浏览器进程', value: browserWorkers, description: '浏览器采集工作进程', tone: 'warning', icon: 'Monitor' },
  ]
  const siteValues = sites.slice(0, 7).map((site) => Math.max(0, 3 - Number(site.consecutive_failures || 0)))
  const rows = sites.map((site, index) => ({
    key: site.site_name || `site-${index}`,
    title: site.site_name || site.name || '未命名站点',
    detail: site.last_error || site.message || '',
    category: site.overall_status || '未知',
    source: site.running_jobs ? `${site.running_jobs} 个任务` : '采集站点',
    time: site.last_success_at || site.updated_at || '',
    severity: siteSeverity(site),
  }))
  return {
    ...base,
    periodLabel: '实时',
    metrics,
    trend: { labels: sites.slice(0, 7).map((site) => site.site_name), values: siteValues },
    ranking: (recentFailures.length ? recentFailures : sites).map((item) => ({ name: item.site_name || item.site || item.name || '未知站点', value: Number(item.consecutive_failures || item.failure_count || 0) })),
    rows,
    columns: { title: '站点', category: '总体状态', source: '任务', time: '最近成功' },
  }
}

function buildMonitorModel(base, moduleId) {
  const isCode = moduleId === 'code-monitoring'
  const summary = monitorSummary
  const metrics = isCode
    ? [
        metric('公开仓库命中', summary.totalHits, '公开代码搜索命中总数', 'primary', 'Connection'),
        metric('敏感代码片段', summary.sensitiveSnippetCount, '规则识别的敏感片段', 'danger', 'WarningFilled'),
        metric('线索命中', summary.clueHitCount, '关键词关联结果', 'warning', 'Search'),
        metric('高风险仓库', summary.highRiskRepoCount, '需要优先人工复核', 'danger', 'Lock'),
      ]
    : [
        metric(moduleId === 'netdisk' ? '分享链接' : '公开文档', summary.totalHits, '最近扫描命中总数', 'primary', 'Files'),
        metric('高风险命中', summary.highRiskCount, '需要优先人工复核', 'danger', 'WarningFilled'),
        metric(moduleId === 'netdisk' ? '公开可访问' : '近 24h 新增', moduleId === 'netdisk' ? summary.publicCount : summary.recentCount, '当前有效结果', 'success', 'CircleCheck'),
        metric('待复核', summary.pendingReviewCount, '尚未完成人工研判', 'warning', 'View'),
      ]
  return {
    ...base,
    periodLabel: '最近扫描',
    metrics,
    trend: normalizeTrend(summary.trend),
    ranking: Array.isArray(summary.platformDistribution) ? summary.platformDistribution : [],
    rows: monitorHits.value.map((row, index) => mapMonitorRow(row, index, isCode)),
    columns: isCode
      ? { title: '仓库 / 文件', category: '敏感类型', source: '代码平台', time: '发现时间' }
      : { title: '文件 / 文档', category: '匹配关键词', source: '来源平台', time: '发现时间' },
  }
}

function mapIntelRow(item, index) {
  return {
    key: item.id || `${item.title}-${index}`,
    title: item.title || item.victim || '未命名事件',
    detail: item.region || item.summary || '',
    category: item.category || item.industry || '公开线索',
    source: item.attacker || item.sourceSite || item.industry || '公开来源',
    time: item.disclosureTime || item.disclosure_time || '',
    severity: normalizeSeverity(item.severity, item.riskScore),
  }
}

function mapVulnerabilityRow(item, index) {
  return {
    key: item.id || item.cveId || `vuln-${index}`,
    title: item.title || item.cveId || '未命名漏洞',
    detail: item.cveId || item.summary || '',
    category: item.category || item.product || '安全漏洞',
    source: item.vendor || item.product || '公开漏洞源',
    time: item.disclosureTime || item.disclosure_time || '',
    severity: normalizeSeverity(item.severity, item.cvss ? item.cvss * 10 : 0),
  }
}

function mapMonitorRow(row, index, isCode) {
  const repository = row.repositoryFullName || row.repositoryName || row.title || row.fileName || row.documentTitle || row.shareTitle
  const file = row.filePath || row.primaryFileName || row.filename || row.documentName
  return {
    key: row.id || `monitor-${index}`,
    title: [repository, file].filter(Boolean).join(' / ') || '未命名命中',
    detail: row.snippet || row.description || row.shareUrl || row.url || '',
    category: isCode ? (row.sensitiveLabel || row.sensitiveType || row.matchedTerm) : (row.matchedTerms?.join?.('、') || row.matchedTerm || row.fileType),
    source: row.platformLabel || row.platform || row.sourceName || '公开来源',
    time: row.discoveredAt || row.foundAt || row.createdAt || row.updatedAt || '',
    severity: normalizeSeverity(row.severity, row.riskScore),
  }
}

function ensureFourMetrics(metrics, events) {
  if (metrics.length >= 4) return metrics
  const highCount = events.filter((item) => ['critical', 'high'].includes(item.severity)).length
  return [...metrics, { label: '高风险事件', value: highCount, description: '需要优先人工研判', tone: 'danger', icon: 'WarningFilled' }]
}

function normalizeTrend(trend) {
  const rows = Array.isArray(trend) ? trend : []
  return {
    labels: rows.map((item) => item.date?.slice(5) || item.label || '-'),
    values: rows.map((item) => Number(item.value || 0)),
  }
}

function metric(label, value, description, tone, icon) {
  return { label, value: Number(value || 0), description, tone, icon }
}

function normalizeSeverity(value, score = 0) {
  const text = String(value || '').toLowerCase()
  if (text.includes('critical') || text.includes('严重')) return 'critical'
  if (text.includes('high') || text.includes('高')) return 'high'
  if (text.includes('medium') || text.includes('中')) return 'medium'
  if (text.includes('low') || text.includes('低')) return 'low'
  const numeric = Number(score || 0)
  if (numeric >= 80) return 'critical'
  if (numeric >= 60) return 'high'
  if (numeric >= 30) return 'medium'
  return 'low'
}

function siteSeverity(site) {
  const status = String(site.overall_status || '').toLowerCase()
  if (status.includes('失败') || status.includes('异常') || Number(site.consecutive_failures || 0) >= 3) return 'critical'
  if (status.includes('警告') || Number(site.consecutive_failures || 0) > 0) return 'high'
  return 'low'
}

function severityLabel(value) {
  return { critical: '严重', high: '高危', medium: '中危', low: '正常' }[value] || '关注'
}

function formatNumber(value) {
  if (value === '' || value == null) return 0
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : value
}

function compactTime(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  const matched = text.match(/(\d{2}-\d{2})[ T](\d{2}:\d{2})/)
  if (matched) return `${matched[1]} ${matched[2]}`
  return text.length > 16 ? text.slice(0, 16) : text
}

function rankingWidth(value) {
  const max = Math.max(...model.value.ranking.map((item) => Number(item.value || 0)), 1)
  return `${Math.max(5, (Number(value || 0) / max) * 100)}%`
}

async function loadMonitorData(moduleId) {
  if (!['netdisk', 'document-library', 'code-monitoring'].includes(moduleId)) return
  for (const key of Object.keys(monitorSummary)) delete monitorSummary[key]
  monitorHits.value = []
  try {
    if (moduleId === 'code-monitoring') {
      const [summary, hits] = await Promise.all([codeApi.loadSummary(), codeApi.loadHits({ limit: 100, includeSuppressed: true })])
      Object.assign(monitorSummary, summary || {})
      monitorHits.value = Array.isArray(hits) ? hits : []
      return
    }
    const sourceFamily = moduleId === 'netdisk' ? 'netdisk_aggregator' : 'document_library'
    const [summary, hits] = await Promise.all([
      documentApi.loadSummary({ sourceFamily }),
      documentApi.loadHits({ sourceFamily, limit: 100 }),
    ])
    Object.assign(monitorSummary, summary || {})
    monitorHits.value = Array.isArray(hits) ? hits : []
  } catch {
    // Keep the module usable when a monitoring source has not been configured yet.
  }
}

watch(() => props.moduleId, loadMonitorData, { immediate: true })
</script>

<style scoped lang="scss">
.module-view { min-width: 0; }

.module-heading {
  display: flex;
  min-width: 0;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
}

.module-heading h1 { margin: 0; font-size: 24px; line-height: 1.25; }
.module-heading p { max-width: 760px; margin: 6px 0 0; color: var(--ops-muted); font-size: 12px; line-height: 1.6; }

.module-action {
  display: inline-flex;
  min-height: 34px;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  padding: 0 12px;
  border: 1px solid var(--ops-border);
  border-radius: 6px;
  background: #fff;
  color: #334155;
  font-size: 11px;
  font-weight: 700;
}

.module-action:hover { border-color: #9aa6b5; color: var(--ops-blue); }

.module-metrics {
  display: grid;
  min-width: 0;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 16px;
  border: 1px solid var(--ops-border);
  border-radius: 8px;
  background: #fff;
}

.module-metric {
  display: grid;
  min-width: 0;
  grid-template-columns: 34px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
}

.module-metric + .module-metric { border-left: 1px solid var(--ops-border-soft); }
.module-metric__icon { display: inline-flex; width: 32px; height: 32px; align-items: center; justify-content: center; border-radius: 6px; background: #e8eefc; color: var(--ops-blue); }
.module-metric__icon--danger { background: #fee2e2; color: var(--ops-red); }
.module-metric__icon--warning { background: #ffedd5; color: var(--ops-orange); }
.module-metric__icon--success { background: #ccfbf1; color: var(--ops-green); }
.module-metric > div { display: grid; min-width: 0; }
.module-metric span { color: var(--ops-muted); font-size: 10px; }
.module-metric strong { margin-top: 2px; font-family: var(--ti-font-mono); font-size: 22px; line-height: 1.2; }
.module-metric small { overflow: hidden; margin-top: 3px; color: #7b8797; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }

.module-grid { display: grid; min-width: 0; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; }
.module-panel { min-width: 0; overflow: hidden; border: 1px solid var(--ops-border); border-radius: 8px; background: #fff; }
.module-panel--table { grid-column: 1 / -1; }
.module-panel__header { display: flex; min-height: 54px; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 15px; border-bottom: 1px solid var(--ops-border-soft); }
.module-panel__header h2 { margin: 0; font-size: 14px; }
.module-panel__header span { color: var(--ops-muted); font-family: var(--ti-font-mono); font-size: 10px; }
.module-chart { width: 100%; height: 270px; padding: 8px 12px 12px; }

.module-ranking { padding: 7px 14px; }
.module-ranking article { display: grid; min-height: 41px; grid-template-columns: 26px minmax(0, 1fr) auto; align-items: center; gap: 8px; }
.module-ranking article + article { border-top: 1px solid var(--ops-border-soft); }
.module-ranking__index { color: #94a3b8; font-family: var(--ti-font-mono); font-size: 9px; }
.module-ranking article > div { display: grid; min-width: 0; gap: 5px; }
.module-ranking strong { overflow: hidden; color: #334155; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.module-ranking article > div > span { display: block; height: 3px; overflow: hidden; border-radius: 2px; background: #eef1f5; }
.module-ranking i { display: block; height: 100%; border-radius: inherit; background: var(--ops-blue); }
.module-ranking b { color: #475569; font-family: var(--ti-font-mono); font-size: 10px; }

.module-table__head,
.module-table__row { display: grid; min-width: 0; grid-template-columns: 60px minmax(220px, 1.8fr) minmax(110px, 0.8fr) minmax(100px, 0.7fr) 92px; align-items: center; gap: 12px; }
.module-table__head { min-height: 34px; padding: 0 15px; background: #f8f9fb; color: #8491a3; font-size: 9px; font-weight: 700; }
.module-table__row { min-height: 55px; padding: 8px 15px; border-top: 1px solid var(--ops-border-soft); color: #536274; font-size: 10px; }
.module-table__head + .module-table__row { border-top: 0; }
.module-table__row:hover { background: #f8fafc; }
.module-table__row > span:not(.module-severity), .module-table__row time { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.module-table__row time { color: #8491a3; font-family: var(--ti-font-mono); }
.module-table__title { display: grid; min-width: 0; gap: 3px; }
.module-table__title strong, .module-table__title small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.module-table__title strong { color: #263445; font-size: 11px; }
.module-table__title small { color: #8491a3; font-size: 9px; }
.module-severity { display: inline-flex; width: 42px; height: 20px; align-items: center; justify-content: center; border-radius: 4px; font-size: 9px; font-weight: 700; }
.module-severity--critical { background: #fee2e2; color: #b91c1c; }
.module-severity--high { background: #ffedd5; color: #c2410c; }
.module-severity--medium { background: #fef3c7; color: #a16207; }
.module-severity--low { background: #d1fae5; color: #047857; }
.module-empty { display: grid; min-height: 140px; place-items: center; color: #94a3b8; font-size: 11px; }
.module-empty--table { min-height: 90px; }

@media (max-width: 1024px) {
  .module-grid { grid-template-columns: minmax(0, 1fr) 280px; }
  .module-table__head, .module-table__row { grid-template-columns: 56px minmax(180px, 1fr) minmax(90px, 0.6fr) 82px; }
  .module-table__head span:nth-child(4), .module-table__row > span:nth-child(4) { display: none; }
}

@media (max-width: 820px) {
  .module-grid { grid-template-columns: 1fr; }
  .module-panel--table { grid-column: auto; }
}

@media (max-width: 760px) {
  .module-heading { align-items: flex-start; }
  .module-heading h1 { font-size: 20px; }
  .module-heading p { max-width: 36ch; }
  .module-action { width: 34px; padding: 0; justify-content: center; font-size: 0; }
  .module-action .el-icon { font-size: 14px; }
  .module-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .module-metric:nth-child(3) { border-left: 0; }
  .module-metric:nth-child(n + 3) { border-top: 1px solid var(--ops-border-soft); }
  .module-table__head { display: none; }
  .module-table__row { grid-template-columns: 48px minmax(0, 1fr) 72px; min-height: 60px; gap: 8px; }
  .module-table__row > span:nth-child(3), .module-table__row > span:nth-child(4) { display: none; }
}

@media (max-width: 420px) {
  .module-metric { padding: 12px 10px; }
  .module-metric__icon { width: 28px; height: 28px; }
  .module-metric strong { font-size: 18px; }
}
</style>
