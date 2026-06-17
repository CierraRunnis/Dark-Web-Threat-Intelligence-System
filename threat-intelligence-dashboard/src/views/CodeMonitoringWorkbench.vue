<template>
  <div class="monitoring-workbench">
    <main class="page">
      <header class="page-header">
        <div>
          <h1>代码监测亮色态势版</h1>
        </div>
        <div class="header-actions">
          <el-button plain class="ghost-btn" @click="router.push('/document-exposure/code-monitoring/settings')">配置管理</el-button>
          <el-button plain class="ghost-btn" @click="router.push('/document-exposure/code-monitoring/scans')">扫描历史</el-button>
          <el-button type="primary" class="primary-btn" :loading="scanLoading" @click="runQuickScan">立即扫描</el-button>
        </div>
      </header>

      <section class="top-grid">
        <div class="top-grid__metrics">
          <article v-for="card in metricCards" :key="card.label" class="panel metric-card">
            <div class="panel-title">
              <h2>{{ card.label }}</h2>
              <span class="info-dot">i</span>
            </div>
            <div class="metric-main">
              <div :class="['icon-box', `tone-${card.tone}`]" v-html="card.icon"></div>
              <div>
                <div class="metric-value">{{ formatNumber(card.value) }}</div>
              </div>
            </div>
          </article>
        </div>

        <article class="panel source-card">
          <div class="panel-title">
            <h2>来源平台分布</h2>
            <span class="info-dot">i</span>
          </div>
          <div class="source-list">
            <article v-for="item in platformCards" :key="item.rawName" class="source-item">
              <div class="source-item__main">
                <div :class="['source-logo', item.brandKey]" v-html="item.logo"></div>
                <div class="source-item__content">
                  <div class="source-name">{{ item.label }}</div>
                  <div class="source-metrics">
                    <strong>{{ formatNumber(item.value) }}</strong>
                    <span>{{ item.shareText }}</span>
                  </div>
                </div>
              </div>
              <div class="source-progress">
                <span class="source-progress__fill" :style="{ width: item.progressWidth, background: item.progressColor }"></span>
              </div>
            </article>
          </div>
        </article>
      </section>

      <section class="content-grid">
        <article class="panel chart-panel">
          <div class="chart-title">
            <h2>新增代码泄露趋势（近 7 天）</h2>
            <span>按日扫描命中统计</span>
          </div>
          <div v-if="trendChart.points.length" class="trend-wrap">
            <svg viewBox="0 0 760 260" preserveAspectRatio="none" aria-label="趋势图">
              <defs>
                <linearGradient id="cm-area-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="rgba(64, 153, 255, 0.24)" />
                  <stop offset="100%" stop-color="rgba(64, 153, 255, 0.03)" />
                </linearGradient>
                <filter id="cm-line-glow" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="3" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur"></feMergeNode>
                    <feMergeNode in="SourceGraphic"></feMergeNode>
                  </feMerge>
                </filter>
              </defs>

              <g v-for="tick in trendChart.ticks" :key="`tick-${tick.value}`">
                <line
                  :x1="trendChart.padding.left"
                  :y1="tick.y"
                  :x2="trendChart.width - trendChart.padding.right"
                  :y2="tick.y"
                  stroke="rgba(96, 140, 200, 0.14)"
                  stroke-dasharray="4 6"
                />
                <text
                  :x="trendChart.padding.left - 12"
                  :y="tick.y + 4"
                  fill="#6a84a6"
                  font-size="15"
                  font-weight="600"
                  text-anchor="end"
                >
                  {{ formatNumber(tick.value) }}
                </text>
              </g>

              <path :d="trendChart.areaPath" fill="url(#cm-area-fill)" />
              <path :d="trendChart.linePath" fill="none" stroke="#3a94ff" stroke-width="3" filter="url(#cm-line-glow)" />

              <g v-for="(point, index) in trendChart.points" :key="point.label">
                <circle
                  :cx="point.x"
                  :cy="point.y"
                  :r="index === trendChart.points.length - 1 ? 5.5 : 4.5"
                  fill="#63b0ff"
                  stroke="#ffffff"
                  stroke-width="2"
                />
                <text
                  :x="point.x"
                  :y="point.y - 16"
                  :fill="index === trendChart.points.length - 1 ? '#1d63df' : '#2f4d74'"
                  font-size="16"
                  font-weight="700"
                  text-anchor="middle"
                >
                  {{ formatNumber(point.value) }}
                </text>
                <text
                  :x="
                    index === 0
                      ? point.x + 8
                      : index === trendChart.points.length - 1
                        ? point.x - 8
                        : point.x
                  "
                  :y="trendChart.height - 6"
                  :fill="index === trendChart.points.length - 1 ? '#2e83ff' : '#617b9d'"
                  font-size="15"
                  :font-weight="index === trendChart.points.length - 1 ? '700' : '600'"
                  :text-anchor="
                    index === 0
                      ? 'start'
                      : index === trendChart.points.length - 1
                        ? 'end'
                        : 'middle'
                  "
                >
                  {{ point.label }}
                </text>
              </g>
            </svg>
          </div>
          <div v-else class="panel-empty panel-empty--chart">暂无趋势数据</div>
        </article>

        <article class="panel chart-panel">
          <div class="chart-title">
            <h2>仓库风险等级分布</h2>
            <span>总仓库 {{ formatNumber(riskTotalDisplay) }}</span>
          </div>
          <div v-if="riskEntries.length" class="risk-layout">
            <div class="donut-shell" :style="riskDonutStyle">
              <div class="donut-inner">
                <div>
                  <div class="donut-total">{{ formatNumber(riskTotalDisplay) }}</div>
                  <div class="donut-label">总数</div>
                </div>
              </div>
            </div>
            <div class="legend-list">
              <div v-for="item in riskEntries" :key="item.label" class="legend-item">
                <span class="legend-dot" :style="{ background: item.color }"></span>
                <span>{{ item.label }}</span>
                <span><strong>{{ formatNumber(item.value) }}</strong> {{ item.shareText }}</span>
              </div>
            </div>
          </div>
          <div v-else class="panel-empty panel-empty--chart">暂无风险分布数据</div>
        </article>

        <article class="panel chart-panel">
          <div class="chart-title">
            <h2>敏感类型分布（Top 8）</h2>
            <span>按命中次数降序</span>
          </div>
          <div v-if="typeBars.length" class="bar-list">
            <div v-for="item in typeBars" :key="item.name" class="bar-row">
              <span>{{ item.name }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: item.width }"></div>
              </div>
              <strong>{{ formatNumber(item.value) }}</strong>
            </div>
          </div>
          <div v-else class="panel-empty panel-empty--chart">暂无敏感类型数据</div>
        </article>
      </section>

      <section class="stack">
        <article class="panel table-panel">
          <div class="table-title">
            <div>
              <h2>代码泄露监测主列表</h2>
              <div class="footnote">详情页展示代码片段、敏感项列表、风险分析和处置记录，不在列表页展开。</div>
            </div>
            <div class="table-meta">
              {{ primaryHits.length }} 条结果&nbsp;&nbsp; 最近扫描 {{ formatDateTime(summary.lastScanAt) || '-' }}
            </div>
          </div>

          <div class="table-toolbar">
            <div class="table-toolbar-left">
              <el-select v-model="watchlistFilter" clearable placeholder="监测对象" class="toolbar-control">
                <el-option v-for="item in watchlists" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
              <el-select v-model="platformFilter" clearable placeholder="来源平台" class="toolbar-control">
                <el-option v-for="item in platformOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="severityFilter" clearable placeholder="风险级别" class="toolbar-control">
                <el-option label="高危" value="high" />
                <el-option label="中危" value="medium" />
                <el-option label="低危" value="low" />
              </el-select>
              <el-select v-model="resultLayerFilter" clearable placeholder="命中层级" class="toolbar-control">
                <el-option label="敏感命中" value="sensitive" />
                <el-option label="线索命中" value="clue" />
              </el-select>
              <el-select v-model="sensitiveTypeFilter" clearable placeholder="敏感类型" class="toolbar-control">
                <el-option v-for="item in sensitiveTypeOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </div>
            <el-input v-model="keyword" clearable placeholder="搜索仓库、路径、敏感词" class="toolbar-search">
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
          </div>

          <div class="table-shell">
            <table>
              <thead>
                <tr>
                  <th>仓库名称</th>
                  <th>来源平台</th>
                  <th>文件路径</th>
                  <th>敏感类型</th>
                  <th>检索命中词</th>
                  <th>命中层级</th>
                  <th>风险级别</th>
                  <th>发现时间</th>
                  <th>处理状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in pagedHits" :key="row.id">
                  <td><strong class="cell-ellipsis" :title="repositoryLabel(row)">{{ repositoryLabel(row) }}</strong></td>
                  <td>{{ platformLabel(row) }}</td>
                  <td><span class="cell-ellipsis" :title="row.filePath || '-'">{{ row.filePath || '-' }}</span></td>
                  <td><span class="cell-ellipsis" :title="sensitiveTypeLabel(row)">{{ sensitiveTypeLabel(row) }}</span></td>
                  <td><span class="cell-ellipsis" :title="row.matchedTerm || '-'">{{ row.matchedTerm || '-' }}</span></td>
                  <td>
                    <span :class="['badge', row.resultLayer === 'clue' ? 'keyword' : 'hit']">
                      {{ resultLayerLabel(row.resultLayer) }}
                    </span>
                  </td>
                  <td><span :class="['badge', severityBadgeClass(row.severity)]">{{ formatSeverity(row.severity) }}</span></td>
                  <td>{{ formatDateTime(row.lastSeenAt) || '-' }}</td>
                  <td>{{ row.reviewStatus || '-' }}</td>
                  <td><button type="button" class="detail-link" @click="viewDetail(row)">详情</button></td>
                </tr>
                <tr v-if="!pagedHits.length">
                  <td colspan="10" class="table-empty">暂无符合条件的数据</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="table-footer">
            <span class="table-footer__note">搜索、筛选、分页与详情跳转保持真实交互。</span>
            <el-pagination
              v-model:current-page="currentPage"
              v-model:page-size="pageSize"
              :page-sizes="[10, 20, 50]"
              :total="primaryHits.length"
              layout="total, sizes, prev, pager, next"
              background
            />
          </div>
        </article>

        <article class="panel table-panel">
          <div class="table-title">
            <div>
              <h2>被压制的企业相关线索</h2>
              <div class="footnote">用于保留观察面，不与真实泄露混在一起。</div>
            </div>
            <div class="table-meta">{{ suppressedHits.length }} 条结果</div>
          </div>

          <div class="table-shell">
            <table>
              <thead>
                <tr>
                  <th>仓库名称</th>
                  <th>来源平台</th>
                  <th>文件路径</th>
                  <th>检索命中词</th>
                  <th>当前层级</th>
                  <th>压制原因</th>
                  <th>风险级别</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in pagedSuppressedHits" :key="row.id">
                  <td><strong class="cell-ellipsis" :title="repositoryLabel(row)">{{ repositoryLabel(row) }}</strong></td>
                  <td>{{ platformLabel(row) }}</td>
                  <td><span class="cell-ellipsis" :title="row.filePath || '-'">{{ row.filePath || '-' }}</span></td>
                  <td><span class="cell-ellipsis" :title="row.matchedTerm || '-'">{{ row.matchedTerm || '-' }}</span></td>
                  <td>
                    <span :class="['badge', row.resultLayer === 'clue' ? 'keyword' : 'hit']">
                      {{ resultLayerLabel(row.resultLayer) }}
                    </span>
                  </td>
                  <td><span class="cell-ellipsis" :title="suppressionReasonLabel(row)">{{ suppressionReasonLabel(row) }}</span></td>
                  <td><span :class="['badge', severityBadgeClass(row.severity)]">{{ formatSeverity(row.severity) }}</span></td>
                  <td><button type="button" class="detail-link" @click="viewDetail(row)">详情</button></td>
                </tr>
                <tr v-if="!pagedSuppressedHits.length">
                  <td colspan="8" class="table-empty">暂无被压制线索</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="table-footer">
            <span class="table-footer__note">这些结果说明代码与企业相关，但已因上下文被压制，不进入主泄露列表。</span>
            <el-pagination
              v-model:current-page="suppressedCurrentPage"
              v-model:page-size="suppressedPageSize"
              :page-sizes="[10, 20, 50]"
              :total="suppressedHits.length"
              layout="total, sizes, prev, pager, next"
              background
            />
          </div>
        </article>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { useCodeMonitoringApi } from '@/composables/useCodeMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const PLATFORM_LOGOS = {
  github:
    '<svg fill="#FFFFFF" role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-label="GitHub"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>',
  gitee:
    '<svg fill="#FFFFFF" role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-label="Gitee"><path d="M11.984 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.016 0zm6.09 5.333c.328 0 .593.266.592.593v1.482a.594.594 0 0 1-.593.592H9.777c-.982 0-1.778.796-1.778 1.778v5.63c0 .327.266.592.593.592h5.63c.982 0 1.778-.796 1.778-1.778v-.296a.593.593 0 0 0-.592-.593h-4.15a.592.592 0 0 1-.592-.592v-1.482a.593.593 0 0 1 .593-.592h6.815c.327 0 .593.265.593.592v3.408a4 4 0 0 1-4 4H5.926a.593.593 0 0 1-.593-.593V9.778a4.444 4.444 0 0 1 4.445-4.444h8.296Z"/></svg>',
  gitlab:
    '<svg fill="#FFFFFF" role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" aria-label="GitLab"><path d="m23.6004 9.5927-.0337-.0862L20.3.9814a.851.851 0 0 0-.3362-.405.8748.8748 0 0 0-.9997.0539.8748.8748 0 0 0-.29.4399l-2.2055 6.748H7.5375l-2.2057-6.748a.8573.8573 0 0 0-.29-.4412.8748.8748 0 0 0-.9997-.0537.8585.8585 0 0 0-.3362.4049L.4332 9.5015l-.0325.0862a6.0657 6.0657 0 0 0 2.0119 7.0105l.0113.0087.03.0213 4.976 3.7264 2.462 1.8633 1.4995 1.1321a1.0085 1.0085 0 0 0 1.2197 0l1.4995-1.1321 2.4619-1.8633 5.006-3.7489.0125-.01a6.0682 6.0682 0 0 0 2.0094-7.003z"/></svg>',
}

