import { defineConfig, mergeConfig } from 'vite'
import { sharedViteConfig } from './vite.config.shared'

export default mergeConfig(
  defineConfig({
    server: {
      host: '127.0.0.1',
      port: 5173,
    },
    build: {
      sourcemap: true,
      minify: false,
    },
  }),
  sharedViteConfig
)
