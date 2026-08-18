import { createRouter, createWebHistory } from 'vue-router'
import { hasAuthSession, isAuthSessionValidated, loadCurrentUser } from '@/composables/useAuth'
import PrototypeScreen from '@/views/PrototypeScreen.vue'
import DataMigration from '@/views/DataMigration.vue'

const screen = (path, name, file, meta = {}) => ({
  path,
  name,
  component: PrototypeScreen,
  meta: { screen: file, ...meta },
})

const routes = [
  screen('/login', 'Login', 'index.html', { public: true }),
  screen('/', 'Dashboard', 'dashboard.html'),
  screen('/intelligence', 'IntelligenceSearch', 'intelligence.html'),
  screen('/ransomware', 'Ransomware', 'ransomware.html'),
  screen('/ransomware/:eventId', 'RansomwareDetail', 'ransomware-detail.html'),
  screen('/data-leak', 'DataLeak', 'data-leak.html'),
  screen('/data-leak/:eventId', 'DataLeakDetail', 'data-leak-detail.html'),
  screen('/vulnerability-alerts', 'VulnerabilityAlerts', 'vulnerabilities.html'),
  screen('/vulnerability-alerts/:eventId', 'VulnerabilityDetail', 'vulnerability-detail.html'),
  screen('/document-exposure/netdisk', 'DocumentExposureNetdisk', 'monitoring.html', { source: 'netdisk' }),
  screen('/document-exposure/document-library', 'DocumentExposureDocumentLibrary', 'monitoring.html', { source: 'library' }),
  screen('/document-exposure/code-monitoring', 'CodeMonitoringWorkbench', 'monitoring.html', { source: 'code' }),
  screen('/document-exposure/detail/netdisk_aggregator/:hitId', 'DocumentExposureNetdiskDetail', 'netdisk-detail.html', { source: 'netdisk' }),
  screen('/document-exposure/detail/document_library/:hitId', 'DocumentExposureLibraryDetail', 'library-detail.html', { source: 'library' }),
  screen('/document-exposure/code-monitoring/detail/:hitId', 'CodeMonitoringDetail', 'code-detail.html', { source: 'code' }),
  screen('/collector-control/sites', 'CollectorSites', 'collector-sites.html'),
  screen('/collector-control/sync', 'CollectorSync', 'collector-sync.html'),
  screen('/collector-control/runtime', 'CollectorRuntime', 'collector-runtime.html'),
  screen('/collector-control/failures', 'CollectorFailures', 'collector-failures.html'),
  screen('/collector-control/run/:runId', 'CollectorRunDetail', 'collector-run-detail.html'),
  screen('/settings', 'Settings', 'settings.html'),
  { path: '/settings/data-migration', name: 'DataMigration', component: DataMigration },
  screen('/event/:eventId', 'EventDetail', 'event-detail.html'),
  { path: '/threat-situation', redirect: '/' },
  { path: '/collector-control', redirect: '/collector-control/sites' },
  { path: '/document-exposure', redirect: '/document-exposure/netdisk' },
  { path: '/document-exposure/settings', redirect: '/settings?tab=objects&module=netdisk' },
  { path: '/document-exposure/netdisk/settings', redirect: '/settings?tab=objects&module=netdisk' },
  { path: '/document-exposure/document-library/settings', redirect: '/settings?tab=objects&module=library' },
  { path: '/document-exposure/code-monitoring/settings', redirect: '/settings?tab=objects&module=code' },
  { path: '/document-exposure/scans', redirect: '/collector-control/failures' },
  { path: '/document-exposure/results', redirect: '/document-exposure/netdisk' },
  { path: '/document-exposure/code-monitoring/scans', redirect: '/collector-control/failures' },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (to.meta.public) {
    if (!hasAuthSession()) return true
    if (!isAuthSessionValidated() && !(await loadCurrentUser())) return true
    return '/'
  }

  if (!hasAuthSession()) return { path: '/login', query: { redirect: to.fullPath } }
  if (!isAuthSessionValidated() && !(await loadCurrentUser())) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
