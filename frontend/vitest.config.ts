import { defineConfig, mergeConfig } from 'vitest/config'
import { sharedViteConfig } from './vite.config.shared'

/** Node 25+ 默认开启实验性 Web Storage，与 jsdom 的 localStorage 叠用会触发警告/异常；对 Vitest worker 关闭之。CI（.nvmrc Node 22）不传。 */
function vitestWorkerExecArgv(): string[] {
  const major = Number(process.versions.node.split('.')[0])
  return Number.isFinite(major) && major >= 25 ? ['--no-experimental-webstorage'] : []
}

export default mergeConfig(
  sharedViteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./tests/setup.ts'],
      execArgv: vitestWorkerExecArgv(),
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html'],
        include: [
          'src/components/workflow/**/*.{ts,vue}',
          'src/components/logs/**/*.{ts,vue}',
          'src/composables/useLogs.ts',
        ],
      },
    },
  })
)
