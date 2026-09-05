<template>
  <div class="data-leak-page ti-page">
    <section class="ti-panel ti-reveal-up">
      <div class="summary-grid summary-grid--compact">
        <ModuleSummaryCard
          v-for="card in dataLeakSummary"
          :key="card.label"
          v-bind="card"
        />
      </div>
    </section>

    <section class="content-grid">
      <div class="ti-card ti-reveal-up">
        <div class="ti-card-body">
          <EventTableToolbar
            eyebrow="事件表"
            title="数据泄露事件列表"
            description="本页以事件列表为主，趋势、占比和排行图已统一并入威胁态势页。"
            :search-value="searchValue"
            search-placeholder="搜索标题、攻击者、地区"
            :active-filters="activeFilters"
            @update:search-value="searchValue = $event"
          >
            <template #filters>
              <el-select v-model="categoryFilter" placeholder="事件分类" style="width: 160px" clearable>
                <el-option v-for="item in categoryOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </template>

            <template #actions>
              <el-button plain>导出</el-button>
            </template>
          </EventTableToolbar>

          <div v-loading="eventsLoading" class="ti-table-shell table-shell">
            <el-table class="event-table" :data="dataLeakEvents" style="width: 100%" table-layout="auto">
              <el-table-column prop="disclosureDate" label="披露日期" width="140" />
              <el-table-column prop="updatedTime" label="最近更新" width="170" />
              <el-table-column prop="title" label="标题" min-width="420" show-overflow-tooltip />
              <el-table-column prop="category" label="事件分类" width="150" />
              <el-table-column prop="attacker" label="攻击者" width="160" show-overflow-tooltip />
              <el-table-column prop="industry" label="行业" width="150" />
              <el-table-column prop="region" label="受害国家和地区" min-width="220" show-overflow-tooltip />
              <el-table-column label="查看" width="120" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" @click="viewEventDetail(row)">查看</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div class="table-footer">
            <div v-if="eventsError" class="table-footer__note">{{ eventsError }}</div>
            <div v-else class="table-footer__note">
              当前页展示 {{ dataLeakEvents.length }} 条，共 {{ totalEvents }} 条。
            </div>
            <el-pagination
              v-model:current-page="currentPage"
              v-model:page-size="pageSize"
              :page-sizes="[10, 20, 50, 100]"
              :total="totalEvents"
              :disabled="eventsLoading"
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EventTableToolbar from '@/components/common/EventTableToolbar.vue'
import ModuleSummaryCard from '@/components/common/ModuleSummaryCard.vue'
import { normalizeEventItem } from '@/composables/useIntelligenceData'

const DETAIL_CACHE_VERSION = '2026-04-09-rich-detail-v4'

const dataLeakEvents = ref([])
const dataLeakSummary = ref([])
const categoryOptions = ref([])
const totalEvents = ref(0)
const eventsLoading = ref(false)
const eventsError = ref('')
const route = useRoute()
const router = useRouter()

const currentPage = ref(1)
const pageSize = ref(10)
const categoryFilter = ref('')
const searchValue = ref('')
const listStateKey = computed(() => `list-state:${route.path}`)
let refreshTimer = null
let requestTimer = null
let requestController = null
let pageReady = false

async function loadDataLeakPage() {
  requestController?.abort()
  const controller = new AbortController()
  requestController = controller
  eventsLoading.value = true
  eventsError.value = ''

  const params = new URLSearchParams({
    page: String(currentPage.value),
    page_size: String(pageSize.value),
  })
  if (categoryFilter.value) {
    params.set('category', categoryFilter.value)
  }
  if (searchValue.value.trim()) {
    params.set('keyword', searchValue.value.trim())
  }

  try {
    const response = await fetch(`/api/data-leaks?${params.toString()}`, {
      signal: controller.signal,
    })
    if (!response.ok) {
      throw new Error(`API request failed: ${response.status}`)
    }
    const payload = await response.json()
    if (controller.signal.aborted) return

    dataLeakEvents.value = Array.isArray(payload.items) ? payload.items.map(normalizeEventItem) : []
    dataLeakSummary.value = Array.isArray(payload.summary) ? payload.summary : []
    categoryOptions.value = Array.isArray(payload.categories) ? payload.categories : []
    totalEvents.value = Number(payload.total) || 0

    const responsePage = Number(payload.page) || 1
    if (currentPage.value !== responsePage) {
      currentPage.value = responsePage
    }
  } catch (requestError) {
    if (requestError?.name !== 'AbortError') {
      eventsError.value = `分页数据加载失败：${requestError.message}`
    }
  } finally {
    if (requestController === controller) {
      requestController = null
      eventsLoading.value = false
    }
  }
}

function scheduleDataLeakPageLoad(delay = 250) {
  if (requestTimer) {
    window.clearTimeout(requestTimer)
  }
  requestTimer = window.setTimeout(() => {
    requestTimer = null
    loadDataLeakPage()
  }, delay)
}

function viewEventDetail(row) {
  if (!row?.id) return
  sessionStorage.setItem(
    listStateKey.value,
    JSON.stringify({
      currentPage: currentPage.value,
      pageSize: pageSize.value,
      categoryFilter: categoryFilter.value,
      searchValue: searchValue.value,
    })
  )
  sessionStorage.setItem(`event-back:${row.id}`, '/data-leak')
  router.push({ name: 'EventDetail', params: { eventId: row.id }, query: { module: 'data_leak' } })
}

const activeFilters = computed(() => {
  const filters = []

  if (categoryFilter.value) {
    filters.push(`分类: ${categoryFilter.value}`)
  }

  if (searchValue.value.trim()) {
    filters.push(`关键词: ${searchValue.value.trim()}`)
  }

  return filters
})

watch([pageSize, categoryFilter, searchValue], () => {
  if (!pageReady) return
  if (currentPage.value !== 1) {
    currentPage.value = 1
    return
  }
  scheduleDataLeakPageLoad()
})

watch(currentPage, () => {
  if (pageReady) {
    scheduleDataLeakPageLoad(0)
  }
})

onMounted(() => {
  const raw = sessionStorage.getItem(listStateKey.value)
  if (raw) {
    try {
      const payload = JSON.parse(raw)
      currentPage.value = Number(payload.currentPage) || 1
      pageSize.value = Number(payload.pageSize) || 10
      categoryFilter.value = String(payload.categoryFilter || '')
      searchValue.value = String(payload.searchValue || '')
    } catch {
      sessionStorage.removeItem(listStateKey.value)
    }
  }

  pageReady = true
  loadDataLeakPage()
  refreshTimer = window.setInterval(loadDataLeakPage, 15000)
})

onBeforeUnmount(() => {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
  if (requestTimer) {
    window.clearTimeout(requestTimer)
    requestTimer = null
  }
  requestController?.abort()
  requestController = null
})
</script>

<style scoped lang="scss">
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
}

.summary-grid--compact {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.content-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 22px;
}

.table-shell {
  margin-top: 18px;
}

.event-table {
  width: 100%;
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

@media (max-width: 1440px) {
  .summary-grid,
  .summary-grid--compact {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 767px) {
  .summary-grid,
  .summary-grid--compact {
    grid-template-columns: 1fr;
  }

  .table-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
