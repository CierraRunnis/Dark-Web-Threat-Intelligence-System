import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  hasAuthSession,
  hasModuleAccess,
  isAuthSessionValidated,
  isCurrentUserAdmin,
  loadCurrentUser,
} from '@/composables/useAuth'
import { ASSIGNABLE_MODULE_KEYS, MODULE_KEYS } from '@/config/permissions'
const Login = () => import('@/views/Login.vue')
const PrototypeScreen = () => import('@/views/PrototypeScreen.vue')
const CollectorControl = () => import('@/views/CollectorControl.vue')
const EventDetail = () => import('@/views/EventDetail.vue')
const AccountManagement = () => import('@/views/AccountManagement.vue')

const prototypeScreen = (path, name, screen, meta = {}) => ({
  path,
  name,
  component: PrototypeScreen,
  meta: { layout: 'prototype', screen, hidden: false, ...meta },
})

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { title: '登录', hidden: true, layout: 'blank' },
  },
  prototypeScreen('/', 'Dashboard', 'dashboard.html', {
    title: '总览', icon: 'DataLine', kicker: 'Threat Overview', subtitle: '查看全局情报态势、核心告警和重点监测变化。',
  }),
  prototypeScreen('/intelligence', 'IntelligenceSearch', 'intelligence.html', {
    title: '情报检索',
  }),
  prototypeScreen('/ai-aggregation', 'AiAggregation', 'ai-aggregation.html', {
    title: 'AI聚合',
  }),
  prototypeScreen('/ai-aggregation/templates', 'AiAggregationTemplates', 'ai-aggregation-templates.html', {
    title: 'AI聚合模板任务',
    hidden: true,
  }),
  prototypeScreen('/ransomware', 'Ransomware', 'ransomware.html', {
    title: '勒索情报',
  }),
  prototypeScreen('/ransomware/:eventId', 'RansomwareDetail', 'ransomware-detail.html', {
    title: '勒索情报详情', hidden: true,
  }),
  prototypeScreen('/data-leak', 'DataLeak', 'data-leak.html', {
    title: '数据泄露情报',
  }),
  prototypeScreen('/data-leak/:eventId', 'DataLeakDetail', 'data-leak-detail.html', {
    title: '数据泄露详情', hidden: true,
  }),
  prototypeScreen('/vulnerability-alerts', 'VulnerabilityAlerts', 'vulnerabilities.html', {
    title: '漏洞预警',
  }),
  prototypeScreen('/vulnerability-alerts/:eventId', 'VulnerabilityDetail', 'vulnerability-detail.html', {
    title: '漏洞详情', hidden: true,
  }),
  {
    path: '/threat-situation',
    redirect: '/',
    meta: { hidden: true },
  },
  {
    path: '/collector-control',
    name: 'CollectorControl',
    component: CollectorControl,
    meta: { title: '采集控制', icon: 'VideoPlay', kicker: 'Collection Control', subtitle: '统一触发采集任务、查看同步状态和手工联调入口。', layout: 'prototype-vue' },
  },
  {
    path: '/document-exposure',
    redirect: '/document-exposure/netdisk',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/search-engine',
    redirect: '/document-exposure/netdisk',
    meta: { hidden: true },
  },
  prototypeScreen('/document-exposure/netdisk', 'DocumentExposureNetdisk', 'monitoring.html', {
    title: '网盘监测',
    source: 'netdisk',
    monitorGroup: 'document-exposure',
  }),
  prototypeScreen('/document-exposure/document-library', 'DocumentExposureDocumentLibrary', 'monitoring.html', {
    title: '文库监测',
    source: 'library',
    monitorGroup: 'document-exposure',
  }),
  prototypeScreen('/document-exposure/code-monitoring', 'DocumentExposureCodeMonitoring', 'monitoring.html', {
    title: '代码监测',
    source: 'code',
    monitorGroup: 'document-exposure',
  }),
  prototypeScreen(
    '/document-exposure/detail/netdisk_aggregator/:hitId',
    'DocumentExposureNetdiskDetail',
    'netdisk-detail.html',
    { title: '网盘监测详情', source: 'netdisk', hidden: true },
  ),
  prototypeScreen(
    '/document-exposure/detail/document_library/:hitId',
    'DocumentExposureLibraryDetail',
    'library-detail.html',
    { title: '文库监测详情', source: 'library', hidden: true },
  ),
  prototypeScreen(
    '/document-exposure/code-monitoring/detail/:hitId',
    'CodeMonitoringDetail',
    'code-detail.html',
    { title: '代码监测详情', source: 'code', hidden: true },
  ),
  {
    path: '/document-exposure/detail/:sourceFamily/:hitId',
    name: 'DocumentExposureLegacyDetail',
    redirect: (to) => ({
      name: to.params.sourceFamily === 'document_library'
        ? 'DocumentExposureLibraryDetail'
        : 'DocumentExposureNetdiskDetail',
      params: { hitId: to.params.hitId },
    }),
    meta: { hidden: true },
  },
  prototypeScreen('/settings', 'ExposureSettings', 'settings.html', {
    title: '监测配置',
    source: 'settings',
    hidden: true,
  }),
  {
    path: '/document-exposure/settings',
    redirect: '/settings?tab=objects&module=netdisk',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/search-engine/settings',
    redirect: '/settings?tab=objects&module=netdisk',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/netdisk/settings',
    redirect: '/settings?tab=objects&module=netdisk',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/document-library/settings',
    redirect: '/settings?tab=objects&module=library',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/code-monitoring/settings',
    redirect: '/settings?tab=objects&module=code',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/scans',
    redirect: '/collector-control/failures',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/code-monitoring/scans',
    redirect: '/collector-control/failures',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/results',
    redirect: '/document-exposure/netdisk',
    meta: { hidden: true },
  },
  {
    path: '/collector-control/failures',
    redirect: '/collector-control',
    meta: { hidden: true },
  },
  {
    path: '/account-management',
    name: 'AccountManagement',
    component: AccountManagement,
    meta: { title: '账号管理', icon: 'User', adminOnly: true, kicker: 'System Accounts', subtitle: '创建账号并管理模块可见范围。', layout: 'prototype-vue' },
  },
  {
    path: '/event/:eventId',
    name: 'EventDetail',
    component: EventDetail,
    meta: { title: '事件详情', icon: 'Document', hidden: true, kicker: 'Threat Detail', subtitle: '查看统一事件详情、证据、时间线和关联记录。' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

const PATH_MODULES = [
  ['/intelligence', MODULE_KEYS.INTELLIGENCE_SEARCH],
  ['/ai-aggregation', MODULE_KEYS.AI_AGGREGATION],
  ['/ransomware', MODULE_KEYS.RANSOMWARE],
  ['/data-leak', MODULE_KEYS.DATA_LEAK],
  ['/vulnerability-alerts', MODULE_KEYS.VULNERABILITY_ALERTS],
  ['/collector-control', MODULE_KEYS.COLLECTOR_CONTROL],
  ['/document-exposure', MODULE_KEYS.FILE_MONITORING],
  ['/settings', MODULE_KEYS.FILE_MONITORING],
]

function eventDetailModule(to) {
  const rawModule = Array.isArray(to.query.module) ? to.query.module[0] : to.query.module
  const requestedModule = String(rawModule || '')
  if (ASSIGNABLE_MODULE_KEYS.includes(requestedModule)) return requestedModule

  const eventId = String(to.params.eventId || '')
  if (eventId.startsWith('vuln:')) return MODULE_KEYS.VULNERABILITY_ALERTS
  if (eventId.startsWith('document:')) return MODULE_KEYS.FILE_MONITORING
  return ''
}

function requiredModuleForRoute(to) {
  if (to.name === 'EventDetail') return eventDetailModule(to)
  const match = PATH_MODULES.find(([path]) => to.path === path || to.path.startsWith(`${path}/`))
  return match?.[1] || ''
}

function permissionDeniedRedirect(message) {
  ElMessage.warning(message)
  return { name: 'Dashboard' }
}

router.beforeEach(async (to) => {
  if (to.name === 'Login') {
    if (hasAuthSession()) {
      if (!isAuthSessionValidated()) {
        const user = await loadCurrentUser()
        if (!user) return true
      }
      const redirect = typeof to.query.redirect === 'string' && to.query.redirect.startsWith('/') ? to.query.redirect : '/'
      return redirect === '/login' ? '/' : redirect
    }
    return true
  }

  if (!hasAuthSession()) {
    return {
      path: '/login',
      query: { redirect: to.fullPath },
    }
  }

  if (!isAuthSessionValidated()) {
    const user = await loadCurrentUser()
    if (!user) {
      return {
        path: '/login',
        query: { redirect: to.fullPath },
      }
    }
  }

  if (to.meta.adminOnly && !isCurrentUserAdmin()) {
    return permissionDeniedRedirect('仅管理员可以访问账号管理')
  }

  const requiredModule = requiredModuleForRoute(to)
  if (to.name === 'EventDetail' && !requiredModule && !isCurrentUserAdmin()) {
    return permissionDeniedRedirect('无法确认事件所属模块，暂无权限查看详情')
  }
  if (requiredModule && !hasModuleAccess(requiredModule)) {
    return permissionDeniedRedirect('当前账号没有该模块的访问权限')
  }

  return true
})

export default router
