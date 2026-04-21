import { defineConfig, mergeConfig } from 'vite'
import { sharedViteConfig } from './vite.config.shared'

export default mergeConfig(
  defineConfig({
    build: {
      sourcemap: false,
      minify: 'esbuild',
      cssMinify: true,
      reportCompressedSize: true,
    },
  }),
  sharedViteConfig
)
