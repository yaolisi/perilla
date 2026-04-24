import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'
import {
  clearInferenceCache,
  createInferenceCacheClearChallenge,
  getInferenceCacheStats,
  type InferenceCacheStats,
} from '@/services/api'

const CACHE_AUTO_REFRESH_ENABLED_KEY = 'settings.runtime.cacheAutoRefreshEnabled'
const CACHE_AUTO_REFRESH_INTERVAL_KEY = 'settings.runtime.cacheAutoRefreshIntervalMs'

export function useCacheMonitor() {
  const cacheStats = ref<InferenceCacheStats | null>(null)
  const prevCacheStats = ref<InferenceCacheStats | null>(null)
  const cacheStatsLoading = ref(false)
  const clearCacheLoading = ref(false)
  const clearCacheMessage = ref('')
  const clearCacheError = ref('')
  const cacheClearModelAlias = ref('')
  const cacheClearUserId = ref('')
  const cacheAutoRefreshEnabled = ref(true)
  const cacheAutoRefreshIntervalMs = ref(10000)
  const cacheLastRefreshedAt = ref<Date | null>(null)
  let cacheStatsTimer: ReturnType<typeof setInterval> | null = null

  const challengeMetrics = computed(() => cacheStats.value?.challenge_metrics ?? null)
  const challengeValidateAttempts = computed(() => {
    const m = challengeMetrics.value
    if (!m) return 0
    return (m.validate_success_total ?? 0) + (m.validate_failed_total ?? 0)
  })
  const challengeSuccessRateText = computed(() => {
    const total = challengeValidateAttempts.value
    const success = challengeMetrics.value?.validate_success_total ?? 0
    if (total <= 0) return '0.0%'
    return `${((success / total) * 100).toFixed(1)}%`
  })
  const challengeActorMismatchRateText = computed(() => {
    const totalFailed = challengeMetrics.value?.validate_failed_total ?? 0
    const actorMismatch = challengeMetrics.value?.validate_failed_actor_mismatch_total ?? 0
    if (totalFailed <= 0) return '0.0%'
    return `${((actorMismatch / totalFailed) * 100).toFixed(1)}%`
  })
  const cacheLastRefreshedText = computed(() => {
    if (!cacheLastRefreshedAt.value) return '--'
    return cacheLastRefreshedAt.value.toLocaleTimeString()
  })

  const restoreCacheMonitorPrefs = () => {
    try {
      const enabledRaw = localStorage.getItem(CACHE_AUTO_REFRESH_ENABLED_KEY)
      if (enabledRaw === 'false') cacheAutoRefreshEnabled.value = false
      const intervalRaw = localStorage.getItem(CACHE_AUTO_REFRESH_INTERVAL_KEY)
      const interval = Number(intervalRaw)
      if ([10000, 30000, 60000].includes(interval)) {
        cacheAutoRefreshIntervalMs.value = interval
      }
    } catch {
      // ignore storage read errors
    }
  }

  const persistCacheMonitorPrefs = () => {
    try {
      localStorage.setItem(CACHE_AUTO_REFRESH_ENABLED_KEY, String(cacheAutoRefreshEnabled.value))
      localStorage.setItem(CACHE_AUTO_REFRESH_INTERVAL_KEY, String(cacheAutoRefreshIntervalMs.value))
    } catch {
      // ignore storage write errors
    }
  }

  const loadCacheStats = async () => {
    cacheStatsLoading.value = true
    try {
      prevCacheStats.value = cacheStats.value
      cacheStats.value = await getInferenceCacheStats()
      cacheLastRefreshedAt.value = new Date()
    } catch (e) {
      console.error('Failed to load inference cache stats:', e)
    } finally {
      cacheStatsLoading.value = false
    }
  }

  const startCacheAutoRefresh = () => {
    if (!cacheAutoRefreshEnabled.value) return
    if (cacheStatsTimer) return
    cacheStatsTimer = setInterval(() => {
      void loadCacheStats()
    }, cacheAutoRefreshIntervalMs.value)
  }

  const stopCacheAutoRefresh = () => {
    if (!cacheStatsTimer) return
    clearInterval(cacheStatsTimer)
    cacheStatsTimer = null
  }

  const toggleCacheAutoRefresh = () => {
    cacheAutoRefreshEnabled.value = !cacheAutoRefreshEnabled.value
    persistCacheMonitorPrefs()
    if (cacheAutoRefreshEnabled.value) {
      void loadCacheStats()
      startCacheAutoRefresh()
    } else {
      stopCacheAutoRefresh()
    }
  }

  const setCacheAutoRefreshInterval = (ms: number) => {
    cacheAutoRefreshIntervalMs.value = ms
    persistCacheMonitorPrefs()
    if (cacheAutoRefreshEnabled.value) {
      stopCacheAutoRefresh()
      startCacheAutoRefresh()
    }
  }

  const resetCacheMonitorPrefs = () => {
    cacheAutoRefreshEnabled.value = true
    cacheAutoRefreshIntervalMs.value = 10000
    try {
      localStorage.removeItem(CACHE_AUTO_REFRESH_ENABLED_KEY)
      localStorage.removeItem(CACHE_AUTO_REFRESH_INTERVAL_KEY)
    } catch {
      // ignore storage write errors
    }
    stopCacheAutoRefresh()
    startCacheAutoRefresh()
    void loadCacheStats()
  }

  const handleClearInferenceCache = async () => {
    clearCacheMessage.value = ''
    clearCacheError.value = ''
    const userId = cacheClearUserId.value.trim()
    const modelAlias = cacheClearModelAlias.value.trim()
    const hasScope = Boolean(userId || modelAlias)
    clearCacheLoading.value = true
    try {
      if (hasScope) {
        const scopeText = `user_id=${userId || '-'}, model_alias=${modelAlias || '-'}`
        const confirmed = window.confirm(`确认执行缓存清理？\n范围：${scopeText}`)
        if (!confirmed) return
      } else {
        const challenge = await createInferenceCacheClearChallenge()
        const confirmText = window.prompt(
          `你将执行“全量缓存清理”。请输入确认码：${challenge.challenge_code}\n有效期 ${challenge.expires_in_seconds} 秒`,
          '',
        )
        if ((confirmText || '').trim().toUpperCase() !== challenge.challenge_code.toUpperCase()) {
          clearCacheError.value = '确认码不匹配，已取消全量清理。'
          return
        }
        const resp = await clearInferenceCache({
          cache_kind: 'generate',
          force_all: true,
          challenge_id: challenge.challenge_id,
          confirm_text: (confirmText ?? '').trim(),
        })
        clearCacheMessage.value = `清理完成：memory=${resp.memory_deleted}, redis=${resp.redis_deleted}, total=${resp.total_deleted}`
        await loadCacheStats()
        return
      }
      const resp = await clearInferenceCache({
        cache_kind: 'generate',
        user_id: userId || undefined,
        model_alias: modelAlias || undefined,
      })
      clearCacheMessage.value = `清理完成：memory=${resp.memory_deleted}, redis=${resp.redis_deleted}, total=${resp.total_deleted}`
      await loadCacheStats()
    } catch (e) {
      clearCacheError.value = e instanceof Error ? e.message : String(e)
    } finally {
      clearCacheLoading.value = false
    }
  }

  onMounted(() => {
    restoreCacheMonitorPrefs()
    void loadCacheStats()
    startCacheAutoRefresh()
  })

  onActivated(() => {
    void loadCacheStats()
    startCacheAutoRefresh()
  })

  onDeactivated(() => {
    stopCacheAutoRefresh()
  })

  onUnmounted(() => {
    stopCacheAutoRefresh()
  })

  return {
    cacheStats,
    prevCacheStats,
    cacheStatsLoading,
    clearCacheLoading,
    clearCacheMessage,
    clearCacheError,
    cacheClearModelAlias,
    cacheClearUserId,
    cacheAutoRefreshEnabled,
    cacheAutoRefreshIntervalMs,
    challengeMetrics,
    challengeSuccessRateText,
    challengeActorMismatchRateText,
    cacheLastRefreshedText,
    loadCacheStats,
    toggleCacheAutoRefresh,
    setCacheAutoRefreshInterval,
    resetCacheMonitorPrefs,
    handleClearInferenceCache,
  }
}
