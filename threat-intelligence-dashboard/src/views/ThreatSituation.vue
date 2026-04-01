<template>
  <div class="threat-situation-page ti-page">
    <section class="ti-panel ti-reveal-up">
      <div class="overview-card">
        <div>
          <span class="ti-kicker">全局总览卡</span>
          <h3>{{ threatSituationSummary.title }}</h3>
          <p>{{ threatSituationSummary.description }}</p>
        </div>
        <div class="overview-card__stats">
          <div v-for="item in threatSituationSummary.stats" :key="item.label">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
      </div>
    </section>

    <section v-if="threatSituationBehavior.summaryCards?.length" class="ti-panel ti-reveal-up">
      <div class="summary-grid summary-grid--behavior">
        <ModuleSummaryCard
          v-for="card in threatSituationBehavior.summaryCards"
          :key="card.label"
          :label="card.label"
          :value="card.value"
          :description="card.description"
          :tone="card.tone"
          icon="DataAnalysis"
        />
      </div>
    </section>

    <section class="charts-grid">
      <section class="chart-group chart-group--global">
        <div class="chart-group__header">
          <span class="ti-kicker">全局态势组</span>
          <h3>跨模块总体态势</h3>
          <p>保留全局热区、结构占比和区域对比，用于总览层快速判断威胁分布。</p>
        </div>
        <div class="chart-group__grid">
          <ChartPanel
            eyebrow="区域热区"
            title="全球 / 区域威胁分布热力矩阵"
            description="以地区和攻击类型为二维坐标，突出高热威胁集中区域。"
            icon="Grid"
            height="330px"
          >
            <v-chart class="chart" :option="heatmapOption" autoresize />
          </ChartPanel>

          <ChartPanel
            eyebrow="结构占比"
            title="攻击类型占比环形图"
            description="勒索与数据泄露仍然是占比最高的两类活动。"
            icon="PieChart"
            height="330px"
          >
            <v-chart class="chart" :option="attackTypeOption" autoresize />
          </ChartPanel>

          <ChartPanel
            eyebrow="等级趋势"
            title="威胁等级变化趋势折线图"
            description="高危与中危告警保持上行，低危事件相对平稳。"
            icon="TrendCharts"
            height="300px"
          >
            <v-chart class="chart" :option="threatTrendOption" autoresize />
          </ChartPanel>

          <ChartPanel
            eyebrow="区域对比"
            title="区域威胁对比柱状图"
            description="便于快速识别需要单独展开的重点地区。"
            icon="Histogram"
            height="300px"
          >
            <v-chart class="chart" :option="regionalOption" autoresize />
          </ChartPanel>
        </div>
      </section>

      <section class="chart-group chart-group--ransomware">
        <div class="chart-group__header">
          <span class="ti-kicker">勒索趋势组</span>
          <h3>勒索情报图表集</h3>
          <p>从勒索模块页迁入的趋势、行业和组织活跃度图表统一放在这里查看。</p>
        </div>
        <div class="chart-group__grid">
          <ChartPanel
            eyebrow="勒索趋势"
            title="勒索事件趋势折线图"
            description="从勒索模块迁入，统一在态势页观察波动。"
            icon="TrendCharts"
            height="280px"
          >
            <v-chart class="chart" :option="ransomwareTrendOption" autoresize />
          </ChartPanel>

          <ChartPanel
            eyebrow="勒索行业"
            title="受影响行业横向条形图"
            description="制造、医疗与专业服务仍然是主要受害面。"
            icon="Histogram"
            height="280px"
          >
            <v-chart class="chart" :option="ransomwareIndustryOption" autoresize />
          </ChartPanel>

          <ChartPanel
            eyebrow="勒索组织"
            title="攻击组织活跃度排行"
            description="用于识别近期需要重点跟踪的团伙。"
            icon="DataAnalysis"
            height="280px"
          >
            <v-chart class="chart" :option="ransomwareActorOption" autoresize />
          </ChartPanel>
        </div>
      </section>

      <section class="chart-group chart-group--leak">
        <div class="chart-group__header">
          <span class="ti-kicker">泄露趋势组</span>
          <h3>数据泄露图表集</h3>
          <p>将数据泄露相关趋势、类型占比和行业 / 地区排行集中到同一阅读区。</p>
        </div>
        <div class="chart-group__grid">
          <ChartPanel
            eyebrow="泄露趋势"
            title="数据泄露事件趋势折线图"
            description="从数据泄露模块迁入，统一展示事件数量变化。"
            icon="TrendCharts"
            height="280px"
          >
            <v-chart class="chart" :option="dataLeakEventTrendOption" autoresize />
          </ChartPanel>

          <ChartPanel
            eyebrow="泄露类型"
            title="敏感信息类型占比"
            description="凭证、客户资料与源代码仍是主要暴露面。"
            icon="PieChart"
            height="300px"
          >
            <v-chart class="chart" :option="dataLeakTypeShareOption" autoresize />
          </ChartPanel>

          <ChartPanel
            eyebrow="泄露排行"
            title="泄露行业 / 地区排行图"
            description="帮助识别需要重点跟踪的暴露方向。"
            icon="Histogram"
            height="280px"
          >
            <v-chart class="chart" :option="dataLeakRankingOption" autoresize />
          </ChartPanel>
        </div>
      </section>

      <section class="chart-group chart-group--behavior">
        <div class="chart-group__header">
          <span class="ti-kicker">提取与分析</span>
          <h3>威胁情报提取与行为分析</h3>
          <p>将标准化事件、风险评分和行为信号直接并入态势页，避免再拆独立模块。</p>
        </div>
        <div class="chart-group__grid">
          <ChartPanel
            eyebrow="主体风险"
            title="高风险主体排行"
            description="按平均风险分与事件频率展示近期最活跃的主体。"
            icon="DataAnalysis"
            height="300px"
          >
            <v-chart class="chart" :option="behaviorActorOption" autoresize />
          </ChartPanel>

          <ChartPanel
            eyebrow="行业风险"
            title="高风险行业分布"
            description="帮助识别需要在论文中重点说明的高频受影响行业。"
            icon="Histogram"
            height="300px"
          >
            <v-chart class="chart" :option="behaviorIndustryOption" autoresize />
          </ChartPanel>
        </div>
      </section>
    </section>

    <section class="behavior-panels">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">行为分析信号</div>
          <StatusBadge label="规则型 MVP" tone="primary" :dot="false" />
        </div>
        <div class="ti-card-body">
          <div v-if="behaviorSignals.length" class="signal-list">
            <article
              v-for="signal in behaviorSignals"
              :key="signal.title"
              :class="['signal-card', `signal-card--${signal.tone || 'primary'}`]"
            >
              <h3>{{ signal.title }}</h3>
              <p>{{ signal.description }}</p>
            </article>
          </div>
          <p v-else class="empty-state">暂无行为分析信号。</p>
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">重复受害实体</div>
          <StatusBadge
            :label="`已提取 ${threatSituationBehavior.extractionStats?.dataLeakCount || 0} / ${threatSituationBehavior.extractionStats?.ransomwareCount || 0}`"
            tone="success"
            :dot="false"
          />
        </div>
        <div class="ti-card-body">
          <div v-if="victimRiskRanking.length" class="victim-list">
            <article v-for="item in victimRiskRanking.slice(0, 6)" :key="item.victim" class="victim-card">
              <div class="victim-card__meta">
                <h3>{{ item.victim }}</h3>
                <strong>{{ item.averageRiskScore }}</strong>
              </div>
              <p>重复事件 {{ item.eventCount }} 次</p>
              <span>{{ item.lastSeenAt || '暂无时间' }}</span>
            </article>
          </div>
          <p v-else class="empty-state">暂无重复受害实体。</p>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">异常风险事件</div>
        <StatusBadge label="可直接回溯详情" tone="danger" :dot="false" />
      </div>
      <div class="ti-card-body">
        <div class="ti-table-shell">
          <el-table :data="anomalyEvents" table-layout="auto" style="width: 100%">
            <el-table-column prop="title" label="事件标题" min-width="320" show-overflow-tooltip />
            <el-table-column prop="attacker" label="主体" min-width="140" />
            <el-table-column prop="victim" label="受害者" min-width="180" show-overflow-tooltip />
            <el-table-column prop="category" label="分类" min-width="120" />
            <el-table-column prop="riskScore" label="风险分" width="90" />
            <el-table-column prop="sourceSite" label="来源站点" min-width="120" />
            <el-table-column prop="disclosureTime" label="时间" min-width="150" />
            <el-table-column label="详情" width="100" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" @click="viewEventDetail(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">
          <el-icon><Bell /></el-icon>
          实时态势告警流
        </div>
        <StatusBadge label="列表式信息流" tone="primary" :dot="false" />
      </div>
      <div class="ti-card-body">
        <div class="alert-stream">
          <article
            v-for="item in situationAlerts"
            :key="item.title"
            :class="['alert-stream__item', `alert-stream__item--${item.level}`]"
          >
            <div class="alert-stream__meta">
              <StatusBadge :label="levelText[item.level]" :tone="levelTone[item.level]" />
              <span>{{ item.time }}</span>
            </div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.description }}</p>
            <div class="alert-stream__source">来源：{{ item.source }}</div>
          </article>
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
import ModuleSummaryCard from '@/components/common/ModuleSummaryCard.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useIntelligenceData } from '@/composables/useIntelligenceData'

