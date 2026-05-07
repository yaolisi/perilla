import { defineConfig, mergeConfig } from 'vite'
import { sharedViteConfig } from './vite.config.shared'

/** 开发代理长连接（SSE）；毫秒。勿用 0：部分 http-proxy 版本对 0 处理不一致 */
const DEV_PROXY_LONG_MS = 86_400_000 // 24h

export default mergeConfig(
  defineConfig({
    server: {
      // true → 监听 0.0.0.0，避免仅绑定 127.0.0.1 时用户用「localhost」走到 IPv6(::1) 而连不上 Vite（表现为 Chat Failed to fetch / httpStatus 0）
      host: true,
      port: 5173,
      strictPort: true,
      // 开发环境若未设置 VITE_API_URL，前端走同源相对路径，由此转发到本机网关（避免 localhost→IPv6 而后端仅 IPv4 导致的 Failed to fetch）
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
          ws: true,
          timeout: DEV_PROXY_LONG_MS,
          proxyTimeout: DEV_PROXY_LONG_MS,
        },
        '/v1': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
          ws: true,
          timeout: DEV_PROXY_LONG_MS,
          proxyTimeout: DEV_PROXY_LONG_MS,
        },
      },
    },
    build: {
      sourcemap: true,
      minify: false,
    },
  }),
  sharedViteConfig
)
