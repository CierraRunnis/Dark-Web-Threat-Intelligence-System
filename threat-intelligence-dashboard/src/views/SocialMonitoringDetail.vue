<template>
  <div class="social-detail ti-page">
    <header class="detail-head">
      <div>
        <el-button text @click="router.push('/social-monitoring')">← 返回社交平台监测</el-button>
        <div class="eyebrow">SOCIAL THREAT DETAIL</div>
        <h1>{{ event.threatTitle || event.title || '威胁事件详情' }}</h1>
        <div class="meta-line">
          <span>{{ platformLabel(event.platform) }}</span>
          <span>{{ formatDateTime(event.discoveredAt) }}</span>
          <a v-if="event.sourceUrl" :href="event.sourceUrl" target="_blank" rel="noreferrer">打开原始网址</a>
        </div>
      </div>
      <div class="head-tags">
        <el-tag :type="severityTone(event.severity)">{{ severityLabel(event.severity) }}</el-tag>
        <el-tag effect="plain">{{ statusLabel(event.verificationStatus || event.status) }}</el-tag>
        <el-button
          v-if="canClaim"
          type="primary"
          :loading="busyAction === 'claim'"
          @click="claimEvent"
        >
          领取事件
        </el-button>
      </div>
    </header>

    <section class="detail-grid">
      <article class="detail-card">
        <div class="card-title"><span>线索</span><h2>原始内容与命中依据</h2></div>
        <dl class="info-grid">
          <dt>来源平台</dt><dd>{{ platformLabel(event.platform) }}</dd>
          <dt>来源账号</dt><dd>{{ event.author || event.sourceAccount || '-' }}</dd>
          <dt>原帖时间</dt><dd>{{ formatDateTime(event.sourcePublishedAt || event.publishedAt || event.postedAt) }}</dd>
          <dt>发现时间</dt><dd>{{ formatDateTime(event.discoveredAt) }}</dd>
          <dt>命中关键词</dt><dd>{{ listText(event.matchedTerms) }}</dd>
          <dt>关联目标</dt><dd>{{ [event.targetUnit, event.targetIndustry].filter(Boolean).join(' / ') || '-' }}</dd>
        </dl>
        <div class="original-text">{{ event.originalText || event.content || '暂无原始正文' }}</div>
      </article>

      <article class="detail-card">
        <div class="card-title"><span>初验</span><h2>威胁核验与处置方向</h2></div>
        <el-form label-position="top" :model="verifyForm">
          <div class="form-grid">
            <el-form-item label="威胁标题" class="full"><el-input v-model="verifyForm.threatTitle" /></el-form-item>
            <el-form-item label="威胁类型">
              <el-select v-model="verifyForm.threatType" placeholder="请选择">
                <el-option label="扬言攻击" value="attackThreat" />
                <el-option label="数据售卖" value="dataSale" />
                <el-option label="数据泄露" value="dataLeak" />
                <el-option label="凭证售卖" value="credentialSale" />
                <el-option label="定向攻击" value="targetedAttack" />
                <el-option label="其他" value="other" />
              </el-select>
            </el-form-item>
            <el-form-item label="初验结论">
              <el-select v-model="verifyForm.result" placeholder="请选择">
                <el-option label="较可信" value="credible" />
                <el-option label="待持续核实" value="monitor" />
                <el-option label="误报" value="falsePositive" />
              </el-select>
            </el-form-item>
            <el-form-item label="具体单位"><el-input v-model="verifyForm.targetUnit" /></el-form-item>
            <el-form-item label="关联行业"><el-input v-model="verifyForm.targetIndustry" /></el-form-item>
            <el-form-item label="事件等级">
              <el-select v-model="verifyForm.severity" :disabled="!isAdmin">
                <el-option label="一般" value="normal" />
                <el-option label="重大" value="major" />
                <el-option label="紧急" value="emergency" />
              </el-select>
            </el-form-item>
            <el-form-item label="证据说明" class="full"><el-input v-model="verifyForm.evidenceNote" type="textarea" :rows="3" /></el-form-item>
            <el-form-item label="初步处置方向" class="full"><el-input v-model="verifyForm.disposalDirection" type="textarea" :rows="4" /></el-form-item>
          </div>
        </el-form>
        <div class="actions-row">
          <span v-if="event.verificationDurationSeconds">实际初验耗时：{{ durationText(event.verificationDurationSeconds) }}</span>
          <el-button type="primary" :loading="busyAction === 'verify'" :disabled="!canVerify" @click="submitVerification">保存初验</el-button>
        </div>
      </article>
    </section>

    <section class="detail-card evidence-card">
      <div class="card-title-row">
        <div class="card-title"><span>证据</span><h2>截图合规处理</h2></div>
        <div class="evidence-actions">
          <el-button :loading="busyAction === 'capture'" :disabled="!canVerify" @click="captureEvidence">授权浏览器取证</el-button>
          <el-upload :auto-upload="false" :show-file-list="false" accept="image/png,image/jpeg" :on-change="uploadEvidence">
            <el-button :loading="busyAction === 'upload'" :disabled="!canVerify">取证失败时上传 PNG / JPEG</el-button>
          </el-upload>
        </div>
      </div>
      <p class="card-note">原图不直接发布。选择证据后在图中拖动框选敏感区域，生成不可逆黑框合规副本。</p>
      <div class="evidence-layout">
        <div class="evidence-list">
          <button
            v-for="item in originalEvidence"
            :key="item.id"
            type="button"
            :class="['evidence-item', { active: selectedEvidenceId === item.id }]"
            @click="selectEvidence(item)"
          >
            <strong>{{ item.originalFilename || `证据 ${item.id}` }}</strong>
            <span>{{ evidenceStatusLabel(item) }}</span>
            <small>SHA-256 {{ shortHash(item.sha256) }}</small>
          </button>
          <div v-if="!evidence.length" class="empty-state">暂无截图证据</div>
        </div>
        <div class="canvas-panel">
          <canvas
            ref="canvasRef"
            :class="{ 'canvas--ready': canvasReady }"
            @mousedown="startSelection"
            @mousemove="moveSelection"
            @mouseup="finishSelection"
            @mouseleave="finishSelection"
          ></canvas>
          <div v-if="!canvasReady" class="canvas-empty">选择一张原始截图后开始脱敏</div>
          <div class="canvas-actions">
            <span>已框选 {{ rectangles.length }} 个区域</span>
            <el-button size="small" :disabled="!rectangles.length" @click="clearRectangles">清空框选</el-button>
            <el-button
              size="small"
              type="primary"
              :loading="busyAction === 'redact'"
              :disabled="!selectedEvidenceId || !rectangles.length || !canVerify"
              @click="redactEvidence"
            >
              生成并审批合规图
            </el-button>
          </div>
        </div>
        <div class="compliant-preview">
          <strong>合规副本</strong>
          <img v-if="compliantImageUrl" :src="compliantImageUrl" alt="合规证据截图" />
          <div v-else class="empty-state">尚未生成合规副本</div>
        </div>
      </div>
    </section>

    <section class="detail-card release-card">
      <div>
        <div class="card-title"><span>发布</span><h2>平台内情报卡片与专项报告</h2></div>
        <p class="card-note">发布前必须完成初验并至少有一张已审批合规截图。专项报告仅适用于重大或紧急事件。</p>
      </div>
      <div class="release-actions">
        <el-button
          :loading="busyAction === 'report'"
          :disabled="!canGenerateReport"
          @click="generateReport"
        >
          生成 DOCX 草稿
        </el-button>
        <el-button
          type="primary"
          :loading="busyAction === 'publish'"
          :disabled="!canPublish"
          @click="publishEvent"
        >
          发布到通知中心
        </el-button>
        <el-button v-if="!isClosed" type="danger" plain :loading="busyAction === 'close'" @click="closeEvent">关闭事件</el-button>
      </div>
    </section>

    <section class="detail-card" v-if="actions.length">
      <div class="card-title"><span>审计</span><h2>事件操作记录</h2></div>
      <el-timeline>
        <el-timeline-item v-for="item in actions" :key="item.id || `${item.actionType}-${item.createdAt}`" :timestamp="formatDateTime(item.createdAt)">
          <strong>{{ actionLabel(item.actionType || item.action) }}</strong>
          <span class="audit-actor">{{ item.actorDisplayName || item.actorUsername || 'system' }}</span>
          <p v-if="item.note">{{ item.note }}</p>
        </el-timeline-item>
      </el-timeline>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { listFromResponse, useSocialMonitoringApi } from '@/composables/useSocialMonitoringApi'