const METRIC_ICONS = {
  repo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 5.5h8M5 11h8M5 16.5h5" /><rect x="3" y="3.5" width="12" height="17" rx="2.5" /><circle cx="18.5" cy="18" r="3.5" /><path d="m21 20.5 2 2" /></svg>',
  code: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 7-4 5 4 5M15 7l4 5-4 5M13 5l-2 14" /></svg>',
  clue: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12h7M13 6h7M13 18h7" /><circle cx="8" cy="12" r="3" /><circle cx="17" cy="6" r="3" /><circle cx="17" cy="18" r="3" /></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 5 6v5c0 4.5 2.8 7.6 7 10 4.2-2.4 7-5.5 7-10V6l-7-3Z" /><path d="m9.5 12 1.7 1.8 3.3-4.1" /></svg>',
}

const route = useRoute()
const router = useRouter()
const api = useCodeMonitoringApi()
const WORKBENCH_CACHE_KEY = 'code-monitoring-workbench-cache-v1'
const WORKBENCH_CACHE_TTL_MS = 5 * 60 * 1000

const keyword = ref('')
const watchlistFilter = ref('')
const platformFilter = ref('')
const severityFilter = ref('')
const resultLayerFilter = ref('')
const sensitiveTypeFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(10)
const suppressedCurrentPage = ref(1)
const suppressedPageSize = ref(10)
const scanLoading = ref(false)
const applyingRouteState = ref(false)
const hits = ref([])
const watchlists = ref([])
const summary = reactive({
  totalHits: 0,
  sensitiveSnippetCount: 0,
  clueHitCount: 0,
  primaryHitCount: 0,
  suppressedHitCount: 0,
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
  {
    label: '公开仓库命中',
    value: summary.totalHits,
    hint: '命中结果总数（含附加线索）',
    tone: 'blue',
    icon: METRIC_ICONS.repo,
    delta: summary.primaryHitCount ? `主列表 ${formatNumber(summary.primaryHitCount)}` : '',
  },
  {
    label: '敏感代码片段',
    value: summary.sensitiveSnippetCount,
    hint: '规则识别结果（含附加线索）',
    tone: 'violet',
    icon: METRIC_ICONS.code,
    delta: '',
  },
  {
    label: '线索命中',
    value: summary.clueHitCount,
    hint: '关键词相关结果（含附加线索）',
    tone: 'orange',
    icon: METRIC_ICONS.clue,
    delta: summary.suppressedHitCount ? `附加线索 ${formatNumber(summary.suppressedHitCount)}` : '',
  },
  {
    label: '高危仓库',
    value: summary.highRiskRepoCount,
    hint: '风险等级高危',
    tone: 'red',
    icon: METRIC_ICONS.shield,
    delta: '',
  },
])

