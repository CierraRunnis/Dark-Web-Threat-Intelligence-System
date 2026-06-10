<template>
  <div class="code-monitoring-settings ti-page">
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
            <el-table :data="platformSessions" table-layout="auto">
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
              <el-table-column prop="last_error" label="最近错误" min-width="220" show-overflow-tooltip />
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
          <div class="ti-card-title">监测对象与敏感规则</div>
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
                <el-option v-for="item in watchlists" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </div>
            <div class="watchlist-toolbar__item watchlist-toolbar__item--switch">
              <span>启停状态</span>
              <el-switch v-model="watchlistForm.enabled" active-text="启用" inactive-text="停用" />
            </div>
          </div>

          <div class="watchlist-form">
            <el-input v-model="watchlistForm.name" placeholder="监测对象名称" />
            <el-input v-model="watchlistForm.organization_name" placeholder="所属机构" />
            <el-input v-model="watchlistForm.notes" placeholder="备注" />
          </div>

          <div class="watchlist-options">
            <div class="watchlist-option">
              <span>平台选择</span>
              <el-select v-model="watchlistForm.platforms" multiple collapse-tags placeholder="选择平台">
                <el-option v-for="item in platformOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </div>
            <div class="watchlist-option">
              <span>文件扩展名</span>
              <el-select v-model="watchlistForm.file_extensions" multiple collapse-tags placeholder="选择扩展名">
                <el-option v-for="item in fileExtensionOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </div>
            <div class="watchlist-option">
              <span>每词最大结果数</span>
              <el-input-number v-model="watchlistForm.max_results_per_term" :min="1" :max="20" />
            </div>
            <div class="watchlist-option">
              <span>搜索页数</span>
              <el-input-number v-model="watchlistForm.search_page_limit" :min="1" :max="10" />
            </div>
            <div class="watchlist-option watchlist-option--toggles">
              <label><el-switch v-model="watchlistForm.detail_fetch" /> 详情抓取</label>
            </div>
          </div>

          <div class="watchlist-option">
            <span>敏感规则</span>
            <el-checkbox-group v-model="watchlistForm.enabled_rule_keys">
              <el-checkbox v-for="item in ruleOptions" :key="item.value" :label="item.value">
                {{ item.label }}
              </el-checkbox>
            </el-checkbox-group>
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
                <el-option label="项目名" value="project" />
                <el-option label="产品名" value="product" />
                <el-option label="自定义词" value="custom" />
              </el-select>
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
import { useCodeMonitoringApi } from '@/composables/useCodeMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const api = useCodeMonitoringApi()

const loadingSessions = ref(false)
const loadingWatchlists = ref(false)
const savingWatchlist = ref(false)
const platformSessions = ref([])
const watchlists = ref([])
const selectedWatchlistId = ref(null)
const sessionDrafts = reactive({})
const loginStarting = reactive({})

const platformOptions = [
  { label: 'GitHub', value: 'github' },
  { label: 'GitLab', value: 'gitlab' },
  { label: 'Gitee', value: 'gitee' },
]
const fileExtensionOptions = ['env', 'yaml', 'yml', 'json', 'ini', 'conf', 'properties', 'py', 'js', 'ts', 'java']
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
  platforms: ['github', 'gitlab', 'gitee'],
  file_extensions: [...fileExtensionOptions],
  search_page_limit: 3,
  max_results_per_term: 5,
  detail_fetch: true,
  enabled_rule_keys: ['api_key', 'token', 'ak_sk', 'db_url', 'jwt_secret', 'redis_url', 'private_key', 'internal_url', 'password'],
  terms: [],
})

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

function applyWatchlist(payload) {
  selectedWatchlistId.value = payload?.id ?? null
  watchlistForm.id = payload?.id ?? null
  watchlistForm.name = payload?.name || ''
  watchlistForm.organization_name = payload?.organization_name || ''
  watchlistForm.notes = payload?.notes || ''
  watchlistForm.enabled = payload?.enabled ?? true
  watchlistForm.platforms = Array.isArray(payload?.platforms) && payload.platforms.length ? [...payload.platforms] : ['github', 'gitlab', 'gitee']
  watchlistForm.file_extensions = Array.isArray(payload?.file_extensions) ? [...payload.file_extensions] : []
  watchlistForm.search_page_limit = Number(payload?.search_page_limit || 3)
  watchlistForm.max_results_per_term = Number(payload?.max_results_per_term || 5)
  watchlistForm.detail_fetch = Boolean(payload?.detail_fetch ?? true)
  watchlistForm.enabled_rule_keys = Array.isArray(payload?.enabled_rule_keys) ? [...payload.enabled_rule_keys] : []
  watchlistForm.terms = Array.isArray(payload?.terms)
    ? payload.terms.map((item) => ({
        term: item?.term || '',
        term_type: item?.term_type || 'company_name',
        enabled: item?.enabled ?? true,
      }))
    : []
}

function createWatchlist() {
  applyWatchlist({
    id: null,
    name: '',
    organization_name: '',
    notes: '',
    enabled: true,
    platforms: ['github', 'gitlab', 'gitee'],
    file_extensions: [...fileExtensionOptions],
    search_page_limit: 3,
    max_results_per_term: 5,
    detail_fetch: true,
    enabled_rule_keys: ['api_key', 'token', 'ak_sk', 'db_url', 'jwt_secret', 'redis_url', 'private_key', 'internal_url', 'password'],
    terms: [],
  })
}

function selectWatchlist(watchlistId) {
  const target = watchlists.value.find((item) => item.id === watchlistId)
  applyWatchlist(target || null)
}

function addTerm() {
  watchlistForm.terms.push({ term: '', term_type: 'company_name', enabled: true })
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
    ElMessage.error('请输入所属机构')
    return
  }
  savingWatchlist.value = true
  try {
    const payload = await api.saveWatchlist({
      ...watchlistForm,
      terms: watchlistForm.terms.map((item) => ({
        term: item.term,
        term_type: item.term_type,
        enabled: item.enabled,
      })),
    })
    applyWatchlist(payload)
    await loadWatchlists()
    ElMessage.success('代码监测配置已保存')
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

.watchlist-toolbar__item,
.watchlist-option {
  display: grid;
  gap: 8px;
}

.watchlist-toolbar__item--switch {
  align-content: start;
}

.watchlist-form,
.watchlist-options {
  display: grid;
  gap: 12px;
  margin-bottom: 18px;
}

.watchlist-form {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.watchlist-options {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.watchlist-option--toggles {
  align-content: start;
}

.watchlist-option--toggles label {
  display: flex;
  align-items: center;
  gap: 10px;
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
  margin-top: 18px;
}

.watchlist-terms__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.watchlist-term-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 160px 96px 80px;
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
