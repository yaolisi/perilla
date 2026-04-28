import { ref, type Ref } from 'vue'

import { useDebouncedOnSystemConfigChange } from '@/composables/useDebouncedOnSystemConfigChange'
import { SYSTEM_CONFIG_CHANGE_DEBOUNCE_MS } from '@/constants/platformEvents'
import { getSystemConfig, type SystemConfig } from '@/services/api'

export type UseSystemConfigWithDebounceOptions = {
  /**
   * 默认 true。设为 false 时不监听平台配置变更事件（由页面自行防抖刷新更大范围，例如模型列表 + config 一并重拉）。
   */
  subscribeToPlatformConfig?: boolean
  /** 控制台错误前缀，便于区分来源 */
  logPrefix?: string
}

/**
 * 页脚/只读展示用：缓存一份 GET /api/system/config，并在平台设置保存后防抖刷新。
 * 调用方式：`useSystemConfigWithDebounce({ logPrefix })` 或 `useSystemConfigWithDebounce(600, { ... })` 自定义毫秒数。
 */
export function useSystemConfigWithDebounce(
  options?: UseSystemConfigWithDebounceOptions,
): {
  systemConfig: Ref<SystemConfig | null>
  refreshSystemConfig: () => Promise<void>
}
export function useSystemConfigWithDebounce(
  debounceMs: number,
  options?: UseSystemConfigWithDebounceOptions,
): {
  systemConfig: Ref<SystemConfig | null>
  refreshSystemConfig: () => Promise<void>
}
export function useSystemConfigWithDebounce(
  debounceMsOrOptions?: number | UseSystemConfigWithDebounceOptions,
  maybeOptions?: UseSystemConfigWithDebounceOptions,
): {
  systemConfig: Ref<SystemConfig | null>
  refreshSystemConfig: () => Promise<void>
} {
  let debounceMs = SYSTEM_CONFIG_CHANGE_DEBOUNCE_MS
  let options: UseSystemConfigWithDebounceOptions | undefined
  if (typeof debounceMsOrOptions === 'number') {
    debounceMs = debounceMsOrOptions
    options = maybeOptions
  } else {
    options = debounceMsOrOptions
  }

  const systemConfig = ref<SystemConfig | null>(null)
  const prefix = options?.logPrefix ? `[${options.logPrefix}] ` : ''

  async function refreshSystemConfig() {
    try {
      systemConfig.value = await getSystemConfig()
    } catch (e) {
      console.error(`${prefix}Failed to load system config:`, e)
    }
  }

  if (options?.subscribeToPlatformConfig !== false) {
    useDebouncedOnSystemConfigChange(() => void refreshSystemConfig(), debounceMs)
  }

  return { systemConfig, refreshSystemConfig }
}
