<template>
  <div class="embedded-browser-page ti-page">
    <section class="embedded-browser-header ti-reveal-up">
      <div>
        <div class="ti-kicker">Embedded Browser Session</div>
        <h2>平台内置浏览器登录</h2>
        <p>在服务器 Linux 环境中启动真实 Chromium，通过页面内浏览器完成登录和安全验证。</p>
      </div>
      <div class="embedded-browser-header__actions">
        <el-button plain @click="returnToPrevious">返回</el-button>
        <el-button type="primary" :loading="saving" :disabled="!sessionId" @click="finishSession">保存会话</el-button>
        <el-button type="danger" plain :loading="closing" :disabled="!sessionId" @click="closeSession">关闭会话</el-button>
      </div>
    </section>

    <section class="embedded-browser-layout">
      <div class="ti-card ti-reveal-up embedded-browser-card">
        <div class="ti-card-header">
          <div>
            <div class="ti-card-title">{{ platformLabel }}</div>
            <div class="ti-card-subtitle">{{ state?.url || '正在创建内置浏览器会话' }}</div>
          </div>
          <div class="browser-tags">
            <el-tag :type="rfbTagType" effect="plain">{{ rfbStatusLabel }}</el-tag>
            <el-tag v-if="sessionId" effect="plain">{{ sessionId.slice(0, 10) }}</el-tag>
          </div>
        </div>
        <div class="ti-card-body">
          <div v-if="state?.rfb_ws_path" ref="browserDesktopRef" class="browser-desktop" />
          <el-empty v-else class="browser-empty" description="等待内置浏览器启动" />
          <div class="browser-footer">
            <span>{{ rfbError || '点击浏览器画面后可以直接输入、滚动和完成二次验证。' }}</span>
            <span>{{ viewportText }}</span>
          </div>
        </div>
      </div>

      <aside class="embedded-browser-side">
        <div class="ti-card ti-reveal-up">
          <div class="ti-card-header">
            <div class="ti-card-title">会话保存</div>
          </div>
          <div class="ti-card-body side-form">
            <el-form label-position="top">
              <el-form-item label="账号标签">
                <el-input v-model="accountLabel" placeholder="例如 GitHub 主账号" clearable />
              </el-form-item>
            </el-form>
            <el-alert
              type="info"
              :closable="false"
              show-icon
              title="保存时机"
              description="登录完成并确认浏览器里已进入账号状态后，再点击保存会话。"
            />
          </div>
        </div>

        <div class="ti-card ti-reveal-up">
          <div class="ti-card-header">
            <div class="ti-card-title">运行状态</div>
          </div>
          <div class="ti-card-body embedded-browser-state">
            <div class="state-row">
              <span>模式</span>
              <strong>{{ state?.mode || '-' }}</strong>
            </div>
            <div class="state-row">
              <span>页面标题</span>
              <strong>{{ state?.title || '-' }}</strong>
            </div>
            <div class="state-row">
              <span>会话文件</span>
              <strong>{{ state?.storage_state_path || '-' }}</strong>
            </div>
          </div>
        </div>
      </aside>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import RFB from '@novnc/novnc'
import { useCodeMonitoringApi } from '@/composables/useCodeMonitoringApi'

const api = useCodeMonitoringApi()
const route = useRoute()
const router = useRouter()

const browserDesktopRef = ref(null)
const state = ref(null)
const sessionId = ref(String(route.query.session_id || '').trim())
const accountLabel = ref('')
const loading = ref(false)
const saving = ref(false)
const closing = ref(false)
const rfbStatus = ref('idle')
const rfbError = ref('')
let refreshTimer = null
let rfb = null

const platform = computed(() => String(route.query.platform || state.value?.platform || '').trim())
const platformLabel = computed(() => state.value?.label || platform.value || '代码平台')
const returnTo = computed(() => {
  const value = String(route.query.return_to || '').trim()
  return value.startsWith('/') && !value.startsWith('//') ? value : '/document-exposure/code-monitoring/settings'
})

const viewportText = computed(() => {
  const viewport = state.value?.viewport || {}
  if (!viewport.width || !viewport.height) return '画面尺寸 -'
  return `画面尺寸 ${viewport.width} x ${viewport.height}`
})

const rfbStatusLabel = computed(() => {
  const labels = {
    idle: '未连接',
    connecting: '连接中',
    connected: '已连接',
    disconnected: '已断开',
    error: '连接失败',
  }
  return labels[rfbStatus.value] || rfbStatus.value
})

const rfbTagType = computed(() => {
  if (rfbStatus.value === 'connected') return 'success'
  if (rfbStatus.value === 'connecting') return 'warning'
  if (rfbStatus.value === 'error') return 'danger'
  return 'info'
})

