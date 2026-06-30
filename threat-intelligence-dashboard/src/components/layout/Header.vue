<template>
  <header class="header">
    <div class="header__actions">
      <el-badge :value="6" class="header__badge">
        <el-button circle class="header__action-btn" aria-label="通知">
          <el-icon><Bell /></el-icon>
        </el-button>
      </el-badge>

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
            <el-dropdown-item disabled>账号：{{ username }}</el-dropdown-item>
            <el-dropdown-item command="logout" divided>
              <el-icon><SwitchButton /></el-icon>
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '@/composables/useAuth'

const router = useRouter()
const { state, loadCurrentUser, logout } = useAuth()

const username = computed(() => state.user?.username || 'admin')
const displayName = computed(() => state.user?.display_name || username.value)

onMounted(() => {
  loadCurrentUser()
})

async function handleUserCommand(command) {
  if (command !== 'logout') return
  await logout()
  ElMessage.success('已退出登录')
  router.replace('/login')
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
