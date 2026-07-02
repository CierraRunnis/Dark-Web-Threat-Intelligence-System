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
      <div
        v-show="!shell.state.sidebarCollapsed"
        class="sidebar__version"
        :class="{ 'sidebar__version--update': versionStatus?.update_available }"
      >
        <div class="sidebar__version-head">
          <span class="sidebar__version-label">版本信息</span>
          <el-icon v-if="versionStatus?.update_available" class="sidebar__version-icon sidebar__version-icon--warning">
            <WarningFilled />
          </el-icon>
          <el-icon v-else class="sidebar__version-icon">
            <CircleCheck />
          </el-icon>
        </div>
        <strong>{{ versionTitle }}</strong>
        <p>{{ versionDescription }}</p>
        <a v-if="versionStatus?.update_available && versionStatus?.compare_url" :href="versionStatus.compare_url" target="_blank" rel="noreferrer">
          查看 main 更新
        </a>
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useShellLayout } from '@/composables/useShellLayout'

const route = useRoute()
const shell = useShellLayout()
const VERSION_CHECK_INTERVAL_MS = 5 * 60 * 1000
const versionStatus = ref(null)
const versionLoading = ref(false)
const versionError = ref('')
let versionTimer = null

const navTree = [
  { type: 'item', path: '/', title: '总览', icon: 'DataLine' },
  { type: 'item', path: '/ransomware', title: '勒索情报', icon: 'Lock' },
  { type: 'item', path: '/data-leak', title: '数据泄露情报', icon: 'Document' },
  { type: 'item', path: '/vulnerability-alerts', title: '漏洞预警', icon: 'WarningFilled' },
  { type: 'item', path: '/threat-situation', title: '威胁态势', icon: 'TrendCharts' },
  { type: 'item', path: '/collector-control', title: '采集控制', icon: 'VideoPlay' },
  {
    type: 'group',
    key: 'document-exposure',
    title: '文件监测',
    icon: 'Files',
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

const versionTitle = computed(() => {
  if (versionLoading.value && !versionStatus.value) return '检查中'
  if (versionError.value && !versionStatus.value) return '检查失败'
  if (versionStatus.value?.update_available) return '发现新版本'
  return `当前 ${versionStatus.value?.current?.short_commit || 'local'}`
})

const versionDescription = computed(() => {
  if (versionError.value && !versionStatus.value) return versionError.value
  if (!versionStatus.value) return '正在检查 GitHub main 分支'
  const current = versionStatus.value.current?.short_commit || 'local'
  const latest = versionStatus.value.latest?.short_commit || '-'
  if (versionStatus.value.update_available) return `本地 ${current} / main ${latest}`
  return `main 分支已同步 · ${latest || current}`
})

async function loadVersionStatus() {
  if (versionLoading.value) return
  versionLoading.value = true
  versionError.value = ''
  try {
    const response = await fetch('/api/system/version')
    if (!response.ok) throw new Error(`版本检查失败：${response.status}`)
    versionStatus.value = await response.json()
  } catch (error) {
    versionError.value = error.message || '无法检查 GitHub 更新'
  } finally {
    versionLoading.value = false
  }
}

onMounted(() => {
  loadVersionStatus()
  versionTimer = window.setInterval(loadVersionStatus, VERSION_CHECK_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (versionTimer) window.clearInterval(versionTimer)
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
  overflow-x: hidden;
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
  overflow-x: hidden;
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

.sidebar__version {
  margin-bottom: 12px;
  padding: 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.62);
  border: 1px solid var(--ti-border-soft);
}

.sidebar__version--update {
  border-color: rgba(232, 128, 48, 0.32);
  background: rgba(255, 248, 238, 0.86);
}

.sidebar__version-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.sidebar__version-label {
  display: inline-block;
  margin-bottom: 6px;
  color: var(--ti-accent-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.sidebar__version-icon {
  color: var(--ti-success-strong);
  font-size: 15px;
}

.sidebar__version-icon--warning {
  color: var(--ti-warning-strong);
}

.sidebar__version strong {
  display: block;
  color: var(--ti-text-primary);
  font-size: 14px;
  line-height: 1.4;
}

.sidebar__version p {
  margin-top: 4px;
  color: var(--ti-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.sidebar__version a {
  display: inline-flex;
  margin-top: 8px;
  color: var(--ti-primary);
  font-size: 12px;
  font-weight: 700;
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
  .sidebar__version,
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
