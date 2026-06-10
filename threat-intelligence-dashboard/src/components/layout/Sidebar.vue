<template>
  <aside class="sidebar" :class="{ collapsed: shell.state.sidebarCollapsed }">
    <div class="sidebar__brand">
      <div class="sidebar__brand-mark">
        <el-icon><Monitor /></el-icon>
      </div>
      <div v-show="!shell.state.sidebarCollapsed" class="sidebar__brand-text">
        <strong>公网信息泄露监测平台</strong>
      </div>
    </div>

    <nav class="sidebar__nav">
      <template v-for="item in navTree" :key="item.key || item.path">
        <router-link
          v-if="item.type === 'item'"
          :to="item.path"
          class="sidebar__item"
          :class="{ active: isRouteActive(item.path) }"
        >
          <div class="sidebar__item-main">
            <el-icon class="sidebar__item-icon">
              <component :is="item.icon" />
            </el-icon>
            <div v-show="!shell.state.sidebarCollapsed" class="sidebar__item-text">
              <span class="sidebar__item-title">{{ item.title }}</span>
            </div>
          </div>
          <StatusBadge
            v-show="!shell.state.sidebarCollapsed"
            :label="item.badge"
            :tone="item.tone"
            :dot="false"
          />
        </router-link>

        <div v-else class="sidebar__group" :class="{ active: isGroupActive(item) }">
          <button class="sidebar__item sidebar__item--button" type="button" @click="toggleGroup(item.key)">
            <div class="sidebar__item-main">
              <el-icon class="sidebar__item-icon">
                <component :is="item.icon" />
              </el-icon>
              <div v-show="!shell.state.sidebarCollapsed" class="sidebar__item-text">
                <span class="sidebar__item-title">{{ item.title }}</span>
              </div>
            </div>
            <div v-show="!shell.state.sidebarCollapsed" class="sidebar__group-meta">
              <StatusBadge :label="item.badge" :tone="item.tone" :dot="false" />
              <el-icon class="sidebar__group-arrow">
                <component :is="isGroupOpen(item.key) ? 'ArrowDown' : 'ArrowRight'" />
              </el-icon>
            </div>
          </button>

          <div v-show="!shell.state.sidebarCollapsed && isGroupOpen(item.key)" class="sidebar__children">
            <router-link
              v-for="child in item.children"
              :key="child.path"
              :to="child.path"
              class="sidebar__child"
              :class="{ active: isRouteActive(child.path) }"
            >
              <el-icon class="sidebar__child-icon">
                <component :is="child.icon" />
              </el-icon>
              <span>{{ child.title }}</span>
            </router-link>
          </div>
        </div>
      </template>
    </nav>

    <div class="sidebar__footer">
      <div v-show="!shell.state.sidebarCollapsed" class="sidebar__watch">
        <span class="sidebar__watch-label">监测范围</span>
        <p>{{ monitoringRangeText }}</p>
      </div>
      <button class="sidebar__collapse" @click="shell.toggleSidebar">
        <el-icon>
          <Fold v-if="!shell.state.sidebarCollapsed" />
          <Expand v-else />
        </el-icon>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useShellLayout } from '@/composables/useShellLayout'
import { useIntelligenceData } from '@/composables/useIntelligenceData'

const route = useRoute()
const shell = useShellLayout()
const { data } = useIntelligenceData()

const navTree = [
  { type: 'item', path: '/', title: '总览', icon: 'DataLine', badge: '今日', tone: 'primary' },
  { type: 'item', path: '/ransomware', title: '勒索情报', icon: 'Lock', badge: '高热', tone: 'danger' },
  { type: 'item', path: '/data-leak', title: '数据泄露情报', icon: 'Document', badge: '更新', tone: 'warning' },
  { type: 'item', path: '/vulnerability-alerts', title: '漏洞预警', icon: 'WarningFilled', badge: '预警', tone: 'danger' },
  { type: 'item', path: '/threat-situation', title: '威胁态势', icon: 'TrendCharts', badge: '态势', tone: 'success' },
  { type: 'item', path: '/collector-control', title: '采集控制', icon: 'VideoPlay', badge: '控制', tone: 'primary' },
  {
    type: 'group',
    key: 'document-exposure',
    title: '文件监测',
    icon: 'Files',
    badge: '4项',
    tone: 'warning',
    children: [
      { path: '/document-exposure/search-engine', title: '搜索引擎监测', icon: 'Search' },
      { path: '/document-exposure/netdisk', title: '网盘监测', icon: 'Share' },
      { path: '/document-exposure/document-library', title: '文库监测', icon: 'Files' },
      { path: '/document-exposure/code-monitoring', title: '代码监测', icon: 'Connection' },
    ],
  },
]

const expandedGroups = ref(['document-exposure'])

function isRouteActive(path) {
  if (path === '/') return route.path === '/'
  return route.path === path || route.path.startsWith(`${path}/`)
}

function isGroupActive(group) {
  if (group.key === 'document-exposure') {
    return route.path.startsWith('/document-exposure/')
  }
  return group.children?.some((child) => isRouteActive(child.path))
}

function isGroupOpen(groupKey) {
  return expandedGroups.value.includes(groupKey)
}

function toggleGroup(groupKey) {
  if (isGroupOpen(groupKey)) {
    expandedGroups.value = expandedGroups.value.filter((item) => item !== groupKey)
    return
  }
  expandedGroups.value = [...expandedGroups.value, groupKey]
}

