<template>
  <div class="social-settings ti-page">
    <header class="page-head">
      <div>
        <el-button text @click="router.push('/social-monitoring')">← 返回监测工作台</el-button>
        <div class="eyebrow">MONITORING SETTINGS</div>
        <h1>重要时间节点监测配置</h1>
        <p>任务启用后立即执行首轮，后续按启用时间锚点每 30 分钟运行。</p>
      </div>
      <el-button v-if="isAdmin" type="primary" @click="openCreate">新建监测任务</el-button>
    </header>

    <section class="settings-grid">
      <article class="content-card">
        <div class="card-head">
          <div><h2>监测任务</h2><p>{{ isAdmin ? '管理启停时间、平台、词项与重点源。' : '当前为只读视图，只有管理员可修改配置。' }}</p></div>
          <el-button :loading="loadingCampaigns" @click="loadCampaigns">刷新</el-button>
        </div>
        <el-table v-loading="loadingCampaigns" :data="campaigns" table-layout="fixed">
          <el-table-column prop="name" label="任务名称" min-width="190" show-overflow-tooltip />
          <el-table-column label="监测平台" min-width="190">
            <template #default="{ row }">{{ platformList(row.platforms) }}</template>
          </el-table-column>
          <el-table-column label="起止时间" min-width="280">
            <template #default="{ row }">{{ formatDateTime(row.startAt) }} 至 {{ formatDateTime(row.endAt) }}</template>
          </el-table-column>
          <el-table-column label="周期" width="110"><template #default>30 分钟</template></el-table-column>
          <el-table-column label="状态" width="95">
            <template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '已启用' : '已停用' }}</el-tag></template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link @click="openEdit(row)">{{ isAdmin ? '编辑' : '查看' }}</el-button>
              <el-button v-if="isAdmin" type="danger" link @click="removeCampaign(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </article>

      <article class="content-card">
        <div class="card-head"><div><h2>平台接入状态</h2><p>凭据只从环境变量或机器本地秘密文件读取。</p></div><el-button :loading="loadingPlatforms" @click="loadPlatforms">刷新</el-button></div>
        <div class="platform-grid">
          <div v-for="item in platforms" :key="item.platform" class="platform-card">
            <div>
              <strong>{{ platformLabel(item.platform) }}</strong>
              <el-tag size="small" :type="platformTone(item)">{{ platformStatus(item) }}</el-tag>
            </div>
            <p>{{ item.message || item.coverageDescription || '尚无状态说明' }}</p>
            <span>最近更新：{{ formatDateTime(item.updatedAt || item.lastCheckedAt) }}</span>
          </div>
          <div v-if="!platforms.length" class="empty">暂无平台状态</div>
        </div>
      </article>

      <article class="content-card content-card--full">
        <div class="card-head"><div><h2>最近监测轮次</h2><p>单平台失败会明确显示为采集异常，不作为“未发现威胁”。</p></div><el-button :loading="loadingScans" @click="loadScans">刷新</el-button></div>
        <el-table v-loading="loadingScans" :data="scans" table-layout="fixed">
          <el-table-column label="计划时间" width="170"><template #default="{ row }">{{ formatDateTime(row.scheduledAt) }}</template></el-table-column>
          <el-table-column label="任务" min-width="170"><template #default="{ row }">{{ row.campaignName || row.campaignId || '-' }}</template></el-table-column>
          <el-table-column label="平台" width="110"><template #default="{ row }">{{ platformLabel(row.platform) }}</template></el-table-column>
          <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="scanTone(row.status)">{{ scanStatus(row.status) }}</el-tag></template></el-table-column>
          <el-table-column prop="candidateCount" label="候选" width="80" />
          <el-table-column prop="newEventCount" label="新增" width="80" />
          <el-table-column prop="duplicateCount" label="重复" width="80" />
          <el-table-column label="完成时间" width="170"><template #default="{ row }">{{ formatDateTime(row.finishedAt) }}</template></el-table-column>
          <el-table-column prop="error" label="错误信息" min-width="220" show-overflow-tooltip />
        </el-table>
      </article>
    </section>

    <el-drawer v-model="drawerVisible" :title="editingId ? '编辑监测任务' : '新建监测任务'" size="640px" destroy-on-close>
      <el-form label-position="top" :model="form" :disabled="!isAdmin">
        <div class="form-grid">
          <el-form-item label="任务名称" class="full"><el-input v-model="form.name" placeholder="例如：重要会议期间专项监测" /></el-form-item>
          <el-form-item label="开始时间"><el-date-picker v-model="form.startAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" style="width: 100%" /></el-form-item>
          <el-form-item label="结束时间"><el-date-picker v-model="form.endAt" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" style="width: 100%" /></el-form-item>
          <el-form-item label="时区"><el-input model-value="Asia/Shanghai" disabled /></el-form-item>
          <el-form-item label="监测间隔"><el-input model-value="固定 30 分钟" disabled /></el-form-item>
          <el-form-item label="监测平台" class="full">
            <el-checkbox-group v-model="form.platforms">
              <el-checkbox v-for="item in platformOptions" :key="item.value" :value="item.value">{{ item.label }}</el-checkbox>
            </el-checkbox-group>
          </el-form-item>
          <el-form-item label="西藏地域词" class="full"><el-input v-model="form.regionTermsText" type="textarea" :rows="2" placeholder="使用换行或逗号分隔" /></el-form-item>
          <el-form-item label="具体单位 / 行业 / 品牌 / 域名别名" class="full"><el-input v-model="form.targetAliasesText" type="textarea" :rows="3" placeholder="使用换行或逗号分隔" /></el-form-item>
          <el-form-item label="威胁词" class="full"><el-input v-model="form.threatTermsText" type="textarea" :rows="3" placeholder="攻击、泄露、售卖、凭证、定向行动等" /></el-form-item>
          <el-form-item label="排除词" class="full"><el-input v-model="form.exclusionTermsText" type="textarea" :rows="2" placeholder="排除普通新闻与无关讨论" /></el-form-item>
          <el-form-item label="重点账号 / 页面 / 频道" class="full"><el-input v-model="form.sourcesText" type="textarea" :rows="4" placeholder="每行填写 平台｜账号或网址，例如 telegram｜example_channel" /></el-form-item>
          <el-form-item label="启停状态"><el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" /></el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="drawerVisible = false">{{ isAdmin ? '取消' : '关闭' }}</el-button>
        <el-button v-if="isAdmin" type="primary" :loading="saving" @click="saveCampaign">保存</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { listFromResponse, useSocialMonitoringApi } from '@/composables/useSocialMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const router = useRouter()
