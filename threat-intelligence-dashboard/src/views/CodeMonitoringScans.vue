<template>
  <div class="code-monitoring-scans ti-page">
    <section class="content-grid">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">代码扫描执行</div>
          <div class="health-actions">
            <el-button plain :loading="loadingWatchlists" @click="loadWatchlists">刷新配置</el-button>
            <el-button type="success" :loading="scanLoading" @click="runScan">立即扫描</el-button>
          </div>
        </div>
        <div class="ti-card-body">
          <div class="scan-form">
            <div class="scan-form__item">
              <span>监测对象</span>
              <el-select v-model="scanForm.watchlistId" placeholder="选择监测对象">
                <el-option v-for="item in watchlists" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </div>
            <div class="scan-form__item">
              <span>平台选择</span>
              <el-select v-model="scanForm.platforms" multiple collapse-tags placeholder="选择平台">
                <el-option label="GitHub" value="github" />
                <el-option label="GitLab" value="gitlab" />
                <el-option label="Gitee" value="gitee" />
              </el-select>
            </div>
            <div class="scan-form__item">
              <span>文件扩展名</span>
              <el-select v-model="scanForm.fileExtensions" multiple collapse-tags placeholder="选择扩展名">
                <el-option v-for="item in fileExtensionOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </div>
            <div class="scan-form__item">
              <span>每词最大结果数</span>
              <el-input-number v-model="scanForm.maxResultsPerTerm" :min="1" :max="20" />
            </div>
            <div class="scan-form__item">
              <span>搜索页数</span>
              <el-input-number v-model="scanForm.searchPageLimit" :min="1" :max="10" />
            </div>
            <div class="scan-form__item scan-form__item--switches">
              <label><el-switch v-model="scanForm.detailFetch" /> 详情抓取</label>
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
            <p v-if="lastRunMessage" class="panel-note">{{ lastRunMessage }}</p>
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
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useCodeMonitoringApi } from '@/composables/useCodeMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const api = useCodeMonitoringApi()

const loadingWatchlists = ref(false)
const loadingScans = ref(false)
const scanLoading = ref(false)
const watchlists = ref([])
const scanRuns = ref([])
const lastRunMessage = ref('')
const lastRunErrors = ref([])

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

const scanForm = reactive({
  watchlistId: null,
  platforms: [],
  fileExtensions: [],
  searchPageLimit: 3,
  maxResultsPerTerm: 5,
  detailFetch: true,
  enabledRuleKeys: ['api_key', 'token', 'ak_sk', 'db_url', 'jwt_secret', 'redis_url', 'private_key', 'internal_url', 'password'],
})

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

function applyWatchlist(payload) {
  if (!payload) return
  scanForm.watchlistId = payload.id
  scanForm.platforms = Array.isArray(payload.platforms) ? [...payload.platforms] : []
  scanForm.fileExtensions = Array.isArray(payload.file_extensions) ? [...payload.file_extensions] : []
  scanForm.searchPageLimit = Number(payload.search_page_limit || 3)
  scanForm.maxResultsPerTerm = Number(payload.max_results_per_term || 5)
  scanForm.detailFetch = Boolean(payload.detail_fetch ?? true)
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
    lastRunMessage.value = `已扫描 ${payload.scanned_terms || 0} 个监测词，候选 ${payload.candidates || 0} 条，命中 ${payload.hits || 0} 条。`
    lastRunErrors.value = payload.errors || []
    await loadScans()
    ElMessage.success('代码扫描已执行')
  } catch (error) {
    ElMessage.error(error.message || '执行代码扫描失败')
  } finally {
    scanLoading.value = false
  }
}

watch(
  () => scanForm.watchlistId,
  async (watchlistId) => {
    if (!watchlistId) return
    const target = watchlists.value.find((item) => item.id === watchlistId)
    if (target) applyWatchlist(target)
    await loadScans()
  },
)

onMounted(async () => {
  await loadWatchlists()
  await loadScans()
})
</script>

<style scoped lang="scss">
.content-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 22px;
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
  .scan-form {
    grid-template-columns: 1fr;
  }
}
</style>
