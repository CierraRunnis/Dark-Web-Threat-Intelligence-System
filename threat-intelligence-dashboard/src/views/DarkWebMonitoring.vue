<template>
  <div class="darkweb-monitoring ti-page">
    <section class="ti-panel monitoring-header ti-reveal-up">
      <div class="monitoring-header__summary">
        <div class="monitoring-header__title-row">
          <h1>暗网监测工作台</h1>
          <span :class="['service-state', serviceStateClass]">{{ serviceStateLabel }}</span>
        </div>
        <div class="service-facts">
          <span><b>{{ service.slaMinutes || 30 }}</b> 分钟复核 SLA</span>
          <span><b>{{ service.connectedPlatformCount || 0 }}</b> / {{ service.monitoredPlatformCount || 4 }} 平台已连接</span>
          <span>更新于 {{ formatDateTime(service.lastUpdatedAt) || '-' }}</span>
        </div>
      </div>

      <div class="monitoring-header__actions">
        <el-button :loading="overviewLoading" plain @click="loadOverview">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
        <el-button type="primary" :loading="runningMonitoring" @click="runMonitoring">
          <el-icon><VideoPlay /></el-icon>
          运行监测
        </el-button>
      </div>
    </section>

    <section class="metrics-grid" aria-label="暗网监测指标">
      <article
        v-for="item in metricCards"
        :key="item.key"
        :class="['ti-card', 'metric-card', 'metric-card--' + item.tone]"
      >
        <div class="metric-card__head">
          <span>{{ item.label }}</span>
          <el-icon><component :is="item.icon" /></el-icon>
        </div>
        <strong class="ti-number">{{ item.value }}</strong>
        <small>{{ item.detail }}</small>
      </article>
    </section>

    <section class="platform-section">
      <div class="section-heading">
        <div>
          <h2>监测平台</h2>
        </div>
        <span class="section-heading__note">{{ enabledPlatformCount }} 个平台启用</span>
      </div>

      <div class="platform-grid">
        <article v-for="platform in monitoredPlatforms" :key="platform.key" class="ti-card platform-card">
          <div class="platform-card__head">
            <div>
              <h3>{{ platform.name }}</h3>
              <span>{{ platform.kind || '-' }}</span>
            </div>
            <span :class="['platform-status', 'platform-status--' + platformStatusTone(platform)]">
              {{ platformStatusLabel(platform) }}
            </span>
          </div>
          <dl class="platform-card__facts">
            <div>
              <dt>今日发现</dt>
              <dd class="ti-number">{{ platform.findingCount || 0 }}</dd>
            </div>
            <div>
              <dt>最近连接</dt>
              <dd>{{ formatDateTime(platform.lastSeenAt) || '-' }}</dd>
            </div>
          </dl>
          <p v-if="platform.lastError || platform.configurationHint" class="platform-card__hint">
            {{ platform.lastError || platform.configurationHint }}
          </p>
        </article>
      </div>
    </section>

    <section class="ti-card cases-card ti-reveal-up">
      <div class="ti-card-body">
        <EventTableToolbar
          title="暗网案件队列"
          :search-value="filters.search"
          search-placeholder="搜索标题、目标、来源或处置记录"
          :active-filters="activeFilters"
          @update:search-value="filters.search = $event"
        >
          <template #filters>
            <el-select v-model="filters.platform" class="filter-control" placeholder="来源平台" clearable>
              <el-option v-for="item in platformFilterOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-model="filters.verificationStatus" class="filter-control" placeholder="复核状态" clearable>
              <el-option v-for="item in verificationOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-model="filters.slaStatus" class="filter-control" placeholder="SLA 状态" clearable>
              <el-option v-for="item in slaOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-model="filters.threatType" class="filter-control" placeholder="威胁类型" clearable filterable>
              <el-option v-for="item in threatTypeOptions" :key="item" :label="labelValue(item)" :value="item" />
            </el-select>
            <el-select v-model="filters.targetIndustry" class="filter-control" placeholder="目标行业" clearable filterable>
              <el-option v-for="item in targetIndustryOptions" :key="item" :label="item" :value="item" />
            </el-select>
            <el-select v-model="filters.screenshot" class="filter-control" placeholder="截图状态" clearable>
              <el-option label="截图合规" value="compliant" />
              <el-option label="截图未合规" value="non_compliant" />
              <el-option label="未上传截图" value="missing" />
            </el-select>
          </template>
        </EventTableToolbar>

        <div class="ti-table-shell case-table-shell">
          <el-table
            v-loading="overviewLoading"
            :data="pagedCases"
            table-layout="fixed"
            empty-text="暂无暗网监测案件"
            style="width: 100%"
          >
            <el-table-column label="案件">
              <template #default="{ row }">
                <div class="case-primary-cell">
                  <strong :title="row.title">{{ row.title || '未命名案件' }}</strong>
                  <span>#{{ row.id }} · {{ platformName(row.sourcePlatform) }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="威胁对象">
              <template #default="{ row }">
                <div class="case-stacked-cell">
                  <strong>{{ labelValue(row.threatType) }}</strong>
                  <span :title="row.targetName">{{ row.targetName || '待确认' }} · {{ row.targetIndustry || '待确认' }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="发现时间">
              <template #default="{ row }">
                <div class="case-stacked-cell">
                  <strong>{{ formatDateTime(row.discoveredAt) || '-' }}</strong>
                  <span>入库 {{ formatDateTime(row.firstDetectedAt) || '-' }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="SLA">
              <template #default="{ row }">
                <span :class="['case-badge', 'case-badge--' + slaTone(row.slaStatus)]">
                  {{ slaLabel(row.slaStatus) }}
                </span>
                <small class="case-cell-note">{{ formatSlaMinutes(row.slaMinutesRemaining) }}</small>
              </template>
            </el-table-column>
            <el-table-column label="复核">
              <template #default="{ row }">
                <div class="case-stacked-cell">
                  <strong>{{ verificationLabel(row.verificationStatus) }}</strong>
                  <span>{{ confidenceLabel(row.confidenceLevel) }}置信度 · 截图{{ screenshotLabel(row) }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="编目">
              <template #default="{ row }">
                <div class="case-stacked-cell">
                  <strong>{{ row.catalogNumber || catalogStatusLabel(row.catalogStatus) }}</strong>
                  <span>{{ row.pushedAt ? '已报送' : '未报送' }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="128">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button link type="primary" @click="openReview(row)">详情</el-button>
                  <el-button link :loading="pushingCaseId === row.id" @click="pushCase(row)">推送</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="mobile-case-list">
          <article v-for="row in pagedCases" :key="row.id" class="mobile-case-card">
            <div class="mobile-case-card__head">
              <div>
                <strong>{{ row.title || '未命名案件' }}</strong>
                <span>#{{ row.id }} · {{ platformName(row.sourcePlatform) }}</span>
              </div>
              <span :class="['case-badge', 'case-badge--' + slaTone(row.slaStatus)]">{{ slaLabel(row.slaStatus) }}</span>
            </div>
            <dl>
              <div><dt>威胁对象</dt><dd>{{ labelValue(row.threatType) }} · {{ row.targetName || '待确认' }}</dd></div>
              <div><dt>发现时间</dt><dd>{{ formatDateTime(row.discoveredAt) || '-' }}</dd></div>
              <div><dt>复核状态</dt><dd>{{ verificationLabel(row.verificationStatus) }} · {{ confidenceLabel(row.confidenceLevel) }}置信度</dd></div>
              <div><dt>编目状态</dt><dd>{{ row.catalogNumber || catalogStatusLabel(row.catalogStatus) }}</dd></div>
            </dl>
            <div class="mobile-case-card__actions">
              <el-button size="small" type="primary" plain @click="openReview(row)">查看详情</el-button>
              <el-button size="small" :loading="pushingCaseId === row.id" @click="pushCase(row)">推送</el-button>
            </div>
          </article>
          <el-empty v-if="!pagedCases.length" description="暂无暗网监测案件" :image-size="64" />
        </div>

        <div class="table-footer">
          <span>共 {{ filteredCases.length }} 条案件</span>
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :page-sizes="[10, 20, 50]"
            :total="filteredCases.length"
            layout="total, sizes, prev, pager, next"
            background
          />
        </div>
      </div>
    </section>

    <section class="report-band ti-panel ti-reveal-up">
      <div class="report-band__heading">
        <h2>监测报告</h2>
      </div>
      <div class="report-controls">
        <div class="report-control">
          <el-date-picker
            v-model="reportDate"
            type="date"
            value-format="YYYY-MM-DD"
            format="YYYY-MM-DD"
            :clearable="false"
            aria-label="日报日期"
          />
          <el-button :loading="exportingDaily" @click="exportDailyReport">
            <el-icon><Download /></el-icon>
            导出日报
          </el-button>
        </div>
        <div class="report-control">
          <el-select v-model="reportMonth" filterable allow-create default-first-option aria-label="月报月份">
            <el-option v-for="item in monthlyPeriodOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-button :loading="exportingMonthly" @click="exportMonthlyReport">
            <el-icon><Download /></el-icon>
            导出月报
          </el-button>
        </div>
      </div>
    </section>

    <el-drawer
      v-model="reviewVisible"
      :title="selectedCase ? '案件复核 · ' + selectedCase.id : '案件复核'"
      size="min(680px, 100%)"
      destroy-on-close
    >
      <div v-if="selectedCase" class="review-drawer">
        <div class="review-evidence">
          <div>
            <span>来源平台</span>
            <strong>{{ platformName(selectedCase.sourcePlatform) }}</strong>
          </div>
          <div>
            <span>发现时间</span>
            <strong>{{ formatDateTime(selectedCase.discoveredAt) || '-' }}</strong>
          </div>
          <div>
            <span>首次入库</span>
            <strong>{{ formatDateTime(selectedCase.firstDetectedAt) || '-' }}</strong>
          </div>
          <div>
            <span>SLA 状态</span>
            <strong>{{ slaLabel(selectedCase.slaStatus) }} · {{ formatSlaMinutes(selectedCase.slaMinutesRemaining) }}</strong>
          </div>
          <div>
            <span>SLA 截止</span>
            <strong>{{ formatDateTime(selectedCase.slaDueAt) || '-' }}</strong>
          </div>
          <div>
            <span>来源链接</span>
            <el-link
              v-if="safeUrl(selectedCase.sourceUrl)"
              :href="safeUrl(selectedCase.sourceUrl)"
              target="_blank"
              rel="noreferrer"
            >
              打开原始页面
            </el-link>
            <strong v-else>-</strong>
          </div>
          <div>
            <span>情报编目</span>
            <strong>{{ selectedCase.catalogNumber || catalogStatusLabel(selectedCase.catalogStatus) }}</strong>
          </div>
          <div>
            <span>截图状态</span>
            <strong>{{ screenshotLabel(selectedCase) }}</strong>
          </div>
          <div>
            <span>报送状态</span>
            <strong>{{ selectedCase.pushedAt ? '已于 ' + formatDateTime(selectedCase.pushedAt) + ' 报送' : '未报送' }}</strong>
          </div>
        </div>

        <div class="review-excerpt">
          <h3>{{ selectedCase.title || '未命名案件' }}</h3>
          <p>{{ selectedCase.contentExcerpt || '暂无内容摘录' }}</p>
        </div>

        <div v-if="safeUrl(selectedCase.screenshotUrl)" class="screenshot-preview">
          <div class="screenshot-preview__head">
            <span>证据截图</span>
            <el-link :href="safeUrl(selectedCase.screenshotUrl)" target="_blank" rel="noreferrer">查看原图</el-link>
          </div>
          <img
            v-if="!screenshotPreviewFailed"
            :src="safeUrl(selectedCase.screenshotUrl)"
            :alt="selectedCase.title || '暗网案件截图'"
            @error="screenshotPreviewFailed = true"
          />
          <div v-else class="screenshot-preview__fallback">截图暂不可预览，请通过原图链接查看。</div>
        </div>

        <el-form label-position="top" class="review-form">
          <div class="review-form__grid">
            <el-form-item label="复核状态">
              <el-select v-model="reviewForm.verification_status">
                <el-option v-for="item in verificationOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="置信度">
              <el-select v-model="reviewForm.confidence_level">
                <el-option v-for="item in confidenceOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="目标名称">
              <el-input v-model="reviewForm.target_name" />
            </el-form-item>
            <el-form-item label="目标行业">
              <el-input v-model="reviewForm.target_industry" />
            </el-form-item>
            <el-form-item label="威胁类型">
              <el-input v-model="reviewForm.threat_type" />
            </el-form-item>
            <el-form-item label="复核人">
              <el-input v-model="reviewForm.reviewer" />
            </el-form-item>
            <el-form-item label="处置结论">
              <el-input v-model="reviewForm.disposition" />
            </el-form-item>
            <el-form-item label="截图合规">
              <el-switch
                v-model="reviewForm.screenshot_compliant"
                inline-prompt
                active-text="合规"
                inactive-text="未合规"
              />
            </el-form-item>
          </div>
          <el-form-item label="建议措施">
            <el-input v-model="reviewForm.suggested_action" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="复核备注">
            <el-input v-model="reviewForm.note" type="textarea" :rows="4" />
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <div class="drawer-actions">
          <el-button @click="reviewVisible = false">取消</el-button>
          <el-button type="primary" :loading="savingReview" @click="saveReview">保存复核</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import EventTableToolbar from '@/components/common/EventTableToolbar.vue'
import { useDarkWebMonitoringApi } from '@/composables/useDarkWebMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const api = useDarkWebMonitoringApi()

const PLATFORM_DEFINITIONS = [
  { key: 'changan-night-city', aliases: ['changan-night-city', 'changan', '长安不夜城'], name: '长安不夜城', kind: '暗网论坛' },
  { key: 'xss', aliases: ['xss'], name: 'XSS', kind: '暗网论坛' },
  { key: 'breachforums', aliases: ['breachforums', 'breach_forums'], name: 'BreachForums', kind: '数据泄露论坛' },
  { key: 'telegram', aliases: ['telegram', 'tg'], name: 'Telegram', kind: '即时通信频道' },
]

const verificationOptions = [
  { label: '待复核', value: 'pending' },
  { label: '已确认', value: 'verified' },
  { label: '误报', value: 'false_positive' },
  { label: '持续监测', value: 'monitoring' },
]

const confidenceOptions = [
  { label: '高', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '低', value: 'low' },
]

const slaOptions = [
  { label: 'SLA 内', value: 'pending' },
  { label: '临近超时', value: 'at_risk' },
  { label: '已超时', value: 'breached' },
  { label: '已完成', value: 'completed' },
]

const emptyOverview = () => ({
  service: {
    slaMinutes: 30,
    monitoredPlatformCount: 4,
    connectedPlatformCount: 0,
    lastUpdatedAt: '',
    autoMonitoringEnabled: false,
  },
  metrics: {
    todayFindings: 0,
    pendingVerification: 0,
    slaBreached: 0,
    verifiedThisMonth: 0,
  },
  platforms: [],
  cases: [],
  monthlyPeriods: [],
})

const overview = ref(emptyOverview())
const overviewLoading = ref(false)
const runningMonitoring = ref(false)
const pushingCaseId = ref(null)
const savingReview = ref(false)
const reviewVisible = ref(false)
const selectedCase = ref(null)
const screenshotPreviewFailed = ref(false)
const currentPage = ref(1)
const pageSize = ref(10)
const exportingDaily = ref(false)
const exportingMonthly = ref(false)

const filters = reactive({
  search: '',
  platform: '',
  verificationStatus: '',
  slaStatus: '',
  threatType: '',
  targetIndustry: '',
  screenshot: '',
})

const reviewForm = reactive({
  verification_status: 'pending',
  confidence_level: 'medium',
  target_name: '',
  target_industry: '',
  threat_type: '',
  suggested_action: '',
  screenshot_compliant: false,
  reviewer: '',
  disposition: '',
  note: '',
})

function localDateValue(date = new Date()) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return year + '-' + month + '-' + day
}

const reportDate = ref(localDateValue())
const reportMonth = ref(reportDate.value.slice(0, 7))

const service = computed(() => overview.value.service)
const cases = computed(() => overview.value.cases)
const enabledPlatformCount = computed(() => monitoredPlatforms.value.filter((item) => item.enabled).length)
const serviceStateLabel = computed(() => service.value.autoMonitoringEnabled ? '自动监测已开启' : '自动监测未开启')
const serviceStateClass = computed(() => service.value.autoMonitoringEnabled ? 'service-state--active' : 'service-state--inactive')

const metricCards = computed(() => [
  {
    key: 'todayFindings',
    label: '今日发现',
    value: overview.value.metrics.todayFindings || 0,
    detail: '今日进入案件队列',
    icon: 'DataLine',
    tone: 'primary',
  },
  {
    key: 'pendingVerification',
    label: '待复核',
    value: overview.value.metrics.pendingVerification || 0,
    detail: (service.value.slaMinutes || 30) + ' 分钟内需完成复核',
    icon: 'Timer',
    tone: 'warning',
  },
  {
    key: 'slaBreached',
    label: 'SLA 超时',
    value: overview.value.metrics.slaBreached || 0,
    detail: '已超过复核时限',
    icon: 'WarningFilled',
    tone: 'danger',
  },
  {
    key: 'verifiedThisMonth',
    label: '本月已核验',
    value: overview.value.metrics.verifiedThisMonth || 0,
    detail: '已完成复核闭环',
    icon: 'CircleCheck',
    tone: 'success',
  },
])

const monitoredPlatforms = computed(() => PLATFORM_DEFINITIONS.map((definition) => {
  const platform = overview.value.platforms.find((item) => {
    const candidates = [item.key, item.name].map(normalize)
    return definition.aliases.some((alias) => candidates.includes(normalize(alias)))
  })
  return {
    ...definition,
    enabled: false,
    status: 'unconfigured',
    lastSeenAt: '',
    findingCount: 0,
    configurationHint: '',
    ...platform,
    name: platform?.name || definition.name,
    kind: platform?.kind || definition.kind,
  }
}))

const platformFilterOptions = computed(() => {
  const values = new Map()
  for (const platform of monitoredPlatforms.value) values.set(platform.key, platform.name)
  for (const item of cases.value) {
    if (item.sourcePlatform) values.set(item.sourcePlatform, platformName(item.sourcePlatform))
  }
  return [...values].map(([value, label]) => ({ value, label }))
})

const threatTypeOptions = computed(() => uniqueCaseValues('threatType'))
const targetIndustryOptions = computed(() => uniqueCaseValues('targetIndustry'))

const monthlyPeriodOptions = computed(() => {
  const values = overview.value.monthlyPeriods
    .map((item) => {
      const value = typeof item === 'string' ? item : item?.month || item?.period || item?.value
      if (!value) return null
      return {
        value: String(value),
        label: typeof item === 'object' && item.label ? item.label : String(value),
      }
    })
    .filter(Boolean)
  if (!values.some((item) => item.value === reportMonth.value)) {
    values.unshift({ value: reportMonth.value, label: reportMonth.value })
  }
  return values
})

const filteredCases = computed(() => {
  const keyword = normalize(filters.search)
  return cases.value.filter((item) => {
    const searchable = [
      item.id,
      item.title,
      item.sourcePlatform,
      platformName(item.sourcePlatform),
      item.sourceUrl,
      item.threatType,
      item.targetName,
      item.targetIndustry,
      item.contentExcerpt,
      item.reviewer,
      item.disposition,
      item.note,
      item.suggestedAction,
    ]
    const matchesKeyword = !keyword || searchable.some((value) => normalize(value).includes(keyword))
    const matchesPlatform = !filters.platform || item.sourcePlatform === filters.platform
    const matchesVerification = !filters.verificationStatus || item.verificationStatus === filters.verificationStatus
    const matchesSla = !filters.slaStatus || item.slaStatus === filters.slaStatus
    const matchesThreat = !filters.threatType || item.threatType === filters.threatType
    const matchesIndustry = !filters.targetIndustry || item.targetIndustry === filters.targetIndustry
    const screenshotState = !item.screenshotUrl ? 'missing' : item.screenshotCompliant ? 'compliant' : 'non_compliant'
    const matchesScreenshot = !filters.screenshot || filters.screenshot === screenshotState
    return matchesKeyword && matchesPlatform && matchesVerification && matchesSla && matchesThreat && matchesIndustry && matchesScreenshot
  })
})

const pagedCases = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredCases.value.slice(start, start + pageSize.value)
})

const activeFilters = computed(() => {
  const values = []
  if (filters.platform) values.push('平台: ' + platformName(filters.platform))
  if (filters.verificationStatus) values.push('复核: ' + verificationLabel(filters.verificationStatus))
  if (filters.slaStatus) values.push('SLA: ' + slaLabel(filters.slaStatus))
  if (filters.threatType) values.push('类型: ' + labelValue(filters.threatType))
  if (filters.targetIndustry) values.push('行业: ' + filters.targetIndustry)
  if (filters.screenshot) values.push('截图: ' + screenshotFilterLabel(filters.screenshot))
  if (filters.search.trim()) values.push('搜索: ' + filters.search.trim())
  return values
})

function normalize(value) {
  return String(value || '').trim().toLowerCase()
}

function labelValue(value) {
  if (!value) return '-'
  return String(value).replaceAll('_', ' ')
}

function uniqueCaseValues(key) {
  return [...new Set(cases.value.map((item) => item[key]).filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b), 'zh-CN'))
}

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

