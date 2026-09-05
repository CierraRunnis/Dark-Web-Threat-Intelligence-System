<template>
  <aside class="sidebar" :class="{ collapsed: shell.state.sidebarCollapsed }">
    <div class="sidebar__brand">
      <div class="sidebar__brand-mark">
        <img src="/assets/xuanjian-mark.svg" alt="" />
      </div>
      <div class="sidebar__brand-text">
        <strong>玄鉴</strong>
        <small>XUANJIAN INTELLIGENCE</small>
      </div>
    </div>

    <nav class="sidebar__nav">
      <template v-for="item in visibleNavTree" :key="item.key || item.path">
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
            <div class="sidebar__item-text">
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
              <div class="sidebar__item-text">
                <span class="sidebar__item-title">{{ item.title }}</span>
              </div>
            </div>
            <div class="sidebar__group-meta">
              <el-icon class="sidebar__group-arrow">
                <component :is="isGroupOpen(item.key) ? 'ArrowDown' : 'ArrowRight'" />
              </el-icon>
            </div>
          </button>

          <div
            v-show="isGroupOpen(item.key)"
            class="sidebar__children"
            :class="{ 'is-open': isGroupOpen(item.key) }"
          >
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
        v-if="isAdmin"
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
        <p v-if="versionDescription">{{ versionDescription }}</p>
        <div class="sidebar__version-actions">
          <a v-if="versionStatus?.compare_url" :href="versionStatus.compare_url" target="_blank" rel="noreferrer">
            {{ versionStatus?.update_available ? '查看版本差异' : '查看正式版本' }}
          </a>
          <button type="button" :disabled="versionLoading" @click="loadVersionStatus(true)">
            {{ versionLoading ? '检查中…' : '立即检查' }}
          </button>
        </div>
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
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useShellLayout } from '@/composables/useShellLayout'
import { useAuth } from '@/composables/useAuth'
import { MODULE_KEYS } from '@/config/permissions'

const route = useRoute()
const shell = useShellLayout()
const { isAdmin, canAccessModule } = useAuth()
const VERSION_CHECK_INTERVAL_MS = 5 * 60 * 1000
const versionStatus = ref(null)
const versionLoading = ref(false)
const versionError = ref('')
let versionTimer = null

const navTree = [
  { type: 'item', moduleKey: MODULE_KEYS.DASHBOARD, path: '/', title: '总览', icon: 'DataLine' },
  { type: 'item', moduleKey: MODULE_KEYS.RANSOMWARE, path: '/ransomware', title: '勒索情报', icon: 'Lock' },
  { type: 'item', moduleKey: MODULE_KEYS.DATA_LEAK, path: '/data-leak', title: '数据泄露情报', icon: 'Document' },
  { type: 'item', moduleKey: MODULE_KEYS.VULNERABILITY_ALERTS, path: '/vulnerability-alerts', title: '漏洞预警', icon: 'WarningFilled' },
  { type: 'item', moduleKey: MODULE_KEYS.COLLECTOR_CONTROL, path: '/collector-control', title: '采集控制', icon: 'VideoPlay' },
  {
    type: 'group',
    moduleKey: MODULE_KEYS.FILE_MONITORING,
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
  { type: 'item', adminOnly: true, path: '/settings/data-migration', title: '数据迁移', icon: 'Switch' },
  { type: 'item', adminOnly: true, path: '/account-management', title: '账号管理', icon: 'User' },
]

const visibleNavTree = computed(() => navTree.filter((item) => (
  item.adminOnly ? isAdmin.value : canAccessModule(item.moduleKey)
)))


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
    for (const item of visibleNavTree.value) {
      if (item.type === 'group' && isGroupActive(item) && !isGroupOpen(item.key)) {
        expandedGroups.value = [...expandedGroups.value, item.key]
      }
    }
  },
  { immediate: true },
)

const versionTitle = computed(() => {
  if (versionError.value) return '检查失败'
  if (versionLoading.value && !versionStatus.value) return '检查中'
  if (versionStatus.value?.update_available) return '发现新版本'
  return currentVersionLabel.value
})

const versionDescription = computed(() => {
  if (versionError.value) return versionError.value
  if (!versionStatus.value) return '正在检查 GitHub 正式版本'
  const branch = versionStatus.value.branch || versionStatus.value.latest?.branch || '正式发布分支'
  const latest = versionStatus.value.latest?.version
    || versionStatus.value.latest?.short_commit
    || '-'
  if (versionStatus.value.update_available) {
    return `当前 ${currentVersionLabel.value}，${branch} 已发布 ${latest}`
  }
  return `${branch} · ${latest}`
})

const currentVersionLabel = computed(() => (
  versionStatus.value?.current?.version
  || versionStatus.value?.current?.short_commit
  || 'local'
))

async function loadVersionStatus(force = false) {
  if (!isAdmin.value || versionLoading.value) return
  versionLoading.value = true
  versionError.value = ''
  try {
    const response = await fetch(`/api/system/version${force ? '?force=true' : ''}`, { cache: 'no-store' })
    if (!response.ok) throw new Error(`版本检查失败：${response.status}`)
    versionStatus.value = await response.json()
    if (versionStatus.value.status === 'error') {
      throw new Error(versionStatus.value.error || versionStatus.value.message || '无法检查 GitHub 正式版本')
    }
  } catch (error) {
    versionError.value = error.message || '无法检查 GitHub 正式版本'
  } finally {
    versionLoading.value = false
  }
}

