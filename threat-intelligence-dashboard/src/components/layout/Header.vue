<template>
  <header class="header">
    <div class="header__actions">
      <el-popover placement="bottom-end" :width="420" trigger="click" @show="loadNotifications">
        <template #reference>
          <el-badge :value="unreadCount" :hidden="unreadCount < 1" :max="99" class="header__badge">
            <el-button circle class="header__action-btn" aria-label="平台内通知">
              <el-icon><Bell /></el-icon>
            </el-button>
          </el-badge>
        </template>
        <div class="notification-panel">
          <div class="notification-panel__head">
            <div><strong>平台内通知</strong><span>{{ unreadCount }} 条未读</span></div>
            <el-button v-if="unreadCount" type="primary" link @click="markAllRead">全部已读</el-button>
          </div>
          <div v-loading="notificationsLoading" class="notification-list">
            <button
              v-for="item in notifications"
              :key="item.id"
              type="button"
              :class="['notification-item', { unread: !notificationRead(item) }]"
              @click="openNotification(item)"
            >
              <span class="notification-item__dot"></span>
              <span class="notification-item__body">
                <strong>{{ item.card?.threatTitle || item.threatTitle || item.title || '社交平台威胁情报' }}</strong>
                <small>{{ item.card?.platform || item.platformLabel || item.platform || '-' }} · {{ notificationTime(item.createdAt || item.publishedAt) }}</small>
                <p>{{ item.card?.disposalDirection || item.summary || item.disposalDirection || '点击查看威胁详情' }}</p>
              </span>
            </button>
            <div v-if="!notifications.length && !notificationsLoading" class="notification-empty">暂无平台内通知</div>
          </div>
        </div>
      </el-popover>

      <el-dropdown trigger="click" @command="handleUserCommand">
        <el-button class="header__profile-btn" aria-label="用户菜单">
          <span class="header__profile-avatar">
            <el-icon><UserFilled /></el-icon>
          </span>
          <span class="header__profile-name">{{ displayName }}</span>
          <el-icon class="header__profile-caret"><ArrowDown /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>账号：{{ username }} · {{ roleLabel }}</el-dropdown-item>
            <el-dropdown-item command="change-password" divided>
              <el-icon><Key /></el-icon>
              修改密码
            </el-dropdown-item>
            <el-dropdown-item command="logout" divided>
              <el-icon><SwitchButton /></el-icon>
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>

  <el-dialog v-model="passwordDialogVisible" title="修改密码" width="420px" destroy-on-close>
    <el-form
      ref="passwordFormRef"
      class="password-form"
      :model="passwordForm"
      :rules="passwordRules"
      label-position="top"
      @keyup.enter="submitPasswordChange"
    >
      <el-form-item label="当前密码" prop="currentPassword">
        <el-input
          v-model="passwordForm.currentPassword"
          type="password"
          autocomplete="current-password"
          show-password
        />
      </el-form-item>
      <el-form-item label="新密码" prop="newPassword">
        <el-input
          v-model="passwordForm.newPassword"
          type="password"
          autocomplete="new-password"
          show-password
        />
      </el-form-item>
      <el-form-item label="确认新密码" prop="confirmPassword">
        <el-input
          v-model="passwordForm.confirmPassword"
          type="password"
          autocomplete="new-password"
          show-password
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="passwordDialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="passwordSubmitting" @click="submitPasswordChange">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '@/composables/useAuth'
import { listFromResponse, useSocialMonitoringApi } from '@/composables/useSocialMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const router = useRouter()
const { state, loadCurrentUser, changePassword, logout } = useAuth()
const socialApi = useSocialMonitoringApi()
const passwordDialogVisible = ref(false)
const passwordSubmitting = ref(false)
const passwordFormRef = ref()
const passwordForm = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
})
const notifications = ref([])
const notificationsLoading = ref(false)
let notificationsTimer = null

const username = computed(() => state.user?.username || 'admin')
const displayName = computed(() => state.user?.displayName || state.user?.display_name || username.value)
const roleLabel = computed(() => String(state.user?.role || '').toLowerCase() === 'admin' ? '管理员' : '分析员')
const unreadCount = computed(() => notifications.value.filter((item) => !notificationRead(item)).length)

const passwordRules = {
  currentPassword: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '新密码至少 6 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
}

onMounted(() => {
  loadCurrentUser()
  loadNotifications()
  notificationsTimer = window.setInterval(loadNotifications, 15000)
})

onBeforeUnmount(() => {
  if (notificationsTimer) window.clearInterval(notificationsTimer)
})

async function loadNotifications() {
  if (notificationsLoading.value) return
  notificationsLoading.value = true
  try {
    const payload = await socialApi.loadNotifications({ limit: 20 })
    notifications.value = listFromResponse(payload, ['notifications'])
  } catch {
    notifications.value = []
  } finally {
    notificationsLoading.value = false
  }
}

