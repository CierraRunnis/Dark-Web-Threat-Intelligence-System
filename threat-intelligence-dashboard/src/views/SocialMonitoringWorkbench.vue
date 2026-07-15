<template>
  <div class="social-workbench ti-page">
    <header class="page-head">
      <div>
        <div class="eyebrow">SOCIAL THREAT MONITORING</div>
        <h1>社交平台监测</h1>
        <p>面向 X、Facebook、YouTube、Telegram，每 30 分钟更新一次公开威胁线索。</p>
      </div>
      <div class="head-actions">
        <el-button @click="router.push('/social-monitoring/settings')">监测配置</el-button>
        <el-button v-if="isAdmin" @click="router.push('/social-monitoring/users')">用户管理</el-button>
        <el-button type="primary" :loading="loading" @click="refreshAll">刷新</el-button>
      </div>
    </header>

    <section class="schedule-strip">
      <div>
        <span>上次监测更新</span>
        <strong>{{ formatDateTime(summary.lastUpdatedAt) }}</strong>
      </div>
      <div>
        <span>下次监测更新</span>
        <strong>{{ formatDateTime(summary.nextRunAt) }}</strong>
      </div>
      <div class="countdown">
        <span>距离下一轮</span>
        <strong>{{ nextRunCountdown }}</strong>
      </div>
      <el-tag effect="plain">固定周期 30 分钟</el-tag>
    </section>

    <section class="metric-grid">
      <article class="metric-card">
        <span>本轮新增</span>
        <strong>{{ number(summary.currentRunNewCount) }}</strong>
        <small>新进入初验队列</small>
      </article>
      <article class="metric-card">
        <span>待初验</span>
        <strong>{{ number(summary.pendingVerificationCount) }}</strong>
        <small>待领取或初验中</small>
      </article>
      <article class="metric-card metric-card--danger">
        <span>重大 / 紧急事件</span>
        <strong>{{ number(summary.majorEventCount) }}</strong>
        <small>需重点跟进</small>
      </article>
      <article class="metric-card metric-card--wide">
        <span>平台运行状态</span>
        <div class="platform-list">
          <div v-for="item in platformRows" :key="item.platform" class="platform-item">
            <span class="platform-dot" :class="`platform-dot--${platformTone(item)}`"></span>
            <strong>{{ platformLabel(item.platform) }}</strong>
            <small>{{ platformStatusLabel(item) }}</small>
          </div>
        </div>
      </article>
    </section>

    <section class="content-card">
      <div class="card-head">
        <div>
          <h2>威胁初验队列</h2>
          <p>系统命中后需由分析员领取、核验并完成合规证据处理。</p>
        </div>
        <span>共 {{ total }} 条</span>
      </div>

      <div class="filters">
        <el-select v-model="filters.platform" clearable placeholder="来源平台">
          <el-option v-for="item in platformOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="filters.verificationStatus" clearable placeholder="初验状态">
          <el-option label="待领取" value="pending" />
          <el-option label="初验中" value="inProgress" />
          <el-option label="初验完成" value="verified" />
          <el-option label="已发布" value="published" />
          <el-option label="已关闭" value="closed" />
        </el-select>
        <el-select v-model="filters.severity" clearable placeholder="事件等级">
          <el-option label="紧急" value="emergency" />
          <el-option label="重大" value="major" />
          <el-option label="一般" value="normal" />
        </el-select>
        <el-input v-model="filters.keyword" clearable placeholder="标题、目标、关键词" @keyup.enter="applyFilters">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button @click="resetFilters">重置</el-button>
        <el-button type="primary" @click="applyFilters">查询</el-button>
      </div>

      <el-table v-loading="loading" :data="events" table-layout="fixed" style="width: 100%">
        <el-table-column label="威胁标题" min-width="240" show-overflow-tooltip>
          <template #default="{ row }"><strong>{{ row.threatTitle || row.title || '未命名威胁' }}</strong></template>
        </el-table-column>
        <el-table-column label="来源平台" width="110">
          <template #default="{ row }">{{ platformLabel(row.platform) }}</template>
        </el-table-column>
        <el-table-column label="威胁类型" width="130">
          <template #default="{ row }">{{ threatTypeLabel(row.threatType) }}</template>
        </el-table-column>
        <el-table-column label="关联目标" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ targetLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="发现时间" width="165">
          <template #default="{ row }">{{ formatDateTime(row.discoveredAt) }}</template>
        </el-table-column>
        <el-table-column label="等级" width="90">
          <template #default="{ row }"><el-tag :type="severityTone(row.severity)">{{ severityLabel(row.severity) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="初验状态" width="120">
          <template #default="{ row }">{{ verificationLabel(row.verificationStatus || row.status) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="canClaim(row)"
              type="primary"
              link
              :loading="claimingId === row.id"
              @click="claim(row)"
            >
              领取
            </el-button>
            <el-button type="primary" link @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          background
        />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { listFromResponse, useSocialMonitoringApi } from '@/composables/useSocialMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const api = useSocialMonitoringApi()