function safeUrl(value) {
  if (!value) return ''
  try {
    const url = new URL(value, window.location.origin)
    return ['http:', 'https:'].includes(url.protocol) ? url.href : ''
  } catch {
    return ''
  }
}

function platformName(value) {
  const normalized = normalize(value)
  const definition = PLATFORM_DEFINITIONS.find((item) => item.aliases.some((alias) => normalize(alias) === normalized) || item.key === normalized)
  return definition?.name || value || '-'
}

function platformStatusLabel(platform) {
  if (!platform.enabled) return platform.status === 'unconfigured' ? '未配置' : '未启用'
  const labels = {
    connected: '已连接',
    online: '在线',
    healthy: '正常',
    degraded: '连接异常',
    error: '异常',
    offline: '离线',
    waiting_configuration: '待接入',
    unconfigured: '未配置',
  }
  return labels[platform.status] || labelValue(platform.status)
}

function platformStatusTone(platform) {
  if (!platform.enabled || ['offline', 'unconfigured', 'waiting_configuration'].includes(platform.status)) return 'muted'
  if (['degraded', 'error'].includes(platform.status)) return 'danger'
  return 'success'
}

function verificationLabel(value) {
  const aliases = {
    new: '待复核',
    pending: '待复核',
    reviewing: '复核中',
    confirmed: '已确认',
    verified: '已确认',
    false_positive: '误报',
    rejected: '误报',
    closed: '已关闭',
    monitoring: '持续监测',
  }
  return aliases[value] || labelValue(value)
}

