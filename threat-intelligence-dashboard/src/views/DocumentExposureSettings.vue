<template>
  <div class="document-exposure-settings ti-page">
    <section class="settings-header ti-reveal-up">
      <div>
        <div class="settings-header__eyebrow">{{ currentModule.eyebrow }}</div>
        <h2>{{ currentModule.title }}</h2>
        <p>{{ currentModule.subtitle }}</p>
      </div>
      <div class="module-tabs">
        <el-button
          v-for="item in moduleTabs"
          :key="item.sourceFamily"
          :type="item.sourceFamily === currentSourceFamily ? 'primary' : ''"
          plain
          @click="router.push(item.settingsRoute)"
        >
          {{ item.label }}
        </el-button>
      </div>
    </section>

    <section class="content-grid">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div>
            <div class="ti-card-title">{{ currentModule.sourceTitle }}</div>
            <div class="ti-card-subtitle">{{ modulePlatformRows.length }} 个来源，当前配置只作用于{{ currentModule.label }}</div>
          </div>
          <div class="health-actions">
            <el-button plain :loading="loadingPlatforms" @click="loadPlatforms">刷新来源</el-button>
          </div>
        </div>
        <div class="ti-card-body">
          <div class="source-overview">
            <span v-for="item in sourceTypeSummary" :key="item.label" class="source-overview__item">
              <strong>{{ item.value }}</strong>
              {{ item.label }}
            </span>
          </div>
          <div class="ti-table-shell">
            <el-table :data="pagedModulePlatformRows" table-layout="auto" style="width: 100%">
              <el-table-column prop="label" label="信息源" min-width="170" />
              <el-table-column label="类型" min-width="140">
                <template #default="{ row }">
                  <el-tag effect="plain">{{ platformTypeLabel(row.platform_type) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="接入方式" min-width="140">
                <template #default="{ row }">
                  {{ platformAccessMode(row) }}
                </template>
              </el-table-column>
              <el-table-column label="域名 / 地址" min-width="240" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ sourceAddress(row) }}
                </template>
              </el-table-column>
              <el-table-column label="默认策略" width="120">
                <template #default="{ row }">
                  <el-tag :type="sourcePolicyTagType(row)" effect="light">
                    {{ sourcePolicyLabel(row) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="130">
                <template #default="{ row }">
                  <el-tag :type="sourceStateTagType(row)" effect="light">
                    {{ sourceStateLabel(row) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="主页" width="110">
                <template #default="{ row }">
                  <el-link v-if="row.homepage_url" :href="row.homepage_url" target="_blank" type="primary">打开</el-link>
                  <span v-else>-</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div v-if="modulePlatformRows.length > sourcePageSize" class="source-pagination">
            <el-pagination
              v-model:current-page="sourcePage"
              :page-size="sourcePageSize"
              :total="modulePlatformRows.length"
              layout="total, prev, pager, next"
              background
            />
          </div>
        </div>
      </div>

      <div v-if="currentSourceFamily === 'netdisk_aggregator'" class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div>
            <div class="ti-card-title">来源健康 / 分页游标</div>
            <div class="ti-card-subtitle">{{ netdiskCursorRows.length }} 项，只读展示网盘来源健康和下一轮建议页码</div>
          </div>
          <div class="health-actions">
            <el-button plain :loading="loadingNetdiskCursor" @click="loadNetdiskCursor">刷新状态</el-button>
          </div>
        </div>
        <div class="ti-card-body">
          <div class="ti-table-shell">
            <el-table :data="netdiskCursorRows" table-layout="fixed" style="width: 100%" size="small">
              <el-table-column label="来源" min-width="130" show-overflow-tooltip>
                <template #default="{ row }">
                  <span>{{ row.sourceLabel || row.sourceKey || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="关键词" min-width="150" show-overflow-tooltip>
                <template #default="{ row }">
                  <span>{{ row.term || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="建议页码" min-width="130">
                <template #default="{ row }">
                  <span class="cursor-pages">{{ formatSuggestedPages(row) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" min-width="110">
                <template #default="{ row }">
                  <span :class="['state-status', `state-status--${row.healthStatus || 'healthy'}`]">
                    {{ healthStatusLabel(row.healthStatus) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="空页/重复页" min-width="110">
                <template #default="{ row }">
                  <span>{{ formatCursorCounters(row) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="更新时间" min-width="170">
                <template #default="{ row }">
                  <span>{{ formatDateTime(row.updatedAt || row.healthUpdatedAt) || '-' }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>

      <div v-if="moduleSessions.length" class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">{{ currentModule.sessionTitle }}</div>
          <div class="health-actions">
            <el-button plain :loading="loadingSessions" @click="loadSessions">刷新会话</el-button>
          </div>
        </div>
        <div class="ti-card-body">
          <div class="ti-table-shell">
            <el-table :data="moduleSessions" table-layout="auto" style="width: 100%">
              <el-table-column prop="label" label="平台" min-width="180" />
              <el-table-column label="状态" width="140">
                <template #default="{ row }">
                  {{ statusLabelMap[row.status] || row.status || 'unknown' }}
                </template>
              </el-table-column>
              <el-table-column prop="account_label" label="账号标签" min-width="180">
                <template #default="{ row }">
                  <el-input v-model="sessionDrafts[row.platform]" placeholder="账号标签" size="small" />
                </template>
              </el-table-column>
              <el-table-column prop="last_verified_at" label="最近校验" min-width="180">
                <template #default="{ row }">
                  {{ formatDateTime(row.last_verified_at) || '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="last_error" label="最近错误" min-width="240" show-overflow-tooltip />
              <el-table-column label="操作" min-width="320" fixed="right">
                <template #default="{ row }">
                  <div class="table-actions">
                    <el-button
                      size="small"
                      :disabled="row.status === 'login_in_progress' || Boolean(loginStarting[row.platform])"
                      :loading="Boolean(loginStarting[row.platform])"
                      @click="launchLogin(row.platform)"
                    >
                      {{ row.status === 'login_in_progress' ? '登录中' : '启动登录' }}
                    </el-button>
                    <el-button size="small" type="primary" @click="saveSession(row.platform)">保存会话</el-button>
                    <el-button size="small" plain @click="verifySession(row.platform)">校验</el-button>
                    <el-button size="small" type="danger" plain @click="removeSession(row.platform)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div>
            <div class="ti-card-title">{{ currentModule.watchlistTitle }}</div>
            <div class="ti-card-subtitle">只显示并保存{{ currentModule.label }}的监测对象</div>
          </div>
          <div class="health-actions">
            <el-button plain :loading="loadingWatchlists" @click="loadWatchlists">刷新对象</el-button>
            <el-button plain @click="createWatchlist">新建对象</el-button>
            <el-button type="primary" :loading="savingWatchlist" @click="saveWatchlist">保存配置</el-button>
          </div>
        </div>
        <div class="ti-card-body">
          <div class="watchlist-toolbar">
            <div class="watchlist-toolbar__item">
              <span>监测对象</span>
              <el-select v-model="selectedWatchlistId" placeholder="选择监测对象" @change="selectWatchlist">
                <el-option
                  v-for="item in moduleWatchlists"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </div>
            <div class="watchlist-toolbar__item">
              <span>所属模块</span>
              <div class="module-family">
                <el-tag type="primary" effect="plain">{{ currentModule.sourceLabel }}</el-tag>
              </div>
            </div>
            <div class="watchlist-toolbar__item watchlist-toolbar__item--switch">
              <span>启停状态</span>
              <el-switch
                v-model="watchlistForm.enabled"
                active-text="启用"
                inactive-text="停用"
              />
            </div>
          </div>

          <div class="watchlist-form">
            <el-input v-model="watchlistForm.name" placeholder="监测对象名称" />
            <el-input v-model="watchlistForm.organization_name" placeholder="企业名称" />
            <el-input v-model="watchlistForm.notes" placeholder="备注" />
          </div>

          <div class="watchlist-options">
            <div class="watchlist-option">
              <span>文件类型</span>
              <el-select v-model="watchlistForm.file_types" multiple collapse-tags placeholder="选择文件类型">
                <el-option v-for="item in fileTypeOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </div>
            <div v-if="currentSourceFamily !== 'netdisk_aggregator'" class="watchlist-option">
              <span>单源候选上限</span>
              <el-input-number v-model="watchlistForm.page_limit" :min="1" :max="20" />
            </div>
            <div class="watchlist-option watchlist-option--switch">
              <span>详情抓取</span>
              <el-switch v-model="watchlistForm.detail_fetch" active-text="启用" inactive-text="关闭" />
            </div>
          </div>

          <div class="watchlist-terms">
            <div class="watchlist-terms__header">
              <strong>监测词</strong>
              <el-button plain size="small" @click="addTerm">新增监测词</el-button>
            </div>
            <div v-for="(term, index) in watchlistForm.terms" :key="`${term.term_type}-${index}`" class="watchlist-term-row">
              <el-input v-model="term.term" placeholder="监测词" />
              <el-select v-model="term.term_type" placeholder="类型" style="width: 160px">
                <el-option label="企业名" value="company_name" />
                <el-option label="域名" value="domain" />
                <el-option label="产品" value="product" />
                <el-option label="项目" value="project" />
                <el-option label="关键词" value="keyword" />
                <el-option label="敏感词" value="sensitive_keyword" />
              </el-select>
              <el-input-number v-if="currentSourceFamily !== 'netdisk_aggregator'" v-model="term.weight" :min="1" :max="30" />
              <el-switch v-model="term.enabled" />
              <el-button type="danger" plain size="small" @click="removeTerm(index)">删除</el-button>
            </div>
            <el-empty v-if="!watchlistForm.terms.length" description="暂无监测词" />
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useDocumentExposureApi } from '@/composables/useDocumentExposureApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const api = useDocumentExposureApi()
const route = useRoute()
const router = useRouter()

const MODULE_CONFIG = {
  search_engine: {
    sourceFamily: 'search_engine',
    label: '搜索引擎监测',
    title: '搜索引擎监测配置',
    eyebrow: 'Search Engine',
    subtitle: '配置搜索引擎监测对象、关键词、文件类型和搜索来源。',
    sourceLabel: '搜索引擎',
    sourceTitle: '搜索引擎信息源',
    sessionTitle: '搜索平台会话',
    watchlistTitle: '搜索引擎监测对象与关键词',
    settingsRoute: '/document-exposure/search-engine/settings',
    platformTypes: ['search_engine'],
  },
  netdisk_aggregator: {
    sourceFamily: 'netdisk_aggregator',
    label: '网盘监测',
    title: '网盘监测配置',
    eyebrow: 'Netdisk',
    subtitle: '配置网盘监测对象、关键词、文件类型和网盘聚合信息源。',
    sourceLabel: '网盘聚合',
    sourceTitle: '网盘信息源',
    sessionTitle: '网盘平台会话',
    watchlistTitle: '网盘监测对象与关键词',
    settingsRoute: '/document-exposure/netdisk/settings',
    platformTypes: ['netdisk_search', 'netdisk_share'],
  },
  document_library: {
    sourceFamily: 'document_library',
    label: '文库监测',
    title: '文库监测配置',
    eyebrow: 'Document Library',
    subtitle: '配置文库监测对象、关键词、文件类型和文库平台来源。',
    sourceLabel: '文库平台',
    sourceTitle: '文库信息源',
    sessionTitle: '文库平台会话',
    watchlistTitle: '文库监测对象与关键词',
    settingsRoute: '/document-exposure/document-library/settings',
    platformTypes: ['document_library'],
  },
}

const moduleTabs = Object.values(MODULE_CONFIG)
const loadingPlatforms = ref(false)
const loadingSessions = ref(false)
const loadingWatchlists = ref(false)
const loadingNetdiskCursor = ref(false)
const savingWatchlist = ref(false)
const allPlatforms = ref([])
const platformSessions = ref([])
const watchlists = ref([])
const netdiskSourceStates = ref([])
const netdiskSourceHealth = ref([])
const selectedWatchlistId = ref(null)
const sourcePage = ref(1)
const sourcePageSize = 10
const sessionDrafts = reactive({})
const loginStarting = reactive({})
const fileTypeOptions = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'zip', 'rar', '7z', 'txt', 'csv']

const statusLabelMap = {
  configured: '已配置',
  valid: '有效',
  invalid: '失效',
  missing: '缺失',
  unavailable: '不可用',
  login_in_progress: '登录中',
  not_configured: '未配置',
}

const watchlistForm = reactive({
  id: null,
  name: '',
  organization_name: '',
  notes: '',
  enabled: true,
  source_families: [],
  file_types: [],
  page_limit: 4,
  detail_fetch: true,
  terms: [],
})

const currentSourceFamily = computed(() => (
  route.meta.sourceFamily || route.query.source_family || 'search_engine'
))
const currentModule = computed(() => MODULE_CONFIG[currentSourceFamily.value] || MODULE_CONFIG.search_engine)
const modulePlatformRows = computed(() => allPlatforms.value
  .filter((item) => currentModule.value.platformTypes.includes(item.platform_type))
  .sort(comparePlatformRows))
const pagedModulePlatformRows = computed(() => {
  const start = (sourcePage.value - 1) * sourcePageSize
  return modulePlatformRows.value.slice(start, start + sourcePageSize)
})
const moduleSessions = computed(() => platformSessions.value.filter((item) => (
  currentModule.value.platformTypes.includes(item.platform_type)
)))
const moduleWatchlists = computed(() => watchlists.value.filter((item) => {
  const families = Array.isArray(item.source_families) ? item.source_families : []
  return families.length === 1 && families[0] === currentSourceFamily.value
}))
const sourceTypeSummary = computed(() => {
  const rows = modulePlatformRows.value
  const groups = new Map()
  for (const item of rows) {
    const label = platformTypeLabel(item.platform_type)
    groups.set(label, (groups.get(label) || 0) + 1)
  }
  return [...groups.entries()].map(([label, value]) => ({ label, value }))
})
const netdiskHealthBySource = computed(() => {
  const rows = new Map()
  for (const item of netdiskSourceHealth.value || []) {
    rows.set(item.sourceKey, item)
  }
  return rows
})
const netdiskCursorRows = computed(() => {
  if (currentSourceFamily.value !== 'netdisk_aggregator') return []
  const states = Array.isArray(netdiskSourceStates.value) ? netdiskSourceStates.value : []
  if (states.length) {
    return states.map((row) => {
      const health = netdiskHealthBySource.value.get(row.sourceKey) || {}
      return {
        ...row,
        healthStatus: health.status || 'healthy',
        healthUpdatedAt: health.updatedAt || '',
      }
    })
  }
  return (netdiskSourceHealth.value || []).map((row) => ({
    sourceKey: row.sourceKey,
    sourceLabel: row.sourceLabel,
    term: '',
    suggestedPages: [1],
    consecutiveEmptyPages: 0,
    consecutiveRepeatedPages: 0,
    healthStatus: row.status || 'healthy',
    healthUpdatedAt: row.updatedAt || '',
  }))
})

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

function comparePlatformRows(left, right) {
  if (currentSourceFamily.value !== 'netdisk_aggregator') return 0
  return platformSortRank(left) - platformSortRank(right)
}

function platformSortRank(row) {
  if (row.platform_type === 'netdisk_search') return Number(row.scan_priority || 999)
  if (row.platform_type === 'netdisk_share') return 500
  return 999
}

function platformTypeLabel(type) {
  return {
    search_engine: '搜索引擎',
    netdisk_search: '网盘聚合源',
    netdisk_share: '网盘分享平台',
    document_library: '文库平台',
  }[type] || type || '-'
}

function platformAccessMode(row) {
  if (row.platform === 'pansou') return '本地 API'
  if (row.platform === 'panhub') return '外部 API'
  if (row.discovery_only) return '公开检索'
  if (row.platform_type === 'netdisk_share') return '链接识别'
  return row.requires_login ? '登录会话' : '公开检索'
}

function sourceAddress(row) {
  if (Array.isArray(row.domains) && row.domains.length) {
    return row.domains.join(', ')
  }
  return row.homepage_url || '-'
}

function sourceStateLabel(row) {
  if (row.scan_tier === 'primary') return '默认启用'
  if (row.scan_tier === 'optional') return row.scan_enabled ? '默认启用' : '需配置'
  if (row.scan_tier === 'fallback') return row.scan_enabled ? '备用启用' : '备用关闭'
  if (row.discovery_only) return '已接入'
  if (row.requires_login) return '需会话'
  return '已接入'
}

function sourceStateTagType(row) {
  if (row.scan_tier === 'primary') return 'success'
  if (row.scan_tier === 'optional') return row.scan_enabled ? 'success' : 'warning'
  if (row.scan_tier === 'fallback') return row.scan_enabled ? 'warning' : 'info'
  if (row.discovery_only) return 'success'
  return row.requires_login ? 'warning' : 'info'
}

function sourcePolicyLabel(row) {
  if (row.scan_tier === 'primary') return `优先 ${row.scan_priority || ''}`.trim()
  if (row.scan_tier === 'optional') return '可选 API'
  if (row.scan_tier === 'fallback') return '备用'
  if (row.platform_type === 'netdisk_share') return '链接识别'
  return '默认'
}

function sourcePolicyTagType(row) {
  if (row.scan_tier === 'primary') return 'success'
  if (row.scan_tier === 'optional') return row.scan_enabled ? 'success' : 'warning'
  if (row.scan_tier === 'fallback') return 'info'
  return row.requires_login ? 'warning' : 'info'
}

function formatSuggestedPages(row) {
  const pages = Array.isArray(row?.suggestedPages) ? row.suggestedPages : []
  return pages.length ? pages.join('、') : '-'
}

function healthStatusLabel(status) {
  return {
    healthy: '健康',
    error: '异常',
    login_required: '需登录',
    captcha: '验证码',
    rate_limited: '限流',
  }[status] || status || '健康'
}

function formatCursorCounters(row) {
  return `${Number(row?.consecutiveEmptyPages || 0)} / ${Number(row?.consecutiveRepeatedPages || 0)}`
}

function defaultDetailFetch() {
  return currentSourceFamily.value === 'document_library'
}

function emptyWatchlist() {
  return {
    id: null,
    name: '',
    organization_name: '',
    notes: '',
    enabled: true,
    source_families: [currentSourceFamily.value],
    file_types: [],
    page_limit: 4,
    detail_fetch: defaultDetailFetch(),
    terms: [],
  }
}

function applyWatchlist(payload) {
  const next = payload || emptyWatchlist()
  selectedWatchlistId.value = next.id ?? null
  watchlistForm.id = next.id ?? null
  watchlistForm.name = next.name || ''
  watchlistForm.organization_name = next.organization_name || ''
  watchlistForm.notes = next.notes || ''
  watchlistForm.enabled = next.enabled ?? true
  watchlistForm.source_families = [currentSourceFamily.value]
  watchlistForm.file_types = Array.isArray(next.file_types) ? [...next.file_types] : []
  watchlistForm.page_limit = Number(next.page_limit || 4)
  watchlistForm.detail_fetch = Boolean(next.detail_fetch ?? defaultDetailFetch())
  watchlistForm.terms = Array.isArray(next.terms) ? next.terms.map((item) => ({ ...item })) : []
}

function selectFirstModuleWatchlist(preferredId = null) {
  const rows = moduleWatchlists.value
  const target = rows.find((item) => item.id === preferredId) || rows[0] || null
  applyWatchlist(target)
}

function createWatchlist() {
  applyWatchlist(emptyWatchlist())
}

function selectWatchlist(watchlistId) {
  const target = moduleWatchlists.value.find((item) => item.id === watchlistId)
  applyWatchlist(target || null)
}

function addTerm() {
  watchlistForm.terms.push({ term: '', term_type: 'company_name', weight: 10, enabled: true })
}

function removeTerm(index) {
  watchlistForm.terms.splice(index, 1)
}

async function loadPlatforms() {
  loadingPlatforms.value = true
  try {
    allPlatforms.value = await api.loadPlatforms()
    sourcePage.value = 1
  } catch (error) {
    ElMessage.error(error.message || '加载信息源失败')
  } finally {
    loadingPlatforms.value = false
  }
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    platformSessions.value = await api.loadSessions()
    for (const item of platformSessions.value) {
      sessionDrafts[item.platform] = item.account_label || ''
    }
  } catch (error) {
    ElMessage.error(error.message || '加载平台会话失败')
  } finally {
    loadingSessions.value = false
  }
}

async function loadWatchlists() {
  loadingWatchlists.value = true
  try {
    watchlists.value = await api.loadWatchlists()
    selectFirstModuleWatchlist(selectedWatchlistId.value)
  } catch (error) {
    ElMessage.error(error.message || '加载监测对象失败')
  } finally {
    loadingWatchlists.value = false
  }
}

async function loadNetdiskCursor() {
  if (currentSourceFamily.value !== 'netdisk_aggregator') {
    netdiskSourceStates.value = []
    netdiskSourceHealth.value = []
    return
  }
  loadingNetdiskCursor.value = true
  try {
    const [statePayload, healthPayload] = await Promise.all([
      api.loadNetdiskSourceStates(),
      api.loadNetdiskSourceHealth(),
    ])
    netdiskSourceStates.value = Array.isArray(statePayload) ? statePayload : []
    netdiskSourceHealth.value = Array.isArray(healthPayload) ? healthPayload : []
  } catch (error) {
    ElMessage.error(error.message || '加载网盘来源状态失败')
  } finally {
    loadingNetdiskCursor.value = false
  }
}

async function saveWatchlist() {
  if (!watchlistForm.name.trim()) {
    ElMessage.error('请输入监测对象名称')
    return
  }
  if (!watchlistForm.organization_name.trim()) {
    ElMessage.error('请输入企业名称')
    return
  }
  savingWatchlist.value = true
  try {
    const terms = watchlistForm.terms.map((term) => ({
      ...term,
      weight: currentSourceFamily.value === 'netdisk_aggregator' ? 10 : Number(term.weight || 10),
    }))
    const payload = await api.saveWatchlist({
      ...watchlistForm,
      terms,
      source_families: [currentSourceFamily.value],
    })
    await loadWatchlists()
    applyWatchlist(payload)
    ElMessage.success('监测配置已保存')
  } catch (error) {
    ElMessage.error(error.message || '保存监测配置失败')
  } finally {
    savingWatchlist.value = false
  }
}

async function launchLogin(platform) {
  if (loginStarting[platform]) return
  loginStarting[platform] = true
  try {
    const payload = await api.launchLogin(platform)
    await loadSessions()
    ElMessage.success(payload?.message || '已启动登录会话')
  } catch (error) {
    ElMessage.error(error.message || '启动登录失败')
  } finally {
    loginStarting[platform] = false
  }
}

async function saveSession(platform) {
  try {
    await api.saveSession(platform, sessionDrafts[platform] || '')
    await loadSessions()
    ElMessage.success('会话已保存')
  } catch (error) {
    ElMessage.error(error.message || '保存会话失败')
  }
}

async function verifySession(platform) {
  try {
    await api.verifySession(platform)
    await loadSessions()
    ElMessage.success('会话状态已刷新')
  } catch (error) {
    ElMessage.error(error.message || '校验会话失败')
  }
}

async function removeSession(platform) {
  try {
    await api.deleteSession(platform)
    await loadSessions()
    ElMessage.success('会话已删除')
  } catch (error) {
    ElMessage.error(error.message || '删除会话失败')
  }
}

watch(currentSourceFamily, () => {
  sourcePage.value = 1
  selectFirstModuleWatchlist(null)
  loadNetdiskCursor()
})

watch(() => modulePlatformRows.value.length, (total) => {
  const maxPage = Math.max(1, Math.ceil(total / sourcePageSize))
  if (sourcePage.value > maxPage) {
    sourcePage.value = maxPage
  }
})

onMounted(async () => {
  await Promise.all([loadPlatforms(), loadSessions(), loadWatchlists(), loadNetdiskCursor()])
})
</script>

<style scoped lang="scss">
.settings-header {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  margin-bottom: 22px;
}

.settings-header__eyebrow {
  color: var(--ti-accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.settings-header h2 {
  margin: 8px 0 8px;
  color: var(--ti-text-primary);
  font-size: 28px;
  line-height: 1.2;
}

.settings-header p {
  margin: 0;
  color: var(--ti-text-secondary);
}

.module-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.content-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 22px;
}

.ti-card-subtitle {
  margin-top: 6px;
  color: var(--ti-text-secondary);
  font-size: 13px;
}

.source-overview {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.source-overview__item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--ti-border);
  border-radius: 8px;
  color: var(--ti-text-secondary);
  background: var(--ti-surface-soft);
}

.source-overview__item strong {
  color: var(--ti-text-primary);
}

.ti-table-shell {
  margin-top: 18px;
}

.cursor-pages {
  color: #155bd6;
  font-weight: 600;
}

.state-status {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 4px;
  color: #2f6b4f;
  background: rgba(55, 182, 166, 0.12);
  font-size: 12px;
  font-weight: 600;
}

.state-status--error,
.state-status--captcha,
.state-status--login_required,
.state-status--rate_limited {
  color: #b45808;
  background: rgba(238, 157, 41, 0.14);
}

.source-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.table-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.watchlist-toolbar {
  display: grid;
  grid-template-columns: minmax(260px, 380px) minmax(160px, 220px) auto;
  gap: 16px;
  margin-bottom: 18px;
}

.watchlist-toolbar__item {
  display: grid;
  gap: 8px;
}

.watchlist-toolbar__item--switch {
  align-content: start;
}

.module-family {
  min-height: 32px;
  display: flex;
  align-items: center;
}

.watchlist-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.watchlist-options {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) 180px 180px;
  gap: 12px;
  margin-bottom: 18px;
}

.watchlist-option {
  display: grid;
  gap: 8px;
}

.watchlist-option--switch {
  align-content: start;
}

.watchlist-toolbar__item span,
.watchlist-option span {
  color: var(--ti-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.watchlist-terms {
  display: grid;
  gap: 10px;
}

.watchlist-terms__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.watchlist-term-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 160px 120px 96px 80px;
  gap: 10px;
  align-items: center;
}

@media (max-width: 1200px) {
  .settings-header {
    display: grid;
  }

  .module-tabs {
    justify-content: flex-start;
  }

  .watchlist-toolbar,
  .watchlist-form,
  .watchlist-options,
  .watchlist-term-row {
    grid-template-columns: 1fr;
  }
}
</style>
