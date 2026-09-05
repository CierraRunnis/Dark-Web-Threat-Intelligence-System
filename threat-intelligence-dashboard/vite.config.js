import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

import {
  createBasicAuthCookieMiddleware,
  resolveBasicAuthCookieConfig,
} from './build/basicAuthCookieGate.js'
import {
  createLoopbackOnlyApiProxyBlocker,
} from './build/loopbackOnlyApiGate.js'


// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const dashboardEnv = loadEnv(mode, __dirname, '')
  const collectorEnv = loadEnv(mode, resolve(__dirname, '../darkweb_collector'), '')
  const basicAuth = resolveBasicAuthCookieConfig(process.env, collectorEnv, dashboardEnv)
  const loopbackOnlyApiPlugin = {
    name: 'block-loopback-only-api-proxy',
    configureServer(server) {
      server.middlewares.use(createLoopbackOnlyApiProxyBlocker())
    },
    configurePreviewServer(server) {
      server.middlewares.use(createLoopbackOnlyApiProxyBlocker())
    },
  }

  const basicAuthPlugin = {
    name: 'darkweb-http-basic-auth',
    configureServer(server) {
      server.middlewares.use(createBasicAuthCookieMiddleware(basicAuth))
    },
    configurePreviewServer(server) {
      server.middlewares.use(createBasicAuthCookieMiddleware(basicAuth))
    },
  }

  return {
    plugins: [loopbackOnlyApiPlugin, basicAuthPlugin, vue()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
          ws: true,
        },
        '/collector-output': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },
    css: {
      preprocessorOptions: {
        scss: {
          additionalData: `@use "@/styles/variables.scss" as *;`,
        },
      },
    },
  }
})