const router = useRouter()
const { data } = useIntelligenceData()
const attackTypeShare = computed(() => data.value.attackTypeShare || [])
const dataLeakEventTrend = computed(() => data.value.dataLeakEventTrend || { labels: [], values: [] })
const dataLeakRanking = computed(() => data.value.dataLeakRanking || [])
const regionalThreatComparison = computed(() => data.value.regionalThreatComparison || [])
const ransomwareActorRanking = computed(() => data.value.ransomwareActorRanking || [])
const ransomwareIndustryImpact = computed(() => data.value.ransomwareIndustryImpact || [])
const ransomwareTrend = computed(() => data.value.ransomwareTrend || { labels: [], values: [] })
const sensitiveTypeShare = computed(() => data.value.sensitiveTypeShare || [])
const situationAlerts = computed(() => data.value.situationAlerts || [])
const threatHeatmap = computed(() => data.value.threatHeatmap || { regions: [], categories: [], values: [] })
const threatLevelTrend = computed(() => data.value.threatLevelTrend || { labels: [], high: [], medium: [], low: [] })
const threatSituationSummary = computed(() => data.value.threatSituationSummary || { title: '', description: '', stats: [] })
const threatSituationBehavior = computed(() => data.value.threatSituationBehavior || {})
const actorRiskRanking = computed(() => threatSituationBehavior.value.actorRiskRanking || [])
const victimRiskRanking = computed(() => threatSituationBehavior.value.victimRiskRanking || [])
const industryRiskDistribution = computed(() => threatSituationBehavior.value.industryRiskDistribution || [])
const anomalyEvents = computed(() => threatSituationBehavior.value.anomalyEvents || [])
const behaviorSignals = computed(() => threatSituationBehavior.value.behaviorSignals || [])

