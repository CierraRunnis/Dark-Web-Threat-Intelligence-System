<template>
  <div class="account-management-page ti-page">
    <section class="ti-panel ti-reveal-up">
      <div class="account-management__header">
        <div>
          <span class="ti-kicker">System Accounts</span>
          <h2>账号与权限管理</h2>
          <p>总览为所有账号固定权限，其余模块由管理员按账号分配。</p>
        </div>
        <el-button type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon>
          创建账号
        </el-button>
      </div>

      <div class="fixed-permission-note">
        <el-icon><CircleCheck /></el-icon>
        <span>固定权限：所有账号均可查看完整总览。</span>
      </div>

      <div class="ti-table-shell account-table-shell">
        <el-table v-loading="loading" :data="accounts" table-layout="auto" style="width: 100%">
          <el-table-column prop="username" label="账号" min-width="150" />
          <el-table-column prop="display_name" label="显示名称" min-width="150" />
          <el-table-column label="身份" width="120">
            <template #default="{ row }">
              <el-tag :type="row.role === 'admin' ? 'danger' : 'info'">
                {{ row.role === 'admin' ? '管理员' : '普通账号' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="可见模块" min-width="360">
            <template #default="{ row }">
              <div class="module-tags">
                <el-tag effect="plain">总览（固定）</el-tag>
                <el-tag
                  v-for="moduleKey in row.modules || []"
                  :key="moduleKey"
                  effect="plain"
                  type="success"
                >
                  {{ moduleLabel(moduleKey) }}
                </el-tag>
                <span v-if="row.role !== 'admin' && !(row.modules || []).length" class="module-tags__empty">
                  未分配其他模块
                </span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'">
                {{ row.enabled ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="260" fixed="right">
            <template #default="{ row }">
              <div v-if="row.role !== 'admin'" class="account-actions">
                <el-button link type="primary" @click="openInfoDialog(row)">编辑信息</el-button>
                <el-button link type="primary" @click="openEditDialog(row)">权限设置</el-button>
                <el-button
                  link
                  type="danger"
                  :loading="deletingUsername === row.username"
                  @click="deleteAccountRow(row)"
                >
                  删除
                </el-button>
              </div>
              <span v-else class="fixed-admin-label">固定管理员</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <el-dialog v-model="createDialogVisible" title="创建账号" width="560px" destroy-on-close>
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-position="top">
        <div class="account-form-grid">
          <el-form-item label="登录账号" prop="username">
            <el-input v-model.trim="createForm.username" autocomplete="off" placeholder="3-64 个字符，不含空格" />
          </el-form-item>
          <el-form-item label="显示名称" prop="displayName">
            <el-input v-model.trim="createForm.displayName" autocomplete="off" placeholder="用于页面右上角展示" />
          </el-form-item>
        </div>
        <el-form-item label="初始密码" prop="password">
          <el-input v-model="createForm.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="可见模块">
          <div class="permission-editor">
            <div class="permission-editor__fixed">总览（所有账号固定可见）</div>
            <el-checkbox-group v-model="createForm.modules">
              <el-checkbox v-for="item in ASSIGNABLE_MODULES" :key="item.key" :value="item.key">
                {{ item.label }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="infoDialogVisible" title="编辑账户信息" width="560px" destroy-on-close>
      <el-form ref="infoFormRef" :model="infoForm" :rules="infoRules" label-position="top">
        <div class="account-form-grid">
          <el-form-item label="登录账号" prop="username">
            <el-input v-model.trim="infoForm.username" autocomplete="off" placeholder="3-64 个字符，不含空格" />
          </el-form-item>
          <el-form-item label="显示名称" prop="displayName">
            <el-input v-model.trim="infoForm.displayName" autocomplete="off" />
          </el-form-item>
        </div>
        <el-form-item label="重置密码（可选）" prop="newPassword">
          <el-input
            v-model="infoForm.newPassword"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="留空表示不修改密码"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="infoDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitInfo">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialogVisible" title="权限设置" width="560px" destroy-on-close>
      <el-form ref="editFormRef" :model="editForm" label-position="top">
        <el-form-item label="账号">
          <el-input :model-value="editingUsername" disabled />
        </el-form-item>
        <el-form-item label="账号状态">
          <el-switch v-model="editForm.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
        <el-form-item label="可见模块">
          <div class="permission-editor">
            <div class="permission-editor__fixed">总览（所有账号固定可见）</div>
            <el-checkbox-group v-model="editForm.modules">
              <el-checkbox v-for="item in ASSIGNABLE_MODULES" :key="item.key" :value="item.key">
                {{ item.label }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ASSIGNABLE_MODULES, moduleLabel } from '@/config/permissions'
import { useAuth } from '@/composables/useAuth'

const { listAccounts, createAccount, updateAccount, updateAccountInfo, deleteAccount } = useAuth()
const accounts = ref([])
const loading = ref(false)
const submitting = ref(false)
const deletingUsername = ref('')
const createDialogVisible = ref(false)
const infoDialogVisible = ref(false)
const editDialogVisible = ref(false)
const createFormRef = ref()
const infoFormRef = ref()
const editFormRef = ref()
const editingUsername = ref('')
const editingInfoUsername = ref('')

const createForm = reactive({
  username: '',
  displayName: '',
  password: '',
  modules: [],
})

const infoForm = reactive({
  username: '',
  displayName: '',
  newPassword: '',
})

const editForm = reactive({
  displayName: '',
  enabled: true,
  modules: [],
})

const usernameRules = [
  { required: true, message: '请输入登录账号', trigger: 'blur' },
  { min: 3, max: 64, message: '账号长度为 3-64 个字符', trigger: 'blur' },
  { pattern: /^\S+$/, message: '账号不能包含空格', trigger: 'blur' },
]
const displayNameRules = [{ required: true, message: '请输入显示名称', trigger: 'blur' }]

const createRules = {
  username: usernameRules,
  displayName: displayNameRules,
  password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    { min: 6, message: '密码至少需要 6 位', trigger: 'blur' },
  ],
}

const infoRules = {
  username: usernameRules,
  displayName: displayNameRules,
  newPassword: [{ min: 6, message: '新密码至少需要 6 位', trigger: 'blur' }],
}

async function loadAccounts() {
  loading.value = true
  try {
    accounts.value = await listAccounts()
  } catch (error) {
    ElMessage.error(error.message || '加载账号失败')
  } finally {
    loading.value = false
  }
}

function resetCreateForm() {
  createForm.username = ''
  createForm.displayName = ''
  createForm.password = ''
  createForm.modules = []
  createFormRef.value?.clearValidate()
}

function openCreateDialog() {
  resetCreateForm()
  createDialogVisible.value = true
}

function openInfoDialog(row) {
  editingInfoUsername.value = row.username
  infoForm.username = row.username
  infoForm.displayName = row.display_name || row.username
  infoForm.newPassword = ''
  infoDialogVisible.value = true
}

function openEditDialog(row) {
  editingUsername.value = row.username
  editForm.displayName = row.display_name || row.username
  editForm.enabled = row.enabled !== false
  editForm.modules = [...(row.modules || [])]
  editDialogVisible.value = true
}

async function submitCreate() {
  if (!createFormRef.value || submitting.value) return
  try {
    await createFormRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    await createAccount(createForm)
    ElMessage.success('账号已创建')
    createDialogVisible.value = false
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '创建账号失败')
  } finally {
    submitting.value = false
  }
}

async function submitInfo() {
  if (!infoFormRef.value || submitting.value) return
  try {
    await infoFormRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    await updateAccountInfo(editingInfoUsername.value, infoForm)
    ElMessage.success('账户信息已更新')
    infoDialogVisible.value = false
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '更新账户信息失败')
  } finally {
    submitting.value = false
  }
}

async function deleteAccountRow(row) {
  try {
    await ElMessageBox.confirm(
      `删除后账号“${row.username}”将无法登录，确定继续吗？`,
      '删除账号',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  deletingUsername.value = row.username
  try {
    await deleteAccount(row.username)
    ElMessage.success('账号已删除')
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '删除账号失败')
  } finally {
    deletingUsername.value = ''
  }
}

async function submitEdit() {
  if (!editFormRef.value || submitting.value) return
  try {
    await editFormRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    await updateAccount(editingUsername.value, editForm)
    ElMessage.success('账号权限已更新')
    editDialogVisible.value = false
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error.message || '更新账号失败')
  } finally {
    submitting.value = false
  }
}

onMounted(loadAccounts)
</script>

<style scoped lang="scss">
.account-management__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}

.account-management__header h2 {
  margin: 10px 0 8px;
  color: var(--ti-text-primary);
  font-size: 28px;
}

.account-management__header p {
  margin: 0;
  color: var(--ti-text-secondary);
}

.fixed-permission-note {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 22px 0 16px;
  padding: 12px 14px;
  border: 1px solid rgba(45, 93, 255, 0.14);
  border-radius: 14px;
  background: rgba(45, 93, 255, 0.05);
  color: var(--ti-primary);
  font-size: 13px;
  font-weight: 600;
}

.account-table-shell {
  margin-top: 0;
}

.module-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  padding: 4px 0;
}

.module-tags__empty,
.fixed-admin-label {
  color: var(--ti-text-muted);
  font-size: 12px;
}

.account-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.account-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.permission-editor {
  width: 100%;
  padding: 14px;
  border: 1px solid var(--ti-border-soft);
  border-radius: 14px;
  background: rgba(247, 250, 255, 0.72);
}

.permission-editor__fixed {
  margin-bottom: 12px;
  color: var(--ti-primary);
  font-size: 13px;
  font-weight: 700;
}

.permission-editor :deep(.el-checkbox-group) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 14px;
}

@media (max-width: 720px) {
  .account-management__header {
    flex-direction: column;
  }

  .account-form-grid,
  .permission-editor :deep(.el-checkbox-group) {
    grid-template-columns: 1fr;
  }
}
</style>
