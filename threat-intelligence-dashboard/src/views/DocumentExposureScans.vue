<template>
  <div class="document-exposure-scans ti-page">
    <section class="content-grid">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">扫描执行</div>
          <div class="health-actions">
            <el-button plain :loading="loadingWatchlists" @click="loadWatchlists">刷新配置</el-button>
            <el-button type="success" :loading="scanLoading" @click="runScan">立即扫描</el-button>
            <el-select v-model="continuousIntervalHours" style="width: 150px" :disabled="!isSelectedNetdiskWatchlist">
              <el-option label="每 1 小时" :value="1" />
              <el-option label="每 4 小时" :value="4" />
              <el-option label="每 8 小时" :value="8" />
            </el-select>
            <el-button type="success" :loading="continuousLoading" :disabled="continuousStartDisabled" @click="startContinuousScan">开始长期扫描</el-button>
            <el-button type="danger" plain :loading="continuousLoading" :disabled="continuousStopDisabled" @click="stopContinuousScan">停止长期扫描</el-button>
          </div>
        </div>
        <div class="ti-card-body">
          <div class="status-grid status-grid--compact">
            <div class="metric-card">
              <span>长期任务</span>
              <strong>{{ continuousStatus.enabled ? '运行中' : '未启动' }}</strong>
            </div>
            <div class="metric-card">
              <span>运行任务数</span>
              <strong>{{ continuousStatus.active_watchlist_count || 0 }}</strong>
            </div>
            <div class="metric-card">
              <span>扫描间隔</span>
              <strong>{{ continuousStatus.interval_seconds ? `${Math.round(continuousStatus.interval_seconds / 3600)} 小时` : '未设置' }}</strong>
            </div>
            <div class="metric-card">
              <span>最近后台扫描</span>
              <strong class="metric-card__value metric-card__value--small">{{ formatDateTime(continuousStatus.last_success_at) || '暂无' }}</strong>
            </div>
            <div class="metric-card">
              <span>长期对象</span>
              <strong class="metric-card__value metric-card__value--small">{{ continuousStatus.target_watchlist_name || '未绑定' }}</strong>
            </div>
            <div class="metric-card">
              <span>最近命中 / 候选</span>
              <strong class="metric-card__value metric-card__value--small">{{ `${continuousStatus.hit_count || 0} / ${continuousStatus.candidate_count || 0}` }}</strong>
            </div>
          </div>

          <div class="scan-form">
            <div class="scan-form__item">
              <span>监测对象</span>
              <el-select v-model="scanForm.watchlistId" placeholder="选择监测对象">
                <el-option
                  v-for="item in watchlists"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </div>
            <div class="scan-form__item">
              <span>来源家族</span>
              <el-select v-model="scanForm.sourceFamilies" multiple collapse-tags placeholder="选择来源家族">
                <el-option label="网盘聚合" value="netdisk_aggregator" />
                <el-option label="搜索引擎" value="search_engine" />
                <el-option label="文档平台" value="document_library" />
              </el-select>
            </div>
            <div class="scan-form__item">
              <span>文件类型</span>
              <el-select v-model="scanForm.fileTypes" multiple collapse-tags placeholder="选择文件类型">
                <el-option v-for="item in fileTypeOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </div>
            <div v-if="!isSelectedNetdiskWatchlist" class="scan-form__item">
              <span>页数上限</span>
              <el-input-number v-model="scanForm.pageLimit" :min="1" :max="20" />
            </div>
            <div class="scan-form__item">
              <span>详情抓取</span>
              <el-switch v-model="scanForm.detailFetch" />
            </div>
          </div>

          <div class="scan-status">
            <p class="panel-note">网盘长期后台扫描按监测对象独立运行，固定使用网盘聚合来源，并跳过详情抓取和镜像文件。</p>
            <p v-if="!isSelectedNetdiskWatchlist" class="panel-note panel-note--danger">当前监测对象未启用网盘聚合来源，不能开启网盘长期扫描。</p>
            <p v-if="(continuousStatus.active_watchlist_count || 0) > 1" class="panel-note">当前共有 {{ continuousStatus.active_watchlist_count }} 个监测对象在执行网盘长期扫描。</p>
            <p v-if="lastRunMessage" class="panel-note">{{ lastRunMessage }}</p>
            <p v-if="continuousStatus.last_error" class="panel-note panel-note--danger">后台扫描错误：{{ continuousStatus.last_error }}</p>
            <p v-if="lastRunErrors.length" class="panel-note panel-note--danger">
              最近扫描错误：{{ lastRunErrors.slice(0, 3).join('；') }}
            </p>
          </div>
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">扫描历史</div>
          <div class="health-actions">
            <el-button plain :loading="loadingScans" @click="loadScans">刷新历史</el-button>
          </div>
        </div>
        <div class="ti-card-body">
          <div class="ti-table-shell">
            <el-table :data="scanRuns" table-layout="auto" style="width: 100%">
              <el-table-column type="expand" width="44">
                <template #default="{ row }">
                  <div class="source-stats-detail">
                    <div v-if="!sourceStatsRows(row).length" class="source-stats-empty">暂无来源统计</div>
                    <div v-for="item in sourceStatsRows(row)" :key="item.source" class="source-stat-row">
                      <div class="source-stat-row__name">
                        <strong>{{ item.sourceLabel || item.source }}</strong>
                        <span>{{ item.source }}</span>
                      </div>
                      <div class="source-stat-row__metrics">
                        <span>页数 {{ item.pagesScanned || 0 }}</span>
                        <span>候选 {{ item.candidateCount || 0 }}</span>
                        <span>命中 {{ item.hitCount || 0 }}</span>
                        <span>错误 {{ item.errorCount || 0 }}</span>
                      </div>
                      <el-tooltip v-if="item.lastUrl" :content="item.lastUrl" placement="top">
                        <span class="source-stat-row__url">第 {{ item.lastPage || 0 }} 页</span>
                      </el-tooltip>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="finishedAt" label="完成时间" min-width="180">
                <template #default="{ row }">
                  {{ formatDateTime(row.finishedAt) || '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="watchlistName" label="监测对象" min-width="180" />
              <el-table-column label="来源家族" min-width="220">
                <template #default="{ row }">
                  {{ formatSourceFamilies(row.sourceFamilies) }}
                </template>
              </el-table-column>
              <el-table-column prop="candidateCount" label="候选数" width="100" />
              <el-table-column prop="hitCount" label="命中数" width="100" />
              <el-table-column prop="errorCount" label="错误数" width="100" />
              <el-table-column label="源统计" min-width="190">
                <template #default="{ row }">
                  {{ formatSourceStatsSummary(row) }}
                </template>
              </el-table-column>
              <el-table-column prop="status" label="状态" width="120">
                <template #default="{ row }">
                  {{ statusLabelMap[row.status] || row.status || 'unknown' }}
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useDocumentExposureApi } from '@/composables/useDocumentExposureApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const api = useDocumentExposureApi()
const loadingWatchlists = ref(false)
const loadingScans = ref(false)
const scanLoading = ref(false)
const continuousLoading = ref(false)
const watchlists = ref([])
const scanRuns = ref([])
const lastRunMessage = ref('')
const lastRunErrors = ref([])
const continuousIntervalHours = ref(1)
const continuousStatus = ref({
  enabled: false,
  running: false,
  started_at: '',
  last_tick_at: '',
  last_success_at: '',
  last_error: '',
  interval_seconds: 3600,
  watchlist_count: 0,
  candidate_count: 0,
  hit_count: 0,
  error_count: 0,
  target_watchlist_id: 0,
  target_watchlist_name: '',
  active_watchlist_count: 0,
})
let continuousTimer = null
const fileTypeOptions = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'zip', 'rar', '7z', 'txt', 'csv']

