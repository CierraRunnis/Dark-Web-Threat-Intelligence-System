<template>
  <header class="header">
    <div class="header__intro">
      <div class="header__kicker">
        <span>{{ pageMeta.kicker }}</span>
        <span class="header__dot" />
        <span>{{ monitoringStatus.dateLabel }}</span>
      </div>
      <h1 class="header__title">{{ $route.meta.title }}</h1>
      <p class="header__subtitle">{{ pageMeta.subtitle }}</p>
    </div>

    <div class="header__right">
      <div class="header__status-strip">
        <div class="header__status-item">
          <span class="header__status-label">{{ monitoringStatus.refreshedLabel }}</span>
          <span class="header__status-value">{{ monitoringStatus.refreshedValue }}</span>
        </div>
        <div class="header__status-item">
          <span class="header__status-label">{{ monitoringStatus.statusLabel }}</span>
          <StatusBadge :label="monitoringStatus.statusValue" tone="success" />
        </div>
      </div>

      <div class="header__actions">
        <div class="header__buttons">
          <el-badge :value="6" class="header__badge">
            <el-button circle class="header__action-btn">
              <el-icon><Bell /></el-icon>
            </el-button>
          </el-badge>

          <el-button circle class="header__action-btn" @click="shell.toggleSidebar">
            <el-icon>
              <Fold v-if="!shell.state.sidebarCollapsed" />
              <Expand v-else />
            </el-icon>
          </el-button>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useIntelligenceData } from '@/composables/useIntelligenceData'
import { useShellLayout } from '@/composables/useShellLayout'

const $route = useRoute()
const shell = useShellLayout()
const { data } = useIntelligenceData()

const monitoringStatus = computed(() => data.value.monitoringStatus || {})
const routeHeaderMeta = computed(() => data.value.routeHeaderMeta || {})
const pageMeta = computed(() => routeHeaderMeta.value[$route.path] || routeHeaderMeta.value['/'] || {})
</script>

<style lang="scss" scoped>
.header {
  position: sticky;
  top: 0;
  z-index: 50;
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-start;
  min-height: var(--ti-header-height);
  padding: 22px 28px 20px;
  border-bottom: 1px solid rgba(87, 97, 123, 0.08);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(16px);
}

.header__intro {
  max-width: 760px;
}

.header__kicker {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--ti-accent-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.header__dot {
  width: 4px;
  height: 4px;
  border-radius: 999px;
  background: currentColor;
}

.header__title {
  margin: 10px 0 6px;
  font-family: var(--ti-font-display);
  font-size: clamp(28px, 3.2vw, 42px);
  line-height: 1;
  letter-spacing: -0.03em;
  color: var(--ti-text-primary);
}

.header__subtitle {
  margin: 0;
  color: var(--ti-text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

.header__right {
  display: flex;
  flex-direction: column;
  gap: 14px;
  align-items: flex-end;
  min-width: 220px;
}

.header__status-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.header__status-item {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 16px;
  border: 1px solid var(--ti-border-soft);
  background: rgba(255, 255, 255, 0.96);
}

.header__status-label {
  color: var(--ti-text-muted);
  font-size: 12px;
}

.header__status-value {
  color: var(--ti-text-primary);
  font-size: 12px;
  font-weight: 600;
}

.header__actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.header__buttons {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header__action-btn {
  width: 42px;
  height: 42px;
  border-color: var(--ti-border-default);
  background: rgba(255, 255, 255, 0.98);
}

@media (max-width: 1200px) {
  .header {
    flex-direction: column;
  }

  .header__right {
    min-width: auto;
    width: 100%;
    align-items: stretch;
  }

  .header__status-strip {
    justify-content: flex-start;
  }

  .header__actions {
    justify-content: flex-end;
  }
}

@media (max-width: 767px) {
  .header {
    padding: 18px 18px 16px;
  }
}
</style>