const platformOptions = computed(() =>
  (summary.platformDistribution || []).map((item) => ({
    value: item.name,
    label: item.name,
  })),
)

const sensitiveTypeOptions = computed(() =>
  (summary.sensitiveTypeTop || []).map((item) => item.name),
)

const platformTotal = computed(() => {
  const total = (summary.platformDistribution || []).reduce((sum, item) => sum + Number(item.value || 0), 0)
  return total || Number(summary.totalHits || 0)
})

const platformCards = computed(() =>
  (() => {
    const rows = Array.isArray(summary.platformDistribution) ? [...summary.platformDistribution] : []
    const mapped = new Map()
    for (const item of rows) {
      const brand = resolvePlatformBrand(item.name)
      const value = Number(item.value || 0)
      const share = Number(item.share ?? (platformTotal.value ? (value / platformTotal.value) * 100 : 0))
      mapped.set(brand.key, {
        rawName: item.name || brand.label,
        label: brand.label,
        brandKey: brand.key,
        logo: brand.logo,
        value,
        shareValue: share,
        shareText: `${share.toFixed(1)}%`,
        progressWidth: `${Math.min(100, Math.max(0, share))}%`,
        progressColor: brand.progressColor,
      })
    }
    for (const platformName of ['github', 'gitlab', 'gitee']) {
      if (mapped.has(platformName)) continue
      const brand = resolvePlatformBrand(platformName)
      mapped.set(platformName, {
        rawName: brand.label,
        label: brand.label,
        brandKey: brand.key,
        logo: brand.logo,
        value: 0,
        shareValue: 0,
        shareText: '0.0%',
        progressWidth: '0%',
        progressColor: brand.progressColor,
      })
    }
    return [...mapped.values()].sort((left, right) => {
      if (right.value !== left.value) return right.value - left.value
      return left.label.localeCompare(right.label, 'zh-CN')
    })
  })(),
)

