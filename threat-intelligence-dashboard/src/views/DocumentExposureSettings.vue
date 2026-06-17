<template>
  <div class="document-exposure-settings ti-page">
    <section class="content-grid">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">平台会话管理</div>
          <div class="health-actions">
            <el-button plain :loading="loadingSessions" @click="loadSessions">刷新会话</el-button>
          </div>
        </div>
        <div class="ti-card-body">
          <div class="ti-table-shell">
            <el-table :data="platformSessions" table-layout="auto" style="width: 100%">
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
          <div class="ti-card-title">监测对象与关键词</div>
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
                  v-for="item in watchlists"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
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
              <span>来源家族</span>
              <el-select v-model="watchlistForm.source_families" multiple collapse-tags placeholder="选择来源家族">
                <el-option label="网盘聚合" value="netdisk_aggregator" />
                <el-option label="搜索引擎" value="search_engine" />
                <el-option label="文档平台" value="document_library" />
              </el-select>
            </div>
            <div class="watchlist-option">
              <span>文件类型</span>
              <el-select v-model="watchlistForm.file_types" multiple collapse-tags placeholder="选择文件类型">
                <el-option v-for="item in fileTypeOptions" :key="item" :label="item" :value="item" />
              </el-select>
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
                <el-option label="敏感词" value="sensitive_keyword" />
              </el-select>
              <el-input-number v-model="term.weight" :min="1" :max="30" />
              <el-switch v-model="term.enabled" />
              <el-button type="danger" plain size="small" @click="removeTerm(index)">删除</el-button>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useDocumentExposureApi } from '@/composables/useDocumentExposureApi'

const api = useDocumentExposureApi()
const loadingSessions = ref(false)
const loadingWatchlists = ref(false)
const savingWatchlist = ref(false)
const platformSessions = ref([])
const watchlists = ref([])
const selectedWatchlistId = ref(null)
const sessionDrafts = reactive({})
const loginStarting = reactive({})
const fileTypeOptions = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'zip', 'rar', '7z', 'txt', 'csv']
const defaultSourceFamilies = ['netdisk_aggregator', 'search_engine', 'document_library']

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
  source_families: [...defaultSourceFamilies],
  file_types: [],
  page_limit: 4,
  detail_fetch: true,
  terms: [],
})

function formatDateTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 16)
}

function applyWatchlist(payload) {
  selectedWatchlistId.value = payload?.id ?? null
  watchlistForm.id = payload?.id ?? null
  watchlistForm.name = payload?.name || ''
  watchlistForm.organization_name = payload?.organization_name || ''
  watchlistForm.notes = payload?.notes || ''
  watchlistForm.enabled = payload?.enabled ?? true
  watchlistForm.source_families = Array.isArray(payload?.source_families) && payload.source_families.length
    ? [...payload.source_families]
    : [...defaultSourceFamilies]
  watchlistForm.file_types = Array.isArray(payload?.file_types) ? [...payload.file_types] : []
  watchlistForm.page_limit = Number(payload?.page_limit || 4)
  watchlistForm.detail_fetch = Boolean(payload?.detail_fetch ?? true)
  watchlistForm.terms = Array.isArray(payload?.terms) ? payload.terms.map((item) => ({ ...item })) : []
}

function createWatchlist() {
  applyWatchlist({
    id: null,
    name: '',
    organization_name: '',
    notes: '',
    enabled: true,
    source_families: [...defaultSourceFamilies],
    file_types: [],
    page_limit: 4,
    detail_fetch: true,
    terms: [],
  })
}

function selectWatchlist(watchlistId) {
  const target = watchlists.value.find((item) => item.id === watchlistId)
  applyWatchlist(target || null)
}

function addTerm() {
  watchlistForm.terms.push({ term: '', term_type: 'company_name', weight: 10, enabled: true })
}

function removeTerm(index) {
  watchlistForm.terms.splice(index, 1)
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
    if (selectedWatchlistId.value) {
      const current = watchlists.value.find((item) => item.id === selectedWatchlistId.value)
      applyWatchlist(current || watchlists.value[0] || null)
      return
    }
    applyWatchlist(watchlists.value[0] || null)
  } catch (error) {
    ElMessage.error(error.message || '加载监测对象失败')
  } finally {
    loadingWatchlists.value = false
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
    const payload = await api.saveWatchlist(watchlistForm)
    applyWatchlist(payload)
    await loadWatchlists()
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

onMounted(async () => {
  await Promise.all([loadSessions(), loadWatchlists()])
})
</script>

<style scoped lang="scss">
.content-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 22px;
}

.ti-table-shell {
  margin-top: 18px;
}

.table-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.watchlist-toolbar {
  display: grid;
  grid-template-columns: minmax(280px, 420px) auto;
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

.watchlist-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.watchlist-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.watchlist-option {
  display: grid;
  gap: 8px;
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
  .watchlist-toolbar,
  .watchlist-form,
  .watchlist-options,
  .watchlist-term-row {
    grid-template-columns: 1fr;
  }
}
</style>