function confidenceLabel(value) {
  return { high: '高', medium: '中', low: '低' }[value] || labelValue(value)
}

function catalogStatusLabel(value) {
  return {
    unfiled: '未编目',
    filed: '已编目',
    cataloged: '已编目',
    excluded: '不编目',
  }[value] || labelValue(value)
}

function slaLabel(value) {
  const labels = {
    pending: 'SLA 内',
    within_sla: 'SLA 内',
    normal: 'SLA 内',
    at_risk: '临近超时',
    due_soon: '临近超时',
    breached: '已超时',
    overdue: '已超时',
    completed: '已完成',
  }
  return labels[value] || labelValue(value)
}

function slaTone(value) {
  if (['breached', 'overdue'].includes(value)) return 'danger'
  if (['at_risk', 'due_soon'].includes(value)) return 'warning'
  if (value === 'completed') return 'success'
  return 'primary'
}

function formatSlaMinutes(value) {
  const minutes = Number(value)
  if (!Number.isFinite(minutes)) return '-'
  if (minutes < 0) return '超时 ' + Math.abs(minutes) + ' 分钟'
  return '剩余 ' + minutes + ' 分钟'
}

function screenshotLabel(row) {
  if (!row.screenshotUrl) return '未上传'
  return row.screenshotCompliant ? '合规' : '未合规'
}