const levelText = {
  critical: '严重',
  high: '高危',
  medium: '中危'
}

const levelTone = {
  critical: 'danger',
  high: 'warning',
  medium: 'primary'
}

const heatmapOption = computed(() => ({
  tooltip: {
    position: 'top',
    formatter: (params) =>
      `${threatHeatmap.value.regions[params.value[0]]} / ${threatHeatmap.value.categories[params.value[1]]}<br/>热度指数: ${params.value[2]}`
  },
  grid: { left: 20, right: 20, top: 20, bottom: 10, containLabel: true },
  xAxis: {
    type: 'category',
    data: threatHeatmap.value.regions,
    axisLabel: { color: '#536074' },
    axisTick: { show: false },
    axisLine: { show: false }
  },
  yAxis: {
    type: 'category',
    data: threatHeatmap.value.categories,
    axisLabel: { color: '#536074' },
    axisTick: { show: false },
    axisLine: { show: false }
  },
  visualMap: {
    min: 0,
    max: 90,
    orient: 'horizontal',
    left: 'center',
    bottom: 0,
    calculable: false,
    textStyle: { color: '#7f8898' },
    inRange: {
      color: ['#f8efe0', '#ffd8b4', '#f2a65d', '#cf4432']
    }
  },
  series: [
    {
      type: 'heatmap',
      data: threatHeatmap.value.values,
      label: {
        show: true,
        color: '#1e2735',
        fontSize: 11
      },
      itemStyle: {
        borderRadius: 10,
        borderColor: 'rgba(255, 253, 250, 0.9)',
        borderWidth: 3
      }
    }
  ]
}))

