<template>
  <div class="dashboard-page ti-page">
    <section class="ti-panel ti-reveal-up dashboard-hero">
      <SectionHeader
        eyebrow="Threat Intelligence Dashboard"
        title="编辑化卡片视角下的威胁情报总览"
      />

      <div class="dashboard-hero__summary">
        <ModuleSummaryCard
          v-for="card in visibleDashboardSummaryCards"
          :key="card.label"
          v-bind="card"
        />
      </div>
    </section>

    <section class="dashboard-main ti-page-grid">
      <ChartPanel
        eyebrow="态势摘要"
        title="跨模块趋势概览"
        icon="TrendCharts"
        height="330px"
      >
        <v-chart class="dashboard-chart" :option="overviewTrendOption" autoresize />
      </ChartPanel>

      <div class="ti-card dashboard-watchlist ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">
            <el-icon><Bell /></el-icon>
            观察重点
          </div>
          <StatusBadge label="人工跟踪池" tone="warning" :dot="false" />
        </div>
        <div class="ti-card-body">
          <div class="dashboard-watchlist__list">
            <article
              v-for="item in dashboardWatchlist"
              :key="item.title"
              class="dashboard-watchlist__item"
            >
              <StatusBadge :label="item.module" :tone="item.tone" />
              <h3>{{ item.title }}</h3>
              <p>{{ item.note }}</p>
            </article>
          </div>
        </div>
      </div>
    </section>

    <section class="module-preview">
      <SectionHeader
        eyebrow="模块重点"
        title="核心模块预览"
        description="首页只展示最值得展开查看的重点，深度内容留在各模块页完成。"
      />

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
          <StatusBadge label="过去 4 小时" tone="primary" :dot="false" />
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

      <ChartPanel
        eyebrow="重点国家"
        title="国家与地区暴露分布"
        icon="MapLocation"
        height="320px"
      >
        <div class="dashboard-focus__body">
          <div class="dashboard-focus__chart">
            <v-chart class="dashboard-chart" :option="countryFocusOption" autoresize />
          </div>

          <aside class="dashboard-focus__aside">
            <div class="dashboard-focus__stats">
              <article class="dashboard-focus__stat">
                <span>头部地区</span>
                <strong>{{ leadCountry.name || '暂无' }}</strong>
                <small>暴露强度 {{ leadCountry.value || 0 }}</small>
              </article>
              <article class="dashboard-focus__stat">
                <span>头部占比</span>
                <strong>{{ leadCountryShare }}%</strong>
                <small>前 1 位占总关注强度</small>
              </article>
            </div>

            <div class="dashboard-focus__ranking">
              <article
                v-for="(item, index) in rankedCountryFocus"
                :key="item.name"
                class="dashboard-focus__ranking-item"
              >
                <span class="dashboard-focus__rank">#{{ index + 1 }}</span>
                <div class="dashboard-focus__meta">
                  <strong>{{ item.name }}</strong>
                  <small>暴露强度 {{ item.value }}</small>
                </div>
                <span class="dashboard-focus__share">{{ item.share }}%</span>
              </article>
            </div>
          </aside>
        </div>
      </ChartPanel>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { Bell, Connection, Right } from '@element-plus/icons-vue'
import '@/lib/echarts'
import ChartPanel from '@/components/common/ChartPanel.vue'
import ModuleSummaryCard from '@/components/common/ModuleSummaryCard.vue'
import SectionHeader from '@/components/common/SectionHeader.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useIntelligenceData } from '@/composables/useIntelligenceData'

const { data } = useIntelligenceData()
const crossModuleTimeline = computed(() => data.value.crossModuleTimeline || [])
const dashboardCountryFocus = computed(() => data.value.dashboardCountryFocus || [])
const dashboardSummaryCards = computed(() => data.value.dashboardSummaryCards || [])
const dashboardTrendSeries = computed(() => data.value.dashboardTrendSeries || { labels: [], ransomware: [], dataLeak: [], vulnerability: [], threatAlerts: [] })
const dashboardWatchlist = computed(() => data.value.dashboardWatchlist || [])
const modulePreviewCards = computed(() => data.value.modulePreviewCards || [])

const visibleDashboardSummaryCards = computed(() =>
  dashboardSummaryCards.value.filter((card) => card?.label !== '爬虫任务')
)

const countryFocusTotal = computed(() =>
  dashboardCountryFocus.value.reduce((total, item) => total + Number(item.value || 0), 0)
)

const leadCountry = computed(() => dashboardCountryFocus.value[0] || { name: '', value: 0 })

const leadCountryShare = computed(() => {
  if (!countryFocusTotal.value || !leadCountry.value.value) return 0
  return Math.round((Number(leadCountry.value.value || 0) / countryFocusTotal.value) * 100)
})

const rankedCountryFocus = computed(() =>
  dashboardCountryFocus.value.slice(0, 5).map((item) => ({
    ...item,
    share: countryFocusTotal.value ? Math.round((Number(item.value || 0) / countryFocusTotal.value) * 100) : 0,
  }))
)

