<template>
  <div class="collector-control-page ti-page">
    <section class="ti-panel ti-reveal-up">
      <div class="control-hero">
        <div>
          <span class="ti-kicker">采集控制台</span>
          <h3>站点运行控制与健康监测</h3>
          <p>统一触发站点采集任务、启用或停用单个站点，并快速定位最近的失败任务。</p>
        </div>
        <div class="control-hero__stats">
          <div>
            <span>总体状态</span>
            <strong>{{ jobsData.overall_status || '未知' }}</strong>
          </div>
          <div>
            <span>运行中任务</span>
            <strong>{{ jobsData.running_jobs || 0 }}</strong>
          </div>
          <div>
            <span>异常挂起</span>
            <strong>{{ jobsData.stale_jobs || 0 }}</strong>
          </div>
          <div>
            <span>24 小时失败</span>
            <strong>{{ jobsData.failed_jobs_24h || 0 }}</strong>
          </div>
          <div>
            <span>持久运行</span>
            <strong>{{ continuousStatus.enabled ? '运行中' : '未启动' }}</strong>
          </div>
          <div>
            <span>最近调度</span>
            <strong>{{ continuousStatus.last_tick_at || '暂无' }}</strong>
          </div>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">公开源漏洞同步控制</div>
        <div class="health-actions">
          <el-select v-model="vulnerabilityIntervalHours" style="width: 150px">
            <el-option label="每 1 小时" :value="1" />
            <el-option label="每 4 小时" :value="4" />
          </el-select>
          <el-button plain :loading="vulnerabilityRunLoading" @click="runVulnerabilitySyncOnce">
            同步一次
          </el-button>
          <el-button
            type="success"
            :loading="vulnerabilityContinuousLoading"
            :disabled="vulnerabilitySync.enabled"
            @click="startVulnerabilitySync"
          >
            开始自动同步
          </el-button>
          <el-button
            type="danger"
            plain
            :loading="vulnerabilityContinuousLoading"
            :disabled="!vulnerabilitySync.enabled"
            @click="stopVulnerabilitySync"
          >
            停止自动同步
          </el-button>
          <StatusBadge
            :label="vulnerabilitySync.running ? '同步中' : vulnerabilitySync.enabled ? '自动运行中' : '未运行'"
            :tone="vulnerabilitySync.running ? 'warning' : vulnerabilitySync.enabled ? 'success' : 'muted'"
            :dot="false"
          />
        </div>
      </div>
      <div class="ti-card-body">
        <div class="vulnerability-sync-grid">
          <div>
            <span>自动同步</span>
            <strong>{{ vulnerabilitySync.enabled ? '已开启' : '未开启' }}</strong>
          </div>
          <div>
            <span>同步间隔</span>
            <strong>{{ vulnerabilitySync.interval_seconds ? `${Math.round(vulnerabilitySync.interval_seconds / 3600)} 小时` : '未设置' }}</strong>
          </div>
          <div>
            <span>漏洞记录数</span>
            <strong>{{ vulnerabilitySync.record_count || 0 }}</strong>
          </div>
          <div>
            <span>最近同步</span>
            <strong>{{ vulnerabilitySync.last_success_at || '暂无' }}</strong>
          </div>
          <div>
            <span>最新漏洞日期</span>
            <strong>{{ vulnerabilitySync.latest_disclosure_time || '暂无' }}</strong>
          </div>
          <div>
            <span>最近结果</span>
            <strong>{{ vulnerabilitySync.last_ingested ? `同步 ${vulnerabilitySync.last_ingested} 条` : '暂无' }}</strong>
          </div>
        </div>
        <div v-if="vulnerabilitySync.last_error" class="empty-state vulnerability-sync-error">
          <p>最近错误：{{ vulnerabilitySync.last_error }}</p>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">运行库状态</div>
        <StatusBadge
          :label="runtimeDbStatus.using_runtime_db ? 'WSL 运行库' : 'Windows 源库'"
          :tone="runtimeDbStatus.using_runtime_db ? 'success' : 'warning'"
          :dot="false"
        />
      </div>
      <div class="ti-card-body">
        <div class="vulnerability-sync-grid">
          <div>
            <span>当前数据库</span>
            <strong>{{ runtimeDbStatus.runtime_db_path || '未知' }}</strong>
          </div>
          <div>
            <span>源库路径</span>
            <strong>{{ runtimeDbStatus.source_db_path || '未知' }}</strong>
          </div>
          <div>
            <span>上次准备</span>
            <strong>{{ runtimeDbStatus.prepared_at || '未知' }}</strong>
          </div>
          <div>
            <span>运行库大小</span>
            <strong>{{ runtimeDbStatus.runtime_db_size_mb ? `${runtimeDbStatus.runtime_db_size_mb} MB` : '未知' }}</strong>
          </div>
          <div>
            <span>Victims 记录</span>
            <strong>{{ runtimeDbStatus.copied_counts?.victims ?? '未知' }}</strong>
          </div>
          <div>
            <span>标准化事件</span>
            <strong>{{ runtimeDbStatus.copied_counts?.normalized_intelligence_events ?? '未知' }}</strong>
          </div>
        </div>
        <div v-if="Object.keys(runtimeDbStatus.skipped_tables || {}).length" class="empty-state vulnerability-sync-error">
          <p>运行库准备时跳过的表：{{ Object.keys(runtimeDbStatus.skipped_tables || {}).join(' / ') }}</p>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">站点健康表</div>
        <div class="health-actions">
          <el-button plain @click="refreshAllPanels">刷新状态</el-button>
          <el-button type="primary" :loading="runningAllSites" @click="runAllSitesOnce">
            运行全部站点
          </el-button>
          <el-button
            type="success"
            :loading="continuousLoading"
            :disabled="continuousStatus.enabled"
            @click="startContinuousRun"
          >
            开始持久运行
          </el-button>
          <el-button
            type="danger"
            plain
            :loading="continuousLoading"
            :disabled="!continuousStatus.enabled"
            @click="stopContinuousRun"
          >
            停止持久运行
          </el-button>
          <StatusBadge :label="jobsData.overall_status || '未知'" tone="primary" :dot="false" />
        </div>
      </div>
      <div class="ti-card-body">
        <div class="ti-table-shell">
          <el-table :data="siteHealth" style="width: 100%" table-layout="auto">
            <el-table-column prop="site_name" label="站点" min-width="140" />
            <el-table-column label="采集开关" width="100">
              <template #default="{ row }">
                <StatusBadge :label="row.enabled ? '已启用' : '已停用'" :tone="row.enabled ? 'success' : 'muted'" />
              </template>
            </el-table-column>
            <el-table-column prop="overall_status" label="总体状态" width="110" />
            <el-table-column prop="seed_status" label="种子页状态" width="120" />
            <el-table-column prop="detail_status" label="详情页状态" width="120" />
            <el-table-column prop="running_jobs" label="运行中" width="90" />
            <el-table-column prop="failed_jobs_24h" label="24h失败" width="100" />
            <el-table-column prop="forum_details_count" label="详情记录" width="100" />
            <el-table-column prop="victims_count" label="受害者数" width="100" />
            <el-table-column prop="last_success_at" label="最近成功" min-width="170" />
            <el-table-column prop="last_error" label="最近错误" min-width="260" show-overflow-tooltip />
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button
                    size="small"
                    type="primary"
                    :loading="!!runningSiteMap[row.site_name]"
                    :disabled="isSiteRunBlocked(row) || !row.enabled"
                    @click="runSiteOnce(row.site_name)"
                  >
                    运行一次
                  </el-button>
                  <el-button
                    size="small"
                    :type="row.enabled ? 'danger' : 'success'"
                    plain
                    :loading="!!togglingSiteMap[row.site_name]"
                    @click="toggleSite(row.site_name, !row.enabled)"
                  >
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
          <article
            v-for="item in recentFailures"
            :key="`${item.site_name}-${item.job_type}-${item.finished_at}`"
            class="alert-stream__item alert-stream__item--high"
          >
            <div class="alert-stream__meta">
              <StatusBadge :label="item.status" tone="warning" />
              <span>{{ item.finished_at }}</span>
            </div>
            <h3>{{ item.site_name }} {{ item.job_type }} {{ item.status }}</h3>
            <p>{{ item.error_message }}</p>
            <div class="alert-stream__source">目标：{{ item.target }}</div>
          </article>
        </div>
        <div v-else class="empty-state">
          <p>最近 24 小时没有失败或异常挂起任务。</p>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
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
const runtimeDbStatus = computed(() => jobsData.value.runtime_db || {})