import { formatShanghaiDateTime } from '@/composables/useShanghaiTime'

const route = useRoute()
const router = useRouter()
const api = useSocialMonitoringApi()
const { state } = useAuth()
const event = reactive({})
const evidence = ref([])
const actions = ref([])
const busyAction = ref('')
const selectedEvidenceId = ref('')
const canvasRef = ref()
const canvasReady = ref(false)
const rectangles = ref([])
const dragStart = ref(null)
const dragCurrent = ref(null)
const originalImageUrl = ref('')
const compliantImageUrl = ref('')
let canvasImage = null

const verifyForm = reactive({
  threatTitle: '', threatType: '', result: '', targetUnit: '', targetIndustry: '',
  severity: 'normal', evidenceNote: '', disposalDirection: '',
})

const userRole = computed(() => String(state.user?.role || '').toLowerCase())
const isAdmin = computed(() => userRole.value === 'admin')
const isClosed = computed(() => (event.verificationStatus || event.status) === 'closed')
const canClaim = computed(() => ['pending', 'unclaimed'].includes(event.verificationStatus || event.status))
const canVerify = computed(() => isAdmin.value || String(event.assignedTo || event.assignedUserId || '') === String(state.user?.id || ''))
const originalEvidence = computed(() => evidence.value.filter((item) =>
  item.evidenceType !== 'redacted' && ['image/png', 'image/jpeg'].includes(item.mimeType),
))
const hasApprovedEvidence = computed(() => evidence.value.some((item) => item.evidenceType === 'redacted' && item.approved))
const canPublish = computed(() => ['verified', 'verificationCompleted'].includes(event.verificationStatus || event.status) && hasApprovedEvidence.value)
const canGenerateReport = computed(() => ['major', 'emergency'].includes(verifyForm.severity || event.severity) && ['verified', 'published'].includes(event.verificationStatus || event.status))

