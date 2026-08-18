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
          'page-content--prototype': isPrototypeLayout,
        }"
      >
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <PrototypeVueShell
              v-if="isPrototypeVueLayout"
              page-class="page-vue-module"
              :key="prototypeVuePageId"
              :page-id="prototypeVuePageId"
            >
              <component :is="Component" />
            </PrototypeVueShell>
            <component v-else :is="Component" />
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
import PrototypeVueShell from '@/components/layout/PrototypeVueShell.vue'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const shell = provideShellLayout()
const route = useRoute()
const isPrototypeVueLayout = computed(() => route.meta.layout === 'prototype-vue')
const isPrototypeLayout = computed(() => ['prototype', 'prototype-vue'].includes(route.meta.layout))
const isBlankLayout = computed(() => ['blank', 'prototype', 'prototype-vue'].includes(route.meta.layout))
const prototypeVuePageId = computed(() => `vue:${String(route.name || route.path)}`)
</script>

<style lang="scss">
@use '@/styles/global.scss';

.app-container {
  display: grid;
  grid-template-columns: var(--ti-sidebar-width) minmax(0, 1fr);
  min-height: 100vh;
  background: #ffffff;
  transition: grid-template-columns 0.2s ease;
}

.app-container--blank {
  display: block;
}

.main-content {
  grid-column: 2;
  min-width: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  margin-left: 0;
  background: #ffffff;
}

.main-content--blank {
  min-height: 100vh;
  margin-left: 0;
}

.app-container.sidebar-collapsed {
  grid-template-columns: var(--ti-sidebar-collapsed) minmax(0, 1fr);
}

.app-container.sidebar-collapsed .main-content {
  width: 100%;
  margin-left: 0;
}

.app-container .main-content.main-content--blank,
.app-container.sidebar-collapsed .main-content.main-content--blank {
  width: 100%;
  margin-left: 0;
}

.page-content {
  flex: 1;
  padding: 28px;
  overflow-y: auto;
  background: #ffffff;
}

.page-content.page-content--code-monitoring {
  padding: 8px 8px 16px;
}

.page-content.page-content--blank {
  min-height: 100vh;
  padding: 0;
  overflow: hidden;
}

.page-content.page-content--prototype {
  overflow: visible;
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
    width: 100%;
    margin-left: 0;
  }

  .page-content {
    padding: 18px;
  }
}
</style>