const filteredHits = computed(() => {
  const searchText = keyword.value.trim().toLowerCase()
  return hits.value.filter((row) => {
    const matchesWatchlist = !watchlistFilter.value || row.watchlistId === watchlistFilter.value
    const matchesPlatform = !platformFilter.value || row.platformLabel === platformFilter.value || row.platform === platformFilter.value
    const matchesSeverity = !severityFilter.value || row.severity === severityFilter.value
    const matchesLayer = !resultLayerFilter.value || row.resultLayer === resultLayerFilter.value
    const matchesSensitiveType =
      !sensitiveTypeFilter.value ||
      row.sensitiveLabel === sensitiveTypeFilter.value ||
      row.sensitiveType === sensitiveTypeFilter.value
    const matchesKeyword =
      !searchText ||
      [row.repositoryFullName, row.repositoryName, row.filePath, row.sensitiveLabel, row.matchedTerm]
        .join(' ')
        .toLowerCase()
        .includes(searchText)
    return matchesWatchlist && matchesPlatform && matchesSeverity && matchesLayer && matchesSensitiveType && matchesKeyword
  })
})

const primaryHits = computed(() => filteredHits.value.filter((row) => row.displayBucket !== 'suppressed'))
const suppressedHits = computed(() => filteredHits.value.filter((row) => row.displayBucket === 'suppressed'))

const pagedHits = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return primaryHits.value.slice(start, start + pageSize.value)
})

const pagedSuppressedHits = computed(() => {
  const start = (suppressedCurrentPage.value - 1) * suppressedPageSize.value
  return suppressedHits.value.slice(start, start + suppressedPageSize.value)
})

const trendChart = computed(() => {
  const width = 760
  const height = 260
  const padding = { top: 16, right: 14, bottom: 34, left: 52 }
  const entries = (summary.trend || []).map((item) => ({
    label: item.date?.slice(5) || item.label || '-',
    value: Number(item.value || 0),
  }))
  if (!entries.length) {
    return { width, height, padding, ticks: [], points: [], linePath: '', areaPath: '' }
  }
  const innerWidth = width - padding.left - padding.right
  const innerHeight = height - padding.top - padding.bottom
  const maxSource = Math.max(...entries.map((item) => item.value), 1)
  const maxValue = Math.ceil(maxSource / 200) * 200 || 200
  const steps = 4
  const baseY = height - padding.bottom
  const xStep = entries.length > 1 ? innerWidth / (entries.length - 1) : 0
  const yFor = (value) => padding.top + innerHeight - (value / maxValue) * innerHeight
  const points = entries.map((item, index) => ({
    ...item,
    x: padding.left + xStep * index,
    y: yFor(item.value),
  }))
  const linePath = points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ')
  const lastPoint = points[points.length - 1]
  const areaPath = `${linePath} L ${lastPoint.x} ${baseY} L ${points[0].x} ${baseY} Z`
  const ticks = Array.from({ length: steps + 1 }, (_, index) => {
    const value = Math.round((maxValue / steps) * (steps - index))
    return { value, y: yFor(value) }
  })
  return { width, height, padding, ticks, points, linePath, areaPath }
})