const router = useRouter()
const { state } = useAuth()
const loading = ref(false)
const claimingId = ref('')
const events = ref([])
const platformRows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const now = ref(Date.now())
const summary = reactive({
  lastUpdatedAt: '',
  nextRunAt: '',
  currentRunNewCount: 0,
  pendingVerificationCount: 0,
  majorEventCount: 0,
})
const filters = reactive({ platform: '', verificationStatus: '', severity: '', keyword: '' })
let refreshTimer = null
let clockTimer = null

const platformOptions = [
  { label: 'X', value: 'x' },
  { label: 'Facebook', value: 'facebook' },
  { label: 'YouTube', value: 'youtube' },
  { label: 'Telegram', value: 'telegram' },
]

const isAdmin = computed(() => String(state.user?.role || '').toLowerCase() === 'admin')
const nextRunCountdown = computed(() => {
  if (!summary.nextRunAt) return '--:--'
  const remaining = Math.max(0, new Date(summary.nextRunAt).getTime() - now.value)
  if (!Number.isFinite(remaining)) return '--:--'
  const minutes = Math.floor(remaining / 60000)
  const seconds = Math.floor((remaining % 60000) / 1000)
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
})

watch([page, pageSize], loadEvents)

onMounted(async () => {
  await refreshAll()
  refreshTimer = window.setInterval(refreshAll, 15000)
  clockTimer = window.setInterval(() => { now.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  if (clockTimer) window.clearInterval(clockTimer)
})

async function refreshAll() {
  if (loading.value) return
  loading.value = true
  try {
    const [summaryPayload, platformPayload, eventPayload, scanPayload] = await Promise.all([
      api.loadSummary(),
      api.loadPlatforms(),
      api.loadEvents({ ...filters, page: page.value, pageSize: pageSize.value }),
      api.loadScans({ limit: 20 }),
    ])
    const scanRows = listFromResponse(scanPayload, ['scans'])
    const latestSchedule = scanRows[0]?.scheduledAt
    const currentRunNewCount = scanRows
      .filter((item) => !latestSchedule || item.scheduledAt === latestSchedule)
      .reduce((totalCount, item) => totalCount + Number(item.newEventCount || 0), 0)
    Object.assign(summary, summaryPayload || {}, {
      nextRunAt: summaryPayload?.nextRunAt || summaryPayload?.nextUpdatedAt,
      pendingVerificationCount: summaryPayload?.pendingVerificationCount ?? summaryPayload?.pendingCount ?? 0,
      majorEventCount: summaryPayload?.majorEventCount ?? summaryPayload?.majorCount ?? 0,
      currentRunNewCount: summaryPayload?.currentRunNewCount ?? currentRunNewCount,
    })
    platformRows.value = listFromResponse(platformPayload, ['platforms'])
    setEvents(eventPayload)
  } catch (error) {
    ElMessage.error(error.message || '加载社交平台监测数据失败')
  } finally {
    loading.value = false
  }
}

async function loadEvents() {
  try {
    setEvents(await api.loadEvents({ ...filters, page: page.value, pageSize: pageSize.value }))
  } catch (error) {
    ElMessage.error(error.message || '加载威胁事件失败')
  }
}

function setEvents(payload) {
  const keyword = filters.keyword.trim().toLowerCase()
  const rows = listFromResponse(payload, ['events']).filter((row) => {
    if (filters.severity && row.severity !== filters.severity) return false
    if (!keyword) return true
    return [row.title, row.threatTitle, row.targetUnit, row.targetIndustry, ...(row.matchedTerms || [])]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  })
  total.value = rows.length
  const start = (page.value - 1) * pageSize.value
  events.value = rows.slice(start, start + pageSize.value)
}

function applyFilters() {
  if (page.value === 1) loadEvents()
  else page.value = 1
}

function resetFilters() {
  Object.assign(filters, { platform: '', verificationStatus: '', severity: '', keyword: '' })
  applyFilters()
}

async function claim(row) {
  claimingId.value = row.id
  try {
    await api.claimEvent(row.id)
    ElMessage.success('事件已领取')
    router.push(`/social-monitoring/events/${row.id}`)
  } catch (error) {
    ElMessage.error(error.message || '领取失败，事件可能已被其他分析员领取')
    await loadEvents()
  } finally {
    claimingId.value = ''
  }
}

function openDetail(row) {
  router.push(`/social-monitoring/events/${row.id}`)
}

function canClaim(row) {
  return ['pending', 'unclaimed', '待领取'].includes(row.verificationStatus || row.status)
}

function formatDateTime(value) {
  return formatShanghaiDateTime(value, { includeSeconds: true }) || '-'
}

function number(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function platformLabel(value) {
  return platformOptions.find((item) => item.value === String(value || '').toLowerCase())?.label || value || '-'
}

function platformTone(item) {
  const value = String(item.status || item.healthStatus || '').toLowerCase()
  if (['healthy', 'success', 'ok', 'completed', 'configured'].includes(value)) return 'success'
  if (['running', 'queued'].includes(value)) return 'running'
  if (['limited', 'degraded', 'coverageLimited', 'missing_credentials'].includes(value)) return 'warning'
  return 'danger'
}

function platformStatusLabel(item) {
  const labels = {
    healthy: '正常', success: '正常', ok: '正常', completed: '已完成',
    running: '监测中', queued: '待执行', limited: '覆盖受限', degraded: '覆盖受限',
    failed: '采集异常', error: '采集异常', missingCredentials: '缺少凭据', missing_credentials: '缺少凭据',
  }
  return labels[item.status || item.healthStatus] || item.statusLabel || '待配置'
}

function threatTypeLabel(value) {
  const labels = { attackThreat: '扬言攻击', dataSale: '数据售卖', dataLeak: '数据泄露', credentialSale: '凭证售卖', targetedAttack: '定向攻击' }
  return labels[value] || value || '-'
}

function targetLabel(row) {
  return [row.targetUnit, row.targetIndustry].filter(Boolean).join(' / ') || '-'
}

function severityLabel(value) {
  return { emergency: '紧急', critical: '紧急', major: '重大', high: '重大', normal: '一般', medium: '一般', low: '一般' }[value] || value || '一般'
}

function severityTone(value) {
  if (['emergency', 'critical'].includes(value)) return 'danger'
  if (['major', 'high'].includes(value)) return 'warning'
  return 'info'
}

function verificationLabel(value) {
  return { pending: '待领取', unclaimed: '待领取', verifying: '初验中', inProgress: '初验中', claimed: '初验中', verified: '初验完成', published: '已发布', closed: '已关闭' }[value] || value || '-'
}
</script>

<style lang="scss" scoped>
.social-workbench { display: grid; gap: 20px; }
.page-head, .schedule-strip, .content-card, .metric-card { border: 1px solid var(--ti-border-soft); background: #fff; box-shadow: var(--ti-shadow-sm); }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 24px 26px; border-radius: 22px; }
.page-head h1 { margin: 5px 0 8px; color: var(--ti-text-primary); font-size: 28px; }
.page-head p, .card-head p { margin: 0; color: var(--ti-text-secondary); line-height: 1.6; }
.eyebrow { color: var(--ti-primary); font-size: 12px; font-weight: 800; letter-spacing: .12em; }
.head-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.schedule-strip { display: flex; align-items: center; gap: 34px; padding: 17px 22px; border-radius: 18px; }
.schedule-strip > div { display: grid; gap: 4px; }
.schedule-strip span, .metric-card > span { color: var(--ti-text-secondary); font-size: 13px; }
.schedule-strip strong { color: var(--ti-text-primary); font-size: 15px; }
.schedule-strip .countdown strong { color: var(--ti-primary); font-size: 21px; font-variant-numeric: tabular-nums; }
.schedule-strip .el-tag { margin-left: auto; }
.metric-grid { display: grid; grid-template-columns: repeat(3, minmax(150px, .7fr)) minmax(360px, 1.8fr); gap: 16px; }
.metric-card { min-height: 142px; padding: 20px; border-radius: 20px; }
.metric-card > strong { display: block; margin: 12px 0 7px; color: var(--ti-primary); font-size: 34px; }
.metric-card--danger > strong { color: var(--ti-danger-strong); }
.metric-card small { color: var(--ti-text-muted); }
.platform-list { display: grid; grid-template-columns: repeat(2, minmax(130px, 1fr)); gap: 14px; margin-top: 14px; }
.platform-item { display: grid; grid-template-columns: 9px auto 1fr; align-items: center; gap: 8px; }
.platform-item small { justify-self: end; }
.platform-dot { width: 9px; height: 9px; border-radius: 50%; background: #adb5c4; }
.platform-dot--success { background: #23b481; box-shadow: 0 0 0 4px rgba(35,180,129,.12); }
.platform-dot--running { background: #409eff; }
.platform-dot--warning { background: #e6a23c; }
.platform-dot--danger { background: #f56c6c; }
.content-card { padding: 22px; border-radius: 22px; }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.card-head h2 { margin: 0 0 6px; font-size: 19px; }
.card-head > span { color: var(--ti-text-secondary); }
.filters { display: grid; grid-template-columns: 150px 150px 140px minmax(220px, 1fr) auto auto; gap: 10px; margin-bottom: 16px; }
.pagination { display: flex; justify-content: flex-end; margin-top: 18px; }
@media (max-width: 1200px) { .metric-grid { grid-template-columns: repeat(3, 1fr); } .metric-card--wide { grid-column: 1 / -1; } .filters { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 767px) { .page-head, .schedule-strip { align-items: stretch; flex-direction: column; } .schedule-strip .el-tag { margin-left: 0; align-self: flex-start; } .metric-grid { grid-template-columns: 1fr; } .metric-card--wide { grid-column: auto; } .filters { grid-template-columns: 1fr; } }
</style>
