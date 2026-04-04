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
import ChartPanel from '@/components/common/ChartPanel.vue'
import { useIntelligenceData } from '@/composables/useIntelligenceData'

const router = useRouter()
const { data } = useIntelligenceData()

const cards = computed(() => data.value.threatExecutiveCards || {
  totalEvents30d: 0,
  totalEventsDeltaPct: 0,
  highRisk30d: 0,
  highRiskDeltaPct: 0,
  topCountry: '未知',
  topCountryEventCount: 0
})

const coverage = computed(() => data.value.threatExecutiveCoverage || {
  countryCoverageRate: 0,
  regionCoverageRate: 0,
  industryCoverageRate: 0
})

const trend = computed(() => data.value.threatExecutiveTrend || {
  labels: [],
  total: [],
  highRisk: []
})

const countries = computed(() => data.value.threatExecutiveCountries || [])
const priorityEvents = computed(() => data.value.threatExecutivePriorityEvents || [])

const executiveSummary = computed(() => {
  const totalTrend = cards.value.totalEventsDeltaPct >= 0 ? '上升' : '下降'
  const riskTrend = cards.value.highRiskDeltaPct >= 0 ? '增加' : '下降'
  return `攻击事件总体呈${totalTrend}趋势，高风险事件持续${riskTrend}，当前受害最多国家为 ${cards.value.topCountry || '未知'}。`
})

const trendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: {
    bottom: 0,
    textStyle: { color: '#6b7280' }
  },
  grid: {
    top: 20,
    right: 16,
    bottom: 42,
    left: 44
  },
  xAxis: {
    type: 'category',
    data: trend.value.labels,
    boundaryGap: false,
    axisLine: { lineStyle: { color: '#d1d5db' } },
    axisLabel: { color: '#6b7280' }
  },
  yAxis: {
    type: 'value',
    axisLine: { show: false },
    splitLine: { lineStyle: { color: '#eef2f7' } },
    axisLabel: { color: '#6b7280' }
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
      areaStyle: { color: 'rgba(234, 88, 12, 0.10)' }
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
      areaStyle: { color: 'rgba(37, 99, 235, 0.08)' }
    }
  ]
}))

const countriesOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: {
    top: 20,
    right: 16,
    bottom: 20,
    left: 72
  },
  xAxis: {
    type: 'value',
    axisLine: { show: false },
    splitLine: { lineStyle: { color: '#eef2f7' } },
    axisLabel: { color: '#6b7280' }
  },
  yAxis: {
    type: 'category',
    data: [...countries.value].reverse().map((item) => item.name),
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: '#334155' }
  },
  series: [
    {
      name: '事件量',
      type: 'bar',
      data: [...countries.value].reverse().map((item) => item.eventCount),
      barWidth: 18,
      itemStyle: {
        borderRadius: [0, 8, 8, 0],
        color: '#0f766e'
      }
    }
  ]
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
  border-radius: 20px;
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
