<template>
  <div class="document-exposure-results ti-page">
    <section class="content-grid">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-body">
          <EventTableToolbar
            eyebrow="命中结果"
            title="文件监测命中列表"
            description="筛选并核验文档平台、网盘聚合与搜索引擎中的疑似文件暴露命中。"
            :search-value="searchValue"
            search-placeholder="搜索标题、平台、企业名"
            :active-filters="activeFilters"
            @update:search-value="searchValue = $event"
          >
            <template #filters>
              <el-select v-model="sourceFamilyFilter" placeholder="来源家族" style="width: 160px" clearable>
                <el-option label="网盘聚合" value="netdisk_aggregator" />
                <el-option label="搜索引擎" value="search_engine" />
                <el-option label="文档平台" value="document_library" />
              </el-select>
              <el-select v-model="platformFilter" placeholder="平台" style="width: 160px" clearable>
                <el-option v-for="item in platformOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="reviewFilter" placeholder="核验状态" style="width: 160px" clearable>
                <el-option v-for="item in reviewOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="accessStateFilter" placeholder="访问状态" style="width: 160px" clearable>
                <el-option v-for="item in accessStateOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="matchedTermFilter" placeholder="关键词" style="width: 180px" clearable filterable>
                <el-option v-for="item in matchedTermOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </template>
            <template #actions>
              <el-button plain :loading="loadingHits" @click="loadHits">刷新结果</el-button>
            </template>
          </EventTableToolbar>

          <div class="ti-table-shell table-shell">
            <el-table :data="pagedHits" table-layout="auto" style="width: 100%">
              <el-table-column prop="lastSeenAt" label="最近发现" min-width="180">
                <template #default="{ row }">
                  {{ formatDateTime(row.lastSeenAt) || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="来源家族" width="140">
                <template #default="{ row }">
                  {{ sourceFamilyLabelMap[row.sourceFamily] || row.sourceFamily || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="平台" width="170">
                <template #default="{ row }">
                  {{ row.platformLabel || row.platform || '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="title" label="标题" min-width="320" show-overflow-tooltip />
              <el-table-column prop="riskScore" label="风险分" width="100" />
              <el-table-column prop="fileCount" label="文件数" width="100" />
              <el-table-column label="核验状态" width="120">
                <template #default="{ row }">
                  {{ reviewLabelMap[row.reviewStatus] || row.reviewStatus || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="复核" min-width="220">
                <template #default="{ row }">
                  <div class="review-actions">
                    <el-button size="small" @click="reviewHit(row, 'confirmed')">确认</el-button>
                    <el-button size="small" plain @click="reviewHit(row, 'false_positive')">误报</el-button>
                    <el-button size="small" plain @click="reviewHit(row, 'closed')">关闭</el-button>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="查看" width="120" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" @click="viewEvent(row)">查看</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div class="table-footer">
            <div class="table-footer__note">当前展示 {{ filteredHits.length }} 条命中，支持复核并跳转统一事件详情页查看截图、快照和文件清单。</div>
            <el-pagination
              v-model:current-page="currentPage"
              v-model:page-size="pageSize"
              :page-sizes="[10, 20, 50]"
              :total="filteredHits.length"
              layout="total, sizes, prev, pager, next"
              background
            />
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import EventTableToolbar from '@/components/common/EventTableToolbar.vue'
import { useDocumentExposureApi } from '@/composables/useDocumentExposureApi'
import { useIntelligenceData } from '@/composables/useIntelligenceData'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const api = useDocumentExposureApi()
const router = useRouter()
const { refresh } = useIntelligenceData()

const loadingHits = ref(false)
const hits = ref([])
const currentPage = ref(1)
const pageSize = ref(10)
const searchValue = ref('')
const sourceFamilyFilter = ref('')
const platformFilter = ref('')
const reviewFilter = ref('')
const accessStateFilter = ref('')
const matchedTermFilter = ref('')

const sourceFamilyLabelMap = {
  netdisk_aggregator: '网盘聚合',
  search_engine: '搜索引擎',
  document_library: '文档平台',
}

const reviewLabelMap = {
  new: '待处理',
  triaged: '已分诊',
  confirmed: '已确认',
  false_positive: '误报',
  closed: '已关闭',
}

const accessStateLabelMap = {
  public: '公开访问',
  login_required: '需要登录',
  captcha: '验证码',
  removed: '已移除',
  forbidden: '禁止访问',
  unknown: '未知',
}

const reviewOptions = [
  { label: '待处理', value: 'new' },
  { label: '已分诊', value: 'triaged' },
  { label: '已确认', value: 'confirmed' },
  { label: '误报', value: 'false_positive' },
  { label: '已关闭', value: 'closed' },
]

const accessStateOptions = [
  { label: '公开访问', value: 'public' },
  { label: '需要登录', value: 'login_required' },
  { label: '验证码', value: 'captcha' },
  { label: '已移除', value: 'removed' },
  { label: '禁止访问', value: 'forbidden' },
  { label: '未知', value: 'unknown' },
]

const platformOptions = computed(() =>
  [...new Map(
    hits.value
      .filter((item) => item.platform)
      .map((item) => [item.platform, { value: item.platform, label: item.platformLabel || item.platform }])
  ).values()]
)

const matchedTermOptions = computed(() =>
  [...new Set(
    hits.value.flatMap((item) =>
      Array.isArray(item.matchedTerms)
        ? item.matchedTerms.map((term) => String(term?.term || '').trim()).filter(Boolean)
        : []
    )
  )]
)

const filteredHits = computed(() => {
  const keyword = searchValue.value.trim().toLowerCase()
  return hits.value.filter((item) => {
    const matchesKeyword =
      !keyword ||
      [item.title, item.platformLabel, item.platform, item.organizationName, item.watchlistName]
        .some((field) => String(field || '').toLowerCase().includes(keyword))
    const matchesFamily = !sourceFamilyFilter.value || item.sourceFamily === sourceFamilyFilter.value
    const matchesPlatform = !platformFilter.value || item.platform === platformFilter.value
    const matchesReview = !reviewFilter.value || item.reviewStatus === reviewFilter.value
    const matchesAccess = !accessStateFilter.value || item.accessState === accessStateFilter.value
    const matchesTerm =
      !matchedTermFilter.value ||
      (Array.isArray(item.matchedTerms) &&
        item.matchedTerms.some((term) => String(term?.term || '').trim() === matchedTermFilter.value))
    return matchesKeyword && matchesFamily && matchesPlatform && matchesReview && matchesAccess && matchesTerm
  })
})

const pagedHits = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredHits.value.slice(start, start + pageSize.value)
})

const activeFilters = computed(() => {
  const filters = []
  if (sourceFamilyFilter.value) filters.push(`来源: ${sourceFamilyLabelMap[sourceFamilyFilter.value] || sourceFamilyFilter.value}`)
  if (platformFilter.value) filters.push(`平台: ${platformOptions.value.find((item) => item.value === platformFilter.value)?.label || platformFilter.value}`)
  if (reviewFilter.value) filters.push(`核验: ${reviewLabelMap[reviewFilter.value] || reviewFilter.value}`)
  if (accessStateFilter.value) filters.push(`访问: ${accessStateLabelMap[accessStateFilter.value] || accessStateFilter.value}`)
  if (matchedTermFilter.value) filters.push(`关键词: ${matchedTermFilter.value}`)
  if (searchValue.value.trim()) filters.push(`搜索: ${searchValue.value.trim()}`)
  return filters
})

function formatDateTime(value) {
  return formatShanghaiDateTime(value)
}

async function loadHits() {
  loadingHits.value = true
  try {
    hits.value = await api.loadHits({ limit: 300 })
  } catch (error) {
    ElMessage.error(error.message || '加载命中结果失败')
  } finally {
    loadingHits.value = false
  }
}

async function reviewHit(row, status) {
  try {
    await api.reviewHit(row.id, { status, reviewer: 'ui', note: '' })
    await Promise.all([loadHits(), refresh()])
    ElMessage.success('核验状态已更新')
  } catch (error) {
    ElMessage.error(error.message || '更新核验状态失败')
  }
}

function viewEvent(row) {
  if (!row?.id) return
  sessionStorage.setItem(`event-back:document:${row.id}`, '/document-exposure/results')
  router.push({ name: 'EventDetail', params: { eventId: `document:${row.id}` } })
}

watch([filteredHits, pageSize], () => {
  const maxPage = Math.max(1, Math.ceil(filteredHits.value.length / pageSize.value))
  if (currentPage.value > maxPage) currentPage.value = maxPage
})

onMounted(loadHits)
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

.review-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.table-footer {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-top: 18px;
}

.table-footer__note {
  color: var(--ti-text-muted);
  font-size: 12px;
}

@media (max-width: 1200px) {
  .table-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