function screenshotTone(row) {
  if (!row.screenshotUrl) return 'muted'
  return row.screenshotCompliant ? 'success' : 'warning'
}

function screenshotFilterLabel(value) {
  return {
    compliant: '合规',
    non_compliant: '未合规',
    missing: '未上传',
  }[value] || value
}

async function loadOverview() {
  overviewLoading.value = true
  try {
    const payload = await api.loadOverview()
    const defaults = emptyOverview()
    overview.value = {
      ...defaults,
      ...payload,
      service: { ...defaults.service, ...(payload?.service || {}) },
      metrics: { ...defaults.metrics, ...(payload?.metrics || {}) },
      platforms: Array.isArray(payload?.platforms) ? payload.platforms : [],
      cases: Array.isArray(payload?.cases) ? payload.cases : [],
      monthlyPeriods: Array.isArray(payload?.monthlyPeriods) ? payload.monthlyPeriods : [],
    }
  } catch (error) {
    ElMessage.error(error.message || '加载暗网监测数据失败')
  } finally {
    overviewLoading.value = false
  }
}

async function runMonitoring() {
  runningMonitoring.value = true
  try {
    const payload = await api.runMonitoring()
    ElMessage.success(payload?.message || '暗网监测任务已启动')
    await loadOverview()
  } catch (error) {
    ElMessage.error(error.message || '运行暗网监测失败')
  } finally {
    runningMonitoring.value = false
  }
}

