<template>
  <div class="user-management ti-page">
    <header class="page-head">
      <div>
        <el-button text @click="router.push('/social-monitoring')">← 返回社交平台监测</el-button>
        <div class="eyebrow">ACCESS CONTROL</div>
        <h1>用户管理</h1>
        <p>管理员维护账号；分析员负责领取、初验、证据脱敏、发布和报告生成。</p>
      </div>
      <el-button type="primary" @click="openCreate">新建用户</el-button>
    </header>

    <section class="content-card">
      <div class="card-head"><div><h2>系统用户</h2><p>共 {{ users.length }} 个账号</p></div><el-button :loading="loading" @click="loadUsers">刷新</el-button></div>
      <el-table v-loading="loading" :data="users" table-layout="fixed">
        <el-table-column prop="username" label="账号" min-width="150" />
        <el-table-column label="显示名称" min-width="160"><template #default="{ row }">{{ row.displayName || row.username }}</template></el-table-column>
        <el-table-column label="角色" width="120"><template #default="{ row }"><el-tag :type="row.role === 'admin' ? 'danger' : 'info'">{{ roleLabel(row.role) }}</el-tag></template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.enabled === false ? 'info' : 'success'">{{ row.enabled === false ? '已禁用' : '已启用' }}</el-tag></template></el-table-column>
        <el-table-column label="最近登录" width="180"><template #default="{ row }">{{ formatDateTime(row.lastLoginAt) }}</template></el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-button type="primary" link @click="openPassword(row)">重置密码</el-button>
            <el-button type="danger" link :disabled="isCurrentUser(row)" @click="removeUser(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑用户' : '新建用户'" width="480px" destroy-on-close>
      <el-form label-position="top" :model="form">
        <el-form-item label="账号"><el-input v-model="form.username" :disabled="Boolean(editingId)" autocomplete="off" /></el-form-item>
        <el-form-item label="显示名称"><el-input v-model="form.displayName" /></el-form-item>
        <el-form-item v-if="!editingId" label="初始密码"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="form.role"><el-radio value="analyst">分析员</el-radio><el-radio value="admin">管理员</el-radio></el-radio-group>
        </el-form-item>
        <el-form-item label="状态"><el-switch v-model="form.enabled" active-text="启用" inactive-text="禁用" :disabled="editingId && isCurrentUser({ id: editingId })" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveUser">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="passwordVisible" title="重置密码" width="430px" destroy-on-close>
      <p class="dialog-note">为账号 <strong>{{ passwordTarget?.username }}</strong> 设置新密码。</p>
      <el-input v-model="newPassword" type="password" show-password autocomplete="new-password" placeholder="至少 8 位" />
      <template #footer><el-button @click="passwordVisible = false">取消</el-button><el-button type="primary" :loading="savingPassword" @click="resetPassword">确认重置</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { listFromResponse, useSocialMonitoringApi } from '@/composables/useSocialMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const router = useRouter()
const api = useSocialMonitoringApi()
const { state } = useAuth()
const users = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const passwordVisible = ref(false)
const editingId = ref('')
const saving = ref(false)
const savingPassword = ref(false)
const passwordTarget = ref(null)
const newPassword = ref('')
const form = reactive(emptyForm())

onMounted(loadUsers)

function emptyForm() { return { username: '', displayName: '', password: '', role: 'analyst', enabled: true } }
async function loadUsers() {
  loading.value = true
  try { users.value = listFromResponse(await api.loadUsers(), ['users']) }
  catch (error) { ElMessage.error(error.message || '加载用户失败') }
  finally { loading.value = false }
}
function openCreate() { editingId.value = ''; Object.assign(form, emptyForm()); dialogVisible.value = true }
function openEdit(row) { editingId.value = row.id; Object.assign(form, { ...emptyForm(), ...row, password: '' }); dialogVisible.value = true }
async function saveUser() {
  if (!form.username || !form.displayName || !form.role || (!editingId.value && form.password.length < 8)) {
    ElMessage.warning(editingId.value ? '请完整填写用户信息' : '请完整填写信息，初始密码至少 8 位')
    return
  }
  saving.value = true
  try {
    if (editingId.value) await api.updateUser(editingId.value, { displayName: form.displayName, role: form.role, enabled: form.enabled })
    else await api.createUser({ username: form.username, displayName: form.displayName, password: form.password, role: form.role, enabled: form.enabled })
    ElMessage.success('用户已保存')
    dialogVisible.value = false
    await loadUsers()
  } catch (error) { ElMessage.error(error.message || '保存用户失败') }
  finally { saving.value = false }
}
function openPassword(row) { passwordTarget.value = row; newPassword.value = ''; passwordVisible.value = true }
async function resetPassword() {
  if (newPassword.value.length < 8) { ElMessage.warning('新密码至少 8 位'); return }
  savingPassword.value = true
  try { await api.resetUserPassword(passwordTarget.value.id, newPassword.value); ElMessage.success('密码已重置'); passwordVisible.value = false }
  catch (error) { ElMessage.error(error.message || '重置密码失败') }
  finally { savingPassword.value = false }
}
async function removeUser(row) {
  try { await ElMessageBox.confirm(`确认删除账号“${row.username}”？`, '删除用户', { type: 'warning' }) } catch { return }
  try { await api.deleteUser(row.id); ElMessage.success('用户已删除'); await loadUsers() }
  catch (error) { ElMessage.error(error.message || '删除用户失败') }
}
function isCurrentUser(row) { return String(row.id || '') === String(state.user?.id || '') }
function roleLabel(role) { return role === 'admin' ? '管理员' : '分析员' }
function formatDateTime(value) { return formatShanghaiDateTime(value, { includeSeconds: true }) || '-' }
</script>

<style lang="scss" scoped>
.user-management { display: grid; gap: 20px; }.page-head, .content-card { border: 1px solid var(--ti-border-soft); border-radius: 22px; background: #fff; box-shadow: var(--ti-shadow-sm); }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 24px 26px; }.page-head h1 { margin: 5px 0 8px; font-size: 27px; }.page-head p, .card-head p { margin: 0; color: var(--ti-text-secondary); }.eyebrow { color: var(--ti-primary); font-size: 11px; font-weight: 800; letter-spacing: .12em; }
.content-card { padding: 22px; }.card-head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 18px; }.card-head h2 { margin: 0 0 6px; font-size: 19px; }.dialog-note { margin: 0 0 16px; color: var(--ti-text-secondary); }
@media (max-width: 767px) { .page-head { flex-direction: column; } }
</style>