onMounted(loadDetail)
onBeforeUnmount(revokeImageUrls)

async function loadDetail() {
  try {
    const payload = await api.loadEvent(route.params.eventId)
    Object.assign(event, payload?.event || payload)
    evidence.value = listFromResponse(payload?.evidence || [], ['evidence'])
    actions.value = listFromResponse(payload?.actions || [], ['actions'])
    Object.assign(verifyForm, {
      threatTitle: event.threatTitle || event.title || '',
      threatType: event.threatType || '',
      result: event.verificationResult || event.result || '',
      targetUnit: event.targetUnit || '',
      targetIndustry: event.targetIndustry || '',
      severity: event.severity || 'normal',
      evidenceNote: event.evidenceNote || '',
      disposalDirection: event.disposalDirection || '',
    })
  } catch (error) {
    ElMessage.error(error.message || '加载事件详情失败')
  }
}

async function loadEvidence() {
  try {
    const payload = await api.loadEvent(route.params.eventId)
    evidence.value = listFromResponse(payload?.evidence || [], ['evidence'])
  } catch (error) {
    ElMessage.error(error.message || '加载证据失败')
  }
}

async function claimEvent() {
  busyAction.value = 'claim'
  try {
    await api.claimEvent(route.params.eventId)
    ElMessage.success('事件已领取')
    await loadDetail()
  } catch (error) {
    ElMessage.error(error.message || '领取失败')
  } finally { busyAction.value = '' }
}