function openReview(item) {
  selectedCase.value = item
  screenshotPreviewFailed.value = false
  Object.assign(reviewForm, {
    verification_status: item.verificationStatus || 'pending',
    confidence_level: item.confidenceLevel || 'medium',
    target_name: item.targetName || '',
    target_industry: item.targetIndustry || '',
    threat_type: item.threatType || '',
    suggested_action: item.suggestedAction || '',
    screenshot_compliant: Boolean(item.screenshotCompliant),
    reviewer: item.reviewer || '',
    disposition: item.disposition || '',
    note: item.note || '',
  })
  reviewVisible.value = true
}

async function saveReview() {
  if (!selectedCase.value) return
  savingReview.value = true
  try {
    await api.reviewCase(selectedCase.value.id, { ...reviewForm })
    ElMessage.success('案件复核已保存')
    reviewVisible.value = false
    await loadOverview()
  } catch (error) {
    ElMessage.error(error.message || '保存案件复核失败')
  } finally {
    savingReview.value = false
  }
}

async function pushCase(item) {
  pushingCaseId.value = item.id
  try {
    const payload = await api.pushCase(item.id)
    ElMessage.success(payload?.message || '案件已推送')
    await loadOverview()
  } catch (error) {
    ElMessage.error(error.message || '推送案件失败')
  } finally {
    pushingCaseId.value = null
  }
}

function reportValue(value) {
  if (value == null || value === '') return ''
  if (Array.isArray(value)) {
    return value.map((item) => reportValue(item)).filter(Boolean).join('；')
  }
  if (typeof value === 'object') {
    return Object.entries(value)
      .map(([key, item]) => key + ': ' + reportValue(item))
      .filter((item) => !item.endsWith(': '))
      .join('；')
  }
  return String(value)
}

