<template>
  <aside class="sidebar" :class="{ collapsed: shell.state.sidebarCollapsed }">
    <div class="sidebar__brand">
      <div class="sidebar__brand-mark">
        <el-icon><Monitor /></el-icon>
      </div>
      <div v-show="!shell.state.sidebarCollapsed" class="sidebar__brand-text">
        <strong>Threat Intel</strong>
        <span>监控台 / Editorial View</span>
      </div>
    </div>

    <nav class="sidebar__nav">
      <router-link
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        class="sidebar__item"
        :class="{ active: $route.path === item.path }"
      >
        <div class="sidebar__item-main">
          <el-icon class="sidebar__item-icon">
            <component :is="item.icon" />
          </el-icon>
          <div v-show="!shell.state.sidebarCollapsed" class="sidebar__item-text">
            <span class="sidebar__item-title">{{ item.title }}</span>
            <span class="sidebar__item-note">{{ item.note }}</span>
          </div>
        </div>
        <StatusBadge
          v-show="!shell.state.sidebarCollapsed"
          :label="item.badge"
          :tone="item.tone"
          :dot="false"
        />
      </router-link>
    </nav>

    <div class="sidebar__footer">
      <div v-show="!shell.state.sidebarCollapsed" class="sidebar__watch">
        <span class="sidebar__watch-label">监控范围</span>
        <p>42 国 / 18 行业 / 126 点位</p>
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
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import router from '@/router'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useShellLayout } from '@/composables/useShellLayout'

const $route = useRoute()
const shell = useShellLayout()

const navMeta = {
  '/': { note: '总览摘要与联动事件', badge: '今日', tone: 'primary' },
  '/ransomware': { note: '披露事件与团伙活跃度', badge: '高热', tone: 'danger' },
  '/data-leak': { note: '泄露规模与敏感类型', badge: '更新', tone: 'warning' },
  '/vulnerability-alerts': { note: '公开源高危漏洞与利用状态', badge: '预警', tone: 'danger' },
  '/threat-situation': { note: '区域热区与告警流', badge: '态势', tone: 'success' },
  '/collector-control': { note: '任务触发与站点健康', badge: '控制', tone: 'primary' }
}

const navItems = computed(() =>
  router
    .getRoutes()
    .filter((route) => route.meta?.title && !route.meta?.hidden)
    .map((route) => ({
      path: route.path,
      title: route.meta.title,
      icon: route.meta.icon,
      ...navMeta[route.path]
    }))
)
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

.sidebar__brand-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar__brand-text strong {
  color: var(--ti-text-primary);
  font-size: 16px;
}

.sidebar__brand-text span {
  color: var(--ti-text-muted);
  font-size: 12px;
}

.sidebar__nav {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
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

.sidebar__item:hover {
  transform: translateX(2px);
  border-color: var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.56);
  color: var(--ti-text-primary);
}

.sidebar__item.active {
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

.sidebar__item-icon {
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

.sidebar__item-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.sidebar__item-title {
  color: var(--ti-text-primary);
  font-size: 14px;
  font-weight: 700;
}

.sidebar__item-note {
  color: var(--ti-text-muted);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
  .sidebar__watch {
    display: none !important;
  }

  .sidebar__item {
    justify-content: center;
    padding-left: 8px;
    padding-right: 8px;
  }

  .sidebar__collapse {
    width: 100%;
  }
}
</style>