const attackTypeOption = computed(() => ({
  tooltip: { trigger: 'item' },
  legend: {
    bottom: 0,
    textStyle: { color: '#536074' }
  },
  series: [
    {
      type: 'pie',
      radius: ['48%', '74%'],
      center: ['50%', '42%'],
      itemStyle: { borderRadius: 10, borderColor: '#fffdfa', borderWidth: 3 },
      label: { show: false },
      data: attackTypeShare.value.map((item, index) => ({
        ...item,
        itemStyle: {
          color: ['#cf4432', '#e88030', '#2d5dff', '#43a06e', '#7e8ca3'][index]
        }
      }))
    }
  ]
}))

const threatTrendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: {
    bottom: 0,
    textStyle: { color: '#536074' }
  },
  grid: { left: 10, right: 10, top: 10, bottom: 34, containLabel: true },
  xAxis: {
    type: 'category',
    data: threatLevelTrend.value.labels,
    axisLabel: { color: '#7f8898' },
    axisLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.16)' } }
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#7f8898' },
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } }
  },
  series: [
    {
      name: '高危',
      type: 'line',
      smooth: true,
      data: threatLevelTrend.value.high,
      lineStyle: { color: '#cf4432', width: 3 },
      itemStyle: { color: '#cf4432' }
    },
    {
      name: '中危',
      type: 'line',
      smooth: true,
      data: threatLevelTrend.value.medium,
      lineStyle: { color: '#e88030', width: 3 },
      itemStyle: { color: '#e88030' }
    },
    {
      name: '低危',
      type: 'line',
      smooth: true,
      data: threatLevelTrend.value.low,
      lineStyle: { color: '#2d5dff', width: 3 },
      itemStyle: { color: '#2d5dff' }
    }
  ]
}))

const regionalOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 10, right: 10, top: 10, bottom: 10, containLabel: true },
  xAxis: {
    type: 'category',
    data: regionalThreatComparison.value.map((item) => item.name),
    axisLabel: { color: '#536074' },
    axisTick: { show: false },
    axisLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.16)' } }
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#7f8898' },
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } }
  },
  series: [
    {
      type: 'bar',
      data: regionalThreatComparison.value.map((item) => item.value),
      barWidth: 24,
      itemStyle: {
        borderRadius: [10, 10, 0, 0],
        color: {
          type: 'linear',
          x: 0,
          y: 1,
          x2: 0,
          y2: 0,
          colorStops: [
            { offset: 0, color: '#dbe6ff' },
            { offset: 1, color: '#2d5dff' }
          ]
        }
      }
    }
  ]
}))

const ransomwareTrendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 10, right: 10, top: 10, bottom: 10, containLabel: true },
  xAxis: {
    type: 'category',
    data: ransomwareTrend.value.labels,
    axisLabel: { color: '#7f8898' },
    axisLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.16)' } }
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#7f8898' },
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } }
  },
  series: [
    {
      type: 'line',
      smooth: true,
      data: ransomwareTrend.value.values,
      symbolSize: 8,
      lineStyle: { color: '#cf4432', width: 3 },
      itemStyle: { color: '#cf4432' }
    }
  ]
}))

const ransomwareIndustryOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 10, right: 14, top: 10, bottom: 10, containLabel: true },
  xAxis: {
    type: 'value',
    axisLabel: { color: '#7f8898' },
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } }
  },
  yAxis: {
    type: 'category',
    data: ransomwareIndustryImpact.value.map((item) => item.name),
    axisLabel: { color: '#536074' },
    axisTick: { show: false },
    axisLine: { show: false }
  },
  series: [
    {
      type: 'bar',
      data: ransomwareIndustryImpact.value.map((item) => item.value),
      barWidth: 14,
      itemStyle: {
        borderRadius: [0, 8, 8, 0],
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 1,
          y2: 0,
          colorStops: [
            { offset: 0, color: '#ffd8b4' },
            { offset: 1, color: '#e88030' }
          ]
        }
      }
    }
  ]
}))

const ransomwareActorOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 10, right: 10, top: 10, bottom: 20, containLabel: true },
  xAxis: {
    type: 'category',
    data: ransomwareActorRanking.value.map((item) => item.name),
    axisLabel: { color: '#536074', interval: 0 },
    axisTick: { show: false },
    axisLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.16)' } }
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#7f8898' },
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } }
  },
  series: [
    {
      type: 'bar',
      data: ransomwareActorRanking.value.map((item) => item.value),
      barWidth: 20,
      itemStyle: {
        borderRadius: [8, 8, 0, 0],
        color: '#2d5dff'
      }
    }
  ]
}))

const dataLeakEventTrendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 10, right: 10, top: 10, bottom: 10, containLabel: true },
  xAxis: {
    type: 'category',
    data: dataLeakEventTrend.value.labels,
    axisLabel: { color: '#7f8898' },
    axisLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.16)' } }
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#7f8898' },
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } }
  },
  series: [
    {
      type: 'line',
      smooth: true,
      data: dataLeakEventTrend.value.values,
      symbolSize: 8,
      lineStyle: { color: '#2d5dff', width: 3 },
      itemStyle: { color: '#2d5dff' }
    }
  ]
}))

const dataLeakTypeShareOption = computed(() => ({
  tooltip: { trigger: 'item' },
  legend: {
    bottom: 0,
    textStyle: { color: '#536074' }
  },
  series: [
    {
      type: 'pie',
      radius: ['46%', '72%'],
      center: ['50%', '42%'],
      itemStyle: { borderRadius: 10, borderColor: '#fffdfa', borderWidth: 3 },
      label: { show: false },
      data: sensitiveTypeShare.value.map((item, index) => ({
        ...item,
        itemStyle: {
          color: ['#cf4432', '#e88030', '#2d5dff', '#43a06e', '#7e8ca3'][index]
        }
      }))
    }
  ]
}))

const dataLeakRankingOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 10, right: 14, top: 10, bottom: 10, containLabel: true },
  xAxis: {
    type: 'value',
    axisLabel: { color: '#7f8898' },
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } }
  },
  yAxis: {
    type: 'category',
    data: dataLeakRanking.value.map((item) => item.name),
    axisLabel: { color: '#536074' },
    axisTick: { show: false },
    axisLine: { show: false }
  },
  series: [
    {
      type: 'bar',
      data: dataLeakRanking.value.map((item) => item.value),
      barWidth: 14,
      itemStyle: {
        borderRadius: [0, 8, 8, 0],
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 1,
          y2: 0,
          colorStops: [
            { offset: 0, color: '#dbe6ff' },
            { offset: 1, color: '#2d5dff' }
          ]
        }
      }
    }
  ]
}))

function viewEventDetail(row) {
  if (!row?.id) return
  sessionStorage.setItem(`event-back:${row.id}`, '/threat-situation')
  router.push({ name: 'EventDetail', params: { eventId: row.id } })
}

const behaviorActorOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 14, right: 16, top: 10, bottom: 30, containLabel: true },
  xAxis: {
    type: 'category',
    data: actorRiskRanking.value.slice(0, 6).map((item) => item.actor),
    axisLabel: { color: '#536074', interval: 0 },
    axisTick: { show: false },
    axisLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.16)' } }
  },
  yAxis: {
    type: 'value',
    axisLabel: { color: '#7f8898' },
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } }
  },
  series: [
    {
      type: 'bar',
      data: actorRiskRanking.value.slice(0, 6).map((item) => item.averageRiskScore),
      barWidth: 22,
      itemStyle: {
        borderRadius: [10, 10, 0, 0],
        color: '#cf4432'
      }
    }
  ]
}))

