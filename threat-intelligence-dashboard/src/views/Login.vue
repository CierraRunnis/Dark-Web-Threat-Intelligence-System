<template>
  <div class="login-page">
    <div class="login-shell">
      <div class="login-brand">
        <div class="login-brand__mark">
          <el-icon><Monitor /></el-icon>
        </div>
        <div>
          <span class="ti-kicker">安全监测入口</span>
          <h1>公网信息泄露监测平台</h1>
        </div>
      </div>

      <section class="login-panel">
        <header class="login-panel__header">
          <span class="ti-kicker">Welcome Back</span>
          <h2>账号登录</h2>
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
            <el-checkbox v-model="form.rememberAccount">记住账号</el-checkbox>
          </div>

          <el-button class="login-form__submit" type="primary" size="large" :loading="submitting" @click="submitLogin">
            <span>进入系统</span>
            <el-icon><Right /></el-icon>
          </el-button>
        </el-form>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '@/composables/useAuth'

const ACCOUNT_STORAGE_KEY = 'dwti-login-account'

const router = useRouter()
const route = useRoute()
const { login } = useAuth()
const loginFormRef = ref()
const submitting = ref(false)
const rememberedAccount = localStorage.getItem(ACCOUNT_STORAGE_KEY) || ''

const form = reactive({
  account: rememberedAccount || 'admin',
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
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: 32px 18px;
  background:
    linear-gradient(rgba(45, 93, 255, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(45, 93, 255, 0.045) 1px, transparent 1px),
    radial-gradient(circle at 50% 18%, rgba(45, 93, 255, 0.1), transparent 34%),
    linear-gradient(135deg, rgba(247, 250, 255, 0.96), rgba(255, 255, 255, 1) 52%, rgba(255, 247, 237, 0.86)),
    #ffffff;
  background-size: 34px 34px, 34px 34px, auto, auto;
}

.login-shell {
  display: grid;
  width: min(100%, 440px);
  gap: 24px;
  justify-items: center;
}

.login-brand {
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 14px;
}

.login-brand > div:last-child {
  display: grid;
  justify-items: center;
  gap: 6px;
}

.login-brand .ti-kicker {
  justify-content: center;
}

.login-brand__mark {
  display: inline-flex;
  width: 56px;
  height: 56px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(45, 93, 255, 0.16);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 16px 34px rgba(45, 93, 255, 0.1);
  color: var(--ti-primary);
  font-size: 25px;
}

.login-brand h1 {
  color: var(--ti-text-primary);
  font-size: 30px;
  line-height: 1.2;
  letter-spacing: 0;
}

.login-panel {
  width: 100%;
  padding: 34px 36px 36px;
  border: 1px solid var(--ti-border-default);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 22px 54px rgba(53, 64, 86, 0.12);
}

.login-panel__header {
  margin-bottom: 28px;
}

.login-panel__header h2 {
  margin-top: 10px;
  color: var(--ti-text-primary);
  font-size: 26px;
  line-height: 1.25;
  letter-spacing: 0;
}

.login-form {
  display: grid;
  gap: 6px;
}

.login-form__options {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 38px;
}

.login-form__submit {
  width: 100%;
  margin-top: 8px;
}

.login-form__submit :deep(.el-icon) {
  margin-left: 6px;
}

:deep(.el-form-item__label) {
  color: var(--ti-text-primary);
  font-weight: 700;
}

:deep(.el-input__wrapper) {
  min-height: 46px;
}

@media (max-width: 980px) {
  .login-brand h1 {
    font-size: 28px;
  }
}

@media (max-width: 640px) {
  .login-brand h1 {
    font-size: 24px;
  }

  .login-panel {
    padding: 26px 22px;
  }
}
</style>