const riskEntries = computed(() => {
  const order = { high: 0, medium: 1, low: 2, unknown: 3 }
  const mapped = [...(summary.riskDistribution || [])]
    .map((item) => {
      const key = normalizeRiskKey(item)
      return {
        key,
        label: formatSeverity(key),
        value: Number(item.value || 0),
        color: riskColor(key),
      }
    })
    .filter((item) => item.value > 0)
    .sort((left, right) => order[left.key] - order[right.key])

  const total = mapped.reduce((sum, item) => sum + item.value, 0) || 1
  return mapped.map((item) => ({
    ...item,
    shareText: `(${((item.value / total) * 100).toFixed(1)}%)`,
  }))
})

const riskTotal = computed(() => riskEntries.value.reduce((sum, item) => sum + item.value, 0))
const riskTotalDisplay = computed(() => riskTotal.value || Number(summary.totalHits || 0))

const riskDonutStyle = computed(() => {
  if (!riskEntries.value.length) {
    return { background: 'conic-gradient(#dfe8f6 0 100%)' }
  }
  let start = 0
  const segments = riskEntries.value
    .map((item) => {
      const width = (item.value / riskTotal.value) * 100
      const end = start + width
      const segment = `${item.color} ${start}% ${end}%`
      start = end
      return segment
    })
    .join(', ')
  return { background: `conic-gradient(${segments})` }
})

const typeBars = computed(() => {
  const entries = [...(summary.sensitiveTypeTop || [])]
    .map((item) => ({ name: item.name, value: Number(item.value || 0) }))
    .sort((left, right) => right.value - left.value)
    .slice(0, 8)
  const maxValue = entries.reduce((max, item) => Math.max(max, item.value), 0)
  return entries.map((item) => ({
    ...item,
    width: maxValue ? `${(item.value / maxValue) * 100}%` : '0%',
  }))
})

function resolvePlatformBrand(name = '') {
  const raw = String(name || '').trim()
  const normalized = raw.toLowerCase()
  if (normalized.includes('github')) return { key: 'github', label: 'GitHub', logo: PLATFORM_LOGOS.github, progressColor: '#3b82f6' }
  if (normalized.includes('gitee')) return { key: 'gitee', label: 'Gitee', logo: PLATFORM_LOGOS.gitee, progressColor: '#e67a36' }
  if (normalized.includes('gitlab')) return { key: 'gitlab', label: 'GitLab', logo: PLATFORM_LOGOS.gitlab, progressColor: '#f08b43' }
  const fallback = (raw || 'NA').slice(0, 2).toUpperCase()
  return {
    key: 'generic',
    label: raw || '未知平台',
    logo: `<span class="source-logo__fallback">${fallback}</span>`,
    progressColor: '#7089a6',
  }
}

function normalizeRiskKey(item) {
  const raw = String(item.key || item.name || item.label || '').toLowerCase()
  if (raw.includes('high') || raw.includes('高')) return 'high'
  if (raw.includes('medium') || raw.includes('中')) return 'medium'
  if (raw.includes('low') || raw.includes('低')) return 'low'
  return 'unknown'
}