const behaviorIndustryOption = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
  grid: { left: 16, right: 16, top: 10, bottom: 10, containLabel: true },
  xAxis: {
    type: 'value',
    axisLabel: { color: '#7f8898' },
    splitLine: { lineStyle: { color: 'rgba(87, 97, 123, 0.08)', type: 'dashed' } }
  },
  yAxis: {
    type: 'category',
    data: industryRiskDistribution.value.slice(0, 6).map((item) => item.name),
    axisTick: { show: false },
    axisLine: { show: false },
    axisLabel: { color: '#536074' }
  },
  series: [
    {
      type: 'bar',
      data: industryRiskDistribution.value.slice(0, 6).map((item) => item.averageRiskScore),
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
            { offset: 0, color: '#dbe6ff' },
            { offset: 1, color: '#2d5dff' }
          ]
        }
      }
    }
  ]
}))
</script>

<style scoped lang="scss">
.overview-card {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 1fr);
  gap: 24px;
  margin-top: 22px;
  padding: 22px;
  border-radius: 22px;
  border: 1px solid var(--ti-border-default);
  background: rgba(255, 255, 255, 0.68);
}

.overview-card h3 {
  margin: 10px 0 8px;
  font-size: 28px;
  color: var(--ti-text-primary);
}

.overview-card p {
  color: var(--ti-text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

.overview-card__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.overview-card__stats div {
  padding: 16px;
  border-radius: 18px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.72);
}

.overview-card__stats span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.overview-card__stats strong {
  display: block;
  margin-top: 6px;
  color: var(--ti-text-primary);
  font-size: 24px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
}

.summary-grid--behavior {
  margin-top: 0;
}

.charts-grid {
  display: grid;
  gap: 24px;
}

.chart-group {
  display: grid;
  gap: 16px;
}

.chart-group__header {
  padding: 0 4px;
}

.chart-group__header h3 {
  margin: 8px 0 6px;
  color: var(--ti-text-primary);
  font-size: 24px;
}

.chart-group__header p {
  color: var(--ti-text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

.chart-group__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px;
}

.chart {
  height: 100%;
}

.behavior-panels {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 22px;
}

.signal-list,
.victim-list {
  display: grid;
  gap: 14px;
}

.signal-card,
.victim-card {
  padding: 16px;
  border-radius: 18px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.7);
}

.signal-card--danger {
  border-left: 4px solid var(--ti-danger-strong);
}

.signal-card--warning {
  border-left: 4px solid var(--ti-warning-strong);
}

.signal-card--primary {
  border-left: 4px solid var(--ti-primary);
}

.signal-card--success {
  border-left: 4px solid var(--ti-success-strong);
}

.signal-card h3,
.victim-card h3 {
  margin: 0 0 8px;
  color: var(--ti-text-primary);
  font-size: 16px;
}

.signal-card p,
.victim-card p,
.victim-card span,
.empty-state {
  color: var(--ti-text-secondary);
  line-height: 1.7;
}

.victim-card__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.victim-card__meta strong {
  color: var(--ti-danger-strong);
  font-size: 22px;
}

.alert-stream {
  display: grid;
  gap: 14px;
}

.alert-stream__item {
  padding: 18px;
  border-radius: 20px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.7);
}

.alert-stream__item--critical {
  border-left: 4px solid var(--ti-danger-strong);
}

.alert-stream__item--high {
  border-left: 4px solid var(--ti-warning-strong);
}

.alert-stream__item--medium {
  border-left: 4px solid var(--ti-primary);
}

.alert-stream__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.alert-stream__item h3 {
  margin: 12px 0 6px;
  color: var(--ti-text-primary);
  font-size: 16px;
}

.alert-stream__item p {
  color: var(--ti-text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.alert-stream__source {
  margin-top: 10px;
  color: var(--ti-text-muted);
  font-size: 12px;
}

@media (max-width: 1440px) {
  .overview-card,
  .summary-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1024px) {
  .chart-group__grid,
  .behavior-panels {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 767px) {
  .overview-card__stats {
    grid-template-columns: 1fr;
  }
}
</style>
