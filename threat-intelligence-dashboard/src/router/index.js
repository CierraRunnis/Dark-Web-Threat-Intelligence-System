import { createRouter, createWebHistory } from 'vue-router'
import { getCurrentUser, hasAuthSession, isAuthSessionValidated, loadCurrentUser } from '@/composables/useAuth'
import Login from '@/views/Login.vue'
import Dashboard from '@/views/Dashboard.vue'
import Ransomware from '@/views/Ransomware.vue'
import DataLeak from '@/views/DataLeak.vue'
import VulnerabilityAlerts from '@/views/VulnerabilityAlerts.vue'
import ThreatSituation from '@/views/ThreatSituation.vue'
import CollectorControl from '@/views/CollectorControl.vue'
import EventDetail from '@/views/EventDetail.vue'
import DocumentExposureSettings from '@/views/DocumentExposureSettings.vue'
import DocumentExposureScans from '@/views/DocumentExposureScans.vue'
import DocumentExposureResults from '@/views/DocumentExposureResults.vue'
import DocumentExposureWorkbench from '@/views/DocumentExposureWorkbench.vue'
import DocumentExposureDetail from '@/views/DocumentExposureDetail.vue'
import CodeMonitoringWorkbench from '@/views/CodeMonitoringWorkbench.vue'
import CodeMonitoringSettings from '@/views/CodeMonitoringSettings.vue'
import CodeMonitoringScans from '@/views/CodeMonitoringScans.vue'
import CodeMonitoringDetail from '@/views/CodeMonitoringDetail.vue'
import RemotePlatformLogin from '@/views/RemotePlatformLogin.vue'
import SocialMonitoringWorkbench from '@/views/SocialMonitoringWorkbench.vue'
import SocialMonitoringDetail from '@/views/SocialMonitoringDetail.vue'
import SocialMonitoringSettings from '@/views/SocialMonitoringSettings.vue'
import UserManagement from '@/views/UserManagement.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: {
      title: '登录',
      hidden: true,
      layout: 'blank',
    },
  },
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard,
    meta: {
      title: '总览',
      icon: 'DataLine',
      kicker: 'Threat Overview',
      subtitle: '查看全局情报态势、核心告警和重点监测变化。',
    },
  },
  {
    path: '/ransomware',
    name: 'Ransomware',
    component: Ransomware,
    meta: {
      title: '勒索情报',
      icon: 'Lock',
      kicker: 'Ransomware',
      subtitle: '跟踪勒索组织动态、受害者样本和近期高风险事件。',
    },
  },
  {
    path: '/data-leak',
    name: 'DataLeak',
    component: DataLeak,
    meta: {
      title: '数据泄露情报',
      icon: 'Document',
      kicker: 'Data Leak',
      subtitle: '聚焦公开泄露事件、敏感字段和受影响行业分布。',
    },
  },
  {
    path: '/vulnerability-alerts',
    name: 'VulnerabilityAlerts',
    component: VulnerabilityAlerts,
    meta: {
      title: '漏洞预警',
      icon: 'WarningFilled',
      kicker: 'Vulnerability Alerts',
      subtitle: '查看近期漏洞预警、厂商分布和产品热度趋势。',
    },
  },
  {
    path: '/threat-situation',
    name: 'ThreatSituation',
    component: ThreatSituation,
    meta: {
      title: '威胁态势',
      icon: 'TrendCharts',
      kicker: 'Threat Situation',
      subtitle: '汇总多模块监测结果，形成面向运营的态势视图。',
    },
  },
  {
    path: '/collector-control',
    name: 'CollectorControl',
    component: CollectorControl,
    meta: {
      title: '采集控制',
      icon: 'VideoPlay',
      kicker: 'Collection Control',
      subtitle: '统一触发采集任务、查看同步状态和手工联调入口。',
    },
  },
  {
    path: '/document-exposure',
    redirect: '/document-exposure/netdisk',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/netdisk',
    name: 'DocumentExposureNetdisk',
    component: DocumentExposureWorkbench,
    meta: {
      title: '网盘监测',
      icon: 'Share',
      sourceFamily: 'netdisk_aggregator',
      monitorGroup: 'document-exposure',
      kicker: '文件监测',
      subtitle: '聚焦网盘分享链接、访问状态、文件清单和处置状态。',
    },
  },
  {
    path: '/document-exposure/document-library',
    name: 'DocumentExposureDocumentLibrary',
    component: DocumentExposureWorkbench,
    meta: {
      title: '文库监测',
      icon: 'Files',
      sourceFamily: 'document_library',
      monitorGroup: 'document-exposure',
      kicker: '文件监测',
      subtitle: '按文库平台查看文档命中、截图预览和敏感关键词分布。',
    },
  },
  {
    path: '/document-exposure/code-monitoring',
    name: 'CodeMonitoringWorkbench',
    component: CodeMonitoringWorkbench,
    meta: {
      title: '代码监测',
      icon: 'Connection',
      monitorGroup: 'document-exposure',
      kicker: '文件监测',
      subtitle: '对公开代码平台执行检索、匹配、快照和处置闭环。',
    },
  },
  {
    path: '/document-exposure/detail/:sourceFamily/:hitId',
    name: 'DocumentExposureDetail',
    component: DocumentExposureDetail,
    meta: {
      title: '文件监测详情',
      hidden: true,
      kicker: '文件监测',
      subtitle: '查看命中详情、链接信息、文件清单和处理记录。',
    },
  },
  {
    path: '/document-exposure/code-monitoring/detail/:hitId',
    name: 'CodeMonitoringDetail',
    component: CodeMonitoringDetail,
    meta: {
      title: '代码监测详情',
      hidden: true,
      kicker: '文件监测',
      subtitle: '查看代码片段、敏感命中、风险分析和处置记录。',
    },
  },
  {
    path: '/document-exposure/settings',
    redirect: '/document-exposure/netdisk/settings',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/netdisk/settings',
    name: 'DocumentExposureNetdiskSettings',
    component: DocumentExposureSettings,
    meta: {
      title: '网盘监测配置',
      hidden: true,
      sourceFamily: 'netdisk_aggregator',
      kicker: '文件监测',
      subtitle: '独立管理网盘监测对象、关键词、文件类型和网盘信息源。',
    },
  },
  {
    path: '/document-exposure/document-library/settings',
    name: 'DocumentExposureLibrarySettings',
    component: DocumentExposureSettings,
    meta: {
      title: '文库监测配置',
      hidden: true,
      sourceFamily: 'document_library',
      kicker: '文件监测',
      subtitle: '独立管理文库监测对象、关键词和文库信息源。',
    },
  },
  {
    path: '/document-exposure/scans',
    name: 'DocumentExposureScans',
    component: DocumentExposureScans,
    meta: {
      title: '文件监测扫描历史',
      hidden: true,
      kicker: '文件监测',
      subtitle: '查看文档类扫描执行记录、候选数、命中数和错误信息。',
    },
  },
  {
    path: '/document-exposure/results',
    name: 'DocumentExposureResults',
    component: DocumentExposureResults,
    meta: {
      title: '文件监测命中结果',
      hidden: true,
      kicker: '文件监测',
      subtitle: '保留原始结果页作为辅助入口，支持全量检索与人工复核。',
    },
  },
  {
    path: '/document-exposure/code-monitoring/settings',
    name: 'CodeMonitoringSettings',
    component: CodeMonitoringSettings,
    meta: {
      title: '代码监测配置',
      hidden: true,
      kicker: '文件监测',
      subtitle: '管理代码平台会话、监测对象、敏感规则和扩展名策略。',
    },
  },
  {
    path: '/document-exposure/code-monitoring/scans',
    name: 'CodeMonitoringScans',
    component: CodeMonitoringScans,
    meta: {
      title: '代码监测扫描历史',
      hidden: true,
      kicker: '文件监测',
      subtitle: '查看代码扫描记录、平台分布、命中数和错误信息。',
    },
  },
  {
    path: '/social-monitoring',
    name: 'SocialMonitoringWorkbench',
    component: SocialMonitoringWorkbench,
    meta: {
      title: '社交平台监测',
      icon: 'ChatDotRound',
      kicker: 'Social Threat Monitoring',
      subtitle: '每 30 分钟更新境外主流社交平台威胁线索，形成初验、合规证据与平台内发布闭环。',
    },
  },
  {
    path: '/social-monitoring/events/:eventId',
    name: 'SocialMonitoringDetail',
    component: SocialMonitoringDetail,
    meta: {
      title: '社交平台威胁详情',
      hidden: true,
      kicker: 'Social Threat Detail',
      subtitle: '完成威胁初验、截图合规处理、平台内发布和重大事件专项报告。',
    },
  },
  {
    path: '/social-monitoring/settings',
    name: 'SocialMonitoringSettings',
    component: SocialMonitoringSettings,
    meta: {
      title: '社交平台监测配置',
      hidden: true,
      kicker: 'Social Monitoring Settings',
      subtitle: '配置重要时间节点、监测平台、关键词、目标别名和重点来源。',
    },
  },
  {
    path: '/social-monitoring/users',
    name: 'UserManagement',
    component: UserManagement,
    meta: {
      title: '用户管理',
      hidden: true,
      requiresAdmin: true,
      kicker: 'Access Control',
      subtitle: '管理社交平台监测管理员与分析员账号。',
    },
  },
  {
    path: '/platform-sessions/remote-login',
    name: 'RemotePlatformLogin',
    component: RemotePlatformLogin,
    meta: {
      title: '平台远程验证',
      hidden: true,
      kicker: 'Remote Browser',
      subtitle: '通过服务端浏览器完成平台登录或安全验证。',
    },
  },
  {
    path: '/event/:eventId',
    name: 'EventDetail',
    component: EventDetail,
    meta: {
      title: '事件详情',
      hidden: true,
      kicker: 'Threat Detail',
      subtitle: '查看统一事件详情、证据、时间线和关联记录。',
    },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

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

  if (to.meta.requiresAdmin && String(getCurrentUser()?.role || '').toLowerCase() !== 'admin') {
    return '/social-monitoring'
  }

  return true
})

export default router
