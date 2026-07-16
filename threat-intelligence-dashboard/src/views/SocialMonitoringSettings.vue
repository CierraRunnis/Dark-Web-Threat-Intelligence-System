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
        <div class="card-head"><div><h2>平台接入状态</h2><p>凭据只从环境变量或机器本地秘密文件读取。</p></div><el-button :loading="loadingPlatforms" @click="refreshPlatformState">刷新</el-button></div>
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

      <article v-if="isAdmin" id="platform-access-config" class="content-card content-card--full">
        <div class="card-head">
          <div><h2>免费平台接入配置</h2><p>在这里配置 YouTube Data API 和 Telegram MTProto。已保存的值不会回显。</p></div>
          <el-button :loading="loadingAccessConfig" @click="loadAccessConfig">刷新配置状态</el-button>
        </div>
        <el-alert
          title="凭据采用只写方式保存到服务端用户私有目录，Linux 下文件权限为 0600；环境变量优先级更高且不能在页面覆盖。"
          type="info"
          :closable="false"
          show-icon
          class="config-alert"
        />
        <div v-loading="loadingAccessConfig" class="access-grid">
          <section class="access-panel">
            <div class="access-title">
              <div><span class="platform-mark youtube">YT</span><strong>YouTube Data API</strong></div>
              <el-tag :type="accessConfigured('youtube') ? 'success' : 'info'">{{ accessConfigured('youtube') ? '已接入' : '待配置' }}</el-tag>
            </div>
            <p class="access-description">用于关键词搜索和重点频道新视频监测。重点频道通过 uploads 播放列表读取，不占用搜索调用次数。</p>
            <el-form label-position="top">
              <el-form-item>
                <template #label><span>API Key <em>{{ credentialLabel('youtube', 'apiKey') }}</em></span></template>
                <el-input
                  v-model="youtubeForm.apiKey"
                  type="password"
                  show-password
                  autocomplete="new-password"
                  :disabled="credentialLocked('youtube', 'apiKey')"
                  :placeholder="credentialPlaceholder('youtube', 'apiKey', '粘贴 Google Cloud API Key')"
                />
              </el-form-item>
            </el-form>
            <div class="access-actions">
              <el-button type="primary" :loading="savingPlatform === 'youtube'" :disabled="credentialLocked('youtube', 'apiKey')" @click="saveAccessConfig('youtube')">保存 YouTube 配置</el-button>
              <el-button v-if="hasLocalCredential('youtube')" type="danger" plain @click="clearAccessConfig('youtube')">清除页面配置</el-button>
            </div>
          </section>

          <section class="access-panel">
            <div class="access-title">
              <div><span class="platform-mark telegram">TG</span><strong>Telegram MTProto</strong></div>
              <el-tag :type="accessConfigured('telegram') ? 'success' : 'info'">{{ accessConfigured('telegram') ? '已接入' : '待配置' }}</el-tag>
            </div>
            <p class="access-description">用于公开广播频道关键词和重点频道主消息监测。保存 API ID 和 API Hash 后，可直接在本页面完成账号验证。</p>
            <el-form label-position="top" class="telegram-form">
              <el-form-item>
                <template #label><span>API ID <em>{{ credentialLabel('telegram', 'apiId') }}</em></span></template>
                <el-input v-model="telegramForm.apiId" :disabled="credentialLocked('telegram', 'apiId')" :placeholder="credentialPlaceholder('telegram', 'apiId', 'my.telegram.org 获取的数字 ID')" />
              </el-form-item>
              <el-form-item>
                <template #label><span>API Hash <em>{{ credentialLabel('telegram', 'apiHash') }}</em></span></template>
                <el-input v-model="telegramForm.apiHash" type="password" show-password autocomplete="new-password" :disabled="credentialLocked('telegram', 'apiHash')" :placeholder="credentialPlaceholder('telegram', 'apiHash', '32 位 API Hash')" />
              </el-form-item>
              <el-form-item class="session-field">
                <template #label><span>已有 StringSession（可选） <em>{{ credentialLabel('telegram', 'session') }}</em></span></template>
                <el-input v-model="telegramForm.session" type="password" show-password autocomplete="new-password" :disabled="credentialLocked('telegram', 'session')" :placeholder="credentialPlaceholder('telegram', 'session', '已有会话可直接粘贴；也可使用下方页面登录生成')" />
              </el-form-item>
            </el-form>
            <div class="session-wizard">
              <div class="session-wizard-head">
                <div><strong>页面生成 StringSession</strong><span>验证码和两步验证密码仅用于本次登录，不会保存或回显。</span></div>
                <el-tag size="small" :type="credential('telegram', 'session').configured ? 'success' : 'info'">
                  {{ credential('telegram', 'session').configured ? '会话已配置' : '等待验证' }}
                </el-tag>
              </div>
              <el-alert
                v-if="!telegramApiCredentialsReady"
                title="请先在上方保存 API ID 和 API Hash，再发送验证码。"
                type="warning"
                :closable="false"
                show-icon
              />
              <el-form label-position="top" class="session-wizard-form">
                <el-form-item v-if="!telegramLogin.attemptId" label="Telegram 登录手机号" class="full">
                  <el-input v-model="telegramLogin.phone" autocomplete="tel" placeholder="国际格式，例如 +8613800138000" />
                </el-form-item>
                <template v-else>
                  <el-form-item v-if="telegramLogin.status !== 'password_required'" label="Telegram 验证码">
                    <el-input v-model="telegramLogin.code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="输入 Telegram 收到的验证码" />
                  </el-form-item>
                  <el-form-item :label="telegramLogin.status === 'password_required' ? '两步验证密码' : '两步验证密码（如已启用）'">
                    <el-input v-model="telegramLogin.password" type="password" show-password autocomplete="current-password" placeholder="未启用两步验证可留空" />
                  </el-form-item>
                  <div class="session-expiry full">本次验证将在 {{ formatDateTime(telegramLogin.expiresAt) }} 失效。</div>
                </template>
              </el-form>
              <div class="session-wizard-actions">
                <el-button
                  v-if="!telegramLogin.attemptId"
                  type="primary"
                  :loading="telegramLoginBusy"
                  :disabled="!telegramApiCredentialsReady"
                  @click="startTelegramLogin"
                >发送验证码</el-button>
                <template v-else>
                  <el-button type="primary" :loading="telegramLoginBusy" @click="completeTelegramLogin">
                    {{ telegramLogin.status === 'password_required' ? '验证两步密码并保存' : '完成登录并保存会话' }}
                  </el-button>
                  <el-button :disabled="telegramLoginBusy" @click="cancelTelegramLogin">取消本次验证</el-button>
                </template>
              </div>
            </div>
            <div class="access-actions">
              <el-button type="primary" :loading="savingPlatform === 'telegram'" @click="saveAccessConfig('telegram')">保存 Telegram 配置</el-button>
              <el-button v-if="hasLocalCredential('telegram')" type="danger" plain @click="clearAccessConfig('telegram')">清除页面配置</el-button>
            </div>
          </section>
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
const accessConfig = ref({})
const loadingCampaigns = ref(false)
const loadingPlatforms = ref(false)
const loadingScans = ref(false)
const loadingAccessConfig = ref(false)
const drawerVisible = ref(false)
const editingId = ref('')
const saving = ref(false)
const savingPlatform = ref('')
const telegramLoginBusy = ref(false)
const platformOptions = [
  { label: 'X', value: 'x' }, { label: 'Facebook', value: 'facebook' },
  { label: 'YouTube', value: 'youtube' }, { label: 'Telegram', value: 'telegram' },
]
const form = reactive(emptyForm())
const youtubeForm = reactive({ apiKey: '' })
const telegramForm = reactive({ apiId: '', apiHash: '', session: '' })
const telegramLogin = reactive({ phone: '', code: '', password: '', attemptId: '', status: 'idle', expiresAt: '' })
const isAdmin = computed(() => String(state.user?.role || '').toLowerCase() === 'admin')
const telegramApiCredentialsReady = computed(() => (
  credential('telegram', 'apiId').configured && credential('telegram', 'apiHash').configured
))

