/** `window` 上触发；持久化系统配置可能已变更，其他设置页可据此 `loadConfig()`。 */
export const OPEN_VITAMIN_SYSTEM_CONFIG_CHANGED = 'openvitamin:system-config-changed' as const

/** 与 `useDebouncedOnSystemConfigChange`、`useSystemConfigWithDebounce` 默认一致。 */
export const SYSTEM_CONFIG_CHANGE_DEBOUNCE_MS = 400

export function notifySystemConfigChanged(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(OPEN_VITAMIN_SYSTEM_CONFIG_CHANGED))
}
