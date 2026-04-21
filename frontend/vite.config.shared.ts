import vue from '@vitejs/plugin-vue'
import path from 'path'

export const sharedViteConfig = {
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
}
