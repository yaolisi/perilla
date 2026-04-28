import { onUnmounted } from 'vue'

import { useListenSystemConfigChanged } from '@/composables/useListenSystemConfigChanged'
import { SYSTEM_CONFIG_CHANGE_DEBOUNCE_MS } from '@/constants/platformEvents'

/**
 * 平台配置保存后防抖执行回调，避免短时多次 updateSystemConfig 触发重复请求。
 * 用于列表、设置子页、侧栏版本等（默认与 `SYSTEM_CONFIG_CHANGE_DEBOUNCE_MS` 一致）。
 */
export function useDebouncedOnSystemConfigChange(
  fn: () => void | Promise<void>,
  debounceMs = SYSTEM_CONFIG_CHANGE_DEBOUNCE_MS,
): void {
  let timer: ReturnType<typeof setTimeout> | null = null

  const schedule = () => {
    if (timer != null) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      void fn()
    }, debounceMs)
  }

  useListenSystemConfigChanged(schedule)

  onUnmounted(() => {
    if (timer != null) {
      clearTimeout(timer)
      timer = null
    }
  })
}
