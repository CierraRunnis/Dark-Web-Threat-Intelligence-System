<template>
  <div class="data-migration-page ti-page">
    <section class="migration-hero ti-panel ti-reveal-up">
      <div class="migration-hero__head">
        <div>
          <span class="ti-kicker">Database Migration</span>
          <h2>数据库与证据镜像迁移</h2>
          <p>上传可信的 <code>.dwti</code> 全量迁移包，在独立 PostgreSQL Schema 中完成预检、导入和联合校验后再确认切换。</p>
        </div>
        <el-button :loading="loadingOverview" @click="loadOverview">
          <el-icon><Refresh /></el-icon>
          刷新状态
        </el-button>
      </div>

      <div class="migration-status-grid">
        <article class="migration-status-card">
          <div class="migration-status-card__label">
            <span>目标数据库</span>
            <i :class="targetConfigured ? 'is-success' : 'is-warning'"></i>
          </div>
          <strong>{{ targetConfigured ? 'PostgreSQL 已配置' : '尚未配置' }}</strong>
          <p v-if="targetConfigured" class="migration-mono">
            {{ target.host || '127.0.0.1' }}:{{ target.port || 5432 }}/{{ target.database || '-' }}
          </p>
          <p v-else>请先由服务端准备迁移目标，页面不会接收数据库口令。</p>
        </article>

        <article class="migration-status-card">
          <div class="migration-status-card__label">
            <span>当前活动版本</span>
            <i :class="activeRelease.active ? 'is-success' : 'is-neutral'"></i>
          </div>
          <strong>{{ activeRelease.active ? 'PostgreSQL' : 'SQLite' }}</strong>
          <p v-if="activeRelease.active" class="migration-mono">
            {{ activeRelease.database_schema || activeRelease.job_id || '-' }}
          </p>
          <p v-else>确认激活之前，现有 SQLite 与镜像目录保持不变。</p>
        </article>

        <article class="migration-status-card">
          <div class="migration-status-card__label">
            <span>切换策略</span>
            <i :class="config.auto_restart ? 'is-success' : 'is-warning'"></i>
          </div>
          <strong>{{ config.auto_restart ? '自动重启与回退' : '需要人工重启' }}</strong>
          <p>激活会短暂中断服务；新版本检查失败时将尝试恢复上一活动版本。</p>
        </article>
      </div>
    </section>

    <el-alert
      v-if="pageError"
      class="migration-alert"
      type="error"
      :title="pageError"
      :closable="true"
      show-icon
      @close="pageError = ''"
    />

    <section class="migration-workspace">
      <article class="ti-panel migration-upload-panel ti-reveal-up">
        <header class="migration-panel-head">
          <div>
            <span class="migration-step">1</span>
            <div>
              <h3>上传迁移包</h3>
              <p>浏览器以原始请求体流式上传，不使用 multipart 封装。</p>
            </div>
          </div>
          <el-tag effect="plain">{{ maxBundleLabel }}</el-tag>
        </header>

        <el-alert
          v-if="!targetConfigured"
          type="warning"
          title="目标 PostgreSQL 尚未配置，暂不能上传"
          :closable="false"
          show-icon
        />

        <div
          class="migration-drop-zone"
          :class="{
            'is-dragging': dragging,
            'is-disabled': !targetConfigured || uploadBusy,
            'has-file': selectedFile,
          }"
          role="button"
          tabindex="0"
          @click="openFilePicker"
          @keydown.enter.prevent="openFilePicker"
          @keydown.space.prevent="openFilePicker"
          @dragenter.prevent="dragging = true"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="handleDrop"
        >
          <input
            ref="fileInput"
            type="file"
            accept=".dwti,application/octet-stream"
            hidden
            @change="handleFileChange"
          />
          <el-icon class="migration-drop-zone__icon"><UploadFilled /></el-icon>
          <strong>{{ selectedFile?.name || '选择或拖入 .dwti 文件' }}</strong>
          <small v-if="selectedFile">{{ formatBytes(selectedFile.size) }}</small>
          <small v-else>只接受可信来源的 ZIP64 迁移包；上传后会自动开始安全预检。</small>
        </div>

        <div v-if="uploading" class="migration-upload-progress">
          <div>
            <span>正在流式上传 {{ selectedFile?.name }}</span>
            <strong>{{ formatBytes(selectedFile?.size || 0) }}</strong>
          </div>
          <el-progress :percentage="100" :show-text="false" :indeterminate="true" :duration="2" />
        </div>

        <div class="migration-upload-actions">
          <div>
            <p>上传前应停止旧系统 API、worker、scheduler 等写入进程。</p>
            <p v-if="blockingJob" class="migration-warning-text">
              当前任务 {{ jobIdShort(blockingJob) }} 仍在处理中，请等待结束。
            </p>
          </div>
          <div class="migration-button-row">
            <el-button v-if="selectedFile" :disabled="uploading" @click.stop="clearSelectedFile">清除</el-button>
            <el-button
              type="primary"
              :loading="uploading"
              :disabled="!canUpload"
              @click="startUpload"
            >
              上传并开始校验
            </el-button>
          </div>
        </div>

        <div class="migration-safety-notes">
          <p><el-icon><WarningFilled /></el-icon>这是完整版本替换，不会合并当前库中的新增记录。</p>
          <p><el-icon><Lock /></el-icon>平台会话需要在迁移后重新登录；校验和不代表迁移包发布者身份。</p>
        </div>
      </article>

      <article class="ti-panel migration-job-panel ti-reveal-up" v-loading="loadingJob">
        <header class="migration-panel-head">
          <div>
            <span class="migration-step">2</span>
            <div>
              <h3>任务状态</h3>
              <p v-if="currentJob">任务 {{ jobIdShort(currentJob) }}</p>
              <p v-else>上传迁移包后在此跟踪处理进度。</p>
            </div>
          </div>
          <el-tag v-if="currentJob" :type="currentStatus.type" effect="dark">
            {{ currentStatus.label }}
          </el-tag>
        </header>

        <template v-if="currentJob">
          <div class="migration-flow" aria-label="迁移任务阶段">
            <div
              v-for="step in flowSteps"
              :key="step"
              class="migration-flow__step"
              :class="flowStepClass(step)"
            >
              <i></i>
              <span>{{ statusMeta(step).label }}</span>
            </div>
          </div>

          <div class="migration-progress-card">
            <div>
              <strong>{{ currentStatus.label }}</strong>
              <span>{{ currentStatus.progress }}%</span>
            </div>
            <el-progress
              :percentage="currentStatus.progress"
              :status="progressStatus"
              :stroke-width="10"
              :show-text="false"
            />
            <p>{{ currentJob.message || currentStatus.description }}</p>
          </div>
          <section
            v-if="currentStatus.key === 'analyzing' || performanceResult"
            class="migration-performance-card"
          >
            <div class="migration-performance-card__head">
              <div>
                <strong>性能验证报告</strong>
                <p>提交后端生成或认可的 JSON 性能报告，完成迁移后的性能分析门禁。</p>
              </div>
              <el-tag :type="performanceResult ? 'success' : 'warning'" effect="plain">
                {{ performanceResult ? '已提交' : '待提交' }}
              </el-tag>
            </div>

            <template v-if="performanceResult">
              <pre>{{ formatJson(performanceResult) }}</pre>
            </template>
            <template v-else>
              <input
                ref="performanceFileInput"
                type="file"
                accept=".json,application/json"
                hidden
                @change="handlePerformanceFile"
              />
              <div class="migration-performance-card__actions">
                <div>
                  <strong>{{ performanceFile?.name || '请选择 JSON 性能报告' }}</strong>
                  <small v-if="performanceFile">{{ formatBytes(performanceFile.size) }}</small>
                </div>
                <el-button @click="performanceFileInput?.click()">选择 JSON</el-button>
                <el-button
                  type="primary"
                  :loading="performanceSubmitting"
                  :disabled="!performancePayload"
                  @click="submitPerformance"
                >
                  提交性能报告
                </el-button>
              </div>
              <p v-if="performanceError" class="migration-performance-card__error">{{ performanceError }}</p>
            </template>
          </section>

          <el-alert
            v-if="pollWarning"
            class="migration-inline-alert"
            type="warning"
            :title="pollWarning"
            :closable="false"
            show-icon
          />
          <el-alert
            v-if="currentFailure"
            class="migration-inline-alert"
            :type="currentStatus.key === 'rollback_failed' ? 'error' : 'warning'"
            :title="currentJob.message || currentStatus.description"
            :description="failureDescription"
            :closable="false"
            show-icon
          />
          <el-alert
            v-if="String(currentJob.status || '').toLowerCase() === 'restart_required'"
            class="migration-inline-alert"
            type="warning"
            title="活动版本已写入，但自动重启已关闭"
            description="请尽快使用项目启动脚本重启全部服务；重启前数据库与镜像视图可能不一致。"
            :closable="false"
            show-icon
          />

          <div class="migration-job-facts">
            <div><span>文件</span><strong>{{ currentJob.filename || 'upload.dwti' }}</strong></div>
            <div><span>包体</span><strong>{{ formatBytes(currentJob.bundle_bytes || 0) }}</strong></div>
            <div><span>阶段</span><strong>{{ currentJob.phase || currentStatus.key }}</strong></div>
            <div><span>更新时间</span><strong>{{ formatTime(jobTimestamp(currentJob)) }}</strong></div>
          </div>

          <div class="migration-activate-row">
            <p v-if="currentStatus.key === 'ready'">所有校验通过后，仍需人工确认才会写入活动版本并重启服务。</p>
            <p v-else>{{ currentStatus.description }}</p>
            <el-button
              v-if="currentStatus.key === 'ready'"
              type="danger"
              :loading="activating"
              @click="confirmActivate"
            >
              确认激活并切换
            </el-button>
          </div>
        </template>

        <el-empty v-else description="暂无迁移任务" />
      </article>
    </section>

    <section v-if="report" class="ti-panel migration-report ti-reveal-up">
      <header class="migration-panel-head">
        <div>
          <span class="migration-step">3</span>
          <div>
            <h3>导入与校验报告</h3>
            <p>以下数据来自后端完成导入后的只读报告。</p>
          </div>
        </div>
        <el-tag :type="currentStatus.type" effect="plain">{{ currentStatus.label }}</el-tag>
      </header>

      <div class="migration-report-metrics">
        <div><span>数据表</span><strong>{{ formatNumber(report.tables) }}</strong></div>
        <div><span>数据行</span><strong>{{ formatNumber(report.rows) }}</strong></div>
        <div><span>镜像文件</span><strong>{{ formatNumber(report.artifacts) }}</strong></div>
        <div><span>镜像体积</span><strong>{{ formatBytes(report.artifact_bytes) }}</strong></div>
      </div>

      <dl class="migration-report-details">
        <div>
          <dt>目标数据库</dt>
          <dd>{{ report.database_name || target.database || '-' }}</dd>
        </div>
        <div>
          <dt>独立 Schema</dt>
          <dd class="migration-mono">{{ report.database_schema || '-' }}</dd>
        </div>
        <div>
          <dt>新镜像根目录</dt>
          <dd class="migration-mono">{{ report.output_root || '-' }}</dd>
        </div>
        <div>
          <dt>Schema 指纹</dt>
          <dd class="migration-mono migration-break-all">{{ report.schema_fingerprint || '-' }}</dd>
        </div>
        <div>
          <dt>可移植路径</dt>
          <dd>{{ portablePathSummary }}</dd>
        </div>
        <div>
          <dt>校验完成</dt>
          <dd>{{ formatTime(report.verified_at) }}</dd>
        </div>
      </dl>
    </section>

    <section class="ti-panel migration-history ti-reveal-up">
      <header class="migration-panel-head">
        <div>
          <span class="migration-step migration-step--muted"><el-icon><Clock /></el-icon></span>
          <div>
            <h3>最近迁移任务</h3>
            <p>选择任务可查看完整状态、错误和导入报告。</p>
          </div>
        </div>
        <span class="migration-history__count">{{ jobs.length }} 条</span>
      </header>

      <el-table
        :data="jobs"
        empty-text="暂无迁移记录"
        row-key="job_id"
        highlight-current-row
        :current-row-key="currentJob?.job_id"
        @row-click="selectJob"
      >
        <el-table-column label="任务" min-width="210">
          <template #default="{ row }">
            <div class="migration-job-cell">
              <strong>{{ row.filename || 'migration.dwti' }}</strong>
              <span class="migration-mono">{{ jobIdShort(row) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="132">
          <template #default="{ row }">
            <el-tag :type="jobMeta(row).type" effect="plain">{{ jobMeta(row).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" min-width="180">
          <template #default="{ row }">
            <el-progress :percentage="jobMeta(row).progress" :show-text="false" :stroke-width="7" />
          </template>
        </el-table-column>
        <el-table-column prop="message" label="最近消息" min-width="300" show-overflow-tooltip />
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">{{ formatTime(jobTimestamp(row)) }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createDataMigrationApi,
  isMigrationPollingStatus,
  migrationStatusKey,
  migrationStatusMeta,
} from '@/composables/useDataMigrationApi'

const POLL_INTERVAL_MS = 1600
const flowSteps = ['queued', 'preflight', 'importing', 'verifying', 'analyzing', 'ready', 'activating', 'active']
const abortController = new AbortController()
const api = createDataMigrationApi({ signal: abortController.signal })

const config = ref({})
const jobs = ref([])
const currentJob = ref(null)
const selectedFile = ref(null)
const fileInput = ref(null)
const dragging = ref(false)
const loadingOverview = ref(false)
const loadingJob = ref(false)
const uploading = ref(false)
const activating = ref(false)
const pageError = ref('')
const pollWarning = ref('')
const performanceFileInput = ref(null)
const performanceFile = ref(null)
const performancePayload = ref(null)
const performanceSubmitting = ref(false)
const performanceError = ref('')

let pollTimer = null
let pollInFlight = false
let disposed = false

const target = computed(() => config.value?.target || {})
const activeRelease = computed(() => config.value?.active_release || {})
const targetConfigured = computed(() => Boolean(target.value?.configured))
const report = computed(() => currentJob.value?.report || null)
const performanceResult = computed(() => (
  currentJob.value?.performance_result
  || currentJob.value?.performance_report
  || currentJob.value?.performance
  || currentJob.value?.report?.performance
  || null
))
const currentStatus = computed(() => migrationStatusMeta(currentJob.value || 'queued'))
const currentFailure = computed(() => ['failed', 'rolled_back', 'rollback_failed'].includes(currentStatus.value.key))
const progressStatus = computed(() => (
  ['active'].includes(currentStatus.value.key)
    ? 'success'
    : ['failed', 'rollback_failed'].includes(currentStatus.value.key)
      ? 'exception'
      : undefined
))
const failureDescription = computed(() => {
  const type = currentJob.value?.error_type
  const fallback = currentStatus.value.description
  return type ? `${fallback}（错误类型：${type}）` : fallback
})
const blockingJob = computed(() => jobs.value.find((job) => isMigrationPollingStatus(job)) || null)
const uploadBusy = computed(() => uploading.value || Boolean(blockingJob.value))
const canUpload = computed(() => targetConfigured.value && selectedFile.value && !uploadBusy.value)
const maxBundleBytes = computed(() => Number(config.value?.max_bundle_bytes || 0))
const maxBundleLabel = computed(() => (
  maxBundleBytes.value > 0 ? `上限 ${formatBytes(maxBundleBytes.value)}` : '由服务端限制体积'
))
const portablePathSummary = computed(() => {
  const paths = report.value?.portable_artifact_paths
  const count = paths && typeof paths === 'object'
    ? Object.values(paths).reduce((sum, value) => sum + Number(value || 0), 0)
    : Number(paths || 0)
  const renamed = Number(report.value?.portable_path_renames || 0)
  return `${formatNumber(count)} 条路径，${formatNumber(renamed)} 个重命名`
})

function statusMeta(status) {
  return migrationStatusMeta(status)
}

function jobMeta(job) {
  return migrationStatusMeta(job)
}

function flowStepClass(step) {
  const currentKey = currentStatus.value.key
  const currentIndex = flowSteps.indexOf(currentKey)
  const index = flowSteps.indexOf(step)
  if (currentFailure.value) {
    const phaseIndex = flowSteps.indexOf(migrationStatusKey(currentJob.value?.phase || 'queued'))
    return {
      'is-complete': index < Math.max(phaseIndex, 0),
      'is-error': index === Math.max(phaseIndex, 0),
      'is-pending': index > Math.max(phaseIndex, 0),
    }
  }
  return {
    'is-complete': currentKey === 'active' ? index < currentIndex : index < currentIndex,
    'is-current': index === currentIndex,
    'is-pending': index > currentIndex,
  }
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const precision = index === 0 || bytes / (1024 ** index) >= 100 ? 0 : 1
  return `${(bytes / (1024 ** index)).toFixed(precision)} ${units[index]}`
}

function formatNumber(value) {
  const number = Number(value || 0)
  return Number.isFinite(number) ? new Intl.NumberFormat('zh-CN').format(number) : '-'
}

function formatTime(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(parsed)
}

function jobTimestamp(job) {
  return job?.updated_at || job?.finished_at || job?.verified_at || job?.created_at || ''
}

function jobIdShort(job) {
  const value = String(job?.job_id || '')
  return value ? value.slice(0, 12) : '-'
}

function upsertJob(job) {
  if (!job?.job_id) return
  const existing = jobs.value.find((item) => item.job_id === job.job_id) || {}
  const merged = { ...existing, ...job }
  jobs.value = [merged, ...jobs.value.filter((item) => item.job_id !== job.job_id)]
  if (currentJob.value?.job_id === job.job_id || !currentJob.value) {
    currentJob.value = { ...(currentJob.value || {}), ...merged }
  }
}

function clearPollTimer() {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = null
}

function schedulePoll() {
  clearPollTimer()
  if (disposed || !isMigrationPollingStatus(currentJob.value)) return
  pollTimer = window.setTimeout(pollCurrentJob, POLL_INTERVAL_MS)
}

async function pollCurrentJob() {
  if (disposed || pollInFlight || !currentJob.value?.job_id) return
  pollInFlight = true
  const previousStatus = currentStatus.value.key
  try {
    const updated = await api.getJob(currentJob.value.job_id)
    pollWarning.value = ''
    upsertJob(updated)
    const nextStatus = migrationStatusMeta(updated).key
    if (nextStatus !== previousStatus && ['ready', 'active', 'failed', 'rolled_back', 'rollback_failed'].includes(nextStatus)) {
      const [nextConfig, nextJobs] = await Promise.all([api.getConfig(), api.listJobs()])
      config.value = nextConfig || {}
      jobs.value = Array.isArray(nextJobs?.items) ? nextJobs.items : []
      upsertJob(updated)
    }
  } catch (error) {
    if (error?.name !== 'AbortError') {
      pollWarning.value = currentStatus.value.key === 'activating'
        ? '服务可能正在重启，页面会继续尝试恢复任务状态。'
        : (error.message || '暂时无法刷新任务状态，页面将自动重试。')
    }
  } finally {
    pollInFlight = false
    schedulePoll()
  }
}

async function loadOverview() {
  loadingOverview.value = true
  pageError.value = ''
  try {
    const [nextConfig, nextJobs] = await Promise.all([api.getConfig(), api.listJobs()])
    config.value = nextConfig || {}
    jobs.value = Array.isArray(nextJobs?.items) ? nextJobs.items : []
    const selectedId = currentJob.value?.job_id
    const summary = jobs.value.find((job) => job.job_id === selectedId) || jobs.value[0] || null
    currentJob.value = summary
    if (summary?.job_id) await refreshJob(summary.job_id, true)
  } catch (error) {
    if (error?.name !== 'AbortError') pageError.value = error.message || '加载迁移配置失败'
  } finally {
    loadingOverview.value = false
    schedulePoll()
  }
}

async function refreshJob(jobId, silent = false) {
  if (!jobId) return
  if (!silent) loadingJob.value = true
  try {
    const job = await api.getJob(jobId)
    upsertJob(job)
    pollWarning.value = ''
  } catch (error) {
    if (error?.name !== 'AbortError') {
      if (silent) pollWarning.value = error.message || '加载任务详情失败'
      else ElMessage.error(error.message || '加载任务详情失败')
    }
  } finally {
    if (!silent) loadingJob.value = false
    schedulePoll()
  }
}

async function selectJob(row) {
  if (!row?.job_id) return
  currentJob.value = row
  pollWarning.value = ''
  await refreshJob(row.job_id)
}

function openFilePicker() {
  if (!targetConfigured.value || uploadBusy.value) return
  fileInput.value?.click()
}

function chooseFile(file) {
  dragging.value = false
  if (!file) return
  if (!String(file.name || '').toLowerCase().endsWith('.dwti')) {
    ElMessage.error('请选择 .dwti 迁移包')
    return
  }
  if (maxBundleBytes.value > 0 && file.size > maxBundleBytes.value) {
    ElMessage.error(`迁移包超过服务端限制 ${formatBytes(maxBundleBytes.value)}`)
    return
  }
  selectedFile.value = file
}

function handleFileChange(event) {
  chooseFile(event.target.files?.[0])
  event.target.value = ''
}

function handleDrop(event) {
  dragging.value = false
  if (!targetConfigured.value || uploadBusy.value) return
  chooseFile(event.dataTransfer?.files?.[0])
}

function clearSelectedFile() {
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function startUpload() {
  if (!canUpload.value) return
  uploading.value = true
  pageError.value = ''
  try {
    const job = await api.uploadBundle(selectedFile.value)
    currentJob.value = job
    upsertJob(job)
    clearSelectedFile()
    ElMessage.success('迁移包已上传，后端正在执行安全预检')
    schedulePoll()
  } catch (error) {
    if (error?.name !== 'AbortError') {
      pageError.value = error.message || '上传迁移包失败'
      ElMessage.error(pageError.value)
    }
  } finally {
    uploading.value = false
  }
}

function formatJson(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

async function handlePerformanceFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  performanceError.value = ''
  performanceFile.value = null
  performancePayload.value = null
  if (!file) return
  if (!String(file.name || '').toLowerCase().endsWith('.json')) {
    performanceError.value = '请选择 JSON 性能报告'
    return
  }
  try {
    const payload = JSON.parse(await file.text())
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new Error('性能报告根节点必须是 JSON 对象')
    }
    performanceFile.value = file
    performancePayload.value = payload
  } catch (error) {
    performanceError.value = error.message || '性能报告不是有效 JSON'
  }
}

async function submitPerformance() {
  if (!currentJob.value?.job_id || !performancePayload.value || performanceSubmitting.value) return
  performanceSubmitting.value = true
  performanceError.value = ''
  try {
    const result = await api.submitPerformance(currentJob.value.job_id, performancePayload.value)
    const updated = result?.job || result
    if (updated && typeof updated === 'object' && (updated.status || updated.job_id)) {
      upsertJob({ ...currentJob.value, ...updated, job_id: currentJob.value.job_id })
    } else {
      currentJob.value = { ...currentJob.value, performance_result: result }
      upsertJob(currentJob.value)
    }
    performanceFile.value = null
    performancePayload.value = null
    ElMessage.success('性能报告已提交')
    schedulePoll()
  } catch (error) {
    if (error?.name !== 'AbortError') {
      performanceError.value = error.message || '提交性能报告失败'
    }
  } finally {
    performanceSubmitting.value = false
  }
}
async function confirmActivate() {
  if (!currentJob.value?.job_id || currentStatus.value.key !== 'ready') return
  const schema = report.value?.database_schema || '新的 PostgreSQL Schema'
  try {
    await ElMessageBox.confirm(
      `确定激活 ${schema}？服务会短暂重启；如果新数据库已产生写入，后续回退不会合并这些写入。`,
      '确认切换活动版本',
      {
        type: 'warning',
        confirmButtonText: '确认激活',
        cancelButtonText: '暂不切换',
        distinguishCancelAndClose: true,
      },
    )
  } catch {
    return
  }

  activating.value = true
  pageError.value = ''
  try {
    const job = await api.activate(currentJob.value.job_id)
    upsertJob(job)
    if (String(job.status || '').toLowerCase() === 'restart_required') {
      ElMessage.warning('活动版本已写入，请手工重启全部服务')
    } else {
      ElMessage.success('激活已开始，服务重启期间页面会自动重试')
    }
    schedulePoll()
  } catch (error) {
    if (error?.name !== 'AbortError') {
      pageError.value = error.message || '激活迁移版本失败'
      ElMessage.error(pageError.value)
    }
  } finally {
    activating.value = false
  }
}

onMounted(loadOverview)

onBeforeUnmount(() => {
  disposed = true
  clearPollTimer()
  abortController.abort()
})
</script>

<style scoped lang="scss">
.data-migration-page {
  display: grid;
  gap: 20px;
  color: var(--ti-text-primary);
}

.migration-hero,
.migration-upload-panel,
.migration-job-panel,
.migration-report,
.migration-history {
  padding: 24px;
}

.migration-hero__head,
.migration-panel-head,
.migration-upload-actions,
.migration-activate-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.migration-hero__head h2 {
  margin: 8px 0;
  font-size: clamp(26px, 3vw, 36px);
}

.migration-hero__head p,
.migration-panel-head p,
.migration-upload-actions p,
.migration-activate-row p {
  margin: 0;
  color: var(--ti-text-secondary);
  line-height: 1.65;
}

.migration-hero code,
.migration-mono {
  font-family: var(--ti-font-mono, "SFMono-Regular", Consolas, monospace);
}

.migration-status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-top: 22px;
}

.migration-status-card {
  min-width: 0;
  padding: 17px;
  border: 1px solid var(--ti-border-soft);
  border-radius: 16px;
  background: rgba(247, 250, 255, 0.72);
}

.migration-status-card__label {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--ti-text-muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.migration-status-card__label i {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: var(--ti-text-muted);
}

.migration-status-card__label i.is-success { background: var(--ti-success-strong); }
.migration-status-card__label i.is-warning { background: var(--ti-warning-strong); }
.migration-status-card__label i.is-neutral { background: var(--ti-border-strong); }

.migration-status-card strong {
  display: block;
  margin-top: 13px;
  font-size: 18px;
}

.migration-status-card p {
  min-height: 42px;
  margin: 8px 0 0;
  overflow-wrap: anywhere;
  color: var(--ti-text-secondary);
  font-size: 13px;
  line-height: 1.55;
}

.migration-alert,
.migration-inline-alert {
  border-radius: 14px;
}

.migration-workspace {
  display: grid;
  grid-template-columns: minmax(0, 0.92fr) minmax(420px, 1.08fr);
  gap: 20px;
  align-items: start;
}

.migration-panel-head > div:first-child {
  display: flex;
  align-items: center;
  gap: 13px;
}

.migration-panel-head h3 {
  margin: 0 0 4px;
  font-size: 20px;
}

.migration-step {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: var(--ti-primary);
  color: #fff;
  font-weight: 800;
}

.migration-step--muted {
  background: rgba(45, 93, 255, 0.1);
  color: var(--ti-primary);
}

.migration-upload-panel .el-alert {
  margin-top: 18px;
}

.migration-drop-zone {
  display: grid;
  place-items: center;
  min-height: 210px;
  margin-top: 18px;
  padding: 26px;
  border: 1.5px dashed var(--ti-border-strong);
  border-radius: 18px;
  background: linear-gradient(145deg, rgba(45, 93, 255, 0.035), rgba(247, 250, 255, 0.9));
  text-align: center;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, transform 0.18s ease;
}

.migration-drop-zone:hover,
.migration-drop-zone:focus-visible,
.migration-drop-zone.is-dragging {
  border-color: var(--ti-primary);
  background: rgba(45, 93, 255, 0.07);
  outline: none;
  transform: translateY(-1px);
}

.migration-drop-zone.is-disabled {
  cursor: not-allowed;
  opacity: 0.58;
  transform: none;
}

.migration-drop-zone.has-file {
  border-style: solid;
  border-color: rgba(31, 157, 104, 0.48);
  background: rgba(31, 157, 104, 0.055);
}

.migration-drop-zone__icon {
  margin-bottom: 13px;
  color: var(--ti-primary);
  font-size: 44px;
}

.migration-drop-zone strong {
  max-width: 100%;
  overflow-wrap: anywhere;
  font-size: 17px;
}

.migration-drop-zone small {
  max-width: 480px;
  margin-top: 8px;
  color: var(--ti-text-muted);
  line-height: 1.6;
}

.migration-upload-progress {
  margin-top: 16px;
  padding: 14px;
  border-radius: 14px;
  background: rgba(45, 93, 255, 0.05);
}

.migration-upload-progress > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  font-size: 13px;
}

.migration-upload-actions {
  margin-top: 18px;
}

.migration-upload-actions p + p {
  margin-top: 5px;
}

.migration-button-row {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
}

.migration-warning-text {
  color: var(--ti-warning-strong) !important;
}

.migration-safety-notes {
  display: grid;
  gap: 8px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--ti-border-soft);
}

.migration-safety-notes p {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0;
  color: var(--ti-text-muted);
  font-size: 12px;
  line-height: 1.55;
}

.migration-flow {
  display: grid;
  grid-template-columns: repeat(8, minmax(54px, 1fr));
  gap: 0;
  margin: 24px 0 20px;
  overflow-x: auto;
  padding-bottom: 8px;
}

.migration-flow__step {
  position: relative;
  display: grid;
  justify-items: center;
  min-width: 66px;
  gap: 7px;
  color: var(--ti-text-muted);
  font-size: 11px;
  text-align: center;
}

.migration-flow__step::before {
  position: absolute;
  top: 6px;
  left: 0;
  right: 50%;
  height: 2px;
  background: var(--ti-border-soft);
  content: "";
}

.migration-flow__step::after {
  position: absolute;
  top: 6px;
  left: 50%;
  right: 0;
  height: 2px;
  background: var(--ti-border-soft);
  content: "";
}

.migration-flow__step:first-child::before,
.migration-flow__step:last-child::after {
  display: none;
}

.migration-flow__step i {
  position: relative;
  z-index: 1;
  width: 14px;
  height: 14px;
  border: 3px solid #fff;
  border-radius: 999px;
  background: var(--ti-border-strong);
  box-shadow: 0 0 0 1px var(--ti-border-soft);
}

.migration-flow__step.is-complete::before,
.migration-flow__step.is-complete::after,
.migration-flow__step.is-current::before {
  background: var(--ti-success-strong);
}

.migration-flow__step.is-complete i {
  background: var(--ti-success-strong);
}

.migration-flow__step.is-current {
  color: var(--ti-primary);
  font-weight: 700;
}

.migration-flow__step.is-current i {
  background: var(--ti-primary);
  box-shadow: 0 0 0 3px rgba(45, 93, 255, 0.15);
}

.migration-flow__step.is-error {
  color: var(--ti-danger-strong);
  font-weight: 700;
}

.migration-flow__step.is-error i {
  background: var(--ti-danger-strong);
}

.migration-progress-card {
  padding: 17px;
  border: 1px solid var(--ti-border-soft);
  border-radius: 16px;
  background: rgba(247, 250, 255, 0.76);
}

.migration-progress-card > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 11px;
}

