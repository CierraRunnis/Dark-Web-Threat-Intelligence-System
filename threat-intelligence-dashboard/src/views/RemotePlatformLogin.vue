<template>
  <div class="remote-login-page ti-page">
    <section class="remote-login-header ti-reveal-up">
      <div>
        <div class="ti-kicker">Remote Browser Session</div>
        <h2>平台远程验证</h2>
        <p>在服务器端浏览器中完成登录或安全验证，保存后会写入现有平台会话。</p>
      </div>
      <div class="remote-login-header__actions">
        <el-button plain @click="router.back()">返回</el-button>
        <el-button plain :loading="loading" @click="refreshState">刷新画面</el-button>
        <el-button type="primary" :loading="saving" :disabled="!sessionId" @click="finishSession">保存会话</el-button>
        <el-button type="danger" plain :loading="closing" :disabled="!sessionId" @click="closeSession">关闭会话</el-button>
      </div>
    </section>

    <section class="remote-login-layout">
      <div class="ti-card ti-reveal-up remote-login-card">
        <div class="ti-card-header">
          <div>
            <div class="ti-card-title">{{ platformLabel }}</div>
            <div class="ti-card-subtitle">{{ state?.url || '正在创建远程浏览器会话' }}</div>
          </div>
          <el-tag v-if="sessionId" effect="plain">{{ sessionId.slice(0, 10) }}</el-tag>
        </div>
        <div class="ti-card-body">
          <div class="remote-screen-shell" :class="{ 'remote-screen-shell--empty': !state?.screenshot }">
            <img
              v-if="state?.screenshot"
              class="remote-screen"
              :src="state.screenshot"
              alt="远程浏览器画面"
              draggable="false"
              @click="clickRemote"
            />
            <el-empty v-else description="等待远程浏览器画面" />
          </div>
          <div class="screen-footer">
            <span>{{ actionResultText }}</span>
            <span>{{ viewportText }}</span>
          </div>
        </div>
      </div>

      <aside class="remote-side">
        <div class="ti-card ti-reveal-up">
          <div class="ti-card-header">
            <div class="ti-card-title">登录凭据</div>
          </div>
          <div class="ti-card-body">
            <el-form class="credential-form" label-position="top">
              <el-form-item label="账号标签">
                <el-input v-model="credentialForm.accountLabel" placeholder="例如 GitHub 主账号" clearable />
              </el-form-item>
              <el-form-item label="账号 / 邮箱 / 用户名">
                <el-input v-model="credentialForm.username" autocomplete="username" clearable />
              </el-form-item>
              <el-form-item label="密码 / Token">
                <el-input v-model="credentialForm.password" type="password" autocomplete="current-password" show-password clearable />
              </el-form-item>
              <el-form-item label="验证码 / 二次验证">
                <el-input v-model="credentialForm.otp" autocomplete="one-time-code" clearable />
              </el-form-item>
            </el-form>
            <div class="credential-actions">
              <el-button type="primary" :loading="actionLoading" :disabled="!canFillLoginForm" @click="fillLoginForm">
                自动填入登录表单
              </el-button>
              <el-button type="success" plain :loading="actionLoading" @click="submitLoginForm">提交登录</el-button>
            </div>
          </div>
        </div>

        <div class="ti-card ti-reveal-up">
          <div class="ti-card-header">
            <div class="ti-card-title">手动控制</div>
          </div>
          <div class="ti-card-body remote-manual">
            <el-input v-model="navigateUrl" placeholder="URL" clearable @keyup.enter="navigateRemote" />
            <el-button plain :disabled="!navigateUrl.trim() || actionLoading" @click="navigateRemote">跳转</el-button>
            <el-input v-model="manualText" placeholder="发送到当前焦点输入框" clearable @keyup.enter="typeRemoteText" />
            <el-button type="primary" plain :disabled="!manualText || actionLoading" @click="typeRemoteText">发送当前焦点文本</el-button>
            <div class="key-actions">
              <el-button plain :disabled="actionLoading" @click="pressKey('Enter')">Enter</el-button>
              <el-button plain :disabled="actionLoading" @click="pressKey('Tab')">Tab</el-button>
              <el-button plain :disabled="actionLoading" @click="pressKey('Backspace')">退格</el-button>
            </div>
          </div>
        </div>

        <div class="ti-card ti-reveal-up">
          <div class="ti-card-header">
            <div class="ti-card-title">会话状态</div>
          </div>
          <div class="ti-card-body remote-side__body">
            <div class="remote-state-row">
              <span>平台</span>
              <strong>{{ platformLabel }}</strong>
            </div>
            <div class="remote-state-row">
              <span>页面标题</span>
              <strong>{{ state?.title || '-' }}</strong>
            </div>
            <div class="remote-state-row">
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
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useCodeMonitoringApi } from '@/composables/useCodeMonitoringApi'

const api = useCodeMonitoringApi()
const route = useRoute()
const router = useRouter()

const state = ref(null)
const sessionId = ref(String(route.query.session_id || '').trim())
const credentialForm = reactive({
  accountLabel: '',
  username: '',
  password: '',
  otp: '',
})
const manualText = ref('')
const navigateUrl = ref('')
const loading = ref(false)
const actionLoading = ref(false)
const saving = ref(false)
const closing = ref(false)
const lastActionResult = ref('')
let refreshTimer = null

const platform = computed(() => String(route.query.platform || state.value?.platform || '').trim())
const platformLabel = computed(() => state.value?.label || platform.value || '代码平台')
const canFillLoginForm = computed(() => Boolean(credentialForm.username || credentialForm.password || credentialForm.otp))

