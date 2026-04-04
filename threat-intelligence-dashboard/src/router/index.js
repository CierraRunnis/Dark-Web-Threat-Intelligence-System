import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '@/views/Dashboard.vue'
import Ransomware from '@/views/Ransomware.vue'
import DataLeak from '@/views/DataLeak.vue'
import VulnerabilityAlerts from '@/views/VulnerabilityAlerts.vue'
import ThreatSituation from '@/views/ThreatSituation.vue'
import CollectorControl from '@/views/CollectorControl.vue'
import EventDetail from '@/views/EventDetail.vue'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard,
    meta: { title: '总览', icon: 'DataLine' }
  },
  {
    path: '/ransomware',
    name: 'Ransomware',
    component: Ransomware,
    meta: { title: '勒索情报', icon: 'Lock' }
  },
  {
    path: '/data-leak',
    name: 'DataLeak',
    component: DataLeak,
    meta: { title: '数据泄露情报', icon: 'Document' }
  },
  {
    path: '/vulnerability-alerts',
    name: 'VulnerabilityAlerts',
    component: VulnerabilityAlerts,
    meta: { title: '漏洞预警', icon: 'WarningFilled' }
  },
  {
    path: '/threat-situation',
    name: 'ThreatSituation',
    component: ThreatSituation,
    meta: { title: '威胁态势', icon: 'TrendCharts' }
  },
  {
    path: '/collector-control',
    name: 'CollectorControl',
    component: CollectorControl,
    meta: { title: '采集控制', icon: 'VideoPlay' }
  },
  {
    path: '/event/:eventId',
    name: 'EventDetail',
    component: EventDetail,
    meta: { title: '事件详情', icon: 'Document', hidden: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
