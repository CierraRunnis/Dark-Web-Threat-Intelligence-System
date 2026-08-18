<template>
  <div
    ref="screenRoot"
    class="prototype-screen"
    :class="bodyClass"
    @click="handleNavigation"
  ></div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import '@/prototype/styles.css'
import '@/prototype/integration.css'
import '@/prototype/overrides.css'
import '@/prototype/aiAggregation.css'

const screens = import.meta.glob('@/prototype/screens/*.html', {
  query: '?raw',
  import: 'default',
})

const route = useRoute()
const router = useRouter()
const screenRoot = ref(null)
const bodyClass = ref('')
let renderVersion = 0
let disposeRuntime = null
let disposeExposureRuntime = null
let exposureStyleElement = null
let disposeExposureData = null

const exposureFiles = new Set([
  'monitoring.html',
  'netdisk-detail.html',
  'library-detail.html',
  'code-detail.html',
  'settings.html',
])

const screenRoutes = {
  'dashboard.html': '/',
  'intelligence.html': '/intelligence',
  'ai-aggregation.html': '/ai-aggregation',
  'ai-aggregation-templates.html': '/ai-aggregation/templates',
  'ransomware.html': '/ransomware',
  'data-leak.html': '/data-leak',
  'vulnerabilities.html': '/vulnerability-alerts',
  'settings.html': '/settings',
  'collector-sites.html': '/collector-control',
  'collector-sync.html': '/collector-control',
  'collector-runtime.html': '/collector-control',
  'collector-failures.html': '/collector-control/failures',
}

async function screenSource(file) {
  const entry = Object.entries(screens).find(([path]) => path.endsWith(`/screens/${file}`))
  if (!entry) throw new Error(`Prototype screen not found: ${file}`)
  return entry[1]()
}

function rewriteHref(rawHref) {
  if (!rawHref || rawHref.startsWith('#') || /^(https?:|mailto:|tel:)/i.test(rawHref)) return rawHref
  const url = new URL(rawHref, 'https://prototype.local/')
  const file = url.pathname.split('/').pop()
  const id = url.searchParams.get('id') || ''
  if (file === 'index.html') return '/login'
  if (file === 'monitoring.html') {
    const sourceRoute = { library: 'document-library', code: 'code-monitoring' }[url.searchParams.get('source')]
      || url.searchParams.get('source')
      || 'netdisk'
    return `/document-exposure/${sourceRoute}`
  }
  if (file === 'netdisk-detail.html') return `/document-exposure/detail/netdisk_aggregator/${encodeURIComponent(id)}`
  if (file === 'library-detail.html') return `/document-exposure/detail/document_library/${encodeURIComponent(id)}`
  if (file === 'code-detail.html') return `/document-exposure/code-monitoring/detail/${encodeURIComponent(id)}`
  if (file === 'ransomware-detail.html') return `/ransomware/${encodeURIComponent(id)}`
  if (file === 'data-leak-detail.html') return `/data-leak/${encodeURIComponent(id)}`
  if (file === 'vulnerability-detail.html') return `/vulnerability-alerts/${encodeURIComponent(id)}`
  if (file === 'event-detail.html') return `/event/${encodeURIComponent(id)}`
  const path = screenRoutes[file]
  return path ? `${path}${url.search}` : rawHref
}

function handleNavigation(event) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  const link = event.target.closest('a[href]')
  if (!link || !screenRoot.value?.contains(link) || link.hasAttribute('download') || link.target === '_blank') return
  const href = link.getAttribute('href')
  if (!href || href.startsWith('#') || /^(mailto:|tel:|javascript:)/i.test(href)) return
  const url = new URL(href, window.location.href)
  if (url.origin !== window.location.origin) return
  event.preventDefault()
  router.push(`${url.pathname}${url.search}${url.hash}`)
}

async function setExposureStyles(enabled, version = renderVersion) {
  if (!enabled) {
    exposureStyleElement?.remove()
    exposureStyleElement = null
    return
  }
  if (exposureStyleElement) return
  const { default: exposureStyles } = await import('@/prototype/exposure-upstream.css?raw')
  if (version !== renderVersion || !exposureFiles.has(route.meta.screen)) return
  exposureStyleElement = document.createElement('style')
  exposureStyleElement.dataset.prototypeExposureStyles = '1'
  exposureStyleElement.textContent = exposureStyles
  document.head.appendChild(exposureStyleElement)
}

