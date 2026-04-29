<template>
  <div class="collector-control-page ti-page">
    <section class="ti-panel ti-reveal-up">
      <div class="control-hero">
        <div class="control-hero__copy">
          <span class="ti-kicker">采集控制台</span>
          <h3>站点运行控制与情报同步</h3>
          <p>统一触发采集任务、维护漏洞与勒索情报同步，并集中查看站点健康和最近失败任务。</p>
        </div>
        <div class="control-hero__stats">
          <div class="metric-card">
            <span>总体状态</span>
            <strong>{{ jobsData.overall_status || '未知' }}</strong>
          </div>
          <div class="metric-card">
            <span>运行中任务</span>
            <strong>{{ jobsData.running_jobs || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>异常挂起</span>
            <strong>{{ jobsData.stale_jobs || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>24 小时失败</span>
            <strong>{{ jobsData.failed_jobs_24h || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>持续运行</span>
            <strong>{{ continuousStatus.enabled ? '运行中' : '未启动' }}</strong>
          </div>
          <div class="metric-card">
            <span>最近调度</span>
            <strong class="metric-card__value metric-card__value--small">{{ continuousStatus.last_tick_at || '暂无' }}</strong>
          </div>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">公开源漏洞同步</div>
        <div class="health-actions">
          <el-select v-model="vulnerabilityIntervalHours" style="width: 150px">
            <el-option label="每 1 小时" :value="1" />
            <el-option label="每 4 小时" :value="4" />
          </el-select>
          <el-button plain :loading="vulnerabilityRunLoading" @click="runVulnerabilitySyncOnce">同步一次</el-button>
          <el-button type="success" :loading="vulnerabilityContinuousLoading" :disabled="vulnerabilitySync.enabled" @click="startVulnerabilitySync">开始自动同步</el-button>
          <el-button type="danger" plain :loading="vulnerabilityContinuousLoading" :disabled="!vulnerabilitySync.enabled" @click="stopVulnerabilitySync">停止自动同步</el-button>
        </div>
      </div>
      <div class="ti-card-body status-grid">
        <div class="metric-card">
          <span>自动同步</span>
          <strong>{{ vulnerabilitySync.enabled ? '已开启' : '未开启' }}</strong>
        </div>
        <div class="metric-card">
          <span>同步间隔</span>
          <strong>{{ vulnerabilitySync.interval_seconds ? `${Math.round(vulnerabilitySync.interval_seconds / 3600)} 小时` : '未设置' }}</strong>
        </div>
        <div class="metric-card">
          <span>漏洞记录数</span>
          <strong>{{ vulnerabilitySync.record_count || 0 }}</strong>
        </div>
        <div class="metric-card">
          <span>最近同步</span>
          <strong class="metric-card__value metric-card__value--small">{{ vulnerabilitySync.last_success_at || '暂无' }}</strong>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">ransomware.live 同步接入</div>
        <div class="health-actions">
          <el-select v-model="ransomwareIntervalHours" style="width: 150px">
            <el-option label="每 1 小时" :value="1" />
            <el-option label="每 4 小时" :value="4" />
          </el-select>
          <el-button plain :loading="ransomwareRunLoading" @click="runRansomwareSyncOnce">同步一次</el-button>
          <el-button type="success" :loading="ransomwareContinuousLoading" :disabled="ransomwareSync.enabled" @click="startRansomwareSync">开始自动同步</el-button>
          <el-button type="danger" plain :loading="ransomwareContinuousLoading" :disabled="!ransomwareSync.enabled" @click="stopRansomwareSync">停止自动同步</el-button>
        </div>
      </div>
      <div class="ti-card-body">
        <div class="status-grid status-grid--compact">
          <div class="metric-card">
            <span>API Key</span>
            <strong>{{ ransomwareConfig.has_api_key ? '已配置' : '未配置' }}</strong>
          </div>
          <div class="metric-card">
            <span>自动同步</span>
            <strong>{{ ransomwareSync.enabled ? '已开启' : '未开启' }}</strong>
          </div>
          <div class="metric-card">
            <span>记录数</span>
            <strong>{{ ransomwareSync.record_count || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>最近同步</span>
            <strong class="metric-card__value metric-card__value--small">{{ ransomwareSync.last_success_at || '暂无' }}</strong>
          </div>
        </div>
        <div class="status-grid status-grid--compact">
          <div class="metric-card">
            <span>最新披露</span>
            <strong class="metric-card__value metric-card__value--small">{{ ransomwareSync.latest_disclosure_time || '暂无' }}</strong>
          </div>
          <div class="metric-card">
            <span>最近来源</span>
            <strong class="metric-card__value metric-card__value--small metric-card__value--break">{{ ransomwareLastSourceLabel }}</strong>
          </div>
          <div class="metric-card">
            <span>最近入库</span>
            <strong>{{ ransomwareSync.last_ingested || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>配置来源</span>
            <strong class="metric-card__value metric-card__value--small">{{ ransomwareConfig.source || 'none' }}</strong>
          </div>
        </div>
        <div class="credential-row">
          <el-input
            v-model="ransomwareApiKey"
            type="password"
            show-password
            placeholder="输入 ransomware.live API Key"
            class="credential-row__input"
          />
          <el-button type="primary" :loading="ransomwareSaveLoading || ransomwareConfigLoading" @click="saveRansomwareConfig">保存 Key</el-button>
        </div>
        <div class="panel-note-block">
          <p class="panel-note">当前 Key：{{ ransomwareConfig.masked_api_key || '未保存' }}</p>
          <p class="panel-note panel-note--mono">配置文件：{{ ransomwareConfig.settings_path || ransomwareConfig.env_var }}</p>
          <p v-if="ransomwareSync.last_error" class="panel-note panel-note--danger">最近错误：{{ ransomwareSync.last_error }}</p>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">运行库状态</div>
        <StatusBadge :label="runtimeDbStatus.using_runtime_db ? 'WSL 运行库' : 'Windows 源库'" :tone="runtimeDbStatus.using_runtime_db ? 'success' : 'warning'" :dot="false" />
      </div>
      <div class="ti-card-body status-grid">
        <div class="metric-card">
          <span>当前数据库</span>
          <strong class="metric-card__value metric-card__value--path">{{ runtimeDbStatus.runtime_db_path || '未知' }}</strong>
        </div>
        <div class="metric-card">
          <span>源库路径</span>
          <strong class="metric-card__value metric-card__value--path">{{ runtimeDbStatus.source_db_path || '未知' }}</strong>
        </div>
        <div class="metric-card">
          <span>上次准备</span>
          <strong class="metric-card__value metric-card__value--small">{{ runtimeDbStatus.prepared_at || '未知' }}</strong>
        </div>
        <div class="metric-card">
          <span>标准化事件</span>
          <strong>{{ runtimeDbStatus.copied_counts?.normalized_intelligence_events ?? '未知' }}</strong>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">监测规则</div>
        <div class="health-actions">
          <el-button plain :loading="keywordLoading" @click="loadMonitoringKeywords">刷新规则</el-button>
          <el-button type="primary" plain @click="addMonitoringKeyword">新增词条</el-button>
          <el-button type="success" :loading="keywordLoading" @click="saveMonitoringKeywords">保存规则</el-button>
        </div>
      </div>
      <div class="ti-card-body">
        <div class="status-grid status-grid--compact">
          <div class="metric-card">
            <span>启用规则数</span>
            <strong>{{ monitoringStatus.enabledKeywordCount || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>高优先事件</span>
            <strong>{{ monitoringStatus.highPriorityCount || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>样本证据事件</span>
            <strong>{{ monitoringStatus.sampleEvidenceCount || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>规则覆盖事件</span>
            <strong>{{ monitoringStatus.eventCount || 0 }}</strong>
          </div>
        </div>
        <p class="panel-note">英文完整词建议使用词边界匹配，中文关键词建议使用包含匹配。</p>
        <div class="ti-table-shell">
          <el-table :data="monitoringKeywords" table-layout="auto" style="width: 100%">
            <el-table-column label="关键词" min-width="180">
              <template #default="{ row }">
                <el-input v-model="row.keyword" placeholder="例如 中国 / 政府 / 能源 / 企业名" />
              </template>
            </el-table-column>
            <el-table-column label="类别" width="160">
              <template #default="{ row }">
                <el-select v-model="row.category">
                  <el-option label="地理关键词" value="geo_keywords" />
                  <el-option label="组织关键词" value="org_keywords" />
                  <el-option label="自定义关键词" value="custom_keywords" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="权重" width="120">
              <template #default="{ row }">
                <el-input-number v-model="row.weight" :min="1" :max="25" />
              </template>
            </el-table-column>
            <el-table-column label="匹配方式" width="160">
              <template #default="{ row }">
                <el-select v-model="row.match_mode">
                  <el-option label="包含匹配" value="contains" />
                  <el-option label="词边界匹配" value="word_boundary" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button text type="danger" @click="removeMonitoringKeyword(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">站点健康表</div>
        <div class="health-actions">
          <el-button plain @click="refreshAllPanels">刷新状态</el-button>
          <el-button type="primary" :loading="runningAllSites" @click="runAllSitesOnce">运行全部站点</el-button>
          <el-button type="success" :loading="continuousLoading" :disabled="continuousStatus.enabled" @click="startContinuousRun">开始持续运行</el-button>
          <el-button type="danger" plain :loading="continuousLoading" :disabled="!continuousStatus.enabled" @click="stopContinuousRun">停止持续运行</el-button>
          <StatusBadge :label="jobsData.overall_status || '未知'" tone="primary" :dot="false" />
        </div>
      </div>
      <div class="ti-card-body">
        <div class="ti-table-shell">
          <el-table :data="siteHealth" style="width: 100%" table-layout="auto">
            <el-table-column prop="site_name" label="站点" min-width="140" />
            <el-table-column prop="overall_status" label="总体状态" width="110" />
            <el-table-column prop="seed_status" label="种子页状态" width="120" />
            <el-table-column prop="detail_status" label="详情页状态" width="120" />
            <el-table-column prop="running_jobs" label="运行中" width="90" />
            <el-table-column prop="failed_jobs_24h" label="24h 失败" width="100" />
            <el-table-column prop="last_success_at" label="最近成功" min-width="170" />
            <el-table-column prop="last_error" label="最近错误" min-width="260" show-overflow-tooltip />
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" type="primary" :loading="!!runningSiteMap[row.site_name]" :disabled="isSiteRunBlocked(row) || !row.enabled" @click="runSiteOnce(row.site_name)">运行一次</el-button>
                  <el-button size="small" :type="row.enabled ? 'danger' : 'success'" plain :loading="!!togglingSiteMap[row.site_name]" @click="toggleSite(row.site_name, !row.enabled)">
                    {{ row.enabled ? '停用采集' : '启用采集' }}
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">最近失败任务</div>
        <StatusBadge label="按站点追踪" tone="warning" :dot="false" />
      </div>
      <div class="ti-card-body">
        <div v-if="recentFailures.length" class="alert-stream">
          <article v-for="item in recentFailures" :key="`${item.site_name}-${item.job_type}-${item.finished_at}`" class="alert-stream__item alert-stream__item--high">
            <div class="alert-stream__meta">
              <StatusBadge :label="item.status" tone="warning" />
              <span>{{ item.finished_at }}</span>
            </div>
            <h3>{{ item.site_name }} {{ item.job_type }} {{ item.status }}</h3>
            <p>{{ item.error_message || '暂无错误详情' }}</p>
            <div class="alert-stream__source">目标：{{ item.target }}</div>
          </article>
        </div>
        <div v-else class="empty-state"><p>最近 24 小时没有失败或异常挂起任务。</p></div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useIntelligenceData } from '@/composables/useIntelligenceData'
import { useJobsData } from '@/composables/useJobsData'
import { useContinuousJobs } from '@/composables/useContinuousJobs'

const { refresh: refreshIntelligence } = useIntelligenceData()
const { data: jobsState, refresh: refreshJobs } = useJobsData()
const { data: continuousState, refresh: refreshContinuous } = useContinuousJobs()

const jobsData = computed(() => jobsState.value || {})
const continuousStatus = computed(() => continuousState.value || {})
const siteHealth = computed(() => jobsData.value.site_health || [])
const recentFailures = computed(() => jobsData.value.recent_failures || [])
const vulnerabilitySync = computed(() => jobsData.value.vulnerability_sync || {})
const ransomwareSync = computed(() => jobsData.value.ransomware_sync || {})
const runtimeDbStatus = computed(() => jobsData.value.runtime_db || {})
const ransomwareLastSourceLabel = computed(() => {
  const raw = String(ransomwareSync.value.last_source || '').trim()
  if (!raw) return '暂无'
  try {
    return new URL(raw).host || raw
  } catch {
    return raw
  }
})

const runningAllSites = ref(false)
const continuousLoading = ref(false)
const vulnerabilityRunLoading = ref(false)
const vulnerabilityContinuousLoading = ref(false)
const vulnerabilityIntervalHours = ref(1)
const ransomwareRunLoading = ref(false)
const ransomwareContinuousLoading = ref(false)
const ransomwareSaveLoading = ref(false)
const ransomwareConfigLoading = ref(false)
const ransomwareIntervalHours = ref(1)
const ransomwareApiKey = ref('')
const ransomwareConfig = ref({
  has_api_key: false,
  masked_api_key: '',
  source: 'none',
  env_var: 'RANSOMWARE_LIVE_API_KEY',
  settings_path: '',
  updated_at: '',
})
const runningSiteMap = ref({})
const togglingSiteMap = ref({})
const keywordLoading = ref(false)
const monitoringStatus = ref({ keywordCount: 0, enabledKeywordCount: 0, highPriorityCount: 0, sampleEvidenceCount: 0, eventCount: 0 })
const monitoringKeywords = ref([])

function isSiteRunBlocked(row) {
  return row?.blockingReason === 'active_seed_job' || row?.activeSeedJobStatus === 'running' || row?.activeSeedJobStatus === 'enqueued'
}

function setSiteRunning(siteName, value) {
  runningSiteMap.value = { ...runningSiteMap.value, [siteName]: value }
}

function setSiteToggling(siteName, value) {
  togglingSiteMap.value = { ...togglingSiteMap.value, [siteName]: value }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    })
  } finally {
    window.clearTimeout(timeoutId)
  }
}

async function loadMonitoringKeywords() {
  keywordLoading.value = true
  try {
    const [keywordsResponse, statusResponse] = await Promise.all([
      fetchWithTimeout('/api/monitoring/keywords'),
      fetchWithTimeout('/api/analysis/monitoring-status'),
    ])
    monitoringKeywords.value = keywordsResponse.ok ? await keywordsResponse.json() : []
    monitoringStatus.value = statusResponse.ok ? await statusResponse.json() : monitoringStatus.value
  } finally {
    keywordLoading.value = false
  }
}

async function loadRansomwareConfig() {
  ransomwareConfigLoading.value = true
  try {
    const response = await fetch('/api/ransomware/config')
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    ransomwareConfig.value = await response.json()
  } catch (error) {
    ElMessage.error(error.message || '读取 ransomware.live 配置失败')
  } finally {
    ransomwareConfigLoading.value = false
  }
}

async function refreshAllPanels() {
  await Promise.all([refreshIntelligence(), refreshJobs(), refreshContinuous(), loadMonitoringKeywords(), loadRansomwareConfig()])
}

function addMonitoringKeyword() {
  monitoringKeywords.value = [
    ...monitoringKeywords.value,
    { id: `new-${Date.now()}`, keyword: '', category: 'custom_keywords', weight: 5, enabled: true, match_mode: 'contains' },
  ]
}

function removeMonitoringKeyword(id) {
  monitoringKeywords.value = monitoringKeywords.value.filter((item) => item.id !== id)
}

async function saveMonitoringKeywords() {
  keywordLoading.value = true
  try {
    const response = await fetch('/api/monitoring/keywords', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        keywords: monitoringKeywords.value.map((item) => ({
          keyword: item.keyword,
          category: item.category,
          weight: Number(item.weight || 0),
          enabled: Boolean(item.enabled),
          match_mode: item.match_mode || 'contains',
        })),
      }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    monitoringKeywords.value = await response.json()
    await loadMonitoringKeywords()
    await refreshIntelligence()
    ElMessage.success('监测规则已保存')
  } catch (error) {
    ElMessage.error(error.message || '保存监测规则失败')
  } finally {
    keywordLoading.value = false
  }
}

async function runSiteOnce(siteName) {
  setSiteRunning(siteName, true)
  try {
    const response = await fetch('/api/jobs/run-site', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ site_name: siteName, force: true }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success(`已触发 ${siteName} 运行一次`)
  } catch (error) {
    ElMessage.error(error.message || '触发站点运行失败')
  } finally {
    setSiteRunning(siteName, false)
  }
}

async function toggleSite(siteName, enabled) {
  setSiteToggling(siteName, true)
  try {
    const response = await fetch(`/api/sites/${encodeURIComponent(siteName)}/enabled`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success(enabled ? `已启用 ${siteName}` : `已停用 ${siteName}`)
  } catch (error) {
    ElMessage.error(error.message || '更新站点状态失败')
  } finally {
    setSiteToggling(siteName, false)
  }
}

async function runAllSitesOnce() {
  runningAllSites.value = true
  try {
    const response = await fetch('/api/jobs/run-all-once', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已触发全部站点运行')
  } catch (error) {
    ElMessage.error(error.message || '触发全部站点运行失败')
  } finally {
    runningAllSites.value = false
  }
}

async function startContinuousRun() {
  continuousLoading.value = true
  try {
    const response = await fetch('/api/jobs/run-all-continuous/start', { method: 'POST' })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshContinuous()
    ElMessage.success('已开启持续运行')
  } catch (error) {
    ElMessage.error(error.message || '开启持续运行失败')
  } finally {
    continuousLoading.value = false
  }
}

async function stopContinuousRun() {
  continuousLoading.value = true
  try {
    const response = await fetch('/api/jobs/run-all-continuous/stop', { method: 'POST' })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshContinuous()
    ElMessage.success('已停止持续运行')
  } catch (error) {
    ElMessage.error(error.message || '停止持续运行失败')
  } finally {
    continuousLoading.value = false
  }
}

async function runVulnerabilitySyncOnce() {
  vulnerabilityRunLoading.value = true
  try {
    const response = await fetch('/api/vulnerabilities/sync/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 300 }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已触发漏洞同步')
  } catch (error) {
    ElMessage.error(error.message || '触发漏洞同步失败')
  } finally {
    vulnerabilityRunLoading.value = false
  }
}

async function startVulnerabilitySync() {
  vulnerabilityContinuousLoading.value = true
  try {
    const response = await fetch('/api/vulnerabilities/sync/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        interval_seconds: Number(vulnerabilityIntervalHours.value || 1) * 3600,
        limit: 300,
      }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已开启漏洞自动同步')
  } catch (error) {
    ElMessage.error(error.message || '开启漏洞自动同步失败')
  } finally {
    vulnerabilityContinuousLoading.value = false
  }
}

async function stopVulnerabilitySync() {
  vulnerabilityContinuousLoading.value = true
  try {
    const response = await fetch('/api/vulnerabilities/sync/stop', { method: 'POST' })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已停止漏洞自动同步')
  } catch (error) {
    ElMessage.error(error.message || '停止漏洞自动同步失败')
  } finally {
    vulnerabilityContinuousLoading.value = false
  }
}

async function saveRansomwareConfig() {
  const apiKey = String(ransomwareApiKey.value || '').trim()
  if (!apiKey) {
    ElMessage.error('请输入 ransomware.live API Key')
    return
  }

  ransomwareSaveLoading.value = true
  try {
    const response = await fetch('/api/ransomware/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    ransomwareConfig.value = await response.json()
    ransomwareApiKey.value = ''
    ElMessage.success('已保存 ransomware.live API Key')
  } catch (error) {
    ElMessage.error(error.message || '保存 ransomware.live API Key 失败')
  } finally {
    ransomwareSaveLoading.value = false
  }
}

async function runRansomwareSyncOnce() {
  ransomwareRunLoading.value = true
  try {
    const response = await fetch('/api/ransomware/sync/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 0 }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    await refreshIntelligence()
    ElMessage.success('已触发 ransomware.live 同步')
  } catch (error) {
    ElMessage.error(error.message || '触发 ransomware.live 同步失败')
  } finally {
    ransomwareRunLoading.value = false
  }
}

async function startRansomwareSync() {
  ransomwareContinuousLoading.value = true
  try {
    const response = await fetch('/api/ransomware/sync/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        interval_seconds: Number(ransomwareIntervalHours.value || 1) * 3600,
        limit: 0,
      }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已开启 ransomware.live 自动同步')
  } catch (error) {
    ElMessage.error(error.message || '开启 ransomware.live 自动同步失败')
  } finally {
    ransomwareContinuousLoading.value = false
  }
}

async function stopRansomwareSync() {
  ransomwareContinuousLoading.value = true
  try {
    const response = await fetch('/api/ransomware/sync/stop', { method: 'POST' })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已停止 ransomware.live 自动同步')
  } catch (error) {
    ElMessage.error(error.message || '停止 ransomware.live 自动同步失败')
  } finally {
    ransomwareContinuousLoading.value = false
  }
}

onMounted(async () => {
  await refreshAllPanels()
})
</script>

<style scoped lang="scss">
.control-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 1fr);
  gap: 24px;
  align-items: start;
}

.control-hero__copy h3 {
  margin: 10px 0 0;
  color: var(--ti-text-primary);
  font-size: 34px;
}

.control-hero__copy p {
  margin: 12px 0 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
}

.control-hero__stats,
.status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.metric-card {
  min-width: 0;
  padding: 16px 18px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.92);
}

.metric-card span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.metric-card strong {
  display: block;
  margin-top: 8px;
  color: var(--ti-text-primary);
  font-size: clamp(20px, 2vw, 28px);
  line-height: 1.25;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.metric-card__value--small {
  font-size: clamp(16px, 1.35vw, 22px);
}

.metric-card__value--path {
  font-size: clamp(14px, 1.05vw, 18px);
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
}

.metric-card__value--break {
  word-break: break-all;
}

.status-grid--compact {
  margin-bottom: 16px;
}

.credential-row {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.credential-row__input {
  flex: 1 1 360px;
  min-width: 220px;
}

.panel-note-block {
  display: grid;
  gap: 6px;
}

.panel-note {
  margin: 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.panel-note--mono {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: 13px;
}

.panel-note--danger {
  color: #b91c1c;
}

.health-actions,
.row-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.alert-stream {
  display: grid;
  gap: 12px;
}

.alert-stream__item {
  padding: 16px 18px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.92);
}

.alert-stream__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.alert-stream__item h3 {
  margin: 10px 0 0;
  color: var(--ti-text-primary);
}

.alert-stream__item p,
.alert-stream__source {
  margin: 10px 0 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
  word-break: break-word;
  overflow-wrap: anywhere;
}

@media (max-width: 1440px) {
  .control-hero,
  .control-hero__stats,
  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .control-hero {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 767px) {
  .control-hero__stats,
  .status-grid {
    grid-template-columns: 1fr;
  }
}
</style>
