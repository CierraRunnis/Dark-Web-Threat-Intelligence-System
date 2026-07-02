<template>
  <div class="collector-control-page ti-page">
    <section class="ti-panel ti-reveal-up">
      <div class="control-hero">
        <div class="control-hero__copy">
          <span class="ti-kicker">采集控制台</span>
          <h3>站点运行控制与情报同步</h3>
          <p>统一触发采集任务、维护漏洞与勒索情报同步，并集中查看站点健康和最近失败任务。</p>
        </div>
        <div class="control-hero__stats">
          <div class="metric-card">
            <span>总体状态</span>
            <strong>{{ jobsData.overall_status || '未知' }}</strong>
          </div>
          <div class="metric-card">
            <span>运行中任务</span>
            <strong>{{ jobsData.running_jobs || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>异常挂起</span>
            <strong>{{ jobsData.stale_jobs || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>24 小时失败</span>
            <strong>{{ jobsData.failed_jobs_24h || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>持续运行</span>
            <strong>{{ continuousStatus.enabled ? '运行中' : '未启动' }}</strong>
          </div>
          <div class="metric-card">
            <span>最近调度</span>
            <strong class="metric-card__value metric-card__value--small">{{ continuousStatus.last_tick_at || '暂无' }}</strong>
          </div>
          <div class="metric-card">
            <span>浏览器 Worker</span>
            <strong>{{ browserWorkerLabel }}</strong>
          </div>
          <div class="metric-card">
            <span>本地浏览器池</span>
            <strong>{{ localBrowserPoolLabel }}</strong>
          </div>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up tor-bridge-panel">
      <div class="tor-bridge-panel__header">
        <div>
          <h3>网桥</h3>
          <p>在 Tor 被封锁的地区，网桥可用于安全访问 Tor 网络。不同地区的网络环境存在差异，网桥效果可能因人而异。</p>
        </div>
        <div class="health-actions">
          <el-button plain :loading="torBridgeLoading" @click="loadTorBridgeStatus">刷新状态</el-button>
          <el-button type="primary" :loading="torBridgeStartLoading || torBridgeSaveLoading" :disabled="!torBridgeConfig.enabled || torBridgeConfig.process_running" @click="startTorBridge">连接</el-button>
          <el-button type="danger" plain :loading="torBridgeStopLoading" :disabled="!torBridgeConfig.process_running" @click="stopTorBridge">断开</el-button>
        </div>
      </div>

      <div class="tor-bridge-body">
        <div class="tor-bridge-primary">
          <div class="tor-bridge-toggle">
            <el-switch v-model="torBridgeConfig.enabled" @change="handleTorBridgeEnabledChange" />
            <span>使用网桥</span>
          </div>

          <div class="tor-bridge-current">
            <div class="tor-bridge-current__head">
              <strong>您的网桥</strong>
              <div>
                <span>内置</span>
                <el-button text class="tor-bridge-current__menu" @click="openBuiltinBridgeDialog">...</el-button>
              </div>
            </div>
            <div class="tor-bridge-current__body">
              <strong>{{ torBridgeModeLabel }}</strong>
              <p>{{ torBridgeDescription }}</p>
            </div>
          </div>

          <div class="tor-bridge-change">
            <h4>更换网桥</h4>
            <div class="tor-bridge-change__row">
              <div>
                <span>选择 Tor 浏览器内置网桥</span>
                <p>obfs4 / Snowflake / meek</p>
              </div>
              <el-button @click="openBuiltinBridgeDialog">选择内置网桥...</el-button>
            </div>
            <div class="tor-bridge-change__row">
              <div>
                <span>输入已知的网桥地址</span>
                <p>粘贴 Bridge 行后连接</p>
              </div>
              <el-button @click="openCustomBridgeDialog">更换网桥...</el-button>
            </div>
          </div>
        </div>

        <div class="tor-bridge-runtime">
          <div class="tor-bridge-runtime__item">
            <span>连接状态</span>
            <strong>{{ torBridgeStatusLabel }}</strong>
          </div>
          <div class="tor-bridge-runtime__item">
            <span>采集代理</span>
            <strong>{{ torBridgeConfig.collector_proxy || `socks5h://${torBridgeConfig.socks_host}:${torBridgeConfig.socks_port}` }}</strong>
          </div>
          <div class="tor-bridge-runtime__item">
            <span>检测方式</span>
            <strong>自动检测</strong>
          </div>
        </div>
      </div>
      <p v-if="torBridgeConfig.last_error" class="panel-note panel-note--danger">最近错误：{{ torBridgeConfig.last_error }}</p>
    </section>

    <el-dialog v-model="builtinBridgeDialogVisible" title="选择内置网桥" width="720px" class="builtin-bridge-dialog">
      <p class="builtin-bridge-dialog__intro">Tor 浏览器包括一些称为“可插拔传输”的特殊网桥，可隐藏您使用 Tor 这一事实。</p>
      <el-radio-group v-model="builtinBridgeSelection" class="builtin-bridge-list">
        <el-radio v-for="option in builtinBridgeOptions" :key="option.value" :label="option.value" class="builtin-bridge-option">
          <div>
            <div class="builtin-bridge-option__title">
              <strong>{{ option.label }}</strong>
              <span v-if="option.value === torBridgeConfig.bridge_mode">当前网桥</span>
            </div>
            <p>{{ option.description }}</p>
          </div>
        </el-radio>
      </el-radio-group>
      <template #footer>
        <el-button type="primary" :loading="torBridgeStartLoading || torBridgeSaveLoading" @click="confirmBuiltinBridgeSelection">连接</el-button>
        <el-button @click="builtinBridgeDialogVisible = false">取消</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="customBridgeDialogVisible" title="输入已知的网桥地址" width="720px">
      <el-input v-model="customBridgeLinesDraft" type="textarea" :rows="6" placeholder="Bridge obfs4 ... / Bridge snowflake ..." />
      <template #footer>
        <el-button type="primary" :loading="torBridgeStartLoading || torBridgeSaveLoading" @click="confirmCustomBridgeSelection">连接</el-button>
        <el-button @click="customBridgeDialogVisible = false">取消</el-button>
      </template>
    </el-dialog>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">公开源漏洞同步</div>
        <div class="health-actions">
          <el-select v-model="vulnerabilityIntervalHours" style="width: 150px">
            <el-option label="每 1 小时" :value="1" />
            <el-option label="每 4 小时" :value="4" />
          </el-select>
          <el-button plain :loading="vulnerabilityRunLoading" @click="runVulnerabilitySyncOnce">同步一次</el-button>
          <el-button type="success" :loading="vulnerabilityContinuousLoading" :disabled="vulnerabilitySync.enabled" @click="startVulnerabilitySync">开始自动同步</el-button>
          <el-button type="danger" plain :loading="vulnerabilityContinuousLoading" :disabled="!vulnerabilitySync.enabled" @click="stopVulnerabilitySync">停止自动同步</el-button>
        </div>
      </div>
      <div class="ti-card-body status-grid">
        <div class="metric-card">
          <span>自动同步</span>
          <strong>{{ vulnerabilitySync.enabled ? '已开启' : '未开启' }}</strong>
        </div>
        <div class="metric-card">
          <span>同步间隔</span>
          <strong>{{ vulnerabilitySync.interval_seconds ? `${Math.round(vulnerabilitySync.interval_seconds / 3600)} 小时` : '未设置' }}</strong>
        </div>
        <div class="metric-card">
          <span>漏洞记录数</span>
          <strong>{{ vulnerabilitySync.record_count || 0 }}</strong>
        </div>
        <div class="metric-card">
          <span>最近同步</span>
          <strong class="metric-card__value metric-card__value--small">{{ vulnerabilitySync.last_success_at || '暂无' }}</strong>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">ransomware.live 同步接入</div>
        <div class="health-actions">
          <el-select v-model="ransomwareIntervalHours" style="width: 150px">
            <el-option label="每 1 小时" :value="1" />
            <el-option label="每 4 小时" :value="4" />
          </el-select>
          <el-button plain :loading="ransomwareRunLoading" @click="runRansomwareSyncOnce">同步一次</el-button>
          <el-button type="success" :loading="ransomwareContinuousLoading" :disabled="ransomwareSync.enabled" @click="startRansomwareSync">开始自动同步</el-button>
          <el-button type="danger" plain :loading="ransomwareContinuousLoading" :disabled="!ransomwareSync.enabled" @click="stopRansomwareSync">停止自动同步</el-button>
        </div>
      </div>
      <div class="ti-card-body">
        <div class="status-grid status-grid--compact">
          <div class="metric-card">
            <span>API Key</span>
            <strong>{{ ransomwareConfig.has_api_key ? '已配置' : '未配置' }}</strong>
          </div>
          <div class="metric-card">
            <span>自动同步</span>
            <strong>{{ ransomwareSync.enabled ? '已开启' : '未开启' }}</strong>
          </div>
          <div class="metric-card">
            <span>记录数</span>
            <strong>{{ ransomwareSync.record_count || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>最近同步</span>
            <strong class="metric-card__value metric-card__value--small">{{ ransomwareSync.last_success_at || '暂无' }}</strong>
          </div>
        </div>
        <div class="status-grid status-grid--compact">
          <div class="metric-card">
            <span>最新披露</span>
            <strong class="metric-card__value metric-card__value--small">{{ ransomwareSync.latest_disclosure_time || '暂无' }}</strong>
          </div>
          <div class="metric-card">
            <span>最近来源</span>
            <strong class="metric-card__value metric-card__value--small metric-card__value--break">{{ ransomwareLastSourceLabel }}</strong>
          </div>
          <div class="metric-card">
            <span>最近入库</span>
            <strong>{{ ransomwareSync.last_ingested || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>配置来源</span>
            <strong class="metric-card__value metric-card__value--small">{{ ransomwareConfig.source || 'none' }}</strong>
          </div>
        </div>
        <div class="credential-row">
          <el-input
            v-model="ransomwareApiKey"
            type="password"
            show-password
            placeholder="输入 ransomware.live API Key"
            class="credential-row__input"
          />
          <el-button type="primary" :loading="ransomwareSaveLoading || ransomwareConfigLoading" @click="saveRansomwareConfig">保存 Key</el-button>
        </div>
        <div class="panel-note-block">
          <p class="panel-note">当前 Key：{{ ransomwareConfig.masked_api_key || '未保存' }}</p>
          <p class="panel-note panel-note--mono">配置文件：{{ ransomwareConfig.settings_path || ransomwareConfig.env_var }}</p>
          <p v-if="ransomwareSync.last_error" class="panel-note panel-note--danger">最近错误：{{ ransomwareSync.last_error }}</p>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">Bot 助手推送</div>
        <div class="health-actions">
          <el-button plain :loading="botConfigLoading" @click="loadBotConfig">刷新配置</el-button>
          <el-button type="success" plain :loading="botTestLoading" :disabled="!botSmartConfigured || !botHasTargets" @click="testBotMessage">测试推送</el-button>
        </div>
      </div>
      <div class="ti-card-body">
        <div class="status-grid status-grid--compact">
          <div class="metric-card">
            <span>智能机器人</span>
            <strong>{{ botSmartConfigured ? '已配置' : '未配置' }}</strong>
          </div>
          <div class="metric-card">
            <span>Secret</span>
            <strong>{{ botSecretConfigured ? '已配置' : '未配置' }}</strong>
          </div>
          <div class="metric-card">
            <span>已登记会话</span>
            <strong class="metric-card__value metric-card__value--small">{{ botTargetLabel }}</strong>
          </div>
          <div class="metric-card">
            <span>更新时间</span>
            <strong class="metric-card__value metric-card__value--small">{{ botConfig.updated_at || '暂无' }}</strong>
          </div>
        </div>
        <div class="credential-row">
          <el-input
            v-model="botIdInput"
            type="password"
            show-password
            placeholder="Bot ID"
            class="credential-row__input"
          />
          <el-input
            v-model="botSecretInput"
            type="password"
            show-password
            placeholder="Secret"
            class="credential-row__input credential-row__input--secret"
          />
          <el-button type="primary" :loading="botSaveLoading || botConfigLoading" @click="saveBotConfig">保存配置</el-button>
        </div>
        <div class="panel-note-block">
          <p class="panel-note">当前 Bot ID：{{ botConfig.bot_id || '未保存' }}</p>
          <p class="panel-note">连接地址：{{ botConfig.websocket_url || 'wss://openws.work.weixin.qq.com' }}</p>
          <p class="panel-note">推送目标：{{ botTargetsText }}</p>
          <p class="panel-note">保存 Bot ID 和 Secret 后，把机器人拉进群聊或直接私聊机器人，系统会自动登记会话并向这些会话推送监测事件。</p>
          <p class="panel-note panel-note--mono">配置文件：{{ botConfig.settings_path || '默认运行目录' }}</p>
          <p v-if="botConfig.listener?.last_error" class="panel-note panel-note--danger">监听错误：{{ botConfig.listener.last_error }}</p>
          <p v-if="botLastError" class="panel-note panel-note--danger">最近错误：{{ botLastError }}</p>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">运行库状态</div>
        <StatusBadge :label="runtimeDbStatus.using_runtime_db ? 'WSL 运行库' : 'Windows 源库'" :tone="runtimeDbStatus.using_runtime_db ? 'success' : 'warning'" :dot="false" />
      </div>
      <div class="ti-card-body status-grid">
        <div class="metric-card">
          <span>当前数据库</span>
          <strong class="metric-card__value metric-card__value--path">{{ runtimeDbStatus.runtime_db_path || '未知' }}</strong>
        </div>
        <div class="metric-card">
          <span>源库路径</span>
          <strong class="metric-card__value metric-card__value--path">{{ runtimeDbStatus.source_db_path || '未知' }}</strong>
        </div>
        <div class="metric-card">
          <span>上次准备</span>
          <strong class="metric-card__value metric-card__value--small">{{ runtimeDbStatus.prepared_at || '未知' }}</strong>
        </div>
        <div class="metric-card">
          <span>标准化事件</span>
          <strong>{{ runtimeDbStatus.copied_counts?.normalized_intelligence_events ?? '未知' }}</strong>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">监测规则</div>
        <div class="health-actions">
          <el-button plain :loading="keywordLoading" @click="loadMonitoringKeywords">刷新规则</el-button>
          <el-button type="primary" plain @click="addMonitoringKeyword">新增词条</el-button>
          <el-button type="success" :loading="keywordLoading" @click="saveMonitoringKeywords">保存规则</el-button>
        </div>
      </div>
      <div class="ti-card-body">
        <div class="status-grid status-grid--compact">
          <div class="metric-card">
            <span>启用规则数</span>
            <strong>{{ monitoringStatus.enabledKeywordCount || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>高优先事件</span>
            <strong>{{ monitoringStatus.highPriorityCount || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>样本证据事件</span>
            <strong>{{ monitoringStatus.sampleEvidenceCount || 0 }}</strong>
          </div>
          <div class="metric-card">
            <span>规则覆盖事件</span>
            <strong>{{ monitoringStatus.eventCount || 0 }}</strong>
          </div>
        </div>
        <p class="panel-note">英文完整词建议使用词边界匹配，中文关键词建议使用包含匹配。</p>
        <div class="ti-table-shell">
          <el-table :data="monitoringKeywords" table-layout="auto" style="width: 100%">
            <el-table-column label="关键词" min-width="180">
              <template #default="{ row }">
                <el-input v-model="row.keyword" placeholder="例如 中国 / 政府 / 能源 / 企业名" />
              </template>
            </el-table-column>
            <el-table-column label="类别" width="160">
              <template #default="{ row }">
                <el-select v-model="row.category">
                  <el-option label="地理关键词" value="geo_keywords" />
                  <el-option label="组织关键词" value="org_keywords" />
                  <el-option label="自定义关键词" value="custom_keywords" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="权重" width="120">
              <template #default="{ row }">
                <el-input-number v-model="row.weight" :min="1" :max="25" />
              </template>
            </el-table-column>
            <el-table-column label="匹配方式" width="160">
              <template #default="{ row }">
                <el-select v-model="row.match_mode">
                  <el-option label="包含匹配" value="contains" />
                  <el-option label="词边界匹配" value="word_boundary" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button text type="danger" @click="removeMonitoringKeyword(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">站点健康表</div>
        <div class="health-actions">
          <el-button plain @click="refreshAllPanels">刷新状态</el-button>
          <el-button type="primary" :loading="runningAllSites" @click="runAllSitesOnce">运行全部站点</el-button>
          <el-button type="success" :loading="continuousLoading" :disabled="continuousStatus.enabled" @click="startContinuousRun">开始持续运行</el-button>
          <el-button type="danger" plain :loading="continuousLoading" :disabled="!continuousStatus.enabled" @click="stopContinuousRun">停止持续运行</el-button>
          <StatusBadge :label="jobsData.overall_status || '未知'" tone="primary" :dot="false" />
        </div>
      </div>
      <div class="ti-card-body">
        <div class="ti-table-shell">
          <el-table :data="siteHealth" style="width: 100%" table-layout="auto">
            <el-table-column prop="site_name" label="站点" min-width="140" />
            <el-table-column prop="overall_status" label="总体状态" width="110" />
            <el-table-column prop="seed_status" label="种子页状态" width="120" />
            <el-table-column prop="detail_status" label="详情页状态" width="120" />
            <el-table-column prop="running_jobs" label="运行中" width="90" />
            <el-table-column prop="failed_jobs_24h" label="24h 失败" width="100" />
            <el-table-column label="连续失败" width="100">
              <template #default="{ row }">
                {{ row.consecutive_failures || 0 }}/{{ row.failure_threshold || 3 }}
              </template>
            </el-table-column>
            <el-table-column label="熔断" width="100">
              <template #default="{ row }">
                <StatusBadge :label="circuitBreakerLabel(row)" :tone="circuitBreakerTone(row)" :dot="false" />
              </template>
            </el-table-column>
            <el-table-column prop="failure_cooldown_until" label="冷却至" min-width="150" />
            <el-table-column label="错误分类" width="130">
              <template #default="{ row }">
                <StatusBadge :label="errorCategoryLabel(row.error_category)" :tone="errorCategoryTone(row.error_category)" :dot="false" />
              </template>
            </el-table-column>
            <el-table-column prop="last_success_at" label="最近成功" min-width="170" />
            <el-table-column prop="last_error" label="最近错误" min-width="260" show-overflow-tooltip />
            <el-table-column label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" type="primary" :loading="!!runningSiteMap[row.site_name]" :disabled="isSiteRunBlocked(row) || !row.enabled" @click="runSiteOnce(row.site_name)">运行一次</el-button>
                  <el-button size="small" :type="row.enabled ? 'danger' : 'success'" plain :loading="!!togglingSiteMap[row.site_name]" @click="toggleSite(row.site_name, !row.enabled)">
                    {{ row.enabled ? '停用采集' : '启用采集' }}
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </section>

    <section class="ti-card ti-reveal-up">
      <div class="ti-card-header">
        <div class="ti-card-title">最近失败任务</div>
        <StatusBadge label="按站点追踪" tone="warning" :dot="false" />
      </div>
      <div class="ti-card-body">
        <div v-if="recentFailures.length" class="alert-stream">
          <article v-for="item in recentFailures" :key="`${item.site_name}-${item.job_type}-${item.finished_at}`" class="alert-stream__item alert-stream__item--high">
            <div class="alert-stream__meta">
              <StatusBadge :label="item.status" tone="warning" />
              <StatusBadge :label="errorCategoryLabel(item.error_category)" :tone="errorCategoryTone(item.error_category)" :dot="false" />
              <span>{{ item.finished_at }}</span>
            </div>
            <h3>{{ item.site_name }} {{ item.job_type }} {{ item.status }}</h3>
            <p>{{ item.error_message || '暂无错误详情' }}</p>
            <div class="alert-stream__source">目标：{{ item.target }}</div>
          </article>
        </div>
        <div v-else class="empty-state"><p>最近 24 小时没有失败或异常挂起任务。</p></div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useIntelligenceData } from '@/composables/useIntelligenceData'
import { useJobsData } from '@/composables/useJobsData'
import { useContinuousJobs } from '@/composables/useContinuousJobs'

const { refresh: refreshIntelligence } = useIntelligenceData()
const { data: jobsState, refresh: refreshJobs } = useJobsData()
const { data: continuousState, refresh: refreshContinuous } = useContinuousJobs()

const jobsData = computed(() => jobsState.value || {})
const continuousStatus = computed(() => continuousState.value || {})
const siteHealth = computed(() => jobsData.value.site_health || [])
const recentFailures = computed(() => jobsData.value.recent_failures || [])
const vulnerabilitySync = computed(() => jobsData.value.vulnerability_sync || {})
const ransomwareSync = computed(() => jobsData.value.ransomware_sync || {})
const runtimeDbStatus = computed(() => jobsData.value.runtime_db || {})
const browserRuntime = computed(() => jobsData.value.browser_runtime || {})
const localBrowserPool = computed(() => browserRuntime.value.local_process_pool || {})
const browserWorkerLabel = computed(() => {
  const workers = Number(browserRuntime.value.browser_worker_count || 0)
  const capacity = Number(browserRuntime.value.browser_concurrency || browserRuntime.value.configured_concurrency || 2)
  return `${workers}/${capacity}`
})
const localBrowserPoolLabel = computed(() => {
  const running = Number(localBrowserPool.value.running_or_pending || 0)
  const capacity = Number(localBrowserPool.value.max_workers || browserRuntime.value.browser_concurrency || 2)
  return `${running}/${capacity}`
})
const botSmartConfigured = computed(() => botConfig.value.provider === 'wechat_work_aibot' && botConfig.value.configured)
const botSecretConfigured = computed(() => botConfig.value.provider === 'wechat_work_aibot' && botConfig.value.has_secret)
const botHasTargets = computed(() => Number(botConfig.value.chat_target_count || 0) > 0 || Boolean(botConfig.value.chat_id))
const botTargetLabel = computed(() => {
  if (botConfig.value.provider !== 'wechat_work_aibot') return '未配置'
  const count = Number(botConfig.value.chat_target_count || 0)
  if (count > 0) return `${count} 个会话`
  return botConfig.value.chat_id ? '1 个会话' : '等待登记'
})
const botTargetsText = computed(() => {
  const targets = Array.isArray(botConfig.value.chat_ids) ? botConfig.value.chat_ids.filter(Boolean) : []
  if (targets.length) return targets.join('、')
  if (botConfig.value.chat_id) return botConfig.value.chat_id
  return '未登记；把机器人拉进目标群聊或私聊机器人后自动登记'
})
const ransomwareLastSourceLabel = computed(() => {
  const raw = String(ransomwareSync.value.last_source || '').trim()
  if (!raw) return '暂无'
  try {
    return new URL(raw).host || raw
  } catch {
    return raw
  }
})
const torBridgeModeLabel = computed(() => {
  const labels = {
    snowflake: 'Snowflake',
    obfs4: 'obfs4',
    webtunnel: 'WebTunnel',
    meek_lite: 'meek',
    vanilla: 'Vanilla',
    custom: 'Custom',
  }
  return labels[torBridgeConfig.value.bridge_mode] || torBridgeConfig.value.bridge_mode || '未设置'
})
const builtinBridgeOptions = [
  {
    value: 'obfs4',
    label: 'obfs4',
    description: '可使 Tor 流量看似随机数据，在审查严格的地区可能无效。',
  },
  {
    value: 'snowflake',
    label: 'Snowflake',
    description: '通过 Snowflake 代理路由连接，使其看似视频通话。',
  },
  {
    value: 'meek_lite',
    label: 'meek',
    description: '通过大型云服务提供商将您连接到 Tor 网络。可能在审查严格的地区有效，但通常速度很慢。',
  },
]
const torBridgeDescription = computed(() => {
  const option = builtinBridgeOptions.find((item) => item.value === torBridgeConfig.value.bridge_mode)
  if (option) return option.description
  if (torBridgeConfig.value.bridge_count) return `已配置 ${torBridgeConfig.value.bridge_count} 条网桥地址。`
  return '通过内置网桥连接，Tor 和传输插件会自动检测。'
})
const torBridgeStatusLabel = computed(() => {
  if (!torBridgeConfig.value.process_running) return '未运行'
  return torBridgeConfig.value.process_pid ? `运行中 #${torBridgeConfig.value.process_pid}` : '运行中'
})

const runningAllSites = ref(false)
const continuousLoading = ref(false)
const vulnerabilityRunLoading = ref(false)
const vulnerabilityContinuousLoading = ref(false)
const vulnerabilityIntervalHours = ref(1)
const torBridgeLoading = ref(false)
const torBridgeSaveLoading = ref(false)
const torBridgeStartLoading = ref(false)
const torBridgeStopLoading = ref(false)
const torBridgeLinesText = ref('')
const builtinBridgeDialogVisible = ref(false)
const customBridgeDialogVisible = ref(false)
const builtinBridgeSelection = ref('snowflake')
const customBridgeLinesDraft = ref('')
const torBridgeConfig = ref({
  enabled: false,
  bridge_mode: 'snowflake',
  tor_executable: '',
  transport_executable: '',
  socks_host: '127.0.0.1',
  socks_port: 9050,
  bridge_lines: [],
  extra_torrc_lines: [],
  bridge_count: 0,
  process_running: false,
  process_pid: null,
  collector_proxy: '',
  settings_path: '',
  torrc_path: '',
  data_directory: '',
  last_error: '',
})
const ransomwareRunLoading = ref(false)
const ransomwareContinuousLoading = ref(false)
const ransomwareSaveLoading = ref(false)
const ransomwareConfigLoading = ref(false)
const ransomwareIntervalHours = ref(1)
const ransomwareApiKey = ref('')
const ransomwareConfig = ref({
  has_api_key: false,
  masked_api_key: '',
  source: 'none',
  env_var: 'RANSOMWARE_LIVE_API_KEY',
  settings_path: '',
  updated_at: '',
})
const botConfigLoading = ref(false)
const botSaveLoading = ref(false)
const botTestLoading = ref(false)
const botIdInput = ref('')
const botSecretInput = ref('')
const botLastError = ref('')
const botConfig = ref({
  provider: 'wechat_work_aibot',
  configured: false,
  source: 'none',
  has_secret: false,
  dry_run: false,
  bot_id: '',
  chat_id: '',
  chat_ids: [],
  chat_target_count: 0,
  listener: {},
  websocket_url: '',
  webhook_key: '',
  masked_webhook_url: '',
  webhook_host: '',
  settings_path: '',
  updated_at: '',
})
const runningSiteMap = ref({})
const togglingSiteMap = ref({})
const keywordLoading = ref(false)
const monitoringStatus = ref({ keywordCount: 0, enabledKeywordCount: 0, highPriorityCount: 0, sampleEvidenceCount: 0, eventCount: 0 })
const monitoringKeywords = ref([])

function isSiteRunBlocked(row) {
  return row?.blockingReason === 'active_seed_job' || row?.activeSeedJobStatus === 'running' || row?.activeSeedJobStatus === 'enqueued'
}

function errorCategoryLabel(category) {
  const labels = {
    browser_runtime: '浏览器运行时',
    timeout: '超时',
    proxy: '代理/网络',
    parse: '解析',
    site_blocked: '站点阻断',
    unknown: '未知',
  }
  return labels[category] || '无'
}

function errorCategoryTone(category) {
  if (!category) return 'neutral'
  if (category === 'browser_runtime' || category === 'site_blocked') return 'danger'
  if (category === 'timeout' || category === 'proxy') return 'warning'
  if (category === 'parse') return 'primary'
  return 'neutral'
}

function circuitBreakerLabel(row) {
  if (row?.circuit_breaker_open) return '冷却中'
  if (Number(row?.consecutive_failures || 0) > 0) return '观察'
  return '正常'
}

function circuitBreakerTone(row) {
  if (row?.circuit_breaker_open) return 'danger'
  if (Number(row?.consecutive_failures || 0) > 0) return 'warning'
  return 'success'
}

function setSiteRunning(siteName, value) {
  runningSiteMap.value = { ...runningSiteMap.value, [siteName]: value }
}

function setSiteToggling(siteName, value) {
  togglingSiteMap.value = { ...togglingSiteMap.value, [siteName]: value }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    })
  } finally {
    window.clearTimeout(timeoutId)
  }
}

async function readApiError(response, fallbackMessage) {
  try {
    const payload = await response.json()
    return payload?.detail || payload?.message || fallbackMessage
  } catch {
    return fallbackMessage
  }
}

async function loadMonitoringKeywords() {
  keywordLoading.value = true
  try {
    const [keywordsResponse, statusResponse] = await Promise.all([
      fetchWithTimeout('/api/monitoring/keywords'),
      fetchWithTimeout('/api/analysis/monitoring-status'),
    ])
    monitoringKeywords.value = keywordsResponse.ok ? await keywordsResponse.json() : []
    monitoringStatus.value = statusResponse.ok ? await statusResponse.json() : monitoringStatus.value
  } finally {
    keywordLoading.value = false
  }
}

async function loadRansomwareConfig() {
  ransomwareConfigLoading.value = true
  try {
    const response = await fetch('/api/ransomware/config')
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    ransomwareConfig.value = await response.json()
  } catch (error) {
    ElMessage.error(error.message || '读取 ransomware.live 配置失败')
  } finally {
    ransomwareConfigLoading.value = false
  }
}

function textToLines(value) {
  return String(value || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

function applyTorBridgeStatus(payload) {
  torBridgeConfig.value = {
    ...torBridgeConfig.value,
    ...payload,
    socks_port: Number(payload?.socks_port || 9050),
    bridge_lines: Array.isArray(payload?.bridge_lines) ? payload.bridge_lines : [],
    extra_torrc_lines: Array.isArray(payload?.extra_torrc_lines) ? payload.extra_torrc_lines : [],
  }
  torBridgeLinesText.value = torBridgeConfig.value.bridge_lines.join('\n')
}

async function loadTorBridgeStatus() {
  torBridgeLoading.value = true
  try {
    const response = await fetch('/api/tor-bridge/status')
    if (!response.ok) throw new Error(await readApiError(response, `请求失败: ${response.status}`))
    applyTorBridgeStatus(await response.json())
  } catch (error) {
    ElMessage.error(error.message || '读取 Tor 网桥状态失败')
  } finally {
    torBridgeLoading.value = false
  }
}

async function saveTorBridgeConfig(options = {}) {
  const silent = Boolean(options?.silent)
  torBridgeSaveLoading.value = true
  try {
    const response = await fetch('/api/tor-bridge/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: Boolean(torBridgeConfig.value.enabled),
        bridge_mode: torBridgeConfig.value.bridge_mode || 'snowflake',
        socks_host: torBridgeConfig.value.socks_host || '127.0.0.1',
        socks_port: Number(torBridgeConfig.value.socks_port || 9050),
        bridge_lines: textToLines(torBridgeLinesText.value),
        extra_torrc_lines: [],
        tor_executable: '',
        transport_executable: '',
        data_directory: '',
      }),
    })
    if (!response.ok) throw new Error(await readApiError(response, `请求失败: ${response.status}`))
    applyTorBridgeStatus(await response.json())
    if (!silent) ElMessage.success('Tor 网桥配置已保存')
    return true
  } catch (error) {
    ElMessage.error(error.message || '保存 Tor 网桥配置失败')
    return false
  } finally {
    torBridgeSaveLoading.value = false
  }
}

async function startTorBridge() {
  torBridgeStartLoading.value = true
  try {
    const saved = await saveTorBridgeConfig({ silent: true })
    if (!saved) return
    const response = await fetch('/api/tor-bridge/start', { method: 'POST' })
    if (!response.ok) throw new Error(await readApiError(response, `请求失败: ${response.status}`))
    applyTorBridgeStatus(await response.json())
    ElMessage.success('Tor 网桥已启动')
  } catch (error) {
    ElMessage.error(error.message || '启动 Tor 网桥失败')
  } finally {
    torBridgeStartLoading.value = false
  }
}

async function stopTorBridge() {
  torBridgeStopLoading.value = true
  try {
    const response = await fetch('/api/tor-bridge/stop', { method: 'POST' })
    if (!response.ok) throw new Error(await readApiError(response, `请求失败: ${response.status}`))
    applyTorBridgeStatus(await response.json())
    ElMessage.success('Tor 网桥已停止')
  } catch (error) {
    ElMessage.error(error.message || '停止 Tor 网桥失败')
  } finally {
    torBridgeStopLoading.value = false
  }
}

async function handleTorBridgeEnabledChange(enabled) {
  if (!enabled && torBridgeConfig.value.process_running) {
    await stopTorBridge()
  }
  await saveTorBridgeConfig({ silent: true })
}

function openBuiltinBridgeDialog() {
  const current = builtinBridgeOptions.some((option) => option.value === torBridgeConfig.value.bridge_mode)
    ? torBridgeConfig.value.bridge_mode
    : 'snowflake'
  builtinBridgeSelection.value = current
  builtinBridgeDialogVisible.value = true
}

async function confirmBuiltinBridgeSelection() {
  torBridgeConfig.value.enabled = true
  torBridgeConfig.value.bridge_mode = builtinBridgeSelection.value || 'snowflake'
  torBridgeLinesText.value = ''
  builtinBridgeDialogVisible.value = false
  await startTorBridge()
}

function openCustomBridgeDialog() {
  customBridgeLinesDraft.value = torBridgeLinesText.value
  customBridgeDialogVisible.value = true
}

function inferBridgeModeFromLines(lines) {
  const first = String(lines?.[0] || '').replace(/^bridge\s+/i, '').trim().split(/\s+/)[0]?.toLowerCase()
  if (first === 'meek') return 'meek_lite'
  if (['snowflake', 'obfs4', 'webtunnel', 'meek_lite', 'vanilla'].includes(first)) return first
  return 'custom'
}

async function confirmCustomBridgeSelection() {
  const lines = textToLines(customBridgeLinesDraft.value)
  if (!lines.length) {
    ElMessage.error('请输入网桥地址')
    return
  }
  torBridgeConfig.value.enabled = true
  torBridgeConfig.value.bridge_mode = inferBridgeModeFromLines(lines)
  torBridgeLinesText.value = lines.join('\n')
  customBridgeDialogVisible.value = false
  await startTorBridge()
}

async function refreshAllPanels() {
  await Promise.all([
    refreshIntelligence(),
    refreshJobs(),
    refreshContinuous(),
    loadMonitoringKeywords(),
    loadRansomwareConfig(),
    loadBotConfig(),
    loadTorBridgeStatus(),
  ])
}

async function loadBotConfig() {
  botConfigLoading.value = true
  try {
    const response = await fetch('/api/bot/status')
    if (!response.ok) throw new Error(await readApiError(response, `请求失败: ${response.status}`))
    botConfig.value = await response.json()
    botLastError.value = ''
  } catch (error) {
    botLastError.value = error.message || '读取 Bot 配置失败'
    ElMessage.error(botLastError.value)
  } finally {
    botConfigLoading.value = false
  }
}

async function saveBotConfig() {
  const botIdValue = String(botIdInput.value || '').trim()
  const secretValue = String(botSecretInput.value || '').trim()
  if (!botIdValue || !secretValue) {
    ElMessage.error('请输入企业微信智能机器人的 Bot ID 和 Secret')
    return
  }

  botSaveLoading.value = true
  try {
    const response = await fetch('/api/bot/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: 'wechat_work_aibot',
        bot_id: botIdValue,
        secret: secretValue,
      }),
    })
    if (!response.ok) throw new Error(await readApiError(response, `请求失败: ${response.status}`))
    botConfig.value = await response.json()
    botIdInput.value = ''
    botSecretInput.value = ''
    botLastError.value = ''
    ElMessage.success('Bot 助手配置已保存')
  } catch (error) {
    botLastError.value = error.message || '保存 Bot 助手配置失败'
    ElMessage.error(botLastError.value)
  } finally {
    botSaveLoading.value = false
  }
}

async function testBotMessage() {
  if (!botHasTargets.value) {
    ElMessage.error('请先把机器人拉进目标群聊或私聊机器人完成会话登记')
    return
  }
  botTestLoading.value = true
  try {
    const response = await fetch('/api/bot/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'markdown',
        content: `### 暗网情报系统\n> Bot 助手测试推送：${new Date().toLocaleString()}`,
      }),
    })
    if (!response.ok) throw new Error(await readApiError(response, `请求失败: ${response.status}`))
    botLastError.value = ''
    ElMessage.success('Bot 测试推送已发送')
  } catch (error) {
    botLastError.value = error.message || 'Bot 测试推送失败'
    ElMessage.error(botLastError.value)
  } finally {
    botTestLoading.value = false
  }
}

function addMonitoringKeyword() {
  monitoringKeywords.value = [
    ...monitoringKeywords.value,
    { id: `new-${Date.now()}`, keyword: '', category: 'custom_keywords', weight: 5, enabled: true, match_mode: 'contains' },
  ]
}

function removeMonitoringKeyword(id) {
  monitoringKeywords.value = monitoringKeywords.value.filter((item) => item.id !== id)
}

async function saveMonitoringKeywords() {
  keywordLoading.value = true
  try {
    const response = await fetch('/api/monitoring/keywords', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        keywords: monitoringKeywords.value.map((item) => ({
          keyword: item.keyword,
          category: item.category,
          weight: Number(item.weight || 0),
          enabled: Boolean(item.enabled),
          match_mode: item.match_mode || 'contains',
        })),
      }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    monitoringKeywords.value = await response.json()
    await loadMonitoringKeywords()
    await refreshIntelligence()
    ElMessage.success('监测规则已保存')
  } catch (error) {
    ElMessage.error(error.message || '保存监测规则失败')
  } finally {
    keywordLoading.value = false
  }
}

async function runSiteOnce(siteName) {
  setSiteRunning(siteName, true)
  try {
    const response = await fetch('/api/jobs/run-site', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ site_name: siteName, force: true }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success(`已触发 ${siteName} 运行一次`)
  } catch (error) {
    ElMessage.error(error.message || '触发站点运行失败')
  } finally {
    setSiteRunning(siteName, false)
  }
}

async function toggleSite(siteName, enabled) {
  setSiteToggling(siteName, true)
  try {
    const response = await fetch(`/api/sites/${encodeURIComponent(siteName)}/enabled`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success(enabled ? `已启用 ${siteName}` : `已停用 ${siteName}`)
  } catch (error) {
    ElMessage.error(error.message || '更新站点状态失败')
  } finally {
    setSiteToggling(siteName, false)
  }
}

async function runAllSitesOnce() {
  runningAllSites.value = true
  try {
    const response = await fetch('/api/jobs/run-all-once', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已触发全部站点运行')
  } catch (error) {
    ElMessage.error(error.message || '触发全部站点运行失败')
  } finally {
    runningAllSites.value = false
  }
}

async function startContinuousRun() {
  continuousLoading.value = true
  try {
    const response = await fetch('/api/jobs/run-all-continuous/start', { method: 'POST' })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshContinuous()
    ElMessage.success('已开启持续运行')
  } catch (error) {
    ElMessage.error(error.message || '开启持续运行失败')
  } finally {
    continuousLoading.value = false
  }
}

async function stopContinuousRun() {
  continuousLoading.value = true
  try {
    const response = await fetch('/api/jobs/run-all-continuous/stop', { method: 'POST' })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshContinuous()
    ElMessage.success('已停止持续运行')
  } catch (error) {
    ElMessage.error(error.message || '停止持续运行失败')
  } finally {
    continuousLoading.value = false
  }
}

async function runVulnerabilitySyncOnce() {
  vulnerabilityRunLoading.value = true
  try {
    const response = await fetch('/api/vulnerabilities/sync/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 300 }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已触发漏洞同步')
  } catch (error) {
    ElMessage.error(error.message || '触发漏洞同步失败')
  } finally {
    vulnerabilityRunLoading.value = false
  }
}

async function startVulnerabilitySync() {
  vulnerabilityContinuousLoading.value = true
  try {
    const response = await fetch('/api/vulnerabilities/sync/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        interval_seconds: Number(vulnerabilityIntervalHours.value || 1) * 3600,
        limit: 300,
      }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已开启漏洞自动同步')
  } catch (error) {
    ElMessage.error(error.message || '开启漏洞自动同步失败')
  } finally {
    vulnerabilityContinuousLoading.value = false
  }
}

async function stopVulnerabilitySync() {
  vulnerabilityContinuousLoading.value = true
  try {
    const response = await fetch('/api/vulnerabilities/sync/stop', { method: 'POST' })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已停止漏洞自动同步')
  } catch (error) {
    ElMessage.error(error.message || '停止漏洞自动同步失败')
  } finally {
    vulnerabilityContinuousLoading.value = false
  }
}

async function saveRansomwareConfig() {
  const apiKey = String(ransomwareApiKey.value || '').trim()
  if (!apiKey) {
    ElMessage.error('请输入 ransomware.live API Key')
    return
  }

  ransomwareSaveLoading.value = true
  try {
    const response = await fetch('/api/ransomware/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    ransomwareConfig.value = await response.json()
    ransomwareApiKey.value = ''
    ElMessage.success('已保存 ransomware.live API Key')
  } catch (error) {
    ElMessage.error(error.message || '保存 ransomware.live API Key 失败')
  } finally {
    ransomwareSaveLoading.value = false
  }
}

async function runRansomwareSyncOnce() {
  ransomwareRunLoading.value = true
  try {
    const response = await fetch('/api/ransomware/sync/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 0 }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    await refreshIntelligence()
    ElMessage.success('已触发 ransomware.live 同步')
  } catch (error) {
    ElMessage.error(error.message || '触发 ransomware.live 同步失败')
  } finally {
    ransomwareRunLoading.value = false
  }
}

async function startRansomwareSync() {
  ransomwareContinuousLoading.value = true
  try {
    const response = await fetch('/api/ransomware/sync/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        interval_seconds: Number(ransomwareIntervalHours.value || 1) * 3600,
        limit: 0,
      }),
    })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已开启 ransomware.live 自动同步')
  } catch (error) {
    ElMessage.error(error.message || '开启 ransomware.live 自动同步失败')
  } finally {
    ransomwareContinuousLoading.value = false
  }
}

async function stopRansomwareSync() {
  ransomwareContinuousLoading.value = true
  try {
    const response = await fetch('/api/ransomware/sync/stop', { method: 'POST' })
    if (!response.ok) throw new Error(`请求失败: ${response.status}`)
    await refreshJobs()
    ElMessage.success('已停止 ransomware.live 自动同步')
  } catch (error) {
    ElMessage.error(error.message || '停止 ransomware.live 自动同步失败')
  } finally {
    ransomwareContinuousLoading.value = false
  }
}

onMounted(async () => {
  await refreshAllPanels()
})
</script>

<style scoped lang="scss">
.collector-control-page {
  min-width: 0;
  overflow-x: hidden;
}

.control-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 1fr);
  gap: 24px;
  align-items: start;
}

.control-hero__copy h3 {
  margin: 10px 0 0;
  color: var(--ti-text-primary);
  font-size: 34px;
}

.control-hero__copy p {
  margin: 12px 0 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
}

.control-hero__stats,
.status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.metric-card {
  min-width: 0;
  padding: 16px 18px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.92);
}

.metric-card span {
  display: block;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.metric-card strong {
  display: block;
  margin-top: 8px;
  color: var(--ti-text-primary);
  font-size: clamp(20px, 2vw, 28px);
  line-height: 1.25;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.metric-card__value--small {
  font-size: clamp(16px, 1.35vw, 22px);
}

.metric-card__value--path {
  font-size: clamp(14px, 1.05vw, 18px);
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
}

.metric-card__value--break {
  word-break: break-all;
}

.status-grid--compact {
  margin-bottom: 16px;
}

.credential-row {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.credential-row__input {
  flex: 1 1 360px;
  min-width: 220px;
}

.tor-bridge-panel {
  display: grid;
  gap: 0;
  min-width: 0;
  padding: 30px;
  overflow: hidden;
}

.tor-bridge-panel__header {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-start;
  min-width: 0;
  padding-bottom: 22px;
  border-bottom: 1px solid var(--ti-border-soft);
}

.tor-bridge-panel__header h3 {
  margin: 0;
  color: var(--ti-text-primary);
  font-size: 30px;
  line-height: 1.18;
}

.tor-bridge-panel__header p {
  max-width: 880px;
  margin: 10px 0 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
}

.tor-bridge-panel__header .health-actions {
  flex: 0 0 auto;
  justify-content: flex-end;
}

.tor-bridge-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(240px, 280px);
  gap: 28px;
  min-width: 0;
  padding-top: 24px;
  align-items: start;
}

.tor-bridge-primary {
  display: grid;
  gap: 24px;
  min-width: 0;
}

.tor-bridge-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--ti-text-primary);
  min-height: 32px;
}

.tor-bridge-current {
  width: 100%;
  min-width: 0;
  border-radius: 8px;
  background: #f4f6fb;
  padding: 24px 28px;
}

.tor-bridge-current__head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.28);
  color: var(--ti-text-primary);
  min-width: 0;
}