function disposeScreenRuntime() {
  screenRoot.value?.__dataRuntimeAbort?.abort()
  disposeRuntime?.()
  disposeExposureRuntime?.()
  disposeExposureData?.()
  disposeRuntime = null
  disposeExposureRuntime = null
  disposeExposureData = null
  if (screenRoot.value) delete screenRoot.value.__prototypeBeforeLeave
}

async function renderScreen() {
  const version = ++renderVersion
  const file = route.meta.screen
  if (!file) return
  disposeScreenRuntime()

  const source = await screenSource(file)
  if (version !== renderVersion) return
  const parsed = new DOMParser().parseFromString(source, 'text/html')
  parsed.querySelectorAll('script').forEach((script) => script.remove())
  parsed.querySelectorAll('a[href]').forEach((link) => {
    link.setAttribute('href', rewriteHref(link.getAttribute('href')))
  })
  parsed.querySelectorAll('[src]').forEach((node) => {
    const source = node.getAttribute('src')
    if (source?.startsWith('assets/')) node.setAttribute('src', `/${source}`)
  })
  parsed.querySelectorAll('image[href]').forEach((node) => {
    const source = node.getAttribute('href')
    if (source?.startsWith('assets/')) node.setAttribute('href', `/${source}`)
  })

  const exposureScreen = exposureFiles.has(file)
  await setExposureStyles(exposureScreen, version)
  if (version !== renderVersion) return
  bodyClass.value = parsed.body.className
  document.body.dataset.prototypePage = file
  document.body.dataset.prototypeSource = String(route.meta.source || '')
  document.body.dataset.prototypeRecordId = String(
    route.params.eventId || route.params.hitId || route.params.runId || '',
  )
  const monitoringTitle = {
    netdisk: '网盘监测 · 玄鉴',
    library: '文库监测 · 玄鉴',
    code: '代码监测 · 玄鉴',
  }[route.meta.source]
  document.title = monitoringTitle || parsed.title || '玄鉴威胁情报平台'
  await nextTick()
  if (version !== renderVersion || !screenRoot.value) return
  screenRoot.value.innerHTML = parsed.body.innerHTML
  const { initializePrototype } = await import('@/prototype/runtime')
  if (version !== renderVersion || !screenRoot.value) return
  disposeRuntime = initializePrototype(screenRoot.value, { serverControls: !exposureScreen })
  if (exposureScreen) {
    const [{ initializeExposurePrototype }, exposureData] = await Promise.all([
      import('@/prototype/exposureRuntime'),
      import('@/prototype/exposureDataRuntime'),
    ])
    if (version !== renderVersion || !screenRoot.value) return
    disposeExposureData = exposureData.disposeExposureDataRuntime
    disposeExposureRuntime = initializeExposurePrototype(screenRoot.value)
    await exposureData.hydrateExposurePrototypeScreen({ root: screenRoot.value, route, file })
  } else {
    const { hydratePrototypeScreen } = await import('@/prototype/dataRuntime')
    if (version !== renderVersion || !screenRoot.value) return
    await hydratePrototypeScreen({ root: screenRoot.value, route, file })
  }
}

async function invokePrototypeBeforeLeave(to, from) {
  const beforeLeave = screenRoot.value?.__prototypeBeforeLeave
  if (typeof beforeLeave !== 'function') return true
  const result = await beforeLeave({ to, from })
  return result === false ? false : true
}

onBeforeRouteLeave(invokePrototypeBeforeLeave)
onBeforeRouteUpdate(invokePrototypeBeforeLeave)

watch(() => route.fullPath, renderScreen, { immediate: true })
onMounted(renderScreen)


onBeforeUnmount(() => {
  renderVersion += 1
  disposeScreenRuntime()
  setExposureStyles(false)
  delete document.body.dataset.prototypePage
  delete document.body.dataset.prototypeSource
  delete document.body.dataset.prototypeRecordId
})
</script>