const api = useSocialMonitoringApi()
const { state } = useAuth()
const campaigns = ref([])
const platforms = ref([])
const scans = ref([])
const loadingCampaigns = ref(false)
const loadingPlatforms = ref(false)
const loadingScans = ref(false)
const drawerVisible = ref(false)
const editingId = ref('')
const saving = ref(false)
const platformOptions = [
  { label: 'X', value: 'x' }, { label: 'Facebook', value: 'facebook' },
  { label: 'YouTube', value: 'youtube' }, { label: 'Telegram', value: 'telegram' },
]
const form = reactive(emptyForm())
const isAdmin = computed(() => String(state.user?.role || '').toLowerCase() === 'admin')

onMounted(() => Promise.all([loadCampaigns(), loadPlatforms(), loadScans()]))

function emptyForm() {
  return { name: '', startAt: '', endAt: '', timezone: 'Asia/Shanghai', intervalSeconds: 1800, platforms: ['x', 'facebook', 'youtube', 'telegram'], regionTermsText: '西藏\n藏区', targetAliasesText: '', threatTermsText: '攻击\n泄露\n售卖\n凭证\n定向行动', exclusionTermsText: '', sourcesText: '', enabled: true }
}

async function loadCampaigns() {
  loadingCampaigns.value = true
  try { campaigns.value = listFromResponse(await api.loadCampaigns(), ['campaigns']) }
  catch (error) { ElMessage.error(error.message || '加载监测任务失败') }
  finally { loadingCampaigns.value = false }
}
async function loadPlatforms() {
  loadingPlatforms.value = true
  try { platforms.value = listFromResponse(await api.loadPlatforms(), ['platforms']) }
  catch (error) { ElMessage.error(error.message || '加载平台状态失败') }
  finally { loadingPlatforms.value = false }
}
async function loadScans() {
  loadingScans.value = true
  try { scans.value = listFromResponse(await api.loadScans({ limit: 50 }), ['scans']) }
  catch (error) { ElMessage.error(error.message || '加载监测轮次失败') }
  finally { loadingScans.value = false }
}

function openCreate() { editingId.value = ''; Object.assign(form, emptyForm()); drawerVisible.value = true }
function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    ...emptyForm(), ...row,
    regionTermsText: joinLines(row.terms?.region), targetAliasesText: joinLines(row.terms?.target),
    threatTermsText: joinLines(row.terms?.threat), exclusionTermsText: joinLines(row.terms?.exclude),
    sourcesText: joinLines((row.sources || []).map((item) => `${item.platform}｜${item.sourceValue}`)),
  })
  drawerVisible.value = true
}

async function saveCampaign() {
  if (!form.name || !form.startAt || !form.endAt || !form.platforms.length) {
    ElMessage.warning('请填写任务名称、起止时间并至少选择一个平台')
    return
  }
  if (new Date(form.endAt) <= new Date(form.startAt)) { ElMessage.warning('结束时间必须晚于开始时间'); return }
  const payload = {
    name: form.name, startAt: form.startAt, endAt: form.endAt, timezone: 'Asia/Shanghai', intervalSeconds: 1800,
    platforms: form.platforms,
    terms: {
      region: splitTerms(form.regionTermsText), target: splitTerms(form.targetAliasesText),
      threat: splitTerms(form.threatTermsText), exclude: splitTerms(form.exclusionTermsText),
    },
    sources: parseSources(form.sourcesText, form.platforms), enabled: form.enabled,
  }
  saving.value = true
  try {
    if (editingId.value) await api.updateCampaign(editingId.value, payload)
    else await api.createCampaign(payload)
    ElMessage.success('监测任务已保存')
    drawerVisible.value = false
    await loadCampaigns()
  } catch (error) { ElMessage.error(error.message || '保存监测任务失败') }
  finally { saving.value = false }
}