const runningAllSites = ref(false)
const continuousLoading = ref(false)
const vulnerabilityRunLoading = ref(false)
const vulnerabilityContinuousLoading = ref(false)
const vulnerabilityIntervalHours = ref(1)
const runningSiteMap = ref({})
const togglingSiteMap = ref({})
let pollTimer = null

function isSiteRunBlocked(row) {
  return row?.blockingReason === 'active_seed_job' || row?.activeSeedJobStatus === 'running' || row?.activeSeedJobStatus === 'enqueued'
}

function setSiteRunning(siteName, value) {
  runningSiteMap.value = {
    ...runningSiteMap.value,
    [siteName]: value,
  }
}

function setSiteToggling(siteName, value) {
  togglingSiteMap.value = {
    ...togglingSiteMap.value,
    [siteName]: value,
  }
}

async function refreshAllPanels() {
  await Promise.all([refreshIntelligence(), refreshJobs(), refreshContinuous()])
}

async function runSiteOnce(siteName) {
  setSiteRunning(siteName, true)
  try {
    const response = await fetch('/api/jobs/run-site', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ site_name: siteName, force: true }),
    })
    if (!response.ok) {
      throw new Error(`请求失败：${response.status}`)
    }
    const payload = await response.json()
    ElMessage.success(payload.message || `${siteName} 已触发`)
    await refreshAllPanels()
  } catch (error) {
    ElMessage.error(error.message || `${siteName} 触发失败`)
  } finally {
    setSiteRunning(siteName, false)
  }
}

