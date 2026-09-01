<template>
  <a class="skip-link" href="#content">跳到主要内容</a>
  <div class="app-shell sidebar-collapsed migration-shell" @click="handleNavigation">
    <aside class="app-sidebar" data-od-id="data-migration-sidebar">
      <a class="brand" href="/">
        <span class="brand-mark" aria-hidden="true"><img src="/assets/xuanjian-mark.svg?v=8" alt="" /></span>
        <span class="brand-copy"><strong>玄鉴</strong><span>XUANJIAN INTELLIGENCE</span></span>
      </a>
      <nav class="sidebar-nav" aria-label="主导航"></nav>
      <div class="sidebar-footer"></div>
    </aside>
    <button class="sidebar-backdrop" data-sidebar-toggle aria-label="关闭导航"></button>

    <div class="app-stage">
      <header class="app-header" data-od-id="data-migration-header">
        <button class="btn btn-secondary icon-btn menu-button" type="button" data-sidebar-toggle aria-label="打开导航">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
        </button>
        <div class="migration-breadcrumbs">
          <router-link to="/settings">配置中心</router-link>
          <span>/</span>
          <strong>数据迁移</strong>
        </div>
        <div class="header-actions">
          <span class="app-version">版本 <strong>v20260901</strong></span>
          <button class="avatar" type="button" aria-label="个人账户"></button>
        </div>
      </header>

      <main class="app-main migration-main" id="content">
        <section class="page-titlebar migration-titlebar">
          <div>
            <span class="migration-kicker">DATABASE MIGRATION</span>
            <h1>数据迁移</h1>
            <p class="lead">导入数据库与镜像文件一体化迁移包，完成联合校验后再切换活动版本。</p>
          </div>
          <div class="page-actions">
            <button class="btn btn-secondary" type="button" :disabled="loading" @click="loadAll">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" /></svg>
              {{ loading ? '正在刷新' : '刷新状态' }}
            </button>
          </div>
        </section>

        <section class="migration-status-grid" aria-label="迁移环境状态">
          <article class="card migration-status-card">
            <div class="migration-status-head"><span>目标数据库</span><i :class="config.target?.configured ? 'is-ok' : 'is-warning'"></i></div>
            <strong :class="config.target?.configured ? 'migration-state-ok' : 'migration-state-warning'">
              {{ config.target?.configured ? 'PostgreSQL 已配置' : '尚未配置' }}
            </strong>
            <p v-if="config.target?.configured" class="num">
              {{ config.target.host }}:{{ config.target.port }}/{{ config.target.database }}
            </p>
            <p v-else>首次启动会自动准备本机 PostgreSQL，也可在服务端设置迁移目标。</p>
          </article>
          <article class="card migration-status-card">
            <div class="migration-status-head"><span>当前活动数据库</span><i :class="config.active_release?.active ? 'is-ok' : 'is-info'"></i></div>
            <strong>{{ activeDatabaseLabel }}</strong>
            <p v-if="config.active_release?.active" class="num">批次 {{ config.active_release.job_id }}</p>
            <p v-else>项目仍使用原 SQLite，确认切换前不会改变。</p>
          </article>
          <article class="card migration-status-card">
            <div class="migration-status-head"><span>切换策略</span><i :class="config.auto_restart ? 'is-ok' : 'is-warning'"></i></div>
            <strong>{{ config.auto_restart ? '自动重启已启用' : '需要手工重启' }}</strong>
            <p>上一活动版本会被保留，用于启动失败时受控回退。</p>
          </article>
          <article class="card migration-status-card">
            <div class="migration-status-head"><span>数据存储</span><i :class="storageNeedsAttention ? 'is-warning' : 'is-ok'"></i></div>
            <strong :title="config.storage?.data_root || ''">{{ config.storage?.custom ? '自定义数据盘' : '默认数据目录' }}</strong>
            <p class="migration-storage-path" :title="config.storage?.data_root || ''">{{ config.storage?.data_root || '正在读取…' }}</p>
            <p v-if="config.storage?.disk_free_bytes">
              可用 {{ formatBytes(config.storage.disk_free_bytes) }}{{ storageNeedsAttention ? ' · 部分数据仍在其他目录' : ' · 迁移目录已跟随数据盘' }}
            </p>
          </article>
        </section>

        <section class="settings-surface migration-panel">
          <header class="settings-surface-head">
            <div class="settings-heading">
              <span class="migration-step">1</span>
              <div><h2>选择 .dwti 迁移包</h2><p>上传前确认已暂停旧系统写入，并使用外部工具完成离线打包。</p></div>
            </div>
            <span class="badge migration-limit">最大 {{ formatBytes(config.max_bundle_bytes || 0) }}</span>
          </header>
          <div class="migration-panel-body">
            <label class="migration-drop-zone" :class="{ disabled: !config.target?.configured || uploading }">
              <input
                type="file"
                accept=".dwti"
                :disabled="!config.target?.configured || uploading"
                @change="selectFile"
              />
              <span class="migration-upload-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M12 16V4m0 0L7 9m5-5 5 5M5 14v5h14v-5" /></svg>
              </span>
              <strong>{{ selectedFile?.name || '点击选择迁移包' }}</strong>
              <small v-if="selectedFile">{{ formatBytes(selectedFile.size) }}</small>
              <small v-else>支持 ZIP64；数据库、表清单和镜像文件会在后台逐项校验</small>
            </label>

            <div v-if="uploading || uploadProgress" class="migration-progress">
              <div><span>上传进度</span><strong class="num">{{ uploadProgress }}%</strong></div>
              <div class="migration-progress-track"><i :style="{ width: uploadProgress + '%' }"></i></div>
            </div>
            <div class="migration-panel-actions">
              <p>平台会话、Cookie、令牌及凭据文件不会进入迁移包。</p>
              <button
                class="btn btn-primary"
                type="button"
                :disabled="!selectedFile || uploading || !config.target?.configured"
                @click="uploadBundle"
              >
                {{ uploading ? '正在上传…' : '上传并开始校验' }}
              </button>
            </div>
          </div>
        </section>

        <section v-if="currentJob" class="settings-surface migration-panel">
          <header class="settings-surface-head">
            <div class="settings-heading">
              <span class="migration-step">2</span>
              <div><h2>预检、导入与联合校验</h2><p>{{ currentJob.message }}</p></div>
            </div>
            <span class="badge migration-job-status" :class="currentJob.status">{{ statusLabel(currentJob.status) }}</span>
          </header>
          <div class="migration-panel-body">
            <div class="migration-progress">
              <div><span>{{ phaseLabel(currentJob.phase) }}</span><strong class="num">{{ currentJob.progress || 0 }}%</strong></div>
              <div class="migration-progress-track"><i :style="{ width: (currentJob.progress || 0) + '%' }"></i></div>
            </div>
            <div v-if="currentJob.report" class="migration-result-grid">
              <div><span>数据库表</span><strong class="num">{{ currentJob.report.tables }}</strong></div>
              <div><span>数据行</span><strong class="num">{{ number(currentJob.report.rows) }}</strong></div>
              <div><span>镜像文件</span><strong class="num">{{ number(currentJob.report.artifacts) }}</strong></div>
              <div><span>镜像大小</span><strong class="num">{{ formatBytes(currentJob.report.artifact_bytes) }}</strong></div>
              <div><span>目标 Schema</span><strong class="num">{{ currentJob.report.database_schema }}</strong></div>
              <div><span>校验结果</span><strong class="migration-state-ok">全部一致</strong></div>
            </div>
            <div v-if="currentJob.status === 'failed'" class="migration-error" role="alert">{{ currentJob.message }}</div>
          </div>
        </section>

        <section v-if="currentJob?.status === 'ready'" class="settings-surface migration-panel migration-danger-panel">
          <header class="settings-surface-head">
            <div class="settings-heading">
              <span class="migration-step is-danger">3</span>
              <div><h2>确认切换</h2><p>系统将进入短暂维护窗口，并重启到新的 PostgreSQL Schema 与镜像目录。</p></div>
            </div>
            <span class="badge migration-switch-badge">高风险操作</span>
          </header>
          <div class="migration-panel-body">
            <label class="migration-confirm-line">
              <input v-model="confirmed" type="checkbox" />
              <span><strong>确认使用当前迁移包切换活动版本</strong><small>我已确认这是最终数据版本，并接受切换期间短暂停机。</small></span>
            </label>
            <div class="migration-panel-actions">
              <p>PostgreSQL 产生新写入后，不能直接丢弃新数据回退至旧 SQLite。</p>
              <button class="btn btn-danger" type="button" :disabled="!confirmed || activating" @click="activate">
                {{ activating ? '正在切换…' : '确认切换并重启' }}
              </button>
            </div>
          </div>
        </section>

        <section v-if="notice" class="migration-notice" :class="noticeType" role="status">{{ notice }}</section>

        <section v-if="jobs.length" class="settings-surface migration-history">
          <header class="settings-surface-head">
            <div class="settings-heading">
              <span class="settings-section-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M4 7h16v12H4zM8 4h8v3M8 11h8M8 15h5" /></svg>
              </span>
              <div><h2>最近迁移任务</h2><p>保留最近 20 个迁移批次的处理状态</p></div>
            </div>
          </header>
          <div class="migration-history-list">
            <button v-for="job in jobs" :key="job.job_id" type="button" class="migration-history-row" @click="chooseJob(job)">
              <span><strong>{{ job.filename }}</strong><small class="num">{{ job.job_id }}</small></span>
              <span class="badge migration-job-status" :class="job.status">{{ statusLabel(job.status) }}</span>
            </button>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getAuthToken } from '@/composables/useAuth'
