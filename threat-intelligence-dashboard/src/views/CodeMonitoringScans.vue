<template>
  <div class="code-monitoring-scans ti-page">
    <section class="content-grid">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">代码扫描执行</div>
          <div class="health-actions">
            <el-button plain :loading="loadingWatchlists" @click="loadWatchlists">刷新配置</el-button>
            <el-button type="success" :loading="scanLoading" @click="runScan">立即扫描</el-button>
            <el-select v-model="continuousIntervalHours" style="width: 150px">
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
              <span>最近分层结果</span>
              <strong class="metric-card__value metric-card__value--small">{{ `${continuousStatus.sensitive_hit_count || 0} / ${continuousStatus.clue_hit_count || 0}` }}</strong>
            </div>
          </div>

          <div class="scan-form">
            <div class="scan-form__item">
              <span>监测对象</span>
              <el-select v-model="scanForm.watchlistId" placeholder="选择监测对象">
                <el-option v-for="item in watchlists" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </div>
          </div>

          <div class="rule-box">
            <span>敏感规则</span>
            <el-checkbox-group v-model="scanForm.enabledRuleKeys">
              <el-checkbox v-for="item in ruleOptions" :key="item.value" :label="item.value">
                {{ item.label }}
              </el-checkbox>
            </el-checkbox-group>
          </div>

          <div class="scan-status">
            <p class="panel-note">代码监测长期后台扫描按监测对象独立运行，当前页面仅展示所选监测对象的长期任务状态，并沿用该对象的 GitHub / GitLab / Gitee 平台配置、详情抓取和不受限的搜索/结果预算。</p>
            <p v-if="(continuousStatus.active_watchlist_count || 0) > 1" class="panel-note">当前共有 {{ continuousStatus.active_watchlist_count }} 个监测对象在执行长期扫描。</p>
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
            <el-table :data="scanRuns" table-layout="auto">
              <el-table-column prop="finishedAt" label="完成时间" min-width="180">
                <template #default="{ row }">
                  {{ formatDateTime(row.finishedAt) || '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="watchlistName" label="监测对象" min-width="180" />
              <el-table-column label="扫描平台" min-width="220">
                <template #default="{ row }">
                  {{ Array.isArray(row.platforms) ? row.platforms.join(' / ') : '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="candidateCount" label="候选数" width="100" />
              <el-table-column prop="hitCount" label="命中数" width="100" />
              <el-table-column prop="sensitiveHitCount" label="敏感命中" width="110" />
              <el-table-column prop="clueHitCount" label="线索命中" width="110" />
              <el-table-column prop="errorCount" label="错误数" width="100" />
              <el-table-column prop="status" label="状态" width="120" />
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
import { useCodeMonitoringApi } from '@/composables/useCodeMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const api = useCodeMonitoringApi()

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
  clue_hit_count: 0,
  sensitive_hit_count: 0,
  target_watchlist_id: 0,
  target_watchlist_name: '',
  active_watchlist_count: 0,
})
let continuousTimer = null

const ruleOptions = [
  { label: 'API Key', value: 'api_key' },
  { label: 'Token', value: 'token' },
  { label: 'AK / SK', value: 'ak_sk' },
  { label: '数据库连接串', value: 'db_url' },
  { label: 'JWT Secret', value: 'jwt_secret' },
  { label: 'Redis URL', value: 'redis_url' },
  { label: '私钥', value: 'private_key' },
  { label: '内网 URL', value: 'internal_url' },
  { label: '账号口令', value: 'password' },
]

const scanForm = reactive({
  watchlistId: null,
  platforms: ['github', 'gitlab', 'gitee'],
  fileExtensions: [],
  searchPageLimit: 0,
  maxResultsPerTerm: 0,
  detailFetch: true,
  enabledRuleKeys: ['api_key', 'token', 'ak_sk', 'db_url', 'jwt_secret', 'redis_url', 'private_key', 'internal_url', 'password'],
})

const continuousStartDisabled = computed(() => {
  const selectedId = Number(scanForm.watchlistId || 0)
  if (!selectedId) return true
  return Boolean(continuousStatus.value.enabled)
})

const continuousStopDisabled = computed(() => !continuousStatus.value.enabled)

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

function applyWatchlist(payload) {
  if (!payload) return
  scanForm.watchlistId = payload.id
  scanForm.platforms = ['github', 'gitlab', 'gitee']
  scanForm.fileExtensions = []
  scanForm.searchPageLimit = 0
  scanForm.maxResultsPerTerm = 0
  scanForm.detailFetch = true
  scanForm.enabledRuleKeys = Array.isArray(payload.enabled_rule_keys) ? [...payload.enabled_rule_keys] : []
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
    continuousStatus.value = await api.loadContinuousStatus({
      watchlistId: scanForm.watchlistId || undefined,
    })
  } catch (error) {
    ElMessage.error(error.message || '加载长期扫描状态失败')
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
    const payload = await api.runScan(scanForm.watchlistId, {
      platforms: scanForm.platforms,
      file_extensions: scanForm.fileExtensions,
      search_page_limit: scanForm.searchPageLimit,
      max_results_per_term: scanForm.maxResultsPerTerm,
      detail_fetch: scanForm.detailFetch,
      enabled_rule_keys: scanForm.enabledRuleKeys,
    })
    lastRunMessage.value = `已扫描 ${payload.scanned_terms || 0} 个监测词，候选 ${payload.candidates || 0} 条，命中 ${payload.hits || 0} 条（敏感 ${payload.sensitive_hits || 0} / 线索 ${payload.clue_hits || 0}）。`
    lastRunErrors.value = payload.errors || []
    await loadScans()
    ElMessage.success('代码扫描已执行')
  } catch (error) {
    ElMessage.error(error.message || '执行代码扫描失败')
  } finally {
    scanLoading.value = false
  }
}

async function startContinuousScan() {
  if (!scanForm.watchlistId) {
    ElMessage.error('请先选择监测对象')
    return
  }
  continuousLoading.value = true
  try {
    const payload = await api.startContinuous({
      interval_seconds: Number(continuousIntervalHours.value || 1) * 3600,
      watchlist_id: scanForm.watchlistId,
    })
    continuousStatus.value = payload
    ElMessage.success(payload.message || '已开启代码监测长期扫描')
  } catch (error) {
    ElMessage.error(error.message || '开启代码监测长期扫描失败')
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
    const payload = await api.stopContinuous({
      watchlist_id: scanForm.watchlistId,
    })
    continuousStatus.value = payload
    ElMessage.success(payload.message || '已停止代码监测长期扫描')
  } catch (error) {
    ElMessage.error(error.message || '停止代码监测长期扫描失败')
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
  },
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

.scan-form__item,
.rule-box {
  display: grid;
  gap: 8px;
}

.scan-form__item span,
.rule-box span {
  color: var(--ti-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.scan-form__item--switches {
  align-content: start;
}

.scan-form__item--switches label {
  display: flex;
  align-items: center;
  gap: 10px;
}

.rule-box {
  margin-top: 18px;
}

.scan-status,
.ti-table-shell {
  margin-top: 18px;
}

@media (max-width: 1200px) {
  .status-grid,
  .scan-form {
    grid-template-columns: 1fr;
  }
}
</style>