async function toggleSite(siteName, enabled) {
  setSiteToggling(siteName, true)
  try {
    const response = await fetch(`/api/sites/${siteName}/enabled`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    })
    if (!response.ok) {
      throw new Error(`请求失败：${response.status}`)
    }
    const payload = await response.json()
    ElMessage.success(payload.message || `${siteName} 状态已更新`)
    await refreshAllPanels()
  } catch (error) {
    ElMessage.error(error.message || `${siteName} 状态更新失败`)
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
    if (!response.ok) {
      throw new Error(`请求失败：${response.status}`)
    }
    const payload = await response.json()
    ElMessage.success(`已触发 ${payload.count} 个站点`)
    await refreshAllPanels()
  } catch (error) {
    ElMessage.error(error.message || '批量触发失败')
  } finally {
    runningAllSites.value = false
  }
}

async function startContinuousRun() {
  continuousLoading.value = true
  try {
    const response = await fetch('/api/jobs/run-all-continuous/start', {
      method: 'POST',
    })
    if (!response.ok) {
      throw new Error(`请求失败：${response.status}`)
    }
    const payload = await response.json()
    ElMessage.success(payload.message || '已开始持久运行')
    await refreshAllPanels()
  } catch (error) {
    ElMessage.error(error.message || '启动持久运行失败')
  } finally {
    continuousLoading.value = false
  }
}

async function stopContinuousRun() {
  continuousLoading.value = true
  try {
    const response = await fetch('/api/jobs/run-all-continuous/stop', {
      method: 'POST',
    })
    if (!response.ok) {
      throw new Error(`请求失败：${response.status}`)
    }
    const payload = await response.json()
    ElMessage.success(payload.message || '已停止持久运行')
    await refreshAllPanels()
  } catch (error) {
    ElMessage.error(error.message || '停止持久运行失败')
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
    if (!response.ok) {
      throw new Error(`请求失败：${response.status}`)
    }
    const payload = await response.json()
    ElMessage.success(payload.message || '已触发漏洞同步')
    await refreshAllPanels()
  } catch (error) {
    ElMessage.error(error.message || '漏洞同步触发失败')
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
      body: JSON.stringify({ interval_seconds: vulnerabilityIntervalHours.value * 3600, limit: 300 }),
    })
    if (!response.ok) {
      throw new Error(`请求失败：${response.status}`)
    }
    const payload = await response.json()
    ElMessage.success(payload.message || '已开始漏洞自动同步')
    await refreshAllPanels()
  } catch (error) {
    ElMessage.error(error.message || '启动漏洞自动同步失败')
  } finally {
    vulnerabilityContinuousLoading.value = false
  }
}

async function stopVulnerabilitySync() {
  vulnerabilityContinuousLoading.value = true
  try {
    const response = await fetch('/api/vulnerabilities/sync/stop', {
      method: 'POST',
    })
    if (!response.ok) {
      throw new Error(`请求失败：${response.status}`)
    }
    const payload = await response.json()
    ElMessage.success(payload.message || '已停止漏洞自动同步')
    await refreshAllPanels()
  } catch (error) {
    ElMessage.error(error.message || '停止漏洞自动同步失败')
  } finally {
    vulnerabilityContinuousLoading.value = false
  }
}

onMounted(() => {
  pollTimer = window.setInterval(() => {
    refreshContinuous()
    refreshJobs()
  }, 12000)
})

onBeforeUnmount(() => {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped lang="scss">
.control-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(340px, 1fr);
  gap: 24px;
  margin-top: 22px;
  padding: 22px;
  border-radius: 22px;
  border: 1px solid var(--ti-border-default);
  background: rgba(255, 255, 255, 0.68);
}

.control-hero h3 {
  margin: 10px 0 8px;
  font-size: 28px;
  color: var(--ti-text-primary);
}

.control-hero p {
  color: var(--ti-text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

.control-hero__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.control-hero__stats div {
  padding: 16px;
  border-radius: 18px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.72);
}

.control-hero__stats span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.control-hero__stats strong {
  display: block;
  margin-top: 6px;
  color: var(--ti-text-primary);
  font-size: 24px;
}

.health-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.vulnerability-sync-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.vulnerability-sync-grid div {
  padding: 16px;
  border-radius: 18px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.72);
}

.vulnerability-sync-grid span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.vulnerability-sync-grid strong {
  display: block;
  margin-top: 6px;
  color: var(--ti-text-primary);
  font-size: 22px;
}

.vulnerability-sync-error {
  margin-top: 14px;
}

.row-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
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

.alert-stream__item--high {
  border-left: 4px solid var(--ti-warning-strong);
}

.alert-stream__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.alert-stream__item h3 {
  margin: 0 0 6px;
  color: var(--ti-text-primary);
}

.alert-stream__item p,
.alert-stream__source {
  color: var(--ti-text-secondary);
  line-height: 1.7;
}

.empty-state {
  padding: 20px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.7);
  color: var(--ti-text-secondary);
}

@media (max-width: 1100px) {
  .control-hero {
    grid-template-columns: 1fr;
  }

  .vulnerability-sync-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 767px) {
  .vulnerability-sync-grid {
    grid-template-columns: 1fr;
  }
}
</style>
