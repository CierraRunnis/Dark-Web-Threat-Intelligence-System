<template>
  <div class="code-monitoring-settings ti-page">
    <section class="content-grid">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">平台会话管理</div>
          <div class="health-actions">
            <el-button plain :loading="loadingSessions || detectingSessions" @click="refreshSessions">
              刷新会话
            </el-button>
          </div>
        </div>
        <div class="ti-card-body">
          <div class="ti-table-shell">
            <el-table :data="platformSessions" table-layout="auto">
              <el-table-column prop="label" label="平台" min-width="180" />
              <el-table-column label="状态" width="140">
                <template #default="{ row }">
                  <span class="session-status" :class="statusBadgeClass(row.status)">
                    <span class="session-status__dot" />
                    {{ statusLabelMap[row.status] || row.status || 'unknown' }}
                  </span>
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
              <el-table-column prop="last_error" label="最近错误" min-width="260" show-overflow-tooltip />
              <el-table-column label="操作" min-width="260" fixed="right">
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
                    <el-button size="small" type="danger" plain @click="removeSession(row.platform)">删除</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <p class="panel-note">
            代码监测会话状态会在进入页面和点击刷新时自动检测代码搜索页可用性，无需手动校验。
          </p>
        </div>
      </div>

      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">监测对象与企业画像</div>
          <div class="health-actions">
            <el-button plain :loading="loadingWatchlists" @click="loadWatchlists">刷新对象</el-button>
            <el-button plain @click="createWatchlist">新建对象</el-button>
            <el-button type="danger" plain :disabled="!selectedWatchlistId || savingWatchlist" @click="deleteWatchlist">删除对象</el-button>
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

          <div class="watchlist-option">
            <span>敏感规则</span>
            <el-checkbox-group v-model="watchlistForm.enabled_rule_keys">
              <el-checkbox v-for="item in ruleOptions" :key="item.value" :label="item.value">
                {{ item.label }}
              </el-checkbox>
            </el-checkbox-group>
          </div>

          <div class="enterprise-profile">
            <div class="watchlist-terms__header">
              <strong>企业画像</strong>
              <div class="enterprise-profile__actions">
                <span class="enterprise-profile__hint">每行一个值，用于确定企业锚点与高危提权。</span>
                <el-button plain size="small" @click="clearEnterpriseProfile">清空画像</el-button>
              </div>
            </div>
            <div class="enterprise-profile__grid">
              <div class="watchlist-option">
                <span>企业全称</span>
                <el-input
                  v-model="enterpriseProfileDraft.official_names"
                  type="textarea"
                  :rows="3"
                  placeholder="例如：宁德时代"
                />
              </div>
              <div class="watchlist-option">
                <span>品牌别名</span>
                <el-input
                  v-model="enterpriseProfileDraft.brand_aliases"
                  type="textarea"
                  :rows="3"
                  placeholder="例如：CATL&#10;时代电池"
                />
              </div>
              <div class="watchlist-option">
                <span>英文简称</span>
                <el-input
                  v-model="enterpriseProfileDraft.english_aliases"
                  type="textarea"
                  :rows="3"
                  placeholder="例如：catl"
                />
              </div>
              <div class="watchlist-option">
                <span>主域名</span>
                <el-input
                  v-model="enterpriseProfileDraft.root_domains"
                  type="textarea"
                  :rows="3"
                  placeholder="例如：catl.com"
                />
              </div>
              <div class="watchlist-option">
                <span>子域名规则</span>
                <el-input
                  v-model="enterpriseProfileDraft.trusted_subdomain_patterns"
                  type="textarea"
                  :rows="3"
                  placeholder="例如：*.catl.com"
                />
              </div>
              <div class="watchlist-option">
                <span>企业系统关键词</span>
                <el-input
                  v-model="enterpriseProfileDraft.internal_system_keywords"
                  type="textarea"
                  :rows="3"
                  placeholder="例如：zabbix&#10;eicc&#10;sso"
                />
              </div>
              <div class="watchlist-option">
                <span>排除别名</span>
                <el-input
                  v-model="enterpriseProfileDraft.negative_aliases"
                  type="textarea"
                  :rows="3"
                  placeholder="用于屏蔽已知误匹配词"
                />
              </div>
              <div class="watchlist-option">
                <span>短词保护</span>
                <el-input
                  v-model="enterpriseProfileDraft.short_alias_guard"
                  type="textarea"
                  :rows="3"
                  placeholder="例如：catl"
                />
              </div>
            </div>
          </div>

          <p class="panel-note">
            代码监测默认长期覆盖 GitHub / GitLab / Gitee，并使用高风险文件类型与详情抓取策略。
          </p>

          <div class="watchlist-terms">
            <div class="watchlist-terms__header">
              <strong>检索词</strong>
              <el-button plain size="small" @click="addTerm">新增检索词</el-button>
            </div>
            <div v-for="(term, index) in watchlistForm.terms" :key="`${term.term_type}-${index}`" class="watchlist-term-row">
              <el-input v-model="term.term" placeholder="检索词" />
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { useCodeMonitoringApi } from '@/composables/useCodeMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const api = useCodeMonitoringApi()

