import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import { AUTH_UNAUTHORIZED_EVENT, installAuthFetch } from './composables/useAuth'

installAuthFetch()

window.addEventListener(AUTH_UNAUTHORIZED_EVENT, () => {
  const route = router.currentRoute.value
  if (route.name === 'Login') return
  router.replace({ path: '/login', query: { redirect: route.fullPath } })
})

const app = createApp(App)

// Register all Element Plus icons
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

app.mount('#app')