function riskColor(key) {
  if (key === 'high') return '#ff545d'
  if (key === 'medium') return '#ff9b2f'
  if (key === 'low') return '#2e83ff'
  return '#93a7c4'
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function formatSeverity(value) {
  if (value === 'high') return '高危'
  if (value === 'medium') return '中危'
  if (value === 'low') return '低危'
  return '未知'
}

function resultLayerLabel(value) {
  return value === 'clue' ? '线索命中' : '敏感命中'
}

function platformLabel(row) {
  return row.platformLabel || row.platform || '-'
}

function repositoryLabel(row) {
  return row.repositoryFullName || row.repositoryName || '-'
}

function sensitiveTypeLabel(row) {
  return row.sensitiveLabel || row.sensitiveType || '-'
}

function suppressionReasonLabel(row) {
  return Array.isArray(row.suppressionReasons) && row.suppressionReasons.length
    ? row.suppressionReasons.join(' / ')
    : '-'
}

function severityBadgeClass(value) {
  if (value === 'high') return 'high'
  if (value === 'medium') return 'medium'
  if (value === 'low') return 'low'
  return 'low'
}

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

function firstQueryValue(value) {
  return Array.isArray(value) ? value[0] : value
}

function parseIntegerQuery(value, fallback) {
  const parsed = Number.parseInt(String(firstQueryValue(value) || ''), 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function applyRouteFilters(query = route.query) {
  applyingRouteState.value = true
  watchlistFilter.value = query.watchlist ? parseIntegerQuery(query.watchlist, '') : ''
  platformFilter.value = String(firstQueryValue(query.platform) || '')
  severityFilter.value = String(firstQueryValue(query.severity) || '')
  resultLayerFilter.value = String(firstQueryValue(query.layer) || '')
  sensitiveTypeFilter.value = String(firstQueryValue(query.sensitiveType) || '')
  keyword.value = String(firstQueryValue(query.keyword) || '')
  currentPage.value = parseIntegerQuery(query.page, 1)
  pageSize.value = [10, 20, 50].includes(parseIntegerQuery(query.pageSize, 10))
    ? parseIntegerQuery(query.pageSize, 10)
    : 10
  applyingRouteState.value = false
}

function buildRouteQuery() {
  const query = {}
  if (watchlistFilter.value) query.watchlist = String(watchlistFilter.value)
  if (platformFilter.value) query.platform = platformFilter.value
  if (severityFilter.value) query.severity = severityFilter.value
  if (resultLayerFilter.value) query.layer = resultLayerFilter.value
  if (sensitiveTypeFilter.value) query.sensitiveType = sensitiveTypeFilter.value
  if (keyword.value.trim()) query.keyword = keyword.value.trim()
  if (currentPage.value > 1) query.page = String(currentPage.value)
  if (pageSize.value !== 10) query.pageSize = String(pageSize.value)
  return query
}

function syncRouteQuery() {
  if (applyingRouteState.value) return
  router.replace({
    name: 'CodeMonitoringWorkbench',
    query: buildRouteQuery(),
  })
}

function summarySnapshot() {
  return {
    totalHits: summary.totalHits,
    sensitiveSnippetCount: summary.sensitiveSnippetCount,
    clueHitCount: summary.clueHitCount,
    primaryHitCount: summary.primaryHitCount,
    suppressedHitCount: summary.suppressedHitCount,
    secretLikeCount: summary.secretLikeCount,
    highRiskRepoCount: summary.highRiskRepoCount,
    recentCount: summary.recentCount,
    trend: Array.isArray(summary.trend) ? [...summary.trend] : [],
    platformDistribution: Array.isArray(summary.platformDistribution) ? [...summary.platformDistribution] : [],
    sensitiveTypeTop: Array.isArray(summary.sensitiveTypeTop) ? [...summary.sensitiveTypeTop] : [],
    riskDistribution: Array.isArray(summary.riskDistribution) ? [...summary.riskDistribution] : [],
    lastScanAt: summary.lastScanAt,
  }
}

function persistWorkbenchCache() {
  try {
    sessionStorage.setItem(
      WORKBENCH_CACHE_KEY,
      JSON.stringify({
        savedAt: Date.now(),
        summary: summarySnapshot(),
        hits: hits.value,
        watchlists: watchlists.value,
      }),
    )
  } catch {
    // Ignore cache write failures.
  }
}

function restoreWorkbenchCache() {
  try {
    const raw = sessionStorage.getItem(WORKBENCH_CACHE_KEY)
    if (!raw) return false
    const payload = JSON.parse(raw)
    if (!payload || typeof payload !== 'object') return false
    const savedAt = Number(payload.savedAt || 0)
    if (!savedAt || Date.now() - savedAt > WORKBENCH_CACHE_TTL_MS) return false
    Object.assign(summary, payload.summary || {})
    hits.value = Array.isArray(payload.hits) ? payload.hits : []
    watchlists.value = Array.isArray(payload.watchlists) ? payload.watchlists : []
    return true
  } catch {
    return false
  }
}

async function loadData({ background = false } = {}) {
  try {
    const [summaryPayload, hitPayload, watchlistPayload] = await Promise.all([
      api.loadSummary(),
      api.loadHits({ limit: 300, includeSuppressed: true }),
      api.loadWatchlists(),
    ])
    Object.assign(summary, summaryPayload || {})
    hits.value = Array.isArray(hitPayload) ? hitPayload : []
    watchlists.value = Array.isArray(watchlistPayload) ? watchlistPayload : []
    persistWorkbenchCache()
  } catch (error) {
    ElMessage.error(error.message || '加载代码监测数据失败')
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
      search_page_limit: 0,
      max_results_per_term: 0,
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
    query: { from: route.fullPath },
  })
}

watch([primaryHits, pageSize], () => {
  const maxPage = Math.max(1, Math.ceil(primaryHits.value.length / pageSize.value))
  if (currentPage.value > maxPage) currentPage.value = maxPage
})

watch([suppressedHits, suppressedPageSize], () => {
  const maxPage = Math.max(1, Math.ceil(suppressedHits.value.length / suppressedPageSize.value))
  if (suppressedCurrentPage.value > maxPage) suppressedCurrentPage.value = maxPage
})

watch(
  [watchlistFilter, platformFilter, severityFilter, resultLayerFilter, sensitiveTypeFilter, keyword, currentPage, pageSize],
  syncRouteQuery,
)

watch(
  () => route.query,
  (query) => {
    applyRouteFilters(query)
  },
)

onMounted(async () => {
  applyRouteFilters(route.query)
  const restored = restoreWorkbenchCache()
  await loadData({ background: restored })
})
</script>

<style scoped lang="scss">
* {
  box-sizing: border-box;
}

.monitoring-workbench {
  --bg: #f4f7fc;
  --bg-deep: #ebf1fa;
  --panel: rgba(255, 255, 255, 0.94);
  --panel-soft: rgba(247, 250, 255, 0.92);
  --panel-line: rgba(97, 135, 189, 0.18);
  --text: #182538;
  --text-soft: #56697f;
  --text-faint: #8798ad;
  --blue: #2e83ff;
  --blue-soft: #4ea1ff;
  --orange: #ff9b2f;
  --red: #ff545d;
  --green: #2fd597;
  --yellow: #f5bb45;
  --shadow: 0 18px 42px rgba(34, 67, 113, 0.08);
  --radius: 18px;
  --font: 'Bahnschrift', 'Segoe UI', 'Microsoft YaHei UI', sans-serif;
  --font-mono: 'DIN Alternate', 'Bahnschrift', 'Consolas', monospace;
  position: relative;
  min-height: 100%;
  background: #ffffff;
  color: var(--text);
  font-family: var(--font);
}

.monitoring-workbench::before {
  content: none;
}

.page {
  position: relative;
  z-index: 1;
  width: min(1480px, calc(100% - 48px));
  margin: 0 auto;
  padding: 26px 0 40px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: center;
  margin-bottom: 18px;
}

h1 {
  margin: 0;
  font-family: var(--font);
  font-size: clamp(30px, 3.6vw, 44px);
  line-height: 1.1;
  letter-spacing: 0.02em;
}

.header-actions {
  flex: none;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.ghost-btn,
.primary-btn {
  min-width: 108px;
  height: 42px;
  padding: 0 18px;
  border-radius: 999px;
  font-family: var(--font);
  font-weight: 700;
}

.top-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.1fr) minmax(460px, 1fr);
  gap: 16px;
}

.top-grid__metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.panel {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--panel-line);
  border-radius: var(--radius);
  background: #ffffff;
  box-shadow: var(--shadow);
}