const loadingSessions = ref(false)
const detectingSessions = ref(false)
const loadingWatchlists = ref(false)
const savingWatchlist = ref(false)
const platformSessions = ref([])
const watchlists = ref([])
const selectedWatchlistId = ref(null)
const sessionDrafts = reactive({})
const loginStarting = reactive({})

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
  invalid: '无效',
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
  search_page_limit: 0,
  max_results_per_term: 0,
  detail_fetch: true,
  enabled_rule_keys: ['api_key', 'token', 'ak_sk', 'db_url', 'jwt_secret', 'redis_url', 'private_key', 'internal_url', 'password'],
  terms: [],
})

const enterpriseProfileDraft = reactive({
  official_names: '',
  brand_aliases: '',
  english_aliases: '',
  root_domains: '',
  trusted_subdomain_patterns: '',
  internal_system_keywords: '',
  negative_aliases: '',
  short_alias_guard: '',
})

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

function statusBadgeClass(status) {
  return `session-status--${status || 'unknown'}`
}

function normalizeLines(value) {
  return String(value || '')
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function toMultilineText(values) {
  return Array.isArray(values) ? values.join('\n') : ''
}

function readEnterpriseProfilePayload() {
  return {
    official_names: normalizeLines(enterpriseProfileDraft.official_names),
    brand_aliases: normalizeLines(enterpriseProfileDraft.brand_aliases),
    english_aliases: normalizeLines(enterpriseProfileDraft.english_aliases),
    root_domains: normalizeLines(enterpriseProfileDraft.root_domains),
    trusted_subdomain_patterns: normalizeLines(enterpriseProfileDraft.trusted_subdomain_patterns),
    internal_system_keywords: normalizeLines(enterpriseProfileDraft.internal_system_keywords),
    negative_aliases: normalizeLines(enterpriseProfileDraft.negative_aliases),
    short_alias_guard: normalizeLines(enterpriseProfileDraft.short_alias_guard),
  }
}

function syncEnterpriseProfileDraft(profile = {}) {
  enterpriseProfileDraft.official_names = toMultilineText(profile.official_names)
  enterpriseProfileDraft.brand_aliases = toMultilineText(profile.brand_aliases)
  enterpriseProfileDraft.english_aliases = toMultilineText(profile.english_aliases)
  enterpriseProfileDraft.root_domains = toMultilineText(profile.root_domains)
  enterpriseProfileDraft.trusted_subdomain_patterns = toMultilineText(profile.trusted_subdomain_patterns)
  enterpriseProfileDraft.internal_system_keywords = toMultilineText(profile.internal_system_keywords)
  enterpriseProfileDraft.negative_aliases = toMultilineText(profile.negative_aliases)
  enterpriseProfileDraft.short_alias_guard = toMultilineText(profile.short_alias_guard)
}

function clearEnterpriseProfile() {
  syncEnterpriseProfileDraft({})
}

function syncSessionDrafts(rows) {
  for (const item of rows || []) {
    sessionDrafts[item.platform] = item.account_label || ''
  }
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
  watchlistForm.search_page_limit = 0
  watchlistForm.max_results_per_term = 0
  watchlistForm.detail_fetch = Boolean(payload?.detail_fetch ?? true)
  watchlistForm.enabled_rule_keys = Array.isArray(payload?.enabled_rule_keys) ? [...payload.enabled_rule_keys] : []
  watchlistForm.terms = Array.isArray(payload?.terms)
    ? payload.terms.map((item) => ({
        term: item?.term || '',
        term_type: item?.term_type || 'company_name',
        enabled: item?.enabled ?? true,
      }))
    : []
  syncEnterpriseProfileDraft(payload?.enterprise_profile || {})
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
    search_page_limit: 0,
    max_results_per_term: 0,
    detail_fetch: true,
    enabled_rule_keys: ['api_key', 'token', 'ak_sk', 'db_url', 'jwt_secret', 'redis_url', 'private_key', 'internal_url', 'password'],
    terms: [],
    enterprise_profile: {},
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
    syncSessionDrafts(platformSessions.value)
  } catch (error) {
    ElMessage.error(error.message || '加载平台会话失败')
  } finally {
    loadingSessions.value = false
  }
}