.tor-bridge-current__head > div {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tor-bridge-current__menu {
  width: 32px;
  height: 32px;
  padding: 0;
  color: var(--ti-text-primary);
  font-weight: 700;
  background: rgba(255, 255, 255, 0.84);
}

.tor-bridge-current__body {
  padding-top: 16px;
}

.tor-bridge-current__body strong {
  color: var(--ti-text-primary);
  font-size: 18px;
}

.tor-bridge-current__body p {
  margin: 12px 0 0;
  color: var(--ti-text-primary);
  line-height: 1.7;
}

.tor-bridge-change {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.tor-bridge-change h4 {
  margin: 0;
  color: var(--ti-text-primary);
  font-size: 22px;
}

.tor-bridge-change__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px;
  align-items: center;
  min-width: 0;
  padding: 14px 0;
  border-top: 1px solid var(--ti-border-soft);
}

.tor-bridge-change__row span {
  color: var(--ti-text-primary);
  font-weight: 600;
}

.tor-bridge-change__row p {
  margin: 4px 0 0;
  color: var(--ti-text-muted);
  font-size: 12px;
}

.tor-bridge-change__row .el-button {
  width: 178px;
  justify-self: end;
}

.tor-bridge-runtime {
  display: grid;
  gap: 14px;
  min-width: 0;
  padding: 18px;
  border: 1px solid var(--ti-border-soft);
  border-radius: 12px;
  background: rgba(248, 250, 253, 0.86);
}

.tor-bridge-runtime__item {
  min-width: 0;
}

.tor-bridge-runtime__item span {
  display: block;
  color: var(--ti-text-secondary);
  font-size: 12px;
}

.tor-bridge-runtime__item strong {
  display: block;
  margin-top: 4px;
  color: var(--ti-text-primary);
  font-size: 14px;
  line-height: 1.45;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.builtin-bridge-dialog__intro {
  margin: 0 0 14px;
  color: var(--ti-text-primary);
  line-height: 1.7;
}

.builtin-bridge-list {
  display: grid;
  gap: 14px;
}

.builtin-bridge-option {
  width: 100%;
  height: auto;
  margin-right: 0;
  align-items: flex-start;
  white-space: normal;
}

.builtin-bridge-option__title {
  display: flex;
  gap: 10px;
  align-items: center;
}

.builtin-bridge-option__title strong {
  color: var(--ti-text-primary);
  font-size: 17px;
}

.builtin-bridge-option__title span {
  color: #1677ff;
  font-size: 13px;
}

.builtin-bridge-option p {
  margin: 8px 0 0;
  color: var(--ti-text-primary);
  line-height: 1.7;
}

.panel-note-block {
  display: grid;
  gap: 6px;
}

.panel-note {
  margin: 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.panel-note--mono {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: 13px;
}

.panel-note--danger {
  color: #b91c1c;
}

.health-actions,
.row-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.alert-stream {
  display: grid;
  gap: 12px;
}

.alert-stream__item {
  padding: 16px 18px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.92);
}

.alert-stream__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.alert-stream__item h3 {
  margin: 10px 0 0;
  color: var(--ti-text-primary);
}

.alert-stream__item p,
.alert-stream__source {
  margin: 10px 0 0;
  color: var(--ti-text-secondary);
  line-height: 1.7;
  word-break: break-word;
  overflow-wrap: anywhere;
}

@media (max-width: 1440px) {
  .control-hero,
  .control-hero__stats,
  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1200px) {
  .tor-bridge-panel__header,
  .tor-bridge-body {
    grid-template-columns: 1fr;
  }

  .tor-bridge-panel__header {
    display: grid;
  }

  .tor-bridge-panel__header .health-actions {
    justify-content: flex-start;
  }

  .tor-bridge-runtime {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .control-hero {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 767px) {
  .control-hero__stats,
  .status-grid {
    grid-template-columns: 1fr;
  }

  .tor-bridge-panel {
    padding: 22px;
  }

  .tor-bridge-runtime,
  .tor-bridge-change__row {
    grid-template-columns: 1fr;
  }

  .tor-bridge-change__row .el-button {
    width: 100%;
    justify-self: stretch;
  }
}
</style>
