import { defineConfig, mergeConfig } from 'vitest/config'
import { sharedViteConfig } from './vite.config.shared'

export default mergeConfig(
  sharedViteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./tests/setup.ts'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html'],
        include: ['src/components/workflow/**/*.{ts,vue}'],
      },
    },
  })
)