async function autoDetectSessions({ silent = false } = {}) {
  if (detectingSessions.value) return
  detectingSessions.value = true
  try {
    platformSessions.value = await api.autoDetectSessions()
    syncSessionDrafts(platformSessions.value)
    if (!silent) {
      ElMessage.success('会话状态已自动检测')
    }
  } catch (error) {
    ElMessage.error(error.message || '自动检测会话失败')
  } finally {
    detectingSessions.value = false
  }
}

async function refreshSessions() {
  await loadSessions()
  await autoDetectSessions({ silent: true })
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
      enterprise_profile: readEnterpriseProfilePayload(),
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

async function deleteWatchlist() {
  if (!selectedWatchlistId.value) {
    ElMessage.error('请先选择监测对象')
    return
  }
  const current = watchlists.value.find((item) => item.id === selectedWatchlistId.value)
  try {
    await ElMessageBox.confirm(
      `删除监测对象“${current?.name || '当前对象'}”后，企业画像、检索词、命中结果和扫描历史将一并删除。`,
      '删除确认',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  savingWatchlist.value = true
  try {
    await api.deleteWatchlist(selectedWatchlistId.value)
    selectedWatchlistId.value = null
    createWatchlist()
    await loadWatchlists()
    ElMessage.success('监测对象已删除')
  } catch (error) {
    ElMessage.error(error.message || '删除监测对象失败')
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
  await autoDetectSessions({ silent: true })
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

.session-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--ti-text-secondary);
}

.session-status__dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #cbd5e1;
  box-shadow: 0 0 0 3px rgba(203, 213, 225, 0.2);
  flex: 0 0 auto;
}

.session-status--valid {
  color: #166534;
}

.session-status--valid .session-status__dot {
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.18);
}

.session-status--invalid,
.session-status--missing,
.session-status--unavailable {
  color: #b91c1c;
}

.session-status--invalid .session-status__dot,
.session-status--missing .session-status__dot,
.session-status--unavailable .session-status__dot {
  background: #ef4444;
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.18);
}

.session-status--login_in_progress,
.session-status--configured {
  color: #92400e;
}

.session-status--login_in_progress .session-status__dot,
.session-status--configured .session-status__dot {
  background: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.18);
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

.watchlist-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.watchlist-toolbar__item span,
.watchlist-option span {
  color: var(--ti-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.enterprise-profile,
.watchlist-terms {
  display: grid;
  gap: 12px;
  margin-top: 18px;
}

.enterprise-profile__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.enterprise-profile__hint {
  color: var(--ti-text-secondary);
  font-size: 12px;
}

.enterprise-profile__actions {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: space-between;
}

.panel-note {
  margin: 16px 0 0;
  color: var(--ti-text-secondary);
}

.watchlist-terms__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
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
  .watchlist-term-row,
  .enterprise-profile__grid {
    grid-template-columns: 1fr;
  }
}
</style>