async function submitVerification() {
  if (!verifyForm.threatTitle || !verifyForm.threatType || !verifyForm.result) {
    ElMessage.warning('请完整填写威胁标题、类型、初验结论和处置方向')
    return
  }
  if (verifyForm.result !== 'falsePositive' && !verifyForm.disposalDirection) {
    ElMessage.warning('请填写初步处置方向')
    return
  }
  if (verifyForm.result !== 'falsePositive' && !verifyForm.targetUnit && !verifyForm.targetIndustry) {
    ElMessage.warning('请填写具体单位或关联行业')
    return
  }
  busyAction.value = 'verify'
  try {
    await api.verifyEvent(route.params.eventId, { ...verifyForm })
    ElMessage.success('初验结果已保存')
    await loadDetail()
  } catch (error) {
    ElMessage.error(error.message || '保存初验失败')
  } finally { busyAction.value = '' }
}

async function uploadEvidence(uploadFile) {
  if (!uploadFile?.raw) return
  busyAction.value = 'upload'
  try {
    await api.uploadEvidence(route.params.eventId, uploadFile.raw)
    ElMessage.success('证据已上传')
    await loadEvidence()
  } catch (error) {
    ElMessage.error(error.message || '上传证据失败')
  } finally { busyAction.value = '' }
}

async function captureEvidence() {
  busyAction.value = 'capture'
  try {
    await api.captureEvidence(route.params.eventId)
    ElMessage.success('已保存授权浏览器 HTML 与原始截图')
    await loadEvidence()
  } catch (error) {
    ElMessage.error(error.message || '浏览器取证失败，请上传 PNG / JPEG')
  } finally { busyAction.value = '' }
}

async function selectEvidence(item) {
  selectedEvidenceId.value = item.id
  rectangles.value = []
  dragStart.value = null
  revokeImageUrls()
  try {
    originalImageUrl.value = URL.createObjectURL(await api.loadEvidenceBlob(item.id))
    await loadCanvasImage(originalImageUrl.value)
    const redacted = evidence.value.find((candidate) => candidate.evidenceType === 'redacted' && candidate.sourceEvidenceId === item.id && candidate.approved)
    if (redacted) {
      compliantImageUrl.value = URL.createObjectURL(await api.loadEvidenceBlob(redacted.id))
    }
  } catch (error) {
    canvasReady.value = false
    ElMessage.error(error.message || '读取证据失败')
  }
}

function loadCanvasImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = async () => {
      canvasImage = image
      await nextTick()
      const canvas = canvasRef.value
      canvas.width = image.naturalWidth
      canvas.height = image.naturalHeight
      canvasReady.value = true
      drawCanvas()
      resolve()
    }
    image.onerror = () => reject(new Error('无法解析截图'))
    image.src = url
  })
}

function canvasPoint(event) {
  const canvas = canvasRef.value
  const bounds = canvas.getBoundingClientRect()
  return {
    x: Math.max(0, Math.min(canvas.width, (event.clientX - bounds.left) * canvas.width / bounds.width)),
    y: Math.max(0, Math.min(canvas.height, (event.clientY - bounds.top) * canvas.height / bounds.height)),
  }
}

function startSelection(event) {
  if (!canvasReady.value || !canVerify.value) return
  dragStart.value = canvasPoint(event)
  dragCurrent.value = dragStart.value
}

function moveSelection(event) {
  if (!dragStart.value) return
  dragCurrent.value = canvasPoint(event)
  drawCanvas()
}