async function buildWordReport(kind, period, payload) {
  const {
    BorderStyle,
    Document,
    HeadingLevel,
    Packer,
    PageOrientation,
    Paragraph,
    Table,
    TableCell,
    TableRow,
    TextRun,
    WidthType,
  } = await import('docx')

  const table = (headers, rows) => new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((header) => new TableCell({
          shading: { fill: 'EDF2FF' },
          children: [new Paragraph({ children: [new TextRun({ text: header, bold: true })] })],
        })),
      }),
      ...rows.map((row) => new TableRow({
        children: row.map((cell) => new TableCell({
          children: [new Paragraph(reportValue(cell) || '-')],
        })),
      })),
    ],
  })

  const heading = (text) => new Paragraph({
    text,
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 260, after: 120 },
    border: {
      left: { color: '2D5DFF', style: BorderStyle.SINGLE, size: 12, space: 8 },
    },
  })

  const title = payload?.title || ('暗网监测' + (kind === 'daily' ? '日报' : '月报'))
  const metrics = payload?.metrics || overview.value.metrics
  const platforms = Array.isArray(payload?.platforms) ? payload.platforms : overview.value.platforms
  const reportCases = [payload?.cases, payload?.findings, payload?.items].find(Array.isArray) || []
  const children = [
    new Paragraph({ text: title, heading: HeadingLevel.TITLE, spacing: { after: 160 } }),
    new Paragraph('报告周期：' + period),
    new Paragraph('生成时间：' + (formatDateTime(payload?.generatedAt) || new Date().toLocaleString('zh-CN', { hour12: false }))),
  ]

  const narrativeSections = [
    ['报告摘要', payload?.summary || payload?.overview || payload?.markdown],
    ['重点发现', payload?.keyFindings || payload?.highlights],
    ['处置建议', payload?.recommendations || payload?.suggestedActions],
  ]
  for (const [sectionTitle, value] of narrativeSections) {
    const text = reportValue(value)
    if (!text) continue
    children.push(heading(sectionTitle), new Paragraph(text))
  }

  children.push(heading('核心指标'))
  children.push(table(
    ['发现线索', '完成初验', '误报', 'SLA 超时', '已推送'],
    [[
      metrics?.findingCount ?? metrics?.todayFindings ?? 0,
      metrics?.verifiedCount ?? metrics?.verifiedThisMonth ?? 0,
      metrics?.falsePositiveCount ?? 0,
      metrics?.slaBreachedCount ?? metrics?.slaBreached ?? 0,
      metrics?.pushedCount ?? 0,
    ]],
  ))

  if (platforms.length) {
    children.push(heading('平台运行状态'))
    children.push(table(
      ['平台', '类型', '启用', '状态', '发现数', '最近连接'],
      platforms.map((item) => [
        item.name || platformName(item.key),
        item.kind,
        item.enabled ? '是' : '否',
        platformStatusLabel(item),
        item.findingCount || 0,
        formatDateTime(item.lastSeenAt),
      ]),
    ))
  }

  children.push(heading('案件清单'))
  if (reportCases.length) {
    children.push(table(
      ['编目编号', '标题', '来源', '威胁类型', '关联目标', 'SLA', '复核状态', '置信度'],
      reportCases.map((item) => [
        item.catalogNumber || ('#' + item.id),
        item.title,
        platformName(item.sourcePlatform),
        labelValue(item.threatType),
        (item.targetName || '待确认') + ' / ' + (item.targetIndustry || '待确认'),
        slaLabel(item.slaStatus),
        verificationLabel(item.verificationStatus),
        confidenceLabel(item.confidenceLevel),
      ]),
    ))
    children.push(heading('案件详情'))
    for (const item of reportCases) {
      const fields = [
        ['来源平台/网址', platformName(item.sourcePlatform) + ' / ' + (item.sourceUrl || '未提供')],
        ['威胁类型', labelValue(item.threatType)],
        ['关联目标', (item.targetName || '待确认') + ' / ' + (item.targetIndustry || '待确认')],
        ['发现时间', formatDateTime(item.discoveredAt) || '-'],
        ['首次入库', formatDateTime(item.firstDetectedAt) || '-'],
        ['截图及合规状态', (item.screenshotUrl || '未上传') + ' / ' + screenshotLabel(item)],
        ['初步置信度', confidenceLabel(item.confidenceLevel)],
        ['建议处置方向', item.suggestedAction || '待补充'],
        ['复核及编目', verificationLabel(item.verificationStatus) + ' / ' + (item.catalogNumber || catalogStatusLabel(item.catalogStatus))],
        ['处置结论', labelValue(item.disposition)],
      ]
      children.push(new Paragraph({
        children: [new TextRun({ text: (item.catalogNumber || ('#' + item.id)) + ' ' + (item.title || '未命名案件'), bold: true })],
        spacing: { before: 180, after: 80 },
      }))
      for (const [label, value] of fields) {
        children.push(new Paragraph({
          children: [new TextRun({ text: label + '：', bold: true }), new TextRun(reportValue(value) || '-')],
          spacing: { after: 40 },
        }))
      }
    }
  } else {
    children.push(new Paragraph('本周期暂无案件。'))
  }

  const doc = new Document({
    sections: [{
      properties: {
        page: {
          size: { orientation: PageOrientation.LANDSCAPE },
          margin: { top: 720, right: 720, bottom: 720, left: 720 },
        },
      },
      children,
    }],
  })
  return Packer.toBlob(doc)
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

