import { createApp } from 'vue'
import * as XLSX from 'xlsx'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
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

const app = createApp(App)
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}
app.use(router)
app.use(ElementPlus)
app.mount('#app')