function finishSelection(event) {
  if (!dragStart.value) return
  if (event?.clientX != null) dragCurrent.value = canvasPoint(event)
  const rectangle = normalizeRectangle(dragStart.value, dragCurrent.value)
  if (rectangle.width >= 4 && rectangle.height >= 4) rectangles.value.push(rectangle)
  dragStart.value = null
  dragCurrent.value = null
  drawCanvas()
}

function normalizeRectangle(start, end) {
  return {
    x: Math.round(Math.min(start.x, end.x)), y: Math.round(Math.min(start.y, end.y)),
    width: Math.round(Math.abs(start.x - end.x)), height: Math.round(Math.abs(start.y - end.y)),
  }
}

function drawCanvas() {
  const canvas = canvasRef.value
  if (!canvas || !canvasImage) return
  const context = canvas.getContext('2d')
  context.clearRect(0, 0, canvas.width, canvas.height)
  context.drawImage(canvasImage, 0, 0)
  context.fillStyle = 'rgba(0, 0, 0, .82)'
  for (const rect of rectangles.value) context.fillRect(rect.x, rect.y, rect.width, rect.height)
  if (dragStart.value && dragCurrent.value) {
    const rect = normalizeRectangle(dragStart.value, dragCurrent.value)
    context.fillStyle = 'rgba(0, 0, 0, .55)'
    context.fillRect(rect.x, rect.y, rect.width, rect.height)
    context.strokeStyle = '#ff4d4f'
    context.lineWidth = Math.max(2, canvas.width / 600)
    context.strokeRect(rect.x, rect.y, rect.width, rect.height)
  }
}

function clearRectangles() {
  rectangles.value = []
  drawCanvas()
}

async function redactEvidence() {
  busyAction.value = 'redact'
  try {
    await api.redactEvidence(route.params.eventId, selectedEvidenceId.value, rectangles.value, true)
    ElMessage.success('合规副本已生成并审批')
    await loadEvidence()
    const selected = evidence.value.find((item) => item.id === selectedEvidenceId.value)
    if (selected) await selectEvidence(selected)
  } catch (error) {
    ElMessage.error(error.message || '生成合规副本失败')
  } finally { busyAction.value = '' }
}

async function publishEvent() {
  try {
    await ElMessageBox.confirm('发布后将在平台内通知中心形成不可变情报卡片，是否继续？', '确认发布', { type: 'warning' })
  } catch { return }
  busyAction.value = 'publish'
  try {
    await api.publishEvent(route.params.eventId)
    ElMessage.success('已发布到平台内通知中心')
    await loadDetail()
  } catch (error) {
    ElMessage.error(error.message || '发布失败')
  } finally { busyAction.value = '' }
}