.migration-progress-card p {
  margin: 10px 0 0;
  color: var(--ti-text-secondary);
  font-size: 13px;
  line-height: 1.55;
}

.migration-performance-card {
  margin-top: 14px;
  padding: 15px;
  border: 1px solid rgba(45, 93, 255, 0.2);
  border-radius: 14px;
  background: rgba(45, 93, 255, 0.04);
}

.migration-performance-card__head,
.migration-performance-card__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.migration-performance-card__head p {
  margin: 4px 0 0;
  color: var(--ti-text-secondary);
  font-size: 12px;
}

.migration-performance-card__actions {
  margin-top: 14px;
}

.migration-performance-card__actions > div {
  display: grid;
  min-width: 0;
  margin-right: auto;
}

.migration-performance-card__actions small {
  color: var(--ti-text-muted);
}

.migration-performance-card pre {
  max-height: 220px;
  margin: 12px 0 0;
  padding: 12px;
  overflow: auto;
  border-radius: 10px;
  background: #111827;
  color: #dbeafe;
  font: 12px/1.55 var(--ti-font-mono, Consolas, monospace);
}

.migration-performance-card__error {
  margin: 10px 0 0;
  color: var(--ti-danger-strong);
  font-size: 12px;
}
.migration-inline-alert {
  margin-top: 14px;
}

