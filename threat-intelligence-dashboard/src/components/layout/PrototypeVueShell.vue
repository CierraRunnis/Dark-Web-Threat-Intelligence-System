<template>
  <div
    ref="shellRoot"
    class="prototype-screen prototype-vue-shell"
    :class="pageClass"
    @click="handleNavigation"
  >
    <a class="skip-link" href="#prototype-vue-content">跳到主要内容</a>
    <div class="app-shell sidebar-collapsed">
      <aside class="app-sidebar">
        <a class="brand" href="/">
          <span class="brand-mark" aria-hidden="true">
            <img src="/assets/xuanjian-mark.svg?v=8" alt="">
          </span>
          <span class="brand-copy">
            <strong>玄鉴</strong>
            <span>XUANJIAN INTELLIGENCE</span>
          </span>
        </a>
        <nav class="sidebar-nav" aria-label="主导航"></nav>
        <div class="sidebar-footer"></div>
      </aside>
      <button class="sidebar-backdrop" data-sidebar-toggle aria-label="关闭导航"></button>

      <div class="app-stage">
        <header class="app-header">
          <button class="btn btn-secondary icon-btn menu-button" data-sidebar-toggle aria-label="打开导航">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div class="header-actions">
            <span class="app-version">版本 <strong>v20260831</strong></span>
            <span class="avatar">个人</span>
          </div>
        </header>

        <main class="app-main prototype-vue-main" id="prototype-vue-content">
          <div class="prototype-vue-content">
            <slot />
          </div>
        </main>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { initializePrototype } from '@/prototype/runtime'
import '@/prototype/styles.css'
import '@/prototype/integration.css'

const props = defineProps({
  pageClass: {
    type: String,
    default: '',
  },
  pageId: {
    type: String,
    default: 'vue-screen',
  },
})

const router = useRouter()
const shellRoot = ref(null)
let disposeRuntime = null

function handleNavigation(event) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  const link = event.target.closest('a[href]')
  if (!link || !shellRoot.value?.contains(link) || link.hasAttribute('download') || link.target === '_blank') return
  const href = link.getAttribute('href')
  if (!href || href.startsWith('#') || /^(mailto:|tel:|javascript:)/i.test(href)) return
  const url = new URL(href, window.location.href)
  if (url.origin !== window.location.origin) return
  event.preventDefault()
  router.push(`${url.pathname}${url.search}${url.hash}`)
}

onMounted(() => {
  document.body.dataset.prototypePage = props.pageId
  disposeRuntime = initializePrototype(shellRoot.value)
})

onBeforeUnmount(() => {
  disposeRuntime?.()
  disposeRuntime = null
  if (document.body.dataset.prototypePage === props.pageId) {
    delete document.body.dataset.prototypePage
  }
})
</script>

<style scoped>
.prototype-vue-content {
  min-width: 0;
}
</style>