function buildWebsocketUrl(path) {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}${path}`
}

function disconnectRfb() {
  if (!rfb) return
  try {
    rfb.disconnect()
  } catch {
    // noVNC disconnect can throw if the socket is already closed.
  }
  rfb = null
}

async function connectRfb() {
  if (!state.value?.rfb_ws_path) return
  await nextTick()
  if (!browserDesktopRef.value) return
  disconnectRfb()
  rfbError.value = ''
  rfbStatus.value = 'connecting'
  try {
    rfb = new RFB(browserDesktopRef.value, buildWebsocketUrl(state.value.rfb_ws_path), {
      shared: true,
    })
    rfb.scaleViewport = true
    rfb.resizeSession = false
    rfb.clipViewport = false
    rfb.focusOnClick = true
    rfb.background = '#111827'
    rfb.addEventListener('connect', () => {
      rfbStatus.value = 'connected'
      rfbError.value = ''
    })
    rfb.addEventListener('disconnect', (event) => {
      rfbStatus.value = event.detail?.clean ? 'disconnected' : 'error'
      if (!event.detail?.clean) {
        rfbError.value = '内置浏览器连接已断开，请重新连接或关闭会话后再启动。'
      }
    })
    rfb.addEventListener('securityfailure', () => {
      rfbStatus.value = 'error'
      rfbError.value = 'VNC 安全握手失败，请重新启动内置浏览器会话。'
    })
  } catch (error) {
    rfbStatus.value = 'error'
    rfbError.value = error.message || '连接内置浏览器失败'
  }
}

function applyState(payload) {
  state.value = payload
  if (!accountLabel.value && payload?.label) {
    accountLabel.value = payload.label
  }
}

async function ensureSession() {
  if (sessionId.value) {
    await refreshState()
    return
  }
  if (!platform.value) {
    ElMessage.error('缺少平台参数')
    return
  }
  loading.value = true
  try {
    const payload = await api.startRemoteLogin(platform.value)
    sessionId.value = payload.session_id
    applyState(payload)
    router.replace({
      name: 'RemotePlatformLogin',
      query: { platform: platform.value, session_id: sessionId.value, return_to: returnTo.value },
    })
    await connectRfb()
  } catch (error) {
    ElMessage.error(error.message || '创建内置浏览器会话失败')
  } finally {
    loading.value = false
  }
}

async function refreshState() {
  if (!sessionId.value || loading.value) return
  loading.value = true
  try {
    applyState(await api.loadRemoteLoginState(sessionId.value))
  } catch (error) {
    ElMessage.error(error.message || '刷新内置浏览器状态失败')
  } finally {
    loading.value = false
  }
}

async function finishSession() {
  if (!sessionId.value) return
  saving.value = true
  try {
    await api.finishRemoteLogin(sessionId.value, accountLabel.value || platform.value)
    disconnectRfb()
    ElMessage.success('内置浏览器会话已保存')
    router.push(returnTo.value)
  } catch (error) {
    ElMessage.error(error.message || '保存内置浏览器会话失败')
  } finally {
    saving.value = false
  }
}

async function closeSession() {
  if (!sessionId.value) return
  closing.value = true
  try {
    disconnectRfb()
    await api.closeRemoteLogin(sessionId.value)
    ElMessage.success('内置浏览器会话已关闭')
    router.push(returnTo.value)
  } catch (error) {
    ElMessage.error(error.message || '关闭内置浏览器会话失败')
  } finally {
    closing.value = false
  }
}

function returnToPrevious() {
  router.push(returnTo.value)
}

watch(
  () => state.value?.rfb_ws_path,
  async (path) => {
    if (path) await connectRfb()
  },
)

onMounted(async () => {
  await ensureSession()
  refreshTimer = window.setInterval(refreshState, 5000)
})

onUnmounted(() => {
  disconnectRfb()
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped lang="scss">
.embedded-browser-page {
  min-width: 0;
  overflow-x: hidden;
}

.embedded-browser-header,
.embedded-browser-layout {
  display: grid;
  gap: 18px;
}

.embedded-browser-header {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  margin-bottom: 18px;
}

.embedded-browser-header h2 {
  margin: 4px 0 8px;
  color: var(--ti-text-primary);
  font-size: 30px;
}

.embedded-browser-header p {
  margin: 0;
  color: var(--ti-text-secondary);
}

.embedded-browser-header__actions,
.browser-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.embedded-browser-layout {
  grid-template-columns: minmax(0, 1fr) 340px;
  align-items: start;
}

.browser-desktop,
.browser-empty {
  height: min(760px, calc(100vh - 230px));
  min-height: 520px;
  border: 1px solid rgba(116, 142, 184, 0.2);
  border-radius: 10px;
  background: #111827;
  overflow: hidden;
}

.browser-desktop {
  display: flex;
  align-items: center;
  justify-content: center;
}

.browser-desktop :deep(.rfb_screen) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100% !important;
  height: 100% !important;
}

.browser-desktop :deep(canvas) {
  display: block;
  max-width: 100%;
  max-height: min(760px, calc(100vh - 230px));
  outline: none;
}

.browser-footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding-top: 12px;
  color: var(--ti-text-secondary);
  font-size: 13px;
}

.embedded-browser-side {
  display: grid;
  gap: 18px;
}

.side-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.embedded-browser-state {
  display: grid;
  gap: 12px;
}

.state-row {
  display: grid;
  gap: 4px;
}

.state-row span {
  color: var(--ti-text-secondary);
  font-size: 12px;
}

.state-row strong {
  color: var(--ti-text-primary);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
}

@media (max-width: 1280px) {
  .embedded-browser-header,
  .embedded-browser-layout {
    grid-template-columns: 1fr;
  }
}
</style>
