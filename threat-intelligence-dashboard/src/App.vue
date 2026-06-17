<template>
  <div class="app-container" :class="{ 'sidebar-collapsed': shell.state.sidebarCollapsed }">
    <Sidebar />
    <div class="main-content">
      <Header />
      <main class="page-content">
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

const shell = provideShellLayout()
</script>

<style lang="scss">
@use '@/styles/global.scss';

.app-container {
  display: flex;
  min-height: 100vh;
  background: #ffffff;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  margin-left: var(--ti-sidebar-width);
  background: #ffffff;
  transition: margin-left 0.3s ease;
}

.app-container.sidebar-collapsed .main-content {
  margin-left: var(--ti-sidebar-collapsed);
}

.page-content {
  flex: 1;
  padding: 28px;
  overflow-y: auto;
  background: #ffffff;
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
    margin-left: var(--ti-sidebar-collapsed);
  }

  .page-content {
    padding: 18px;
  }
}
</style>
