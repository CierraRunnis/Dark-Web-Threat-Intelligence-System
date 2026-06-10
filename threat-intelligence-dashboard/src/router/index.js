import { createRouter, createWebHistory } from 'vue-router'
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

const routes = [
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
    redirect: '/document-exposure/search-engine',
    meta: { hidden: true },
  },
  {
    path: '/document-exposure/search-engine',
    name: 'DocumentExposureSearchEngine',
    component: DocumentExposureWorkbench,
    meta: {
      title: '搜索引擎监测',
      icon: 'Search',
      sourceFamily: 'search_engine',
      monitorGroup: 'document-exposure',
      kicker: '文件监测',
      subtitle: '按搜索引擎来源查看敏感文档命中趋势、分布和处置入口。',
    },
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
      subtitle: '聚焦网盘分享链接、访问状态、文件清单和风险处置。',
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
      subtitle: '查看命中详情、证据预览、文件清单和处理记录。',
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
    name: 'DocumentExposureSettings',
    component: DocumentExposureSettings,
    meta: {
      title: '文件监测配置',
      hidden: true,
      kicker: '文件监测',
      subtitle: '管理文档平台会话、监测对象、来源家族和文件类型。',
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

export default router
