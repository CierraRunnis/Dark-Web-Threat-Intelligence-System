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

          <div class="ti-table-shell table-shell">
            <el-table class="event-table" :data="pagedEvents" style="width: 100%" table-layout="auto">
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
            <div class="table-footer__note">当前展示 {{ pagedEvents.length }} 条，事件分类与追踪渠道摘要模块已移除。</div>
            <el-pagination
              v-model:current-page="currentPage"
              v-model:page-size="pageSize"
              :page-sizes="[10, 20, 50, 100]"
              :total="filteredEvents.length"
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
import { useRoute, useRouter } from 'vue-router'
import EventTableToolbar from '@/components/common/EventTableToolbar.vue'
import ModuleSummaryCard from '@/components/common/ModuleSummaryCard.vue'
import { useIntelligenceData } from '@/composables/useIntelligenceData'

const DETAIL_CACHE_VERSION = '2026-04-08-rich-detail-v1'

const { data } = useIntelligenceData()
const dataLeakEvents = computed(() => data.value.dataLeakEvents || [])
const dataLeakSummary = computed(() => data.value.dataLeakSummary || [])
const route = useRoute()
const router = useRouter()

const currentPage = ref(1)
const pageSize = ref(10)
const categoryFilter = ref('')
const searchValue = ref('')
const listStateKey = computed(() => `list-state:${route.path}`)

const categoryOptions = computed(() => [...new Set(dataLeakEvents.value.map((item) => item.category))])

function parseSortTime(value) {
  if (!value) return Number.NEGATIVE_INFINITY
  const normalized = String(value).trim().replace(' ', 'T')
  const parsed = Date.parse(normalized)
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed
}

const sortedEvents = computed(() => {
  return [...dataLeakEvents.value].sort((left, right) => {
    return parseSortTime(right.updatedTimeRaw || right.disclosureTimeRaw || right.disclosureTime) - parseSortTime(left.updatedTimeRaw || left.disclosureTimeRaw || left.disclosureTime)
  })
})

const filteredEvents = computed(() => {
  return sortedEvents.value.filter((item) => {
    const matchesCategory = !categoryFilter.value || item.category === categoryFilter.value
    const keyword = searchValue.value.trim().toLowerCase()
    const matchesKeyword =
      !keyword ||
      [item.title, item.originalTitle, item.attacker, item.region].some((field) => String(field || '').toLowerCase().includes(keyword))

    return matchesCategory && matchesKeyword
  })
})

const pagedEvents = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredEvents.value.slice(start, start + pageSize.value)
})

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
  sessionStorage.setItem(`event-detail:${row.id}`, JSON.stringify({ ...row, __cacheVersion: DETAIL_CACHE_VERSION }))
  sessionStorage.setItem(`event-back:${row.id}`, '/data-leak')
  router.push({ name: 'EventDetail', params: { eventId: row.id } })
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

watch([filteredEvents, pageSize], () => {
  const maxPage = Math.max(1, Math.ceil(filteredEvents.value.length / pageSize.value))
  if (currentPage.value > maxPage) {
    currentPage.value = maxPage
  }
  if (currentPage.value < 1) {
    currentPage.value = 1
  }
})

onMounted(() => {
  const raw = sessionStorage.getItem(listStateKey.value)
  if (!raw) return
  try {
    const payload = JSON.parse(raw)
    currentPage.value = Number(payload.currentPage) || 1
    pageSize.value = Number(payload.pageSize) || 10
    categoryFilter.value = String(payload.categoryFilter || '')
    searchValue.value = String(payload.searchValue || '')
  } catch {
    sessionStorage.removeItem(listStateKey.value)
  }
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