.migration-job-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.migration-job-facts > div {
  min-width: 0;
  padding: 12px;
  border-radius: 12px;
  background: rgba(247, 250, 255, 0.7);
}

.migration-job-facts span,
.migration-report-metrics span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 11px;
  text-transform: uppercase;
}

.migration-job-facts strong {
  display: block;
  margin-top: 6px;
  overflow-wrap: anywhere;
  font-size: 13px;
}

.migration-activate-row {
  align-items: center;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--ti-border-soft);
}

.migration-report-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 20px;
}

.migration-report-metrics > div {
  padding: 16px;
  border: 1px solid var(--ti-border-soft);
  border-radius: 14px;
  background: rgba(247, 250, 255, 0.72);
}

.migration-report-metrics strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
}

.migration-report-details {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 18px 0 0;
  border: 1px solid var(--ti-border-soft);
  border-radius: 14px;
  overflow: hidden;
}

.migration-report-details > div {
  min-width: 0;
  padding: 14px 16px;
  border-bottom: 1px solid var(--ti-border-soft);
}

.migration-report-details > div:nth-child(odd) {
  border-right: 1px solid var(--ti-border-soft);
}

.migration-report-details > div:nth-last-child(-n + 2) {
  border-bottom: 0;
}

.migration-report-details dt {
  color: var(--ti-text-muted);
  font-size: 12px;
}

