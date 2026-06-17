<template>
  <header class="header">
    <div class="header__actions">
      <el-badge :value="6" class="header__badge">
        <el-button circle class="header__action-btn" aria-label="通知">
          <el-icon><Bell /></el-icon>
        </el-button>
      </el-badge>

      <el-button class="header__profile-btn" aria-label="个人用户">
        <span class="header__profile-avatar">
          <el-icon><UserFilled /></el-icon>
        </span>
        <span>个人用户</span>
      </el-button>
    </div>
  </header>
</template>

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

@media (max-width: 767px) {
  .header {
    min-height: 72px;
    padding: 14px 18px 12px;
  }

  .header__profile-btn {
    padding-right: 12px;
  }
}
</style>