onMounted(() => Promise.all([loadCampaigns(), loadPlatforms(), loadScans(), ...(isAdmin.value ? [loadAccessConfig()] : [])]))

function emptyForm() {
  return { name: '', startAt: '', endAt: '', timezone: 'Asia/Shanghai', intervalSeconds: 1800, platforms: ['youtube', 'telegram'], regionTermsText: '西藏\n藏区', targetAliasesText: '', threatTermsText: '攻击\n泄露\n售卖\n凭证\n定向行动', exclusionTermsText: '', sourcesText: '', enabled: true }
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
async function loadAccessConfig() {
  if (!isAdmin.value) return
  loadingAccessConfig.value = true
  try { accessConfig.value = await api.loadPlatformConfig() }
  catch (error) { ElMessage.error(error.message || '加载平台接入配置失败') }
  finally { loadingAccessConfig.value = false }
}
async function refreshPlatformState() { await Promise.all([loadPlatforms(), ...(isAdmin.value ? [loadAccessConfig()] : [])]) }
async function loadScans() {
  loadingScans.value = true
  try { scans.value = listFromResponse(await api.loadScans({ limit: 50 }), ['scans']) }
  catch (error) { ElMessage.error(error.message || '加载监测轮次失败') }
  finally { loadingScans.value = false }
}

async function saveAccessConfig(platform) {
  const payload = platform === 'youtube'
    ? { apiKey: youtubeForm.apiKey.trim() }
    : {
        apiId: telegramForm.apiId.trim(),
        apiHash: telegramForm.apiHash.trim(),
        session: telegramForm.session.trim(),
      }
  const cleanPayload = Object.fromEntries(Object.entries(payload).filter(([, value]) => value))
  if (!Object.keys(cleanPayload).length) { ElMessage.warning('请至少填写一项需要保存的凭据'); return }
  savingPlatform.value = platform
  try {
    await api.savePlatformConfig(platform, cleanPayload)
    Object.assign(platform === 'youtube' ? youtubeForm : telegramForm, platform === 'youtube' ? { apiKey: '' } : { apiId: '', apiHash: '', session: '' })
    ElMessage.success(`${platformLabel(platform)} 配置已安全保存`)
    await Promise.all([loadAccessConfig(), loadPlatforms()])
  } catch (error) { ElMessage.error(error.message || '保存平台配置失败') }
  finally { savingPlatform.value = '' }
}

async function clearAccessConfig(platform) {
  try { await ElMessageBox.confirm(`确认清除页面保存的 ${platformLabel(platform)} 凭据？`, '清除平台配置', { type: 'warning' }) } catch { return }
  try {
    await api.clearPlatformConfig(platform)
    if (platform === 'telegram') resetTelegramLogin()
    ElMessage.success(`${platformLabel(platform)} 页面配置已清除`)
    await Promise.all([loadAccessConfig(), loadPlatforms()])
  } catch (error) { ElMessage.error(error.message || '清除平台配置失败') }
}

function resetTelegramLogin() {
  Object.assign(telegramLogin, { phone: '', code: '', password: '', attemptId: '', status: 'idle', expiresAt: '' })
}

async function startTelegramLogin() {
  const phone = telegramLogin.phone.replace(/[\s()-]/g, '')
  if (!/^\+[1-9][0-9]{6,14}$/.test(phone)) {
    ElMessage.warning('请输入带国家区号的手机号，例如 +8613800138000')
    return
  }
  telegramLoginBusy.value = true
  try {
    const result = await api.startTelegramSession({ phone })
    Object.assign(telegramLogin, {
      phone: '', code: '', password: '', attemptId: result.attemptId,
      status: result.status, expiresAt: result.expiresAt,
    })
    ElMessage.success('验证码已发送，请查看 Telegram 官方消息')
  } catch (error) { ElMessage.error(error.message || '发送 Telegram 验证码失败') }
  finally { telegramLoginBusy.value = false }
}

async function completeTelegramLogin() {
  if (telegramLogin.status !== 'password_required' && !/^\d{4,8}$/.test(telegramLogin.code.trim())) {
    ElMessage.warning('请输入 Telegram 验证码')
    return
  }
  if (telegramLogin.status === 'password_required' && !telegramLogin.password) {
    ElMessage.warning('请输入 Telegram 两步验证密码')
    return
  }
  telegramLoginBusy.value = true
  try {
    const result = await api.completeTelegramSession({
      attemptId: telegramLogin.attemptId,
      code: telegramLogin.code.trim(),
      password: telegramLogin.password,
    })
    telegramLogin.code = ''
    telegramLogin.password = ''
    if (result.status === 'password_required') {
      telegramLogin.status = 'password_required'
      telegramLogin.expiresAt = result.expiresAt
      ElMessage.warning('该账号已启用两步验证，请继续输入密码')
      return
    }
    resetTelegramLogin()
    ElMessage.success('Telegram 会话已生成并安全保存')
    await Promise.all([loadAccessConfig(), loadPlatforms()])
  } catch (error) {
    telegramLogin.code = ''
    telegramLogin.password = ''
    ElMessage.error(error.message || 'Telegram 登录验证失败')
  } finally { telegramLoginBusy.value = false }
}

async function cancelTelegramLogin() {
  const attemptId = telegramLogin.attemptId
  resetTelegramLogin()
  if (!attemptId) return
  try { await api.cancelTelegramSession(attemptId) }
  catch (error) { ElMessage.error(error.message || '取消 Telegram 登录失败') }
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
function credential(platform, field) { return accessConfig.value?.[platform]?.credentials?.[field] || { configured: false, source: 'missing' } }
function accessConfigured(platform) { return Boolean(accessConfig.value?.[platform]?.configured) }
function credentialLocked(platform, field) { return credential(platform, field).source === 'environment' }
function credentialLabel(platform, field) { return { environment: '由环境变量管理', localFile: '已由页面保存', local_file: '已由页面保存', missing: '未配置' }[credential(platform, field).source] || '未配置' }
function credentialPlaceholder(platform, field, emptyText) { const item = credential(platform, field); return item.configured ? (item.source === 'environment' ? '环境变量已配置，页面不可覆盖' : '已保存；留空表示保持不变') : emptyText }
function hasLocalCredential(platform) { return Object.values(accessConfig.value?.[platform]?.credentials || {}).some((item) => ['local_file', 'localFile'].includes(item.source)) }
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
.config-alert { margin-bottom: 18px; }
.access-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.access-panel { padding: 18px; border: 1px solid var(--ti-border-soft); border-radius: 18px; background: linear-gradient(180deg, #fff, #fafcff); }
.access-title, .access-title > div, .access-actions { display: flex; align-items: center; gap: 10px; }
.access-title { justify-content: space-between; }.access-title strong { font-size: 17px; }
.platform-mark { display: inline-grid; width: 34px; height: 34px; place-items: center; border-radius: 10px; color: #fff; font-size: 11px; font-weight: 800; }
.platform-mark.youtube { background: #e53935; }.platform-mark.telegram { background: #168acd; }
.access-description { min-height: 42px; margin: 14px 0 16px; color: var(--ti-text-secondary); line-height: 1.6; }
.access-panel :deep(.el-form-item__label) em { margin-left: 8px; color: var(--ti-text-muted); font-size: 12px; font-style: normal; font-weight: 400; }
.telegram-form { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }.telegram-form .session-field { grid-column: 1 / -1; }
.session-wizard { margin: 2px 0 16px; padding: 15px; border: 1px solid #cfe5f4; border-radius: 14px; background: #f5fbff; }
.session-wizard-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 13px; }
.session-wizard-head > div { display: grid; gap: 4px; }.session-wizard-head span { color: var(--ti-text-muted); font-size: 12px; line-height: 1.5; }
.session-wizard-form { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; margin-top: 13px; }.session-wizard-form .full { grid-column: 1 / -1; }
.session-wizard-actions { display: flex; align-items: center; gap: 10px; }.session-expiry { margin: -6px 0 13px; color: var(--ti-text-muted); font-size: 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }.form-grid .full { grid-column: 1 / -1; }.empty { padding: 40px; color: var(--ti-text-muted); text-align: center; }
@media (max-width: 1000px) { .settings-grid, .access-grid { grid-template-columns: 1fr; }.content-card--full { grid-column: auto; }.access-description { min-height: 0; } }
@media (max-width: 767px) { .page-head { flex-direction: column; }.form-grid, .telegram-form, .session-wizard-form { grid-template-columns: 1fr; }.form-grid .full, .telegram-form .session-field, .session-wizard-form .full { grid-column: auto; }.access-actions, .session-wizard-actions { align-items: stretch; flex-direction: column; }.access-actions .el-button, .session-wizard-actions .el-button { margin-left: 0; }.session-wizard-head { flex-direction: column; } }
</style>