async function exportDailyReport() {
  if (!reportDate.value) return
  exportingDaily.value = true
  try {
    const payload = await api.loadDailyReport(reportDate.value)
    const blob = await buildWordReport('daily', reportDate.value, payload)
    downloadBlob(blob, 'darkweb-monitoring-daily-' + reportDate.value + '.docx')
    ElMessage.success('暗网监测日报已导出')
  } catch (error) {
    ElMessage.error(error.message || '导出暗网监测日报失败')
  } finally {
    exportingDaily.value = false
  }
}

async function exportMonthlyReport() {
  if (!reportMonth.value) return
  exportingMonthly.value = true
  try {
    const payload = await api.loadMonthlyReport(reportMonth.value)
    const blob = await buildWordReport('monthly', reportMonth.value, payload)
    downloadBlob(blob, 'darkweb-monitoring-monthly-' + reportMonth.value + '.docx')
    ElMessage.success('暗网监测月报已导出')
  } catch (error) {
    ElMessage.error(error.message || '导出暗网监测月报失败')
  } finally {
    exportingMonthly.value = false
  }
}

watch(
  () => Object.values(filters),
  () => {
    currentPage.value = 1
  },
  { deep: true },
)

watch([filteredCases, pageSize], () => {
  const maxPage = Math.max(1, Math.ceil(filteredCases.value.length / pageSize.value))
  if (currentPage.value > maxPage) currentPage.value = maxPage
})

onMounted(loadOverview)
</script>

<style scoped lang="scss">
.darkweb-monitoring {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
}

.monitoring-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}

.monitoring-header__summary,
.monitoring-header__actions {
  min-width: 0;
}

.monitoring-header__title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
}

.monitoring-header h1,
.section-heading h2,
.report-band h2 {
  margin: 0;
  color: var(--ti-text-primary);
  letter-spacing: 0;
}

.monitoring-header h1 {
  font-size: 28px;
  line-height: 1.25;
}

.service-state,
.platform-status,
.case-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid transparent;
  border-radius: var(--ti-radius-full);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.service-state,
.platform-status {
  padding: 5px 10px;
}

.case-badge {
  padding: 4px 9px;
}

.service-state::before,
.platform-status::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.service-state--active,
.platform-status--success,
.case-badge--success {
  color: var(--ti-success-strong);
  background: var(--ti-success);
  border-color: rgba(40, 122, 79, 0.18);
}

.service-state--inactive,
.platform-status--muted,
.case-badge--muted {
  color: var(--ti-text-muted);
  background: var(--ti-panel-muted);
  border-color: var(--ti-border-default);
}

.platform-status--danger,
.case-badge--danger {
  color: var(--ti-danger-strong);
  background: var(--ti-danger);
  border-color: rgba(207, 68, 50, 0.18);
}

.case-badge--warning {
  color: var(--ti-warning-strong);
  background: var(--ti-warning);
  border-color: rgba(232, 128, 48, 0.18);
}

.case-badge--primary {
  color: var(--ti-primary-strong);
  background: var(--ti-primary-soft);
  border-color: rgba(45, 93, 255, 0.16);
}

.service-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  margin-top: 14px;
  color: var(--ti-text-secondary);
  font-size: 13px;
}

.service-facts b {
  color: var(--ti-text-primary);
  font-family: var(--ti-font-mono);
}

.monitoring-header__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.metrics-grid,
.platform-grid {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.metrics-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric-card {
  position: relative;
  min-height: 146px;
  padding: 18px 20px;
  overflow: hidden;
}

.metric-card::after {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
  background: var(--metric-color);
}

.metric-card--primary { --metric-color: var(--ti-primary); }
.metric-card--warning { --metric-color: var(--ti-warning-strong); }
.metric-card--danger { --metric-color: var(--ti-danger-strong); }
.metric-card--success { --metric-color: var(--ti-success-strong); }

.metric-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--ti-text-secondary);
  font-weight: 700;
}

.metric-card__head .el-icon {
  color: var(--metric-color);
  font-size: 20px;
}

.metric-card strong {
  display: block;
  margin-top: 14px;
  color: var(--ti-text-primary);
  font-size: 34px;
  line-height: 1;
}

.metric-card small {
  display: block;
  margin-top: 10px;
  color: var(--ti-text-muted);
}

.platform-section {
  min-width: 0;
}

.section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.section-heading h2,
.report-band h2 {
  margin-top: 4px;
  font-size: 20px;
}

.section-heading__note {
  color: var(--ti-text-muted);
  font-size: 13px;
}

.platform-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.platform-card {
  padding: 18px;
}

.platform-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.platform-card h3 {
  margin: 0;
  color: var(--ti-text-primary);
  font-size: 16px;
  line-height: 1.3;
}