const overviewTrendOption = computed(() => ({
  color: ['#2d5dff', '#e88030', '#8a3ffc', '#cf4432'],
  tooltip: {
    trigger: 'axis',
    backgroundColor: 'rgba(255, 253, 250, 0.96)',
    borderColor: 'rgba(63, 80, 104, 0.12)',
    textStyle: { color: '#1e2735' }
  },
  legend: {
    bottom: 0,
    textStyle: { color: '#536074' }
  },
  grid: { left: 10, right: 16, top: 16, bottom: 38, containLabel: true },
  xAxis: {
    type: 'category',
    data: dashboardTrendSeries.value.labels,
    axisLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.16)' } },
    axisLabel: { color: '#7f8898' }
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } },
    axisLabel: { color: '#7f8898' }
  },
  series: [
    {
      name: '勒索披露',
      type: 'line',
      smooth: true,
      symbolSize: 8,
      data: dashboardTrendSeries.value.ransomware
    },
    {
      name: '数据泄露',
      type: 'line',
      smooth: true,
      symbolSize: 8,
      data: dashboardTrendSeries.value.dataLeak
    },
    {
      name: '漏洞预警',
      type: 'line',
      smooth: true,
      symbolSize: 8,
      data: dashboardTrendSeries.value.vulnerability,
      lineStyle: { color: '#8a3ffc' },
      itemStyle: { color: '#8a3ffc' }
    },
    {
      name: '总体告警',
      type: 'line',
      smooth: true,
      symbolSize: 8,
      data: dashboardTrendSeries.value.threatAlerts
    }
  ]
}))

const countryFocusOption = computed(() => ({
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    backgroundColor: 'rgba(255, 253, 250, 0.96)',
    borderColor: 'rgba(63, 80, 104, 0.12)',
    textStyle: { color: '#1e2735' }
  },
  grid: { left: 16, right: 16, top: 10, bottom: 10, containLabel: true },
  xAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } },
    axisLabel: { color: '#7f8898' }
  },
  yAxis: {
    type: 'category',
    data: dashboardCountryFocus.value.map((item) => item.name),
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { color: '#536074' }
  },
  series: [
    {
      type: 'bar',
      data: dashboardCountryFocus.value.map((item) => item.value),
      barWidth: 14,
      itemStyle: {
        borderRadius: [0, 10, 10, 0],
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 1,
          y2: 0,
          colorStops: [
            { offset: 0, color: '#ffcf9f' },
            { offset: 1, color: '#e88030' }
          ]
        }
      }
    }
  ]
}))
</script>

<style scoped lang="scss">
.dashboard-hero__summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
  margin-top: 22px;
}

.dashboard-main {
  grid-template-columns: minmax(0, 1.6fr) minmax(320px, 0.9fr);
}

.dashboard-chart {
  height: 100%;
}

.dashboard-watchlist__list {
  display: grid;
  gap: 14px;
}

.dashboard-watchlist__item {
  padding: 16px;
  border-radius: 18px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.6);
}

.dashboard-watchlist__item h3 {
  margin: 10px 0 6px;
  font-size: 15px;
  color: var(--ti-text-primary);
}

.dashboard-watchlist__item p {
  color: var(--ti-text-secondary);
  font-size: 13px;
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
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
  align-items: start;
}

.dashboard-focus__body {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(220px, 0.9fr);
  gap: 18px;
  align-items: stretch;
  height: 100%;
}

.dashboard-focus__chart {
  min-height: 260px;
}

.dashboard-focus__aside {
  display: grid;
  gap: 12px;
}

.dashboard-focus__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.dashboard-focus__stat,
.dashboard-focus__ranking-item {
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.68);
}

.dashboard-focus__stat span,
.dashboard-focus__stat small,
.dashboard-focus__meta small,
.dashboard-focus__share {
  color: var(--ti-text-muted);
}

.dashboard-focus__stat span {
  display: block;
  margin-bottom: 8px;
  font-size: 12px;
}

.dashboard-focus__stat strong {
  display: block;
  color: var(--ti-text-primary);
  font-size: 24px;
  line-height: 1.1;
}

.dashboard-focus__stat small {
  display: block;
  margin-top: 6px;
  font-size: 12px;
}

.dashboard-focus__ranking {
  display: grid;
  gap: 10px;
}

.dashboard-focus__ranking-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.dashboard-focus__rank {
  display: inline-flex;
  min-width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(232, 128, 48, 0.12);
  color: var(--ti-accent-strong);
  font-size: 12px;
  font-weight: 700;
}

.dashboard-focus__meta {
  min-width: 0;
}

.dashboard-focus__meta strong {
  display: block;
  color: var(--ti-text-primary);
  font-size: 14px;
}

.dashboard-focus__meta small,
.dashboard-focus__share {
  font-size: 12px;
}

.dashboard-focus__share {
  font-weight: 700;
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
  .dashboard-hero__summary,
  .module-preview__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1024px) {
  .dashboard-main,
  .dashboard-bottom,
  .dashboard-focus__body {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 767px) {
  .dashboard-hero__summary,
  .module-preview__grid,
  .module-preview__stats,
  .dashboard-focus__stats {
    grid-template-columns: 1fr;
  }

  .timeline-list__item {
    grid-template-columns: 1fr;
    gap: 8px;
  }
}
</style>
