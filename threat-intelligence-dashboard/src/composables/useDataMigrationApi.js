const STATUS_DEFINITIONS = {
  queued: {
    label: '等待处理',
    type: 'info',
    description: '迁移包已接收，正在等待后端预检。',
    progress: 3,
  },
  preflight: {
    label: '安全预检',
    type: 'primary',
    description: '正在校验包结构、路径、体积、校验和与镜像引用。',
    progress: 20,
  },
  importing: {
    label: '正在导入',
    type: 'primary',
    description: '正在创建独立 PostgreSQL Schema，分批写入数据并释放镜像。',
    progress: 58,
  },
  verifying: {
    label: '联合校验',
    type: 'warning',
    description: '正在复核逐表行数、空值与联合摘要。',
    progress: 84,
  },
  analyzing: {
    label: '结果分析',
    type: 'warning',
    description: '正在整理导入报告与激活前检查结果。',
    progress: 94,
  },
  ready: {
    label: '等待激活',
    type: 'success',
    description: '数据库和镜像已通过校验，需要管理员确认才会切换。',
    progress: 100,
  },
  activating: {
    label: '正在激活',
    type: 'warning',
    description: '活动版本已切换，服务正在重启并执行健康检查。',
    progress: 100,
  },
  active: {
    label: '已激活',
    type: 'success',
    description: '系统已使用新的 PostgreSQL Schema 和镜像目录。',
    progress: 100,
  },
  failed: {
    label: '迁移失败',
    type: 'danger',
    description: '预检、导入或校验失败，当前活动版本未被替换。',
    progress: 100,
  },
  rolled_back: {
    label: '已自动回退',
    type: 'warning',
    description: '新版本未通过启动检查，系统已恢复上一活动版本。',
    progress: 100,
  },
  rollback_failed: {
    label: '回退失败',
    type: 'danger',
    description: '激活和自动回退均失败，需要立即人工检查服务和活动版本文件。',
    progress: 100,
  },
}

export const MIGRATION_STATUS_KEYS = Object.freeze(Object.keys(STATUS_DEFINITIONS))

const POLLING_STATUSES = new Set([
  'queued',
  'preflight',
  'importing',
  'verifying',
  'analyzing',
  'activating',
])

const PHASE_ALIASES = {
  snapshot: 'preflight',
  preflight: 'preflight',
  database: 'importing',
  artifacts: 'importing',
  import: 'importing',
  importing: 'importing',
  verify: 'verifying',
  verifying: 'verifying',
  analysis: 'analyzing',
  analyzing: 'analyzing',
  ready: 'ready',
  activate: 'activating',
  activating: 'activating',
}

function normalizedValue(value) {
  return String(value || '').trim().toLowerCase().replaceAll('-', '_')
}

export function migrationStatusKey(jobOrStatus, phase = '') {
  const job = jobOrStatus && typeof jobOrStatus === 'object' ? jobOrStatus : null
  const rawStatus = normalizedValue(job ? job.status : jobOrStatus)
  const rawPhase = normalizedValue(job ? job.phase : phase)

  if (rawStatus === 'preparing' || rawStatus === 'processing' || rawStatus === 'running') {
    return PHASE_ALIASES[rawPhase] || 'importing'
  }
  if (rawStatus === 'restart_required') return 'activating'
  if (rawStatus === 'completed' || rawStatus === 'success') return 'active'
  if (STATUS_DEFINITIONS[rawStatus]) return rawStatus
  if (PHASE_ALIASES[rawStatus]) return PHASE_ALIASES[rawStatus]
  if (PHASE_ALIASES[rawPhase]) return PHASE_ALIASES[rawPhase]
  return 'queued'
}

export function migrationStatusMeta(jobOrStatus, phase = '') {
  const key = migrationStatusKey(jobOrStatus, phase)
  const job = jobOrStatus && typeof jobOrStatus === 'object' ? jobOrStatus : null
  const explicitProgress = Number(job?.progress)
  const definition = STATUS_DEFINITIONS[key]
  return {
    key,
    ...definition,
    progress: Number.isFinite(explicitProgress)
      ? Math.max(0, Math.min(100, Math.round(explicitProgress)))
      : definition.progress,
  }
}

export function isMigrationPollingStatus(job) {
  const rawStatus = normalizedValue(job?.status)
  if (rawStatus === 'restart_required') return false
  return POLLING_STATUSES.has(migrationStatusKey(job))
}

async function responseError(response) {
  try {
    const payload = await response.clone().json()
    return String(payload?.detail || payload?.message || payload?.error || '').trim()
  } catch {
    try {
      return (await response.text()).trim()
    } catch {
      return ''
    }
  }
}

export function createDataMigrationApi({ fetchImpl = globalThis.fetch, signal } = {}) {
  if (typeof fetchImpl !== 'function') throw new TypeError('fetchImpl must be a function')

  async function requestJson(path, options = {}) {
    const response = await fetchImpl(path, {
      cache: 'no-store',
      signal: options.signal || signal,
      ...options,
    })
    if (!response.ok) {
      const error = new Error((await responseError(response)) || `迁移接口请求失败：${response.status}`)
      error.status = response.status
      throw error
    }
    if (response.status === 204) return {}
    return response.json()
  }

  return {
    getConfig(options) {
      return requestJson('/api/migrations/config', options)
    },
    listJobs(options) {
      return requestJson('/api/migrations', options)
    },
    getJob(jobId, options) {
      return requestJson(`/api/migrations/${encodeURIComponent(jobId)}`, options)
    },
    uploadBundle(file, options = {}) {
      if (!file) return Promise.reject(new TypeError('migration bundle is required'))
      const filename = encodeURIComponent(String(file.name || 'migration.dwti'))
      return requestJson('/api/migrations/upload', {
        ...options,
        method: 'POST',
        headers: {
          'Content-Type': 'application/octet-stream',
          'x-dwti-filename': filename,
          ...(options.headers || {}),
        },
        body: file,
      })
    },
    submitPerformance(jobId, payload, options = {}) {
      return requestJson(`/api/migrations/${encodeURIComponent(jobId)}/performance`, {
        ...options,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(options.headers || {}),
        },
        body: JSON.stringify(payload || {}),
      })
    },
    activate(jobId, options) {
      return requestJson(`/api/migrations/${encodeURIComponent(jobId)}/activate`, {
        ...options,
        method: 'POST',
      })
    },
  }
}