.platform-card__head > div > span {
  display: block;
  margin-top: 4px;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.platform-card__facts {
  display: grid;
  grid-template-columns: minmax(80px, 0.8fr) minmax(0, 1.5fr);
  gap: 12px;
  margin: 18px 0 0;
}

.platform-card__facts div {
  min-width: 0;
  padding-top: 12px;
  border-top: 1px solid var(--ti-border-soft);
}

.platform-card dt {
  color: var(--ti-text-muted);
  font-size: 11px;
}

.platform-card dd {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
  color: var(--ti-text-primary);
  font-size: 12px;
}

.platform-card dd.ti-number {
  font-size: 20px;
}

.platform-card__hint {
  margin: 14px 0 0;
  padding: 10px 12px;
  border-left: 3px solid var(--ti-warning-strong);
  background: var(--ti-warning);
  color: var(--ti-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.cases-card,
.cases-card .ti-card-body {
  min-width: 0;
  max-width: 100%;
}

.filter-control {
  width: 150px;
}

.case-table-shell {
  margin-top: 18px;
  max-width: 100%;
}

.case-table-shell :deep(.el-table) {
  min-width: 100%;
}

.case-table-shell :deep(.el-table__body-wrapper),
.case-table-shell :deep(.el-scrollbar__wrap) {
  overflow-x: hidden;
}

.case-table-shell :deep(.el-scrollbar__bar.is-horizontal) {
  display: none;
}

.case-table-shell :deep(.el-table .cell) {
  min-width: 0;
  padding: 0 10px;
}

.case-primary-cell,
.case-stacked-cell {
  min-width: 0;
}

.case-primary-cell strong,
.case-stacked-cell strong,
.case-primary-cell span,
.case-stacked-cell span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-primary-cell strong,
.case-stacked-cell strong {
  color: var(--ti-text-primary);
  font-size: 13px;
}

.case-primary-cell span,
.case-stacked-cell span,
.case-cell-note {
  margin-top: 5px;
  color: var(--ti-text-muted);
  font-size: 11px;
}

.case-cell-note {
  display: block;
  line-height: 1.35;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  white-space: nowrap;
}

.mobile-case-list {
  display: none;
}

.table-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 18px;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.report-band {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}

.report-controls {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 12px;
  min-width: 0;
}

.report-control {
  display: flex;
  gap: 8px;
  min-width: 0;
}

.report-control .el-date-editor,
.report-control .el-select {
  width: 170px;
}

.review-drawer {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.review-evidence,
.review-form__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.review-evidence div {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--ti-border-soft);
  background: var(--ti-panel-muted);
}

.review-evidence span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 11px;
}

.review-evidence strong,
.review-evidence .el-link {
  display: inline-flex;
  margin-top: 5px;
  overflow-wrap: anywhere;
  color: var(--ti-text-primary);
  font-size: 13px;
}

.review-excerpt h3 {
  margin: 0;
  color: var(--ti-text-primary);
  font-size: 17px;
}

.review-excerpt p {
  margin: 8px 0 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
  white-space: pre-wrap;
}

.screenshot-preview {
  min-width: 0;
}

.screenshot-preview__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  color: var(--ti-text-secondary);
  font-weight: 700;
}

.screenshot-preview img {
  display: block;
  width: 100%;
  max-height: 360px;
  border: 1px solid var(--ti-border-default);
  object-fit: contain;
  background: var(--ti-panel-muted);
}

.screenshot-preview__fallback {
  display: grid;
  min-height: 120px;
  place-items: center;
  padding: 20px;
  border: 1px dashed var(--ti-border-default);
  background: var(--ti-panel-muted);
  color: var(--ti-text-muted);
  font-size: 13px;
  text-align: center;
}

.review-form {
  padding-top: 18px;
  border-top: 1px solid var(--ti-border-soft);
}

.review-form__grid .el-select,
.review-form__grid .el-input {
  width: 100%;
}

.drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 1280px) {
  .metrics-grid,
  .platform-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .report-band {
    align-items: flex-start;
    flex-direction: column;
  }

  .report-controls {
    justify-content: flex-start;
  }
}

@media (max-width: 767px) {
  .monitoring-header {
    align-items: stretch;
    flex-direction: column;
  }

  .monitoring-header h1 {
    font-size: 24px;
  }

  .monitoring-header__actions {
    justify-content: flex-start;
  }

  .metrics-grid,
  .platform-grid,
  .review-evidence,
  .review-form__grid {
    grid-template-columns: 1fr;
  }

  .filter-control {
    width: 100%;
  }

  .case-table-shell {
    display: none;
  }

  .mobile-case-list {
    display: grid;
    gap: 12px;
    margin-top: 16px;
  }

  .mobile-case-card {
    min-width: 0;
    padding: 14px;
    border: 1px solid var(--ti-border-default);
    background: var(--ti-surface-default);
  }

  .mobile-case-card__head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 10px;
  }

  .mobile-case-card__head > div {
    min-width: 0;
  }

  .mobile-case-card__head strong,
  .mobile-case-card__head span {
    display: block;
    overflow-wrap: anywhere;
  }

  .mobile-case-card__head span:not(.case-badge) {
    margin-top: 4px;
    color: var(--ti-text-muted);
    font-size: 11px;
  }

  .mobile-case-card dl {
    display: grid;
    gap: 8px;
    margin: 14px 0 0;
  }

  .mobile-case-card dl div {
    display: grid;
    grid-template-columns: 72px minmax(0, 1fr);
    gap: 10px;
  }

  .mobile-case-card dt,
  .mobile-case-card dd {
    margin: 0;
    font-size: 12px;
  }

  .mobile-case-card dt {
    color: var(--ti-text-muted);
  }

  .mobile-case-card dd {
    overflow-wrap: anywhere;
    color: var(--ti-text-secondary);
  }

  .mobile-case-card__actions {
    display: flex;
    gap: 8px;
    margin-top: 14px;
  }

  .report-controls,
  .report-control {
    width: 100%;
  }

  .report-control {
    align-items: stretch;
    flex-direction: column;
  }

  .report-control .el-date-editor,
  .report-control .el-select,
  .report-control .el-button {
    width: 100%;
  }

  .table-footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .table-footer :deep(.el-pagination) {
    flex-wrap: wrap;
    max-width: 100%;
  }

  .table-footer :deep(.el-pagination__total),
  .table-footer :deep(.el-pagination__sizes) {
    display: none;
  }
}
</style>