watch(
  () => route.path,
  () => {
    for (const item of navTree) {
      if (item.type === 'group' && isGroupActive(item) && !isGroupOpen(item.key)) {
        expandedGroups.value = [...expandedGroups.value, item.key]
      }
    }
  },
  { immediate: true },
)

const monitoringRangeText = computed(() => {
  const dataLeakEvents = Array.isArray(data.value.dataLeakEvents) ? data.value.dataLeakEvents : []
  const ransomwareEvents = Array.isArray(data.value.ransomwareEvents) ? data.value.ransomwareEvents : []
  const vulnerabilityEvents = Array.isArray(data.value.vulnerabilityEvents) ? data.value.vulnerabilityEvents : []
  const documentExposureEvents = Array.isArray(data.value.documentExposureEvents) ? data.value.documentExposureEvents : []
  const allEvents = [...dataLeakEvents, ...ransomwareEvents, ...vulnerabilityEvents, ...documentExposureEvents]

  const countries = new Set()
  const industries = new Set()
  for (const item of allEvents) {
    const country = String(item.country || '').trim()
    const industry = String(item.industry || '').trim()
    if (country && country !== '未知') countries.add(country)
    if (industry && !['未知', '其他'].includes(industry)) industries.add(industry)
  }

  return `${countries.size} 国家 / ${industries.size} 行业 / ${allEvents.length} 事件`
})
</script>

<style lang="scss" scoped>
.sidebar {
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  z-index: 100;
  display: flex;
  flex-direction: column;
  width: var(--ti-sidebar-width);
  padding: 18px 14px;
  border-right: 1px solid rgba(87, 97, 123, 0.08);
  background: rgba(255, 255, 255, 0.98);
  backdrop-filter: blur(16px);
  transition: width 0.3s ease;
}

.sidebar.collapsed {
  width: var(--ti-sidebar-collapsed);
}

.sidebar__brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
  padding: 10px 8px 16px;
  border-bottom: 1px solid var(--ti-border-soft);
}

.sidebar__brand-mark {
  display: inline-flex;
  width: 42px;
  height: 42px;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  background: linear-gradient(135deg, var(--ti-primary-soft), rgba(244, 248, 255, 0.96));
  color: var(--ti-primary);
  font-size: 20px;
}

.sidebar__brand-text strong {
  color: var(--ti-text-primary);
  font-size: 16px;
}

.sidebar__nav {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
}

.sidebar__group {
  display: grid;
  gap: 8px;
}

.sidebar__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px 12px;
  border: 1px solid transparent;
  border-radius: 18px;
  color: var(--ti-text-secondary);
  transition:
    transform 0.2s ease,
    background 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease;
}

.sidebar__item--button {
  width: 100%;
  background: transparent;
  cursor: pointer;
}

.sidebar__item:hover,
.sidebar__group.active > .sidebar__item {
  transform: translateX(2px);
  border-color: var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.56);
  color: var(--ti-text-primary);
}

.sidebar__item.active,
.sidebar__group.active > .sidebar__item.sidebar__item--button {
  border-color: rgba(45, 93, 255, 0.16);
  background: linear-gradient(135deg, rgba(237, 242, 255, 0.96), rgba(248, 251, 255, 0.96));
  color: var(--ti-text-primary);
}

.sidebar__item-main {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.sidebar__item-icon,
.sidebar__child-icon {
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.84);
  color: var(--ti-accent-strong);
  font-size: 18px;
}

.sidebar__child-icon {
  width: 26px;
  height: 26px;
  border-radius: 10px;
  font-size: 14px;
  background: rgba(45, 93, 255, 0.08);
  color: var(--ti-primary);
}

.sidebar__item-title {
  color: var(--ti-text-primary);
  font-size: 14px;
  font-weight: 700;
}

.sidebar__group-meta {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.sidebar__group-arrow {
  color: var(--ti-text-muted);
  font-size: 14px;
}

.sidebar__children {
  display: grid;
  gap: 6px;
  padding-left: 14px;
}

.sidebar__child {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 8px 12px;
  border-radius: 14px;
  color: var(--ti-text-secondary);
  transition:
    background 0.2s ease,
    color 0.2s ease,
    transform 0.2s ease;
}

.sidebar__child:hover,
.sidebar__child.active {
  background: rgba(45, 93, 255, 0.08);
  color: var(--ti-text-primary);
  transform: translateX(2px);
}

.sidebar__footer {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--ti-border-soft);
}

.sidebar__watch {
  margin-bottom: 12px;
  padding: 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.62);
  border: 1px solid var(--ti-border-soft);
}

.sidebar__watch-label {
  display: inline-block;
  margin-bottom: 6px;
  color: var(--ti-accent-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.sidebar__watch p {
  color: var(--ti-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.sidebar__collapse {
  width: 100%;
  height: 40px;
  border: 1px solid var(--ti-border-default);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  color: var(--ti-text-secondary);
  cursor: pointer;
}

@media (max-width: 767px) {
  .sidebar {
    width: var(--ti-sidebar-collapsed);
    padding-left: 10px;
    padding-right: 10px;
  }

  .sidebar__brand-text,
  .sidebar__item-text,
  .sidebar__watch,
  .sidebar__children {
    display: none !important;
  }

  .sidebar__item {
    justify-content: center;
    padding-left: 8px;
    padding-right: 8px;
  }
}
</style>