.migration-report-details dd {
  margin: 6px 0 0;
  overflow-wrap: anywhere;
  font-weight: 650;
}

.migration-break-all {
  word-break: break-all;
}

.migration-history__count {
  color: var(--ti-text-muted);
  font-size: 13px;
}

.migration-history :deep(.el-table) {
  margin-top: 18px;
  cursor: pointer;
}

.migration-job-cell {
  display: grid;
  gap: 4px;
}

.migration-job-cell span {
  color: var(--ti-text-muted);
  font-size: 11px;
}

@media (max-width: 1120px) {
  .migration-workspace {
    grid-template-columns: 1fr;
  }

  .migration-status-grid,
  .migration-report-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .migration-hero,
  .migration-upload-panel,
  .migration-job-panel,
  .migration-report,
  .migration-history {
    padding: 18px;
  }

  .migration-hero__head,
  .migration-panel-head,
  .migration-upload-actions,
  .migration-activate-row {
    flex-direction: column;
  }

  .migration-status-grid,
  .migration-report-metrics,
  .migration-job-facts,
  .migration-report-details {
    grid-template-columns: 1fr;
  }

  .migration-report-details > div,
  .migration-report-details > div:nth-child(odd),
  .migration-report-details > div:nth-last-child(-n + 2) {
    border-right: 0;
    border-bottom: 1px solid var(--ti-border-soft);
  }

  .migration-report-details > div:last-child {
    border-bottom: 0;
  }

  .migration-button-row {
    width: 100%;
  }

  .migration-button-row .el-button {
    flex: 1;
  }
}
</style>