const statusLabelMap = {
  succeeded: '成功',
  partial: '部分成功',
  failed: '失败',
}

const sourceFamilyLabelMap = {
  netdisk_aggregator: '网盘聚合',
  search_engine: '搜索引擎',
  document_library: '文档平台',
}

const scanForm = reactive({
  watchlistId: null,
  sourceFamilies: [],
  fileTypes: [],
  pageLimit: 4,
  detailFetch: true,
})

const selectedWatchlist = computed(() => {
  const selectedId = Number(scanForm.watchlistId || 0)
  return watchlists.value.find((item) => Number(item.id || 0) === selectedId) || null
})

const isSelectedNetdiskWatchlist = computed(() => {
  return Array.isArray(scanForm.sourceFamilies) && scanForm.sourceFamilies.includes('netdisk_aggregator')
})

const continuousStartDisabled = computed(() => {
  if (!scanForm.watchlistId || !isSelectedNetdiskWatchlist.value) return true
  return Boolean(continuousStatus.value.enabled)
})

const continuousStopDisabled = computed(() => !continuousStatus.value.enabled)

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

function formatSourceFamilies(value) {
  const rows = Array.isArray(value) ? value : []
  if (!rows.length) return '全部'
  return rows.map((item) => sourceFamilyLabelMap[item] || item).join(' / ')
}

