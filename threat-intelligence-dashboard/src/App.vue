<template>
  <div
    class="app-container"
    :class="{ 'sidebar-collapsed': shell.state.sidebarCollapsed, 'app-container--blank': isBlankLayout }"
  >
    <Sidebar v-if="!isBlankLayout" />
    <div class="main-content" :class="{ 'main-content--blank': isBlankLayout }">
      <Header v-if="!isBlankLayout" />
      <main
        class="page-content"
        :class="{
          'page-content--code-monitoring': route.name === 'CodeMonitoringWorkbench',
          'page-content--blank': isBlankLayout,
        }"
      >
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup>
import { provideShellLayout } from '@/composables/useShellLayout'
import Sidebar from '@/components/layout/Sidebar.vue'
import Header from '@/components/layout/Header.vue'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const shell = provideShellLayout()
const route = useRoute()
const isBlankLayout = computed(() => route.meta.layout === 'blank')
</script>

<style lang="scss">
@use '@/styles/global.scss';

.app-container {
  min-height: 100vh;
  width: 100%;
  max-width: 100vw;
  overflow-x: hidden;
  background: #ffffff;
}

.app-container--blank {
  display: block;
}

.main-content {
  min-height: 100vh;
  min-width: 0;
  width: auto;
  max-width: calc(100vw - var(--ti-sidebar-width));
  display: flex;
  flex-direction: column;
  margin-left: var(--ti-sidebar-width);
  background: #ffffff;
  transition: margin-left 0.3s ease;
}

.main-content--blank {
  min-height: 100vh;
  width: 100%;
  max-width: 100vw;
  margin-left: 0;
}

.app-container.sidebar-collapsed .main-content {
  max-width: calc(100vw - var(--ti-sidebar-collapsed));
  margin-left: var(--ti-sidebar-collapsed);
}

.app-container.sidebar-collapsed .main-content--blank {
  max-width: 100vw;
  margin-left: 0;
}

.page-content {
  flex: 1;
  min-width: 0;
  padding: 28px;
  overflow-y: auto;
  overflow-x: hidden;
  background: #ffffff;
}

.page-content.page-content--code-monitoring {
  padding: 8px 8px 16px;
}

.page-content.page-content--blank {
  min-height: 100vh;
  width: 100%;
  padding: 0;
  overflow: hidden;
}

.fade-enter-active,
.fade-leave-active {
  transition:
    opacity 0.22s ease,
    transform 0.22s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

@media (max-width: 1024px) {
  .page-content {
    padding: 22px;
  }
}

@media (max-width: 767px) {
  .main-content {
    max-width: calc(100vw - var(--ti-sidebar-collapsed));
    margin-left: var(--ti-sidebar-collapsed);
  }

  .page-content {
    padding: 18px;
  }
}
</style>
