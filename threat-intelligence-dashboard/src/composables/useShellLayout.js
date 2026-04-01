import { computed, inject, provide, reactive } from 'vue'

const shellLayoutKey = Symbol('shell-layout')

export function provideShellLayout() {
  const state = reactive({
    sidebarCollapsed: false
  })

  const shell = {
    state,
    sidebarWidth: computed(() =>
      state.sidebarCollapsed ? 'var(--ti-sidebar-collapsed)' : 'var(--ti-sidebar-width)'
    ),
    toggleSidebar() {
      state.sidebarCollapsed = !state.sidebarCollapsed
    },
    setSidebarCollapsed(value) {
      state.sidebarCollapsed = value
    }
  }

  provide(shellLayoutKey, shell)

  return shell
}

export function useShellLayout() {
  const shell = inject(shellLayoutKey, null)

  if (!shell) {
    throw new Error('useShellLayout must be used within provideShellLayout')
  }

  return shell
}