async function generateReport() {
  busyAction.value = 'report'
  try {
    const data = await api.loadReportData(route.params.eventId)
    const { Document, HeadingLevel, Packer, Paragraph, TextRun } = await import('docx')
    const section = (title, value) => [
      new Paragraph({ text: title, heading: HeadingLevel.HEADING_1 }),
      new Paragraph({ children: [new TextRun(String(value || '暂无'))] }),
    ]
    const doc = new Document({ sections: [{ children: [
      new Paragraph({ text: '重大威胁事件专项分析报告', heading: HeadingLevel.TITLE }),
      ...section('一、事件概况', `${data.title || event.title || '-'}\n来源平台：${platformLabel(data.platform || event.platform)}\n发现时间：${formatDateTime(data.discoveredAt || event.discoveredAt)}\n威胁类型：${data.threatType || event.threatType || '-'}`),
      ...section('二、原始线索与合规证据', `${data.originalText || event.originalText || '-'}\n已审批合规截图：${(data.evidence || []).filter((item) => item.evidenceType === 'redacted' && item.approved).length} 张`),
      ...section('三、来源可信度', `初验结论：${data.verificationResult || event.verificationResult || '-'}\n证据说明：${data.evidenceNote || event.evidenceNote || '-'}`),
      ...section('四、关联目标', [data.targetUnit, data.targetIndustry].filter(Boolean).join(' / ') || '-'),
      ...section('五、攻击或售卖机制', data.originalText || event.originalText),
      ...section('六、初验过程', `领取时间：${formatDateTime(data.claimedAt)}\n初验完成时间：${formatDateTime(data.verifiedAt)}\n核验人：${data.verifiedUsername || '-'}`),
      ...section('七、影响研判', data.evidenceNote || '需结合后续核查持续研判。'),
      ...section('八、处置建议', data.disposalDirection || event.disposalDirection),
      ...section('九、事件时间线', formatTimeline(data.actions)),
      ...section('十、附件', (data.evidence || []).filter((item) => item.evidenceType === 'redacted' && item.approved).map((item) => `${item.originalFilename}（SHA-256：${item.sha256}）`).join('\n')),
    ] }] })
    const blob = await Packer.toBlob(doc)
    const sha256 = await hashBlob(blob)
    const fileName = `重大威胁事件专项分析报告-${event.id || route.params.eventId}.docx`
    await api.recordReport(route.params.eventId, fileName, sha256)
    downloadBlob(blob, fileName)
    ElMessage.success('DOCX 草稿已生成并完成哈希留痕')
  } catch (error) {
    ElMessage.error(error.message || '生成专项报告失败')
  } finally { busyAction.value = '' }
}

async function closeEvent() {
  try { await ElMessageBox.confirm('确认关闭当前事件？', '关闭事件', { type: 'warning' }) } catch { return }
  busyAction.value = 'close'
  try {
    await api.closeEvent(route.params.eventId)
    ElMessage.success('事件已关闭')
    await loadDetail()
  } catch (error) { ElMessage.error(error.message || '关闭失败') }
  finally { busyAction.value = '' }
}