function sourceStatsRows(row) {
  return Array.isArray(row?.sourceStats) ? row.sourceStats : []
}

function formatSourceStatsSummary(row) {
  const rows = sourceStatsRows(row)
  if (!rows.length) return '-'
  const pages = rows.reduce((sum, item) => sum + Number(item.pagesScanned || 0), 0)
  const candidates = rows.reduce((sum, item) => sum + Number(item.candidateCount || 0), 0)
  const hits = rows.reduce((sum, item) => sum + Number(item.hitCount || 0), 0)
  const errors = rows.reduce((sum, item) => sum + Number(item.errorCount || 0), 0)
  return `${pages} 页 / ${candidates} 候选 / ${hits} 命中 / ${errors} 错误`
}

function isNetdiskOnly(sourceFamilies) {
  return Array.isArray(sourceFamilies) && sourceFamilies.length === 1 && sourceFamilies[0] === 'netdisk_aggregator'
}

function isDocumentLibraryOnly(sourceFamilies) {
  return Array.isArray(sourceFamilies) && sourceFamilies.length === 1 && sourceFamilies[0] === 'document_library'
}

function defaultPageLimit(sourceFamilies) {
  return isDocumentLibraryOnly(sourceFamilies) ? 10 : 4
}

function applyWatchlist(payload) {
  if (!payload) return
  scanForm.watchlistId = payload.id
  scanForm.sourceFamilies = Array.isArray(payload.source_families) ? [...payload.source_families] : []
  scanForm.fileTypes = Array.isArray(payload.file_types) ? [...payload.file_types] : []
  scanForm.pageLimit = Number(payload.page_limit || defaultPageLimit(scanForm.sourceFamilies))
  scanForm.detailFetch = isNetdiskOnly(scanForm.sourceFamilies) ? false : Boolean(payload.detail_fetch ?? true)
}

async function loadWatchlists() {
  loadingWatchlists.value = true
  try {
    watchlists.value = await api.loadWatchlists()
    if (!scanForm.watchlistId) {
      applyWatchlist(watchlists.value[0] || null)
      return
    }
    const current = watchlists.value.find((item) => item.id === scanForm.watchlistId)
    if (current) applyWatchlist(current)
  } catch (error) {
    ElMessage.error(error.message || '加载监测对象失败')
  } finally {
    loadingWatchlists.value = false
  }
}

async function loadScans() {
  loadingScans.value = true
  try {
    scanRuns.value = await api.loadScans({ limit: 50, watchlistId: scanForm.watchlistId || undefined })
  } catch (error) {
    ElMessage.error(error.message || '加载扫描历史失败')
  } finally {
    loadingScans.value = false
  }
}

async function loadContinuousStatus() {
  try {
    continuousStatus.value = await api.loadNetdiskContinuousStatus({
      watchlistId: scanForm.watchlistId || undefined,
    })
  } catch (error) {
    ElMessage.error(error.message || '加载网盘长期扫描状态失败')
  }
}

async function runScan() {
  if (!scanForm.watchlistId) {
    ElMessage.error('请先选择监测对象')
    return
  }
  scanLoading.value = true
  lastRunMessage.value = ''
  lastRunErrors.value = []
  try {
    const requestPayload = {
      source_families: scanForm.sourceFamilies,
      file_types: scanForm.fileTypes,
      detail_fetch: scanForm.detailFetch,
    }
    if (!isSelectedNetdiskWatchlist.value) {
      requestPayload.max_candidates_per_term = scanForm.pageLimit
      requestPayload.page_limit = scanForm.pageLimit
    }
    const payload = await api.runScan(scanForm.watchlistId, requestPayload)
    lastRunMessage.value = `已扫描 ${payload.scanned_terms || 0} 个监测词，候选 ${payload.candidates || 0} 条，命中 ${payload.hits || 0} 条。`
    lastRunErrors.value = payload.errors || []
    await loadScans()
    ElMessage.success('扫描任务已执行')
  } catch (error) {
    ElMessage.error(error.message || '执行扫描失败')
  } finally {
    scanLoading.value = false
  }
}