.panel::after {
  content: none;
}

.metric-card {
  min-height: 132px;
  padding: 18px 18px;
}

.source-card {
  min-height: 136px;
  padding: 18px 20px 16px;
}

.panel-title,
.chart-title {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-title {
  margin-bottom: 18px;
}

.panel-title h2,
.chart-title h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: 0;
}

.metric-card .panel-title h2 {
  white-space: nowrap;
}

.info-dot {
  width: 18px;
  height: 18px;
  border: 1px solid rgba(140, 170, 214, 0.34);
  border-radius: 50%;
  color: var(--text-faint);
  display: inline-grid;
  place-items: center;
  font-size: 11px;
}

.metric-main {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 52px;
}

.icon-box {
  display: grid;
  place-items: center;
  flex: none;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  border: 1px solid rgba(107, 144, 196, 0.16);
  background: rgba(255, 255, 255, 0.98);
  box-shadow:
    inset 0 0 18px rgba(255, 255, 255, 0.6),
    0 10px 20px rgba(40, 77, 128, 0.08);
}

.icon-box :deep(svg) {
  width: 24px;
  height: 24px;
  display: block;
}

.tone-blue {
  color: #6aa9f5;
}

.tone-violet {
  color: #919cf2;
}

.tone-orange {
  color: #f0b55e;
}

.tone-red {
  color: #ee949a;
}

.metric-value {
  margin-top: 0;
  font-family: var(--font-mono);
  font-size: 38px;
  font-weight: 700;
  line-height: 1;
}