async function hashBlob(blob) {
  const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function revokeImageUrls() {
  if (originalImageUrl.value) URL.revokeObjectURL(originalImageUrl.value)
  if (compliantImageUrl.value) URL.revokeObjectURL(compliantImageUrl.value)
  originalImageUrl.value = ''
  compliantImageUrl.value = ''
}

function formatTimeline(items) {
  if (!Array.isArray(items)) return items || ''
  return items.map((item) => `${formatDateTime(item.at || item.createdAt)} ${item.description || item.actionType || item.action || ''}`).join('\n')
}
function formatDateTime(value) { return formatShanghaiDateTime(value, { includeSeconds: true }) || '-' }
function listText(value) { return Array.isArray(value) ? value.join('、') || '-' : value || '-' }
function platformLabel(value) { return { x: 'X', facebook: 'Facebook', youtube: 'YouTube', telegram: 'Telegram' }[String(value || '').toLowerCase()] || value || '-' }
function severityLabel(value) { return { emergency: '紧急', critical: '紧急', major: '重大', high: '重大', normal: '一般', medium: '一般', low: '一般' }[value] || value || '一般' }
function severityTone(value) { return ['emergency', 'critical'].includes(value) ? 'danger' : ['major', 'high'].includes(value) ? 'warning' : 'info' }
function statusLabel(value) { return { pending: '待领取', unclaimed: '待领取', verifying: '初验中', inProgress: '初验中', claimed: '初验中', verified: '初验完成', published: '已发布', closed: '已关闭' }[value] || value || '-' }
function durationText(seconds) { const value = Number(seconds || 0); return `${Math.floor(value / 60)} 分 ${value % 60} 秒` }
function shortHash(value) { return value ? `${value.slice(0, 10)}…` : '-' }
function evidenceStatusLabel(item) { return evidence.value.some((candidate) => candidate.evidenceType === 'redacted' && candidate.sourceEvidenceId === item.id && candidate.approved) ? '合规图已审批' : '原图待脱敏' }
function actionLabel(value) { return { claimed: '领取事件', verified: '完成初验', evidence_uploaded: '上传证据', evidence_redacted: '生成合规图', evidence_viewed: '查看原始证据', published: '平台内发布', report_generated: '生成专项报告', closed: '关闭事件' }[value] || value || '事件更新' }
</script>

<style lang="scss" scoped>
.social-detail { display: grid; gap: 20px; }
.detail-head, .detail-card { border: 1px solid var(--ti-border-soft); border-radius: 22px; background: #fff; box-shadow: var(--ti-shadow-sm); }
.detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 24px 26px; }
.detail-head h1 { margin: 6px 0 10px; font-size: 27px; }
.eyebrow, .card-title > span { color: var(--ti-primary); font-size: 11px; font-weight: 800; letter-spacing: .12em; }
.meta-line, .head-tags, .actions-row, .release-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.meta-line { color: var(--ti-text-secondary); font-size: 13px; }
.meta-line a { color: var(--ti-primary); }
.detail-grid { display: grid; grid-template-columns: minmax(0, .9fr) minmax(420px, 1.1fr); gap: 20px; }
.detail-card { padding: 22px; }
.card-title h2 { margin: 4px 0 16px; font-size: 19px; }
.card-title-row, .release-card { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.evidence-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.card-note { margin: -6px 0 18px; color: var(--ti-text-secondary); line-height: 1.6; }
.info-grid { display: grid; grid-template-columns: 110px 1fr; gap: 10px 14px; margin: 0; }
.info-grid dt { color: var(--ti-text-muted); }
.info-grid dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.original-text { max-height: 340px; margin-top: 18px; padding: 16px; overflow: auto; border-radius: 14px; background: #f6f8fc; white-space: pre-wrap; line-height: 1.75; }
.form-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0 14px; }
.form-grid .full { grid-column: 1 / -1; }
.actions-row { justify-content: space-between; color: var(--ti-text-secondary); }
.evidence-layout { display: grid; grid-template-columns: 220px minmax(360px, 1fr) 300px; gap: 16px; min-height: 360px; }
.evidence-list { display: grid; align-content: start; gap: 9px; max-height: 520px; overflow: auto; }
.evidence-item { display: grid; gap: 5px; width: 100%; padding: 12px; border: 1px solid var(--ti-border-soft); border-radius: 13px; background: #fff; color: var(--ti-text-secondary); text-align: left; cursor: pointer; }
.evidence-item.active { border-color: var(--ti-primary); background: rgba(45,93,255,.05); }
.evidence-item strong { color: var(--ti-text-primary); overflow-wrap: anywhere; }
.evidence-item small { font-family: monospace; }
.canvas-panel, .compliant-preview { min-width: 0; padding: 12px; border: 1px solid var(--ti-border-soft); border-radius: 15px; background: #f7f9fc; }
canvas { display: none; width: 100%; max-height: 470px; object-fit: contain; cursor: crosshair; }
canvas.canvas--ready { display: block; }
.canvas-empty, .empty-state { display: grid; place-items: center; min-height: 180px; color: var(--ti-text-muted); text-align: center; }
.canvas-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; margin-top: 10px; color: var(--ti-text-secondary); font-size: 13px; }
.compliant-preview > strong { display: block; margin-bottom: 10px; }
.compliant-preview img { display: block; width: 100%; max-height: 440px; object-fit: contain; border-radius: 10px; }
.release-card { align-items: center; }
.audit-actor { margin-left: 12px; color: var(--ti-text-secondary); }
@media (max-width: 1200px) { .detail-grid { grid-template-columns: 1fr; } .evidence-layout { grid-template-columns: 190px 1fr; } .compliant-preview { grid-column: 1 / -1; } }
@media (max-width: 767px) { .detail-head, .release-card, .card-title-row { flex-direction: column; } .form-grid, .evidence-layout { grid-template-columns: 1fr; } .compliant-preview { grid-column: auto; } }
</style>
