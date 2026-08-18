<template>
  <div class="login-page">
    <div class="login-shell">
      <section class="login-visual">
        <div class="login-brand">
          <span class="login-brand__mark">
            <img src="/assets/xuanjian-mark.svg" alt="" />
          </span>
          <span class="login-brand__copy">
            <strong>玄鉴</strong>
            <small>THREAT INTELLIGENCE</small>
          </span>
        </div>

        <div class="signal-field" aria-hidden="true">
          <span class="signal-orbit orbit-one"></span>
          <span class="signal-orbit orbit-two"></span>
          <span class="signal-orbit orbit-three"></span>
          <span class="signal-core">
            <svg viewBox="0 0 48 48" fill="none">
              <path class="brand-mark-line" d="M18 13h-3a2 2 0 0 0-2 2v3M30 13h3a2 2 0 0 1 2 2v3M13 26v3a2 2 0 0 0 2 2h3M35 26v3a2 2 0 0 1-2 2h-3" />
              <circle class="brand-mark-line" cx="24" cy="22" r="5.7" />
              <circle class="brand-mark-dot" cx="24" cy="22" r="2.3" />
              <path class="brand-mark-line brand-mark-wave" d="M18.5 33.5Q24 36.9 29.5 33.5M16.5 37.4Q24 41.8 31.5 37.4" />
            </svg>
          </span>
          <i style="--x: 13%; --y: 27%; --delay: 0.2s"></i>
          <i style="--x: 78%; --y: 18%; --delay: 0.8s"></i>
          <i style="--x: 86%; --y: 68%; --delay: 1.3s"></i>
          <i style="--x: 23%; --y: 77%; --delay: 1.8s"></i>
          <i style="--x: 57%; --y: 88%; --delay: 2.2s"></i>
        </div>
        <div class="login-visual__copy">
          <small>态势感知 · 暴露监测 · 情报研判</small>
          <h1>看见风险，先于影响。</h1>
        </div>
      </section>


      <section class="login-panel">
        <div class="login-form-wrap">
          <header class="login-panel__header">
            <span class="login-panel__seal" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none">
                <path d="M12 3.2 19 6v5.4c0 4.5-2.8 7.7-7 9.6-4.2-1.9-7-5.1-7-9.6V6l7-2.8Z" stroke="currentColor" stroke-width="1.5" />
                <path d="m8.8 12.1 2 2 4.5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </span>
            <span>
              <h2>欢迎登录</h2>
              <small>玄鉴威胁情报平台</small>
            </span>
          </header>

          <el-form
            ref="loginFormRef"
            class="login-form"
            :model="form"
            :rules="rules"
            label-position="top"
            @keyup.enter="submitLogin"
          >
            <el-form-item label="账号" prop="account">
              <el-input v-model.trim="form.account" size="large" placeholder="请输入账号" autocomplete="username">
                <template #prefix>
                  <el-icon><User /></el-icon>
                </template>
              </el-input>
            </el-form-item>

            <el-form-item label="密码" prop="password">
              <el-input
                v-model="form.password"
                size="large"
                type="password"
                placeholder="请输入密码"
                autocomplete="current-password"
                show-password
              >
                <template #prefix>
                  <el-icon><Lock /></el-icon>
                </template>
              </el-input>
            </el-form-item>

            <div class="login-form__options">
              <el-checkbox v-model="form.rememberAccount">记住登录状态</el-checkbox>
              <el-button link type="primary" @click="showLoginSupport">登录支持</el-button>
            </div>

            <el-button class="login-form__submit" type="primary" size="large" :loading="submitting" @click="submitLogin">
              <span>进入平台</span>
              <el-icon><Right /></el-icon>
            </el-button>
          </el-form>

          <footer class="login-foot">
            <span class="login-service" :class="`login-service--${serviceState}`">
              <i></i>{{ serviceLabel }}
            </span>
            <span>{{ appVersion }}</span>
          </footer>
        </div>
      </section>
    </div>
  </div>
</template>