.source-list {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.source-item {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.source-item__main {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.source-item__content {
  min-width: 0;
}

.source-logo {
  flex: none;
  width: 46px;
  height: 46px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  border: 1px solid rgba(92, 130, 184, 0.12);
  color: white;
}

.source-logo :deep(svg) {
  width: 25px;
  height: 25px;
  display: block;
}

.source-logo :deep(.source-logo__fallback) {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
}

.source-logo.github {
  background: linear-gradient(135deg, #365d90 0%, #173356 52%, #102241 100%);
}

.source-logo.gitee {
  background: linear-gradient(135deg, #f06366 0%, #c82f32 52%, #7d151d 100%);
}

.source-logo.gitlab {
  background: linear-gradient(135deg, #ffb05e 0%, #df5f24 52%, #822e23 100%);
}

.source-logo.generic {
  background: linear-gradient(135deg, #7089a6 0%, #536b89 100%);
}

.source-name {
  font-size: 14px;
  font-weight: 700;
}

.source-metrics {
  display: flex;
  gap: 10px;
  margin-top: 2px;
  color: var(--text-soft);
  font-size: 12px;
  align-items: baseline;
}

.source-metrics strong {
  color: var(--text);
  font-size: 15px;
  font-family: var(--font-mono);
}

.source-progress {
  height: 4px;
  margin-left: 58px;
  border-radius: 999px;
  background: rgba(202, 216, 236, 0.9);
  overflow: hidden;
}

.source-progress__fill {
  display: block;
  height: 100%;
  min-width: 6px;
  border-radius: inherit;
}

.content-grid {
  display: grid;
  grid-template-columns: 1.45fr 1.08fr 1.12fr;
  gap: 16px;
  margin-top: 16px;
}

.chart-panel {
  padding: 16px 18px 18px;
  min-height: 330px;
}

.chart-title {
  margin-bottom: 10px;
  align-items: baseline;
}

.chart-title span {
  color: var(--text-faint);
  font-size: 14px;
  font-weight: 600;
}

.trend-wrap {
  position: relative;
  z-index: 1;
  height: 260px;
}

.trend-wrap svg {
  width: 100%;
  height: 100%;
  display: block;
  text-rendering: geometricPrecision;
}

.risk-layout {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(180px, 220px) 1fr;
  gap: 10px;
  align-items: center;
  height: 252px;
}

.donut-shell {
  width: 196px;
  height: 196px;
  margin: 0 auto;
  border-radius: 50%;
  display: grid;
  place-items: center;
}

.donut-inner {
  width: 116px;
  height: 116px;
  border-radius: 50%;
  border: 1px solid rgba(98, 143, 210, 0.2);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(238, 244, 252, 0.98));
  box-shadow: inset 0 0 28px rgba(70, 111, 168, 0.08);
  display: grid;
  place-items: center;
  text-align: center;
}

.donut-total {
  font-family: var(--font-mono);
  font-size: 34px;
  line-height: 1;
}

.donut-label {
  margin-top: 4px;
  color: var(--text-soft);
  font-size: 12px;
}

.legend-list {
  display: grid;
  gap: 14px;
}

.legend-item {
  display: grid;
  grid-template-columns: 12px auto auto;
  gap: 10px;
  align-items: center;
  color: var(--text-soft);
  font-size: 13px;
  justify-content: start;
}

.legend-item span:nth-child(2),
.legend-item span:last-child {
  white-space: nowrap;
}

.legend-dot {
  width: 12px;
  height: 12px;
  border-radius: 3px;
}

.legend-item strong {
  color: var(--text);
  font-family: var(--font-mono);
}

.bar-list {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 12px;
  padding-top: 4px;
}

.bar-row {
  display: grid;
  grid-template-columns: 88px 1fr auto;
  gap: 12px;
  align-items: center;
  color: var(--text-soft);
  font-size: 13px;
}

.bar-track {
  position: relative;
  height: 9px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(83, 123, 182, 0.12);
  border: 1px solid rgba(83, 123, 182, 0.12);
}

.bar-fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  background: linear-gradient(90deg, #266ee8, #51a7ff);
  box-shadow: 0 0 14px rgba(46, 131, 255, 0.2);
}

.bar-row strong {
  color: var(--text);
  font-family: var(--font-mono);
}

.stack {
  display: grid;
  gap: 16px;
}

.table-panel {
  margin-top: 16px;
  padding: 18px 18px 12px;
}

.table-title {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.table-title h2 {
  margin: 0;
  font-size: 18px;
}

.table-toolbar {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
}

.table-toolbar-left {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-control {
  width: 148px;
}

.toolbar-search {
  min-width: 260px;
  flex: 1;
  max-width: 360px;
}

.table-meta {
  color: var(--text-faint);
  font-size: 12px;
}

.table-shell {
  position: relative;
  z-index: 1;
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  min-width: 980px;
}

th,
td {
  padding: 15px 12px;
  text-align: left;
  border-bottom: 1px solid rgba(80, 118, 170, 0.14);
}

th {
  color: var(--text-faint);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

td {
  color: var(--text-soft);
  font-size: 13px;
  vertical-align: middle;
}

td strong {
  color: var(--text);
  font-weight: 700;
}

.cell-ellipsis {
  display: inline-block;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.table-empty {
  text-align: center;
  color: var(--text-faint);
  padding: 28px 12px;
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 72px;
  height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.badge.hit {
  color: #ca4353;
  background: rgba(255, 84, 93, 0.12);
}

.badge.keyword {
  color: #256fd8;
  background: rgba(46, 131, 255, 0.12);
}

.badge.high {
  color: #d97b1f;
  background: rgba(255, 155, 47, 0.14);
}

.badge.medium {
  color: #ab7a10;
  background: rgba(245, 187, 69, 0.16);
}

.badge.low {
  color: #159569;
  background: rgba(47, 213, 151, 0.14);
}

.detail-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 58px;
  height: 30px;
  padding: 0 10px;
  border: 0;
  border-radius: 999px;
  color: white;
  background: linear-gradient(135deg, rgba(24, 99, 212, 0.9), rgba(56, 128, 255, 0.9));
  font-family: var(--font);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.footnote,
.table-footer__note {
  color: var(--text-faint);
  font-size: 12px;
}

.footnote {
  margin-top: 10px;
}

.table-footer {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-top: 18px;
}

.panel-empty {
  position: relative;
  z-index: 1;
  color: var(--text-faint);
  font-size: 13px;
}

.panel-empty--chart {
  display: grid;
  place-items: center;
  min-height: 250px;
}

:deep(.el-button--default) {
  border: 1px solid rgba(113, 145, 195, 0.24);
  color: var(--text);
  background: rgba(255, 255, 255, 0.9);
  box-shadow:
    inset 0 0 0 1px rgba(37, 94, 161, 0.04),
    0 10px 22px rgba(36, 78, 130, 0.06);
}

:deep(.el-button--primary) {
  border-color: rgba(78, 161, 255, 0.36);
  background: linear-gradient(135deg, rgba(24, 99, 212, 0.96), rgba(56, 128, 255, 0.96));
}

:deep(.el-input__wrapper),
:deep(.el-select__wrapper) {
  min-height: 40px;
  border-radius: 999px;
  background: rgba(248, 251, 255, 0.92);
  border: 1px solid rgba(100, 141, 198, 0.2);
  box-shadow: none !important;
}

:deep(.el-input__wrapper.is-focus),
:deep(.el-select__wrapper.is-focused) {
  border-color: rgba(78, 161, 255, 0.38);
  box-shadow: 0 0 0 4px rgba(46, 131, 255, 0.08) !important;
}

:deep(.el-input__inner),
:deep(.el-select__selected-item),
:deep(.el-select__placeholder) {
  font-family: var(--font);
  color: var(--text);
}

:deep(.el-pagination) {
  --el-pagination-bg-color: rgba(255, 255, 255, 0.95);
  --el-pagination-button-color: #61748b;
  --el-pagination-hover-color: #2e83ff;
}

@media (max-width: 1100px) {
  .top-grid {
    grid-template-columns: 1fr;
  }

  .top-grid__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .content-grid {
    grid-template-columns: 1fr 1fr;
  }

  .content-grid .chart-panel:first-child {
    grid-column: 1 / -1;
  }
}

@media (max-width: 980px) {
  .page {
    width: min(100% - 28px, 1480px);
    padding-top: 20px;
  }

  .page-header,
  .table-toolbar,
  .table-title,
  .table-footer {
    flex-direction: column;
    align-items: flex-start;
  }

  .top-grid__metrics,
  .content-grid,
  .risk-layout {
    grid-template-columns: 1fr;
  }

  .donut-shell {
    width: 180px;
    height: 180px;
  }

  .source-list {
    grid-template-columns: 1fr;
  }

  .toolbar-search {
    width: 100%;
    max-width: none;
  }
}

@media (max-width: 720px) {
  .top-grid__metrics {
    grid-template-columns: 1fr;
  }

  .bar-row {
    grid-template-columns: 74px 1fr 48px;
    gap: 8px;
  }
}
</style>
