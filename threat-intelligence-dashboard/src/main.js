import { createApp } from 'vue'
import * as XLSX from 'xlsx'
import App from './App.vue'
import router from './router'
import { AUTH_UNAUTHORIZED_EVENT, installAuthFetch } from './composables/useAuth'
import './prototype/styles.css'
import './prototype/integration.css'

window.XLSX = XLSX
installAuthFetch()

window.addEventListener(AUTH_UNAUTHORIZED_EVENT, () => {
  if (router.currentRoute.value.name === 'Login') return
  router.replace({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
})

createApp(App).use(router).mount('#app')