async function openNotification(item) {
  if (!notificationRead(item)) {
    try {
      await socialApi.markNotificationRead(item.id)
      item.isRead = true
      item.readAt = new Date().toISOString()
    } catch {
      // The detail remains accessible even if the read receipt cannot be saved.
    }
  }
  const eventId = item.eventId || item.socialEventId || item.card?.eventId
  if (eventId) router.push(`/social-monitoring/events/${eventId}`)
}

async function markAllRead() {
  try {
    await Promise.all(
      notifications.value
        .filter((item) => !notificationRead(item))
        .map((item) => socialApi.markNotificationRead(item.id)),
    )
    const now = new Date().toISOString()
    for (const item of notifications.value) {
      item.isRead = true
      item.readAt ||= now
    }
  } catch (error) {
    ElMessage.error(error.message || '更新通知状态失败')
  }
}

function notificationTime(value) {
  return formatShanghaiDateTime(value, { includeSeconds: false }) || '-'
}

function notificationRead(item) {
  return Boolean(item.read || item.readAt || item.isRead)
}

async function handleUserCommand(command) {
  if (command === 'change-password') {
    openPasswordDialog()
    return
  }
  if (command !== 'logout') return
  await logout()
  ElMessage.success('已退出登录')
  router.replace('/login')
}

function validateConfirmPassword(_rule, value, callback) {
  if (value !== passwordForm.newPassword) {
    callback(new Error('两次输入的新密码不一致'))
    return
  }
  callback()
}

function resetPasswordForm() {
  passwordForm.currentPassword = ''
  passwordForm.newPassword = ''
  passwordForm.confirmPassword = ''
  passwordFormRef.value?.clearValidate()
}

function openPasswordDialog() {
  resetPasswordForm()
  passwordDialogVisible.value = true
}

async function submitPasswordChange() {
  if (!passwordFormRef.value || passwordSubmitting.value) return
  try {
    await passwordFormRef.value.validate()
  } catch {
    return
  }

  passwordSubmitting.value = true
  try {
    await changePassword(passwordForm.currentPassword, passwordForm.newPassword)
    ElMessage.success('密码已修改')
    passwordDialogVisible.value = false
    resetPasswordForm()
  } catch (error) {
    ElMessage.error(error.message || '修改密码失败')
  } finally {
    passwordSubmitting.value = false
  }
}
</script>

<style lang="scss" scoped>
.header {
  position: sticky;
  top: 0;
  z-index: 50;
  display: flex;
  justify-content: flex-end;
  align-items: center;
  min-height: 82px;
  padding: 18px 28px 14px;
  border-bottom: 1px solid rgba(87, 97, 123, 0.08);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(16px);
}

.header__actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header__action-btn,
.header__profile-btn {
  height: 42px;
  border-color: rgba(116, 142, 184, 0.18);
  background: rgba(255, 255, 255, 0.98);
  box-shadow:
    inset 0 0 0 1px rgba(37, 94, 161, 0.03),
    0 8px 18px rgba(36, 78, 130, 0.04);
  color: var(--ti-text-primary);
}

.header__action-btn {
  width: 42px;
}

.header__profile-btn {
  padding: 0 14px 0 10px;
  border-radius: 999px;
  font-weight: 600;
}

.header__profile-avatar {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  margin-right: 8px;
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(45, 93, 255, 0.16), rgba(45, 93, 255, 0.08));
  color: var(--ti-primary);
}

.header__profile-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header__profile-caret {
  margin-left: 6px;
  color: var(--ti-text-muted);
  font-size: 14px;
}

.password-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

.notification-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 2px 12px;
  border-bottom: 1px solid var(--ti-border-soft);
}

.notification-panel__head > div {
  display: flex;
  align-items: baseline;
  gap: 9px;
}

.notification-panel__head span {
  color: var(--ti-text-muted);
  font-size: 12px;
}

.notification-list {
  max-height: 430px;
  min-height: 90px;
  overflow-y: auto;
}

.notification-item {
  display: grid;
  grid-template-columns: 8px 1fr;
  gap: 10px;
  width: 100%;
  padding: 13px 4px;
  border: 0;
  border-bottom: 1px solid var(--ti-border-soft);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.notification-item:hover { background: rgba(45, 93, 255, 0.04); }
.notification-item__dot { width: 7px; height: 7px; margin-top: 6px; border-radius: 50%; background: #c7cfdb; }
.notification-item.unread .notification-item__dot { background: var(--ti-primary); box-shadow: 0 0 0 4px rgba(45, 93, 255, 0.1); }
.notification-item__body { display: grid; gap: 4px; min-width: 0; }
.notification-item__body strong, .notification-item__body p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notification-item__body small { color: var(--ti-text-muted); }
.notification-item__body p { margin: 0; color: var(--ti-text-secondary); }
.notification-empty { display: grid; place-items: center; min-height: 120px; color: var(--ti-text-muted); }

@media (max-width: 767px) {
  .header {
    min-height: 72px;
    padding: 14px 18px 12px;
  }

  .header__profile-btn {
    padding-right: 12px;
  }

  .header__profile-name {
    max-width: 80px;
  }
}
</style>