function stopVersionChecks() {
  if (versionTimer) window.clearInterval(versionTimer)
  versionTimer = null
}

function startVersionChecks() {
  loadVersionStatus()
  versionTimer = window.setInterval(loadVersionStatus, VERSION_CHECK_INTERVAL_MS)
}

watch(isAdmin, (enabled) => {
  stopVersionChecks()
  if (enabled) startVersionChecks()
}, { immediate: true })

onBeforeUnmount(() => {
  stopVersionChecks()
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
  overflow-x: hidden;
  transition:
    width 0.18s ease,
    transform 0.2s ease,
    box-shadow 0.18s ease;
}

.sidebar.collapsed {
  width: var(--ti-sidebar-collapsed);
}

.sidebar.collapsed .sidebar__brand-text,
.sidebar.collapsed .sidebar__item-text,
.sidebar.collapsed .sidebar__group-meta,
.sidebar.collapsed .sidebar__children,
.sidebar.collapsed .sidebar__version {
  display: none !important;
}

@media (min-width: 901px) {
  .sidebar.collapsed {
    overflow: hidden;
    box-shadow: 4px 0 14px rgba(1, 10, 17, 0.12);
  }

  .sidebar.collapsed:is(:hover, :focus-within) {
    width: var(--ti-sidebar-width);
    box-shadow: 12px 0 28px rgba(1, 10, 17, 0.24);
  }

  .sidebar.collapsed .sidebar__brand {
    padding-inline: 11px;
  }

  .sidebar.collapsed .sidebar__nav {
    padding-inline: 8px;
    overflow: hidden;
  }

  .sidebar.collapsed .sidebar__item {
    justify-content: center;
    padding-inline: 0;
  }

  .sidebar.collapsed .sidebar__footer {
    padding-inline: 0;
  }

  .sidebar.collapsed:is(:hover, :focus-within) .sidebar__brand {
    padding-inline: 15px;
  }

  .sidebar.collapsed:is(:hover, :focus-within) .sidebar__brand-text {
    display: grid !important;
  }

  .sidebar.collapsed:is(:hover, :focus-within) .sidebar__nav {
    overflow-y: auto;
  }

  .sidebar.collapsed:is(:hover, :focus-within) .sidebar__item {
    justify-content: space-between;
    padding-inline: 7px;
  }

  .sidebar.collapsed:is(:hover, :focus-within) .sidebar__item-text {
    display: block !important;
  }

  .sidebar.collapsed:is(:hover, :focus-within) .sidebar__group-meta {
    display: inline-flex !important;
  }

  .sidebar.collapsed:is(:hover, :focus-within) .sidebar__children.is-open {
    display: grid !important;
  }

  .sidebar.collapsed:is(:hover, :focus-within) .sidebar__version {
    display: block !important;
  }

  .sidebar.collapsed:is(:hover, :focus-within) .sidebar__footer {
    padding-inline: 12px;
  }
}
.sidebar__brand {
  display: flex;
  align-items: center;
}

.sidebar__brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.sidebar__brand-text {
  display: grid;
  min-width: 0;
}

.sidebar__brand-text small {
  font-weight: 700;
}

.sidebar__nav {
  display: flex;
  flex: 1;
  flex-direction: column;
  overflow-y: auto;
  overflow-x: hidden;
}

.sidebar__group {
  display: grid;
}

.sidebar__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
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

.sidebar__item-main {
  display: flex;
  align-items: center;
  min-width: 0;
}

.sidebar__item-icon,
.sidebar__child-icon {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.sidebar__group-meta {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.sidebar__group-arrow {
  font-size: 14px;
}

.sidebar__children {
  display: grid;
}

.sidebar__child {
  display: flex;
  align-items: center;
  transition:
    background 0.2s ease,
    color 0.2s ease,
    transform 0.2s ease;
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
  line-height: 1.4;
}

.sidebar__version p {
  margin-top: 4px;
  line-height: 1.5;
}

.sidebar__version-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
}

.sidebar__version-actions a {
  display: inline-flex;
  font-size: 12px;
  font-weight: 700;
}

.sidebar__version-actions button {
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--ti-accent-strong);
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.sidebar__version-actions button:disabled {
  cursor: wait;
  opacity: 0.6;
}

.sidebar__collapse {
  width: 100%;
  border: 1px solid var(--ti-border-default);
  cursor: pointer;
}

@media (max-width: 767px) {
  .sidebar {
    width: var(--ti-sidebar-width);
    padding-left: 10px;
    padding-right: 10px;
    box-shadow: 14px 0 28px rgba(1, 10, 17, 0.2);
  }

  .sidebar.collapsed {
    width: var(--ti-sidebar-collapsed);
    box-shadow: none;
  }

  .sidebar.collapsed .sidebar__item {
    justify-content: center;
    padding-left: 8px;
    padding-right: 8px;
  }
}
</style>