async function startContinuousScan() {
  if (!scanForm.watchlistId) {
    ElMessage.error('请先选择监测对象')
    return
  }
  if (!isSelectedNetdiskWatchlist.value) {
    ElMessage.error('当前监测对象未启用网盘聚合来源')
    return
  }
  continuousLoading.value = true
  try {
    const payload = await api.startNetdiskContinuous({
      interval_seconds: Number(continuousIntervalHours.value || 1) * 3600,
      watchlist_id: scanForm.watchlistId,
    })
    continuousStatus.value = payload
    ElMessage.success(payload.message || '已开启网盘长期扫描')
  } catch (error) {
    ElMessage.error(error.message || '开启网盘长期扫描失败')
  } finally {
    continuousLoading.value = false
  }
}

async function stopContinuousScan() {
  if (!scanForm.watchlistId) {
    ElMessage.error('请先选择监测对象')
    return
  }
  continuousLoading.value = true
  try {
    const payload = await api.stopNetdiskContinuous({
      watchlist_id: scanForm.watchlistId,
    })
    continuousStatus.value = payload
    ElMessage.success(payload.message || '已停止网盘长期扫描')
  } catch (error) {
    ElMessage.error(error.message || '停止网盘长期扫描失败')
  } finally {
    continuousLoading.value = false
  }
}

watch(
  () => scanForm.watchlistId,
  async (watchlistId) => {
    if (!watchlistId) return
    const target = watchlists.value.find((item) => item.id === watchlistId)
    if (target) applyWatchlist(target)
    await loadScans()
    await loadContinuousStatus()
  }
)

watch(
  () => [...scanForm.sourceFamilies],
  (families, previousFamilies) => {
    if (isDocumentLibraryOnly(families) && !isDocumentLibraryOnly(previousFamilies) && Number(scanForm.pageLimit || 0) <= 4) {
      scanForm.pageLimit = 10
    }
    if (isNetdiskOnly(families)) {
      scanForm.detailFetch = false
    }
  }
)

onMounted(async () => {
  await loadWatchlists()
  await loadScans()
  await loadContinuousStatus()
  continuousTimer = window.setInterval(() => {
    loadContinuousStatus()
    loadScans()
  }, 15000)
})

onUnmounted(() => {
  if (continuousTimer) {
    window.clearInterval(continuousTimer)
    continuousTimer = null
  }
})
</script>

<style scoped lang="scss">
.content-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 22px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.metric-card {
  display: grid;
  gap: 6px;
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(247, 250, 255, 0.96);
  border: 1px solid rgba(116, 142, 184, 0.14);
}

.metric-card span {
  color: var(--ti-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.metric-card strong {
  color: var(--ti-text-primary);
}

.metric-card__value--small {
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
}

.scan-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.scan-form__item {
  display: grid;
  gap: 8px;
}

.scan-form__item span {
  color: var(--ti-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.scan-status {
  margin-top: 18px;
}

.ti-table-shell {
  margin-top: 18px;
}

.source-stats-detail {
  display: grid;
  gap: 8px;
  padding: 10px 18px 14px 62px;
  background: rgba(247, 250, 255, 0.72);
}

.source-stats-empty {
  color: var(--ti-text-secondary);
  font-size: 13px;
}

.source-stat-row {
  display: grid;
  grid-template-columns: minmax(150px, 220px) minmax(280px, 1fr) minmax(80px, auto);
  align-items: center;
  gap: 14px;
  padding: 9px 12px;
  border: 1px solid rgba(116, 142, 184, 0.14);
  border-radius: 10px;
  background: #fff;
}

.source-stat-row__name,
.source-stat-row__metrics {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.source-stat-row__name span,
.source-stat-row__metrics span,
.source-stat-row__url {
  color: var(--ti-text-secondary);
  font-size: 12px;
}

.source-stat-row__metrics {
  flex-wrap: wrap;
}

.source-stat-row__url {
  justify-self: end;
}

@media (max-width: 1200px) {
  .status-grid,
  .scan-form {
    grid-template-columns: 1fr;
  }
}
</style>
