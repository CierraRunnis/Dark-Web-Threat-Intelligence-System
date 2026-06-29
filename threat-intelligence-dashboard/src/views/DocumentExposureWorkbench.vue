<template>
  <div class="monitoring-workbench ti-page">
    <section v-if="sourceFamily === 'netdisk_aggregator'" class="netdisk-board">
      <header class="netdisk-toolbar">
        <div class="netdisk-title">
          <h2>网盘监测</h2>
          <el-icon><InfoFilled /></el-icon>
        </div>
        <div class="netdisk-toolbar__controls">
          <div class="segmented-control">
            <button
              v-for="item in rangeTabs"
              :key="item.key"
              type="button"
              :class="{ active: selectedRange === item.key }"
              @click="selectRange(item.key)"
            >
              {{ item.label }}
            </button>
          </div>
          <el-date-picker
            v-if="selectedRange === 'custom'"
            v-model="customDateRange"
            class="netdisk-custom-range"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
            :clearable="false"
            size="small"
          />
          <span class="toolbar-divider"></span>
          <div class="segmented-control segmented-control--platform">
            <button
              v-for="item in netdiskPlatformTabs"
              :key="item.key"
              type="button"
              :class="{ active: selectedSource === item.key }"
              @click="selectedSource = item.key"
            >
              {{ item.label }}
            </button>
          </div>
          <el-button plain class="netdisk-settings-btn" title="网盘监测配置" @click="router.push(currentConfig.settingsRoute)">
            <el-icon><Setting /></el-icon>
          </el-button>
          <el-input v-model="keyword" clearable class="netdisk-search" placeholder="请输入关键词、文件名或链接">
            <template #suffix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-button plain class="advanced-filter-btn">
            <el-icon><Filter /></el-icon>
            高级筛选
          </el-button>
        </div>
      </header>

      <section class="netdisk-metric-grid">
        <article v-for="card in netdiskMetricCards" :key="card.label" class="netdisk-metric-card">
          <div>
            <span>{{ card.label }}</span>
            <strong>{{ formatNumber(card.value) }}</strong>
            <small>较昨日 <b :class="card.deltaType">{{ card.delta }}</b></small>
          </div>
          <div :class="['netdisk-metric-icon', `netdisk-metric-icon--${card.icon}`]">
            <el-icon v-if="card.icon === 'link'"><Link /></el-icon>
            <el-icon v-else-if="card.icon === 'alert'"><WarningFilled /></el-icon>
            <el-icon v-else-if="card.icon === 'lock'"><Lock /></el-icon>
            <el-icon v-else><Connection /></el-icon>
          </div>
        </article>
      </section>

      <section class="netdisk-chart-grid">
        <article class="netdisk-panel netdisk-panel--trend">
          <div class="netdisk-panel__title">
            <h3>分享链接趋势</h3>
            <span>{{ rangeDisplayLabel }}</span>
          </div>
          <v-chart class="netdisk-chart" :option="netdiskTrendOption" autoresize />
        </article>
        <article class="netdisk-panel netdisk-panel--distribution">
          <div class="netdisk-panel__title">
            <h3>平台分布</h3>
          </div>
          <div class="netdisk-distribution">
            <v-chart class="netdisk-donut" :option="netdiskDistributionOption" autoresize />
            <div class="netdisk-legend">
              <div v-for="item in netdiskLegendRows" :key="item.name" class="netdisk-legend__row">
                <span :style="{ background: item.color }"></span>
                <strong>{{ item.name }}</strong>
                <em>{{ formatNumber(item.value) }} ({{ item.shareText }})</em>
              </div>
            </div>
          </div>
        </article>
      </section>

      <section class="netdisk-panel netdisk-panel--table">
        <div class="netdisk-panel__title netdisk-panel__title--table">
          <h3>检测结果列表（共 {{ formatNumber(filteredHits.length) }} 条）</h3>
        </div>
        <div class="netdisk-table-shell">
          <el-table :data="pagedHits" table-layout="fixed" :row-class-name="tableRowClassName">
            <el-table-column
              v-for="column in currentConfig.columns"
              :key="column.key"
              :label="column.label"
              :min-width="column.minWidth"
              :width="column.width"
              show-overflow-tooltip
            >
              <template #default="{ row }">
                <span v-if="column.key === 'primaryFileName'" class="file-cell">
                  <span :class="['file-type-icon', `file-type-icon--${fileTypeClass(row)}`]">{{ fileTypeLabel(row) }}</span>
                  <span class="file-cell__name">{{ primaryFileName(row) }}</span>
                </span>
                <span v-else-if="column.key === 'platformLabel'" class="platform-cell">
                  <img
                    v-if="platformIconUrl(row)"
                    class="platform-logo"
                    :src="platformIconUrl(row)"
                    :alt="platformDisplayLabel(row)"
                    loading="lazy"
                  />
                  <span v-else :class="['platform-icon', `platform-icon--${platformIconClass(row)}`]">{{ platformIconText(row) }}</span>
                  <span>{{ platformDisplayLabel(row) }}</span>
                </span>
                <span v-else-if="column.key === 'shareType'" :class="['share-type-pill', `share-type-pill--${row.shareType || 'public_share'}`]">
                  {{ shareTypeLabel(row) }}
                </span>
                <span v-else-if="column.key === 'shareCode'" class="muted-cell">{{ row.shareCode || '-' }}</span>
                <span v-else-if="column.key === 'primaryFileSize'" class="muted-cell">{{ primaryFileSize(row) }}</span>
                <span v-else-if="column.key === 'riskScore'" :class="['severity-pill', `severity-pill--${row.severity || 'low'}`]">
                  {{ severityLabel(row) }}
                </span>
                <span v-else-if="column.key === 'matchedTerms'">{{ matchedTermsText(row) }}</span>
                <span v-else-if="column.key === 'lastSeenAt'">{{ formatDateTime(row.lastSeenAt) || '-' }}</span>
                <span v-else-if="column.key === 'linkValidity'" :class="['validity-pill', `validity-pill--${linkValidityType(row)}`]">
                  <span class="validity-dot"></span>
                  {{ linkValidityLabel(row) }}
                </span>
                <span v-else>{{ column.value(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="62">
              <template #default="{ row }">
                <div class="netdisk-row-actions">
                  <el-button text @click="viewDetail(row)">
                    <el-icon><View /></el-icon>
                  </el-button>
                  <el-button text>
                    <el-icon><MoreFilled /></el-icon>
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="netdisk-pagination">
          <span>共 {{ formatNumber(filteredHits.length) }} 条</span>
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50]"
            :total="filteredHits.length"
            layout="sizes, prev, pager, next, jumper"
            background
          />
        </div>
      </section>
    </section>

    <section v-else class="monitor-shell">
      <header class="monitor-shell__header">
        <div>
          <div class="monitor-shell__eyebrow">{{ currentConfig.eyebrow }}</div>
          <h2 class="monitor-shell__title">{{ currentConfig.title }}</h2>
          <p class="monitor-shell__summary">{{ currentConfig.summary }}</p>
        </div>
        <div class="monitor-shell__actions">
          <el-button plain @click="router.push(currentConfig.settingsRoute)">监测配置</el-button>
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
          <el-select v-if="sourceFamily !== 'netdisk_aggregator'" v-model="riskFilter" clearable placeholder="风险级别" class="filter-control">
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

        <div class="table-shell" :class="{ 'table-shell--netdisk': sourceFamily === 'netdisk_aggregator' }">
          <el-table :data="pagedHits" table-layout="auto" :row-class-name="tableRowClassName">
            <el-table-column
              v-for="column in currentConfig.columns"
              :key="column.key"
              :label="column.label"
              :min-width="column.minWidth"
              :width="column.width"
              show-overflow-tooltip
            >
              <template #default="{ row }">
                <span v-if="column.key === 'primaryFileName'" class="file-cell">
                  <span :class="['file-type-icon', `file-type-icon--${fileTypeClass(row)}`]">{{ fileTypeLabel(row) }}</span>
                  <span class="file-cell__name">{{ primaryFileName(row) }}</span>
                </span>
                <span v-else-if="column.key === 'platformLabel'" class="platform-cell">
                  <img
                    v-if="platformIconUrl(row)"
                    class="platform-logo"
                    :src="platformIconUrl(row)"
                    :alt="platformDisplayLabel(row)"
                    loading="lazy"
                  />
                  <span v-else :class="['platform-icon', `platform-icon--${platformIconClass(row)}`]">{{ platformIconText(row) }}</span>
                  <span>{{ platformDisplayLabel(row) }}</span>
                </span>
                <span v-else-if="column.key === 'shareType'" :class="['share-type-pill', `share-type-pill--${row.shareType || 'public_share'}`]">
                  {{ shareTypeLabel(row) }}
                </span>
                <span v-else-if="column.key === 'primaryFileSize'" class="muted-cell">{{ primaryFileSize(row) }}</span>
                <span v-else-if="column.key === 'riskScore'" :class="['severity-pill', `severity-pill--${row.severity || 'low'}`]">
                  {{ severityLabel(row) }}
                </span>
                <span v-else-if="column.key === 'matchedTerms'">{{ matchedTermsText(row) }}</span>
                <span v-else-if="column.key === 'lastSeenAt'">{{ formatDateTime(row.lastSeenAt) || '-' }}</span>
                <span v-else-if="column.key === 'reviewStatus'">{{ row.reviewStatusLabel || row.reviewStatus || '-' }}</span>
                <span v-else-if="column.key === 'linkValidity'" :class="['validity-pill', `validity-pill--${linkValidityType(row)}`]">
                  <span class="validity-dot"></span>
                  {{ linkValidityLabel(row) }}
                </span>
                <span v-else>{{ column.value(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="104" fixed="right">
              <template #default="{ row }">
                <el-button class="compact-action" type="primary" size="small" @click="viewDetail(row)">查看</el-button>
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
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const route = useRoute()
const router = useRouter()
const api = useDocumentExposureApi()

const FAMILY_CONFIG = {
  search_engine: {
    eyebrow: 'Search Engine',
    title: '搜索引擎监测',
    settingsRoute: '/document-exposure/search-engine/settings',
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
    settingsRoute: '/document-exposure/netdisk/settings',
    summary: '聚焦公开网盘分享页面，展示平台分布、访问状态、文件清单和处置情况。',
    trendTitle: '分享链接发现趋势',
    distributionTitle: '平台分布',
    tableTitle: '网盘命中列表',
    footerHint: '详情页展示分享链接信息、文件清单和处置动作。',
    columns: [
      { key: 'primaryFileName', label: '文件名', minWidth: 178, value: (row) => primaryFileName(row) },
      { key: 'platformLabel', label: '来源平台', minWidth: 90, value: (row) => platformDisplayLabel(row) },
      { key: 'shareType', label: '分享类型', minWidth: 70, value: () => '' },
      { key: 'shareCode', label: '提取码/口令', minWidth: 84, value: (row) => row.shareCode || '-' },
      { key: 'primaryFileSize', label: '文件大小', minWidth: 76, value: (row) => primaryFileSize(row) },
      { key: 'matchedTerms', label: '匹配企业关键词', minWidth: 102, value: () => '' },
      { key: 'riskScore', label: '风险等级', minWidth: 70, value: () => '' },
      { key: 'lastSeenAt', label: '发现时间', minWidth: 120, value: () => '' },
      { key: 'linkValidity', label: '状态', minWidth: 66, value: () => '' },
    ],
    sourceLabel: (row) => platformDisplayLabel(row),
  },
  document_library: {
    eyebrow: 'Document Library',
    title: '文库监测',
    settingsRoute: '/document-exposure/document-library/settings',
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
const selectedRange = ref('7d')
const customDateRange = ref(defaultDateRange(7))
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
const rangeTabs = [
  { key: '7d', label: '近7天' },
  { key: '30d', label: '近30天' },
  { key: 'custom', label: '自定义' },
]
const netdiskPlatformOrder = ['百度网盘', '阿里云盘', '夸克网盘', 'OneDrive']
const netdiskPalette = ['#1d7cff', '#f3a93b', '#2d8cff', '#98b8ff', '#6d8eff', '#37b6a6']

const PLATFORM_ICON_META = {
  baidupan_share: { text: '百', className: 'baidu', url: 'https://nd-static.bdstatic.com/m-static/wp-brand/favicon.ico' },
  aliyundrive_share: { text: '阿', className: 'aliyun', url: 'https://img.alicdn.com/imgextra/i1/O1CN01JDQCi21Dc8EfbRwvF_!!6000000000236-73-tps-64-64.ico' },
  quark_share: { text: '夸', className: 'quark', url: 'https://image.quark.cn/s/uae/g/3o/broccoli/resource/202602/f6439020-13b4-11f1-9342-3944993de2f6.png' },
  tianyi_share: { text: '天', className: 'tianyi' },
  pan123_share: { text: '123', className: 'pan123' },
  onedrive_share: { text: '1D', className: 'onedrive' },
  xunlei_share: { text: '迅', className: 'xunlei' },
  uc_share: { text: 'UC', className: 'uc', url: 'https://drive.uc.cn/favicon.ico' },
  mobile_share: { text: '移', className: 'mobile' },
  pan115_share: { text: '115', className: 'pan115', url: 'https://115.com/favicon.ico' },
  pikpak_share: { text: 'PK', className: 'pikpak', url: 'https://mypikpak.com/favicon.ico' },
}

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
    ...rows.map((item) => {
      const label = normalizePlatformLabel(item.name)
      return { key: label, label: `${label} (${item.value})` }
    }),
  ]
})

const netdiskPlatformTabs = computed(() => [
  { key: 'all', label: '全部' },
  ...netdiskPlatformOrder.map((label) => ({ key: label, label })),
])

const rangeDateBounds = computed(() => {
  if (sourceFamily.value !== 'netdisk_aggregator') return null
  if (selectedRange.value === 'custom') {
    const [start, end] = Array.isArray(customDateRange.value) ? customDateRange.value : []
    return start && end ? normalizeDateBounds(start, end) : null
  }
  return normalizeDateBounds(...defaultDateRange(selectedRange.value === '30d' ? 30 : 7))
})

const rangeDisplayLabel = computed(() => {
  if (selectedRange.value === 'custom') {
    const bounds = rangeDateBounds.value
    return bounds ? `${bounds.start.slice(5)} 至 ${bounds.end.slice(5)}` : '自定义'
  }
  return rangeTabs.find((item) => item.key === selectedRange.value)?.label || '近7天'
})

const dateScopedHits = computed(() => {
  if (sourceFamily.value !== 'netdisk_aggregator') return hits.value
  const bounds = rangeDateBounds.value
  if (!bounds) return hits.value
  return hits.value.filter((row) => {
    const bucket = hitDateBucket(row)
    return bucket && bucket >= bounds.start && bucket <= bounds.end
  })
})

const passwordShareCount = computed(() => dateScopedHits.value.filter((row) => row.shareType === 'password_share').length)
const highSeverityCount = computed(() => dateScopedHits.value.filter((row) => row.severity === 'high').length)
const netdiskInvalidCount = computed(() => dateScopedHits.value.filter((row) => ['removed', 'forbidden'].includes(row.accessState)).length)

const netdiskTrendRows = computed(() => {
  const bounds = rangeDateBounds.value
  if (!bounds) return summary.trend || []
  const counter = {}
  for (const date of enumerateDateRange(bounds.start, bounds.end)) {
    counter[date] = 0
  }
  for (const row of dateScopedHits.value) {
    const bucket = hitDateBucket(row)
    if (Object.prototype.hasOwnProperty.call(counter, bucket)) {
      counter[bucket] += 1
    }
  }
  return Object.entries(counter).map(([date, value]) => ({ date, value }))
})

const netdiskPlatformDistribution = computed(() => {
  const counter = {}
  for (const row of dateScopedHits.value) {
    const label = normalizePlatformLabel(row.platformLabel || row.platform || '未知平台')
    counter[label] = (counter[label] || 0) + 1
  }
  return Object.entries(counter)
    .map(([name, value]) => ({ name, value }))
    .sort((left, right) => right.value - left.value)
})

const trendDeltaText = computed(() => {
  const rows = Array.isArray(netdiskTrendRows.value) ? netdiskTrendRows.value : []
  const current = Number(rows[rows.length - 1]?.value || 0)
  const previous = Number(rows[rows.length - 2]?.value || 0)
  if (!previous && !current) return '0.0%'
  if (!previous) return '100.0%'
  return `${(((current - previous) / previous) * 100).toFixed(1)}%`
})

const netdiskMetricCards = computed(() => [
  {
    label: '发现分享链接',
    value: dateScopedHits.value.length,
    delta: trendDeltaText.value,
    deltaType: 'up',
    icon: 'link',
  },
  {
    label: '高危文件',
    value: highSeverityCount.value || summary.highRiskCount,
    delta: '21.1%',
    deltaType: 'up',
    icon: 'alert',
  },
  {
    label: '口令分享',
    value: passwordShareCount.value,
    delta: '16.3%',
    deltaType: 'up',
    icon: 'lock',
  },
  {
    label: '已失效链接',
    value: netdiskInvalidCount.value,
    delta: '9.4%',
    deltaType: 'up',
    icon: 'broken',
  },
])

const netdiskLegendRows = computed(() => {
  const rows = [...netdiskPlatformDistribution.value]
    .map((item) => ({ ...item, name: normalizePlatformLabel(item.name), value: Number(item.value || 0) }))
    .sort((left, right) => right.value - left.value)
  const total = rows.reduce((sum, item) => sum + item.value, 0) || 1
  return rows.map((item, index) => ({
    ...item,
    color: netdiskPalette[index % netdiskPalette.length],
    shareText: `${((item.value / total) * 100).toFixed(1)}%`,
  }))
})

const netdiskTrendOption = computed(() => ({
  grid: { left: 42, right: 20, top: 28, bottom: 32 },
  xAxis: {
    type: 'category',
    data: netdiskTrendRows.value.map((item) => item.date.slice(5)),
    axisLine: { lineStyle: { color: 'rgba(74, 112, 168, 0.22)' } },
    axisTick: { show: false },
    axisLabel: { color: '#6a7890', fontSize: 12 },
  },
  yAxis: {
    type: 'value',
    splitLine: { lineStyle: { color: 'rgba(74, 112, 168, 0.12)' } },
    axisLabel: { color: '#6a7890', fontSize: 12 },
  },
  tooltip: { trigger: 'axis' },
  series: [
    {
      type: 'line',
      smooth: true,
      data: netdiskTrendRows.value.map((item) => item.value),
      symbolSize: 8,
      lineStyle: { width: 3, color: '#2f8dff' },
      itemStyle: { color: '#35a6ff', borderColor: '#ffffff', borderWidth: 2 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(47, 141, 255, 0.28)' },
            { offset: 1, color: 'rgba(47, 141, 255, 0.02)' },
          ],
        },
      },
    },
  ],
}))

const netdiskDistributionOption = computed(() => ({
  tooltip: { trigger: 'item' },
  series: [
    {
      type: 'pie',
      radius: ['52%', '76%'],
      center: ['50%', '50%'],
      data: netdiskLegendRows.value.map((item) => ({ name: item.name, value: item.value, itemStyle: { color: item.color } })),
      label: { show: false },
      itemStyle: {
        borderColor: '#ffffff',
        borderWidth: 3,
      },
    },
  ],
  graphic: [
    {
      type: 'text',
      left: 'center',
      top: '42%',
      style: {
        text: `${formatNumber(dateScopedHits.value.length)}\n总数`,
        textAlign: 'center',
        fill: '#1d2b3f',
        fontSize: 16,
        fontWeight: 700,
        lineHeight: 22,
      },
    },
  ],
}))

const filteredHits = computed(() => {
  const searchText = keyword.value.trim().toLowerCase()
  return dateScopedHits.value.filter((row) => {
    const matchesSource = selectedSource.value === 'all' || currentConfig.value.sourceLabel(row) === selectedSource.value
    const matchesRisk = sourceFamily.value === 'netdisk_aggregator' || !riskFilter.value || row.severity === riskFilter.value
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

function selectRange(key) {
  selectedRange.value = key
  if (key === 'custom') {
    const [start, end] = Array.isArray(customDateRange.value) ? customDateRange.value : []
    if (!start || !end) {
      customDateRange.value = defaultDateRange(7)
    }
  }
}

function defaultDateRange(days) {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - Math.max(1, days) + 1)
  return [formatDateOnly(start), formatDateOnly(end)]
}

function formatDateOnly(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function parseDateOnly(value) {
  const date = new Date(`${value}T00:00:00`)
  return Number.isNaN(date.getTime()) ? null : date
}

function normalizeDateBounds(start, end) {
  return start <= end ? { start, end } : { start: end, end: start }
}

function enumerateDateRange(start, end) {
  const cursor = parseDateOnly(start)
  const last = parseDateOnly(end)
  if (!cursor || !last) return []
  const dates = []
  while (cursor <= last && dates.length < 366) {
    dates.push(formatDateOnly(cursor))
    cursor.setDate(cursor.getDate() + 1)
  }
  return dates
}

function hitDateBucket(row) {
  return dateValueBucket(row?.lastSeenAt || row?.firstSeenAt || row?.disclosureTime)
}

function dateValueBucket(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  const direct = text.match(/^(\d{4}-\d{2}-\d{2})/)
  if (direct) return direct[1]
  const date = new Date(text.replace(' ', 'T'))
  return Number.isNaN(date.getTime()) ? '' : formatDateOnly(date)
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

function matchedTermsText(row) {
  if (!Array.isArray(row?.matchedTerms) || !row.matchedTerms.length) return '-'
  return row.matchedTerms
    .map((item) => item.term)
    .filter(Boolean)
    .join('、')
}

function normalizePlatformLabel(value) {
  return String(value || '')
    .replace(/\s*分享页/g, '')
    .trim() || '-'
}

function primaryFileName(row) {
  return row?.primaryFileName || row?.title || row?.canonicalUrl || '-'
}

function primaryFileSize(row) {
  if (row?.primaryFileSize) return row.primaryFileSize
  if (Array.isArray(row?.fileSizes) && row.fileSizes.length) return row.fileSizes[0]
  return '-'
}

function primaryFileType(row) {
  const direct = String(row?.primaryFileType || '').trim().toLowerCase()
  if (direct) return direct
  const match = primaryFileName(row).match(/\.([a-z0-9]{2,6})(?:$|[?#\s])/i)
  return match ? match[1].toLowerCase() : ''
}

function fileTypeLabel(row) {
  const type = primaryFileType(row)
  return type ? type.slice(0, 4).toUpperCase() : 'FILE'
}

function fileTypeClass(row) {
  const type = primaryFileType(row)
  if (['xls', 'xlsx', 'csv'].includes(type)) return 'sheet'
  if (type === 'pdf') return 'pdf'
  if (['doc', 'docx', 'txt'].includes(type)) return 'doc'
  if (['ppt', 'pptx'].includes(type)) return 'ppt'
  if (['zip', 'rar', '7z'].includes(type)) return 'archive'
  if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(type)) return 'image'
  if (['mp4', 'mov', 'mkv', 'avi'].includes(type)) return 'video'
  return 'default'
}

function platformDisplayLabel(row) {
  return normalizePlatformLabel(row?.platformLabel || row?.platform)
}

function platformIconMeta(row) {
  return PLATFORM_ICON_META[row?.platform] || { text: platformDisplayLabel(row).slice(0, 2).toUpperCase(), className: 'generic' }
}

function platformIconClass(row) {
  return platformIconMeta(row).className
}

function platformIconUrl(row) {
  return platformIconMeta(row).url || ''
}

function platformIconText(row) {
  return platformIconMeta(row).text || '-'
}

function shareTypeLabel(row) {
  if (row?.shareType === 'password_share') return '加密'
  if (row?.shareType === 'public_share') return '公开'
  return row?.shareType || '-'
}

function severityLabel(row) {
  return {
    high: '高危',
    medium: '中危',
    low: '低危',
  }[row?.severity] || row?.severity || '-'
}

function linkValidityType(row) {
  const state = row?.accessState || ''
  if (['public', 'login_required'].includes(state)) return 'valid'
  if (['removed', 'forbidden'].includes(state)) return 'invalid'
  if (state === 'captcha') return 'gated'
  return 'pending'
}

function linkValidityLabel(row) {
  return {
    valid: '有效',
    invalid: '已失效',
    gated: '需验证',
    pending: '待校验',
  }[linkValidityType(row)]
}

function tableRowClassName() {
  return sourceFamily.value === 'netdisk_aggregator' ? 'compact-netdisk-row' : ''
}

async function loadData() {
  loading.value = true
  try {
    const [summaryPayload, hitPayload] = await Promise.all([
      api.loadSummary({ sourceFamily: sourceFamily.value }),
      api.loadHits({ sourceFamily: sourceFamily.value, limit: 500 }),
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

watch([selectedRange, customDateRange], () => {
  currentPage.value = 1
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
.netdisk-board {
  display: grid;
  gap: 10px;
  color: var(--ti-text-primary);
}

.netdisk-toolbar {
  display: grid;
  gap: 12px;
}

.netdisk-title,
.netdisk-toolbar__controls,
.segmented-control,
.netdisk-row-actions,
.netdisk-pagination {
  display: flex;
  align-items: center;
}

.netdisk-title {
  gap: 6px;
}

.netdisk-title h2 {
  margin: 0;
  font-size: 16px;
  line-height: 1.2;
  color: var(--ti-text-primary);
}

.netdisk-title .el-icon {
  color: var(--ti-text-muted);
  font-size: 14px;
}

.netdisk-toolbar__controls {
  gap: 8px;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: thin;
}

.segmented-control {
  height: 28px;
  padding: 1px;
  border: 1px solid rgba(45, 93, 255, 0.16);
  border-radius: 4px;
  background: rgba(244, 248, 255, 0.92);
}

.segmented-control button {
  height: 24px;
  min-width: 56px;
  padding: 0 10px;
  border: 0;
  border-left: 1px solid rgba(45, 93, 255, 0.12);
  background: transparent;
  color: var(--ti-text-secondary);
  font-size: 12px;
  line-height: 24px;
  white-space: nowrap;
  cursor: pointer;
}

.segmented-control button:first-child {
  border-left: 0;
}

.segmented-control button.active {
  background: rgba(45, 126, 255, 0.12);
  color: #155bd6;
  box-shadow: inset 0 0 0 1px rgba(45, 126, 255, 0.45);
}

.segmented-control--platform button {
  min-width: 72px;
}

.netdisk-custom-range {
  flex: 0 0 248px;
  width: 248px;
}

.netdisk-custom-range :deep(.el-range-input) {
  font-size: 12px;
}

.toolbar-divider {
  width: 1px;
  height: 22px;
  background: rgba(116, 142, 184, 0.18);
}

.netdisk-search {
  flex: 0 0 224px;
  width: 224px;
}

.netdisk-search :deep(.el-input__wrapper) {
  height: 30px;
  border-radius: 4px;
}

.netdisk-settings-btn {
  flex: 0 0 32px;
  width: 32px;
  height: 30px;
  margin-left: auto;
  padding: 0;
  border-radius: 4px;
}

.advanced-filter-btn {
  flex: 0 0 auto;
  height: 30px;
  padding: 0 12px;
  border-radius: 4px;
  white-space: nowrap;
}

.netdisk-metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.netdisk-metric-card,
.netdisk-panel {
  border: 1px solid rgba(45, 93, 255, 0.12);
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 24px rgba(32, 57, 96, 0.05);
}

.netdisk-metric-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: 86px;
  padding: 14px 16px;
}

.netdisk-metric-card span,
.netdisk-metric-card small,
.netdisk-panel__title span {
  color: var(--ti-text-secondary);
  font-size: 12px;
}

.netdisk-metric-card strong {
  display: block;
  margin-top: 6px;
  color: var(--ti-text-primary);
  font-size: 24px;
  line-height: 1;
}

.netdisk-metric-card small {
  display: block;
  margin-top: 7px;
}

.netdisk-metric-card b {
  font-weight: 700;
}

.netdisk-metric-card b.up {
  color: #df4a55;
}

.netdisk-metric-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 50px;
  height: 50px;
  border-radius: 10px;
  font-size: 31px;
}

.netdisk-metric-icon--link {
  color: #1687ff;
  background: rgba(22, 135, 255, 0.12);
}

.netdisk-metric-icon--alert {
  color: #eb4d56;
  background: rgba(235, 77, 86, 0.12);
}

.netdisk-metric-icon--lock {
  color: #ee9d29;
  background: rgba(238, 157, 41, 0.13);
}

.netdisk-metric-icon--broken {
  color: #7d8fa8;
  background: rgba(125, 143, 168, 0.12);
}

.netdisk-chart-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(380px, 1.1fr);
  gap: 12px;
}

.netdisk-panel {
  min-width: 0;
  padding: 12px;
}

.netdisk-panel__title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.netdisk-panel__title h3 {
  margin: 0;
  font-size: 14px;
  color: var(--ti-text-primary);
}

.netdisk-panel__title--table {
  justify-content: flex-start;
  gap: 8px;
}

.netdisk-chart {
  height: 150px;
  margin-top: 6px;
}

.netdisk-distribution {
  display: grid;
  grid-template-columns: minmax(170px, 230px) minmax(0, 1fr);
  align-items: center;
  min-height: 150px;
}

.netdisk-donut {
  height: 150px;
}

.netdisk-legend {
  display: grid;
  gap: 12px;
  padding-right: 8px;
}

.netdisk-legend__row {
  display: grid;
  grid-template-columns: 10px minmax(80px, 1fr) auto;
  align-items: center;
  gap: 9px;
  color: var(--ti-text-secondary);
  font-size: 12px;
}

.netdisk-legend__row span {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.netdisk-legend__row strong {
  color: var(--ti-text-primary);
  font-weight: 600;
}

.netdisk-legend__row em {
  color: var(--ti-text-secondary);
  font-style: normal;
}

.netdisk-panel--table {
  padding: 12px;
}

.netdisk-table-shell {
  overflow-x: auto;
  overflow-y: hidden;
  margin-top: 10px;
  border: 1px solid rgba(45, 93, 255, 0.14);
  border-radius: 5px;
}

.netdisk-table-shell :deep(.el-table) {
  --el-table-bg-color: rgba(255, 255, 255, 0.96);
  --el-table-tr-bg-color: rgba(255, 255, 255, 0.96);
  --el-table-border-color: rgba(45, 93, 255, 0.1);
  --el-table-header-bg-color: rgba(246, 250, 255, 0.98);
  --el-table-header-text-color: var(--ti-text-secondary);
  --el-table-text-color: var(--ti-text-primary);
  font-size: 12px;
  width: 100%;
  min-width: 918px;
}

.netdisk-table-shell :deep(.el-table__header-wrapper th.el-table__cell) {
  height: 34px;
  padding: 5px 0;
  background: rgba(246, 250, 255, 0.98);
  color: var(--ti-text-secondary);
  font-weight: 700;
}

.netdisk-table-shell :deep(.el-table .cell) {
  overflow: hidden;
  padding: 0 6px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.netdisk-table-shell :deep(.compact-netdisk-row td.el-table__cell) {
  height: 34px;
  padding: 4px 0;
  background: rgba(255, 255, 255, 0.96);
}

.netdisk-table-shell :deep(.compact-netdisk-row:hover td.el-table__cell) {
  background: rgba(239, 246, 255, 0.96);
}

.netdisk-table-shell :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.netdisk-row-actions {
  gap: 0;
}

.netdisk-row-actions :deep(.el-button) {
  width: 23px;
  height: 23px;
  padding: 0;
  color: var(--ti-text-secondary);
}

.netdisk-pagination {
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  color: var(--ti-text-secondary);
  font-size: 12px;
}

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

.table-shell--netdisk {
  overflow: hidden;
  border: 1px solid rgba(116, 142, 184, 0.14);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 10px 24px rgba(32, 57, 96, 0.05);
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
  min-width: 50px;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
}

.severity-pill--high {
  background: rgba(229, 85, 87, 0.12);
  color: #c83338;
}

.severity-pill--medium {
  background: rgba(255, 173, 76, 0.16);
  color: #b66a00;
}

.severity-pill--low {
  background: rgba(70, 192, 138, 0.14);
  color: #158353;
}

.file-cell,
.platform-cell {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  max-width: 100%;
  vertical-align: middle;
}

.file-cell__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-type-icon,
.platform-icon {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0;
}

.file-type-icon {
  width: 26px;
  height: 26px;
  border-radius: 5px;
}

.file-type-icon--sheet {
  background: #20a868;
}

.file-type-icon--pdf {
  background: #e64d4f;
}

.file-type-icon--doc {
  background: #3b7bea;
}

.file-type-icon--ppt {
  background: #ed7a34;
}

.file-type-icon--archive {
  background: #8b6eea;
}

.file-type-icon--image {
  background: #17a2b8;
}

.file-type-icon--video {
  background: #5865f2;
}

.file-type-icon--default {
  background: #71839b;
}

.platform-icon {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.28);
}

.platform-logo {
  flex: 0 0 auto;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  object-fit: contain;
  background: #fff;
  box-shadow: 0 0 0 1px rgba(116, 142, 184, 0.18);
}

.platform-icon--baidu {
  background: linear-gradient(135deg, #008cff, #00b8ff);
}

.platform-icon--aliyun {
  background: linear-gradient(135deg, #6d5dfc, #895cff);
}

.platform-icon--quark {
  background: linear-gradient(135deg, #236dff, #69a6ff);
}

.platform-icon--tianyi {
  background: linear-gradient(135deg, #1b72ff, #00a3ff);
}

.platform-icon--pan123 {
  background: linear-gradient(135deg, #24b46b, #83d86e);
}

.platform-icon--onedrive {
  background: linear-gradient(135deg, #0078d4, #38bdf8);
}

.platform-icon--xunlei {
  background: linear-gradient(135deg, #234de6, #4bc5ff);
}

.platform-icon--uc {
  background: linear-gradient(135deg, #ff9f1a, #ffc857);
}

.platform-icon--mobile {
  background: linear-gradient(135deg, #12b886, #69db7c);
}

.platform-icon--pan115 {
  background: linear-gradient(135deg, #3c6ff0, #66d9e8);
}

.platform-icon--pikpak,
.platform-icon--generic {
  background: linear-gradient(135deg, #536d8f, #8aa4c7);
}

.share-type-pill,
.validity-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
}

.share-type-pill--public_share {
  color: #1b6fbc;
  background: rgba(42, 140, 255, 0.14);
}

.share-type-pill--password_share {
  color: #ad6500;
  background: rgba(255, 160, 41, 0.15);
}

.validity-pill {
  gap: 6px;
}

.validity-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.validity-pill--valid {
  color: #13834d;
  background: rgba(56, 193, 114, 0.15);
}

.validity-pill--valid .validity-dot {
  background: #38d66b;
}

.validity-pill--invalid {
  color: #66758a;
  background: rgba(127, 146, 171, 0.16);
}

.validity-pill--invalid .validity-dot {
  background: #7d8794;
}

.validity-pill--gated {
  color: #ad6500;
  background: rgba(255, 173, 76, 0.14);
}

.validity-pill--gated .validity-dot {
  background: #ffac38;
}

.validity-pill--pending {
  color: #346fae;
  background: rgba(92, 148, 214, 0.16);
}

.validity-pill--pending .validity-dot {
  background: #6aa7ea;
}

.muted-cell {
  color: var(--ti-text-muted);
}

.compact-action {
  min-height: 28px;
  padding: 0 12px;
  border-radius: 6px;
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

.table-shell--netdisk :deep(.el-table) {
  --el-table-bg-color: rgba(255, 255, 255, 0.9);
  --el-table-tr-bg-color: rgba(255, 255, 255, 0.9);
  --el-table-border-color: rgba(116, 142, 184, 0.12);
  --el-table-header-bg-color: rgba(245, 249, 255, 0.96);
  --el-table-header-text-color: var(--ti-text-secondary);
  --el-table-text-color: var(--ti-text-primary);
  font-size: 13px;
}

.table-shell--netdisk :deep(.el-table__header-wrapper th.el-table__cell) {
  height: 40px;
  padding: 7px 0;
  background: rgba(245, 249, 255, 0.96);
  color: var(--ti-text-secondary);
  font-size: 13px;
  font-weight: 700;
}

.table-shell--netdisk :deep(.compact-netdisk-row td.el-table__cell) {
  height: 44px;
  padding: 7px 0;
  background: rgba(255, 255, 255, 0.94);
}

.table-shell--netdisk :deep(.compact-netdisk-row:hover td.el-table__cell) {
  background: rgba(244, 248, 255, 0.98);
}

.table-shell--netdisk :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.table-shell--netdisk :deep(.el-table__fixed-right) {
  background: rgba(255, 255, 255, 0.94);
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
