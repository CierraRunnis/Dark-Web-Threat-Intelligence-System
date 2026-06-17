<template>
  <div class="document-exposure-scans ti-page">
    <section class="content-grid">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-header">
          <div class="ti-card-title">扫描执行</div>
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
                <el-option
                  v-for="item in watchlists"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </div>
            <div class="scan-form__item">
              <span>来源家族</span>
              <el-select v-model="scanForm.sourceFamilies" multiple collapse-tags placeholder="选择来源家族">
                <el-option label="网盘聚合" value="netdisk_aggregator" />
                <el-option label="搜索引擎" value="search_engine" />
                <el-option label="文档平台" value="document_library" />
              </el-select>
            </div>
            <div class="scan-form__item">
              <span>文件类型</span>
              <el-select v-model="scanForm.fileTypes" multiple collapse-tags placeholder="选择文件类型">
                <el-option v-for="item in fileTypeOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </div>
            <div class="scan-form__item">
              <span>页数上限</span>
              <el-input-number v-model="scanForm.pageLimit" :min="1" :max="20" />
            </div>
            <div class="scan-form__item">
              <span>详情抓取</span>
              <el-switch v-model="scanForm.detailFetch" />
            </div>
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
            <el-table :data="scanRuns" table-layout="auto" style="width: 100%">
              <el-table-column prop="finishedAt" label="完成时间" min-width="180">
                <template #default="{ row }">
                  {{ formatDateTime(row.finishedAt) || '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="watchlistName" label="监测对象" min-width="180" />
              <el-table-column label="来源家族" min-width="220">
                <template #default="{ row }">
                  {{ formatSourceFamilies(row.sourceFamilies) }}
                </template>
              </el-table-column>
              <el-table-column prop="candidateCount" label="候选数" width="100" />
              <el-table-column prop="hitCount" label="命中数" width="100" />
              <el-table-column prop="errorCount" label="错误数" width="100" />
              <el-table-column prop="status" label="状态" width="120">
                <template #default="{ row }">
                  {{ statusLabelMap[row.status] || row.status || 'unknown' }}
                </template>
              </el-table-column>
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
import { useDocumentExposureApi } from '@/composables/useDocumentExposureApi'

const api = useDocumentExposureApi()
const loadingWatchlists = ref(false)
const loadingScans = ref(false)
const scanLoading = ref(false)
const watchlists = ref([])
const scanRuns = ref([])
const lastRunMessage = ref('')
const lastRunErrors = ref([])
const fileTypeOptions = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'zip', 'rar', '7z', 'txt', 'csv']

const statusLabelMap = {
  succeeded: '成功',
  partial: '部分成功',
  failed: '失败',
}

const sourceFamilyLabelMap = {
  netdisk_aggregator: '网盘聚合',
  search_engine: '搜索引擎',
  document_library: '文档平台',
}

const scanForm = reactive({
  watchlistId: null,
  sourceFamilies: [],
  fileTypes: [],
  pageLimit: 4,
  detailFetch: true,
})

function formatDateTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 16)
}

function formatSourceFamilies(value) {
  const rows = Array.isArray(value) ? value : []
  if (!rows.length) return '全部'
  return rows.map((item) => sourceFamilyLabelMap[item] || item).join(' / ')
}

function applyWatchlist(payload) {
  if (!payload) return
  scanForm.watchlistId = payload.id
  scanForm.sourceFamilies = Array.isArray(payload.source_families) ? [...payload.source_families] : []
  scanForm.fileTypes = Array.isArray(payload.file_types) ? [...payload.file_types] : []
  scanForm.pageLimit = Number(payload.page_limit || 4)
  scanForm.detailFetch = Boolean(payload.detail_fetch ?? true)
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
      max_candidates_per_term: scanForm.pageLimit,
      source_families: scanForm.sourceFamilies,
      file_types: scanForm.fileTypes,
      page_limit: scanForm.pageLimit,
      detail_fetch: scanForm.detailFetch,
    })
    lastRunMessage.value = `已扫描 ${payload.scanned_terms || 0} 个监测词，候选 ${payload.candidates || 0} 条，命中 ${payload.hits || 0} 条。`
    lastRunErrors.value = payload.errors || []
    await loadScans()
    ElMessage.success('扫描任务已执行')
  } catch (error) {
    ElMessage.error(error.message || '执行扫描失败')
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
  }
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

.scan-form__item {
  display: grid;
  gap: 8px;
}

.scan-form__item span {
  color: var(--ti-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.scan-status {
  margin-top: 18px;
}

.ti-table-shell {
  margin-top: 18px;
}

@media (max-width: 1200px) {
  .scan-form {
    grid-template-columns: 1fr;
  }
}
</style>