<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '@/composables/useAuth'
import packageMetadata from '../../package.json'

const ACCOUNT_STORAGE_KEY = 'dwti-login-account'

const router = useRouter()
const route = useRoute()
const { login } = useAuth()
const loginFormRef = ref()
const submitting = ref(false)
const serviceState = ref('checking')
const rememberedAccount = localStorage.getItem(ACCOUNT_STORAGE_KEY) || ''
const appVersion = `v${packageMetadata.version}`

const form = reactive({
  account: rememberedAccount,
  password: '',
  rememberAccount: Boolean(rememberedAccount),
})

const rules = {
  account: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const redirectTarget = computed(() => {
  const redirect = route.query.redirect
  if (typeof redirect === 'string' && redirect.startsWith('/') && redirect !== '/login') {
    return redirect
  }
  return '/'
})

const serviceLabel = computed(() => ({
  checking: '服务检测中',
  available: '服务可用',
  unavailable: '服务暂不可用',
}[serviceState.value]))

onMounted(checkService)

async function checkService() {
  try {
    const response = await fetch('/api/health', { cache: 'no-store' })
    serviceState.value = response.ok ? 'available' : 'unavailable'
  } catch {
    serviceState.value = 'unavailable'
  }
}

function showLoginSupport() {
  ElMessage.info('请联系平台管理员获取登录支持')
}

async function submitLogin() {
  if (!loginFormRef.value || submitting.value) return

  try {
    await loginFormRef.value.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    await login(form.account, form.password)

    if (form.rememberAccount) {
      localStorage.setItem(ACCOUNT_STORAGE_KEY, form.account)
    } else {
      localStorage.removeItem(ACCOUNT_STORAGE_KEY)
    }

    ElMessage.success('已进入系统')
    await router.push(redirectTarget.value)
  } catch (error) {
    ElMessage.error(error.message || '登录失败')
  } finally {
    submitting.value = false
  }
}
</script>


<style lang="scss" scoped>
.login-page {
  --surface: oklch(100% 0 0);
  --secondary: oklch(58% 0.105 190);
  --danger: oklch(57% 0.19 25);
  width: 100%;
  min-height: 100vh;
  background: #ffffff;
}

.login-page .login-shell {
  display: grid;
  width: 100%;
  min-height: 100vh;
  grid-template-columns: minmax(0, 1.8fr) minmax(470px, 1fr);
  gap: 0;
}

.login-visual {
  position: relative;
  min-width: 0;
  min-height: 100vh;
  overflow: hidden;
  background:
    linear-gradient(rgba(75, 111, 132, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(75, 111, 132, 0.08) 1px, transparent 1px),
    #03101a;
  background-size: 52px 52px;
  color: #f8fbfd;
}

.login-visual::after {
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 50% 49%, transparent 0 28%, rgba(3, 16, 26, 0.05) 58%, rgba(3, 16, 26, 0.45) 100%);
  content: '';
  pointer-events: none;
}

.login-visual .login-brand {
  position: absolute;
  z-index: 3;
  top: 44px;
  left: 54px;
  display: flex;
  min-height: auto;
  align-items: center;
  justify-content: flex-start;
  gap: 15px;
  overflow: visible;
  padding: 0;
  background: transparent;
  color: #f8fbfd;
  text-align: left;
}

.login-visual .login-brand::before,
.login-visual .login-brand::after {
  content: none;
}

.login-brand__mark {
  display: inline-flex;
  width: 50px;
  height: 50px;
  flex: 0 0 50px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 50%;
  background: transparent;
  box-shadow: 0 12px 32px rgba(218, 31, 49, 0.28);
}

.login-brand__mark img {
  width: 100%;
  height: 100%;
}

.login-brand__copy {
  display: grid;
  gap: 5px;
}

.login-brand__copy strong {
  color: #ffffff;
  font-size: 25px;
  line-height: 1;
  letter-spacing: 0.08em;
}

.login-brand__copy small {
  color: rgba(226, 237, 244, 0.56);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.signal-field {
  position: absolute;
  left: 50%;
  top: 48%;
  width: min(50vw, 650px);
  aspect-ratio: 1;
  transform: translate(-50%, -50%);
}

.signal-orbit {
  position: absolute;
  left: 50%;
  top: 50%;
  border: 1px solid color-mix(in oklch, var(--secondary) 32%, transparent);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  animation: orbitBreath 4s ease-in-out infinite;
}

.orbit-one {
  width: 30%;
  height: 30%;
}

.orbit-two {
  width: 56%;
  height: 56%;
  animation-delay: 0.7s;
}

.orbit-three {
  width: 84%;
  height: 84%;
  animation-delay: 1.4s;
}

.signal-orbit::after {
  position: absolute;
  left: 50%;
  top: -4px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--secondary);
  box-shadow: 0 0 16px var(--secondary);
  content: '';
}

.signal-core {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 106px;
  height: 106px;
  display: grid;
  place-items: center;
  transform: translate(-50%, -50%);
  border: 1px solid color-mix(in oklch, var(--surface) 10%, transparent);
  border-radius: 50%;
  background: radial-gradient(
    circle at 34% 28%,
    color-mix(in oklch, var(--secondary) 14%, oklch(17% 0.025 245)),
    oklch(13.5% 0.022 245) 72%
  );
  box-shadow:
    inset -12px -10px 28px color-mix(in oklch, black 18%, transparent),
    0 0 0 12px color-mix(in oklch, var(--secondary) 6%, transparent),
    0 0 70px color-mix(in oklch, var(--secondary) 16%, transparent);
}

.signal-core svg {
  width: 72px;
  height: 72px;
}

.signal-core .brand-mark-line {
  fill: none;
  stroke: color-mix(in oklch, var(--surface) 90%, transparent);
  stroke-width: 2.3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.signal-core .brand-mark-dot {
  fill: var(--danger);
}

.signal-core .brand-mark-wave {
  stroke-width: 2;
}

.signal-field > i {
  position: absolute;
  left: var(--x);
  top: var(--y);
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--danger);
  box-shadow: 0 0 0 7px color-mix(in oklch, var(--danger) 10%, transparent);
  animation: signalNode 2.8s var(--delay) ease-in-out infinite;
}
.login-visual__copy {
  position: absolute;
  z-index: 3;
  right: 48px;
  bottom: 48px;
  left: 52px;
}

.login-visual__copy small {
  display: block;
  margin-bottom: 17px;
  color: rgba(225, 235, 241, 0.55);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.login-visual__copy h1 {
  margin: 0;
  color: #ffffff;
  font-size: clamp(40px, 4.1vw, 66px);
  font-weight: 800;
  line-height: 1.15;
  letter-spacing: -0.045em;
}

.login-page .login-panel {
  display: flex;
  width: 100%;
  min-width: 0;
  min-height: 100vh;
  align-items: center;
  justify-content: center;
  padding: 48px clamp(38px, 5vw, 92px);
  border: 0;
  border-radius: 0;
  background: #ffffff;
  box-shadow: none;
}

.login-form-wrap {
  width: min(100%, 488px);
}

.login-page .login-panel__header {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 16px;
  margin: 0 0 42px;
}

.login-panel__seal {
  display: grid;
  width: 56px;
  height: 56px;
  flex: 0 0 56px;
  place-items: center;
  border-radius: 7px;
  background: #17232f;
  color: #ffffff;
}

.login-panel__seal svg {
  width: 34px;
  height: 34px;
}

.login-panel__header > span:last-child {
  display: grid;
  gap: 4px;
}

.login-page .login-panel__header h2 {
  margin: 0;
  color: #101c28;
  font-size: 31px;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: -0.04em;
}

.login-panel__header small {
  color: #536578;
  font-size: 13px;
}


.login-page .login-form {
  display: grid;
  width: 100%;
  gap: 5px;
  margin: 0;
}

:deep(.el-form-item) {
  margin-bottom: 18px;
}

:deep(.el-form-item__label) {
  height: auto;
  margin-bottom: 8px;
  color: #35495c;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.4;
}

:deep(.el-input__wrapper) {
  min-height: 56px;
  padding: 0 16px;
  border: 1px solid #c9d5df;
  border-radius: 6px;
  background: #f0f5fa;
  box-shadow: none;
}

:deep(.el-input__wrapper:hover),
:deep(.el-input__wrapper.is-focus) {
  border-color: #657b8d;
  box-shadow: 0 0 0 1px #657b8d inset;
}

:deep(.el-input__inner) {
  color: #101c28;
  font-size: 16px;
}

:deep(.el-input__prefix),
:deep(.el-input__suffix) {
  color: #657486;
  font-size: 19px;
}

.login-form__options {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  margin-top: -3px;
}

.login-form__options :deep(.el-checkbox__label),
.login-form__options :deep(.el-button) {
  font-size: 13px;
}

.login-page .login-form__submit {
  width: 100%;
  min-height: 58px;
  margin-top: 15px;
  border-color: #17232f;
  border-radius: 6px;
  background: #17232f;
  font-size: 17px;
  font-weight: 800;
}

.login-page .login-form__submit:hover,
.login-page .login-form__submit:focus {
  border-color: #26394a;
  background: #26394a;
}

.login-form__submit :deep(.el-icon) {
  margin-left: 10px;
}

.login-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 22px;
  color: #697b8c;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
}

.login-service {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.login-service i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e19b14;
  animation: xuanjianStatusPulse 1.8s ease-in-out infinite;
}

.login-service--available i {
  background: #24b36b;
}

.login-service--unavailable i {
  background: #e4434d;
  animation: none;
}

@keyframes orbitBreath {
  0%, 100% { opacity: 0.45; transform: translate(-50%, -50%) scale(0.98) rotate(0); }
  50% { opacity: 1; transform: translate(-50%, -50%) scale(1.03) rotate(8deg); }
}

@keyframes signalNode {
  0%, 100% { opacity: 0.45; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}

@keyframes xuanjianStatusPulse {
  0%, 100% { opacity: 0.55; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.2); }
}

@media (max-width: 1100px) {
  .login-page .login-shell {
    grid-template-columns: minmax(0, 1.25fr) minmax(430px, 0.85fr);
  }

  .signal-field {
    width: min(65vw, 580px);
  }

  .login-visual__copy h1 {
    font-size: clamp(36px, 5vw, 52px);
  }
}

@media (max-width: 900px) {
  .login-page .login-shell {
    grid-template-columns: 1fr;
  }

  .login-visual {
    min-height: 260px;
  }

  .login-visual .login-brand {
    top: 26px;
    left: 28px;
    min-height: auto;
    padding: 0;
  }

  .signal-field {
    top: 52%;
    left: 76%;
    width: 340px;
    opacity: 0.68;
  }

  .signal-core {
    width: 84px;
    height: 84px;
  }

  .signal-core svg {
    width: 58px;
    height: 58px;
  }

  .login-visual__copy {
    right: 24px;
    bottom: 27px;
    left: 28px;
  }

  .login-visual__copy small {
    margin-bottom: 8px;
  }

  .login-visual__copy h1 {
    font-size: 34px;
  }

  .login-page .login-panel {
    min-height: calc(100vh - 260px);
    padding: 42px 28px;
  }
}

@media (max-width: 520px) {
  .login-visual {
    min-height: 210px;
  }

  .login-brand__mark {
    width: 42px;
    height: 42px;
    flex-basis: 42px;
  }

  .login-brand__copy strong {
    font-size: 22px;
  }

  .signal-field {
    left: 87%;
    width: 280px;
  }

  .login-visual__copy h1 {
    font-size: 28px;
  }

  .login-page .login-panel {
    min-height: calc(100vh - 210px);
    padding: 34px 20px;
  }

  .login-page .login-panel__header {
    margin-bottom: 30px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .signal-orbit,
  .signal-field > i,
  .login-service i { animation: none !important; }
}
</style>