async function removeCampaign(row) {
  try { await ElMessageBox.confirm(`确认删除“${row.name}”？`, '删除任务', { type: 'warning' }) } catch { return }
  try { await api.deleteCampaign(row.id); ElMessage.success('任务已删除'); await loadCampaigns() }
  catch (error) { ElMessage.error(error.message || '删除任务失败') }
}

function splitTerms(value) { return [...new Set(String(value || '').split(/[\n,，]/).map((item) => item.trim()).filter(Boolean))] }
function parseSources(value, selectedPlatforms) {
  return String(value || '').split('\n').map((line) => line.trim()).filter(Boolean).map((line) => {
    const match = line.match(/^(x|facebook|youtube|telegram)\s*[|｜：]\s*(.+)$/i)
    const platform = match?.[1]?.toLowerCase() || inferPlatform(line) || selectedPlatforms[0]
    return { platform, sourceType: 'account', sourceValue: (match?.[2] || line).trim(), label: '' }
  })
}
function inferPlatform(value) { const text = value.toLowerCase(); if (text.includes('facebook.com')) return 'facebook'; if (text.includes('youtube.com') || text.includes('youtu.be')) return 'youtube'; if (text.includes('t.me')) return 'telegram'; if (text.includes('x.com') || text.includes('twitter.com')) return 'x'; return '' }
function joinLines(value) { return Array.isArray(value) ? value.join('\n') : value || '' }
function formatDateTime(value) { return formatShanghaiDateTime(value, { includeSeconds: true }) || '-' }
function platformLabel(value) { return platformOptions.find((item) => item.value === String(value || '').toLowerCase())?.label || value || '-' }
function platformList(value) { return Array.isArray(value) ? value.map(platformLabel).join('、') : '-' }
function platformStatus(item) { const key = item.status || item.healthStatus; return { healthy: '正常', success: '正常', configured: item.coverageLimited ? '已配置（覆盖受限）' : '已配置', limited: '覆盖受限', degraded: '覆盖受限', missingCredentials: '缺少凭据', missing_credentials: '缺少凭据', failed: '采集异常', error: '采集异常' }[key] || item.statusLabel || '待配置' }
function platformTone(item) { const key = item.status || item.healthStatus; if (['healthy', 'success', 'configured'].includes(key)) return 'success'; if (['limited', 'degraded'].includes(key)) return 'warning'; if (['failed', 'error'].includes(key)) return 'danger'; return 'info' }
function scanStatus(value) { return { queued: '待执行', running: '执行中', completed: '已完成', success: '已完成', delayed: '轮次延迟', failed: '采集异常' }[value] || value || '-' }
function scanTone(value) { return ['completed', 'success'].includes(value) ? 'success' : value === 'failed' ? 'danger' : value === 'delayed' ? 'warning' : 'info' }
</script>

<style lang="scss" scoped>
.social-settings { display: grid; gap: 20px; }
.page-head, .content-card { border: 1px solid var(--ti-border-soft); border-radius: 22px; background: #fff; box-shadow: var(--ti-shadow-sm); }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 24px 26px; }
.page-head h1 { margin: 5px 0 8px; font-size: 27px; }.page-head p, .card-head p { margin: 0; color: var(--ti-text-secondary); }
.eyebrow { color: var(--ti-primary); font-size: 11px; font-weight: 800; letter-spacing: .12em; }
.settings-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(360px, .8fr); gap: 20px; }
.content-card { min-width: 0; padding: 22px; }.content-card--full { grid-column: 1 / -1; }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }.card-head h2 { margin: 0 0 6px; font-size: 19px; }
.platform-grid { display: grid; gap: 11px; }.platform-card { padding: 14px; border: 1px solid var(--ti-border-soft); border-radius: 14px; }.platform-card > div { display: flex; justify-content: space-between; gap: 10px; }.platform-card p { margin: 10px 0; color: var(--ti-text-secondary); }.platform-card > span { color: var(--ti-text-muted); font-size: 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }.form-grid .full { grid-column: 1 / -1; }.empty { padding: 40px; color: var(--ti-text-muted); text-align: center; }
@media (max-width: 1000px) { .settings-grid { grid-template-columns: 1fr; }.content-card--full { grid-column: auto; } }
@media (max-width: 767px) { .page-head { flex-direction: column; }.form-grid { grid-template-columns: 1fr; }.form-grid .full { grid-column: auto; } }
</style>