const viewportText = computed(() => {
  const viewport = state.value?.viewport || {}
  if (!viewport.width || !viewport.height) return '画面尺寸 -'
  return `画面尺寸 ${viewport.width} x ${viewport.height}`
})

const actionResultText = computed(() => lastActionResult.value || '点击远程画面可发送鼠标点击')

function applyState(payload) {
  state.value = payload
  const result = payload?.action_result
  if (!result) return
  if (result.username_filled !== undefined || result.password_filled !== undefined || result.otp_filled !== undefined) {
    const filled = []
    if (result.username_filled) filled.push('账号')
    if (result.password_filled) filled.push('密码')
    if (result.otp_filled) filled.push('验证码')
    lastActionResult.value = filled.length ? `已填入：${filled.join('、')}` : '未找到可填入字段'
  } else if (result.submitted) {
    lastActionResult.value = result.method === 'button' ? '已点击登录按钮' : '已发送 Enter 提交'
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
      query: { platform: platform.value, session_id: sessionId.value },
    })
  } catch (error) {
    ElMessage.error(error.message || '创建远程浏览器会话失败')
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
    ElMessage.error(error.message || '刷新远程画面失败')
  } finally {
    loading.value = false
  }
}

async function sendAction(payload) {
  if (!sessionId.value || actionLoading.value) return
  actionLoading.value = true
  try {
    applyState(await api.controlRemoteLogin(sessionId.value, payload))
  } catch (error) {
    ElMessage.error(error.message || '远程浏览器操作失败')
  } finally {
    actionLoading.value = false
  }
}

async function fillLoginForm() {
  if (!canFillLoginForm.value) return
  await sendAction({
    action: 'fill_login_form',
    username: credentialForm.username,
    password: credentialForm.password,
    otp: credentialForm.otp,
  })
}

async function submitLoginForm() {
  await sendAction({ action: 'submit_login_form' })
}

async function clickRemote(event) {
  const viewport = state.value?.viewport || {}
  if (!viewport.width || !viewport.height) return
  const rect = event.currentTarget.getBoundingClientRect()
  const x = ((event.clientX - rect.left) / rect.width) * viewport.width
  const y = ((event.clientY - rect.top) / rect.height) * viewport.height
  lastActionResult.value = `已点击 ${Math.round(x)}, ${Math.round(y)}`
  await sendAction({ action: 'click', x, y })
}

async function typeRemoteText() {
  const text = manualText.value
  if (!text) return
  manualText.value = ''
  lastActionResult.value = '已发送当前焦点文本'
  await sendAction({ action: 'type', text })
}

async function pressKey(key) {
  lastActionResult.value = `已发送 ${key}`
  await sendAction({ action: 'key', key })
}

async function navigateRemote() {
  const raw = navigateUrl.value.trim()
  if (!raw) return
  const url = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`
  lastActionResult.value = `正在跳转 ${url}`
  await sendAction({ action: 'navigate', url })
}

async function finishSession() {
  if (!sessionId.value) return
  saving.value = true
  try {
    await api.finishRemoteLogin(sessionId.value, credentialForm.accountLabel || platform.value)
    ElMessage.success('远程会话已保存')
    router.push('/document-exposure/code-monitoring/settings')
  } catch (error) {
    ElMessage.error(error.message || '保存远程会话失败')
  } finally {
    saving.value = false
  }
}

async function closeSession() {
  if (!sessionId.value) return
  closing.value = true
  try {
    await api.closeRemoteLogin(sessionId.value)
    ElMessage.success('远程会话已关闭')
    router.push('/document-exposure/code-monitoring/settings')
  } catch (error) {
    ElMessage.error(error.message || '关闭远程会话失败')
  } finally {
    closing.value = false
  }
}

onMounted(async () => {
  await ensureSession()
  refreshTimer = window.setInterval(refreshState, 5000)
})

onUnmounted(() => {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped lang="scss">
.remote-login-page {
  min-width: 0;
  overflow-x: hidden;
}

.remote-login-header,
.remote-login-layout {
  display: grid;
  gap: 18px;
}

.remote-login-header {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  margin-bottom: 18px;
}

.remote-login-header h2 {
  margin: 4px 0 8px;
  color: var(--ti-text-primary);
  font-size: 30px;
}

.remote-login-header p {
  margin: 0;
  color: var(--ti-text-secondary);
}

.remote-login-header__actions,
.credential-actions,
.key-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.remote-login-layout {
  grid-template-columns: minmax(0, 1fr) 360px;
  align-items: start;
}

.remote-screen-shell {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 560px;
  border-radius: 10px;
  border: 1px solid rgba(116, 142, 184, 0.18);
  background: #f8fafc;
  overflow: hidden;
}

.remote-screen-shell--empty {
  min-height: 520px;
}

.remote-screen {
  display: block;
  width: 100%;
  max-height: calc(100vh - 230px);
  object-fit: contain;
  cursor: crosshair;
  user-select: none;
}

.screen-footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding-top: 12px;
  color: var(--ti-text-secondary);
  font-size: 13px;
}

.remote-side {
  display: grid;
  gap: 18px;
}

.credential-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.credential-actions .el-button {
  flex: 1 1 150px;
}

.remote-manual {
  display: grid;
  gap: 10px;
}

.remote-side__body {
  display: grid;
  gap: 14px;
}

.remote-state-row {
  display: grid;
  gap: 4px;
}

.remote-state-row span {
  color: var(--ti-text-secondary);
  font-size: 12px;
}

.remote-state-row strong {
  color: var(--ti-text-primary);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
}

@media (max-width: 1280px) {
  .remote-login-header,
  .remote-login-layout {
    grid-template-columns: 1fr;
  }

  .remote-side {
    order: -1;
  }
}
</style>