import { initializePrototype } from '@/prototype/runtime'

const router = useRouter()
const config = ref({ target: { configured: false }, active_release: {} })
const jobs = ref([])
const currentJob = ref(null)
const selectedFile = ref(null)
const uploading = ref(false)
const uploadProgress = ref(0)
const loading = ref(false)
const confirmed = ref(false)
const activating = ref(false)
const notice = ref('')
const noticeType = ref('info')
let pollTimer = null
let previousBodyClassName = ''

const activeDatabaseLabel = computed(() => {
  const active = config.value.active_release
  return active?.active && active.database_engine === 'postgresql' ? 'PostgreSQL' : 'SQLite'
})

const storageNeedsAttention = computed(() => {
  const storage = config.value.storage || {}
  return storage.migration_on_data_root === false
    || storage.application_on_data_root === false
    || Boolean(storage.active_application_root && !storage.active_application_on_data_root)
    || storage.playwright_on_data_root === false
    || Boolean(storage.postgresql_data_directory && !storage.postgresql_on_data_root)
    || storage.collector_database_on_data_root === false
    || storage.collector_output_on_data_root === false
    || storage.garnet_on_data_root === false
})

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** index).toFixed(index ? 2 : 0)} ${units[index]}`
}

function number(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

function statusLabel(status) {
  return {
    queued: '等待处理', preparing: '处理中', ready: '等待切换', activating: '正在切换',
    restart_required: '等待重启', active: '已生效', failed: '失败', rolled_back: '已回退',
    rollback_failed: '回退失败',
  }[status] || status || '未知'
}

function phaseLabel(phase) {
  return {
    queued: '等待预检', snapshot: '数据库快照', preflight: '安全预检', artifacts: '镜像文件',
    database: '数据库导入', verify: '联合校验', ready: '校验完成', activate: '系统切换',
    complete: '迁移完成', failed: '处理失败',
  }[phase] || phase || '处理中'
}

async function readError(response) {
  try {
    const payload = await response.json()
    return payload.detail || payload.message || '请求失败'
  } catch {
    return '请求失败'
  }
}

async function loadConfig() {
  const response = await fetch('/api/migrations/config', { cache: 'no-store' })
  if (!response.ok) throw new Error(await readError(response))
  config.value = await response.json()
}

async function loadJobs() {
  const response = await fetch('/api/migrations', { cache: 'no-store' })
  if (!response.ok) throw new Error(await readError(response))
  jobs.value = (await response.json()).items || []
  if (!currentJob.value && jobs.value.length) currentJob.value = jobs.value[0]
}

async function loadAll() {
  loading.value = true
  notice.value = ''
  try {
    await Promise.all([loadConfig(), loadJobs()])
    if (currentJob.value) await refreshJob()
  } catch (error) {
    notice.value = error.message
    noticeType.value = 'error'
  } finally {
    loading.value = false
  }
}

function selectFile(event) {
  selectedFile.value = event.target.files?.[0] || null
  uploadProgress.value = 0
  notice.value = ''
}

function uploadBundle() {
  if (!selectedFile.value || uploading.value) return
  uploading.value = true
  uploadProgress.value = 0
  notice.value = ''
  const xhr = new XMLHttpRequest()
  xhr.open('POST', '/api/migrations/upload')
  xhr.setRequestHeader('Authorization', `Bearer ${getAuthToken()}`)
  xhr.setRequestHeader('Content-Type', 'application/octet-stream')
  xhr.setRequestHeader('X-DWTI-Filename', encodeURIComponent(selectedFile.value.name))
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) uploadProgress.value = Math.round((event.loaded / event.total) * 100)
  }
  xhr.onload = () => {
    uploading.value = false
    if (xhr.status < 200 || xhr.status >= 300) {
      try { notice.value = JSON.parse(xhr.responseText).detail || '上传失败' } catch { notice.value = '上传失败' }
      noticeType.value = 'error'
      return
    }
    currentJob.value = JSON.parse(xhr.responseText)
    notice.value = '迁移包已上传，系统正在后台预检和导入。'
    noticeType.value = 'info'
    startPolling()
  }
  xhr.onerror = () => {
    uploading.value = false
    notice.value = '上传连接失败'
    noticeType.value = 'error'
  }
  xhr.send(selectedFile.value)
}

async function refreshJob() {
  if (!currentJob.value?.job_id) return
  const response = await fetch(`/api/migrations/${currentJob.value.job_id}`, { cache: 'no-store' })
  if (!response.ok) throw new Error(await readError(response))
  currentJob.value = await response.json()
  if (!['queued', 'preparing', 'activating'].includes(currentJob.value.status)) stopPolling()
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    try {
      await refreshJob()
      await loadJobs()
      if (currentJob.value?.status === 'active') await loadConfig()
    } catch {
      if (currentJob.value?.status === 'activating') {
        notice.value = '系统正在重启，页面连接暂时中断；服务恢复后刷新即可。'
        noticeType.value = 'info'
      }
    }
  }, 1200)
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = null
}

function chooseJob(job) {
  currentJob.value = job
  confirmed.value = false
  if (['queued', 'preparing', 'activating'].includes(job.status)) startPolling()
}

async function activate() {
  if (!confirmed.value || !currentJob.value) return
  activating.value = true
  try {
    const response = await fetch(`/api/migrations/${currentJob.value.job_id}/activate`, { method: 'POST' })
    if (!response.ok) throw new Error(await readError(response))
    currentJob.value = await response.json()
    notice.value = currentJob.value.message
    noticeType.value = 'info'
    startPolling()
  } catch (error) {
    notice.value = error.message
    noticeType.value = 'error'
  } finally {
    activating.value = false
  }
}

function handleNavigation(event) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  const link = event.target.closest('a[href]')
  if (!link || link.target === '_blank' || link.hasAttribute('download')) return
  const url = new URL(link.href, window.location.href)
  if (url.origin !== window.location.origin) return
  event.preventDefault()
  router.push(`${url.pathname}${url.search}${url.hash}`)
}

onMounted(async () => {
  document.title = '数据迁移 · 玄鉴'
  previousBodyClassName = document.body.className
  document.body.className = 'page-data-migration'
  document.body.dataset.prototypePage = 'data-migration.html'
  await nextTick()
  initializePrototype()
  await loadAll()
})

onBeforeUnmount(() => {
  stopPolling()
  if (document.body.classList.contains('page-data-migration')) document.body.className = previousBodyClassName
  delete document.body.dataset.prototypePage
})
</script>

<style scoped>
.migration-main {
  width: min(100%, 1580px);
  min-width: 0;
  margin-inline: auto;
}

.migration-breadcrumbs {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 12px;
}

.migration-breadcrumbs a:hover { color: var(--accent); }
.migration-breadcrumbs strong { color: var(--fg); }

.migration-titlebar {
  min-height: 64px;
  align-items: center;
  margin-bottom: 8px;
}

.migration-titlebar h1 { font-size: 24px; }

.migration-titlebar .lead {
  display: block;
  margin-top: 5px;
  max-width: 76ch;
  font-size: 12px;
}

.migration-kicker {
  display: block;
  margin-bottom: 3px;
  color: var(--accent);
  font: 700 9px var(--font-mono);
  letter-spacing: .14em;
}

.migration-titlebar .btn svg {
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.migration-status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.migration-status-card {
  min-width: 0;
  min-height: 112px;
  display: grid;
  align-content: start;
  gap: 8px;
  padding: 14px;
}

.migration-status-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--muted);
  font-size: 11px;
}

.migration-status-head i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--muted);
}

.migration-status-head i.is-ok { background: var(--success); }
.migration-status-head i.is-warning { background: var(--warning); }
.migration-status-head i.is-info { background: var(--accent); }

.migration-status-card > strong {
  overflow-wrap: anywhere;
  font-size: 16px;
}

.migration-status-card p {
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--muted);
  font-size: 11px;
}

.migration-storage-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.migration-state-ok { color: var(--success) !important; }
.migration-state-warning { color: #a66b00 !important; }

.migration-panel,
.migration-history {
  margin-top: 10px;
}

.migration-panel :deep(.settings-surface-head),
.migration-history :deep(.settings-surface-head) {
  min-height: 62px;
}

.migration-step {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  display: grid;
  place-items: center;
  border: 1px solid var(--settings-line);
  border-radius: 8px;
  background: var(--settings-tint-strong);
  color: var(--accent);
  font: 700 12px var(--font-mono);
}

.migration-step.is-danger {
  border-color: color-mix(in oklch, var(--danger) 32%, var(--border));
  background: var(--danger-soft);
  color: var(--danger);
}

.migration-limit,
.migration-job-status,
.migration-switch-badge {
  flex: 0 0 auto;
}

.migration-job-status.ready,
.migration-job-status.active {
  color: var(--success);
}

.migration-job-status.preparing,
.migration-job-status.queued,
.migration-job-status.activating {
  color: var(--accent);
}

.migration-job-status.failed,
.migration-job-status.rollback_failed,
.migration-switch-badge {
  color: var(--danger);
}

.migration-panel-body {
  padding: 14px;
}

.migration-drop-zone {
  min-height: 164px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 7px;
  padding: 22px;
  border: 1px dashed color-mix(in oklch, var(--accent) 50%, var(--border));
  border-radius: 6px;
  background: color-mix(in oklch, var(--settings-tint) 72%, var(--surface));
  text-align: center;
  cursor: pointer;
  transition: border-color .16s ease, background .16s ease;
}

.migration-drop-zone:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.migration-drop-zone.disabled {
  opacity: .52;
  cursor: not-allowed;
}

.migration-drop-zone input { display: none; }

.migration-drop-zone strong {
  max-width: 100%;
  overflow-wrap: anywhere;
  font-size: 13px;
}

.migration-drop-zone small {
  color: var(--muted);
  font-size: 11px;
}

.migration-upload-icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border: 1px solid var(--settings-line);
  border-radius: 50%;
  background: var(--surface);
  color: var(--accent);
}

.migration-upload-icon svg,
.migration-history .settings-section-icon svg {
  width: 19px;
  height: 19px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.migration-progress {
  margin: 14px 0 0;
}

.migration-progress > div:first-child {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 7px;
  color: var(--muted);
  font-size: 11px;
}

.migration-progress > div:first-child strong { color: var(--fg); }

.migration-progress-track {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--border);
}

.migration-progress-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent), var(--secondary));
  transition: width .2s ease;
}

.migration-panel-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.migration-panel-actions p {
  margin: 0;
  color: var(--muted);
  font-size: 11px;
}

.migration-main button:disabled {
  opacity: .48;
  cursor: not-allowed;
}

.migration-result-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.migration-result-grid > div {
  min-width: 0;
  display: grid;
  gap: 5px;
  padding: 11px 12px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
}

.migration-result-grid span {
  color: var(--muted);
  font-size: 10px;
}

.migration-result-grid strong {
  overflow-wrap: anywhere;
  font-size: 12px;
}

.migration-error,
.migration-notice {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid color-mix(in oklch, var(--danger) 28%, var(--border));
  border-radius: 4px;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 12px;
}

.migration-notice.info {
  border-color: color-mix(in oklch, var(--accent) 28%, var(--border));
  background: var(--accent-soft);
  color: var(--accent);
}

.migration-danger-panel {
  border-color: color-mix(in oklch, var(--danger) 35%, var(--border));
}

.migration-danger-panel :deep(.settings-surface-head) {
  background: color-mix(in oklch, var(--danger-soft) 46%, var(--surface));
}

.migration-confirm-line {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  border: 1px solid color-mix(in oklch, var(--danger) 20%, var(--border));
  border-radius: 5px;
  background: color-mix(in oklch, var(--danger-soft) 40%, var(--surface));
  cursor: pointer;
}

.migration-confirm-line input {
  margin-top: 3px;
  accent-color: var(--danger);
}

.migration-confirm-line span {
  display: grid;
  gap: 3px;
}

.migration-confirm-line strong { font-size: 12px; }
.migration-confirm-line small { color: var(--muted); font-size: 11px; }

.migration-history-list {
  display: grid;
  padding: 0 13px;
}

.migration-history-row {
  width: 100%;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 0;
  border: 0;
  border-top: 1px solid var(--border);
  background: transparent;
  color: var(--fg);
  text-align: left;
}

.migration-history-row:first-child { border-top: 0; }

.migration-history-row:hover > span:first-child strong {
  color: var(--accent);
}

.migration-history-row > span:first-child {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.migration-history-row strong,
.migration-history-row small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.migration-history-row strong { font-size: 12px; }
.migration-history-row small { color: var(--muted); font-size: 10px; }

@media (max-width: 1200px) {
  .migration-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 900px) {
  .migration-main { width: 100%; }
  .migration-status-grid { grid-template-columns: 1fr; }
  .migration-result-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 640px) {
  .migration-breadcrumbs { font-size: 11px; }
  .migration-titlebar {
    align-items: stretch;
    flex-direction: column;
  }
  .migration-titlebar .page-actions,
  .migration-titlebar .btn { width: 100%; }
  .migration-panel :deep(.settings-surface-head),
  .migration-history :deep(.settings-surface-head) {
    align-items: flex-start;
    flex-direction: column;
  }
  .migration-limit,
  .migration-job-status,
  .migration-switch-badge {
    align-self: flex-start;
  }
  .migration-panel-body { padding: 11px; }
  .migration-drop-zone { min-height: 148px; padding: 18px 12px; }
  .migration-panel-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .migration-panel-actions .btn { width: 100%; }
  .migration-result-grid { grid-template-columns: 1fr; }
  .migration-history-row { align-items: flex-start; }
}
</style>
